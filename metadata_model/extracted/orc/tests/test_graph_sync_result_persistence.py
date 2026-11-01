"""Regression tests for graph_sync_result persistence fix (Phase 2)."""

import pytest
from unittest.mock import patch, MagicMock
from src.orchestrator import Orchestrator
from src.storage import CheckpointManager, CheckpointState
from src.models import GraphSyncStatus
from src.errors import GraphSyncException


class TestGraphSyncResultPersistenceInOrchestrator:
    """Test that graph_sync_result is correctly persisted through orchestrator."""
    
    def test_successful_sync_persists_graph_sync_result_at_graph_sync_complete(
        self, temp_repo_with_py_file, mock_github_token, mock_predictor_result
    ):
        """Test that GRAPH_SYNC_COMPLETE checkpoint contains graph_sync_result."""
        repo_id = "test/repo"
        orchestrator = Orchestrator(github_token=mock_github_token)
        
        # Mock graph_adapter.sync_to_sha to return full result dict
        mock_graph_sync_result = {
            "status": "success",
            "base_sha": "base123abc",
            "target_sha": "target456def",
            "files_added": 2,
            "files_modified": 3,
            "files_deleted": 1,
            "files_renamed": 0,
            "changed_files": ["file1.py", "file2.py", "file3.py"],
            "engine_result": {
                "status": "SYNCED",
                "sync_nodes": 45,
                "sync_edges": 120,
            },
            "persisted_state": {
                "commit_verified": True,
                "status": "SYNCED",
            },
        }
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            graph_instance.get_connected_files.return_value = []
            
            # Get target SHA from temp repo
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
            
            # Process commit
            result = orchestrator.process_commit(
                repo_id=repo_id,
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Verify graph_sync_result was persisted
        mgr = CheckpointManager()
        cp = mgr.get(repo_id, target_sha)
        
        assert cp is not None
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"] is not None, "graph_sync_result should be persisted"
        assert cp["graph_sync_result"]["engine_result"]["status"] == "SYNCED"
        assert cp["graph_sync_result"]["persisted_state"]["commit_verified"] is True
        assert cp["graph_sync_result"]["files_modified"] == 3
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_successful_sync_persists_result_in_complete_state(
        self, temp_repo_with_py_file, mock_github_token, mock_predictor_result
    ):
        """Test that COMPLETE checkpoint (not just GRAPH_SYNC_COMPLETE) has graph_sync_result."""
        repo_id = "test/complete-state"
        orchestrator = Orchestrator(github_token=mock_github_token)
        
        mock_graph_sync_result = {
            "status": "success",
            "base_sha": "base",
            "target_sha": "target",
            "files_added": 0,
            "files_modified": 1,
            "files_deleted": 0,
            "files_renamed": 0,
            "changed_files": ["app.py"],
            "engine_result": {"status": "SYNCED", "sync_nodes": 30},
            "persisted_state": {"commit_verified": True, "status": "SYNCED"},
        }
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            
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
                repo_id=repo_id,
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # Check the COMPLETE state specifically
        mgr = CheckpointManager()
        cp = mgr.get(repo_id, target_sha)
        
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"] is not None
        assert cp["graph_sync_result"]["files_modified"] == 1
        
        mgr.clear(repo_id, target_sha)
    
    def test_cache_recovery_with_legacy_checkpoint_re_syncs(
        self, temp_repo_with_py_file, mock_github_token, mock_predictor_result
    ):
        """Test that legacy checkpoints without graph_sync_result are recovered by re-syncing."""
        repo_id = "test/cache-recovery"
        orchestrator = Orchestrator(github_token=mock_github_token)
        mgr = CheckpointManager()
        
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
        
        # Simulate a legacy checkpoint without graph_sync_result (from before this fix)
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result=mock_predictor_result,
            graph_files_changed={"added": 1, "modified": 0, "deleted": 0, "renamed": 0},
            # Note: graph_sync_result is None (not passed)
        )
        
        # Verify checkpoint was saved without graph_sync_result
        cp = mgr.get(repo_id, target_sha)
        assert cp["graph_sync_result"] is None
        
        # Now process with orchestrator
        # This should detect missing graph_sync_result and re-sync
        mock_graph_sync_result = {
            "status": "success",
            "base_sha": "base",
            "target_sha": target_sha,
            "files_added": 1,
            "files_modified": 0,
            "files_deleted": 0,
            "files_renamed": 0,
            "changed_files": ["new_file.py"],
            "engine_result": {"status": "SYNCED"},
            "persisted_state": {"commit_verified": True, "status": "SYNCED"},
        }
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            graph_instance = MockGraph.return_value
            graph_instance.sync_to_sha.return_value = mock_graph_sync_result
            
            # Orchestrator should detect missing graph_sync_result and re-sync
            result = orchestrator.process_commit(
                repo_id=repo_id,
                target_sha=target_sha,
                repo_path=str(temp_repo_with_py_file),
            )
        
        # The result should be valid
        assert result.graph_status == GraphSyncStatus.SYNCHRONIZED
        
        # Most importantly: checkpoint should now have graph_sync_result populated
        cp_updated = mgr.get(repo_id, target_sha)
        assert cp_updated["graph_sync_result"] is not None, "graph_sync_result should be re-synced"
        assert cp_updated["graph_sync_result"]["engine_result"]["status"] == "SYNCED"
        
        mgr.clear(repo_id, target_sha)
    
    def test_graph_sync_exception_does_not_reference_unbound_variable(
        self, temp_repo_with_py_file, mock_github_token, mock_predictor_result
    ):
        """Test that GraphSyncException path doesn't try to pass unbound graph_sync_result."""
        repo_id = "test/graph-sync-fail"
        orchestrator = Orchestrator(github_token=mock_github_token, max_retries=0)
        
        with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
             patch("src.orchestrator.GraphAdapter") as MockGraph:
            
            MockMetadata.return_value.predict.return_value = mock_predictor_result
            graph_instance = MockGraph.return_value
            
            # Make sync fail immediately without returning a result
            graph_instance.sync_to_sha.side_effect = GraphSyncException("Network error")
            
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
            
            # This should raise but not with UnboundLocalError
            with pytest.raises(GraphSyncException):
                orchestrator.process_commit(
                    repo_id=repo_id,
                    target_sha=target_sha,
                    repo_path=str(temp_repo_with_py_file),
                )
        
        # Verify checkpoint was saved with error (no graph_sync_result)
        mgr = CheckpointManager()
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        assert cp["state"] == CheckpointState.FAILED
        assert cp["error"] is not None
        assert cp["graph_sync_result"] is None  # Expected: no sync result on failure
        
        mgr.clear(repo_id, target_sha)
