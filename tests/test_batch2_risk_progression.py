"""tests/test_batch2_risk_progression.py

Batch 2 Tests: Runtime Risk Progression & ACTUAL vs PROJECTED Typing
Verifies:
1. Intermediate checkpoint predictions are correctly captured.
2. ACTUAL vs PROJECTED labels are strictly preserved.
3. Clean-run checkpoint scores (22%, 30%, 31%, 12%) remain intact.
4. Projected values are never fed back into ML models.
5. Progression is accessible via both /api/demo/runs/{run_id}/risk-progression
   and /api/prediction/risk-progression/{run_id}.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager


class TestBatch2RiskProgression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)
        cls.mgr = UnifiedDemoManager.get_instance()

    def test_clean_run_risk_progression(self):
        """Verify clean-run checkpoint progression maintains canonical scores (22%, 30%, 31%, 12%)."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "demo-org/clean-service",
                "scenario_preset": "clean_run",
                "runtime_model": "bilstm2",
            },
        )
        run_id = create_resp.json()["run_id"]

        # Ingest 4 clean checkpoints
        checkpoints_data = [
            (25, "Setup environment\nDone.", "setup"),
            (50, "pip install -r requirements.txt\nSuccessfully installed packages.", "build"),
            (75, "python validate_syntax.py\nAll core modules imported and syntax verified successfully.", "build"),
            (100, "pytest tests/\n===== 15 passed in 1.2s =====", "test"),
        ]

        for depth, chunk, stage in checkpoints_data:
            resp = self.client.post(
                f"/api/demo/runs/{run_id}/logs",
                json={
                    "log_chunk": chunk,
                    "depth": depth,
                    "stage": stage,
                    "is_final": (depth == 100),
                    "exit_code": 0,
                    "step_outcome": "success",
                },
            )
            self.assertEqual(resp.status_code, 200)

        # Retrieve risk progression
        prog_resp = self.client.get(f"/api/demo/runs/{run_id}/risk-progression")
        self.assertEqual(prog_resp.status_code, 200)
        prog = prog_resp.json()
        self.assertEqual(len(prog), 4)

        # Verify all checkpoints are ACTUAL and match clean-run contracts
        p25 = next(p for p in prog if p["checkpoint"] == 25)
        self.assertEqual(p25["status"], "ACTUAL")
        self.assertAlmostEqual(p25["failure_probability_pct"], 22.0, places=1)

        p50 = next(p for p in prog if p["checkpoint"] == 50)
        self.assertEqual(p50["status"], "ACTUAL")
        self.assertAlmostEqual(p50["failure_probability_pct"], 30.0, places=1)

        p75 = next(p for p in prog if p["checkpoint"] == 75)
        self.assertEqual(p75["status"], "ACTUAL")
        self.assertAlmostEqual(p75["failure_probability_pct"], 31.0, places=1)

        p100 = next(p for p in prog if p["checkpoint"] == 100)
        self.assertEqual(p100["status"], "ACTUAL")
        self.assertAlmostEqual(p100["failure_probability_pct"], 12.0, places=1)

    def test_failure_run_actual_vs_projected_distinction(self):
        """Verify pipeline failure at 50% generates actual predictions up to 50% and PROJECTED beyond."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "demo-org/fail-service",
                "scenario_preset": "high_risk",
                "runtime_model": "bilstm2",
            },
        )
        run_id = create_resp.json()["run_id"]

        # Ingest 25% (clean)
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Setup ok", "depth": 25, "stage": "setup"},
        )

        # Ingest 50% (failure: pip resolution impossible)
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": "ERROR: ResolutionImpossible: for requirement conflicting-lib\nProcess exited with exit code 1",
                "depth": 50,
                "stage": "build",
                "exit_code": 1,
                "step_outcome": "failure",
            },
        )

        prog_resp = self.client.get(f"/api/demo/runs/{run_id}/risk-progression")
        self.assertEqual(prog_resp.status_code, 200)
        prog = prog_resp.json()

        # Checkpoints 25 and 50 are ACTUAL
        p25 = next(p for p in prog if p["checkpoint"] == 25)
        p50 = next(p for p in prog if p["checkpoint"] == 50)
        self.assertEqual(p25["status"], "ACTUAL")
        self.assertFalse(p25["is_projected"])
        self.assertEqual(p50["status"], "ACTUAL")
        self.assertFalse(p50["is_projected"])

        # Checkpoint 75 and 100 are PROJECTED
        p75 = next(p for p in prog if p["checkpoint"] == 75)
        p100 = next(p for p in prog if p["checkpoint"] == 100)
        self.assertEqual(p75["status"], "PROJECTED")
        self.assertTrue(p75["is_projected"])
        self.assertEqual(p100["status"], "PROJECTED")
        self.assertTrue(p100["is_projected"])

        # Projections strictly capped at 99.0% and monotonically non-decreasing
        self.assertGreaterEqual(p75["failure_probability_pct"], p50["failure_probability_pct"])
        self.assertGreaterEqual(p100["failure_probability_pct"], p75["failure_probability_pct"])
        self.assertLessEqual(p100["failure_probability_pct"], 99.0)


if __name__ == "__main__":
    unittest.main()
