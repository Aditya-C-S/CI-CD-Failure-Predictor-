#!/usr/bin/env python3
"""
REAL End-to-End Test: Dual Repository Isolation

This test creates TWO separate repositories with:
- Identical relative file paths
- Different call relationships
- Both synced to the same Neo4j instance
- Verification that no cross-repo contamination occurs

Test passes ONLY if:
1. Both repos create nodes with correct repo_id
2. Query for repo1 returns only repo1 nodes (0 repo2 nodes)
3. Query for repo2 returns only repo2 nodes (0 repo1 nodes)

Requirements:
- Live Neo4j instance at NEO4J_URI pointing to 'graphdoc' database
- graph-doc-gen available at ../graph-doc-gen-main
- pytest to run as proper test (not module-level execution)
"""

import sys
import os
import subprocess
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch
import importlib

# CRITICAL: Unmock database module for real integration test
# The global conftest.py mocks database.neo4j_client for unit tests,
# but we need the real Neo4j client for integration testing
if "database" in sys.modules:
    del sys.modules["database"]
if "database.neo4j_client" in sys.modules:
    del sys.modules["database.neo4j_client"]

# Setup paths
ORC_ROOT = Path.cwd()
GRAPH_DOC_GEN_ROOT = Path.cwd() / ".." / "graph-doc-gen-main"
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT.absolute()))

try:
    from src.adapters.graph_adapter import GraphAdapter
    from src.errors import GraphSyncException
    HAS_GRAPH_ADAPTER = True
except ImportError:
    HAS_GRAPH_ADAPTER = False
import logging

logger = logging.getLogger(__name__)


def is_neo4j_available() -> bool:
    """
    Check if Neo4j is available at the configured URI.
    
    Returns:
        True if Neo4j is reachable, False otherwise
    """
    try:
        from neo4j import GraphDatabase
        from dotenv import load_dotenv
        
        load_dotenv()
        uri = os.getenv("NEO4J_URI")
        username = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        database = os.getenv("NEO4J_DATABASE")
        
        if not all([uri, username, password, database]):
            logger.warning("Neo4j credentials not fully configured in .env")
            return False
        
        if database != "graphdoc":
            logger.warning(f"NEO4J_DATABASE={database}, expected 'graphdoc'")
            return False
        
        # Try to connect
        driver = GraphDatabase.driver(uri, auth=(username, password))
        with driver.session(database=database) as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception as e:
        logger.warning(f"Neo4j availability check failed: {e}")
        return False


pytestmark = pytest.mark.skipif(
    not is_neo4j_available() or not HAS_GRAPH_ADAPTER,
    reason="Live Neo4j instance + graph-doc-gen required for real integration test"
)


class TestDualRepoIsolationReal:
    """Real end-to-end test with live Neo4j."""
    
    @pytest.fixture(autouse=True)
    def _setup_and_teardown(self):
        """Setup and teardown for all tests."""
        # Setup: Create repositories
        self.repo1_path = Path(tempfile.mkdtemp(prefix="repo1_"))
        self.repo1_id = "company/repo-first"
        
        subprocess.run(["git", "init"], cwd=self.repo1_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.repo1_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo1_path, check=True, capture_output=True)
        
        # Create base commit for repo1
        (self.repo1_path / "helpers.py").write_text("def helper_func():\n    return 42\n")
        subprocess.run(["git", "add", "."], cwd=self.repo1_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.repo1_path, check=True, capture_output=True)
        
        self.repo1_base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo1_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Add caller in repo1
        (self.repo1_path / "main.py").write_text(
            "from helpers import helper_func\n"
            "def caller():\n"
            "    return helper_func()\n"
        )
        subprocess.run(["git", "add", "."], cwd=self.repo1_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add caller"], cwd=self.repo1_path, check=True, capture_output=True)
        
        self.repo1_target_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo1_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Setup repo2
        self.repo2_path = Path(tempfile.mkdtemp(prefix="repo2_"))
        self.repo2_id = "company/repo-second"
        
        subprocess.run(["git", "init"], cwd=self.repo2_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.repo2_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo2_path, check=True, capture_output=True)
        
        # Create base commit for repo2
        (self.repo2_path / "helpers.py").write_text("def helper_func():\n    return 'repo2'\n")
        subprocess.run(["git", "add", "."], cwd=self.repo2_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.repo2_path, check=True, capture_output=True)
        
        self.repo2_base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo2_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Add different main.py that doesn't import helpers (different relationship)
        (self.repo2_path / "main.py").write_text(
            "def main():\n"
            "    print('main')\n"
        )
        subprocess.run(["git", "add", "."], cwd=self.repo2_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add main without import"], cwd=self.repo2_path, check=True, capture_output=True)
        
        self.repo2_target_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo2_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        
        # Initialize adapters
        self.adapter1 = None
        self.adapter2 = None
        
        yield  # Run tests
        
        # Teardown: Close adapters and remove temp repos
        import shutil
        
        if self.adapter1:
            self.adapter1.close()
        if self.adapter2:
            self.adapter2.close()
        
        shutil.rmtree(self.repo1_path, ignore_errors=True)
        shutil.rmtree(self.repo2_path, ignore_errors=True)
    
    def test_01_setup_repositories(self):
        """Test 1: Verify repositories were set up."""
        assert self.repo1_path.exists(), "Repo1 creation failed"
        assert (self.repo1_path / "main.py").exists(), "Repo1 main.py not created"
        assert (self.repo1_path / "helpers.py").exists(), "Repo1 helpers.py not created"
        
        assert self.repo2_path.exists(), "Repo2 creation failed"
        assert (self.repo2_path / "main.py").exists(), "Repo2 main.py not created"
        assert (self.repo2_path / "helpers.py").exists(), "Repo2 helpers.py not created"
    
    def test_02_sync_both_repositories(self):
        """Test 2: Sync both repos to Neo4j."""
        # Initialize adapters
        self.adapter1 = GraphAdapter(repo_id=self.repo1_id, repo_path=str(self.repo1_path))
        self.adapter2 = GraphAdapter(repo_id=self.repo2_id, repo_path=str(self.repo2_path))
        
        # Sync repo1
        result1 = self.adapter1.sync_to_sha(self.repo1_base_sha, self.repo1_target_sha)
        assert result1["status"] == "success", f"Repo1 sync failed: {result1}"
        assert result1["repo_id"] == self.repo1_id, f"Repo1 ID mismatch: {result1['repo_id']}"
        
        # Sync repo2
        result2 = self.adapter2.sync_to_sha(self.repo2_base_sha, self.repo2_target_sha)
        assert result2["status"] == "success", f"Repo2 sync failed: {result2}"
        assert result2["repo_id"] == self.repo2_id, f"Repo2 ID mismatch: {result2['repo_id']}"
    
    def test_03_query_isolation_repo1(self):
        """Test 3: Verify repo1 query shows no cross-repo contamination."""
        # Query: "For repo1, get all Functions"
        with self.adapter1.client.session() as session:
            result = session.run("""
                MATCH (fn:Function {repo_id: $repo_id})
                RETURN COUNT(fn) as func_count
            """, repo_id=self.repo1_id)
            
            record = result.single()
            repo1_func_count = record["func_count"]
            
            # Query cross-repo contamination check
            result = session.run("""
                MATCH (fn:Function)
                WHERE fn.repo_id IS NOT NULL AND fn.repo_id <> $repo_id
                RETURN COUNT(fn) as other_repo_funcs
            """, repo_id=self.repo1_id)
            
            record = result.single()
            cross_repo_count = record["other_repo_funcs"]
        
        assert repo1_func_count > 0, "Repo1 should have synced functions"
        assert cross_repo_count == 0, f"Repo1 query sees {cross_repo_count} nodes from other repos (expected 0)"
    
    def test_04_query_isolation_repo2(self):
        """Test 4: Verify repo2 query shows no cross-repo contamination."""
        # Query: "For repo2, get all Functions"
        with self.adapter2.client.session() as session:
            result = session.run("""
                MATCH (fn:Function {repo_id: $repo_id})
                RETURN COUNT(fn) as func_count
            """, repo_id=self.repo2_id)
            
            record = result.single()
            repo2_func_count = record["func_count"]
            
            # Query cross-repo contamination check
            result = session.run("""
                MATCH (fn:Function)
                WHERE fn.repo_id IS NOT NULL AND fn.repo_id <> $repo_id
                RETURN COUNT(fn) as other_repo_funcs
            """, repo_id=self.repo2_id)
            
            record = result.single()
            cross_repo_count = record["other_repo_funcs"]
        
        assert repo2_func_count > 0, "Repo2 should have synced functions"
        assert cross_repo_count == 0, f"Repo2 query sees {cross_repo_count} nodes from other repos (expected 0)"
    
    def test_05_relationship_verification(self):
        """Test 5: Verify relationship structures differ between repos."""
        # Check calls relationships in repo1
        with self.adapter1.client.session() as session:
            result = session.run("""
                MATCH (caller)-[r:CALLS]->(callee)
                WHERE caller.repo_id = $repo_id AND callee.repo_id = $repo_id
                RETURN COUNT(r) as calls_count
            """, repo_id=self.repo1_id)
            
            record = result.single()
            repo1_calls = record["calls_count"] or 0
        
        # Check calls relationships in repo2
        with self.adapter2.client.session() as session:
            result = session.run("""
                MATCH (caller)-[r:CALLS]->(callee)
                WHERE caller.repo_id = $repo_id AND callee.repo_id = $repo_id
                RETURN COUNT(r) as calls_count
            """, repo_id=self.repo2_id)
            
            record = result.single()
            repo2_calls = record["calls_count"] or 0
        
        # Repo1 should have caller->callee relationship, repo2 should not
        assert repo1_calls > 0, "Repo1 should have CALLS relationships (caller -> callee)"
        assert repo2_calls == 0, "Repo2 should have NO CALLS relationships (main has no imports)"


if __name__ == "__main__":
    # Not meant to be run directly. Use pytest:
    # pytest test_dual_repo_isolation_real.py -v
    import sys
    print("This test is meant to be run with pytest, not directly.")
    print("Usage: pytest test_dual_repo_isolation_real.py -v")
    print("")
    print("Note: Requires a live Neo4j instance at NEO4J_URI targeting 'graphdoc' database.")
    sys.exit(0)
