"""tests/test_batch1_neo4j.py

Batch 1 Integration Tests: Neo4j 5.25.1 Community Engine & Health
Verifies:
1. Live Bolt connection to local Neo4j 5.25.1 using existing .env credentials.
2. Basic Cypher query execution (RETURN 1 AS result).
3. MetadataService.get_graph_status() online reporting, version, edition, and database.
4. Repository isolation in graph queries.
5. Graceful fallback when Neo4j is offline or unavailable.
"""

import os
import unittest
from unittest.mock import patch

from src.prediction.metadata_service import MetadataService


class TestBatch1Neo4jIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = MetadataService.get_instance()

    def test_live_neo4j_connectivity(self):
        """Verify official neo4j driver connects and executes a basic Cypher query."""
        from database.neo4j_client import Neo4jClient

        client = Neo4jClient()
        try:
            client.driver.verify_connectivity()
            with client.session() as session:
                res = session.run("RETURN 1 AS result").single()
                self.assertIsNotNone(res)
                self.assertEqual(res["result"], 1)
        finally:
            client.close()

    def test_get_graph_status_live_engine(self):
        """Verify get_graph_status reports ONLINE with version 5.25.1, edition community, and node counts."""
        status = self.service.get_graph_status()
        self.assertEqual(status["status"], "ONLINE")
        self.assertTrue(status["connected"])
        self.assertIn("5.25", status["version"])
        self.assertEqual(status["edition"].lower(), "community")
        self.assertEqual(status["database"], "graphdoc")
        self.assertGreater(status["node_count"], 0)
        self.assertGreater(status["edge_count"], 0)
        self.assertIsInstance(status["repositories"], list)
        self.assertIn("msiemens/tinydb", status["repositories"])

    def test_repository_isolation_blast_radius(self):
        """Verify blast radius queries stay strictly isolated to the specified repository."""
        # Query tinydb
        res_tinydb = self.service.analyze_blast_radius(
            repo_id="msiemens/tinydb",
            changed_files=["tinydb/database.py"]
        )
        self.assertEqual(res_tinydb["repo_id"], "msiemens/tinydb")
        for aff in res_tinydb.get("affected_files", []):
            self.assertFalse(aff["file_path"].startswith("sample/"))

        # Query sample/test-repo
        res_sample = self.service.analyze_blast_radius(
            repo_id="sample/test-repo",
            changed_files=["utils.py"]
        )
        self.assertEqual(res_sample["repo_id"], "sample/test-repo")

    def test_offline_fallback_resilience(self):
        """Verify graceful fallback without unhandled exceptions when Neo4j is unreachable."""
        with patch("database.neo4j_client.GraphDatabase.driver") as mock_driver_fn:
            mock_driver = mock_driver_fn.return_value
            mock_driver.verify_connectivity.side_effect = ConnectionRefusedError("Simulated offline port 7687")
            status = self.service.get_graph_status()
            self.assertEqual(status["status"], "OFFLINE")
            self.assertFalse(status["connected"])
            self.assertIn("offline or unreachable", status["message"])


if __name__ == "__main__":
    unittest.main()
