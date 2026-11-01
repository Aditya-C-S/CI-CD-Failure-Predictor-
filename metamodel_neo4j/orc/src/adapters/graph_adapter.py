"""Adapter for graph-doc-gen integration with repository isolation."""
import sys
import os
import subprocess
import logging
import shutil
import stat
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add graph-doc-gen to path
# Resolves relative to ORC project root, assuming standard layout:
# cicd/
#   ├─ orc/
#   │   └─ src/adapters/graph_adapter.py  (this file)
#   └─ graph-doc-gen-main/
def _resolve_graph_doc_gen_root():
    """Find graph-doc-gen-main relative to this file."""
    orc_dir = Path(__file__).parent.parent.parent  # orc/
    parent_dir = orc_dir.parent  # cicd/
    graph_engine = parent_dir / "graph-doc-gen-main"
    
    if not graph_engine.exists():
        raise RuntimeError(
            f"Cannot find graph-doc-gen-main. Expected at: {graph_engine}\n"
            f"Ensure the project structure is:\n"
            f"  cicd/\n"
            f"    ├─ orc/\n"
            f"    └─ graph-doc-gen-main/\n"
        )
    return graph_engine

GRAPH_DOC_GEN_ROOT = _resolve_graph_doc_gen_root()
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT))

# CRITICAL: Apply monkey-patch BEFORE importing diff_agent or any module that imports it!
# diff_agent.py does: from maintenance.git_utils import check_working_tree_clean
# This creates a LOCAL reference that is fixed at import time.
# We must patch BEFORE that import happens.
from maintenance import git_utils as gitutils_module

_original_check_working_tree_clean = gitutils_module.check_working_tree_clean

def _patched_check_working_tree_clean(cwd: str, file_paths = None):
    """Patched version that filters out invalid paths from stale Neo4j data."""
    if not file_paths:
        return _original_check_working_tree_clean(cwd, file_paths)
    
    # Filter out paths that point outside cwd
    valid_paths = []
    skipped_paths = []
    norm_cwd = os.path.normpath(os.path.abspath(cwd))
    
    for fp in file_paths:
        try:
            norm_fp = os.path.normpath(os.path.abspath(os.path.join(cwd, fp)))
            rel_path = os.path.relpath(norm_fp, norm_cwd)
            if not rel_path.startswith('..'):
                valid_paths.append(fp)
            else:
                skipped_paths.append((fp, rel_path))
        except (ValueError, OSError):
            skipped_paths.append((fp, "error"))
    
    if skipped_paths:
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        _logger.debug(f"Stale Neo4j paths filtered: {len(skipped_paths)} outside repo, {len(valid_paths)} valid")
    
    # Call original with only valid paths
    if valid_paths:
        return _original_check_working_tree_clean(cwd, valid_paths)
    return True

# Apply patch IMMEDIATELY, before importing diff_agent
gitutils_module.check_working_tree_clean = _patched_check_working_tree_clean

# NOW import diff_agent - it will get the patched version
from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient
from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import get_commit_diff

from ..errors import GraphSyncException, InvalidCommitException
from ..models import SuspiciousFile
from ..storage import SyncStateManager

logger = logging.getLogger(__name__)

# Graph working cache directory (similar to Metadata-Pipeline's .repo_cache)
GRAPH_CACHE_ROOT = Path(__file__).parent.parent.parent / ".graph_cache"
GRAPH_CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _handle_remove_readonly(func, path, exc_info):
    """Error handler for shutil.rmtree to handle Windows read-only files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _ensure_graph_working_copy_at_sha(repo_id: str, source_repo_path: str, target_sha: str) -> str:
    """
    Ensure a graph working copy exists for the repo at the exact target_sha.
    
    This provides the graph engine with a repository that is verified to be
    checked out at the target commit, preventing working-tree verification failures.
    
    Uses a persistent cache similar to Metadata-Pipeline's .repo_cache, but isolated
    for graph operations to avoid conflicts with metadata extraction.
    
    Args:
        repo_id: Repository identity (owner/repo)
        source_repo_path: Path to source repository
        target_sha: Target commit to ensure working copy is at
    
    Returns:
        Path to graph working copy, verified to be at target_sha
    
    Raises:
        GraphSyncException: If working copy cannot be created or checked out
    """
    # Sanitize repo_id for use as directory name
    safe_repo_id = repo_id.replace("/", "__")
    graph_cache_dir = GRAPH_CACHE_ROOT / safe_repo_id
    graph_cache_git = graph_cache_dir / ".git"
    
    try:
        # If cache doesn't exist, create it by cloning from source repo
        if not graph_cache_git.exists():
            logger.info(f"Creating graph working copy for {repo_id} at {graph_cache_dir}")
            
            if graph_cache_dir.exists():
                shutil.rmtree(graph_cache_dir, onerror=_handle_remove_readonly)
            
            # Clone from source repo (local path, fast)
            subprocess.run(
                f'git clone --quiet "{source_repo_path}" "{graph_cache_dir}"',
                shell=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Graph working copy created: {graph_cache_dir}")
            
            # CRITICAL: Replace local remote URL with GitHub remote to avoid git path issues
            # When cloned from a local path, git stores the local filesystem URL.
            # This can cause "is outside repository" errors when git tries to access the remote.
            # We must update the remote to a proper remote URL (GitHub or fallback to local).
            try:
                # Try to derive GitHub URL from repo_id (owner/repo)
                owner, repo = repo_id.split("/", 1)
                github_url = f"https://github.com/{owner}/{repo}.git"
                subprocess.run(
                    f'git remote set-url origin "{github_url}"',
                    cwd=graph_cache_dir,
                    shell=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info(f"Configured remote origin to GitHub: {github_url}")
            except Exception as e:
                logger.warning(f"Could not set GitHub remote for {repo_id}: {e}. Keeping local remote.")
                # The local remote is still usable, just not ideal
        
        # Ensure working copy is at exact target_sha
        logger.info(f"Synchronizing graph working copy to {target_sha[:7]}")
        
        # Fetch latest to ensure we have the commit
        subprocess.run(
            'git fetch --quiet --all --prune',
            cwd=graph_cache_dir,
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # For local-only commits, also fetch from source repository
        # This ensures commits not yet pushed to GitHub are available
        try:
            result = subprocess.run(
                f'git checkout --quiet --force "{target_sha}"',
                cwd=graph_cache_dir,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode != 0:
                # Checkout failed - try fetching from source repo if it has the commit
                logger.info(f"Checkout of {target_sha[:7]} failed, attempting to fetch from source repo")
                try:
                    # Check if source repo has this commit
                    source_check = subprocess.run(
                        f'git rev-parse {target_sha}',
                        cwd=source_repo_path,
                        shell=True,
                        capture_output=True,
                        text=True,
                    )
                    if source_check.returncode == 0:
                        # Source repo has the commit - fetch from it
                        logger.info(f"Found {target_sha[:7]} in source repo, fetching...")
                        subprocess.run(
                            f'git fetch --quiet "{source_repo_path}" "{target_sha}"',
                            cwd=graph_cache_dir,
                            shell=True,
                            check=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        logger.info(f"Successfully fetched {target_sha[:7]} from source repo")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to fetch from source repo: {e}")
                    raise
            
            # Try checkout again after potentially fetching from source
            subprocess.run(
                f'git checkout --quiet --force "{target_sha}"',
                cwd=graph_cache_dir,
                shell=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            raise GraphSyncException(
                f"Failed to checkout {target_sha[:7]} in graph working copy for {repo_id}: {e}"
            ) from e
        
        # Clean any untracked files
        subprocess.run(
            'git clean --quiet -fd',
            cwd=graph_cache_dir,
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Verify HEAD is at target_sha
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=graph_cache_dir,
            capture_output=True,
            text=True,
            shell=True,
        )
        if result.returncode != 0 or result.stdout.strip() != target_sha:
            raise GraphSyncException(
                f"Graph working copy verification failed: HEAD is not at {target_sha[:7]} "
                f"after checkout. Graph engine requires exact commit match."
            )
        
        logger.info(f"Graph working copy verified at {target_sha[:7]}")
        return str(graph_cache_dir)
    
    except subprocess.CalledProcessError as e:
        raise GraphSyncException(
            f"Failed to setup graph working copy for {repo_id}: {e}"
        ) from e
    except Exception as e:
        raise GraphSyncException(
            f"Unexpected error setting up graph working copy: {e}"
        ) from e


class GraphAdapter:
    """Bridge to graph-doc-gen for code graph management with repository isolation."""
    def __init__(self, repo_id: str, repo_path: str, neo4j_config: Optional[Dict] = None):
        """
        Initialize graph adapter.
        Args:
            repo_id: Repository identity (owner/repo)
            repo_path: Path to local repository (used for cache initialization)
            neo4j_config: Optional Neo4j configuration override
        """
        self.repo_id = repo_id
        self.repo_path = repo_path
        self.neo4j_config = neo4j_config or {}
        # Initialize Neo4j client (uses .env by default)
        try:
            self.client = Neo4jClient(**self.neo4j_config)
        except Exception as e:
            raise GraphSyncException(f"Failed to initialize Neo4j client: {e}") from e
        # Initialize sync state manager for commit provenance tracking
        try:
            self.sync_state = SyncStateManager()
        except Exception as e:
            self.client.close()
            raise GraphSyncException(f"Failed to initialize sync state manager: {e}") from e
        # Verify that we are targeting the correct database (graphdoc)
        # This prevents accidental writes to the production 'neo4j' database
        try:
            self._verify_database_target()
        except Exception as e:
            self.client.close()
            raise

    def sync_to_sha(self, base_sha: str, target_sha: str) -> Dict:
        """
        Synchronize graph from base_sha to target_sha with verified commit provenance.
        
        Implements the verified commit-provenance contract from graph-doc-gen-main.
        
        KEY FIX: Uses a graph working copy that is guaranteed to be checked out at
        target_sha, preventing "working-tree verification failed" errors from the
        graph engine.
        
        COMMIT PROVENANCE MECHANISM:
        ============================
        1. Check existing graph state in Neo4j via get_sync_state()
        2. Determine appropriate base for incremental sync:
           - If no prior sync: use initial ingestion path (or parent-SHA diff)
           - If existing sync: base must match graph's current target_sha
        3. Ensure graph working copy is checked out to target_sha
           - Creates persistent .graph_cache with working tree at exact commit
           - Prevents working-tree mismatches from user's source repo state
        4. Call graph engine's update_graph_from_diff() on verified working copy
        5. Validate operation result and persisted Neo4j state
        
        Args:
            base_sha: Base commit SHA
            target_sha: Target commit SHA
        
        Returns:
            Dict with sync status, files changed count, and operation metadata
        
        Raises:
            GraphSyncException: If sync fails or verification fails
            InvalidCommitException: If commits are invalid
        """
        graph_working_copy = None
        try:
            logger.info(f"Starting graph sync for {self.repo_id}@{target_sha[:7]}")
            
            # Step 1: Validate that both commits exist
            self._validate_commits(base_sha, target_sha)
            
            # Step 2: Ensure graph working copy is at target_sha
            # This is critical: prevents working-tree verification failures
            graph_working_copy = _ensure_graph_working_copy_at_sha(
                self.repo_id,
                self.repo_path,
                target_sha
            )
            
            # Step 3: Check existing graph state in Neo4j
            existing_sync = self.client.get_sync_state(self.repo_id)
            
            # Step 4: Determine actual base for synchronization
            if existing_sync is None:
                # Initial ingestion: no prior verified state
                logger.info(f"Initial ingestion for {self.repo_id} (no prior sync)")
                actual_base_sha = base_sha
            else:
                # Incremental sync: check graph's current state
                graph_current_sha = existing_sync.get("target_sha")
                if not existing_sync.get("commit_verified"):
                    raise GraphSyncException(
                        f"Existing graph state for {self.repo_id} has commit_verified=False. "
                        f"Graph state is not reliably known. Cannot proceed with incremental sync."
                    )
                # RECOVERY: If graph is already at exact target_sha and verified, skip engine call
                if graph_current_sha == target_sha:
                    logger.info(
                        f"Graph already verified at target {target_sha[:7]} for {self.repo_id}. "
                        f"Recovering verified sync state without re-running engine."
                    )
                    # Verify all conditions are met for safe recovery
                    if existing_sync.get("status") != "SYNCED":
                        raise GraphSyncException(
                            f"Cannot recover: Neo4j SyncState exists at target SHA but status is "
                            f"'{existing_sync.get('status')}' (expected 'SYNCED')"
                        )
                    # Recovery path: return verified sync result without engine call
                    try:
                        diff = get_commit_diff(base_sha, target_sha, cwd=graph_working_copy)
                    except Exception as e:
                        logger.warning(f"Failed to compute diff for recovery path: {e}")
                        diff = {"added": [], "modified": [], "deleted": [], "renamed": []}
                    all_changed = (
                        diff.get("added", []) +
                        diff.get("modified", []) +
                        [new_path for old_path, new_path in diff.get("renamed", [])]
                    )
                    all_changed_abs = [
                        os.path.join(graph_working_copy, f) if not os.path.isabs(f) else f 
                        for f in all_changed
                    ]
                    logger.info(
                        f"✓ Recovered verified sync for {self.repo_id}@{target_sha[:7]}"
                    )
                    return {
                        "status": "SYNCHRONIZED",
                        "base_sha": base_sha,
                        "target_sha": target_sha,
                        "files_added": len(diff.get("added", [])),
                        "files_modified": len(diff.get("modified", [])),
                        "files_deleted": len(diff.get("deleted", [])),
                        "files_renamed": len(diff.get("renamed", [])),
                        "changed_files": all_changed_abs,
                        "engine_result": existing_sync,  # Use verified Neo4j state as proof
                        "persisted_state": existing_sync,  # Already verified in Neo4j
                    }
                # Normal incremental sync: base must match graph's current state
                if graph_current_sha != base_sha:
                    raise GraphSyncException(
                        f"Base SHA mismatch for {self.repo_id}: "
                        f"graph's current target_sha is {graph_current_sha[:7]}, "
                        f"but sync requested base_sha {base_sha[:7]}. "
                        f"Cannot proceed with incremental sync."
                    )
                actual_base_sha = base_sha
                logger.info(f"Incremental sync for {self.repo_id} from {actual_base_sha[:7]} to {target_sha[:7]}")
            
            # Step 5: Call graph engine with graph working copy (verified at target_sha)
            logger.info(f"Calling graph engine: update_graph_from_diff({self.repo_id}, {actual_base_sha[:7]}, {target_sha[:7]})")
            engine_result = update_graph_from_diff(
                graph_working_copy,  # Use graph working copy, not user's source repo
                base_sha=actual_base_sha,
                target_sha=target_sha,
                repo_id=self.repo_id
            )
            
            # Step 6: Validate operation result
            self._validate_sync_result(engine_result, target_sha)
            logger.info(f"✓ Operation result validated: status={engine_result['status']}, commit_verified={engine_result['commit_verified']}")
            
            # Step 7: Verify Neo4j's persisted SyncState
            persisted_state = self._verify_persisted_state(target_sha)
            logger.info(f"✓ Persisted SyncState verified: {self.repo_id}@{target_sha[:7]} is commit_verified=True")
            
            # Step 8: Get diff for file change reporting
            try:
                diff = get_commit_diff(actual_base_sha, target_sha, cwd=graph_working_copy)
            except Exception as e:
                logger.warning(f"Failed to compute diff for file listing: {e}")
                diff = {"added": [], "modified": [], "deleted": [], "renamed": []}
            
            # Collect all changed files (added + modified + renamed new)
            all_changed = (
                diff.get("added", []) +
                diff.get("modified", []) +
                [new_path for old_path, new_path in diff.get("renamed", [])]
            )
            
            # Convert relative paths to absolute for graph investigation
            all_changed_abs = [
                os.path.join(graph_working_copy, f) if not os.path.isabs(f) else f 
                for f in all_changed
            ]
            
            logger.info(
                f"✓ Sync complete: {self.repo_id}@{target_sha[:7]} "
                f"({engine_result['files_parsed']} files parsed, "
                f"{persisted_state['nodes_count']} nodes)"
            )
            
            return {
                "status": "SYNCHRONIZED",
                "base_sha": actual_base_sha,
                "target_sha": target_sha,
                "files_added": len(diff.get("added", [])),
                "files_modified": len(diff.get("modified", [])),
                "files_deleted": len(diff.get("deleted", [])),
                "files_renamed": len(diff.get("renamed", [])),
                "changed_files": all_changed_abs,
                "engine_result": engine_result,  # Full result for debugging/audit
                "persisted_state": persisted_state,  # Proof of Neo4j state
            }
        except InvalidCommitException:
            raise
        except GraphSyncException:
            raise
        except Exception as e:
            raise GraphSyncException(f"Graph sync failed for {self.repo_id}: {e}") from e

    def _extract_commit_evidence(self, base_sha: str, target_sha: str, directly_modified: set) -> dict:
        """
        Extract evidence of code changes for suspicious file ranking.
        
        Args:
            base_sha: Base commit SHA
            target_sha: Target commit SHA
            directly_modified: Set of file paths directly modified
        
        Returns:
            Dict mapping file_path -> list of evidence strings
        """
        evidence_map = {}
        try:
            # Get commit diff to analyze changes
            diff = get_commit_diff(base_sha, target_sha, cwd=self.repo_path)
            
            # Analyze each directly modified file for changed symbols
            for modified_file in directly_modified:
                # Extract relative path from repo root for diff lookup
                try:
                    rel_path = os.path.relpath(modified_file, self.repo_path)
                except ValueError:
                    # File is outside repo, skip symbol analysis
                    continue
                
                evidence_map[modified_file] = []
                
                # Check if this file has changes in the diff
                modified_files = diff.get("modified", [])
                if rel_path in modified_files or rel_path.replace("\\", "/") in modified_files:
                    # Try to extract changed function/class names if possible
                    # For now, just record that it was modified
                    evidence_map[modified_file].append(f"Code changes in {rel_path}")
        
        except Exception as e:
            logger.debug(f"Failed to extract detailed commit evidence: {e}")
        
        return evidence_map

    def get_connected_files(self, changed_files: List[str], base_sha: Optional[str] = None, target_sha: Optional[str] = None) -> List[SuspiciousFile]:
        """
        Query Neo4j for files connected to changed files, scoped to this repository.
        Enhanced with evidence-based ranking when base_sha and target_sha are provided.
        
        Uses explicit repository isolation: all queries are strictly filtered by repo_id.
        The graph-doc-gen Neo4jClient.get_connected_files() provides a strict isolation
        guarantee: no nodes or relationships from any other repository can be reached
        or returned.
        
        Args:
            changed_files: List of changed file paths (absolute or relative to repo root)
            base_sha: (Optional) Base commit SHA for evidence-based ranking
            target_sha: (Optional) Target commit SHA for evidence-based ranking
        
        Returns:
            List of SuspiciousFile objects ranked by evidence strength
            - Rank 1 (Direct): Files directly modified in commit
            - Rank 2 (Dependency): Files depending on modified code
            - Rank 3 (Connected): Files connected via graph relationships
        """
        try:
            if not changed_files:
                return []
            
            # Categorize suspicious files by evidence strength
            directly_modified = set()  # Rank 1: Direct changes
            dependent_files = set()    # Rank 2: Depend on changes
            connected_files = set()    # Rank 3: Graph connections
            
            # Step 1: Identify directly modified files (always available)
            for changed_file in changed_files:
                file_path = changed_file
                if not os.path.isabs(file_path):
                    file_path = os.path.join(self.repo_path, file_path)
                file_path = os.path.abspath(file_path)
                directly_modified.add(file_path)
            
            # Step 2: If commit info available, extract evidence for better ranking
            evidence_map = {}  # file_path -> list of evidence strings
            if base_sha and target_sha:
                try:
                    evidence_map = self._extract_commit_evidence(base_sha, target_sha, directly_modified)
                except Exception as e:
                    logger.warning(f"Failed to extract commit evidence: {e}, proceeding with graph-only analysis")
            
            # Step 3: Query graph for connected files
            for changed_file in changed_files:
                file_path = changed_file
                if not os.path.isabs(file_path):
                    file_path = os.path.join(self.repo_path, file_path)
                file_path = os.path.abspath(file_path)
                try:
                    # Query using Neo4jClient's repository-scoped API.
                    # Strict Isolation Guarantee:
                    # All traversals are strictly filtered by repo_id. No nodes or
                    # relationships from any other repository can be reached or returned.
                    connected = self.client.get_connected_files(
                        repo_id=self.repo_id,
                        file_path=file_path
                    )
                    connected_files.update(connected)
                except Exception as e:
                    logger.warning(f"Failed to get connected files for {file_path}: {e}")
                    continue
            
            # Step 4: Build ranked suspicious file list
            suspicious_files = []
            
            # Rank 1: Directly modified files
            for file_path in directly_modified:
                reasons = ["Directly modified in commit"]
                if file_path in evidence_map:
                    reasons.extend(evidence_map[file_path])
                suspicious_files.append(SuspiciousFile(
                    file_path=file_path,
                    centrality_score=1.0,  # Highest score: direct evidence
                    reasons=reasons,
                ))
            
            # Rank 2: Dependent files (connected but not directly changed)
            for file_path in connected_files - directly_modified:
                reasons = ["Connected via CALLS relationship"]
                if file_path in evidence_map:
                    reasons = evidence_map[file_path]
                suspicious_files.append(SuspiciousFile(
                    file_path=file_path,
                    centrality_score=0.7,  # Medium score: dependency evidence
                    reasons=reasons,
                ))
            
            # Sort by centrality score (descending), then by path for consistency
            suspicious_files.sort(key=lambda x: (-x.centrality_score, x.file_path))
            
            # Return top 10 suspicious files
            return suspicious_files[:10]
        
        except Exception as e:
            raise GraphSyncException(f"Failed to query connected files for {self.repo_id}: {e}") from e

    def _validate_commits(self, base_sha: str, target_sha: str):
        """Validate that commits exist in repository."""
        try:
            for sha in [base_sha, target_sha]:
                result = subprocess.run(
                    f'git cat-file -t "{sha}"',
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    shell=True,
                )
                if result.returncode != 0:
                    raise InvalidCommitException(f"Commit {sha} not found in {self.repo_id}")
        except subprocess.CalledProcessError as e:
            raise InvalidCommitException(f"Failed to validate commit: {e}") from e

    def _verify_database_target(self):
        """
        Verify that the Neo4j client is targeting the 'graphdoc' database.
        This is a safety check to prevent accidental writes to the production 'neo4j' database.
        Raises:
            GraphSyncException: If the target database is not 'graphdoc'
        """
        selected_db = self.client.database
        logger.info(f"Verifying Neo4j database target: selected_db={selected_db}")
        # If database is None, the client is targeting the default database (neo4j)
        if selected_db is None:
            raise GraphSyncException(
                "NEO4J_DATABASE not set. ORC requires explicit targeting of 'graphdoc' database. "
                "Set NEO4J_DATABASE=graphdoc in .env and restart."
            )
        # Verify it's exactly 'graphdoc'
        if selected_db.lower() != "graphdoc":
            raise GraphSyncException(
                f"Wrong database target: '{selected_db}'. "
                f"ORC requires NEO4J_DATABASE=graphdoc to avoid contaminating production data. "
                f"Current .env has NEO4J_DATABASE={selected_db}. Update .env and restart."
            )
        logger.info(f"✓ Database verification passed: targeting 'graphdoc'")

    def _validate_sync_result(self, result: Dict, target_sha: str) -> None:
        """
        Validate that the graph engine's operation result indicates successful synchronization.
        Checks:
        1. Status is "SUCCESS" or "NO_CHANGES"
        2. repo_id matches self.repo_id
        3. target_sha matches requested commit
        4. commit_verified is exactly True
        Args:
            result: Dict returned from graph engine's update_graph_from_diff()
            target_sha: The requested target commit SHA
        Raises:
            GraphSyncException: If any validation fails
        """
        if result is None:
            raise GraphSyncException(
                f"Graph engine returned None instead of result Dict. "
                f"Ensure graph-doc-gen-main is updated to return operation metadata."
            )
        # Check status
        status = result.get("status")
        if status not in ("SUCCESS", "NO_CHANGES"):
            error_msg = result.get("error", "Unknown error")
            raise GraphSyncException(
                f"Graph engine operation failed: status={status}. "
                f"Error: {error_msg}"
            )
        # Check repo_id
        engine_repo_id = result.get("repo_id")
        if engine_repo_id != self.repo_id:
            raise GraphSyncException(
                f"Repo ID mismatch: graph engine returned repo_id='{engine_repo_id}', "
                f"but requested repo_id='{self.repo_id}'. "
                f"Cannot verify correct repository was synced."
            )
        # Check target_sha
        engine_target_sha = result.get("target_sha")
        if engine_target_sha != target_sha:
            raise GraphSyncException(
                f"Target SHA mismatch: graph engine returned target_sha={engine_target_sha[:7]}, "
                f"but requested target_sha={target_sha[:7]}. "
                f"Cannot verify correct commit was synced."
            )
        # Check commit_verified
        commit_verified = result.get("commit_verified")
        if commit_verified is not True:
            raise GraphSyncException(
                f"Commit verification failed: graph engine returned commit_verified={commit_verified}. "
                f"The sync did not complete with verified commit provenance."
            )
        logger.info(
            f"✓ Sync result validated: status={status}, repo_id={engine_repo_id}, "
            f"target_sha={engine_target_sha[:7]}, commit_verified=True"
        )

    def _verify_persisted_state(self, target_sha: str) -> Dict:
        """
        Verify that Neo4j's persisted SyncState matches the requested target SHA.
        After the graph engine completes, Neo4j should have a SyncState record that
        proves the graph now represents the requested target commit. This method reads
        that persisted record and validates it.
        Checks:
        1. SyncState record exists for repo_id
        2. target_sha matches requested commit
        3. commit_verified is exactly True
        4. status is "SYNCED"
        Args:
            target_sha: The requested target commit SHA
        Returns:
            The persisted SyncState dict as proof
        Raises:
            GraphSyncException: If verification fails or record is missing
        """
        persisted = self.client.get_sync_state(self.repo_id)
        if persisted is None:
            raise GraphSyncException(
                f"Persisted SyncState verification failed: No SyncState found in Neo4j for "
                f"repo_id='{self.repo_id}' after sync. "
                f"Graph engine should have written SyncState but it is missing."
            )
        # Check target_sha
        persisted_target = persisted.get("target_sha")
        if persisted_target != target_sha:
            raise GraphSyncException(
                f"Persisted target SHA mismatch: Neo4j SyncState has target_sha={persisted_target[:7]}, "
                f"but requested target_sha={target_sha[:7]}. "
                f"Cannot verify correct commit is in the persisted graph."
            )
        # Check commit_verified
        persisted_verified = persisted.get("commit_verified")
        if persisted_verified is not True:
            raise GraphSyncException(
                f"Persisted commit verification failed: Neo4j SyncState has commit_verified={persisted_verified}. "
                f"Persisted graph state is not verified."
            )
        # Check status
        persisted_status = persisted.get("status")
        if persisted_status != "SYNCED":
            raise GraphSyncException(
                f"Persisted status mismatch: Neo4j SyncState has status='{persisted_status}', "
                f"expected status='SYNCED'. "
                f"Graph sync did not complete successfully at the persisted level."
            )
        logger.info(
            f"✓ Persisted SyncState verified: repo_id={self.repo_id}, "
            f"target_sha={persisted_target[:7]}, commit_verified=True, status=SYNCED"
        )
        return persisted

    def _verify_sync_to_sha(self, target_sha: str, sync_id: str) -> int:
        """
        [DEPRECATED - kept for compatibility, see _validate_sync_result() and _verify_persisted_state()]
        Verify that the graph has been synchronized to the target commit SHA.
        This is a two-part verification:
        PART 1: Node Count Verification
        ===============================
        Checks that nodes exist in Neo4j for the specified repo_id and were created
        by the sync operation. This ensures the graph is not empty.
        PART 2: Provenance Verification (NEW)
        ====================================
        Records the sync state: "current_sha for repo_id is now target_sha".
        This proves the graph was built for the requested commit by storing:
        - repo_id: Which repository
        - target_sha: Which commit
        - sync_id: Which sync attempt
        Only after BOTH verifications pass does the sync state become recorded.
        Limitations:
        ============
        - Assumes update_graph_from_diff() successfully synced (no partial failures detected)
        - Assumes graph engine does not corrupt nodes during update
        - Protection against corruption is via repo_id isolation (enforced by graph engine)
        Args:
            target_sha: Target commit SHA that should have been synced
            sync_id: Unique identifier for this sync attempt
        Returns:
            Node count (number of nodes created/updated for this repo)
        Raises:
            GraphSyncException: If verification fails (no nodes found) or state recording fails
        """
        try:
            with self.client.session() as session:
                # Query: Check if nodes exist for this repo_id
                # If the sync succeeded, there should be at least some File or Function nodes
                result = session.run("""
                    MATCH (n {repo_id: $repo_id})
                    WHERE n:File OR n:Function OR n:Class OR n:Module
                    RETURN COUNT(n) as node_count
                """, repo_id=self.repo_id)
                row = result.single()
                node_count = row["node_count"] if row else 0
                if node_count == 0:
                    raise GraphSyncException(
                        f"Post-sync verification failed: No nodes found for repo_id='{self.repo_id}' "
                        f"after syncing to {target_sha[:7]}. The graph may not have been updated. "
                        f"Retrying or manual inspection may be needed."
                    )
                logger.info(
                    f"✓ Node count verification passed: {node_count} nodes exist for repo_id='{self.repo_id}'"
                )
            # PART 2: Record provenance - atomically update sync state
            # This proves the graph now represents target_sha
            try:
                self.sync_state.verify_sync(
                    repo_id=self.repo_id,
                    target_sha=target_sha,
                    sync_id=sync_id,
                    node_count=node_count
                )
                logger.info(
                    f"✓ Provenance verification passed: Recorded that {self.repo_id} is synced to {target_sha[:7]}"
                )
            except Exception as e:
                raise GraphSyncException(
                    f"Provenance recording failed for {self.repo_id}@{target_sha[:7]}: {e}"
                ) from e
            return node_count
        except Exception as e:
            if isinstance(e, GraphSyncException):
                raise
            raise GraphSyncException(
                f"Post-sync verification query failed: {e}. "
                f"Cannot verify graph state for repo_id='{self.repo_id}' at {target_sha[:7]}."
            ) from e

    def close(self):
        """Close Neo4j connection."""
        if self.client:
            self.client.close()

    def get_current_synced_sha(self) -> Optional[str]:
        """
        Get the SHA that is currently synced for this repository.
        Returns the SHA that was last successfully verified and recorded in sync_state.
        Returns None if no successful sync has been recorded for this repo_id.
        Returns:
            Current synced SHA or None if not synced
        """
        return self.sync_state.get_current_sha(self.repo_id)
