"""Tests for graph adapter recovery when graph is already verified at target SHA."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from src.adapters import GraphAdapter
from src.errors import GraphSyncException, InvalidCommitException


class TestGraphSyncRecoveryPath:
    """Test graph adapter recovery when graph is already synced to target SHA."""
    
    def test_recovery_when_graph_already_at_target_and_verified(self):
        """
        Recovery path: Graph is at target_sha in Neo4j, commit_verified=True, status=SYNCED.
        Should skip engine call and return verified sync result.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: already at target_sha and verified
        existing_sync_state = {
            "target_sha": target_sha,
            "commit_verified": True,
            "status": "SYNCED",
            "nodes_count": 150,
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
                    with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha") as mock_ensure_wc:
                        with patch.object(GraphAdapter, "_verify_database_target"):
                            with patch.object(GraphAdapter, "_validate_commits"):
                                # Setup mocks
                                mock_client = MagicMock()
                                mock_neo4j_class.return_value = mock_client
                                mock_client.get_sync_state.return_value = existing_sync_state
                                mock_client.database = "graphdoc"
                                mock_ensure_wc.return_value = "/tmp/graph_cache/test__repo"
                                
                                # Mock diff: assuming no changes (recovery scenario)
                                mock_diff.return_value = {
                                    "added": [],
                                    "modified": [],
                                    "deleted": [],
                                    "renamed": [],
                                }
                                
                                # Create adapter and call sync
                                adapter = GraphAdapter(repo_id, repo_path)
                                result = adapter.sync_to_sha(base_sha, target_sha)
                                
                                # Verify result structure
                                assert result["status"] == "SYNCHRONIZED"
                                assert result["target_sha"] == target_sha
                                assert result["base_sha"] == base_sha
                                assert result["files_added"] == 0
                                assert result["files_modified"] == 0
                                assert result["files_deleted"] == 0
                                assert result["files_renamed"] == 0
                                assert result["engine_result"] == existing_sync_state
                                assert result["persisted_state"] == existing_sync_state
                                assert isinstance(result["changed_files"], list)
                                
                                # Verify diff was called (to report file changes)
                                # Note: diff can be called with either the source repo or graph cache
                                assert mock_diff.called
                                call_args = mock_diff.call_args
                                assert call_args[0][0] == base_sha
                                assert call_args[0][1] == target_sha
                                
                                mock_client.close()
    
    def test_recovery_rejects_unverified_sync_state(self):
        """
        Recovery denied: Graph is at target_sha but commit_verified=False.
        Should raise GraphSyncException.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: at target but NOT verified
        existing_sync_state = {
            "target_sha": target_sha,
            "commit_verified": False,  # NOT verified
            "status": "SYNCED",
            "nodes_count": 150,
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                    with patch.object(GraphAdapter, "_verify_database_target"):
                        with patch.object(GraphAdapter, "_validate_commits"):
                            mock_client = MagicMock()
                            mock_neo4j_class.return_value = mock_client
                            mock_client.get_sync_state.return_value = existing_sync_state
                            mock_client.database = "graphdoc"
                            
                            adapter = GraphAdapter(repo_id, repo_path)
                            
                            with pytest.raises(GraphSyncException) as exc_info:
                                adapter.sync_to_sha(base_sha, target_sha)
                            assert "commit_verified=False" in str(exc_info.value)
                            
                            mock_client.close()
    
    def test_recovery_rejects_wrong_sync_status(self):
        """
        Recovery denied: Graph is at target_sha and verified but status != SYNCED.
        Should raise GraphSyncException.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: at target, verified, but wrong status
        existing_sync_state = {
            "target_sha": target_sha,
            "commit_verified": True,
            "status": "IN_PROGRESS",  # Not SYNCED
            "nodes_count": 150,
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                    with patch.object(GraphAdapter, "_verify_database_target"):
                        with patch.object(GraphAdapter, "_validate_commits"):
                            mock_client = MagicMock()
                            mock_neo4j_class.return_value = mock_client
                            mock_client.get_sync_state.return_value = existing_sync_state
                            mock_client.database = "graphdoc"
                            
                            adapter = GraphAdapter(repo_id, repo_path)
                            
                            with pytest.raises(GraphSyncException) as exc_info:
                                adapter.sync_to_sha(base_sha, target_sha)
                            assert "status is" in str(exc_info.value)
                            
                            mock_client.close()
    
    def test_normal_incremental_sync_still_validated(self):
        """
        Normal case: Graph is at parent_sha, requesting sync to target.
        Should proceed with engine call and normal validation (NOT recovery path).
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3  # Parent commit
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: at base_sha (parent)
        existing_sync_state = {
            "target_sha": base_sha,  # At parent
            "commit_verified": True,
            "status": "SYNCED",
        }
        
        # Mock engine result: normal incremental sync
        engine_result = {
            "status": "SUCCESS",
            "repo_id": repo_id,
            "target_sha": target_sha,
            "commit_verified": True,
            "files_parsed": 5,
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                    with patch("src.adapters.graph_adapter.update_graph_from_diff") as mock_engine:
                        with patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
                            with patch.object(GraphAdapter, "_verify_database_target"):
                                with patch.object(GraphAdapter, "_validate_commits"):
                                    with patch.object(GraphAdapter, "_verify_persisted_state") as mock_verify:
                                        mock_client = MagicMock()
                                        mock_neo4j_class.return_value = mock_client
                                        mock_client.get_sync_state.return_value = existing_sync_state
                                        mock_client.database = "graphdoc"
                                        
                                        mock_engine.return_value = engine_result
                                        mock_verify.return_value = {
                                            "target_sha": target_sha,
                                            "commit_verified": True,
                                            "status": "SYNCED",
                                            "nodes_count": 200,
                                        }
                                        mock_diff.return_value = {
                                            "added": ["file1.py"],
                                            "modified": ["file2.py"],
                                            "deleted": [],
                                            "renamed": [],
                                        }
                                        
                                        adapter = GraphAdapter(repo_id, repo_path)
                                        result = adapter.sync_to_sha(base_sha, target_sha)
                                        
                                        # Verify engine WAS called (not recovery path)
                                        mock_engine.assert_called_once()
                                        
                                        # Verify result
                                        assert result["status"] == "SYNCHRONIZED"
                                        assert result["files_added"] == 1
                                        assert result["files_modified"] == 1
                                        
                                        mock_client.close()
    
    def test_base_sha_mismatch_still_rejects_normal_case(self):
        """
        Validation still works: If graph is at DIFFERENT sha (not target_sha),
        and base_sha doesn't match, should reject with base mismatch error.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3  # Expected parent
        wrong_graph_sha = "wrong12345678" * 3  # Graph is at wrong place
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: at wrong SHA
        existing_sync_state = {
            "target_sha": wrong_graph_sha,
            "commit_verified": True,
            "status": "SYNCED",
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                    with patch.object(GraphAdapter, "_verify_database_target"):
                        with patch.object(GraphAdapter, "_validate_commits"):
                            mock_client = MagicMock()
                            mock_neo4j_class.return_value = mock_client
                            mock_client.get_sync_state.return_value = existing_sync_state
                            mock_client.database = "graphdoc"
                            
                            adapter = GraphAdapter(repo_id, repo_path)
                            
                            with pytest.raises(GraphSyncException) as exc_info:
                                adapter.sync_to_sha(base_sha, target_sha)
                            assert "Base SHA mismatch" in str(exc_info.value)
                            
                            mock_client.close()
    
    def test_no_prior_sync_proceeds_with_engine(self):
        """
        Initial ingestion: No prior sync state.
        Should proceed with engine call using provided base_sha.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3
        repo_path = "/tmp/test-repo"
        
        # Mock Neo4j SyncState: None (no prior sync)
        
        # Mock engine result
        engine_result = {
            "status": "SUCCESS",
            "repo_id": repo_id,
            "target_sha": target_sha,
            "commit_verified": True,
            "files_parsed": 10,
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                    with patch("src.adapters.graph_adapter.update_graph_from_diff") as mock_engine:
                        with patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
                            with patch.object(GraphAdapter, "_verify_database_target"):
                                with patch.object(GraphAdapter, "_validate_commits"):
                                    with patch.object(GraphAdapter, "_verify_persisted_state") as mock_verify:
                                        mock_client = MagicMock()
                                        mock_neo4j_class.return_value = mock_client
                                        mock_client.get_sync_state.return_value = None  # No prior sync
                                        mock_client.database = "graphdoc"
                                        
                                        mock_engine.return_value = engine_result
                                        mock_verify.return_value = {
                                            "target_sha": target_sha,
                                            "commit_verified": True,
                                            "status": "SYNCED",
                                            "nodes_count": 300,
                                        }
                                        mock_diff.return_value = {
                                            "added": [],
                                            "modified": [],
                                            "deleted": [],
                                            "renamed": [],
                                        }
                                        
                                        adapter = GraphAdapter(repo_id, repo_path)
                                        result = adapter.sync_to_sha(base_sha, target_sha)
                                        
                                        # Verify engine WAS called
                                        mock_engine.assert_called_once()
                                        
                                        assert result["status"] == "SYNCHRONIZED"
                                        
                                        mock_client.close()
    
    def test_recovery_result_suitable_for_checkpoint_persistence(self):
        """
        Verify that recovered result has all fields expected by orchestrator.
        Should have: files_added, files_modified, files_deleted, files_renamed,
        engine_result, persisted_state, changed_files, status, base_sha, target_sha.
        """
        repo_id = "test/repo"
        target_sha = "abc123def456" * 3
        base_sha = "base1234567890" * 3
        repo_path = "/tmp/test-repo"
        
        existing_sync_state = {
            "target_sha": target_sha,
            "commit_verified": True,
            "status": "SYNCED",
            "nodes_count": 150,
            "created_at": "2024-10-15T10:00:00",
        }
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as mock_neo4j_class:
            with patch("src.adapters.graph_adapter.SyncStateManager"):
                with patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
                    with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha"):
                        with patch.object(GraphAdapter, "_verify_database_target"):
                            with patch.object(GraphAdapter, "_validate_commits"):
                                mock_client = MagicMock()
                                mock_neo4j_class.return_value = mock_client
                                mock_client.get_sync_state.return_value = existing_sync_state
                                mock_client.database = "graphdoc"
                                
                                mock_diff.return_value = {
                                    "added": ["new_file.py"],
                                    "modified": ["existing_file.py"],
                                    "deleted": [],
                                    "renamed": [["old.py", "new.py"]],
                                }
                                
                                adapter = GraphAdapter(repo_id, repo_path)
                                result = adapter.sync_to_sha(base_sha, target_sha)
                                
                                # Verify all expected fields for orchestrator checkpoint
                                assert "status" in result
                                assert "target_sha" in result
                                assert "base_sha" in result
                                assert "files_added" in result
                                assert "files_modified" in result
                                assert "files_deleted" in result
                                assert "files_renamed" in result
                                assert "changed_files" in result
                                assert "engine_result" in result
                                assert "persisted_state" in result
                                
                                # Verify types
                                assert result["status"] == "SYNCHRONIZED"
                                assert result["target_sha"] == target_sha
                                assert result["base_sha"] == base_sha
                                assert isinstance(result["files_added"], int)
                                assert isinstance(result["files_modified"], int)
                                assert isinstance(result["files_deleted"], int)
                                assert isinstance(result["files_renamed"], int)
                                assert isinstance(result["changed_files"], list)
                                assert isinstance(result["engine_result"], dict)
                                assert isinstance(result["persisted_state"], dict)
                                
                                # Verify counts match diff
                                assert result["files_added"] == 1
                                assert result["files_modified"] == 1
                                assert result["files_deleted"] == 0
                                assert result["files_renamed"] == 1
                                
                                mock_client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
