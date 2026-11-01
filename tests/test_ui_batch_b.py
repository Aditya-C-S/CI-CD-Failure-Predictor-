"""
tests/test_ui_batch_b.py
Automated Testing Suite for UI Batch B:
- Live Pipeline Monitoring (Header, Copy Demo ID, Risk Gauge, Checkpoints, Logs, Evidence, Early Warnings)
- Run History and Inspection (Search, Filter, Pagination, Run Detail View, Run Comparison)
- Backend Integrity & Non-Interference Verification
"""

import os
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager
from src.demo.presentation_helper import compute_checkpoint_projections

@pytest.fixture(scope="module")
def client():
    api_key = os.getenv("DEMO_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    return TestClient(app, headers=headers)

class TestUIBatchB:
    def test_live_pipeline_and_run_history_html_elements(self, client):
        """Verify index.html contains all required UI Batch B elements."""
        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # 1. Routes & Sidebar
        assert 'data-route="live-pipeline"' in html
        assert 'data-route="run-history"' in html

        # 2. Live Pipeline Page Sections
        assert 'id="view-live-pipeline"' in html
        assert 'id="live-header-run-id"' in html
        assert 'id="btn-live-copy-demo-id"' in html
        assert 'id="live-risk-gauge-circle"' in html
        assert 'id="live-risk-percent"' in html
        assert 'id="live-checkpoint-timeline"' in html
        assert 'id="live-terminal-content"' in html
        assert 'id="btn-toggle-autoscroll"' in html
        assert 'id="btn-clear-log-view"' in html
        assert 'id="btn-copy-visible-logs"' in html
        assert 'id="live-connection-status-pill"' in html
        assert 'id="live-evidence-stream-container"' in html
        assert 'id="live-early-warnings-container"' in html
        assert 'id="live-pipeline-empty-state"' in html

        # 3. Run History Page Sections
        assert 'id="view-run-history"' in html
        assert 'id="history-search-run-id"' in html
        assert 'id="history-search-commit"' in html
        assert 'id="history-filter-scenario"' in html
        assert 'id="history-filter-status"' in html
        assert 'id="history-filter-model"' in html
        assert 'id="history-sort-by"' in html
        assert 'id="history-runs-table-body"' in html
        assert 'id="history-prev-page-btn"' in html
        assert 'id="history-next-page-btn"' in html
        assert 'id="btn-compare-selected-runs"' in html

        # 4. Modals
        assert 'id="run-inspector-modal"' in html
        assert 'id="run-comparison-modal"' in html

    def test_static_module_serving(self, client):
        """Verify new ES modules are served correctly."""
        modules = [
            "/static/js/live-pipeline.js",
            "/static/js/run-history.js"
        ]
        for mod in modules:
            res = client.get(mod)
            assert res.status_code == 200, f"Failed to serve {mod}"
            assert len(res.content) > 100

    def test_checkpoint_projections_semantics_and_distinction(self):
        """Verify ACTUAL and PROJECTED checkpoints are strictly distinguishable."""
        # Case 1: Only 25% checkpoint present
        preds = [
            {
                "checkpoint": 25,
                "depth_percentage": 25,
                "failure_probability": 0.35,
                "failure_probability_pct": 35.0,
                "model_name": "bilstm2",
                "prediction_type": "ACTUAL",
                "is_projected": False,
            }
        ]
        proj = compute_checkpoint_projections(preds)
        assert len(proj) == 4
        # 25% is ACTUAL
        assert proj[25]["type"] == "ACTUAL"
        assert proj[25]["is_projected"] is False
        assert proj[25]["failure_probability_pct"] == 35.0

        # 50% is PROJECTED (35.0 + 3.0 = 38.0%)
        assert proj[50]["type"] == "PROJECTED"
        assert proj[50]["is_projected"] is True
        assert proj[50]["failure_probability_pct"] == 38.0

        # 75% is PROJECTED (38.0 + 2.0 = 40.0%)
        assert proj[75]["type"] == "PROJECTED"
        assert proj[75]["is_projected"] is True
        assert proj[75]["failure_probability_pct"] == 40.0

        # 100% is PROJECTED (40.0 + 2.0 = 42.0%)
        assert proj[100]["type"] == "PROJECTED"
        assert proj[100]["is_projected"] is True
        assert proj[100]["failure_probability_pct"] == 42.0

        # Case 2: Empty predictions -> all NONE
        proj_empty = compute_checkpoint_projections([])
        assert all(p["type"] == "NONE" for p in proj_empty.values())

    def test_early_warning_threshold_and_projected_exclusion(self):
        """Verify 70% threshold is respected and projected checkpoints NEVER trigger warnings."""
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(scenario_preset="dependency", runtime_model="bilstm2")

        # 1. Projected checkpoint must be ignored by check_and_trigger_early_warning
        proj_point = {
            "depth_percentage": 50,
            "failure_probability": 0.85,
            "failure_probability_pct": 85.0,
            "is_projected": True,
            "prediction_type": "PROJECTED",
        }
        res_proj = run.check_and_trigger_early_warning(proj_point)
        assert res_proj is None
        assert len(run.warning_history) == 0

        # 2. Actual prediction under 70% (e.g. 65%) must NOT trigger
        sub_70 = {
            "depth_percentage": 25,
            "failure_probability": 0.65,
            "failure_probability_pct": 65.0,
            "is_projected": False,
            "prediction_type": "ACTUAL",
        }
        res_sub = run.check_and_trigger_early_warning(sub_70)
        assert res_sub is None
        assert len(run.warning_history) == 0

        # 3. Actual prediction >= 70% (e.g. 78%) MUST trigger warning
        over_70 = {
            "depth_percentage": 50,
            "failure_probability": 0.78,
            "failure_probability_pct": 78.0,
            "is_projected": False,
            "prediction_type": "ACTUAL",
            "model_name": "bilstm2",
            "risk_tier": "CRITICAL RISK",
        }
        res_over = run.check_and_trigger_early_warning(over_70)
        assert res_over is not None
        assert len(run.warning_history) == 1
        assert run.warning_history[0]["failure_probability_pct"] == 78.0
        assert run.warning_history[0]["threshold"] == 0.70

    def test_log_ingestion_and_deduplication(self, client):
        """Verify actual log ingestion, deduplication, and Parser V2 evidence streaming."""
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(scenario_preset="dependency", runtime_model="bilstm2")
        run_id = run.run_id

        chunk_1 = "2026-10-30T14:00:00Z Setting up runner environment\nPython 3.12.5"
        res_chunk1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_1,
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "depth": 25
        })
        assert res_chunk1.status_code == 200
        data1 = res_chunk1.json()
        assert data1["log_chunks_count"] == 1
        assert "Setting up runner environment" in data1["accumulated_log"]

        # Duplicate delivery retry of chunk 1
        res_dup = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_1,
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "depth": 25
        })
        assert res_dup.status_code == 200
        data_dup = res_dup.json()
        # Duplicate should be ignored and not increment chunks count
        assert data_dup["log_chunks_count"] == 1

        # Chunk 2 with dependency error in GitHub Actions format
        chunk_2 = (
            "build_job\tInstall Dependencies\t2026-10-30T14:01:00Z pip install -r requirements.txt\n"
            "build_job\tInstall Dependencies\t2026-10-30T14:01:02Z ERROR: Could not find a version that satisfies the requirement missing_pkg==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-30T14:01:02Z ERROR: No matching distribution found for missing_pkg==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-30T14:01:03Z ##[error]Process completed with exit code 1."
        )
        res_chunk2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_2,
            "step_name": "Install Dependencies",
            "stage": "build",
            "is_final": True,
            "exit_code": 1,
            "depth": 50
        })
        assert res_chunk2.status_code == 200
        data2 = res_chunk2.json()
        assert data2["log_chunks_count"] == 2
        assert data2["actual_outcome"] == "failure"
        assert data2["parser_v2_result"] is not None
        assert data2["parser_v2_result"]["failure_type"] == "dependency_error" or data2["parser_v2_result"]["status"] == "failure"

    def test_run_history_endpoints_and_inspection(self, client):
        """Verify historical runs, details, prediction history, and summaries APIs."""
        # 1. Fetch runs list
        res_runs = client.get("/api/demo/runs?limit=10")
        assert res_runs.status_code == 200
        runs = res_runs.json()
        assert len(runs) > 0

        target_run_id = runs[0]["run_id"]

        # 2. Fetch run details
        res_det = client.get(f"/api/demo/runs/{target_run_id}")
        assert res_det.status_code == 200
        det = res_det.json()
        assert det["run_id"] == target_run_id
        assert "accumulated_log" in det
        assert "runtime_predictions" in det
        assert "checkpoint_projections" in det

        # 3. Fetch prediction history
        res_hist = client.get(f"/api/demo/runs/{target_run_id}/prediction-history")
        assert res_hist.status_code == 200
        assert isinstance(res_hist.json(), list)

        # 4. Fetch risk progression
        res_prog = client.get(f"/api/demo/runs/{target_run_id}/risk-progression")
        assert res_prog.status_code == 200
        assert isinstance(res_prog.json(), list)

        # 5. Fetch warnings
        res_warn = client.get(f"/api/demo/runs/{target_run_id}/warnings")
        assert res_warn.status_code == 200
        assert isinstance(res_warn.json(), list)

        # 6. Fetch run summary
        res_sum = client.get(f"/api/demo/runs/{target_run_id}/summary")
        assert res_sum.status_code == 200
        assert "run_id" in res_sum.json()

    def test_replay_sample_stream_local_simulation(self, client):
        """Verify replay_sample_stream advances a run through 4 checkpoints to completion."""
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.create_run(scenario_preset="dependency", runtime_model="bilstm2")
        run_id = run.run_id

        res_replay = client.post(f"/api/demo/runs/{run_id}/replay", json={
            "sample_id": "F2/run_0005.log",
            "chunk_lines": 40
        })
        assert res_replay.status_code == 200
        rep_data = res_replay.json()

        # Should have ingested all 4 checkpoints
        assert rep_data["log_chunks_count"] == 4
        assert rep_data["status"] == "completed"
        assert rep_data["actual_outcome"] == "failure"
        assert len(rep_data["runtime_predictions"]) >= 2
        assert rep_data["parser_v2_result"] is not None

    def test_existing_batch_a_functionality_preserved(self, client):
        """Confirm System Health, Scenarios, and Overview APIs remain 100% operational."""
        # 1. Health check
        res_health = client.get("/api/health/system")
        assert res_health.status_code == 200
        assert res_health.json()["status"] in ["HEALTHY", "DEGRADED"]

        # 2. Scenarios list
        res_sc = client.get("/api/scenarios")
        assert res_sc.status_code == 200
        assert len(res_sc.json()) == 4

        # 3. Model comparison endpoint
        res_comp = client.post("/api/demo/compare-models", json={
            "log_text": "2026-10-30 pip install missing-pkg\nERROR: Not found",
            "depth": 50
        })
        assert res_comp.status_code == 200
        cdata = res_comp.json()
        assert "predictions" in cdata
        assert len(cdata["predictions"]) == 3
        model_ids = [p["model_id"] for p in cdata["predictions"]]
        assert "bilstm2" in model_ids

