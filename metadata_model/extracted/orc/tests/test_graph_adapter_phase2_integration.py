#!/usr/bin/env python3
"""
Phase 2 Integration Tests: Verified Commit Provenance

Tests the integration between ORC and graph-doc-gen-main's new
commit-provenance contract. The graph engine now returns a structured
Dict with operation metadata instead of None.

Tests cover:
1. Validation of engine result structure and values
2. Verification of persisted Neo4j state
3. Rejection of invalid results
4. Complete workflows (initial ingestion, incremental, idempotent)
5. Base SHA mismatch detection
"""

import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

# Setup paths
GRAPH_DOC_GEN_ROOT = Path(__file__).parent.parent.parent / "graph-doc-gen-main"
ORC_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT))
sys.path.insert(0, str(ORC_ROOT))

from src.adapters.graph_adapter import GraphAdapter
from src.errors import GraphSyncException


class TestValidateSyncResult:
    """Test _validate_sync_result method."""
    
    def _make_adapter(self):
        """Create adapter with mocked Neo4jClient."""
        with patch('src.adapters.graph_adapter.Neo4jClient') as MockClient:
            mock_instance = MagicMock()
            mock_instance.database = "graphdoc"
            MockClient.return_value = mock_instance
            return GraphAdapter("test/repo", "/tmp/repo"), mock_instance
    
    def test_accepts_valid_success_result(self):
        """Test _validate_sync_result accepts valid SUCCESS result."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "SUCCESS",
            "repo_id": "test/repo",
            "target_sha": "abc123" * 6 + "abcd",  # 40 chars
            "commit_verified": True,
        }
        
        # Should not raise
        adapter._validate_sync_result(result, "abc123" * 6 + "abcd")
        adapter.close()
    
    def test_accepts_valid_no_changes_result(self):
        """Test _validate_sync_result accepts valid NO_CHANGES result."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "NO_CHANGES",
            "repo_id": "test/repo",
            "target_sha": "def456" * 6 + "defg",
            "commit_verified": True,
        }
        
        adapter._validate_sync_result(result, "def456" * 6 + "defg")
        adapter.close()
    
    def test_rejects_none_result(self):
        """Test _validate_sync_result rejects None result."""
        adapter, _ = self._make_adapter()
        
        with pytest.raises(GraphSyncException) as exc:
            adapter._validate_sync_result(None, "abc123" * 6 + "abcd")
        
        assert "returned none" in str(exc.value).lower()
        adapter.close()
    
    def test_rejects_failed_status(self):
        """Test _validate_sync_result rejects FAILED status."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "FAILED",
            "repo_id": "test/repo",
            "target_sha": "abc123" * 6 + "abcd",
            "commit_verified": False,
            "error": "Parse error",
        }
        
        with pytest.raises(GraphSyncException) as exc:
            adapter._validate_sync_result(result, "abc123" * 6 + "abcd")
        
        assert "operation failed" in str(exc.value).lower()
        adapter.close()
    
    def test_rejects_wrong_repo_id(self):
        """Test _validate_sync_result rejects mismatched repo_id."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "SUCCESS",
            "repo_id": "wrong/repo",
            "target_sha": "abc123" * 6 + "abcd",
            "commit_verified": True,
        }
        
        with pytest.raises(GraphSyncException) as exc:
            adapter._validate_sync_result(result, "abc123" * 6 + "abcd")
        
        assert "repo id mismatch" in str(exc.value).lower()
        adapter.close()
    
    def test_rejects_wrong_target_sha(self):
        """Test _validate_sync_result rejects mismatched target_sha."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "SUCCESS",
            "repo_id": "test/repo",
            "target_sha": "xxx999" * 6 + "xxxx",  # Different
            "commit_verified": True,
        }
        
        with pytest.raises(GraphSyncException) as exc:
            adapter._validate_sync_result(result, "abc123" * 6 + "abcd")  # Different
        
        assert "target sha mismatch" in str(exc.value).lower()
        adapter.close()
    
    def test_rejects_commit_verified_false(self):
        """Test _validate_sync_result rejects commit_verified=False."""
        adapter, _ = self._make_adapter()
        
        result = {
            "status": "SUCCESS",
            "repo_id": "test/repo",
            "target_sha": "abc123" * 6 + "abcd",
            "commit_verified": False,  # NOT VERIFIED
        }
        
        with pytest.raises(GraphSyncException) as exc:
            adapter._validate_sync_result(result, "abc123" * 6 + "abcd")
        
        assert "commit verification failed" in str(exc.value).lower()
        adapter.close()


class TestVerifyPersistedState:
    """Test _verify_persisted_state method."""
    
    def _make_adapter(self):
        """Create adapter with mocked Neo4jClient."""
        with patch('src.adapters.graph_adapter.Neo4jClient') as MockClient:
            mock_instance = MagicMock()
            mock_instance.database = "graphdoc"
            MockClient.return_value = mock_instance
            return GraphAdapter("test/repo", "/tmp/repo"), mock_instance
    
    def test_accepts_valid_persisted_state(self):
        """Test _verify_persisted_state with valid SyncState."""
        adapter, mock_client = self._make_adapter()
        
        target_sha = "abc123" * 6 + "abcd"
        persisted = {
            "repo_id": "test/repo",
            "target_sha": target_sha,
            "commit_verified": True,
            "status": "SYNCED",
            "nodes_count": 100,
        }
        
        with patch.object(mock_client, 'get_sync_state', return_value=persisted):
            result = adapter._verify_persisted_state(target_sha)
            assert result == persisted
        
        adapter.close()
    
    def test_rejects_missing_syncstate(self):
        """Test _verify_persisted_state rejects when SyncState is missing."""
        adapter, mock_client = self._make_adapter()
        
        with patch.object(mock_client, 'get_sync_state', return_value=None):
            with pytest.raises(GraphSyncException) as exc:
                adapter._verify_persisted_state("abc123" * 6 + "abcd")
            
            assert "no syncstate found" in str(exc.value).lower()
        
        adapter.close()
    
    def test_rejects_wrong_target_sha(self):
        """Test _verify_persisted_state rejects mismatched target_sha."""
        adapter, mock_client = self._make_adapter()
        
        persisted = {
            "repo_id": "test/repo",
            "target_sha": "xxx999" * 6 + "xxxx",  # Wrong
            "commit_verified": True,
            "status": "SYNCED",
        }
        
        with patch.object(mock_client, 'get_sync_state', return_value=persisted):
            with pytest.raises(GraphSyncException) as exc:
                adapter._verify_persisted_state("abc123" * 6 + "abcd")
            
            assert "target sha mismatch" in str(exc.value).lower()
        
        adapter.close()
    
    def test_rejects_commit_verified_false(self):
        """Test _verify_persisted_state rejects commit_verified=False."""
        adapter, mock_client = self._make_adapter()
        
        persisted = {
            "repo_id": "test/repo",
            "target_sha": "abc123" * 6 + "abcd",
            "commit_verified": False,  # NOT VERIFIED
            "status": "SYNCED",
        }
        
        with patch.object(mock_client, 'get_sync_state', return_value=persisted):
            with pytest.raises(GraphSyncException) as exc:
                adapter._verify_persisted_state("abc123" * 6 + "abcd")
            
            assert "commit verification failed" in str(exc.value).lower()
        
        adapter.close()
    
    def test_rejects_wrong_status(self):
        """Test _verify_persisted_state rejects non-SYNCED status."""
        adapter, mock_client = self._make_adapter()
        
        persisted = {
            "repo_id": "test/repo",
            "target_sha": "abc123" * 6 + "abcd",
            "commit_verified": True,
            "status": "PENDING",  # WRONG
        }
        
        with patch.object(mock_client, 'get_sync_state', return_value=persisted):
            with pytest.raises(GraphSyncException) as exc:
                adapter._verify_persisted_state("abc123" * 6 + "abcd")
            
            assert "status mismatch" in str(exc.value).lower()
        
        adapter.close()


class TestSyncToShaWorkflows:
    """Test sync_to_sha complete workflows."""
    
    def _make_adapter(self):
        """Create adapter with mocked Neo4jClient."""
        with patch('src.adapters.graph_adapter.Neo4jClient') as MockClient:
            mock_instance = MagicMock()
            mock_instance.database = "graphdoc"
            MockClient.return_value = mock_instance
            return GraphAdapter("test/workflow", "/tmp/repo"), mock_instance
    
    def test_initial_ingestion_workflow(self):
        """Test sync_to_sha for initial ingestion (no existing graph)."""
        adapter, mock_client = self._make_adapter()
        base_sha = "aaa" * 13 + "aaaa"  # 40 chars
        target_sha = "bbb" * 13 + "bbbb"
        
        with patch('src.adapters.graph_adapter._ensure_graph_working_copy_at_sha') as mock_ensure_wc, \
             patch('src.adapters.graph_adapter.update_graph_from_diff') as mock_update, \
             patch('src.adapters.graph_adapter.get_commit_diff') as mock_diff, \
             patch.object(adapter, '_validate_commits'):
            
            # Mock: Working copy setup
            mock_ensure_wc.return_value = "/tmp/graph_cache/test__workflow"
            
            # Mock: No existing graph
            get_sync_calls = [None, {  # First: check existing, Second: verify persisted
                "repo_id": "test/workflow",
                "target_sha": target_sha,
                "commit_verified": True,
                "status": "SYNCED",
                "nodes_count": 50,
            }]
            mock_client.get_sync_state.side_effect = get_sync_calls
            
            # Mock: Engine returns success
            engine_result = {
                "status": "SUCCESS",
                "repo_id": "test/workflow",
                "target_sha": target_sha,
                "base_sha": base_sha,
                "commit_verified": True,
                "files_parsed": 3,
                "nodes_count": 50,
                "edges_count": 20,
                "error": None,
            }
            mock_update.return_value = engine_result
            
            # Mock: Diff result
            mock_diff.return_value = {
                "added": ["file_a.py"],
                "modified": [],
                "deleted": [],
                "renamed": [],
            }
            
            result = adapter.sync_to_sha(base_sha, target_sha)
            
            # Verify result
            assert result["status"] == "SYNCHRONIZED"
            assert result["target_sha"] == target_sha
            assert result["base_sha"] == base_sha
            assert "engine_result" in result
            assert "persisted_state" in result
            
            # Verify engine was called
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[1]["target_sha"] == target_sha
            assert call_args[1]["repo_id"] == "test/workflow"
        
        adapter.close()
    
    def test_incremental_sync_workflow(self):
        """Test sync_to_sha for incremental update (existing graph matches base)."""
        adapter, mock_client = self._make_adapter()
        base_sha = "aaa" * 13 + "aaaa"
        target_sha = "bbb" * 13 + "bbbb"
        
        with patch('src.adapters.graph_adapter._ensure_graph_working_copy_at_sha') as mock_ensure_wc, \
             patch('src.adapters.graph_adapter.update_graph_from_diff') as mock_update, \
             patch('src.adapters.graph_adapter.get_commit_diff') as mock_diff, \
             patch.object(adapter, '_validate_commits'):
            
            # Mock: Working copy setup
            mock_ensure_wc.return_value = "/tmp/graph_cache/test__workflow"
            
            # Mock: Existing graph matches base
            existing_sync = {
                "repo_id": "test/workflow",
                "target_sha": base_sha,
                "commit_verified": True,
            }
            
            persisted_sync = {
                "repo_id": "test/workflow",
                "target_sha": target_sha,
                "commit_verified": True,
                "status": "SYNCED",
                "nodes_count": 75,
            }
            
            mock_client.get_sync_state.side_effect = [existing_sync, persisted_sync]
            
            engine_result = {
                "status": "SUCCESS",
                "repo_id": "test/workflow",
                "target_sha": target_sha,
                "base_sha": base_sha,
                "commit_verified": True,
                "files_parsed": 2,
                "nodes_count": 75,
                "edges_count": 35,
                "error": None,
            }
            mock_update.return_value = engine_result
            
            mock_diff.return_value = {
                "added": [],
                "modified": ["file_c.py"],
                "deleted": [],
                "renamed": [],
            }
            
            result = adapter.sync_to_sha(base_sha, target_sha)
            
            assert result["status"] == "SYNCHRONIZED"
            assert result["target_sha"] == target_sha
        
        adapter.close()
    
    def test_rejects_base_sha_mismatch(self):
        """Test sync_to_sha rejects when base doesn't match graph's current state."""
        adapter, mock_client = self._make_adapter()
        base_sha = "aaa" * 13 + "aaaa"
        target_sha = "bbb" * 13 + "bbbb"
        
        with patch('src.adapters.graph_adapter._ensure_graph_working_copy_at_sha') as mock_ensure_wc, \
             patch.object(adapter, '_validate_commits'):
            
            # Mock: Working copy setup
            mock_ensure_wc.return_value = "/tmp/graph_cache/test__workflow"
            
            # Mock: Existing graph has DIFFERENT target_sha
            wrong_existing = {
                "repo_id": "test/workflow",
                "target_sha": "ccc" * 13 + "cccc",  # NOT matching base
                "commit_verified": True,
            }
            
            mock_client.get_sync_state.return_value = wrong_existing
            
            with pytest.raises(GraphSyncException) as exc:
                adapter.sync_to_sha(base_sha, target_sha)
            
            assert "base sha mismatch" in str(exc.value).lower()
        
        adapter.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
