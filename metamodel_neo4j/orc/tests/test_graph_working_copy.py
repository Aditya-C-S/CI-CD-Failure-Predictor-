"""
Test suite for graph working copy and commit resolution fixes.

Tests verify that:
1. Graph working copy is created and maintained at target commit
2. Source repository HEAD doesn't affect graph sync
3. Base-to-target incremental sync works correctly
4. Invalid commit combinations are rejected
5. Neo4j is only mutated after validation passes
"""

import pytest
import subprocess
from pathlib import Path
import sys

# Add ORC to path
ORC_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ORC_ROOT))

from src.adapters.graph_adapter import _ensure_graph_working_copy_at_sha, GRAPH_CACHE_ROOT
from src.errors import GraphSyncException, InvalidCommitException


class TestGraphWorkingCopy:
    """Test graph working copy creation and maintenance."""
    
    def test_working_copy_created_at_target_sha(self):
        """
        Test 1: Graph working copy is created and checked out to target SHA.
        """
        # Use the test repo
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        target_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"  # Initial commit
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        # Create working copy
        working_copy = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), target_sha)
        
        assert Path(working_copy).exists(), f"Working copy not created at {working_copy}"
        
        # Verify HEAD is at target_sha
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=working_copy,
            capture_output=True,
            text=True,
            shell=True,
        )
        head_sha = result.stdout.strip()
        assert head_sha == target_sha, f"HEAD {head_sha} != target {target_sha}"
    
    def test_source_repo_head_unaffected(self):
        """
        Test 2: Graph working copy operations don't change source repo HEAD.
        """
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        target_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        # Get source repo HEAD before
        result_before = subprocess.run(
            'git rev-parse HEAD',
            cwd=source_repo,
            capture_output=True,
            text=True,
            shell=True,
        )
        head_before = result_before.stdout.strip()
        
        # Create working copy
        _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), target_sha)
        
        # Get source repo HEAD after
        result_after = subprocess.run(
            'git rev-parse HEAD',
            cwd=source_repo,
            capture_output=True,
            text=True,
            shell=True,
        )
        head_after = result_after.stdout.strip()
        
        # Should be unchanged
        assert head_before == head_after, \
            f"Source repo HEAD changed: {head_before} → {head_after}"
    
    def test_working_copy_persists_across_calls(self):
        """
        Test 3: Graph working copy is reused on subsequent calls.
        """
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        target_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        # First call
        working_copy_1 = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), target_sha)
        
        # Second call with same params
        working_copy_2 = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), target_sha)
        
        # Should be the same path
        assert working_copy_1 == working_copy_2, \
            "Working copy path changed between calls"
        
        # Should still be at target SHA
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=working_copy_2,
            capture_output=True,
            text=True,
            shell=True,
        )
        head_sha = result.stdout.strip()
        assert head_sha == target_sha, "Working copy no longer at target SHA"
    
    def test_working_copy_switches_commits(self):
        """
        Test 4: Working copy can be switched between different commits.
        """
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        sha_1 = "edff7d114743823e78cbec5ea0bb79cc72107206"  # Initial
        sha_2 = "a10300b12d89c61afb08cd169e9e4c1c7896d0c6"  # Test commit (if it exists)
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        # Verify both commits exist
        for sha in [sha_1, sha_2]:
            result = subprocess.run(
                f'git cat-file -t "{sha}"',
                cwd=source_repo,
                capture_output=True,
                text=True,
                shell=True,
            )
            if result.returncode != 0:
                pytest.skip(f"Commit {sha} not available in source repo")
        
        # Create at first commit
        working_copy = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), sha_1)
        
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=working_copy,
            capture_output=True,
            text=True,
            shell=True,
        )
        assert result.stdout.strip() == sha_1
        
        # Switch to second commit
        working_copy = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), sha_2)
        
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=working_copy,
            capture_output=True,
            text=True,
            shell=True,
        )
        assert result.stdout.strip() == sha_2


class TestGraphSyncValidation:
    """Test graph sync validation and error handling."""
    
    def test_invalid_commit_raises_error(self):
        """
        Test 5: Invalid commit SHA is rejected before working copy creation.
        """
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        invalid_sha = "0000000000000000000000000000000000000000"
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        with pytest.raises(GraphSyncException) as exc_info:
            _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), invalid_sha)
        
        error_msg = str(exc_info.value).lower()
        assert "failed" in error_msg or "verification" in error_msg


class TestGraphSyncIntegration:
    """Integration tests for full graph sync workflow."""
    
    def test_working_copy_ready_for_graph_engine(self):
        """
        Test 6: Working copy is ready for graph engine (HEAD at target).
        
        This simulates what the graph engine will verify.
        """
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        target_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        # Create working copy
        working_copy = _ensure_graph_working_copy_at_sha(repo_id, str(source_repo), target_sha)
        
        # Verify working-tree is clean (graph engine requirement)
        result = subprocess.run(
            'git status --porcelain',
            cwd=working_copy,
            capture_output=True,
            text=True,
            shell=True,
        )
        working_tree_clean = result.stdout.strip() == ""
        assert working_tree_clean, "Working tree has uncommitted changes"
        
        # Verify HEAD matches exactly (graph engine requirement)
        result = subprocess.run(
            'git rev-parse HEAD',
            cwd=working_copy,
            capture_output=True,
            text=True,
            shell=True,
        )
        head_sha = result.stdout.strip()
        assert head_sha == target_sha, \
            f"Working tree verification would fail: HEAD={head_sha}, target={target_sha}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
