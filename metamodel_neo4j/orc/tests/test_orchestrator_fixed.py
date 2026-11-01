"""Integration tests for orchestrator with regression coverage."""

import pytest
from unittest.mock import patch, MagicMock

from src.orchestrator import Orchestrator
from src.models import GraphSyncStatus
from src.errors import InvalidCommitException, GraphSyncException, PredictionException
from src.storage import CheckpointState


class TestOrchestratorBasicFlow:
    """Test basic orchestrator flow."""
    
    def test_low_risk_commit(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Test processing a low-risk commit."""
        # Setup: low-risk prediction
        low_risk_result = mock_predictor_result.copy()
        low_risk_result["failure_probability"] = 0.15
        low_risk_result["verdict"] = "FAST-TRACK"
        
        # Execute
        orchestrator = Orchestrator(github_token=mock_github_token, investigation_threshold=0.50)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = low_risk_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            
            # Get the target SHA from the repo
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert
        assert result.failure_probability == 0.15
        assert result.verdict == "FAST-TRACK"
        assert result.graph_status == GraphSyncStatus.SYNCHRONIZED
        assert result.suspicious_files is None  # Below threshold
    
    def test_high_risk_commit(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result, mock_suspicious_files):
        """Test processing a high-risk commit with investigation."""
        # Setup: high-risk prediction
        high_risk_result = mock_predictor_result.copy()
        high_risk_result["failure_probability"] = 0.72
        high_risk_result["verdict"] = "PRE-MERGE BLOCK"
        
        orchestrator = Orchestrator(github_token=mock_github_token, investigation_threshold=0.50)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = high_risk_result
            
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = mock_suspicious_files
            
            # Get target SHA
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert
        assert result.failure_probability == 0.72
        assert result.verdict == "PRE-MERGE BLOCK"
        assert result.graph_status == GraphSyncStatus.SYNCHRONIZED
        assert result.suspicious_files is not None
        assert len(result.suspicious_files) == 2
        assert result.suspicious_files[0].file_path == "src/core.py"


class TestRegressionRisk72Threshold50:
    """Regression test: 72% risk at 50% threshold should investigate."""
    
    def test_risk_72_percent_above_50_threshold(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_graph_sync_result, mock_suspicious_files):
        """Verify that 72% risk properly triggers investigation at 50% threshold."""
        high_risk = {
            "failure_probability": 0.72,
            "failure_probability_pct": 72.0,
            "raw_score": 0.72,
            "verdict": "PRE-MERGE BLOCK",
            "shap_drivers": {"positive": [], "negative": []},
            "owner": "testowner",
            "repo": "testrepo",
            "sha": "abc" * 20,
            "short_sha": "abc",
            "cache_status": "miss",
            "features": {},
        }
        
        orchestrator = Orchestrator(github_token="token", investigation_threshold=0.50)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = high_risk
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = mock_suspicious_files
            
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="owner/repo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert investigation was triggered
        assert result.failure_probability == 0.72
        assert result.suspicious_files is not None
        # Verify get_connected_files was called
        graph_instance.get_connected_files.assert_called_once()


class TestChangedFilesPropagation:
    """Test that changed files are correctly propagated to investigation."""
    
    def test_changed_files_in_sync_result(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_graph_sync_result, mock_suspicious_files):
        """Verify changed_files from graph sync result are used in investigation."""
        high_risk = mock_graph_sync_result.copy()
        high_risk["failure_probability"] = 0.75
        high_risk["verdict"] = "HIGH RISK"
        
        predictor_result = {
            "failure_probability": 0.75,
            "verdict": "HIGH RISK",
            "shap_drivers": {},
            "owner": "owner",
            "repo": "repo",
            "sha": "abc" * 20,
            "short_sha": "abc",
            "cache_status": "miss",
            "features": {},
        }
        
        orchestrator = Orchestrator(github_token="token", investigation_threshold=0.50)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = predictor_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = mock_suspicious_files
            
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="owner/repo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Verify get_connected_files was called with changed_files and base/target SHAs
        graph_instance.get_connected_files.assert_called_once()
        call_args = graph_instance.get_connected_files.call_args
        # Check that changed_files were passed as first argument
        assert call_args[0][0] == mock_graph_sync_result["changed_files"]
        # Check that base_sha and target_sha were passed as keyword arguments
        assert "base_sha" in call_args[1]
        assert "target_sha" in call_args[1]


class TestPredictionCaching:
    """Test that predictions are cached and reused on graph retry."""
    
    def test_graph_failure_reuses_prediction(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Verify that graph sync failure retries reuse cached prediction."""
        orchestrator = Orchestrator(github_token="token", max_retries=2, retry_backoff_seconds=0.01)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            graph_instance = MockGraph.return_value
            
            # First call fails, second succeeds
            call_count = [0]
            def sync_side_effect(base, target):
                call_count[0] += 1
                if call_count[0] < 2:
                    raise GraphSyncException("Network error")
                return mock_graph_sync_result
            
            graph_instance.sync_to_sha.side_effect = sync_side_effect
            graph_instance.get_connected_files.return_value = []
            
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="owner/repo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Verify predict was called only once (not twice on retry)
        assert MockMetadata.return_value.predict.call_count == 1
        # Graph sync was called twice (failed once, succeeded once)
        assert call_count[0] == 2


class TestRootCommitHandling:
    """Test that root commits (no parent) are handled correctly."""
    
    def test_root_commit_empty_tree_as_base(self, temp_checkpoint_db, temp_repo, mock_github_token, mock_predictor_result):
        """Verify root commit uses empty tree as base SHA."""
        predictor_result = mock_predictor_result.copy()
        predictor_result["failure_probability"] = 0.30
        
        orchestrator = Orchestrator(github_token="token")
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = predictor_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = {
                "status": "SYNCHRONIZED",
                "base_sha": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",  # Empty tree
                "target_sha": "abc" * 20,
                "files_added": 1,
                "files_modified": 0,
                "files_deleted": 0,
                "files_renamed": 0,
                "changed_files": ["README.md"],
            }
            
            import subprocess
            # Get the root commit (first commit has no ~1)
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="owner/repo",
                target_sha=target_sha,
                repo_path=str(temp_repo),
            )
        
        # Verify graph sync was called (empty tree as base is acceptable)
        graph_instance.sync_to_sha.assert_called_once()


class TestDuplicateProcessing:
    """Test handling of repeated commits."""
    
    def test_duplicate_commit_returns_cached(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Test that processing the same commit twice returns cached result."""
        orchestrator = Orchestrator(github_token=mock_github_token)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = []
            
            # Get target SHA
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            # First call
            result1 = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
            
            # Second call (should use cache)
            result2 = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert: predictions should match
        assert result1.failure_probability == result2.failure_probability
        assert result1.verdict == result2.verdict
        
        # Verify that predict was called only once (cached on second call)
        assert MockMetadata.return_value.predict.call_count == 1


class TestThresholdConfiguration:
    """Test investigation threshold configuration."""
    
    def test_custom_threshold(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Test that custom investigation threshold is respected."""
        # Risk is 0.42, but threshold is 0.60, so investigation should be skipped
        orchestrator = Orchestrator(
            github_token=mock_github_token,
            investigation_threshold=0.60,
        )
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            
            # Get target SHA
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert: suspicious files should be None (below threshold)
        assert result.suspicious_files is None
        # But graph should still be synced
        assert result.graph_status == GraphSyncStatus.SYNCHRONIZED


class TestErrorHandling:
    """Test error handling."""
    
    def test_invalid_commit_sha(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token):
        """Test handling of invalid commit SHA."""
        orchestrator = Orchestrator(github_token=mock_github_token)
        
        with pytest.raises(PredictionException):
            with patch("src.orchestrator.GraphAdapter"):
                orchestrator.process_commit(
                    repo_id="testowner/testrepo",
                    target_sha="invalid_sha_that_does_not_exist",
                    repo_path=str(temp_repo_with_py_file),
                )


class TestGraphSynchronization:
    """Test graph synchronization."""
    
    def test_graph_always_synced_regardless_of_risk(self, temp_checkpoint_db, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Test that graph is synchronized regardless of risk score."""
        # Create low-risk prediction
        low_risk = mock_predictor_result.copy()
        low_risk["failure_probability"] = 0.10
        
        orchestrator = Orchestrator(github_token=mock_github_token, investigation_threshold=0.50)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = low_risk
            
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = []
            
            # Get target SHA
            import subprocess
            result = subprocess.run(
                "git rev-parse HEAD",
                cwd=temp_repo_with_py_file,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
            )
            target_sha = result.stdout.strip()
            
            result = orchestrator.process_commit(
                repo_id="testowner/testrepo",
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Assert
        assert result.graph_status == GraphSyncStatus.SYNCHRONIZED
        assert result.graph_files_changed is not None
        # Verify sync was called
        graph_instance.sync_to_sha.assert_called_once()
