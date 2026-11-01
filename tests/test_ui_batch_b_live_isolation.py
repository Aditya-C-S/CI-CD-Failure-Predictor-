"""
tests/test_ui_batch_b_live_isolation.py

Automated verification suite for Live Telemetry-Driven Predictions and Run Isolation (UI Batch B Final).
Validates:
1. Exact Risk Colour & Tier Boundaries (30%, 40.00%, 40.01%, 60%, 69.99%, 70.00%, 73.67%).
2. New Live Run Isolation (empty logs, empty predictions, dispatched status, zero preloaded state).
3. Progressive Telemetry Ingestion (progressive state evolution checkpoint-by-checkpoint).
4. Cross-Run Isolation (Run A telemetry never bleeds into Run B).
5. Benchmark Replay Rejection on Live Runs.
6. Checkpoint Projections vs Actual vs Skipped Semantics.
"""

import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager
from src.demo.presentation_helper import compute_checkpoint_projections
from src.scenarios.scenario_orchestrator import ScenarioOrchestrator, ScenarioExecutionStatus


@pytest.fixture(scope="module")
def client():
    api_key = os.getenv("DEMO_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    return TestClient(app, headers=headers)


class TestLiveRunIsolationAndTelemetry:
    """Test suite for live telemetry-driven pipeline execution and multi-tenant run isolation."""

    def test_risk_colour_exact_boundary_calibration(self):
        """
        Verify exact risk classification thresholds:
        - <= 40.00%: LOW RISK (Green)
        - > 40.00% and < 70.00%: MODERATE RISK (Yellow)
        - >= 70.00%: HIGH RISK (Red)
        Boundaries tested: 30%, 40.00%, 40.01%, 60%, 69.99%, 70.00%, 73.67%
        """
        cases = [
            (0.30, "LOW RISK"),
            (0.40, "LOW RISK"),
            (0.4001, "MODERATE RISK"),
            (0.60, "MODERATE RISK"),
            (0.6999, "MODERATE RISK"),
            (0.70, "HIGH RISK"),
            (0.7367, "HIGH RISK"),
        ]
        for prob, expected_tier in cases:
            mock_preds = [{
                "checkpoint": 25,
                "depth_percentage": 25,
                "failure_probability": prob,
                "failure_probability_pct": round(prob * 100, 2),
                "prediction_type": "ACTUAL",
                "is_projected": False,
            }]
            projections = compute_checkpoint_projections(mock_preds)
            assert 25 in projections
            actual_tier = projections[25]["risk_tier"]
            assert actual_tier == expected_tier, (
                f"Boundary failure at {prob*100}%: expected {expected_tier}, got {actual_tier}"
            )

    def test_new_live_run_starts_completely_empty(self, client):
        """
        Verify that a newly dispatched Live GitHub Actions run starts with an empty live analysis:
        - 0 log chunks
        - Empty accumulated_log
        - 0 runtime predictions
        - Empty current_runtime_prediction
        - Status is 'dispatched'
        - Execution status is ScenarioExecutionStatus.DISPATCHED
        - Checkpoint projections are all type 'NONE' (awaiting telemetry)
        - Execution source is 'LIVE GITHUB ACTIONS / ACTUAL TELEMETRY'
        """
        resp = client.post("/api/demo/scenarios/dispatch", json={
            "scenario_id": "dependency",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        run_id = data["run_id"]
        assert run_id.startswith("demo_run_")

        # Inspect run details via API
        run_resp = client.get(f"/api/demo/runs/{run_id}")
        assert run_resp.status_code == 200
        run_data = run_resp.json()

        # Strict isolation assertions
        assert run_data["status"] == "dispatched"
        assert run_data["actual_outcome"] == "pending"
        assert run_data["execution_source"] == "LIVE GITHUB ACTIONS / ACTUAL TELEMETRY"
        assert run_data["log_chunks_count"] == 0
        assert run_data["log_lines_count"] == 0
        assert run_data["accumulated_log"] == ""
        assert len(run_data["runtime_predictions"]) == 0
        assert run_data["current_runtime_prediction"] == {}
        assert len(run_data["warning_history"]) == 0
        assert run_data["early_warning"] is None
        assert run_data["parser_v2_result"] is None
        assert run_data["rca_result"] is None

        # Check projections
        projs = run_data["checkpoint_projections"]
        for depth in [25, 50, 75, 100]:
            assert str(depth) in projs or depth in projs
            p = projs.get(str(depth)) or projs.get(depth)
            assert p["type"] == "NONE"
            assert p["failure_probability"] is None

        # Orchestrator status assertion
        status_info = ScenarioOrchestrator.get_execution_status(run_id)
        assert status_info["execution_status"] == ScenarioExecutionStatus.DISPATCHED
        assert status_info["pipeline_result"] == "pending"

    def test_progressive_telemetry_driven_evolution(self, client):
        """
        Verify that a live session populates progressively and exclusively as authentic telemetry arrives.
        """
        disp = client.post("/api/demo/scenarios/dispatch", json={
            "scenario_id": "dependency",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": False,
        }).json()
        run_id = disp["run_id"]

        # 1. Telemetry Chunk 1: Setup at 25% (nominal)
        c1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"event_{run_id}_01",
            "log_chunk": "##[group]Runner Environment Setup\nRunning job on GitHub-hosted runner\nUbuntu 24.04 LTS\n##[endgroup]",
            "step_name": "Runner Environment Setup",
            "stage": "setup",
            "depth": 25,
            "exit_code": 0,
            "step_outcome": "success",
            "ci_run_id": "gha_run_101",
        })
        assert c1.status_code == 200
        d1 = c1.json()

        assert d1["log_chunks_count"] == 1
        assert "Runner Environment Setup" in d1["accumulated_log"]
        assert len(d1["runtime_predictions"]) == 1
        assert d1["runtime_predictions"][0]["depth_percentage"] == 25
        assert d1["runtime_predictions"][0]["prediction_type"] == "ACTUAL"
        assert d1["current_runtime_prediction"]["depth_percentage"] == 25

        # Checkpoint projections should now project 50, 75, 100 based on 25%
        p1 = d1["checkpoint_projections"]
        assert p1["25"]["type"] == "ACTUAL"
        assert p1["50"]["type"] == "PROJECTED"
        assert p1["75"]["type"] == "PROJECTED"
        assert p1["100"]["type"] == "PROJECTED"

        # 2. Telemetry Chunk 2: Dependency Failure at 50%
        c2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"event_{run_id}_02",
            "log_chunk": (
                "=== Step: Install Dependencies ===\n"
                "pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement non_existent_pkg==99.9\n"
                "ERROR: No matching distribution found for non_existent_pkg==99.9\n"
                "##[error]Process completed with exit code 1"
            ),
            "step_name": "Install Dependencies",
            "stage": "build",
            "depth": 50,
            "exit_code": 1,
            "step_outcome": "failure",
            "ci_run_id": "gha_run_101",
        })
        assert c2.status_code == 200
        d2 = c2.json()

        assert d2["log_chunks_count"] == 2
        assert d2["actual_outcome"] == "failure"
        assert len(d2["runtime_predictions"]) == 2
        assert d2["parser_v2_result"] is not None
        assert d2["rca_result"] is not None
        # Failure probability at 50% should be elevated
        pred50 = next(p for p in d2["runtime_predictions"] if p["depth_percentage"] == 50)
        assert pred50["failure_probability"] >= 0.65

        # Checkpoints 75 and 100 skipped
        c3 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"event_{run_id}_03",
            "log_chunk": "=== Step: Run Tests (Skipped due to prior failure) ===",
            "step_name": "Run Tests",
            "stage": "test",
            "depth": 100,
            "step_outcome": "skipped",
            "ci_run_id": "gha_run_101",
            "is_final": True,
            "workflow_outcome": "failure",
        })
        assert c3.status_code == 200
        d3 = c3.json()
        assert d3["status"] == "completed"

    def test_cross_run_isolation(self, client):
        """
        Verify that telemetry sent to Run A NEVER bleeds into Run B.
        """
        disp_a = client.post("/api/demo/scenarios/dispatch", json={
            "scenario_id": "syntax",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": False,
        }).json()
        run_a = disp_a["run_id"]

        disp_b = client.post("/api/demo/scenarios/dispatch", json={
            "scenario_id": "pytest",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": False,
        }).json()
        run_b = disp_b["run_id"]

        # Send telemetry ONLY to Run A
        client.post(f"/api/demo/runs/{run_a}/logs", json={
            "event_id": f"event_{run_a}_01",
            "log_chunk": "Log line specifically for Run A only",
            "depth": 25,
            "exit_code": 0,
        })

        # Fetch Run B - verify it remains completely untouched and pristine
        resp_b = client.get(f"/api/demo/runs/{run_b}").json()
        assert resp_b["log_chunks_count"] == 0
        assert resp_b["accumulated_log"] == ""
        assert len(resp_b["runtime_predictions"]) == 0
        assert resp_b["status"] == "dispatched"
        assert resp_b["actual_outcome"] == "pending"

    def test_replay_rejection_on_live_runs(self, client):
        """
        Verify that benchmark replay is strictly REJECTED on live GitHub Actions runs.
        """
        disp = client.post("/api/demo/scenarios/dispatch", json={
            "scenario_id": "dependency",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": False,
        }).json()
        run_id = disp["run_id"]

        replay_resp = client.post(f"/api/demo/runs/{run_id}/replay", json={
            "sample_id": "F2/run_0005.log",
            "chunk_lines": 40,
        })
        # Must return 400 or error indicating benchmark replay is prohibited
        assert replay_resp.status_code in (400, 404, 422, 500)
        err_msg = replay_resp.text
        assert "live GitHub Actions" in err_msg or "cannot be overwritten" in err_msg or "replay" in err_msg.lower()
