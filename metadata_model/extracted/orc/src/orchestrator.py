"""Core orchestration logic: prediction + graph sync + investigation."""

import time
import logging
from typing import Dict, Optional

from .adapters import MetadataAdapter, GraphAdapter
from .models import CommitPredictionResult, GraphSyncStatus
from .storage import CheckpointManager, CheckpointState
from .errors import (
    OrchestratorException,
    PredictionException,
    GraphSyncException,
    InvalidCommitException,
)


logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine."""
    
    def __init__(
        self,
        github_token: str,
        investigation_threshold: float = 0.50,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
    ):
        """
        Initialize orchestrator.
        
        Args:
            github_token: GitHub PAT for API access
            investigation_threshold: Risk probability threshold for suspicious-file investigation
            max_retries: Maximum number of retries for transient failures
            retry_backoff_seconds: Initial backoff time for exponential retry
        """
        self.github_token = github_token
        self.investigation_threshold = investigation_threshold
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.checkpoint_manager = CheckpointManager()
    
    def process_commit(
        self,
        repo_id: str,
        target_sha: str,
        repo_path: str,
        base_sha: Optional[str] = None,
    ) -> CommitPredictionResult:
        """
        Process a commit: predict risk, sync graph, investigate if needed, and handle retries.
        
        Args:
            repo_id: Repository identity (owner/repo)
            target_sha: Target commit SHA
            repo_path: Path to local repository
            base_sha: Base commit for graph diff (if None, will compute from target_sha~1)
        
        Returns:
            CommitPredictionResult with all details
        
        Raises:
            OrchestratorException: If processing fails
        """
        start_time = time.time()
        logger.info(f"Processing {repo_id}@{target_sha[:7]}")
        
        # Check if already processed
        cached = self.checkpoint_manager.get(repo_id, target_sha)
        if cached and cached["state"] == CheckpointState.COMPLETE:
            logger.info(f"Cache hit: {repo_id}@{target_sha[:7]} already processed")
            return self._result_from_checkpoint(repo_id, target_sha, cached)
        
        # Initialize graph adapter (always needed)
        graph_adapter = GraphAdapter(repo_id, repo_path)
        
        try:
            # Step 1: Run prediction (use cached if available)
            if cached and cached["state"] in [
                CheckpointState.PREDICTION_COMPLETE,
                CheckpointState.GRAPH_SYNC_COMPLETE,
                CheckpointState.INVESTIGATION_IN_PROGRESS,
            ]:
                logger.info(f"Reusing cached prediction from checkpoint")
                prediction_result = cached.get("prediction_result", {})
                if not prediction_result:
                    raise PredictionException("Cached checkpoint missing prediction_result")
            else:
                logger.info(f"Running prediction for {repo_id}@{target_sha[:7]}")
                # Initialize MetadataAdapter with source_repo_path to enable local commit analysis
                metadata_adapter = MetadataAdapter(self.github_token, source_repo_path=repo_path)
                prediction_result = metadata_adapter.predict(
                    repo_id.split("/")[0],
                    repo_id.split("/")[1],
                    target_sha,
                )
                
                # Save prediction to checkpoint
                self.checkpoint_manager.save(
                    repo_id,
                    target_sha,
                    CheckpointState.PREDICTION_COMPLETE,
                    prediction_result=prediction_result,
                )
                logger.info(f"Prediction complete: {prediction_result['verdict']}")
            
            # Step 2: Synchronize graph (always, regardless of risk score)
            if cached and cached["state"] in [
                CheckpointState.GRAPH_SYNC_COMPLETE,
                CheckpointState.INVESTIGATION_IN_PROGRESS,
                CheckpointState.COMPLETE,
            ]:
                graph_sync_result = cached.get("graph_sync_result")
                if graph_sync_result:
                    logger.info(f"Graph already synced, skipping sync")
                else:
                    # Legacy checkpoint without graph_sync_result; re-sync to populate it
                    logger.warning(f"Cached checkpoint missing graph_sync_result; re-syncing to restore data")
                    if base_sha is None:
                        base_sha = self._get_parent_commit(target_sha, repo_path)
                    graph_sync_result = graph_adapter.sync_to_sha(base_sha, target_sha)
                    # Update checkpoint with full result
                    self.checkpoint_manager.save(
                        repo_id,
                        target_sha,
                        CheckpointState.GRAPH_SYNC_COMPLETE,
                        prediction_result=prediction_result,
                        graph_files_changed={
                            "added": graph_sync_result["files_added"],
                            "modified": graph_sync_result["files_modified"],
                            "deleted": graph_sync_result["files_deleted"],
                            "renamed": graph_sync_result["files_renamed"],
                        },
                        graph_sync_result=graph_sync_result,
                    )
            else:
                logger.info(f"Synchronizing graph for {repo_id}@{target_sha[:7]}")
                
                # Determine base SHA if not provided
                if base_sha is None:
                    base_sha = self._get_parent_commit(target_sha, repo_path)
                
                graph_sync_result = graph_adapter.sync_to_sha(base_sha, target_sha)
                
                # Save graph sync to checkpoint
                self.checkpoint_manager.save(
                    repo_id,
                    target_sha,
                    CheckpointState.GRAPH_SYNC_COMPLETE,
                    prediction_result=prediction_result,
                    graph_files_changed={
                        "added": graph_sync_result["files_added"],
                        "modified": graph_sync_result["files_modified"],
                        "deleted": graph_sync_result["files_deleted"],
                        "renamed": graph_sync_result["files_renamed"],
                    },
                    graph_sync_result=graph_sync_result,
                )
                logger.info(f"Graph synchronized successfully")
            
            # Ensure base_sha is available for investigation phase
            if base_sha is None:
                base_sha = self._get_parent_commit(target_sha, repo_path)
            
            # Step 3: Investigate if risk meets threshold (skip if already complete)
            if cached and cached["state"] == CheckpointState.COMPLETE:
                logger.info(f"Investigation already complete, using cached result")
                suspicious_files = None  # Would need to re-query or cache
            else:
                suspicious_files = None
                if prediction_result.get("failure_probability", 0.0) >= self.investigation_threshold:
                    logger.info(f"Risk >= threshold ({self.investigation_threshold}), investigating connected files")
                    
                    # Mark investigation as in progress before making expensive query
                    self.checkpoint_manager.save(
                        repo_id,
                        target_sha,
                        CheckpointState.INVESTIGATION_IN_PROGRESS,
                        prediction_result=prediction_result,
                        graph_files_changed={
                            "added": graph_sync_result.get("files_added", 0),
                            "modified": graph_sync_result.get("files_modified", 0),
                            "deleted": graph_sync_result.get("files_deleted", 0),
                            "renamed": graph_sync_result.get("files_renamed", 0),
                        },
                    )
                    
                    # Get changed files for this commit
                    changed_files = graph_sync_result.get("changed_files", [])
                    
                    # Query for connected files with evidence-based ranking
                    suspicious_files = graph_adapter.get_connected_files(changed_files, base_sha=base_sha, target_sha=target_sha)
                    logger.info(f"Found {len(suspicious_files)} suspicious files")
                else:
                    logger.info(f"Risk < threshold, skipping investigation")
            
            # Build result
            elapsed_ms = (time.time() - start_time) * 1000
            result = CommitPredictionResult(
                repository_identity=repo_id,
                target_sha=target_sha,
                failure_probability=prediction_result.get("failure_probability", 0.0),
                verdict=prediction_result.get("verdict", "UNKNOWN"),
                shap_drivers=prediction_result.get("shap_drivers", {}),
                graph_status=GraphSyncStatus.SYNCHRONIZED,
                graph_files_changed={
                    "added": graph_sync_result.get("files_added", 0),
                    "modified": graph_sync_result.get("files_modified", 0),
                    "deleted": graph_sync_result.get("files_deleted", 0),
                    "renamed": graph_sync_result.get("files_renamed", 0),
                },
                suspicious_files=suspicious_files,
                processing_time_ms=elapsed_ms,
                features=prediction_result.get("features"),
            )
            
            # Mark final checkpoint as COMPLETE only after everything succeeds
            self.checkpoint_manager.save(
                repo_id,
                target_sha,
                CheckpointState.COMPLETE,
                prediction_result=prediction_result,
                graph_files_changed={
                    "added": graph_sync_result.get("files_added", 0),
                    "modified": graph_sync_result.get("files_modified", 0),
                    "deleted": graph_sync_result.get("files_deleted", 0),
                    "renamed": graph_sync_result.get("files_renamed", 0),
                },
                graph_sync_result=graph_sync_result,
            )
            
            logger.info(f"Processing complete in {elapsed_ms:.0f}ms")
            graph_adapter.close()
            return result
        
        except PredictionException as e:
            logger.error(f"Prediction failed: {e}")
            self.checkpoint_manager.save(
                repo_id,
                target_sha,
                CheckpointState.FAILED,
                error=str(e),
            )
            graph_adapter.close()
            raise
        
        except InvalidCommitException as e:
            logger.error(f"Invalid commit: {e}")
            self.checkpoint_manager.save(
                repo_id,
                target_sha,
                CheckpointState.FAILED,
                error=str(e),
            )
            graph_adapter.close()
            raise
        
        except GraphSyncException as e:
            logger.error(f"Graph sync failed: {e}")
            
            # Check if we can retry (reuse prediction, just retry graph sync)
            retry_count = self.checkpoint_manager.get_retry_count(repo_id, target_sha)
            if retry_count < self.max_retries:
                logger.warning(f"Retrying graph sync (attempt {retry_count + 1}/{self.max_retries})")
                self.checkpoint_manager.increment_retry_count(repo_id, target_sha)
                time.sleep(self.retry_backoff_seconds ** retry_count)
                graph_adapter.close()
                # Recurse for retry (will reuse cached prediction)
                return self.process_commit(repo_id, target_sha, repo_path, base_sha)
            else:
                logger.error(f"Graph sync failed after {self.max_retries} retries")
                self.checkpoint_manager.save(
                    repo_id,
                    target_sha,
                    CheckpointState.FAILED,
                    error=str(e),
                    retry_count=retry_count,
                )
                graph_adapter.close()
                raise
    
    def _get_parent_commit(self, target_sha: str, repo_path: str) -> str:
        """Get the parent commit SHA."""
        import subprocess
        try:
            result = subprocess.run(
                f'git rev-parse "{target_sha}~1"',
                cwd=repo_path,
                capture_output=True,
                text=True,
                shell=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                # Root commit, use empty tree
                empty_tree = subprocess.run(
                    'git hash-object -t tree /dev/null',
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    shell=True,
                )
                if empty_tree.returncode == 0:
                    return empty_tree.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to get parent commit: {e}, using target SHA")
        
        return target_sha
    
    def _result_from_checkpoint(
        self,
        repo_id: str,
        target_sha: str,
        checkpoint: Dict,
    ) -> CommitPredictionResult:
        """Reconstruct result from cached checkpoint."""
        pred = checkpoint.get("prediction_result", {})
        return CommitPredictionResult(
            repository_identity=repo_id,
            target_sha=target_sha,
            failure_probability=pred.get("failure_probability", 0.0),
            verdict=pred.get("verdict", "UNKNOWN"),
            shap_drivers=pred.get("shap_drivers", {}),
            graph_status=GraphSyncStatus.SYNCHRONIZED,
            graph_files_changed=checkpoint.get("graph_files_changed"),
            suspicious_files=None,  # Not cached; would need to re-query
            features=pred.get("features"),
        )
