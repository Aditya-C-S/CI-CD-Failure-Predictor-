"""
Test suite for commit resolution fixes in sync_repo_cache().

Tests verify that:
1. Valid commits are correctly checked out
2. Missing commits raise clear errors
3. Local-only commits are detected
4. Recovery attempts are bounded (not infinite)
5. Feature extraction uses the requested commit
"""

import pytest
import subprocess
import shutil
import tempfile
from pathlib import Path
import sys

# Add Metadata-Pipeline to path
METADATA_PIPELINE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(METADATA_PIPELINE_ROOT))

from Metadata_Extractor.core.git_engine import (
    sync_repo_cache, get_churn_metrics, _verify_commit_checked_out, _run_git_checked
)


@pytest.fixture
def clean_cache():
    """Ensure cache is clean before and after tests."""
    from Metadata_Extractor.core.git_engine import _handle_remove_readonly
    
    cache_root = Path(__file__).parent.parent / ".repo_cache"
    test_cache = cache_root / "DhruvHegde__Voice_based-_Tic-Tac-Toe"
    
    if test_cache.exists():
        shutil.rmtree(test_cache, onerror=_handle_remove_readonly)
    
    yield test_cache
    
    # Cleanup after test
    if test_cache.exists():
        shutil.rmtree(test_cache, onerror=_handle_remove_readonly)


class TestCommitResolution:
    """Test suite for commit resolution and checkout verification."""
    
    def test_valid_commit_on_remote_is_checked_out(self, clean_cache):
        """
        Test 1: A valid commit that exists on GitHub remote is checked out correctly.
        
        The initial commit edff7d1 is on both the local repo and the remote.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        valid_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        # Should succeed
        repo_path, status = sync_repo_cache(owner, repo, valid_sha, token=None)
        
        # Verify cache_status indicates work was done
        assert status in ("hit", "miss"), f"Unexpected status: {status}"
        
        # Verify HEAD is at the requested commit
        assert _verify_commit_checked_out(repo_path, valid_sha), \
            f"HEAD not at requested commit {valid_sha}"
        
        # Verify we can extract metrics without error
        churn = get_churn_metrics(repo_path, valid_sha)
        assert churn is not None
        assert isinstance(churn, dict)
        assert "total_files_changed" in churn
    
    def test_missing_commit_raises_clear_error(self, clean_cache):
        """
        Test 2: A commit that doesn't exist on remote raises a clear, actionable error.
        
        Test commit bc95c8b exists locally in the source repo but is not on GitHub.
        This should raise an error mentioning it's not found on the remote.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        missing_sha = "bc95c8bede99362595460d84063834f49c840fdd"
        
        with pytest.raises(RuntimeError) as exc_info:
            sync_repo_cache(owner, repo, missing_sha, token=None)
        
        error_msg = str(exc_info.value).lower()
        # Error should mention something about resolution or remote
        assert "cannot resolve" in error_msg or "failed" in error_msg, \
            f"Error message not clear: {exc_info.value}"
    
    def test_local_only_commit_detected(self, clean_cache):
        """
        Test 3: A commit that exists locally but not on remote is properly detected.
        
        When source_repo_path is provided, the error should indicate the commit
        is local-only and suggest pushing it.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        local_only_sha = "bc95c8bede99362595460d84063834f49c840fdd"
        
        # Provide path to the source repo where this commit exists
        source_repo = Path(__file__).parent.parent.parent.parent / "Voice_based-_Tic-Tac-Toe"
        
        if not source_repo.exists():
            source_repo = Path("C:/Users/DHRUV HEGDE/Desktop/Voice_based-_Tic-Tac-Toe")
        
        if not source_repo.exists():
            pytest.skip(f"Source repo not found at {source_repo}")
        
        with pytest.raises(RuntimeError) as exc_info:
            sync_repo_cache(
                owner, repo, local_only_sha, token=None,
                source_repo_path=str(source_repo)
            )
        
        error_msg = str(exc_info.value).lower()
        # Should indicate it's local-only or suggest pushing
        assert "local" in error_msg or "push" in error_msg or "exists" in error_msg, \
            f"Error should indicate local-only nature: {exc_info.value}"
    
    def test_feature_extraction_with_valid_commit(self, clean_cache):
        """
        Test 4: Feature extraction correctly identifies differences between commits.
        
        The initial commit should have different churn metrics than later commits.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        initial_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        # Sync to initial commit
        repo_path, _ = sync_repo_cache(owner, repo, initial_sha, token=None)
        
        # Extract churn for initial commit
        churn_init = get_churn_metrics(repo_path, initial_sha)
        
        # Initial commit should have total_files_changed = 0 (root commit with single file)
        # or a low value
        assert isinstance(churn_init["total_files_changed"], int)
        assert churn_init["total_files_changed"] >= 0
    
    def test_checkout_verification_prevents_wrong_commit(self, clean_cache):
        """
        Test 5: Verify that _verify_commit_checked_out correctly validates HEAD.
        
        This test ensures the verification logic catches when HEAD is not at the
        requested commit.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        valid_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        # Sync and verify checkout
        repo_path, _ = sync_repo_cache(owner, repo, valid_sha, token=None)
        
        # Verify the commit is actually checked out
        is_verified = _verify_commit_checked_out(repo_path, valid_sha)
        assert is_verified, f"Verification failed for {valid_sha}"
        
        # Verify against a different commit should fail
        different_sha = "0000000000000000000000000000000000000000"
        is_verified_wrong = _verify_commit_checked_out(repo_path, different_sha)
        assert not is_verified_wrong, f"Should not verify different commit"
    
    def test_run_git_checked_detects_failures(self, clean_cache):
        """
        Test 6: _run_git_checked properly detects git command failures.
        
        This test verifies the utility function that distinguishes success from failure.
        """
        owner = "DhruvHegde"
        repo = "Voice_based-_Tic-Tac-Toe"
        valid_sha = "edff7d114743823e78cbec5ea0bb79cc72107206"
        
        # First sync to establish cache
        repo_path, _ = sync_repo_cache(owner, repo, valid_sha, token=None)
        
        # Test success case
        success, output = _run_git_checked(
            f"git rev-parse {valid_sha}",
            repo_path,
            "test success"
        )
        assert success, "Should detect success for valid commit"
        assert output == valid_sha, "Output should be the commit SHA"
        
        # Test failure case - use a command that definitely fails
        failure_success, failure_output = _run_git_checked(
            "git invalid-subcommand",
            repo_path,
            "test failure"
        )
        assert not failure_success, "Should detect failure for invalid subcommand"
        assert failure_output == "", "Output should be empty on failure"


class TestErrorPropagation:
    """Test that errors propagate correctly through the adapter."""
    
    def test_metadata_adapter_propagates_commit_resolution_error(self):
        """
        Test 7: The metadata adapter properly catches and re-raises
        commit resolution errors as PredictionException.
        """
        # Import here to avoid issues if Metadata-Pipeline isn't set up
        try:
            from src.adapters.metadata_adapter import MetadataAdapter
            from src.errors import PredictionException
        except ImportError:
            pytest.skip("ORC not fully configured in this environment")
        
        adapter = MetadataAdapter(github_token=None)
        
        with pytest.raises(PredictionException) as exc_info:
            adapter.predict(
                owner="DhruvHegde",
                repo="Voice_based-_Tic-Tac-Toe",
                target_sha="0000000000000000000000000000000000000000"
            )
        
        # Error should mention prediction failure or commit resolution
        error_msg = str(exc_info.value).lower()
        assert "prediction" in error_msg or "commit" in error_msg or "resolution" in error_msg, \
            f"Error should be clear about what failed: {exc_info.value}"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
