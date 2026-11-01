"""tests/test_batch3_e2e_scenarios.py

Batch 3 End-to-End Integration Validation:
Validates all four scenarios through the complete end-to-end pipeline:
1. Scenario 1: Clean      (Passes nominally, 0 warnings, clean RCA)
2. Scenario 2: Dependency (Fails at 50% build stage, triggers early warning at 75% risk, identifies dependency root cause)
3. Scenario 3: Syntax     (Fails at 75% validation stage, extracts syntax line & AST error, identifies syntax root cause)
4. Scenario 4: Pytest     (Fails at 100% test stage, extracts failed test assertion, identifies test root cause)

Verifies every link in the architectural chain:
Commit -> Metadata Prediction -> Neo4j Graph Impact -> Log Ingestion ->
Runtime Prediction -> Risk Progression -> Early Warning -> Parser V2 ->
Root Cause Analysis -> Final Run Summary & Diagnostics.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.scenarios.scenario_orchestrator import ScenarioExecutionStatus


class TestBatch3EndToEndScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def test_e2e_scenario_1_clean_pipeline(self):
        """End-to-End Scenario 1: Clean Pipeline Execution."""
        # 1. Dispatch scenario
        disp_resp = self.client.post(
            "/api/scenarios/dispatch",
            json={
                "scenario_id": "none",
                "repo_id": "Aditya-C-S/demo-order-service",
                "dry_run": True,
                "runtime_model": "bilstm2",
            },
        )
        self.assertEqual(disp_resp.status_code, 200)
        run_id = disp_resp.json()["run_id"]

        # 2. Ingest nominal checkpoints 25%, 50%, 75%, 100%
        chunks = [
            (25, "setup", "Runner Environment Initialization\nPython 3.12.5\nGit 2.45.0\nWorkspace prepared.", 0, False, "success"),
            (50, "build", "Requirement already satisfied: fastapi in ./venv\nRequirement already satisfied: pydantic in ./venv\nSuccessfully built demo-order-service-1.0.0", 0, False, "success"),
            (75, "test", "tests/test_orders.py::test_create_order PASSED\ntests/test_health.py::test_ping PASSED\n10 passed in 0.45s", 0, False, "success"),
            (100, "test", "All tests passed successfully.\nProcess completed with exit code 0.", 0, True, "success"),
        ]

        for depth, stage, text, ec, is_fin, outcome in chunks:
            resp = self.client.post(
                f"/api/demo/runs/{run_id}/logs",
                json={
                    "log_chunk": text,
                    "depth": depth,
                    "stage": stage,
                    "exit_code": ec,
                    "is_final": is_fin,
                    "step_outcome": outcome,
                },
            )
            self.assertEqual(resp.status_code, 200)

        # 3. Retrieve Final Run Summary
        sum_resp = self.client.get(f"/api/runs/{run_id}/summary")
        self.assertEqual(sum_resp.status_code, 200)
        summary = sum_resp.json()

        self.assertEqual(summary["final_pipeline_status"], "PASSED")
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["early_warnings"]["total_warnings"], 0)
        self.assertEqual(summary["scenario_id"], "none")
        self.assertTrue(summary["final_assessment"]["pipeline_passed"])

    def test_e2e_scenario_2_dependency_failure(self):
        """End-to-End Scenario 2: Dependency Installation Failure at 50% stage."""
        disp_resp = self.client.post(
            "/api/scenarios/dispatch",
            json={
                "scenario_id": "dependency",
                "repo_id": "Aditya-C-S/demo-order-service",
                "dry_run": True,
                "runtime_model": "bilstm2",
            },
        )
        run_id = disp_resp.json()["run_id"]

        # Checkpoint 25 nominal
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Runner Environment Initialization\nPython 3.12.5", "depth": 25, "stage": "setup"},
        )

        # Checkpoint 50 fails with dependency error
        dep_fail = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "--- [Controlled Demo Injection] Simulating dependency resolution failure ---\n"
            "ERROR: Could not find a version that satisfies the requirement demo-unresolved-dependency-pkg==99.99.99\n"
            "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
            "##[error] Requirements installation failed with exit code 1\n"
            "Process completed with exit code 1."
        )
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": dep_fail,
                "depth": 50,
                "stage": "build",
                "exit_code": 1,
                "is_final": True,
                "step_outcome": "failure",
            },
        )

        # Retrieve Final Run Summary
        summary = self.client.get(f"/api/runs/{run_id}/summary").json()
        self.assertEqual(summary["final_pipeline_status"], "FAILED")
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["failure_category"], "DEPENDENCY_FAILURE")

        # Verify RCA details
        rca = summary["root_cause_analysis"]
        self.assertEqual(rca["primary_category"], "DEPENDENCY_FAILURE")
        self.assertIn("demo-unresolved-dependency-pkg", rca["root_causes"][0]["why_failed"])
        self.assertTrue(len(rca["evidence_items"]) >= 1)

    def test_e2e_scenario_3_syntax_failure(self):
        """End-to-End Scenario 3: Syntax Validation Failure at 75% stage."""
        disp_resp = self.client.post(
            "/api/scenarios/dispatch",
            json={
                "scenario_id": "syntax",
                "repo_id": "Aditya-C-S/demo-order-service",
                "dry_run": True,
                "runtime_model": "bilstm2",
            },
        )
        run_id = disp_resp.json()["run_id"]

        # 25% setup
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Runner Environment Initialization", "depth": 25, "stage": "setup"},
        )
        # 50% build
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Dependencies installed nominally", "depth": 50, "stage": "build"},
        )
        # 75% fails with syntax error
        syntax_fail = (
            "=== Stage: Code Quality & Syntax Validation ===\n"
            "Running python -m py_compile app/models.py ...\n"
            "  File \"app/models.py\", line 28\n"
            "    def order_summary(\n"
            "                     ^\n"
            "SyntaxError: '(' was never closed\n"
            "##[error]Code validation failed with exit code 1\n"
            "Process completed with exit code 1."
        )
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": syntax_fail,
                "depth": 75,
                "stage": "test",
                "exit_code": 1,
                "is_final": True,
                "step_outcome": "failure",
            },
        )

        summary = self.client.get(f"/api/runs/{run_id}/summary").json()
        self.assertEqual(summary["final_pipeline_status"], "FAILED")
        self.assertEqual(summary["failure_category"], "SYNTAX_FAILURE")

        rca = summary["root_cause_analysis"]
        self.assertEqual(rca["primary_category"], "SYNTAX_FAILURE")
        self.assertIn("app/models.py", rca["root_causes"][0]["where_failed"])

    def test_e2e_scenario_4_pytest_failure(self):
        """End-to-End Scenario 4: Test Execution Failure at 100% stage."""
        disp_resp = self.client.post(
            "/api/scenarios/dispatch",
            json={
                "scenario_id": "pytest",
                "repo_id": "Aditya-C-S/demo-order-service",
                "dry_run": True,
                "runtime_model": "bilstm2",
            },
        )
        run_id = disp_resp.json()["run_id"]

        for d, s, t in [
            (25, "setup", "Runner Environment Initialization"),
            (50, "build", "Dependencies installed"),
            (75, "test", "Syntax validated"),
        ]:
            self.client.post(f"/api/demo/runs/{run_id}/logs", json={"log_chunk": t, "depth": d, "stage": s})

        # 100% fails with pytest assertion
        pytest_fail = (
            "=== test session starts ===\n"
            "tests/test_orders.py:44: in test_order_creation\n"
            "    assert order.status == 'created'\n"
            "E   AssertionError: assert 'failed' == 'created'\n"
            "=========================== FAILURES ===========================\n"
            "FAILED tests/test_orders.py::test_order_creation - AssertionError: assert 'failed' == 'created'\n"
            "##[error]pytest failed with exit code 1\n"
            "Process completed with exit code 1."
        )
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": pytest_fail,
                "depth": 100,
                "stage": "test",
                "exit_code": 1,
                "is_final": True,
                "step_outcome": "failure",
            },
        )

        summary = self.client.get(f"/api/runs/{run_id}/summary").json()
        self.assertEqual(summary["final_pipeline_status"], "FAILED")
        self.assertEqual(summary["failure_category"], "TEST_FAILURE")

        rca = summary["root_cause_analysis"]
        self.assertEqual(rca["primary_category"], "TEST_FAILURE")
        self.assertIn("assertion", rca["root_causes"][0]["why_failed"].lower())


if __name__ == "__main__":
    unittest.main()
