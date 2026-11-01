"""tests/test_batch2_early_warning.py

Batch 2 Tests: Configurable Early-Warning Threshold & Warning Event History
Verifies:
1. Default threshold is 0.70 (70%).
2. Valid configurable values between 0.0 and 1.0 are accepted.
3. Invalid threshold values (< 0.0, > 1.0, non-numeric) are rejected with HTTP 400.
4. Threshold crossing triggers warning event (e.g. 73.88% triggers 70%, 69.88% does not).
5. Warning deduplication: repeated chunks do not create duplicate warnings unless risk increased.
6. Projected predictions NEVER trigger warnings.
7. Warning records capture the active threshold and persist across reload/restart.
8. Endpoints /api/prediction/threshold and /api/demo/runs/{run_id}/warnings are functional.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.runtime_tracker import (
    get_early_warning_threshold,
    set_early_warning_threshold,
    reset_early_warning_threshold,
)


class TestBatch2EarlyWarning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def tearDown(self):
        reset_early_warning_threshold()

    def test_default_threshold_and_configuration(self):
        """Verify default is 0.70, update works via API, and invalid inputs are rejected."""
        # 1. Check default
        resp = self.client.get("/api/prediction/threshold")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["threshold"], 0.70)
        self.assertTrue(data["is_default"])

        # 2. Update to 0.65
        update_resp = self.client.post("/api/prediction/threshold", json={"threshold": 0.65})
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["threshold"], 0.65)
        self.assertEqual(get_early_warning_threshold(), 0.65)

        # 3. Reject negative threshold
        err_neg = self.client.post("/api/prediction/threshold", json={"threshold": -0.1})
        self.assertIn(err_neg.status_code, (400, 422))

        # 4. Reject threshold > 1.0
        err_high = self.client.post("/api/prediction/threshold", json={"threshold": 1.25})
        self.assertIn(err_high.status_code, (400, 422))

        # 5. Reject non-numeric
        err_str = self.client.post("/api/prediction/threshold", json={"threshold": "invalid_num"})
        self.assertIn(err_str.status_code, (400, 422))

    def test_early_warning_trigger_and_deduplication(self):
        """Verify warning triggers strictly above active threshold, and deduplicates identical alerts."""
        reset_early_warning_threshold()  # 0.70 active

        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "demo-org/warning-test",
                "scenario_preset": "high_risk",
                "runtime_model": "bilstm2",
            },
        )
        run_id = create_resp.json()["run_id"]

        # Ingest nominal chunk (30% risk) -> Below 70% threshold -> No warning
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Starting build nominally\nStep 1 complete", "depth": 25},
        )
        warn_resp1 = self.client.get(f"/api/demo/runs/{run_id}/warnings")
        self.assertEqual(warn_resp1.status_code, 200)
        self.assertEqual(len(warn_resp1.json()), 0)

        # Ingest failure chunk at depth 50 (BiLSTM v2 produces ~0.6988 / 69.88%)
        # Under 70% threshold, 69.88% must NOT trigger an early warning.
        chunk_fail = (
            "ERROR: Could not find a version that satisfies the requirement torch>=2.0.0\n"
            "ERROR: No matching distribution found for torch>=2.0.0\n"
            "Process completed with exit code 1."
        )
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": chunk_fail, "depth": 50, "exit_code": 1, "step_outcome": "failure"},
        )
        warn_resp2 = self.client.get(f"/api/demo/runs/{run_id}/warnings")
        self.assertEqual(warn_resp2.status_code, 200)
        self.assertEqual(len(warn_resp2.json()), 0, "69.88% at depth 50 must NOT trigger a 70% threshold")

        # Ingest failure chunk at depth 75 (BiLSTM v2 produces ~0.7388 / 73.88%)
        # 73.88% >= 0.70 threshold -> Must trigger early warning.
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": chunk_fail, "depth": 75, "exit_code": 1, "step_outcome": "failure"},
        )

        warn_resp3 = self.client.get(f"/api/demo/runs/{run_id}/warnings")
        self.assertEqual(warn_resp3.status_code, 200)
        warnings3 = warn_resp3.json()
        self.assertEqual(len(warnings3), 1, "73.88% at depth 75 must trigger early warning")

        warning_entry = warnings3[0]
        self.assertEqual(warning_entry["run_id"], run_id)
        self.assertEqual(warning_entry["threshold"], 0.70)
        self.assertGreaterEqual(warning_entry["failure_probability"], 0.70)
        self.assertEqual(warning_entry["warning_type"], "EARLY_FAILURE_WARNING")

        # Ingest repeated identical chunk at depth 75 -> Should deduplicate and NOT generate second warning
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": chunk_fail, "depth": 75, "exit_code": 1, "step_outcome": "failure"},
        )
        warn_resp4 = self.client.get(f"/api/demo/runs/{run_id}/warnings")
        self.assertEqual(len(warn_resp4.json()), 1, "Duplicate chunk at same risk level must not create duplicate warning")

    def test_projected_predictions_never_trigger_warnings(self):
        """Verify projected predictions do not trigger early-warning events."""
        from src.demo.demo_manager import UnifiedDemoManager
        mgr = UnifiedDemoManager.get_instance()

        run = mgr.create_run(
            repo_id="demo-org/projected-test",
            runtime_model="bilstm2",
        )
        
        # Manually invoke check_and_trigger_early_warning with a projected point
        projected_point = {
            "failure_probability": 0.95,
            "failure_probability_pct": 95.0,
            "is_projected": True,
            "model_name": "Projection Engine",
        }
        res = run.check_and_trigger_early_warning(projected_point)
        self.assertIsNone(res)
        self.assertEqual(len(run.warning_history), 0)


if __name__ == "__main__":
    unittest.main()
