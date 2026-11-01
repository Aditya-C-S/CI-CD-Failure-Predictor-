"""Integration tests for orchestrator."""

import pytest
from unittest.mock import patch, MagicMock

from src.orchestrator import Orchestrator
from src.models import GraphSyncStatus
from src.errors import InvalidCommitException, GraphSyncException


class TestOrchestratorBasicFlow:
    """Test basic orchestrator flow."""
    
    def test_low_risk_commit(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
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
    
    def test_high_risk_commit(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result, mock_suspicious_files):
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


class TestDuplicateProcessing:
    """Test handling of repeated commits."""
    
    def test_duplicate_commit_returns_cached(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
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
    
    def test_custom_threshold(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
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


class TestCheckpointManagement:
    """Test checkpoint storage and retrieval."""
    
    def test_checkpoint_persists_across_calls(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
        """Test that checkpoints persist and are retrieved on repeated calls."""
        from src.storage import CheckpointManager, CheckpointState
        
        checkpoint_mgr = CheckpointManager()
        repo_id = "testowner/testrepo"
        target_sha = "abc123def456" * 3
        
        # Save checkpoint
        checkpoint_mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result=mock_predictor_result,
            graph_files_changed={"added": 2, "modified": 3, "deleted": 1, "renamed": 0},
        )
        
        # Retrieve checkpoint
        checkpoint = checkpoint_mgr.get(repo_id, target_sha)
        
        # Assert
        assert checkpoint is not None
        assert checkpoint["state"] == CheckpointState.COMPLETE
        assert checkpoint["prediction_result"]["failure_probability"] == 0.42
        assert checkpoint["graph_files_changed"]["added"] == 2
        
        # Cleanup
        checkpoint_mgr.clear(repo_id, target_sha)


class TestErrorHandling:
    """Test error handling."""
    
    def test_invalid_commit_sha(self, temp_repo_with_py_file, mock_github_token):
        """Test handling of invalid commit SHA."""
        orchestrator = Orchestrator(github_token=mock_github_token)
        
        # Invalid SHA will fail in metadata adapter (tries to sync repo cache)
        # which raises PredictionException. That's acceptable error handling.
        from src.errors import PredictionException
        
        with pytest.raises(PredictionException):
            with patch("src.orchestrator.GraphAdapter"):
                orchestrator.process_commit(
                    repo_id="testowner/testrepo",
                    target_sha="invalid_sha_that_does_not_exist",
                    repo_path=str(temp_repo_with_py_file),
                )


class TestGraphSynchronization:
    """Test graph synchronization."""
    
    def test_graph_always_synced_regardless_of_risk(self, temp_repo_with_py_file, mock_github_token, mock_predictor_result, mock_graph_sync_result):
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
