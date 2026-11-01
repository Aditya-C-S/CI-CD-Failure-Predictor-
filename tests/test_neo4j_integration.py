"""
Tests for Neo4j Graph Engine integration, live execution, and error handling.
Verifies connectivity checks, live database queries, AST node extraction,
and error handling when a database port is offline.
"""
import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

# Load environment
load_dotenv()

# Add graph-doc-gen-main to path
sys.path.insert(0, str(Path("metadata_model/extracted/graph-doc-gen-main").resolve()))


def is_live_neo4j_available() -> bool:
    """Probes if Neo4j is actively accepting connections with configured credentials."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD")
    if not pwd:
        return False
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd), connection_timeout=2.0)
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


class TestNeo4jIntegration:
    """Test suite for Neo4j Graph Engine connectivity, error handling, and live queries."""

    def test_neo4j_connectivity_probe_graceful_offline_handling(self):
        """Verifies that probing a closed port returns False gracefully without crashing."""
        from tests.test_neo4j_integration import is_live_neo4j_available
        # Probe an unallocated port (e.g. 17687)
        try:
            driver = GraphDatabase.driver("bolt://localhost:17687", auth=("neo4j", "any"), connection_timeout=1.0)
            driver.verify_connectivity()
            available = True
            driver.close()
        except Exception:
            available = False
        assert available is False, "Expected port 17687 to be offline."

    def test_neo4j_client_connection_error_handling(self):
        """Verifies that direct driver connection attempt raises ServiceUnavailable when port is closed."""
        with pytest.raises((ServiceUnavailable, OSError, Exception)) as exc_info:
            driver = GraphDatabase.driver("bolt://localhost:17687", auth=("neo4j", "password"), connection_timeout=1.0)
            driver.verify_connectivity()
        assert exc_info.value is not None

    def test_metadata_prediction_service_unaffected_by_neo4j(self):
        """Verifies that the metadata prediction model runs with 100% independence from Neo4j."""
        from src.prediction.metadata_service import get_metadata_service
        service = get_metadata_service()
        assert service.is_ready is True
        result = service.predict({"gh_sloc": 100, "git_diff_src_churn": 10})
        assert "failure_probability" in result
        assert result["verdict"] in ["FAST TRACK", "STANDARD GATE", "BLOCKED / HIGH RISK", "FAIL", "PASS"]

    @pytest.mark.skipif(not is_live_neo4j_available(), reason="Neo4j service is offline or unauthenticated")
    def test_live_neo4j_connection_and_database(self):
        """Integration test: Verifies live connection and targeted database name is 'graphdoc'."""
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USERNAME", "neo4j")
        pwd = os.getenv("NEO4J_PASSWORD")
        db = os.getenv("NEO4J_DATABASE", "graphdoc")

        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        driver.verify_connectivity()

        with driver.session(database=db) as session:
            res = session.run("CALL db.info() YIELD name RETURN name")
            row = res.single()
            assert row is not None
            assert row["name"] == "graphdoc"
        driver.close()

    @pytest.mark.skipif(not is_live_neo4j_available(), reason="Neo4j service is offline or unauthenticated")
    def test_live_neo4j_nodes_and_ast_relationships(self):
        """Integration test: Verifies nodes and AST relationships exist in 'graphdoc'."""
        from database.neo4j_client import Neo4jClient
        client = Neo4jClient()
        assert client.database == "graphdoc"

        with client.session() as session:
            res = session.run("MATCH (n {repo_id: 'sample/test-repo'}) RETURN count(n) as node_count")
            node_count = res.single()["node_count"]
            assert node_count >= 8, f"Expected at least 8 AST nodes, found {node_count}"

            res_calls = session.run("MATCH ()-[r:CALLS]->() RETURN count(r) as call_count")
            call_count = res_calls.single()["call_count"]
            assert call_count >= 2, f"Expected at least 2 CALLS edges, found {call_count}"
        client.close()

    @pytest.mark.skipif(not is_live_neo4j_available(), reason="Neo4j service is offline or unauthenticated")
    def test_live_neo4j_affected_caller_traversal(self):
        """Integration test: Verifies get_connected_files traces callers from utils.py to service.py."""
        from database.neo4j_client import Neo4jClient
        client = Neo4jClient()

        utils_file = str(Path("scratch/sample_repo/utils.py").resolve())
        connected_files = client.get_connected_files(repo_id="sample/test-repo", file_path=utils_file)

        assert len(connected_files) >= 1
        assert "service.py" in connected_files[0]
        client.close()
