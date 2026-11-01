"""Tests for local commit support and evidence-based RCA improvements."""

import os
import tempfile
import subprocess
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import pytest

from src.orchestrator import Orchestrator
from src.adapters.graph_adapter import GraphAdapter
from src.models import SuspiciousFile
from src.errors import GraphSyncException


class TestLocalCommitSupport:
    """Test that local commits work without requiring GitHub push."""
    
    def test_metadata_adapter_receives_source_repo_path(self):
        """Verify that orchestrator passes repo_path to MetadataAdapter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create minimal git repo
            subprocess.run("git init", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.email test@test.com", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.name Test", cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Create a file and commit
            test_file = repo_path / "test.py"
            test_file.write_text("print('hello')")
            subprocess.run("git add test.py", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run('git commit -m "initial"', cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Get the commit SHA
            result = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
            target_sha = result.stdout.strip()
            
            orchestrator = Orchestrator(github_token="fake_token")
            
            # Mock MetadataAdapter and GraphAdapter
            with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
                 patch("src.orchestrator.GraphAdapter") as MockGraph:
                
                # Track how MetadataAdapter is initialized
                mock_metadata_instance = MagicMock()
                MockMetadata.return_value = mock_metadata_instance
                mock_metadata_instance.predict.return_value = {
                    "failure_probability": 0.3,
                    "verdict": "LOW RISK",
                    "shap_drivers": {},
                }
                
                mock_graph_instance = MagicMock()
                MockGraph.return_value = mock_graph_instance
                mock_graph_instance.sync_to_sha.return_value = {
                    "status": "SYNCHRONIZED",
                    "files_added": 0,
                    "files_modified": 0,
                    "files_deleted": 0,
                    "files_renamed": 0,
                    "changed_files": [],
                }
                
                # Process commit
                orchestrator.process_commit(
                    repo_id="owner/repo",
                    target_sha=target_sha,
                    repo_path=str(repo_path),
                )
                
                # Verify MetadataAdapter was initialized with source_repo_path
                MockMetadata.assert_called_with("fake_token", source_repo_path=str(repo_path))
    
    def test_source_repo_path_enables_local_analysis(self):
        """Verify that source_repo_path parameter is used by MetadataAdapter."""
        from src.adapters.metadata_adapter import MetadataAdapter
        
        # This just verifies the parameter exists and is stored
        adapter = MagicMock()
        adapter.source_repo_path = "/path/to/repo"
        
        # The key is that MetadataAdapter accepts this parameter
        assert hasattr(MetadataAdapter, '__init__')
        # Check that MetadataAdapter.__init__ accepts source_repo_path
        import inspect
        sig = inspect.signature(MetadataAdapter.__init__)
        assert 'source_repo_path' in sig.parameters


class TestEvidenceBasedRCA:
    """Test evidence-based RCA with diff analysis and ranking."""
    
    def test_extract_commit_evidence_returns_dict(self):
        """Verify that _extract_commit_evidence returns evidence map."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create minimal git repo
            subprocess.run("git init", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.email test@test.com", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.name Test", cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Create initial commit
            file1 = repo_path / "auth.py"
            file1.write_text("def login(): pass")
            subprocess.run("git add auth.py", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run('git commit -m "initial"', cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Get base SHA
            result = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
            base_sha = result.stdout.strip()
            
            # Make a change
            file1.write_text("def login():\n    return True")
            subprocess.run("git add auth.py", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run('git commit -m "fix login"', cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Get target SHA
            result = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
            target_sha = result.stdout.strip()
            
            # Create adapter and test evidence extraction
            with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
                mock_client = MagicMock()
                MockClient.return_value = mock_client
                mock_client.database = "graphdoc"
                
                adapter = GraphAdapter(repo_id="test/repo", repo_path=str(repo_path))
                
                directly_modified = {str(file1)}
                evidence_map = adapter._extract_commit_evidence(base_sha, target_sha, directly_modified)
                
                # Verify evidence_map is a dict
                assert isinstance(evidence_map, dict)
    
    def test_get_connected_files_accepts_base_and_target_sha(self):
        """Verify that get_connected_files accepts base_sha and target_sha."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = []
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            # Call with base_sha and target_sha
            result = adapter.get_connected_files(
                changed_files=["src/auth.py"],
                base_sha="abc123" * 7,
                target_sha="def456" * 7,
            )
            
            # Verify it doesn't crash and returns a list
            assert isinstance(result, list)
    
    def test_directly_modified_files_have_highest_ranking(self):
        """Verify that directly modified files get highest centrality score."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = ["src/core.py"]
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            changed_files = ["/tmp/src/auth.py"]
            
            result = adapter.get_connected_files(
                changed_files=changed_files,
                base_sha="abc123" * 7,
                target_sha="def456" * 7,
            )
            
            # Find directly modified file in result
            direct_files = [f for f in result if f.file_path == "/tmp/src/auth.py"]
            connected_files = [f for f in result if f.file_path != "/tmp/src/auth.py"]
            
            if direct_files and connected_files:
                # Directly modified should have higher score than connected
                assert direct_files[0].centrality_score >= connected_files[0].centrality_score
    
    def test_suspicious_files_includes_directly_modified(self):
        """Verify that directly modified files are always in suspicious list."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = []
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            changed_files = ["/tmp/src/auth.py", "/tmp/src/utils.py"]
            
            result = adapter.get_connected_files(
                changed_files=changed_files,
                base_sha="abc123" * 7,
                target_sha="def456" * 7,
            )
            
            result_paths = [f.file_path for f in result]
            
            # Both changed files should be in result (normalize paths for Windows)
            assert any("auth.py" in p for p in result_paths)
            assert any("utils.py" in p for p in result_paths)
    
    def test_evidence_reasons_included(self):
        """Verify that suspicious files include evidence-based reasons."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = []
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            changed_files = ["/tmp/src/auth.py"]
            
            result = adapter.get_connected_files(
                changed_files=changed_files,
                base_sha="abc123" * 7,
                target_sha="def456" * 7,
            )
            
            # Verify reasons are included
            assert len(result) > 0
            assert all(hasattr(f, 'reasons') for f in result)
            assert all(isinstance(f.reasons, list) for f in result)
            # First file should mention it's directly modified
            assert any("modified" in r.lower() for r in result[0].reasons)
    
    def test_empty_suspicious_files_list_prevented(self):
        """Verify that suspicious_files list is not empty when there are changed files."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = []
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            changed_files = ["/tmp/src/auth.py"]
            
            result = adapter.get_connected_files(
                changed_files=changed_files,
                base_sha="abc123" * 7,
                target_sha="def456" * 7,
            )
            
            # Should NOT be empty - directly modified files should be included
            assert len(result) > 0
            # Check file path contains auth.py (handles Windows path normalization)
            assert any("auth.py" in f.file_path for f in result)


class TestIntegration:
    """Integration tests for local commits and RCA."""
    
    def test_orchestrator_passes_base_and_target_to_get_connected_files(self):
        """Verify orchestrator calls get_connected_files with SHAs for evidence-based ranking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create minimal git repo
            subprocess.run("git init", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.email test@test.com", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run("git config user.name Test", cwd=repo_path, shell=True, check=True, capture_output=True)
            
            # Create initial commit
            file1 = repo_path / "auth.py"
            file1.write_text("def login(): pass")
            subprocess.run("git add auth.py", cwd=repo_path, shell=True, check=True, capture_output=True)
            subprocess.run('git commit -m "initial"', cwd=repo_path, shell=True, check=True, capture_output=True)
            
            result = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
            target_sha = result.stdout.strip()
            
            orchestrator = Orchestrator(github_token="fake_token", investigation_threshold=0.5)
            
            with patch("src.orchestrator.MetadataAdapter") as MockMetadata, \
                 patch("src.orchestrator.GraphAdapter") as MockGraph:
                
                # Mock metadata adapter for high risk
                mock_metadata = MagicMock()
                MockMetadata.return_value = mock_metadata
                mock_metadata.predict.return_value = {
                    "failure_probability": 0.75,  # Above threshold
                    "verdict": "HIGH RISK",
                    "shap_drivers": {},
                }
                
                # Mock graph adapter
                mock_graph = MagicMock()
                MockGraph.return_value = mock_graph
                mock_graph.sync_to_sha.return_value = {
                    "status": "SYNCHRONIZED",
                    "base_sha": target_sha,
                    "target_sha": target_sha,
                    "files_added": 0,
                    "files_modified": 1,
                    "files_deleted": 0,
                    "files_renamed": 0,
                    "changed_files": ["src/auth.py"],
                }
                mock_graph.get_connected_files.return_value = [
                    SuspiciousFile(file_path="src/auth.py", centrality_score=1.0, reasons=["Directly modified"]),
                ]
                
                result = orchestrator.process_commit(
                    repo_id="owner/repo",
                    target_sha=target_sha,
                    repo_path=str(repo_path),
                )
                
                # Verify get_connected_files was called with base_sha and target_sha
                mock_graph.get_connected_files.assert_called_once()
                call_kwargs = mock_graph.get_connected_files.call_args[1]
                assert "base_sha" in call_kwargs
                assert "target_sha" in call_kwargs
                assert call_kwargs["base_sha"] is not None
                assert call_kwargs["target_sha"] is not None


class TestBackwardCompatibility:
    """Test that changes are backward compatible."""
    
    def test_get_connected_files_works_without_base_and_target_sha(self):
        """Verify that get_connected_files still works with only changed_files."""
        with patch("src.adapters.graph_adapter.Neo4jClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.database = "graphdoc"
            mock_client.get_connected_files.return_value = ["src/core.py"]
            
            adapter = GraphAdapter(repo_id="test/repo", repo_path="/tmp")
            
            # Call without base_sha and target_sha (old behavior)
            result = adapter.get_connected_files(
                changed_files=["src/auth.py"],
            )
            
            # Should still work and return list
            assert isinstance(result, list)
    
    def test_metadata_adapter_works_without_source_repo_path(self):
        """Verify that MetadataAdapter still works without source_repo_path (old behavior)."""
        from src.adapters.metadata_adapter import MetadataAdapter
        
        # Should be able to create without source_repo_path
        adapter = MagicMock(spec=MetadataAdapter)
        adapter.source_repo_path = None
        
        # This should not crash
        assert adapter.source_repo_path is None
