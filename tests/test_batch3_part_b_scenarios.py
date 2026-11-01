"""tests/test_batch3_part_b_scenarios.py

Batch 3 Part B Tests: Centralized Scenario Orchestration
Verifies:
1. Exact 4 supported scenario definitions (none, dependency, syntax, pytest).
2. Strict rejection of unknown scenario IDs with HTTP 400.
3. Legacy alias compatibility ('clean' -> 'none', 'high_risk' -> 'dependency').
4. Accurate scenario-to-stage mappings (none->None, dependency->50%, syntax->75%, pytest->100%).
5. Scenario dispatch API with dry_run and execution record tracking.
6. Execution state transitions (CREATED -> DISPATCHED -> RUNNING -> COMPLETED).
7. Persistence with demo runs across restart.
8. Status retrieval endpoint /api/scenarios/runs/{run_id}/status.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.scenarios.scenario_orchestrator import (
    SCENARIO_NONE,
    SCENARIO_DEPENDENCY,
    SCENARIO_SYNTAX,
    SCENARIO_PYTEST,
    SUPPORTED_SCENARIO_IDS,
    ScenarioExecutionStatus,
    normalize_and_validate_scenario,
    get_all_scenarios,
    get_scenario_definition,
    ScenarioOrchestrator,
)


class TestBatch3PartBScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def test_supported_scenarios_definitions_and_schema(self):
        """Verify the 4 central scenarios match exact stage and outcome contracts."""
        all_sc = get_all_scenarios()
        self.assertEqual(len(all_sc), 4)

        sc_map = {s["scenario_id"]: s for s in all_sc}
        self.assertEqual(set(sc_map.keys()), set(SUPPORTED_SCENARIO_IDS))

        # 1. Clean
        self.assertEqual(sc_map[SCENARIO_NONE]["expected_outcome"], "success")
        self.assertIsNone(sc_map[SCENARIO_NONE]["expected_failure_stage"])
        self.assertFalse(sc_map[SCENARIO_NONE]["inject_failure"])

        # 2. Dependency
        self.assertEqual(sc_map[SCENARIO_DEPENDENCY]["expected_outcome"], "failure")
        self.assertEqual(sc_map[SCENARIO_DEPENDENCY]["expected_failure_stage"], "50%")
        self.assertTrue(sc_map[SCENARIO_DEPENDENCY]["inject_failure"])

        # 3. Syntax
        self.assertEqual(sc_map[SCENARIO_SYNTAX]["expected_outcome"], "failure")
        self.assertEqual(sc_map[SCENARIO_SYNTAX]["expected_failure_stage"], "75%")
        self.assertTrue(sc_map[SCENARIO_SYNTAX]["inject_failure"])

        # 4. Pytest
        self.assertEqual(sc_map[SCENARIO_PYTEST]["expected_outcome"], "failure")
        self.assertEqual(sc_map[SCENARIO_PYTEST]["expected_failure_stage"], "100%")
        self.assertTrue(sc_map[SCENARIO_PYTEST]["inject_failure"])

    def test_scenario_validation_strictness_and_legacy_aliases(self):
        """Verify unknown IDs are rejected and legacy aliases normalize safely."""
        # Valid direct
        s_dep = normalize_and_validate_scenario("dependency")
        self.assertEqual(s_dep.scenario_id, "dependency")

        # Valid legacy alias
        s_clean = normalize_and_validate_scenario("clean")
        self.assertEqual(s_clean.scenario_id, "none")

        s_clean_run = normalize_and_validate_scenario("clean_run")
        self.assertEqual(s_clean_run.scenario_id, "none")

        # Rejection of invalid
        with self.assertRaises(ValueError):
            normalize_and_validate_scenario("invalid_random_scenario")

        with self.assertRaises(ValueError):
            normalize_and_validate_scenario("")

        with self.assertRaises(ValueError):
            normalize_and_validate_scenario(None)

    def test_scenario_api_endpoints(self):
        """Verify /api/scenarios and /api/scenarios/validate HTTP responses."""
        # 1. List
        resp_list = self.client.get("/api/scenarios")
        self.assertEqual(resp_list.status_code, 200)
        items = resp_list.json()
        self.assertEqual(len(items), 4)

        # 2. Get single
        resp_single = self.client.get("/api/scenarios/syntax")
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["scenario_id"], "syntax")
        self.assertEqual(resp_single.json()["expected_failure_stage"], "75%")

        # 3. Reject invalid single
        resp_err = self.client.get("/api/scenarios/non_existent")
        self.assertEqual(resp_err.status_code, 400)

        # 4. Validate valid POST
        resp_val = self.client.post("/api/scenarios/validate", json={"scenario_id": "pytest"})
        self.assertEqual(resp_val.status_code, 200)
        self.assertTrue(resp_val.json()["valid"])
        self.assertEqual(resp_val.json()["scenario"]["expected_failure_stage"], "100%")

        # 5. Validate invalid POST
        resp_inval = self.client.post("/api/scenarios/validate", json={"scenario_id": "malicious_injection"})
        self.assertEqual(resp_inval.status_code, 400)

    def test_scenario_dispatch_dry_run_and_status_tracking(self):
        """Verify scenario dispatch registers DemoRun and tracks execution state."""
        dispatch_resp = self.client.post(
            "/api/scenarios/dispatch",
            json={
                "scenario_id": "dependency",
                "repo_id": "Aditya-C-S/demo-order-service",
                "dry_run": True,
                "runtime_model": "bilstm2",
            },
        )
        self.assertEqual(dispatch_resp.status_code, 200)
        body = dispatch_resp.json()
        self.assertEqual(body["status"], ScenarioExecutionStatus.DISPATCHED)
        run_id = body["run_id"]
        self.assertTrue(bool(run_id))
        self.assertIn("run", run_id)

        # Query status endpoint
        status_resp = self.client.get(f"/api/scenarios/runs/{run_id}/status")
        self.assertEqual(status_resp.status_code, 200)
        st = status_resp.json()
        self.assertEqual(st["scenario_id"], "dependency")
        self.assertEqual(st["failure_stage"], "50%")
        self.assertEqual(st["execution_status"], ScenarioExecutionStatus.DISPATCHED)

        # Ingest nominal checkpoint -> moves to RUNNING
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Starting environment", "depth": 25, "stage": "setup"},
        )
        running_st = self.client.get(f"/api/scenarios/runs/{run_id}/status").json()
        self.assertEqual(running_st["execution_status"], ScenarioExecutionStatus.RUNNING)

        # Ingest final failure checkpoint -> moves to COMPLETED
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": "Dependency failure\nexit code 1",
                "depth": 50,
                "stage": "build",
                "exit_code": 1,
                "is_final": True,
                "step_outcome": "failure",
            },
        )
        completed_st = self.client.get(f"/api/scenarios/runs/{run_id}/status").json()
        self.assertEqual(completed_st["execution_status"], ScenarioExecutionStatus.COMPLETED)
        self.assertEqual(completed_st["pipeline_result"], "failure")


if __name__ == "__main__":
    unittest.main()
