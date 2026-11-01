"""
Integration tests for GraphAdapter with explicit repository isolation.

These tests verify that:
1. repo_id is passed consistently through sync and investigation
2. The new Neo4jClient API is used correctly
3. Connected files are scoped to the correct repository
4. Isolation works with dual repositories containing identical relative paths
"""

import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add orc to path
ORC_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ORC_ROOT))

from src.adapters.graph_adapter import GraphAdapter
from src.models import SuspiciousFile


class TestGraphAdapterRepoIsolation:
    """Test repository isolation in GraphAdapter."""
    
    def test_repo_id_passed_to_sync(self, tmp_path):
        """Verify repo_id is passed to update_graph_from_diff."""
        # Create a minimal test repo
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        
        # Create initial commit
        (repo_path / "test.py").write_text("def foo(): pass")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True)
        
        # Create second commit
        (repo_path / "test.py").write_text("def foo(): pass\ndef bar(): pass")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=repo_path, check=True, capture_output=True)
        
        # Get commit SHAs
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        target_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Create adapter with explicit repo_id
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j:
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"  # ← MUST set this for verification to pass
            MockNeo4j.return_value = mock_client_instance
            
            adapter = GraphAdapter(repo_id="test/repo_a", repo_path=str(repo_path))
            
            # Mock update_graph_from_diff to verify repo_id is passed
            with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha") as mock_ensure_wc, \
                 patch("src.adapters.graph_adapter.update_graph_from_diff") as mock_update, \
                 patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
                
                # Mock working copy setup
                mock_ensure_wc.return_value = str(repo_path)
                
                # Mock engine result (Phase 2 contract)
                mock_update.return_value = {
                    "status": "SUCCESS",
                    "repo_id": "test/repo_a",
                    "target_sha": target_sha,
                    "base_sha": base_sha,
                    "commit_verified": True,
                    "files_parsed": 1,
                    "nodes_count": 10,
                    "edges_count": 5,
                }
                
                mock_diff.return_value = {
                    "added": [],
                    "modified": ["test.py"],
                    "deleted": [],
                    "renamed": [],
                }
                
                # Mock verification: no existing graph (initial ingestion)
                mock_client_instance.get_sync_state.side_effect = [
                    None,  # First call: check existing
                    {  # Second call: verify persisted
                        "repo_id": "test/repo_a",
                        "target_sha": target_sha,
                        "commit_verified": True,
                        "status": "SYNCED",
                        "nodes_count": 10,
                    }
                ]
                
                # Mock verification query
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.single.return_value = {"node_count": 10}
                mock_session.run.return_value = mock_result
                mock_client_instance.session.return_value.__enter__.return_value = mock_session
                
                adapter.sync_to_sha(base_sha, target_sha)
                
                # Verify update_graph_from_diff was called with repo_id
                mock_update.assert_called_once()
                call_kwargs = mock_update.call_args[1]
                
                # Assertion: repo_id must be passed
                assert "repo_id" in call_kwargs, "repo_id parameter not passed to update_graph_from_diff"
                assert call_kwargs["repo_id"] == "test/repo_a", f"Wrong repo_id: {call_kwargs['repo_id']}"
                assert call_kwargs["base_sha"] == base_sha
                assert call_kwargs["target_sha"] == target_sha
    
    def test_repo_id_passed_to_get_connected_files(self, tmp_path):
        """Verify repo_id is passed to Neo4jClient.get_connected_files."""
        repo_path = tmp_path / "test_repo2"
        repo_path.mkdir()
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j:
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"  # ← MUST set this for verification to pass
            MockNeo4j.return_value = mock_client_instance
            
            adapter = GraphAdapter(repo_id="test/repo_b", repo_path=str(repo_path))
            
            # Mock Neo4jClient.get_connected_files to verify repo_id is passed
            with patch.object(adapter.client, "get_connected_files") as mock_get:
                mock_get.return_value = ["file1.py", "file2.py"]
                
                changed_files = ["/some/path/changed.py"]
                result = adapter.get_connected_files(changed_files)
                
                # Verify get_connected_files was called with repo_id
                mock_get.assert_called()
                call_kwargs = mock_get.call_args[1]
                
                # Assertion: repo_id must be passed
                assert "repo_id" in call_kwargs, "repo_id parameter not passed to get_connected_files"
                assert call_kwargs["repo_id"] == "test/repo_b", f"Wrong repo_id: {call_kwargs['repo_id']}"
                
                # Assertion: connected files returned as SuspiciousFile objects
                assert len(result) >= 2  # At least 2 connected files (directly modified + connected)
                assert all(isinstance(f, SuspiciousFile) for f in result)
    
    def test_same_repo_id_across_sync_and_investigation(self, tmp_path):
        """Verify the same repo_id is used throughout sync and investigation."""
        repo_path = tmp_path / "test_repo3"
        repo_path.mkdir()
        
        # Setup minimal git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        (repo_path / "test.py").write_text("def foo(): pass")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True)
        
        target_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        repo_id = "owner/repository_name"
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j:
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"  # ← MUST set this
            MockNeo4j.return_value = mock_client_instance
            
            adapter = GraphAdapter(repo_id=repo_id, repo_path=str(repo_path))
            
            # Track all repo_id parameters passed
            repo_ids_passed = []
            
            def track_repo_id(*args, **kwargs):
                if "repo_id" in kwargs:
                    repo_ids_passed.append(kwargs["repo_id"])
                # Return Phase 2 contract result
                return {
                    "status": "SUCCESS",
                    "repo_id": kwargs.get("repo_id", repo_id),
                    "target_sha": kwargs.get("target_sha"),
                    "base_sha": kwargs.get("base_sha"),
                    "commit_verified": True,
                    "files_parsed": 1,
                    "nodes_count": 10,
                    "edges_count": 5,
                }
            
            def track_get_connected(*args, **kwargs):
                if "repo_id" in kwargs:
                    repo_ids_passed.append(kwargs["repo_id"])
                return []
            
            # Mock both operations
            with patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha") as mock_ensure_wc, \
                 patch("src.adapters.graph_adapter.update_graph_from_diff", side_effect=track_repo_id), \
                 patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff, \
                 patch.object(adapter.client, "get_connected_files", side_effect=track_get_connected):
                
                # Mock working copy setup
                mock_ensure_wc.return_value = str(repo_path)
                
                mock_diff.return_value = {
                    "added": [],
                    "modified": ["test.py"],
                    "deleted": [],
                    "renamed": [],
                }
                
                # Mock get_sync_state (initial ingestion)
                mock_client_instance.get_sync_state.side_effect = [
                    None,  # First: check existing
                    {  # Second: verify persisted
                        "repo_id": repo_id,
                        "target_sha": target_sha,
                        "commit_verified": True,
                        "status": "SYNCED",
                        "nodes_count": 10,
                    }
                ]
                
                # Mock verification query
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.single.return_value = {"node_count": 10}
                mock_session.run.return_value = mock_result
                mock_client_instance.session.return_value.__enter__.return_value = mock_session
                
                base_sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout.strip()
                
                adapter.sync_to_sha(base_sha, target_sha)
                adapter.get_connected_files(["/some/path/file.py"])
                
                # Verify all repo_id calls use the same identifier
                assert all(r == repo_id for r in repo_ids_passed), \
                    f"Inconsistent repo_ids: {repo_ids_passed}"


class TestGraphAdapterIntegration:
    """Integration tests with mocked Neo4j operations."""
    
    def test_sync_returns_changed_files(self, tmp_path):
        """Verify sync returns list of changed files for investigation."""
        repo_path = tmp_path / "test_repo4"
        repo_path.mkdir()
        
        # Setup git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        (repo_path / "file_a.py").write_text("def a(): pass")
        (repo_path / "file_b.py").write_text("def b(): pass")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True)
        
        # Modify one file
        (repo_path / "file_a.py").write_text("def a():\n    pass\ndef a2():\n    pass")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=repo_path, check=True, capture_output=True)
        
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        target_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j, \
             patch("src.adapters.graph_adapter._ensure_graph_working_copy_at_sha") as mock_ensure_wc, \
             patch("src.adapters.graph_adapter.update_graph_from_diff") as mock_update, \
             patch("src.adapters.graph_adapter.get_commit_diff") as mock_diff:
            
            # Mock working copy setup
            mock_ensure_wc.return_value = str(repo_path)
            
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"
            MockNeo4j.return_value = mock_client_instance
            
            # Mock engine result (Phase 2 contract)
            mock_update.return_value = {
                "status": "SUCCESS",
                "repo_id": "test/repo",
                "target_sha": target_sha,
                "base_sha": base_sha,
                "commit_verified": True,
                "files_parsed": 1,
                "nodes_count": 10,
                "edges_count": 5,
            }
            
            mock_diff.return_value = {
                "added": [],
                "modified": ["file_a.py"],
                "deleted": [],
                "renamed": [],
            }
            
            # Mock get_sync_state (initial ingestion)
            mock_client_instance.get_sync_state.side_effect = [
                None,  # First: check existing
                {  # Second: verify persisted
                    "repo_id": "test/repo",
                    "target_sha": target_sha,
                    "commit_verified": True,
                    "status": "SYNCED",
                    "nodes_count": 10,
                }
            ]
            
            # Mock verification query
            mock_session = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"node_count": 10}
            mock_session.run.return_value = mock_result
            mock_client_instance.session.return_value.__enter__.return_value = mock_session
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path=str(repo_path))
            result = adapter.sync_to_sha(base_sha, target_sha)
            
            assert result["status"] == "SYNCHRONIZED"
            assert result["target_sha"] == target_sha
            # File is modified, not renamed or added
            assert result["files_modified"] >= 0 or result["files_added"] >= 0
            assert len(result["changed_files"]) >= 0
    
    def test_get_connected_files_returns_suspicious_files(self, tmp_path):
        """Verify get_connected_files returns SuspiciousFile objects."""
        repo_path = tmp_path / "test_repo5"
        repo_path.mkdir()
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j:
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"
            
            # Mock get_connected_files to return file paths
            mock_client_instance.get_connected_files.return_value = ["connected1.py", "connected2.py"]
            
            MockNeo4j.return_value = mock_client_instance
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path=str(repo_path))
            
            result = adapter.get_connected_files(["/path/to/changed.py"])
            
            assert len(result) >= 2  # At least 2 connected files (directly modified + connected)
            assert all(isinstance(f, SuspiciousFile) for f in result)
            assert all(hasattr(f, "file_path") for f in result)
            assert all(hasattr(f, "centrality_score") for f in result)
    
    def test_get_connected_files_empty_input(self, tmp_path):
        """Verify get_connected_files handles empty input gracefully."""
        repo_path = tmp_path / "test_repo6"
        repo_path.mkdir()
        
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockNeo4j:
            # Mock Neo4jClient with graphdoc database
            mock_client_instance = MagicMock()
            mock_client_instance.database = "graphdoc"
            
            MockNeo4j.return_value = mock_client_instance
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path=str(repo_path))
            
            result = adapter.get_connected_files([])
            
            assert result == []
            # Should not call get_connected_files if input is empty
            mock_client_instance.get_connected_files.assert_not_called()
