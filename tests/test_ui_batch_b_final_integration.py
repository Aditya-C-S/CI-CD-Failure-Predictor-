"""
tests/test_ui_batch_b_final_integration.py
Verification suite for UI Batch B Final Integration, Risk Colour Calibration,
and Live GitHub Actions Consistency.
"""

import os
import json
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager
from src.demo.presentation_helper import compute_checkpoint_projections
from src.prediction.predictor import get_predictor
from src.prediction.runtime_tracker import compare_runtime_models
from src.scenarios.scenario_orchestrator import ScenarioOrchestrator


@pytest.fixture(scope="module")
def client():
    api_key = os.getenv("DEMO_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    return TestClient(app, headers=headers)


class TestFinalIntegrationAndRiskCalibration:
    """Tests for calibrated risk thresholds, consistent prediction pipelines, and deduplication."""

    def test_risk_colour_classification_exact_boundaries(self):
        """
        Verify exact risk classification thresholds:
        - 0% - 40% inclusive: Green / Low Risk
        - > 40% and < 70%: Yellow/Amber / Moderate Risk
        - >= 70%: Red / High Risk
        Exact boundary cases: 30%, 40.00%, 40.01%, 60%, 69.99%, 70.00%, 73.67%
        """
        # Test backend projection helper tier assignments
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
            mock_pred = [{
                "checkpoint": 25,
                "depth_percentage": 25,
                "failure_probability": prob,
                "failure_probability_pct": round(prob * 100, 2),
                "prediction_type": "ACTUAL",
                "is_projected": False,
            }]
            proj = compute_checkpoint_projections(mock_pred)
            actual_tier = proj[25]["risk_tier"]
            assert actual_tier == expected_tier, (
                f"Boundary failure at {prob*100}%: expected {expected_tier}, got {actual_tier}"
            )

    def test_local_simulation_provenance_and_terminal_status(self, client):
        """
        Verify Local Simulation:
        - Dispatch scenario (dependency) with dry_run=True.
        - Replay benchmark logs.
        - Verify replay provenance: 'LOCAL SIMULATION / BENCHMARK REPLAY'.
        - Verify predictions and terminal status.
        """
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(repo_id="Aditya-C-S/demo-order-service", scenario_preset="dependency", runtime_model="bilstm2")
        run_id = run.run_id

        # Dispatch via orchestrator
        disp = ScenarioOrchestrator.dispatch(
            scenario_id="dependency",
            repo_id="Aditya-C-S/demo-order-service",
            run_id=run_id,
            dry_run=True,
            runtime_model="bilstm2",
        )
        assert disp["status"] == "DISPATCHED"

        # Replay sample stream
        res_replay = client.post(f"/api/demo/runs/{run_id}/replay", json={
            "sample_id": "F2/run_0005.log",
            "chunk_lines": 40
        })
        assert res_replay.status_code == 200
        rep = res_replay.json()

        # Provenance verification
        assert rep["execution_source"] == "LOCAL SIMULATION / BENCHMARK REPLAY"
        assert rep["status"] == "completed"
        assert rep["actual_outcome"] == "failure"
        assert rep["log_chunks_count"] == 4

        # Scenario execution status verification
        status_info = ScenarioOrchestrator.get_execution_status(run_id)
        assert status_info["execution_status"] in ("COMPLETED", "FAILED")
        assert status_info["pipeline_result"] == "failure"

    def test_live_github_actions_telemetry_flow_and_provenance(self, client):
        """
        Verify Live GitHub Actions execution:
        - Ingest actual telemetry from simulated runner.
        - Verify provenance: 'LIVE GITHUB ACTIONS / ACTUAL TELEMETRY'.
        - Verify same ML prediction pipeline used as Local Simulation.
        - Verify checkpoint progression and terminal status.
        """
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(repo_id="Aditya-C-S/demo-order-service", scenario_preset="dependency", runtime_model="bilstm2")
        run_id = run.run_id

        # Checkpoint 25%: Environment setup (Success)
        c1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"chk_{run_id}_25_001",
            "log_chunk": "##[group]Runner Environment Initialization\nPython 3.12.5\nUbuntu Linux 24.04\n##[endgroup]",
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "depth": 25,
            "exit_code": 0,
            "step_outcome": "success",
            "ci_run_id": "gha_live_run_9999",
            "commit_sha": "f1e2d3c",
        })
        assert c1.status_code == 200
        d1 = c1.json()
        assert d1["execution_source"] == "LIVE GITHUB ACTIONS / ACTUAL TELEMETRY"
        assert any(p["depth_percentage"] == 25 and p["prediction_type"] == "ACTUAL" for p in d1["runtime_predictions"])

        # Checkpoint 50%: Dependency Installation Failure (Exit code 1)
        c2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"chk_{run_id}_50_001",
            "log_chunk": (
                "=== Stage: Dependency Installation ===\n"
                "pip install demo-unresolved-dependency-pkg==99.99.99\n"
                "ERROR: Could not find a version that satisfies the requirement demo-unresolved-dependency-pkg==99.99.99\n"
                "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
                "##[error] Requirements installation failed with exit code 1"
            ),
            "step_name": "Install Dependencies",
            "stage": "build",
            "depth": 50,
            "exit_code": 1,
            "step_outcome": "failure",
            "ci_run_id": "gha_live_run_9999",
            "commit_sha": "f1e2d3c",
        })
        assert c2.status_code == 200
        d2 = c2.json()
        assert d2["actual_outcome"] == "failure"
        assert d2["parser_v2_result"] is not None
        assert d2["parser_v2_result"]["status"] == "failure"
        assert d2["rca_result"] is not None

        # Checkpoint 75%: Skipped stage (due to fail-fast)
        c3 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"chk_{run_id}_75_001",
            "log_chunk": "=== Step 'Validate Environment & Package Syntax' was skipped due to earlier stage failure. ===",
            "step_name": "Validate Environment",
            "stage": "build",
            "depth": 75,
            "step_outcome": "skipped",
            "ci_run_id": "gha_live_run_9999",
        })
        assert c3.status_code == 200
        d3 = c3.json()
        # Skipped step should be recorded without inventing false predictions
        p75 = [p for p in d3["runtime_predictions"] if p.get("depth_percentage") == 75]
        assert len(p75) > 0
        assert p75[0]["is_skipped"] is True
        assert p75[0]["failure_probability"] is None

        # Checkpoint 100%: Skipped & Final
        c4 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "event_id": f"chk_{run_id}_100_001",
            "log_chunk": "=== Step 'Run Test Suite' was skipped due to earlier stage failure. ===",
            "step_name": "Run Test Suite",
            "stage": "test",
            "depth": 100,
            "step_outcome": "skipped",
            "workflow_outcome": "failure",
            "is_final": True,
            "ci_run_id": "gha_live_run_9999",
        })
        assert c4.status_code == 200
        d4 = c4.json()
        assert d4["status"] == "completed"
        assert d4["actual_outcome"] == "failure"
        assert d4["execution_source"] == "LIVE GITHUB ACTIONS / ACTUAL TELEMETRY"

        # Checkpoint projections should provide valid future estimates (+3%, +2%) for 75 and 100
        projs = d4["checkpoint_projections"]
        assert projs["25"]["type"] == "ACTUAL"
        assert projs["50"]["type"] == "ACTUAL"
        assert projs["75"]["type"] == "PROJECTED"
        assert projs["100"]["type"] == "PROJECTED"
        assert projs["75"]["is_projected"] is True
        assert projs["100"]["is_projected"] is True

    def test_deduplication_telemetry_and_warnings(self, client):
        """
        Verify repeated telemetry chunks do not inflate log chunks,
        prediction history, or early warnings.
        """
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(scenario_preset="dependency", runtime_model="bilstm2")
        run_id = run.run_id

        chunk_payload = {
            "event_id": f"chk_{run_id}_25_unique_evt",
            "log_chunk": "Setting up runner environment\nPython 3.12.5 initialized",
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "depth": 25,
            "exit_code": 0,
            "step_outcome": "success",
        }

        # 1. First delivery
        r1 = client.post(f"/api/demo/runs/{run_id}/logs", json=chunk_payload)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["log_chunks_count"] == 1
        initial_history_len = len(d1["prediction_history"])

        # 2. Duplicate deliveries (retry attempts)
        for _ in range(3):
            r_dup = client.post(f"/api/demo/runs/{run_id}/logs", json=chunk_payload)
            assert r_dup.status_code == 200
            d_dup = r_dup.json()
            assert d_dup["log_chunks_count"] == 1
            assert len(d_dup["prediction_history"]) == initial_history_len

        # 3. High-risk chunk triggering early warning
        err_payload = {
            "event_id": f"chk_{run_id}_50_err_evt",
            "log_chunk": "ERROR: Could not find a version that satisfies the requirement\nProcess completed with exit code 1",
            "step_name": "Install Dependencies",
            "stage": "build",
            "depth": 50,
            "exit_code": 1,
            "step_outcome": "failure",
        }
        r_err1 = client.post(f"/api/demo/runs/{run_id}/logs", json=err_payload)
        assert r_err1.status_code == 200
        d_err1 = r_err1.json()
        assert d_err1["log_chunks_count"] == 2
        warn_count = len(d_err1["warning_history"])

        # Duplicate high-risk chunk delivery
        r_err_dup = client.post(f"/api/demo/runs/{run_id}/logs", json=err_payload)
        assert r_err_dup.status_code == 200
        d_err_dup = r_err_dup.json()
        assert d_err_dup["log_chunks_count"] == 2
        # Warning count must not be inflated by duplicates
        assert len(d_err_dup["warning_history"]) == warn_count

    def test_all_three_runtime_models_preserved(self):
        """
        Verify BiLSTM v2, TF-IDF + Linear SVM, and TF-IDF + Logistic Regression
        are all active, functional, and fair in comparison.
        """
        for model_id in ["bilstm2", "svm", "logistic_regression"]:
            predictor = get_predictor(model_id, visibility=50)
            res = predictor.predict_failure("ERROR: requirement demo-pkg==99.99 could not be resolved", visibility=50)
            assert res.failure_probability is not None
            assert 0.0 <= res.failure_probability <= 1.0
            assert res.model_name in ("bilstm2", "svm", "logistic_regression")

        comp = compare_runtime_models("ERROR: package not found", depth=50)
        report = comp.to_dict()
        assert len(report["predictions"]) == 3
        mod_ids = [p["model_id"] for p in report["predictions"]]
        assert "bilstm2" in mod_ids
        assert "svm" in mod_ids
        assert "logistic_regression" in mod_ids
