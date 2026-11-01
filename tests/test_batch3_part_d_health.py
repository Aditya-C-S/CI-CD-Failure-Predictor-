"""tests/test_batch3_part_d_health.py

Batch 3 Part D Tests: System Health, Diagnostics & End-to-End Validation
Verifies:
1. /api/health/system endpoint responsiveness and structure.
2. Neo4j connectivity reporting (5.25.1 version, graphdoc database).
3. Degraded mode reporting when Neo4j is simulated offline with active Tree-Sitter fallback.
4. Independent verification of all 3 runtime models (BiLSTM v2, SVM, Logistic Regression).
5. Metadata model health and 38-feature schema compatibility.
6. Log ingestion subsystem readiness.
7. Persistence subsystem directory write check.
8. Overall status calculation (HEALTHY vs DEGRADED vs UNHEALTHY).
9. Strict credential safety: no secrets, API keys, or passwords in health output.
"""

import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.metadata_service import MetadataService
from src.diagnostics.system_health import SystemHealthService, OverallStatus


class TestBatch3PartDHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def test_system_health_endpoint_structure_and_components(self):
        """Verify GET /api/health/system returns all 6 component subsystems."""
        resp = self.client.get("/api/health/system")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("status", data)
        self.assertIn("timestamp", data)
        self.assertIn("components", data)

        comps = data["components"]
        self.assertIn("backend", comps)
        self.assertIn("neo4j", comps)
        self.assertIn("runtime_models", comps)
        self.assertIn("metadata_model", comps)
        self.assertIn("log_ingestion", comps)
        self.assertIn("persistence", comps)

        # 1. Backend
        self.assertEqual(comps["backend"]["status"], "HEALTHY")

        # 2. Metadata Model
        self.assertEqual(comps["metadata_model"]["status"], "HEALTHY")
        self.assertEqual(comps["metadata_model"]["feature_contract"], "38_features_strict")

        # 3. Runtime Models (all 3 independently present)
        models = comps["runtime_models"]
        self.assertEqual(models["bilstm2"]["status"], "HEALTHY")
        self.assertEqual(models["svm"]["status"], "HEALTHY")
        self.assertEqual(models["logistic_regression"]["status"], "HEALTHY")

        # 4. Ingestion
        self.assertEqual(comps["log_ingestion"]["status"], "HEALTHY")
        self.assertTrue(comps["log_ingestion"]["deduplication_enabled"])

        # 5. Persistence
        self.assertEqual(comps["persistence"]["status"], "HEALTHY")
        self.assertTrue(comps["persistence"]["writable"])

    def test_zero_credentials_or_passwords_leakage(self):
        """Verify no passwords, tokens, or raw secrets are present anywhere in health response."""
        resp = self.client.get("/api/health/system")
        self.assertEqual(resp.status_code, 200)
        raw_text = resp.text.lower()

        # Check for forbidden sensitive keywords in JSON values
        self.assertNotIn("password", raw_text)
        self.assertNotIn("secret", raw_text)
        self.assertNotIn("ghp_", raw_text)
        self.assertNotIn("gho_", raw_text)

        # Check neo4j username/password specifically
        neo4j_pass = os.getenv("NEO4J_PASSWORD")
        if neo4j_pass:
            self.assertNotIn(neo4j_pass.lower(), raw_text)

    def test_neo4j_online_or_degraded_fallback_mode(self):
        """Verify Neo4j returns HEALTHY if online, or DEGRADED with Tree-Sitter fallback if offline."""
        data = SystemHealthService.get_system_health()
        neo = data["components"]["neo4j"]

        if neo["mode"] == "ONLINE":
            self.assertEqual(neo["status"], "HEALTHY")
            self.assertEqual(neo["version"], "5.25.1")
            self.assertEqual(data["status"], OverallStatus.HEALTHY)
        else:
            # If offline, must report DEGRADED and Tree-Sitter active
            self.assertEqual(neo["status"], "DEGRADED")
            self.assertEqual(neo["mode"], "FALLBACK_AST")
            self.assertEqual(data["status"], OverallStatus.DEGRADED)

    def test_simulated_offline_neo4j_yields_degraded_status(self):
        """Verify when Neo4j is offline, overall status is DEGRADED rather than crashing or UNHEALTHY."""
        with patch.object(
            MetadataService,
            "get_graph_status",
            return_value={"status": "OFFLINE", "mode": "FALLBACK_AST", "message": "Simulated offline"},
        ):
            health = SystemHealthService.get_system_health()
            self.assertEqual(health["components"]["neo4j"]["status"], "DEGRADED")
            self.assertEqual(health["status"], OverallStatus.DEGRADED)


if __name__ == "__main__":
    unittest.main()
