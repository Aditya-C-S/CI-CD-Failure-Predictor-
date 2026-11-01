"""Adapter for Metadata-Pipeline integration."""
import sys
import os
from pathlib import Path
from typing import Dict, Optional

# Add Metadata-Pipeline to path
# Resolves relative to ORC project root, assuming standard layout:
# cicd/
#   ├─ orc/
#   │   └─ src/adapters/metadata_adapter.py  (this file)
#   └─ Metadata-Pipeline-main/
def _resolve_metadata_pipeline_root():
    """Find Metadata-Pipeline-main relative to this file."""
    orc_dir = Path(__file__).parent.parent.parent  # orc/
    parent_dir = orc_dir.parent  # cicd/
    metadata_pipeline = parent_dir / "Metadata-Pipeline-main"
    
    if not metadata_pipeline.exists():
        raise RuntimeError(
            f"Cannot find Metadata-Pipeline-main. Expected at: {metadata_pipeline}\n"
            f"Ensure the project structure is:\n"
            f"  cicd/\n"
            f"    ├─ orc/\n"
            f"    └─ Metadata-Pipeline-main/\n"
        )
    return metadata_pipeline

METADATA_PIPELINE_ROOT = _resolve_metadata_pipeline_root()
sys.path.insert(0, str(METADATA_PIPELINE_ROOT))

from Inference_Engine.predictor_service import PredictorService, create_feature_dataframe
from Metadata_Extractor.core.git_engine import (
    sync_repo_cache, get_churn_metrics, get_repo_git_metrics
)
from Metadata_Extractor.core.static_analyzer import analyze_workspace
from Metadata_Extractor.core.github_api import get_github_metadata
from Metadata_Extractor.core.ci_analyzer import get_ci_metrics
from Metadata_Extractor.schema.normalizer import normalize_features

from ..errors import PredictionException


class MetadataAdapter:
    """Bridge to Metadata-Pipeline for risk prediction."""
    def __init__(self, github_token: str, source_repo_path: str = None):
        self.github_token = github_token
        # Optional path to source repository for local-only commits
        self.source_repo_path = source_repo_path
        try:
            self.predictor = PredictorService()
        except Exception as e:
            raise PredictionException(f"Failed to initialize PredictorService: {e}") from e

    def predict(self, owner: str, repo: str, target_sha: str) -> Dict:
        """
        Predict commit risk for a given commit.
        
        Args:
            owner: Repository owner
            repo: Repository name
            target_sha: Target commit SHA (must exist in repository or available locally)
        
        Returns:
            Dict with prediction results including failure_probability (normalized to [0.0, 1.0]),
            verdict, shap_drivers, features
        
        Raises:
            PredictionException: If commit cannot be resolved or prediction fails
        """
        try:
            # Sync repository cache and checkout target commit
            # Pass source_repo_path to allow analysis of local-only commits
            repo_path, cache_status = sync_repo_cache(
                owner, repo, target_sha, self.github_token,
                source_repo_path=self.source_repo_path
            )
            
            # Extract all 38 features
            features_dict = self._extract_features(owner, repo, target_sha, repo_path)
            
            # Create feature DataFrame
            feature_df = create_feature_dataframe(features_dict)
            
            # Run prediction
            prediction_result = self.predictor.predict_commit_risk(feature_df)
            
            # Validate and normalize probability scale
            failure_prob = prediction_result.get("failure_probability", 0.0)
            if not isinstance(failure_prob, (int, float)):
                raise PredictionException(
                    f"Invalid failure_probability type: {type(failure_prob)}, expected float"
                )
            
            # Normalize to [0.0, 1.0]
            failure_prob = float(failure_prob)
            if failure_prob < 0.0 or failure_prob > 1.0:
                raise PredictionException(
                    f"failure_probability out of range [0.0, 1.0]: {failure_prob}"
                )
            
            # Augment with metadata
            prediction_result.update({
                "owner": owner,
                "repo": repo,
                "sha": target_sha,
                "short_sha": target_sha[:7],
                "cache_status": cache_status,
                "features": features_dict,
            })
            return prediction_result
        
        except PredictionException:
            raise
        except RuntimeError as e:
            # RuntimeError from sync_repo_cache means commit resolution failed
            raise PredictionException(f"Commit resolution failed for {owner}/{repo}@{target_sha}: {e}") from e
        except Exception as e:
            raise PredictionException(f"Prediction failed for {owner}/{repo}@{target_sha}: {e}") from e

    def _extract_features(self, owner: str, repo: str, target_sha: str, repo_path: str) -> Dict:
        """Extract all 38 features for a commit."""
        all_features = {}
        try:
            all_features.update(get_churn_metrics(repo_path, target_sha))
            all_features.update(get_repo_git_metrics(repo_path, target_sha))
            all_features.update(analyze_workspace(repo_path))
            all_features.update(get_github_metadata(owner, repo, target_sha))
            all_features.update(get_ci_metrics(owner, repo, target_sha))
            
            # Normalize to ensure exact 38 features
            normalized_df = normalize_features(all_features)
            return normalized_df.iloc[0].to_dict()
        except Exception as e:
            raise PredictionException(f"Feature extraction failed for {target_sha}: {e}") from e
