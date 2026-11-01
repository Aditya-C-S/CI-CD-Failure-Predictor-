"""Pytest fixtures for orchestrator tests."""

import os
import sys
import tempfile
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest


# Add src to path
SRC_PATH = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC_PATH))

# Mock heavy external dependencies before importing adapters
sys.modules["code_parser"] = MagicMock()
sys.modules["code_parser.extractor"] = MagicMock()
sys.modules["database"] = MagicMock()
sys.modules["database.neo4j_client"] = MagicMock()
sys.modules["maintenance"] = MagicMock()
sys.modules["maintenance.diff_agent"] = MagicMock()
sys.modules["maintenance.git_utils"] = MagicMock()
sys.modules["Inference_Engine"] = MagicMock()
sys.modules["Inference_Engine.predictor_service"] = MagicMock()
sys.modules["Metadata_Extractor"] = MagicMock()
sys.modules["Metadata_Extractor.main"] = MagicMock()
sys.modules["Metadata_Extractor.core"] = MagicMock()
sys.modules["Metadata_Extractor.core.git_engine"] = MagicMock()
sys.modules["Metadata_Extractor.core.static_analyzer"] = MagicMock()
sys.modules["Metadata_Extractor.core.github_api"] = MagicMock()
sys.modules["Metadata_Extractor.core.ci_analyzer"] = MagicMock()
sys.modules["Metadata_Extractor.schema"] = MagicMock()
sys.modules["Metadata_Extractor.schema.normalizer"] = MagicMock()


@pytest.fixture
def temp_checkpoint_db():
    """Create a temporary isolated SQLite checkpoint database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_checkpoint.db"
        
        # Create schema
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE checkpoints (
                repo_id TEXT NOT NULL,
                target_sha TEXT NOT NULL,
                state TEXT NOT NULL,
                prediction_result TEXT,
                graph_files_changed TEXT,
                graph_sync_result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY (repo_id, target_sha)
            )
        """)
        conn.commit()
        conn.close()
        
        # Patch CheckpointManager to use this database
        from src.storage.checkpoint import CheckpointManager
        original_init = CheckpointManager.__init__
        
        def patched_init(self):
            self.db_path = db_path
        
        CheckpointManager.__init__ = patched_init
        
        yield db_path
        
        # Restore original
        CheckpointManager.__init__ = original_init



@pytest.fixture
def patch_metadata_adapter(mock_predictor_result):
    """Patch MetadataAdapter.predict() to return mock result."""
    with patch("src.adapters.metadata_adapter.MetadataAdapter.predict") as mock_predict:
        mock_predict.return_value = mock_predictor_result
        yield mock_predict


@pytest.fixture
def patch_graph_adapter(mock_graph_sync_result, mock_suspicious_files):
    """Patch GraphAdapter methods."""
    with patch("src.adapters.graph_adapter.GraphAdapter") as MockGraphAdapter:
        instance = MockGraphAdapter.return_value
        instance.sync_to_sha.return_value = mock_graph_sync_result
        instance.get_connected_files.return_value = mock_suspicious_files
        yield instance


@pytest.fixture
def temp_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test_repo"
        repo_path.mkdir()
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True, check=True)
        
        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "add", "README.md"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True, check=True)
        
        yield repo_path


@pytest.fixture
def temp_repo_with_py_file(temp_repo):
    """Create a temporary repository with a Python file."""
    (temp_repo / "hello.py").write_text("""
def hello():
    return "world"

def caller():
    return hello()
""")
    subprocess.run(["git", "add", "hello.py"], cwd=temp_repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Add hello.py"], cwd=temp_repo, capture_output=True, check=True)
    
    return temp_repo


@pytest.fixture
def mock_github_token():
    """Mock GitHub token."""
    return "ghp_test_token_12345"


@pytest.fixture
def mock_predictor_result():
    """Mock prediction result from Metadata-Pipeline."""
    return {
        "failure_probability": 0.42,
        "failure_probability_pct": 42.0,
        "raw_score": 0.42,
        "latency_ms": 3.5,
        "shap_drivers": {
            "positive": [("git_diff_src_churn", 0.15), ("code_churn_density", 0.10)],
            "negative": [("test_to_src_churn_ratio", -0.08)],
        },
        "verdict": "STANDARD GATE",
        "verdict_description": "MODERATE RISK — Proceed with monitoring",
        "thresholds": {
            "FAST_TRACK": 0.25,
            "STANDARD_GATE": 0.50,
            "ELEVATED_RISK": 0.65,
        },
        "owner": "testowner",
        "repo": "testrepo",
        "sha": "abc123def456" * 3,
        "short_sha": "abc123d",
        "cache_status": "hit",
        "features": {col: 0.0 for col in ["gh_is_pr", "gh_lang_python", "git_diff_src_churn"] + ["col_" + str(i) for i in range(35)]},
    }


@pytest.fixture
def mock_graph_sync_result():
    """Mock graph synchronization result."""
    return {
        "status": "SYNCHRONIZED",
        "base_sha": "parent123" * 3,
        "target_sha": "abc123def456" * 3,
        "files_added": 2,
        "files_modified": 3,
        "files_deleted": 1,
        "files_renamed": 0,
        "changed_files": ["src/hello.py", "src/utils.py", "tests/test_hello.py"],
    }


@pytest.fixture
def mock_suspicious_files():
    """Mock suspicious file results."""
    from src.models import SuspiciousFile
    return [
        SuspiciousFile(
            file_path="src/core.py",
            centrality_score=0.85,
            reasons=["Called by 5 modules", "Calls 3 modules"],
        ),
        SuspiciousFile(
            file_path="src/utils.py",
            centrality_score=0.62,
            reasons=["Called by 2 modules"],
        ),
    ]
