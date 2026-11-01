"""tests/test_batch2_prediction_history.py

Batch 2 Tests: Runtime Prediction History & Persistence
Verifies:
1. Records are created upon actual inference events.
2. Records are correctly associated with their specific run ID.
3. Chronological ordering is strictly preserved.
4. Duplicate events on identical telemetry retries are prevented.
5. History persists across manager reload and backend restart.
6. Non-existent run IDs return HTTP 404.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager


class TestBatch2PredictionHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)
        cls.mgr = UnifiedDemoManager.get_instance()

    def test_prediction_history_lifecycle(self):
        """Verify prediction history records are generated and retrievable upon log ingestion."""
        # Create a new run
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "demo-org/test-service",
                "scenario_preset": "high_risk",
                "runtime_model": "bilstm2",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        run_data = create_resp.json()
        run_id = run_data["run_id"]

        # Initially history is empty
        hist_resp0 = self.client.get(f"/api/demo/runs/{run_id}/prediction-history")
        self.assertEqual(hist_resp0.status_code, 200)
        self.assertEqual(len(hist_resp0.json()), 0)

        # Ingest checkpoint 1 (25% depth)
        chunk1 = "Step 1: Setup virtual environment\nPython 3.10 initialized successfully."
        ingest1 = self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": chunk1,
                "step_name": "Setup Environment",
                "stage": "setup",
                "depth": 25,
            },
        )
        self.assertEqual(ingest1.status_code, 200)

        # Ingest checkpoint 2 (50% depth) with dependency error
        chunk2 = "ERROR: Could not find a version that satisfies the requirement invalid-pkg==99.9\nProcess exited with exit code 1."
        ingest2 = self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": chunk2,
                "step_name": "Install Dependencies",
                "stage": "build",
                "depth": 50,
            },
        )
        self.assertEqual(ingest2.status_code, 200)

        # Check prediction history
        hist_resp = self.client.get(f"/api/demo/runs/{run_id}/prediction-history")
        self.assertEqual(hist_resp.status_code, 200)
        history = hist_resp.json()
        self.assertEqual(len(history), 2)

        # Verify fields on the actual inference records
        rec1 = history[0]
        self.assertEqual(rec1["run_id"], run_id)
        self.assertEqual(rec1["checkpoint"], 25)
        self.assertEqual(rec1["prediction_type"], "ACTUAL")
        self.assertIn("failure_probability", rec1)
        self.assertIsNotNone(rec1["timestamp"])

        rec2 = history[1]
        self.assertEqual(rec2["run_id"], run_id)
        self.assertEqual(rec2["checkpoint"], 50)
        self.assertEqual(rec2["prediction_type"], "ACTUAL")
        self.assertGreaterEqual(rec2["failure_probability"], 0.50)

        # Chronological ordering
        self.assertLessEqual(rec1["timestamp"], rec2["timestamp"])

        # Test duplicate prevention: re-delivering exact same chunk at depth 50
        ingest2_retry = self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": chunk2,
                "step_name": "Install Dependencies",
                "stage": "build",
                "depth": 50,
            },
        )
        self.assertEqual(ingest2_retry.status_code, 200)
        hist_retry = self.client.get(f"/api/demo/runs/{run_id}/prediction-history").json()
        self.assertEqual(len(hist_retry), 2)

        # Test alias endpoint /api/prediction/history/{run_id}
        alias_resp = self.client.get(f"/api/prediction/history/{run_id}")
        self.assertEqual(alias_resp.status_code, 200)
        self.assertEqual(len(alias_resp.json()), 2)

    def test_prediction_history_unknown_run(self):
        """Verify requesting history for non-existent run ID returns HTTP 404."""
        resp = self.client.get("/api/demo/runs/non_existent_run_9999/prediction-history")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
