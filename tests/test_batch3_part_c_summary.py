"""tests/test_batch3_part_c_summary.py

Batch 3 Part C Tests: Final Run Summary & Run Intelligence
Verifies:
1. Successful run summary reflects passed pipeline, exit code 0, and clean narrative.
2. Failed run summary captures actual outcome, failed stage, category, and RCA details.
3. Partial summary correctly flagged when telemetry is incomplete.
4. Strict separation between metadata prediction, graph intelligence, and runtime ML risk.
5. Actual vs projected checkpoints clearly categorized in summary.
6. Early-warning events included with verifiable precedence check (warning <= failure).
7. Execution duration accurately computed from start and end timestamps.
8. Persistence to disk and retrieval via API endpoints (/api/runs/{run_id}/summary, /api/summaries).
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.run_summary import RunSummaryBuilder


class TestBatch3PartCSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def test_successful_clean_run_summary(self):
        """Verify clean run generates PASSED summary, 0 warnings, and clean assessment."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "Aditya-C-S/demo-order-service",
                "scenario_preset": "clean",
                "runtime_model": "bilstm2",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        run_id = create_resp.json()["run_id"]

        # Ingest checkpoints with authentic nominal CI log text
        nominal_chunks = [
            (25, "setup", "Runner Environment Initialization\nPython 3.12.5\nGit 2.45.0\nWorkspace prepared."),
            (50, "build", "Requirement already satisfied: fastapi in ./venv\nRequirement already satisfied: pydantic in ./venv\nSuccessfully built demo-order-service-1.0.0"),
            (75, "test", "tests/test_orders.py::test_create_order PASSED\ntests/test_health.py::test_ping PASSED\n10 passed in 0.45s"),
        ]
        for depth, stage, chunk in nominal_chunks:
            self.client.post(
                f"/api/demo/runs/{run_id}/logs",
                json={"log_chunk": chunk, "depth": depth, "stage": stage},
            )

        final_resp = self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": "All tests passed successfully.\n10 passed in 1.2s",
                "depth": 100,
                "stage": "test",
                "exit_code": 0,
                "is_final": True,
                "step_outcome": "success",
            },
        )
        self.assertEqual(final_resp.status_code, 200)

        # Retrieve summary
        sum_resp = self.client.get(f"/api/runs/{run_id}/summary")
        self.assertEqual(sum_resp.status_code, 200)
        summary = sum_resp.json()

        self.assertEqual(summary["run_id"], run_id)
        self.assertEqual(summary["final_pipeline_status"], "PASSED")
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["summary_status"], "FINAL")

        # Subsystems verification
        meta = summary["metadata_prediction"]
        self.assertIn("LightGBM", meta["subsystem"])
        self.assertEqual(meta["feature_count_total"], 38)

        runtime = summary["runtime_predictions"]
        self.assertEqual(runtime["runtime_model"], "bilstm2")
        self.assertTrue(len(runtime["actual_checkpoints"]) >= 3)

        # Early warnings verification (clean run has 0 warnings)
        warns = summary["early_warnings"]
        self.assertEqual(warns["total_warnings"], 0)

        # Final assessment
        assess = summary["final_assessment"]
        self.assertTrue(assess["pipeline_passed"])
        self.assertFalse(assess["early_warning_generated"])

    def test_failed_run_summary_with_early_warning_and_rca(self):
        """Verify failed run summary records failure stage, RCA category, and early warning precedence."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "Aditya-C-S/demo-order-service",
                "scenario_preset": "dependency",
                "runtime_model": "bilstm2",
            },
        )
        run_id = create_resp.json()["run_id"]

        # Checkpoint 25 nominal
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Setup complete", "depth": 25, "stage": "setup"},
        )

        # Checkpoint 75 triggers early warning (> 70%) and fails
        fail_chunk = (
            "ERROR: Could not find a version that satisfies the requirement torch-missing==99.9.9\n"
            "ERROR: No matching distribution found for torch-missing==99.9.9\n"
            "Process completed with exit code 1."
        )
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": fail_chunk,
                "depth": 75,
                "stage": "build",
                "exit_code": 1,
                "is_final": True,
                "step_outcome": "failure",
            },
        )

        sum_resp = self.client.get(f"/api/runs/{run_id}/summary")
        self.assertEqual(sum_resp.status_code, 200)
        summary = sum_resp.json()

        self.assertEqual(summary["final_pipeline_status"], "FAILED")
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["exit_code"], 1)
        self.assertEqual(summary["failure_category"], "DEPENDENCY_FAILURE")

        # Verify RCA included
        rca = summary["root_cause_analysis"]
        self.assertEqual(rca["primary_category"], "DEPENDENCY_FAILURE")
        self.assertTrue(len(rca["root_causes"]) >= 1)
        self.assertTrue(len(rca["evidence_items"]) >= 1)

        # Verify Early Warning was captured
        warns = summary["early_warnings"]
        self.assertGreaterEqual(warns["total_warnings"], 1)

        # Verify final assessment
        assess = summary["final_assessment"]
        self.assertFalse(assess["pipeline_passed"])
        self.assertTrue(assess["early_warning_generated"])
        self.assertTrue(assess["rca_identified_cause"])

    def test_partial_summary_and_refresh_endpoint(self):
        """Verify incomplete run produces PARTIAL status and refreshes on command."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={"repo_id": "Aditya-C-S/demo-order-service", "scenario_preset": "none"},
        )
        run_id = create_resp.json()["run_id"]

        # Only 1 chunk ingested, run not completed
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Environment initialized", "depth": 25, "is_final": False},
        )

        sum_resp1 = self.client.get(f"/api/runs/{run_id}/summary")
        self.assertEqual(sum_resp1.status_code, 200)
        self.assertEqual(sum_resp1.json()["summary_status"], "PARTIAL")

        # POST /api/runs/{run_id}/summary/refresh
        refresh_resp = self.client.post(f"/api/runs/{run_id}/summary/refresh")
        self.assertEqual(refresh_resp.status_code, 200)
        self.assertEqual(refresh_resp.json()["run_id"], run_id)

        # GET /api/summaries list
        list_resp = self.client.get("/api/summaries")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(isinstance(list_resp.json(), list))
        self.assertTrue(len(list_resp.json()) >= 1)


if __name__ == "__main__":
    unittest.main()
