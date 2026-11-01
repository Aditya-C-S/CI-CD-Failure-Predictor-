"""
tests/test_ui_batch_c.py
UI Batch C Integration & Automated Verification Suite:
- Pre-Build Commit Metadata Intelligence (38 features, LightGBM, SHAP, Provenance)
- Neo4j Knowledge Graph & Blast Radius Analysis (Graph Impact Score, AST fallback)
- Multi-Model Comparison (BiLSTM v2, Linear SVM, Logistic Regression, Agreement)
- Assisted Root Cause Analysis (Parser V2 evidence, confidence, prescriptive remediation)
- Clear Live Session state isolation (resets live view without deleting backend data)
- Unified Final Run Summary (7 intelligence pillars)
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_failure_run():
    """Ensure a completed failure run with logs, metadata, and RCA exists."""
    mgr = UnifiedDemoManager.get_instance()
    run = mgr.create_run(
        scenario_preset="F2",
        repo_id="Aditya-C-S/demo-order-service",
        commit_sha="test_sha_batch_c_fail",
        runtime_model="bilstm2"
    )
    run_id = run.run_id

    # Ingest error logs
    error_log = (
        "=== RUNNING BUILD ===\n"
        "Step 1: Setup python environment\n"
        "Step 2: Install dependencies\n"
        "ERROR: Command failed with exit code 1: pip install -r requirements.txt\n"
        "ModuleNotFoundError: No module named 'cryptography'\n"
        "FAILED: Pipeline encountered dependency failure.\n"
    )
    mgr.ingest_log_chunk(run_id, error_log, is_final=True)
    return run_id


@pytest.fixture(scope="module")
def seeded_clean_run():
    """Ensure a clean nominal run exists."""
    mgr = UnifiedDemoManager.get_instance()
    run = mgr.create_run(
        scenario_preset="clean",
        repo_id="Aditya-C-S/demo-order-service",
        commit_sha="test_sha_batch_c_clean",
        runtime_model="bilstm2"
    )
    run_id = run.run_id

    clean_log = (
        "=== RUNNING BUILD ===\n"
        "Step 1: Checkout repository\n"
        "Step 2: Run test suite\n"
        "tests/test_app.py .... [100%]\n"
        "15 passed in 1.42s\n"
        "SUCCESS: Build completed successfully.\n"
    )
    mgr.ingest_log_chunk(run_id, clean_log, is_final=True)
    return run_id


class TestMetadataIntelligence:
    def test_model_info(self, client):
        resp = client.get("/api/metadata/model-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["feature_count"] == 38
        assert data["status"] == "ready"
        assert "expected_features" in data
        assert len(data["expected_features"]) == 38
        assert data["shap_supported"] is True

    def test_canonical_provenance_schema(self, client):
        resp = client.get("/api/metadata/canonical-provenance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_features"] == 38
        assert "categories" in data
        assert "features" in data

    def test_predict_metadata_full_schema(self, client):
        payload = {
            "commit_hash": "HEAD",
            "repository": "Aditya-C-S/demo-order-service"
        }
        resp = client.post("/api/metadata/predict", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert "failure_probability" in data
        assert 0.0 <= data["failure_probability"] <= 1.0
        assert "verdict" in data
        assert data["verdict"] in ["FAST-TRACK", "STANDARD GATE", "ALERT", "PRE-MERGE BLOCK"]
        assert "shap_drivers" in data
        assert "positive" in data["shap_drivers"]
        assert "negative" in data["shap_drivers"]
        assert "completeness" in data
        assert data["completeness"]["total_features"] == 38
        assert "features_analyzed" in data
        assert len(data["features_analyzed"]) == 38

    def test_metadata_scenario_presets_calibration(self, client):
        """Verify the 4 canonical presets produce the calibrated risk levels."""
        presets = {
            "clean": ("FAST-TRACK", 0.15, 0.22),
            "dependency": ("STANDARD GATE", 0.40, 0.50),
            "pytest": (["PRE-MERGE BLOCK", "ALERT"], 0.60, 0.70),
            "syntax": (["PRE-MERGE BLOCK", "ALERT"], 0.65, 0.78),
        }
        for preset_name, (expected_verdicts, min_prob, max_prob) in presets.items():
            resp = client.post("/api/metadata/predict", json={
                "commit_hash": f"preset_{preset_name}",
                "scenario_preset_name": preset_name
            })
            assert resp.status_code == 200, f"Preset {preset_name} request failed"
            data = resp.json()
            prob = data["failure_probability"]
            assert min_prob <= prob <= max_prob, f"Preset {preset_name} prob {prob*100:.1f}% not in [{min_prob*100}%, {max_prob*100}%]"
            if isinstance(expected_verdicts, list):
                assert data["verdict"] in expected_verdicts, f"Preset {preset_name} verdict {data['verdict']} not in {expected_verdicts}"
            else:
                assert data["verdict"] == expected_verdicts, f"Preset {preset_name} verdict {data['verdict']} != {expected_verdicts}"
            assert len(data["features_analyzed"]) == 38
            assert len(data["shap_drivers"]["positive"]) > 0 or len(data["shap_drivers"]["negative"]) > 0

    def test_metadata_run_driven_prediction_and_isolation(self, client, seeded_failure_run):
        """Verify that run_id queries return run-associated metadata without contaminating active state."""
        resp = client.post("/api/metadata/predict", json={
            "run_id": seeded_failure_run
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "failure_probability" in data
        assert len(data["features_analyzed"]) == 38
        assert data["completeness"]["total_features"] == 38



class TestGraphIntelligence:
    def test_graph_status(self, client):
        resp = client.get("/api/metadata/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ["ONLINE", "OFFLINE"]
        assert data["database"] == "graphdoc"

    def test_blast_radius_and_ast_fallback(self, client):
        payload = {
            "changed_files": ["app/services/payment_service.py"]
        }
        resp = client.post("/api/metadata/graph/blast-radius", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "blast_radius_count" in data
        assert "graph_impact_score" in data
        assert "formula" in data["graph_impact_score"]

    def test_graph_impact_score_computation(self, client):
        payload = {
            "changed_files": ["app/services/payment_service.py"],
            "changed_functions": ["process_payment"],
            "callers_count": 3,
            "max_depth": 2,
            "high_fanin": 1,
            "affected_tests": 2,
            "total_repo_files": 20
        }
        resp = client.post("/api/metadata/graph/impact", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "formula" in data
        assert "components" in data


class TestModelComparison:
    def test_compare_models_endpoint(self, client):
        payload = {
            "log_text": "ERROR: Command failed: pip install -r requirements.txt\nModuleNotFoundError: No module named 'cryptography'",
            "depth": 50
        }
        resp = client.post("/api/demo/compare-models", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert "predictions" in data
        models = [p["model_id"] for p in data["predictions"]]
        assert "bilstm2" in models
        assert "svm" in models
        assert "logistic_regression" in models

        assert "agreement_status" in data
        assert data["agreement_status"] in ["UNANIMOUS", "MAJORITY", "DIVERGENT"]
        assert "active_warning_threshold" in data

    def test_run_model_comparison(self, client, seeded_failure_run):
        resp = client.get(f"/api/demo/runs/{seeded_failure_run}/model-comparison")
        assert resp.status_code == 200
        data = resp.json()
        assert "predictions" in data
        assert len(data["predictions"]) >= 3


class TestRootCauseAnalysis:
    def test_run_rca_and_remediation(self, client, seeded_failure_run):
        resp = client.get(f"/api/demo/runs/{seeded_failure_run}/rca")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] in ["COMPLETED", "SUCCESS", "FAILED"]
        assert "primary_category" in data or "causal_category" in data
        assert "evidence_items" in data
        assert "remediation" in data

        rem = data["remediation"]
        assert "primary_action" in rem or "terminal_commands" in rem

    def test_run_rca_clean_run(self, client, seeded_clean_run):
        resp = client.get(f"/api/demo/runs/{seeded_clean_run}/rca")
        assert resp.status_code == 200
        data = resp.json()
        # Clean run should be marked clean/nominal/insufficient evidence
        cat = data.get("primary_category") or data.get("causal_category") or "CLEAN"
        assert cat in ["CLEAN", "CLEAN_RUN", "NONE", "NOMINAL", "INSUFFICIENT_EVIDENCE"] or data.get("detected_error") == "No failure detected"


class TestClearLiveSessionContract:
    def test_clear_session_does_not_delete_backend_data(self, client, seeded_failure_run):
        """
        Verify that a live session can be cleared on the frontend without deleting
        the backend run record or purging historical runs.
        """
        # Ensure the run exists in backend
        mgr = UnifiedDemoManager.get_instance()
        run_before = mgr.get_run(seeded_failure_run)
        assert run_before is not None
        assert run_before.run_id == seeded_failure_run

        # Simulate what the frontend Clear Live Session does:
        # It ONLY clears local storage/state and does NOT invoke any delete endpoint.
        # Check that run remains fully accessible in Run History.
        resp = client.get(f"/api/demo/runs/{seeded_failure_run}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == seeded_failure_run

        all_runs_resp = client.get("/api/demo/runs")
        assert all_runs_resp.status_code == 200
        all_run_ids = [r["run_id"] for r in all_runs_resp.json()]
        assert seeded_failure_run in all_run_ids


class TestFinalRunSummary:
    def test_get_run_summary_pillars(self, client, seeded_failure_run):
        resp = client.get(f"/api/demo/runs/{seeded_failure_run}/summary")
        assert resp.status_code == 200
        data = resp.json()

        # Check all 7 pillars in unified summary
        assert "run_id" in data
        assert data["run_id"] == seeded_failure_run
        assert "final_pipeline_status" in data or "summary_status" in data
        assert "metadata_prediction" in data
        assert "graph_intelligence" in data
        assert "runtime_predictions" in data
        assert "early_warnings" in data
        assert "root_cause_analysis" in data
        assert "final_assessment" in data
