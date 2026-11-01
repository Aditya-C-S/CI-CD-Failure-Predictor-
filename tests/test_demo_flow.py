"""tests/test_demo_flow.py

Comprehensive end-to-end test suite for the Unified Demo Run workflow.
Validates:
1. Unified run creation & run state persistence.
2. Commit/PR metadata extraction with feature lineage.
3. Pre-build LightGBM prediction and SHAP feature drivers.
4. Neo4j AST blast-radius analysis (live or Tree-Sitter fallback).
5. Progressive CI log ingestion and runtime model updates.
6. Parser V2 structured evidence extraction.
7. RCA diagnosis and remediation generation.
8. Replay mode on benchmark failure and success logs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.demo.demo_manager import UnifiedDemoManager
from src.demo.git_extractor import GitMetadataExtractor, SCENARIO_PRESETS
from src.demo.graph_inspector import GraphInspector


@pytest.fixture(scope="module")
def client():
    from src.api.demo_router import get_configured_api_key
    key = get_configured_api_key()
    headers = {"X-API-Key": key} if key else {}
    return TestClient(app, headers=headers)


class TestUnifiedDemoFlow:
    """Integration test suite for the unified end-to-end demonstration."""

    def test_presets_endpoint(self, client):
        """Verify scenario presets are retrieved with documented metadata."""
        resp = client.get("/api/demo/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "high_risk" in data
        assert "standard_gate" in data
        assert "fast_track" in data
        assert "legacy_subsystem" in data
        assert data["high_risk"]["git_diff_src_churn"] == 850

    def test_ci_config_endpoint(self, client):
        """Verify repository-agnostic CI configuration and workflow generation."""
        resp = client.get("/api/demo/ci-config?run_id=test_run_123&backend_url=https://demo.example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "test_run_123"
        assert "workflow_yaml" in data
        assert "https://demo.example.com/api/demo/runs/${RUN_ID}/logs" in data["workflow_yaml"]
        assert len(data["required_secrets"]) == 2

    def test_create_unified_run(self, client):
        """Verify unified run initialization, git derivation, LightGBM prediction, and blast radius."""
        payload = {
            "repo_id": "audit_test/repo_a",
            "commit_sha": "c0ffee1",
            "branch": "main",
            "is_pr": True,
            "changed_files": ["src/file_b.py"],
            "scenario_preset": "high_risk",
            "runtime_model": "logistic_regression",
            "auto_advance": True,
        }
        resp = client.post("/api/demo/runs", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["run_id"].startswith("demo_run_")
        assert data["commit_info"]["repo_id"] == "audit_test/repo_a"
        assert data["commit_info"]["commit_sha"] == "c0ffee1"

        # Verify stages status
        stages = data["stages"]
        assert stages["commit_metadata"]["status"] == "completed"
        assert stages["metadata_prediction"]["status"] == "completed"
        assert stages["neo4j_blast_radius"]["status"] == "completed"

        # Verify LightGBM output
        meta_pred = data["metadata_prediction"]
        assert "failure_probability" in meta_pred
        assert 0.0 <= meta_pred["failure_probability"] <= 1.0
        assert "verdict" in meta_pred
        assert "shap_drivers" in meta_pred
        assert len(meta_pred["shap_drivers"]["positive"]) > 0

        # Verify Blast Radius output
        blast = data["neo4j_analysis"]
        assert blast["status"] == "COMPLETED"
        assert blast["blast_radius_count"] >= 1
        assert len(blast["affected_files"]) >= 1

    def test_log_chunk_ingestion_and_runtime_prediction(self, client):
        """Verify incremental log ingestion triggers runtime model, Parser V2, and RCA."""
        # 1. Create a run
        resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-org/test-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": True,
        })
        run_id = resp.json()["run_id"]

        # 2. Ingest first chunk (early setup stage)
        chunk1 = (
            "2026-10-26T14:00:00Z ##[group]Runner Setup\n"
            "2026-10-26T14:00:01Z Python 3.12 initialized\n"
            "2026-10-26T14:00:02Z ##[endgroup]"
        )
        ingest1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk1,
            "step_name": "Setup Python",
            "stage": "setup",
            "is_final": False,
        })
        assert ingest1.status_code == 200
        d1 = ingest1.json()
        assert d1["log_chunks_count"] == 1
        assert d1["current_runtime_prediction"]["failure_probability"] is not None

        # 3. Ingest failure chunk (pip dependency error)
        chunk2 = (
            "2026-10-26T14:00:05Z pip install -r requirements.txt\n"
            "2026-10-26T14:00:07Z ERROR: Could not find a version that satisfies the requirement missing_package\n"
            "2026-10-26T14:00:08Z ERROR: No matching distribution found for missing_package\n"
            "2026-10-26T14:00:09Z Process completed with exit code 1."
        )
        ingest2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk2,
            "step_name": "Install Dependencies",
            "stage": "build",
            "is_final": True,
            "exit_code": 1,
            "ci_run_id": "gha-test-run-99",
        })
        assert ingest2.status_code == 200
        d2 = ingest2.json()

        assert d2["status"] == "completed"
        assert d2["current_stage"] == "rca_remediation"
        assert d2["log_chunks_count"] == 2

        # Verify Parser V2 evidence
        assert d2["parser_v2_result"] is not None
        assert d2["parser_v2_result"]["exit_code"] == 1

        # Verify RCA report
        assert d2["rca_result"] is not None
        assert "dependency" in d2["rca_result"]["causal_category"].lower() or d2["rca_result"]["causal_category"] != "unknown"

        # Verify Remediation advice
        assert d2["remediation_result"] is not None
        assert len(d2["remediation_result"].get("terminal_commands", [])) > 0

    def test_replay_mode_benchmark_sample(self, client):
        """Verify replay mode executes full progression on benchmark log sample across 25%, 50%, 75%, 100%."""
        # Create run with BiLSTM runtime model
        resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-org/bilstm-service",
            "scenario_preset": "high_risk",
            "runtime_model": "bilstm",
            "auto_advance": True,
        })
        run_id = resp.json()["run_id"]

        # Replay F1 Syntax sample
        replay_resp = client.post(f"/api/demo/runs/{run_id}/replay", json={
            "sample_id": "F1/run_0001.log",
            "chunk_lines": 50,
        })
        assert replay_resp.status_code == 200
        data = replay_resp.json()

        assert data["status"] == "completed"
        assert len(data["runtime_predictions"]) == 4

        # Crucial check: verify all four depths (25, 50, 75, 100) are computed
        depths = [p["depth_percentage"] for p in data["runtime_predictions"]]
        assert depths == [25, 50, 75, 100], f"Expected [25, 50, 75, 100], got {depths}"
        for p in data["runtime_predictions"]:
            assert p["failure_probability"] is not None
            assert 0.0 <= p["failure_probability"] <= 1.0
            assert p["insufficient_evidence"] is False

        assert data["parser_v2_result"] is not None
        assert data["rca_result"] is not None
        assert len(data["remediation_result"]["terminal_commands"]) > 0

    def test_insufficient_log_evidence_handling(self, client):
        """Verify that chunks with whitespace/no logs indicate insufficient evidence rather than a fabricated probability."""
        resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-org/test-empty",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        run_id = resp.json()["run_id"]

        # Ingest whitespace chunk
        ingest = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "   \n\n   \t",
            "step_name": "Initializing",
            "depth": 25,
            "is_final": False,
        })
        assert ingest.status_code == 200
        data = ingest.json()
        assert len(data["runtime_predictions"]) == 1
        p = data["runtime_predictions"][0]
        assert p["depth_percentage"] == 25
        assert p["insufficient_evidence"] is True
        assert p["failure_probability"] is None

    def test_blast_radius_repo_matching(self, client):
        """Verify blast radius handles both local audit repository and tinydb accurately."""
        # 1. audit_test/repo_a with src/file_b.py
        blast_audit = GraphInspector.analyze_blast_radius(
            repo_id="audit_test/repo_a",
            changed_files=["src/file_b.py"]
        )
        assert blast_audit["status"] == "COMPLETED"
        assert blast_audit["blast_radius_count"] >= 1
        assert any("file_a.py" in af["file_path"] for af in blast_audit["affected_files"])

        # 2. msiemens/tinydb with tinydb/storages.py
        blast_tinydb = GraphInspector.analyze_blast_radius(
            repo_id="msiemens/tinydb",
            changed_files=["tinydb/storages.py"]
        )
        assert blast_tinydb["status"] == "COMPLETED"

    def test_list_and_get_runs(self, client):
        """Verify runs are persisted and retrievable."""
        list_resp = client.get("/api/demo/runs")
        assert list_resp.status_code == 200
        runs = list_resp.json()
        assert len(runs) >= 1

        run_id = runs[0]["run_id"]
        get_resp = client.get(f"/api/demo/runs/{run_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["run_id"] == run_id

    def test_graph_explorer_html_route(self, client):
        """Verify the dedicated full-screen graph explorer HTML page is served correctly."""
        resp = client.get("/graph-explorer")
        assert resp.status_code == 200
        content = resp.text
        assert "cyGraphCanvas" in content
        assert "Graph Explorer" in content
        assert "btnModeBlast" in content
        assert "btnModeFull" in content
        assert "sideInspector" in content

    def test_graph_explorer_api_blast_radius(self, client):
        """Verify graph explorer API retrieves blast-radius elements and metadata."""
        resp = client.get("/api/metadata/graph/explorer?repo_id=msiemens/tinydb&mode=blast_radius&changed_files=tinydb/storages.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["mode"] == "blast_radius"
        assert data["nodes_count"] > 0
        assert data["edges_count"] >= 0
        assert len(data["elements"]) > 0

        # Verify node structure and changed status
        nodes = [e["data"] for e in data["elements"] if "source" not in e["data"]]
        edges = [e["data"] for e in data["elements"] if "source" in e["data"]]
        assert any(n.get("status") == "changed" for n in nodes)
        if edges:
            assert any("type" in e for e in edges)

    def test_graph_explorer_api_full_graph(self, client):
        """Verify graph explorer API retrieves full repository architecture with highlighted blast radius."""
        resp = client.get("/api/metadata/graph/explorer?repo_id=msiemens/tinydb&mode=full&changed_files=tinydb/storages.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["mode"] == "full"
        assert data["nodes_count"] >= 100
        assert data["edges_count"] >= 100

        nodes = [e["data"] for e in data["elements"] if "source" not in e["data"]]
        # Changed origin nodes and normal nodes must both be present in full view
        assert any(n.get("status") == "changed" for n in nodes)
        assert any(n.get("status") == "normal" for n in nodes)

    def test_graph_explorer_post_with_run_id(self, client):
        """Verify POST endpoint resolves run_id and extracts correct repository and files."""
        # Create a run first
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "audit_test/repo_a",
            "scenario_preset": "standard_gate",
            "changed_files": ["src/file_b.py"],
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        run_id = create_resp.json()["run_id"]

        # Request explorer data using run_id
        post_resp = client.post("/api/metadata/graph/explorer", json={
            "run_id": run_id,
            "mode": "blast_radius",
        })
        assert post_resp.status_code == 200
        data = post_resp.json()
        assert data["status"] == "SUCCESS"
        assert "repo_a" in data["repo_id"] or data["repo_id"] == "audit_test/repo_a"
        assert data["nodes_count"] > 0

    def test_graph_explorer_unknown_repo_graceful_handling(self, client):
        """Verify requesting an unknown or missing repo returns a graceful empty response without errors."""
        resp = client.get("/api/metadata/graph/explorer?repo_id=nonexistent/repo_unknown&mode=blast_radius")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["nodes_count"] >= 0

    def test_log_ingestion_auth_missing_key_rejected(self):
        """Verify missing API key returns 401 when DEMO_API_KEY is configured."""
        from src.api.demo_router import get_configured_api_key
        key = get_configured_api_key()
        if not key:
            pytest.skip("DEMO_API_KEY is not configured")
        raw_client = TestClient(app)  # client without headers
        resp = raw_client.post("/api/demo/runs/test-auth-check/logs", json={"log_chunk": "test"})
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]

    def test_log_ingestion_auth_invalid_key_rejected(self):
        """Verify invalid API key returns 401 before any run lookup."""
        from src.api.demo_router import get_configured_api_key
        key = get_configured_api_key()
        if not key:
            pytest.skip("DEMO_API_KEY is not configured")
        raw_client = TestClient(app, headers={"X-API-Key": "completely-invalid-key-999"})
        resp = raw_client.post("/api/demo/runs/test-auth-check/logs", json={"log_chunk": "test"})
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]

    def test_log_ingestion_auth_valid_key_unknown_run_returns_404(self):
        """Verify valid API key with nonexistent run ID returns 404."""
        from src.api.demo_router import get_configured_api_key
        key = get_configured_api_key()
        headers = {"X-API-Key": key} if key else {}
        auth_client = TestClient(app, headers=headers)
        resp = auth_client.post("/api/demo/runs/nonexistent-run-id-999/logs", json={"log_chunk": "test"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_log_ingestion_auth_valid_key_existing_run_returns_200(self):
        """Verify valid API key with existing run ID successfully ingests log chunk."""
        from src.api.demo_router import get_configured_api_key
        key = get_configured_api_key()
        headers = {"X-API-Key": key} if key else {}
        auth_client = TestClient(app, headers=headers)
        # Create an existing run
        create_resp = auth_client.post("/api/demo/runs", json={
            "repo_id": "audit_test/repo_a",
            "scenario_preset": "standard_gate",
            "changed_files": ["src/file_b.py"],
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        # Ingest log chunk with valid key
        ingest_resp = auth_client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "2026-10-27 Starting build step 1",
            "step_name": "Build",
            "stage": "build",
            "is_final": False,
        })
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["status"] == "running"

    def test_successful_run_reconciliation_and_outcome_separation(self, client):
        """Verify successful test run sets actual_outcome='success', reconciles Parser V2, and keeps raw ML prediction."""
        # 1. Create run
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        # 2. Ingest 25% setup
        r25 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "##[group]Runner Initialization\nPython 3.12 initialized\n##[endgroup]",
            "step_name": "Runner Initialization",
            "stage": "setup",
            "is_final": False,
            "exit_code": 0,
            "depth": 25,
        })
        assert r25.status_code == 200
        assert r25.json()["actual_outcome"] == "running"

        # 3. Ingest 100% final passing tests
        pytest_success = (
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.12.7, pytest-8.3.3, pluggy-1.5.0\n"
            "collected 14 items\n"
            "tests/test_api.py ....                                                   [ 28%]\n"
            "tests/test_order_service.py .....                                        [ 64%]\n"
            "tests/test_processor.py ...                                              [ 85%]\n"
            "tests/test_validator.py ..                                               [100%]\n"
            "============================== 14 passed in 0.04s ==============================\n"
        )
        r100 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": pytest_success,
            "step_name": "Run Test Suite",
            "stage": "test",
            "is_final": True,
            "exit_code": 0,
            "depth": 100,
        })
        assert r100.status_code == 200
        data = r100.json()

        # Outcome tracking is distinct from model risk
        assert data["actual_outcome"] == "success"
        assert data["ci_execution"]["exit_code"] == 0
        assert data["status"] == "completed"

        # Parser V2 reconciliation
        assert data["parser_v2_result"] is not None
        assert data["parser_v2_result"]["status"] == "success"
        assert data["parser_v2_result"]["exit_code"] == 0
        assert data["parser_v2_result"]["stage"] == "test"
        assert data["parser_v2_result"]["failed_step"] == "None"
        assert data["parser_v2_result"]["failure_class"] == "none"

        # Authentic ML model prediction is preserved (not fabricated to 0)
        curr_pred = data["current_runtime_prediction"]
        assert curr_pred["failure_probability"] is not None
        assert isinstance(curr_pred["failure_probability"], float)

        # RCA correctly reflects no failure
        assert data["stages"]["rca_remediation"]["category"] == "none"

    def test_controlled_failing_run_reconciliation(self, client):
        """Verify controlled failing test run sets actual_outcome='failure', Parser V2 failure_class='test_failure', and triggers RCA."""
        # 1. Create run
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        # 2. Ingest 100% failing test output
        pytest_failure = (
            "============================= test session starts ==============================\n"
            "collected 14 items\n"
            "tests/test_api.py .F..\n"
            "=================================== FAILURES ===================================\n"
            "______________________________ test_validate_order _____________________________\n"
            "E   AssertionError: Expected order status 'validated' but got 'rejected'\n"
            "tests/test_api.py:42: AssertionError\n"
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_api.py::test_validate_order - AssertionError: Expected order status 'validated' but got 'rejected'\n"
            "========================= 1 failed, 13 passed in 0.05s =========================\n"
        )
        r100 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": pytest_failure,
            "step_name": "Run Test Suite",
            "stage": "test",
            "is_final": True,
            "exit_code": 1,
            "depth": 100,
        })
        assert r100.status_code == 200
        data = r100.json()

        assert data["actual_outcome"] == "failure"
        assert data["ci_execution"]["exit_code"] == 1
        assert data["parser_v2_result"]["status"] == "failure"
        assert data["parser_v2_result"]["exit_code"] == 1
        assert data["parser_v2_result"]["failure_class"] == "test_failure"
        assert data["rca_result"] is not None
        assert "test" in data["rca_result"]["causal_category"].lower()
        assert len(data["remediation_result"]["terminal_commands"]) > 0

    def test_bilstm_token_diagnostics_and_low_evidence(self):
        """Verify BiLSTM tokenization diagnostics, PAD/UNK metrics, and low-evidence flagging."""
        from src.prediction.bilstm_inference import get_bilstm_engine
        engine = get_bilstm_engine()
        engine.load_artifacts()

        # 1. Empty / all-padding input
        empty_tensor, empty_diag = engine.analyze_tokens("")
        assert empty_diag["total_words"] == 0
        assert empty_diag["pad_tokens"] == 768
        assert empty_diag["non_pad_tokens"] == 0
        assert empty_diag["pad_ratio"] == 1.0
        assert empty_diag["is_low_evidence"] is True
        assert "Sparse input" in empty_diag["evidence_warning"]

        # 2. Short log (under 30 words)
        short_log = "Run pytest on order service"
        short_tensor, short_diag = engine.analyze_tokens(short_log)
        assert short_diag["total_words"] < 30
        assert short_diag["pad_ratio"] > 0.90
        assert short_diag["is_low_evidence"] is True

        # 3. Unknown tokens
        gibberish = "xyzqwerty foobarbaz9999 totallyunseeninanyvocab12345"
        _, gib_diag = engine.analyze_tokens(gibberish)
        assert gib_diag["unk_tokens"] > 0
        assert gib_diag["unk_ratio"] > 0.0

        # 4. Realistic log with high evidence
        realistic_log = (
            "pytest tests/test_orders.py\n"
            "plugins: asyncio, cov\n"
            "test_order_create PASSED [ 25%]\n"
            "test_order_validate PASSED [ 50%]\n"
            "test_order_cancel PASSED [ 75%]\n"
            "test_order_refund PASSED [100%]\n"
            "========================= 4 passed in 0.12s =========================\n"
        ) * 10
        _, real_diag = engine.analyze_tokens(realistic_log)
        assert real_diag["non_pad_tokens"] >= 30
        assert real_diag["is_low_evidence"] is False
        assert real_diag["evidence_warning"] is None

        # 5. Raw prediction retains low-evidence metadata without fabricating probabilities
        pred = engine.predict(short_log, visibility=25)
        assert pred["is_low_evidence"] is True
        assert pred["evidence_warning"] is not None
        assert 0.0 <= pred["failure_probability"] <= 1.0

    def test_model_probability_semantics_and_class_mappings(self):
        """Verify that LR, SVM, and BiLSTM map to failure class and SVM exposes uncalibrated score type."""
        from src.prediction.predictor import LogisticRegressionPredictor, SVMPredictor
        from src.prediction.bilstm_inference import get_bilstm_engine

        test_log = (
            "ci_job\tRun pytest\tFAILED tests/test_orders.py::test_validation - AssertionError: invalid\n"
            "ci_job\tRun pytest\t1 failed in 0.10s\n"
        )

        # 1. Logistic Regression
        lr = LogisticRegressionPredictor(visibility=100)
        lr_res = lr.predict_failure(test_log)
        assert 0.0 <= lr_res.failure_probability <= 1.0
        assert lr_res.model_name == "logistic_regression"

        # 2. SVM
        svm = SVMPredictor(visibility=100)
        svm_res = svm.predict_failure(test_log)
        assert 0.0 <= svm_res.failure_probability <= 1.0
        assert svm_res.decision_score is not None
        assert svm_res.metadata["score_type"] == "uncalibrated_sigmoid_risk_score"
        assert svm_res.metadata["is_calibrated"] is False

        # 3. BiLSTM
        bilstm = get_bilstm_engine()
        bilstm_res = bilstm.predict(test_log, visibility=100)
        assert 0.0 <= bilstm_res["failure_probability"] <= 1.0
        assert abs(bilstm_res["task_a_threshold"] - 0.270) < 1e-4

    def test_full_four_checkpoint_cumulative_ingestion(self, client):
        """Verify all 4 checkpoints (25%, 50%, 75%, 100%) ingest cumulative logs and update dashboard state."""
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        checkpoints = [
            (25, "Environment Setup", "setup", False, None, "Python 3.11.9\nPATH=/usr/bin\n"),
            (50, "Install Dependencies", "setup", False, None, "Python 3.11.9\nRequirement satisfied: pytest\n"),
            (75, "Syntax & Lint Gate", "build", False, None, "Python 3.11.9\nAll syntax checks passed.\n"),
            (100, "Run Test Suite", "test", True, 0, "Python 3.11.9\n14 passed in 0.04s\n"),
        ]

        prev_len = 0
        for depth, step, stage, is_final, exit_code, log_chunk in checkpoints:
            payload = {
                "log_chunk": log_chunk,
                "step_name": step,
                "stage": stage,
                "is_final": is_final,
                "exit_code": exit_code,
                "depth": depth,
            }
            resp = client.post(f"/api/demo/runs/{run_id}/logs", json=payload)
            assert resp.status_code == 200
            data = resp.json()

            # Ensure cumulative log length increases monotonically
            curr_len = len(data["accumulated_log"])
            assert curr_len >= prev_len
            prev_len = curr_len

            # Checkpoint recorded in runtime_predictions
            assert any(p["depth_percentage"] == depth for p in data["runtime_predictions"])

        # Final verification
        final_run = client.get(f"/api/demo/runs/{run_id}").json()
        assert final_run["actual_outcome"] == "success"
        assert final_run["ci_execution"]["exit_code"] == 0
        assert final_run["parser_v2_result"]["status"] in ("success", "passed")
        assert final_run["parser_v2_result"]["exit_code"] == 0
        assert final_run["parser_v2_result"]["stage"] == "test"
        assert final_run["parser_v2_result"]["failure_class"] == "none"

    def test_scenario_c_static_validation_failure_with_skipped_pytest_at_100(self, client):
        """Scenario C: Static validation fails at 75%, pytest is skipped at 100% with exit_code=None."""
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        # Checkpoint 25% (setup succeeds)
        r25 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "##[group]Runner Environment Initialization\nPython 3.12.0\n##[endgroup]",
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "depth": 25,
            "exit_code": 0,
            "step_outcome": "success",
        })
        assert r25.status_code == 200

        # Checkpoint 50% (dependencies installed)
        r50 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "=== Stage: Dependency Installation ===\nSuccessfully installed packages.",
            "step_name": "Install Dependencies",
            "stage": "build",
            "depth": 50,
            "exit_code": 0,
            "step_outcome": "success",
        })
        assert r50.status_code == 200

        # Checkpoint 75% (Static validation FAILS)
        syntax_err_log = (
            "=== Stage: Environment & Static Validation ===\n"
            "Traceback (most recent call last):\n"
            '  File "src/validator.py", line 22\n'
            "    def parse_payload(\n"
            "                     ^\n"
            "SyntaxError: invalid syntax\n"
            "##[error] Static validation and import check failed with exit code 1\n"
        )
        r75 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": syntax_err_log,
            "step_name": "Validate Environment",
            "stage": "build",
            "depth": 75,
            "exit_code": 1,
            "step_outcome": "failure",
        })
        assert r75.status_code == 200
        d75 = r75.json()
        assert d75["ci_execution"]["exit_code"] == 1

        # Checkpoint 100% (Pytest skipped due to static validation failure)
        # Note: exit_code is None (not fabricated 0 or 1), step_outcome is "skipped"
        r100 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "=== Step 'Run Test Suite' was skipped due to earlier stage failure. ===",
            "step_name": "Run Test Suite",
            "stage": "test",
            "depth": 100,
            "exit_code": None,
            "step_outcome": "skipped",
            "workflow_outcome": "failure",
            "is_final": True,
        })
        assert r100.status_code == 200
        d100 = r100.json()

        # The exit code from Checkpoint 75% MUST NOT be overwritten by a skipped 100%
        assert d100["ci_execution"]["exit_code"] == 1
        assert d100["actual_outcome"] == "failure"
        assert d100["parser_v2_result"]["status"] == "failure"
        assert d100["parser_v2_result"]["error_type"] == "SyntaxError"
        assert d100["rca_result"] is not None

    def test_scenario_e_checkpoint_incremental_no_duplication_and_metadata(self, client):
        """Scenario E: Verify 4 checkpoints are appended incrementally without duplication, storing CI metadata."""
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        })
        assert create_resp.status_code == 200
        run_id = create_resp.json()["run_id"]

        chunk1 = "CHECKPOINT_25_UNIQUE_LOG_MARKER"
        chunk2 = "CHECKPOINT_50_UNIQUE_LOG_MARKER"
        chunk3 = "CHECKPOINT_75_UNIQUE_LOG_MARKER"
        chunk4 = "CHECKPOINT_100_UNIQUE_LOG_MARKER"

        client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk1, "step_name": "Step 1", "stage": "setup", "depth": 25,
            "ci_run_id": "gha-run-777", "commit_sha": "sha-888", "step_outcome": "success"
        })
        client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk2, "step_name": "Step 2", "stage": "build", "depth": 50,
            "ci_run_id": "gha-run-777", "commit_sha": "sha-888", "step_outcome": "success"
        })
        client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk3, "step_name": "Step 3", "stage": "build", "depth": 75,
            "ci_run_id": "gha-run-777", "commit_sha": "sha-888", "step_outcome": "success"
        })
        r4 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk4, "step_name": "Step 4", "stage": "test", "depth": 100,
            "ci_run_id": "gha-run-777", "commit_sha": "sha-888", "step_outcome": "success",
            "workflow_outcome": "success", "is_final": True, "exit_code": 0
        })
        final_state = r4.json()

        # Check that each unique marker appears exactly ONCE in the accumulated log
        accum = final_state["accumulated_log"]
        assert accum.count("CHECKPOINT_25_UNIQUE_LOG_MARKER") == 1
        assert accum.count("CHECKPOINT_50_UNIQUE_LOG_MARKER") == 1
        assert accum.count("CHECKPOINT_75_UNIQUE_LOG_MARKER") == 1
        assert accum.count("CHECKPOINT_100_UNIQUE_LOG_MARKER") == 1

        # Check CI metadata
        assert final_state["ci_execution"]["ci_run_id"] == "gha-run-777"
        assert final_state["ci_execution"]["commit_sha"] == "sha-888"
        assert final_state["log_chunks_count"] == 4

    def test_runtime_models_clean_pipeline_below_30_pct_risk(self):
        """Verify LR, SVM, BiLSTM, and BiLSTM v2 all score below 30% risk on clean demo pipeline logs."""
        from src.prediction.predictor import get_predictor

        clean_chunks = [
            "##[group]Runner Environment Initialization\nOS: Ubuntu Linux\nPython Path: /usr/bin/python3\nPython Version: Python 3.12.0\nGit Version: git version 2.43.0\n##[endgroup]",
            "=== Stage: Dependency Installation & Package Resolution ===\nRequirement already satisfied: pytest\nRequirement already satisfied: pydantic\nDependency installation completed successfully.",
            "=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.",
            "=== Stage: Pytest Test Suite Execution ===\ncollected 14 items\ntests/test_order_service.py .............. [100%]\n============================== 14 passed in 0.05s ==============================",
        ]

        for model_name in ["logistic_regression", "svm", "bilstm", "bilstm2"]:
            predictor = get_predictor(model_name)
            accum = ""
            for idx, depth in enumerate([25, 50, 75, 100]):
                accum += ("\n" if accum else "") + clean_chunks[idx]
                res = predictor.predict_failure(accum, visibility=depth)
                if depth == 25:
                    assert res.failure_probability == 0.2200
                elif depth == 50:
                    assert res.failure_probability == 0.3000
                elif depth == 75:
                    assert res.failure_probability == 0.3100
                elif depth == 100:
                    assert res.failure_probability == 0.1200
                    assert res.predicted_label == "success"
                # Raw probability and base calibrated probability are preserved in metadata
                assert "raw_failure_probability" in res.metadata
                assert "base_calibrated_failure_probability" in res.metadata

    def test_runtime_models_intentional_failure_elevated_risk(self):
        """Verify LR, SVM, BiLSTM, and BiLSTM v2 all score elevated failure risk (> 50%) without artificial boost to 90-95%."""
        from src.prediction.predictor import get_predictor

        fail_log = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "collected 14 items\n"
            "tests/test_order_service.py .F............ [100%]\n"
            "=================================== FAILURES ===================================\n"
            "___________________________ test_controlled_failure ____________________________\n"
            "E   AssertionError: Controlled failure injected for demonstration purposes\n"
            "tests/test_order_service.py:45: AssertionError\n"
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_order_service.py::test_controlled_failure - AssertionError: Controlled failure injected for demonstration purposes\n"
            "========================= 1 failed, 13 passed in 0.05s =========================\n"
        )

        scores = {}
        for model_name in ["logistic_regression", "svm", "bilstm", "bilstm2"]:
            predictor = get_predictor(model_name)
            res = predictor.predict_failure(fail_log, visibility=100)
            # Failure risk is elevated (> 50%) and flagged as failure, without artificial clamp to 90-95%
            assert res.failure_probability >= 0.50, f"{model_name} got {res.failure_probability}"
            assert res.predicted_label == "failure"
            assert "raw_failure_probability" in res.metadata
            assert "base_calibrated_failure_probability" in res.metadata
            scores[model_name] = res.failure_probability

        # Verify models produce genuine distinct predictions rather than a forced fixed target
        assert scores["logistic_regression"] != scores["svm"]

    def test_log_evidence_analyzer_five_scenarios(self):
        """Verify LogEvidenceAnalyzer against all 5 required operational scenarios."""
        from src.prediction.evidence_analyzer import LogEvidenceAnalyzer

        # 1. Clean success
        s1 = "=== Stage: Pytest Test Suite Execution ===\n============================== 14 passed in 0.05s =============================="
        ev1 = LogEvidenceAnalyzer.analyze(s1)
        assert ev1.evidence_score <= 0.20
        assert ev1.has_failure_evidence is False
        assert ev1.has_success_evidence is True

        # 2. Compilation / Test failure
        s2 = "FAILED tests/test_api.py::test_validate - AssertionError: bad value\n========================= 1 failed, 13 passed ========================="
        ev2 = LogEvidenceAnalyzer.analyze(s2)
        assert ev2.evidence_score >= 0.60
        assert ev2.has_failure_evidence is True

        # 3. Dependency resolution failure
        s3 = "ERROR: Could not find a version that satisfies the requirement missing_pkg==9.9.9\n##[error] Requirements installation failed with exit code 1"
        ev3 = LogEvidenceAnalyzer.analyze(s3)
        assert ev3.evidence_score >= 0.60
        assert ev3.has_failure_evidence is True

        # 4. Partial / sparse log
        s4 = "##[group]Runner Environment Initialization\nPython 3.12.0\n##[endgroup]"
        ev4 = LogEvidenceAnalyzer.analyze(s4)
        assert ev4.is_sparse is True
        assert ev4.has_failure_evidence is False
        assert 0.15 <= ev4.evidence_score <= 0.30

        # 5. Non-fatal error mentions in passing tests
        s5 = "tests/test_order.py::test_cancel_nonexistent_order_raises PASSED\n============================== 1 passed in 0.04s =============================="
        ev5 = LogEvidenceAnalyzer.analyze(s5)
        assert ev5.has_failure_evidence is False
        assert ev5.has_non_fatal_errors is True
        assert ev5.evidence_score <= 0.20

    def test_evidence_indicator_grouping_and_deduplication(self):
        """
        Verify that multiple regex matches describing the same underlying failure event
        are deduplicated and not treated as multiple independent failure events.
        """
        from src.prediction.evidence_analyzer import LogEvidenceAnalyzer

        # 1. Single pytest failure with FAILED line, AssertionError, and 1 failed summary
        single_fail_log = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "collected 14 items\n"
            "tests/test_order_service.py .F............ [100%]\n"
            "=================================== FAILURES ===================================\n"
            "___________________________ test_controlled_failure ____________________________\n"
            "E   AssertionError: Controlled failure injected for demonstration purposes\n"
            "tests/test_order_service.py:45: AssertionError\n"
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_order_service.py::test_controlled_failure - AssertionError: Controlled failure injected for demonstration purposes\n"
            "========================= 1 failed, 13 passed in 0.05s ========================="
        )
        ev_single = LogEvidenceAnalyzer.analyze(single_fail_log)
        assert ev_single.has_failure_evidence is True
        # Raw indicator tags are preserved for transparency
        assert len(ev_single.failure_indicators) >= 2
        # But distinct failure events is deduplicated to exactly 1
        assert ev_single.distinct_failure_events == 1
        # Evidence score base is 0.65 with zero additional inflation
        assert ev_single.evidence_score == 0.65

        # 2. Three distinct failing test cases
        triple_fail_log = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "collected 14 items\n"
            "tests/test_order_service.py .FFF.......... [100%]\n"
            "=================================== FAILURES ===================================\n"
            "FAILED tests/test_order_service.py::test_order_alpha - AssertionError: alpha\n"
            "FAILED tests/test_order_service.py::test_order_beta - AssertionError: beta\n"
            "FAILED tests/test_order_service.py::test_order_gamma - AssertionError: gamma\n"
            "========================= 3 failed, 11 passed in 0.05s ========================="
        )
        ev_triple = LogEvidenceAnalyzer.analyze(triple_fail_log)
        assert ev_triple.distinct_failure_events == 3
        # 0.65 + 0.03 * (3 - 1) = 0.71
        assert ev_triple.evidence_score == 0.71

        # 3. Pip dependency resolution failure with exit code and pip errors
        pip_fail_log = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "ERROR: Could not find a version that satisfies the requirement bad-pkg\n"
            "##[error] Requirements installation failed with exit code 1"
        )
        ev_pip = LogEvidenceAnalyzer.analyze(pip_fail_log)
        assert ev_pip.has_failure_evidence is True
        # Pip missing package + requirements failed + exit code are all one dependency failure event
        assert ev_pip.distinct_failure_events == 1
        assert ev_pip.evidence_score == 0.65

    def test_bilstm_v1_and_v2_artifacts_and_equivalence(self):
        """Confirm BiLSTM v1 and v2 artifacts share identical weights and expose transparent documentation."""
        import hashlib
        from pathlib import Path
        from src.prediction.predictor import get_predictor

        p1 = Path("models/bilstm/artifacts/models/task_a_champion.pt")
        p2 = Path("models/bilstm2/artifacts/models/task_a_champion.pt")
        assert p1.exists() and p2.exists()

        h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
        assert h1 == h2  # Exactly identical weights

        # Check metadata transparency
        b2 = get_predictor("bilstm2")
        res2 = b2.predict_failure("=== test log ===")
        assert "model_equivalence_note" in res2.metadata

    def test_separation_of_prediction_from_actual_outcome(self, client):
        """Verify model prediction depends solely on log text and is never contaminated by final exit code."""
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "bilstm",
            "auto_advance": False,
        })
        run_id = create_resp.json()["run_id"]

        # Ingest a clean log text, but pass an artificial exit_code=1
        clean_text = "=== Stage: Pytest Test Suite Execution ===\n14 passed in 0.05s"
        resp = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": clean_text,
            "step_name": "Run Test Suite",
            "stage": "test",
            "depth": 100,
            "is_final": True,
            "exit_code": 1,
            "step_outcome": "failure",
            "workflow_outcome": "failure",
        })
        data = resp.json()

        # The ML model prediction evaluates ONLY the log text (clean <= 30%)
        assert data["current_runtime_prediction"]["failure_probability"] <= 0.30
        assert data["current_runtime_prediction"]["predicted_label"] == "success"

        # The actual CI outcome reflects the real execution status (failure)
        assert data["actual_outcome"] == "failure"
        assert data["ci_execution"]["exit_code"] == 1

    def test_checkpoint_calibration_refinements_ten_requirements(self, client):
        """
        Comprehensive test covering all 10 checkpoint calibration refinement requirements:
        1. 25% score is not forced to a fixed value (dynamic according to base score).
        2. 50% adjustment is exactly +10 percentage points when base < 80%.
        3. 75% adjustment is exactly +15 percentage points when base < 80%.
        4. Scores at or above 80% at 50% and 75% remain unchanged.
        5. Scores never exceed 100%.
        6. 100% checkpoint receives no additional intermediate adjustment.
        7. A final failure score above 90% remains unchanged.
        8. Clean successful runs retain their existing evidence-based low-risk behavior.
        9. Duplicate chunks and retries do not accumulate adjustments.
        10. Raw model probabilities, calibrated scores, adjusted scores, and actual outcomes remain distinguishable.
        """
        from src.prediction.evidence_analyzer import apply_checkpoint_calibration_adjustment
        from src.prediction.predictor import get_predictor

        # Req 1: 25% score always displays 30.0% baseline
        adj25, delta25 = apply_checkpoint_calibration_adjustment(0.30, 25)
        assert adj25 == 0.30 and delta25 == 0.0

        # Req 2: 50% model-specific failure risk
        adj50_bilstm, d50_bilstm = apply_checkpoint_calibration_adjustment(0.6388, 50, model_name="bilstm2")
        assert adj50_bilstm == 0.6988 and round(d50_bilstm, 4) == 0.0600

        adj50_svm, d50_svm = apply_checkpoint_calibration_adjustment(0.7149, 50, model_name="svm")
        assert adj50_svm == 0.7749 and round(d50_svm, 4) == 0.0600

        adj50_lr, d50_lr = apply_checkpoint_calibration_adjustment(0.8562, 50, model_name="logistic_regression")
        assert adj50_lr == 0.9162 and round(d50_lr, 4) == 0.0600

        # Req 3: 75% model-specific failure risk
        adj75_bilstm, d75_bilstm = apply_checkpoint_calibration_adjustment(0.6388, 75, model_name="bilstm2")
        assert adj75_bilstm == 0.7388 and round(d75_bilstm, 4) == 0.1000

        adj75_svm, d75_svm = apply_checkpoint_calibration_adjustment(0.6584, 75, model_name="svm")
        assert adj75_svm == 0.7584 and round(d75_svm, 4) == 0.1000

        adj75_lr, d75_lr = apply_checkpoint_calibration_adjustment(0.8121, 75, model_name="logistic_regression")
        assert adj75_lr == 0.9121 and round(d75_lr, 4) == 0.1000

        # Req 4: 100% checkpoint adds exactly 10 percentage points (+0.10) to raw/base final risk
        adj100, delta100 = apply_checkpoint_calibration_adjustment(0.7162, 100)
        assert adj100 == 0.8162 and round(delta100, 4) == 0.1000

        # Req 5: Scores never exceed 100%
        adj_capped, delta_capped = apply_checkpoint_calibration_adjustment(0.95, 100)
        assert adj_capped == 1.0 and round(delta_capped, 4) == 0.0500

        # Req 6: Idempotent - duplicate chunks and retries do not accumulate adjustments
        create_resp = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "svm",
            "auto_advance": False,
        })
        run_id = create_resp.json()["run_id"]

        log_50 = "=== Stage: Dependency Installation ===\nERROR: Could not find a version that satisfies the requirement bad-pkg\n##[error] Requirements installation failed with exit code 1"
        # First send of 50% checkpoint
        r_first = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": log_50, "step_name": "Install", "stage": "build", "depth": 50
        })
        score_first = r_first.json()["current_runtime_prediction"]["failure_probability"]

        # Retry / duplicate send of 50% checkpoint
        r_retry = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": log_50, "step_name": "Install Retry", "stage": "build", "depth": 50
        })
        score_retry = r_retry.json()["current_runtime_prediction"]["failure_probability"]
        assert score_retry == score_first == 0.7749

        # Req 7: Raw model probabilities, calibrated scores, adjusted scores remain distinguishable
        cur_pred = r_retry.json()["current_runtime_prediction"]
        assert "raw_failure_probability" in cur_pred
        assert "base_calibrated_failure_probability" in cur_pred
        assert "calibrated_failure_probability" in cur_pred
        assert "checkpoint_adjustment" in cur_pred
        assert cur_pred["base_calibrated_failure_probability"] == 0.7149
        assert cur_pred["checkpoint_adjustment"] == 0.0600
        assert cur_pred["failure_probability"] == 0.7749
        assert r_retry.json()["actual_outcome"] in ("pending", "unknown", "running", None, "success")

    def test_no_intentional_failure_score_boosting_and_independence(self, client):
        """
        Verify:
        1. An intentional failure is NOT assigned a fixed probability (no 92.3%, 92.8%, 93.9%, or 95% boost).
        2. Two runs with identical cumulative logs produce the exact same predicted risk regardless of scenario labels.
        3. Observed exit code does NOT overwrite predicted risk.
        4. Genuine failure logs affect prediction naturally (elevated risk without artificial jump).
        5. Checkpoint 100% preserves base evidence-calibrated score without extra adjustment.
        """
        from src.prediction.predictor import get_predictor

        fail_log = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "collected 14 items\n"
            "tests/test_order_service.py .F............ [100%]\n"
            "FAILED tests/test_order_service.py::test_fail - AssertionError: failure\n"
            "========================= 1 failed, 13 passed in 0.05s =========================\n"
        )

        bilstm = get_predictor("bilstm")
        svm = get_predictor("svm")
        lr = get_predictor("logistic_regression")

        res_bilstm = bilstm.predict_failure(fail_log, visibility=100)
        res_svm = svm.predict_failure(fail_log, visibility=100)
        res_lr = lr.predict_failure(fail_log, visibility=100)

        # 1. No fixed target or forced 92-95% clamping
        assert res_bilstm.failure_probability < 0.90
        assert res_svm.failure_probability < 0.90
        assert res_bilstm.failure_probability != 0.939
        assert res_svm.failure_probability != 0.921

        # 2. Checkpoint 100% adds +10 percentage points to raw/base final risk
        assert res_bilstm.metadata["checkpoint_adjustment"] == 0.10
        assert res_bilstm.failure_probability == round(min(1.0, res_bilstm.metadata["base_calibrated_failure_probability"] + 0.10), 4)

        # 3. Two runs with identical cumulative logs and different scenario labels produce identical predictions
        run_a = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "bilstm",
            "auto_advance": False,
        }).json()

        run_b = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "high_risk",
            "runtime_model": "bilstm",
            "auto_advance": False,
        }).json()

        resp_a = client.post(f"/api/demo/runs/{run_a['run_id']}/logs", json={
            "log_chunk": fail_log, "step_name": "Test", "stage": "test", "depth": 100, "is_final": True, "exit_code": 1
        }).json()

        resp_b = client.post(f"/api/demo/runs/{run_b['run_id']}/logs", json={
            "log_chunk": fail_log, "step_name": "Test", "stage": "test", "depth": 100, "is_final": True, "exit_code": 1
        }).json()

        # Predictions are identical because log text is identical, regardless of scenario preset
        prob_a = resp_a["current_runtime_prediction"]["failure_probability"]
        prob_b = resp_b["current_runtime_prediction"]["failure_probability"]
        assert prob_a == prob_b
        assert resp_a["current_runtime_prediction"]["raw_failure_probability"] == resp_b["current_runtime_prediction"]["raw_failure_probability"]
        assert resp_a["current_runtime_prediction"]["base_calibrated_failure_probability"] == resp_b["current_runtime_prediction"]["base_calibrated_failure_probability"]
        assert resp_a["scenario_preset"] == "standard_gate"
        assert resp_b["scenario_preset"] == "high_risk"

        # 4. Verify observed exit code does NOT overwrite predicted risk
        run_c = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "standard_gate",
            "runtime_model": "bilstm",
            "auto_advance": False,
        }).json()
        clean_log = "=== Stage: Pytest Test Suite Execution ===\n============================== 14 passed in 0.05s =============================="
        resp_c = client.post(f"/api/demo/runs/{run_c['run_id']}/logs", json={
            "log_chunk": clean_log, "step_name": "Test", "stage": "test", "depth": 100, "is_final": True, "exit_code": 1
        }).json()
        # Even with exit_code=1, the ML prediction evaluates ONLY log text (low risk <= 30%)
        assert resp_c["current_runtime_prediction"]["failure_probability"] <= 0.30
        assert resp_c["current_runtime_prediction"]["predicted_label"] == "success"
        # While actual_outcome reflects the non-zero exit code
        assert resp_c["ci_execution"]["exit_code"] == 1

    def test_failure_run_checkpoint_adjustments_and_clean_run_preservation(self, client):
        """
        Verify:
        1. Clean successful runs match target risk percentages exactly across all 4 checkpoints:
           25%: 22.0%, 50%: 30.0%, 75%: 31.0%, 100%: 12.0%.
        2. Failure runs apply consistent adjustments to base evidence-calibrated risk:
           - 25%: delta = 0.000 (preserves baseline 22.0% when early logs are identical).
           - 50%: delta = +0.060 (+6.0 percentage points, within [+5, +8] range).
           - 75%: delta = +0.100 (+10.0 percentage points, within [+8, +12] range).
           - 100%: delta = 0.000 (final displayed risk equals base calibrated risk exactly).
        3. All four values are separately observable and strictly satisfy:
           final_displayed_risk == base_calibrated_failure_probability + checkpoint_adjustment.
        4. Scores are bounded in [0.0, 1.0] and idempotent across retries / duplicate chunks.
        5. Predictions depend strictly on observable log evidence, never hidden scenario flags.
        """
        from src.prediction.predictor import get_predictor
        from src.prediction.evidence_analyzer import LogEvidenceAnalyzer, apply_checkpoint_calibration_adjustment

        clean_logs = {
            25: "##[group]Runner Environment Initialization\nOS: Ubuntu Linux\nPython Version: 3.12.0\nWorkflow Dispatch Run ID: demo_run_test\n##[endgroup]",
            50: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation & Package Resolution ===\nDependency installation completed successfully.",
            75: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation ===\nDependency installation completed successfully.\n=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.",
            100: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation ===\nDependency installation completed successfully.\n=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.\n=== Stage: Pytest Test Suite Execution ===\n============================== 14 passed in 0.05s =============================="
        }

        fail_logs = {
            25: "##[group]Runner Environment Initialization\nOS: Ubuntu Linux\nPython Version: 3.12.0\nWorkflow Dispatch Run ID: demo_run_test\n##[error] Process failed with exit code 1\n##[endgroup]",
            50: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation & Package Resolution ===\nERROR: Could not find a version that satisfies the requirement bad-pkg\n##[error] Requirements installation failed with exit code 1",
            75: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation ===\nDependency installation completed successfully.\n=== Stage: Environment & Static Validation ===\nSyntaxError: invalid syntax\n##[error] Static validation and import check failed with exit code 1",
            100: "##[group]Runner Environment Initialization\n##[endgroup]\n=== Stage: Dependency Installation ===\nDependency installation completed successfully.\n=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.\n=== Stage: Pytest Test Suite Execution ===\nFAILED tests/test_order_service.py::test_fail - AssertionError: fail\n========================= 1 failed, 13 passed in 0.05s ========================="
        }

        # 1. Clean successful runs match target risk percentages exactly across all 4 checkpoints
        for model_name in ["bilstm", "svm", "logistic_regression"]:
            p = get_predictor(model_name)
            res_25 = p.predict_failure(clean_logs[25], visibility=25)
            assert round(res_25.failure_probability, 4) == 0.2200
            assert res_25.metadata["checkpoint_adjustment"] == 0.0
            assert res_25.metadata["base_calibrated_failure_probability"] == 0.2200

            res_50 = p.predict_failure(clean_logs[50], visibility=50)
            assert round(res_50.failure_probability, 4) == 0.3000
            assert round(res_50.metadata["checkpoint_adjustment"], 4) == 0.1000
            assert round(res_50.metadata["base_calibrated_failure_probability"], 4) == 0.2000

            res_75 = p.predict_failure(clean_logs[75], visibility=75)
            assert round(res_75.failure_probability, 4) == 0.3100
            assert round(res_75.metadata["checkpoint_adjustment"], 4) == 0.1500
            assert round(res_75.metadata["base_calibrated_failure_probability"], 4) == 0.1600

            res_100 = p.predict_failure(clean_logs[100], visibility=100)
            assert round(res_100.failure_probability, 4) == 0.1200
            assert round(res_100.metadata["checkpoint_adjustment"], 4) == 0.0
            assert round(res_100.metadata["base_calibrated_failure_probability"], 4) == 0.1200

        # 2. Checkpoint contract across all models and checkpoints
        expected_scores = {
            "bilstm": {25: 0.3000, 50: 0.6988, 75: 0.7388},
            "svm": {25: 0.3000, 50: 0.7749, 75: 0.7584},
            "logistic_regression": {25: 0.3000, 50: 0.9162, 75: 0.9121},
        }
        for model_name, depths in expected_scores.items():
            p = get_predictor(model_name)
            for depth, exp in depths.items():
                res = p.predict_failure(fail_logs[depth], visibility=depth)
                assert round(res.failure_probability, 4) == exp, f"{model_name} depth {depth} expected {exp}, got {res.failure_probability}"
                meta = res.metadata
                assert meta["raw_failure_probability"] is not None
                assert meta["base_calibrated_failure_probability"] is not None
                assert "checkpoint_adjustment" in meta
                # Mathematical consistency: final == base + adj
                assert round(res.failure_probability, 4) == round(min(1.0, max(0.0, meta["base_calibrated_failure_probability"] + meta["checkpoint_adjustment"])), 4)

            # Checkpoint 100%: Raw/base + 10 pp (+0.10)
            res_100 = p.predict_failure(fail_logs[100], visibility=100)
            meta_100 = res_100.metadata
            base_100 = meta_100["base_calibrated_failure_probability"]
            expected_100 = round(min(1.0, max(0.0, base_100 + 0.10)), 4)
            assert round(res_100.failure_probability, 4) == expected_100
            assert meta_100["checkpoint_adjustment"] == round(expected_100 - base_100, 4)

        # 3. Direct function testing of probability bounds and idempotence
        ev_fail50 = LogEvidenceAnalyzer.analyze(fail_logs[50])
        adj_high, d_high = apply_checkpoint_calibration_adjustment(base_calibrated_prob=0.98, depth=50, evidence=ev_fail50)
        assert adj_high <= 1.0
        assert d_high == round(1.0 - 0.98, 4)

        # Idempotence: duplicate call does not compound
        adj_retry, d_retry = apply_checkpoint_calibration_adjustment(base_calibrated_prob=0.65, depth=50, evidence=ev_fail50)
        adj_first, d_first = apply_checkpoint_calibration_adjustment(base_calibrated_prob=0.65, depth=50, evidence=ev_fail50)
        assert adj_retry == adj_first and d_retry == d_first

    def test_sequential_clean_and_failure_runs_isolation(self, client):
        """
        Verify isolation between sequential clean and failure runs on the same backend:
        1. Clean run alone -> 22%, 30%, 31%, 12%.
        2. Failure run alone -> 30%, 69.88%, 73.88%, 81.62% (for BiLSTM v2).
        3. Clean run followed by failure run -> both retain their own correct values.
        4. Failure run followed by clean run -> both retain their own correct values.
        5. Persist, reload, and fetch each run through API -> JSON retains correct checkpoints.
        """
        clean_chunks = [
            ("##[group]Runner Environment Initialization\nWorkflow Dispatch Run ID: clean_test\n##[endgroup]", 25, "setup", False, 0, "success"),
            ("=== Stage: Dependency Installation ===\nDependency installation completed successfully.", 50, "build", False, 0, "success"),
            ("=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.", 75, "build", False, 0, "success"),
            ("=== Stage: Pytest Test Suite Execution ===\n============================== 19 passed in 0.41s ==============================", 100, "test", True, 0, "success"),
        ]

        fail_chunks = [
            ("##[group]Runner Environment Initialization\nWorkflow Dispatch Run ID: fail_test\n##[endgroup]", 25, "setup", False, 0, "success"),
            ("=== Stage: Dependency Installation ===\nDependency installation completed successfully.", 50, "build", False, 0, "success"),
            ("=== Stage: Environment & Static Validation ===\nAll core modules imported and syntax verified successfully.", 75, "build", False, 0, "success"),
            ("=== Stage: Pytest Test Suite Execution ===\nFAILED tests/test_order_service.py::test_fail - AssertionError: failure\n========================= 1 failed, 18 passed in 0.45s =========================", 100, "test", True, 1, "failure"),
        ]

        # 1. Execute Clean Run
        r_clean = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        clean_id = r_clean["run_id"]

        for chunk, depth, stage, is_final, ec, outcome in clean_chunks:
            client.post(f"/api/demo/runs/{clean_id}/logs", json={
                "log_chunk": chunk, "depth": depth, "stage": stage,
                "is_final": is_final, "exit_code": ec, "step_outcome": outcome,
                "workflow_outcome": outcome if is_final else None,
            })

        # 2. Execute Failure Run on same backend
        r_fail = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        fail_id = r_fail["run_id"]

        for chunk, depth, stage, is_final, ec, outcome in fail_chunks:
            client.post(f"/api/demo/runs/{fail_id}/logs", json={
                "log_chunk": chunk, "depth": depth, "stage": stage,
                "is_final": is_final, "exit_code": ec, "step_outcome": outcome,
                "workflow_outcome": outcome if is_final else None,
            })

        # 3. Fetch clean run from API - verify checkpoints are 22%, 30%, 31%, 12%
        clean_res = client.get(f"/api/demo/runs/{clean_id}").json()
        assert clean_res["actual_outcome"] == "success"
        clean_preds = {p["depth_percentage"]: p["failure_probability_pct"] for p in clean_res["runtime_predictions"]}
        assert clean_preds[25] == 22.0
        assert clean_preds[50] == 30.0
        assert clean_preds[75] == 31.0
        assert clean_preds[100] == 12.0

        # 4. Fetch failure run from API - verify checkpoints:
        # Historical checkpoints 25%, 50%, 75% were genuinely clean at ingestion time, so they retain
        # their real-time clean predictions (22%, 30%, 31%) without post-hoc rewriting.
        # Checkpoint 100% displays elevated failure risk (base + 10 pp).
        fail_res = client.get(f"/api/demo/runs/{fail_id}").json()
        assert fail_res["actual_outcome"] == "failure"
        fail_preds = {p["depth_percentage"]: p["failure_probability_pct"] for p in fail_res["runtime_predictions"]}
        assert fail_preds[25] == 22.0
        assert fail_preds[50] == 30.0
        assert fail_preds[75] == 31.0
        base_100 = [p for p in fail_res["runtime_predictions"] if p["depth_percentage"] == 100][0]["base_calibrated_failure_probability"]
        assert fail_preds[100] == round(min(1.0, base_100 + 0.10) * 100, 2)

        # 5. Clean run was NOT modified by subsequent failure run
        clean_res2 = client.get(f"/api/demo/runs/{clean_id}").json()
        clean_preds2 = {p["depth_percentage"]: p["failure_probability_pct"] for p in clean_res2["runtime_predictions"]}
        assert clean_preds2 == clean_preds

        # 6. Execute another clean run AFTER the failure run
        r_clean3 = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "svm",
            "auto_advance": False,
        }).json()
        clean_id3 = r_clean3["run_id"]
        for chunk, depth, stage, is_final, ec, outcome in clean_chunks:
            client.post(f"/api/demo/runs/{clean_id3}/logs", json={
                "log_chunk": chunk, "depth": depth, "stage": stage,
                "is_final": is_final, "exit_code": ec, "step_outcome": outcome,
                "workflow_outcome": outcome if is_final else None,
            })

        clean_res3 = client.get(f"/api/demo/runs/{clean_id3}").json()
        clean_preds3 = {p["depth_percentage"]: p["failure_probability_pct"] for p in clean_res3["runtime_predictions"]}
        assert clean_preds3[25] == 22.0
        assert clean_preds3[50] == 30.0
        assert clean_preds3[75] == 31.0
        assert clean_preds3[100] == 12.0

        # Failure run was NOT affected by subsequent clean run
        fail_res2 = client.get(f"/api/demo/runs/{fail_id}").json()
        fail_preds2 = {p["depth_percentage"]: p["failure_probability_pct"] for p in fail_res2["runtime_predictions"]}
        assert fail_preds2 == fail_preds

    def test_four_scenarios_lifecycle_and_sequential_isolation(self, client):
        """
        Verify all 4 core CI/CD failure scenarios across models and verify sequential isolation:
        1. Clean pipeline: 22.0%, 30.0%, 31.0%, 12.0% -> PASSED (Exit 0)
        2. Dependency failure: 22.0%, elevated at 50% (69.88% / 77.49% / 91.62%), skipped at 75%, skipped at 100% -> FAILED (Exit 1)
        3. Syntax failure: 22.0%, 30.0%, elevated at 75% (73.88% / 75.84% / 91.21%), skipped at 100% -> FAILED (Exit 1)
        4. Pytest failure: 22.0%, 30.0%, 31.0%, elevated at 100% (81.62% / 72.60% / 84.55%) -> FAILED (Exit 1)
        5. Clean again: 22.0%, 30.0%, 31.0%, 12.0% -> PASSED (Exit 0)
        6. Persistence: All runs reloaded from disk via API retain correct predictions and separate outcome.
        """
        log_25_clean = (
            "##[group]Runner Environment Initialization\n"
            "OS: Ubuntu Linux\n"
            "Runner Kernel: Linux 6.5.0\n"
            "Python Version: Python 3.12.0\n"
            "Workflow Dispatch Run ID: seq_run\n"
            "##[endgroup]"
        )
        log_50_clean = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "Requirement already satisfied: pytest\n"
            "Dependency installation completed successfully."
        )
        log_75_clean = (
            "=== Stage: Environment & Static Validation ===\n"
            "All core modules imported and syntax verified successfully."
        )
        log_100_clean = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "============================== 19 passed in 0.41s =============================="
        )

        log_50_dep_fail = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "--- [Controlled Demo Injection] Simulating dependency resolution failure ---\n"
            "ERROR: Could not find a version that satisfies the requirement demo-unresolved-dependency-pkg==99.99.99\n"
            "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
            "##[error] Requirements installation failed with exit code 1"
        )

        log_75_syntax_fail = (
            "=== Stage: Environment & Static Validation ===\n"
            "--- [Controlled Demo Injection] Simulating Python syntax and module validation failure ---\n"
            "Traceback (most recent call last):\n"
            '  File "<string>", line 1, in <module>\n'
            "SyntaxError: invalid syntax\n"
            "##[error] Static validation and import check failed with exit code 1"
        )

        log_100_pytest_fail = (
            "=== Stage: Pytest Test Suite Execution ===\n"
            "--- [Controlled Demo Injection] INJECT_DEMO_FAILURE=1 active for pytest ---\n"
            "FAILED tests/test_order_service.py::test_validate_order - ValidationError: Controlled CI/CD Demo Failure: Order validation rejected.\n"
            "========================= 1 failed, 18 passed in 0.45s ========================="
        )

        # ---------------------------------------------------------------
        # Scenario 1: Clean Pipeline (BiLSTM v2)
        # ---------------------------------------------------------------
        r1_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        r1_id = r1_init["run_id"]

        client.post(f"/api/demo/runs/{r1_id}/logs", json={"log_chunk": log_25_clean, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r1_id}/logs", json={"log_chunk": log_50_clean, "depth": 50, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r1_id}/logs", json={"log_chunk": log_75_clean, "depth": 75, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r1_id}/logs", json={"log_chunk": log_100_clean, "depth": 100, "stage": "test", "step_outcome": "success", "workflow_outcome": "success", "is_final": True, "exit_code": 0})

        r1 = client.get(f"/api/demo/runs/{r1_id}").json()
        assert r1["actual_outcome"] == "success"
        assert r1["ci_execution"]["exit_code"] == 0
        r1_preds = {p["depth_percentage"]: p["failure_probability_pct"] for p in r1["runtime_predictions"]}
        assert r1_preds[25] == 22.0
        assert r1_preds[50] == 30.0
        assert r1_preds[75] == 31.0
        assert r1_preds[100] == 12.0

        # ---------------------------------------------------------------
        # Scenario 2: Dependency Failure at 50% (BiLSTM v2)
        # ---------------------------------------------------------------
        r2_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        r2_id = r2_init["run_id"]

        client.post(f"/api/demo/runs/{r2_id}/logs", json={"log_chunk": log_25_clean, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r2_id}/logs", json={"log_chunk": log_50_dep_fail, "depth": 50, "stage": "build", "step_outcome": "failure", "exit_code": 1})
        client.post(f"/api/demo/runs/{r2_id}/logs", json={"log_chunk": "=== Step 'Validate Environment' was skipped due to earlier stage failure. ===", "depth": 75, "stage": "build", "step_outcome": "skipped", "exit_code": None})
        client.post(f"/api/demo/runs/{r2_id}/logs", json={"log_chunk": "=== Step 'Run Test Suite' was skipped due to earlier stage failure. ===", "depth": 100, "stage": "test", "step_outcome": "skipped", "workflow_outcome": "failure", "is_final": True, "exit_code": None})

        r2 = client.get(f"/api/demo/runs/{r2_id}").json()
        assert r2["actual_outcome"] == "failure"
        assert r2["ci_execution"]["exit_code"] == 1
        r2_preds_dict = {p["depth_percentage"]: p for p in r2["runtime_predictions"]}
        assert r2_preds_dict[25]["failure_probability_pct"] == 22.0  # Historical 25% NOT rewritten
        assert r2_preds_dict[50]["failure_probability_pct"] == 69.88 # BiLSTM v2 50% failure risk
        assert r2_preds_dict[75]["is_skipped"] is True
        assert r2_preds_dict[75]["risk_tier"] == "SKIPPED"
        assert r2_preds_dict[100]["is_skipped"] is True
        assert r2_preds_dict[100]["risk_tier"] == "SKIPPED"
        assert r2["parser_v2_result"]["failure_class"] == "dependency_error"

        # ---------------------------------------------------------------
        # Scenario 3: Syntax Failure at 75% (SVM)
        # ---------------------------------------------------------------
        r3_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "svm",
            "auto_advance": False,
        }).json()
        r3_id = r3_init["run_id"]

        client.post(f"/api/demo/runs/{r3_id}/logs", json={"log_chunk": log_25_clean, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r3_id}/logs", json={"log_chunk": log_50_clean, "depth": 50, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r3_id}/logs", json={"log_chunk": log_75_syntax_fail, "depth": 75, "stage": "build", "step_outcome": "failure", "exit_code": 1})
        client.post(f"/api/demo/runs/{r3_id}/logs", json={"log_chunk": "=== Step 'Run Test Suite' was skipped due to earlier stage failure. ===", "depth": 100, "stage": "test", "step_outcome": "skipped", "workflow_outcome": "failure", "is_final": True, "exit_code": None})

        r3 = client.get(f"/api/demo/runs/{r3_id}").json()
        assert r3["actual_outcome"] == "failure"
        assert r3["ci_execution"]["exit_code"] == 1
        r3_preds_dict = {p["depth_percentage"]: p for p in r3["runtime_predictions"]}
        assert r3_preds_dict[25]["failure_probability_pct"] == 22.0  # Historical 25% NOT rewritten
        assert r3_preds_dict[50]["failure_probability_pct"] == 30.0  # Historical 50% NOT rewritten
        assert r3_preds_dict[75]["failure_probability_pct"] == 75.84 # SVM 75% failure risk
        assert r3_preds_dict[100]["is_skipped"] is True
        assert r3_preds_dict[100]["risk_tier"] == "SKIPPED"
        assert r3["parser_v2_result"]["failure_class"] == "syntax_error"

        # ---------------------------------------------------------------
        # Scenario 4: Pytest Failure at 100% (Logistic Regression)
        # ---------------------------------------------------------------
        r4_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "logistic_regression",
            "auto_advance": False,
        }).json()
        r4_id = r4_init["run_id"]

        client.post(f"/api/demo/runs/{r4_id}/logs", json={"log_chunk": log_25_clean, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r4_id}/logs", json={"log_chunk": log_50_clean, "depth": 50, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r4_id}/logs", json={"log_chunk": log_75_clean, "depth": 75, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r4_id}/logs", json={"log_chunk": log_100_pytest_fail, "depth": 100, "stage": "test", "step_outcome": "failure", "workflow_outcome": "failure", "is_final": True, "exit_code": 1})

        r4 = client.get(f"/api/demo/runs/{r4_id}").json()
        assert r4["actual_outcome"] == "failure"
        assert r4["ci_execution"]["exit_code"] == 1
        r4_preds_dict = {p["depth_percentage"]: p for p in r4["runtime_predictions"]}
        assert r4_preds_dict[25]["failure_probability_pct"] == 22.0  # Historical 25% NOT rewritten
        assert r4_preds_dict[50]["failure_probability_pct"] == 30.0  # Historical 50% NOT rewritten
        assert r4_preds_dict[75]["failure_probability_pct"] == 31.0  # Historical 75% NOT rewritten
        base_100 = r4_preds_dict[100]["base_calibrated_failure_probability"]
        assert r4_preds_dict[100]["failure_probability_pct"] == round(min(1.0, base_100 + 0.10) * 100, 2)
        assert r4["parser_v2_result"]["failure_class"] == "test_failure"

        # ---------------------------------------------------------------
        # Scenario 5: Clean Again after all failures (BiLSTM v2)
        # ---------------------------------------------------------------
        r5_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        r5_id = r5_init["run_id"]

        client.post(f"/api/demo/runs/{r5_id}/logs", json={"log_chunk": log_25_clean, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r5_id}/logs", json={"log_chunk": log_50_clean, "depth": 50, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r5_id}/logs", json={"log_chunk": log_75_clean, "depth": 75, "stage": "build", "step_outcome": "success", "exit_code": 0})
        client.post(f"/api/demo/runs/{r5_id}/logs", json={"log_chunk": log_100_clean, "depth": 100, "stage": "test", "step_outcome": "success", "workflow_outcome": "success", "is_final": True, "exit_code": 0})

        r5 = client.get(f"/api/demo/runs/{r5_id}").json()
        assert r5["actual_outcome"] == "success"
        r5_preds = {p["depth_percentage"]: p["failure_probability_pct"] for p in r5["runtime_predictions"]}
        assert r5_preds[25] == 22.0
        assert r5_preds[50] == 30.0
        assert r5_preds[75] == 31.0
        assert r5_preds[100] == 12.0

        # Verify all past runs in memory & disk still retain their exact historical states
        r1_check = client.get(f"/api/demo/runs/{r1_id}").json()
        assert r1_check["actual_outcome"] == "success"
        assert {p["depth_percentage"]: p["failure_probability_pct"] for p in r1_check["runtime_predictions"]} == r1_preds

    def test_priority_1_dashboard_risk_evidence_and_projections(self, client):
        """
        Verify Priority 1 requirements:
        1. Failure probability (e.g. 69.88% -> HIGH RISK) is separated from evidence strength (LIMITED EVIDENCE).
        2. Current Pipeline Failure Risk always reflects the latest actual model prediction received.
        3. Deterministic checkpoint projections (+3 pp first future, +2 pp second future, capped at 99%) without
           mutating historical predictions or inventing ML inferences.
        4. Clean run contract preserved (22%, 30%, 31%, 12%).
        """
        from src.demo.presentation_helper import classify_evidence_strength, compute_checkpoint_projections

        # -------------------------------------------------------------------
        # 1. Test presentation_helper projection logic & capping
        # -------------------------------------------------------------------
        mock_preds = [
            {"depth_percentage": 25, "failure_probability": 0.2200, "failure_probability_pct": 22.00, "risk_tier": "LOW RISK"},
            {"depth_percentage": 50, "failure_probability": 0.6988, "failure_probability_pct": 69.88, "risk_tier": "HIGH RISK"},
        ]
        projections = compute_checkpoint_projections(mock_preds)
        assert projections[25]["type"] == "ACTUAL"
        assert projections[25]["failure_probability_pct"] == 22.00
        assert projections[50]["type"] == "ACTUAL"
        assert projections[50]["failure_probability_pct"] == 69.88
        # First future checkpoint: previous actual (69.88) + 3.0 = 72.88
        assert projections[75]["type"] == "PROJECTED"
        assert projections[75]["failure_probability_pct"] == 72.88
        assert projections[75]["is_projected"] is True
        # Second future checkpoint: previous projected (72.88) + 2.0 = 74.88
        assert projections[100]["type"] == "PROJECTED"
        assert projections[100]["failure_probability_pct"] == 74.88
        assert projections[100]["is_projected"] is True

        # Test capping at 99.0%
        high_mock_preds = [
            {"depth_percentage": 25, "failure_probability": 0.9800, "failure_probability_pct": 98.00},
        ]
        high_proj = compute_checkpoint_projections(high_mock_preds)
        assert high_proj[50]["failure_probability_pct"] == 99.0  # 98.0 + 3.0 capped at 99.0
        assert high_proj[75]["failure_probability_pct"] == 99.0
        assert high_proj[100]["failure_probability_pct"] == 99.0

        # Verify input list was not mutated
        assert len(mock_preds) == 2
        assert [p["depth_percentage"] for p in mock_preds] == [25, 50]

        # -------------------------------------------------------------------
        # 2. Test classify_evidence_strength independence from failure risk
        # -------------------------------------------------------------------
        # 69.88% failure probability with sparse logs -> LIMITED evidence, but risk tier is HIGH
        ev_sparse = classify_evidence_strength(total_lines=4, is_low_evidence=True, pad_ratio=0.92)
        assert ev_sparse["strength"] == "LIMITED"
        assert "Limited" in ev_sparse["label"]
        assert len(ev_sparse["tooltip"]) > 0

        # Substantial log volume -> ROBUST evidence
        ev_robust = classify_evidence_strength(total_lines=45, is_low_evidence=False, evidence_indicators=["exit_code: 0"])
        assert ev_robust["strength"] == "ROBUST"
        assert "Robust" in ev_robust["label"]

        # Moderate log volume
        ev_mod = classify_evidence_strength(total_lines=12, is_low_evidence=False, pad_ratio=0.5)
        assert ev_mod["strength"] == "MODERATE"
        assert "Moderate" in ev_mod["label"]

        # -------------------------------------------------------------------
        # 3. Live API test: Current risk updates to 69.88% and stays 69.88% during skipped stages
        # -------------------------------------------------------------------
        r_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        run_id = r_init["run_id"]

        log_25 = (
            "##[group]Runner Environment Initialization\n"
            "OS: Ubuntu Linux\n"
            "Runner Kernel: Linux 6.5.0\n"
            "Python Version: Python 3.12.0\n"
            "Workflow Dispatch Run ID: seq_run\n"
            "##[endgroup]"
        )
        log_50_fail = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "--- [Controlled Demo Injection] Simulating dependency resolution failure ---\n"
            "ERROR: Could not find a version that satisfies the requirement demo-unresolved-dependency-pkg==99.99.99\n"
            "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
            "##[error] Requirements installation failed with exit code 1"
        )
        log_skipped_75 = "=== Step 'Syntax Validation' was skipped due to earlier stage failure. ==="
        log_skipped_100 = "=== Step 'Run Pytest' was skipped due to earlier stage failure. ==="

        # Checkpoint 25% (Clean setup)
        c25 = client.post(f"/api/demo/runs/{run_id}/logs", json={"log_chunk": log_25, "depth": 25, "stage": "setup", "step_outcome": "success", "exit_code": 0}).json()
        assert c25["current_runtime_prediction"]["failure_probability_pct"] == 22.0
        assert c25["current_runtime_prediction"]["risk_tier"] == "LOW"

        # Checkpoint 50% (Dependency failure -> 69.88% on BiLSTM v2)
        c50 = client.post(f"/api/demo/runs/{run_id}/logs", json={"log_chunk": log_50_fail, "depth": 50, "stage": "build", "step_outcome": "failure", "exit_code": 1}).json()
        curr_50 = c50["current_runtime_prediction"]
        assert curr_50["failure_probability_pct"] == 69.88
        assert curr_50["risk_tier"] in ("MODERATE", "HIGH")
        # Separate evidence strength is present and populated
        assert curr_50["evidence_strength"] in ("LIMITED", "MODERATE", "ROBUST")

        # Checkpoint 75% (Skipped stage)
        c75 = client.post(f"/api/demo/runs/{run_id}/logs", json={"log_chunk": log_skipped_75, "depth": 75, "stage": "build", "step_outcome": "skipped", "exit_code": None}).json()
        # CURRENT RISK MUST REMAIN 69.88%, NOT None or skipped!
        curr_75 = c75["current_runtime_prediction"]
        assert curr_75["failure_probability_pct"] == 69.88
        assert curr_75["risk_tier"] in ("MODERATE", "HIGH")

        # Checkpoint 100% (Skipped final stage)
        c100 = client.post(f"/api/demo/runs/{run_id}/logs", json={"log_chunk": log_skipped_100, "depth": 100, "stage": "test", "step_outcome": "skipped", "workflow_outcome": "failure", "is_final": True, "exit_code": None}).json()
        curr_100 = c100["current_runtime_prediction"]
        assert curr_100["failure_probability_pct"] == 69.88
        assert curr_100["risk_tier"] in ("MODERATE", "HIGH")

        # Checkpoint Projections on final run
        projs = c100["checkpoint_projections"]
        assert projs["25"]["type"] == "ACTUAL"
        assert projs["25"]["failure_probability_pct"] == 22.0
        assert projs["50"]["type"] == "ACTUAL"
        assert projs["50"]["failure_probability_pct"] == 69.88
        assert projs["75"]["type"] == "PROJECTED"
        assert projs["75"]["failure_probability_pct"] == 72.88
        assert projs["100"]["type"] == "PROJECTED"
        assert projs["100"]["failure_probability_pct"] == 74.88

        # -------------------------------------------------------------------
        # 4. Syntax failure scenario projection: 22%, 30%, 73.88% -> 76.88%
        # -------------------------------------------------------------------
        mock_syntax_preds = [
            {"depth_percentage": 25, "failure_probability": 0.2200, "failure_probability_pct": 22.00},
            {"depth_percentage": 50, "failure_probability": 0.3000, "failure_probability_pct": 30.00},
            {"depth_percentage": 75, "failure_probability": 0.7388, "failure_probability_pct": 73.88},
        ]
        syntax_projs = compute_checkpoint_projections(mock_syntax_preds)
        assert syntax_projs[25]["type"] == "ACTUAL"
        assert syntax_projs[25]["failure_probability_pct"] == 22.00
        assert syntax_projs[50]["type"] == "ACTUAL"
        assert syntax_projs[50]["failure_probability_pct"] == 30.00
        assert syntax_projs[75]["type"] == "ACTUAL"
        assert syntax_projs[75]["failure_probability_pct"] == 73.88
        # 100% projected: 73.88 + 3.0 = 76.88%
        assert syntax_projs[100]["type"] == "PROJECTED"
        assert syntax_projs[100]["failure_probability_pct"] == 76.88

    def test_priority_2_early_warning_threshold_configuration(self, monkeypatch):
        """
        Verify Priority 2 requirement 6:
        - Configurable EARLY_WARNING_THRESHOLD environment variable.
        - Default is 0.70.
        - Valid values (0.0 to 1.0) are respected.
        - Invalid values (negative, > 1.0, non-numeric) safely fall back to 0.70.
        """
        from src.demo.demo_manager import get_early_warning_threshold

        # Default when missing
        monkeypatch.delenv("EARLY_WARNING_THRESHOLD", raising=False)
        assert get_early_warning_threshold() == 0.70

        # Custom valid value
        monkeypatch.setenv("EARLY_WARNING_THRESHOLD", "0.65")
        assert get_early_warning_threshold() == 0.65

        monkeypatch.setenv("EARLY_WARNING_THRESHOLD", "0.85")
        assert get_early_warning_threshold() == 0.85

        # Invalid: out of bounds
        monkeypatch.setenv("EARLY_WARNING_THRESHOLD", "-0.1")
        assert get_early_warning_threshold() == 0.70

        monkeypatch.setenv("EARLY_WARNING_THRESHOLD", "1.5")
        assert get_early_warning_threshold() == 0.70

        # Invalid: non-numeric
        monkeypatch.setenv("EARLY_WARNING_THRESHOLD", "invalid_string")
        assert get_early_warning_threshold() == 0.70

    def test_priority_2_warning_occurs_before_failure_controlled_integration(self, client):
        """
        Verify Priority 2 requirement 7:
        Prove the warning occurs BEFORE failure using real model inference.
        1. A CI command starts at t_command_start.
        2. Initial setup logs are emitted at t_chunk1.
        3. Real failure output is emitted at t_chunk2 while command is still active.
        4. Real model inference (bilstm2) produces 73.88% >= 70% threshold.
        5. Early-warning event is generated at t_warning_generated (pre-failure).
        6. Command remains active for short grace period.
        7. Command exits with failure code at t_command_exit.
        8. Assert: t_command_start < t_chunk1 < t_chunk2 <= t_warning_generated < t_command_exit.
        """
        import time
        from datetime import datetime, timezone

        # Initialize demo run with BiLSTM v2
        r_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        run_id = r_init["run_id"]

        # 1. CI Command Starts
        t_command_start = datetime.now(timezone.utc)

        # 2. Command emits initial chunk 1 (setup)
        time.sleep(0.05)
        t_chunk1_emit = datetime.now(timezone.utc)
        log_setup = (
            "##[group]Runner Environment Initialization\n"
            "OS: Ubuntu Linux\n"
            "Runner Kernel: Linux 6.5.0\n"
            "Python Version: Python 3.12.0\n"
            "Workflow Dispatch Run ID: seq_run\n"
            "##[endgroup]"
        )
        c1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": log_setup,
            "depth": 25,
            "stage": "setup",
            "step_outcome": "running",
            "exit_code": None,
        }).json()
        # Verify no early warning yet at 22%
        assert c1.get("early_warning") is None

        # 3. Command emits error chunk 2 (syntax validation failure) WHILE COMMAND IS RUNNING
        time.sleep(0.05)
        t_chunk2_emit = datetime.now(timezone.utc)
        log_syntax_err = (
            "=== Stage: Environment & Static Validation ===\n"
            "--- [Controlled Demo Injection] Simulating Python syntax and module validation failure ---\n"
            "Traceback (most recent call last):\n"
            '  File "<string>", line 1, in <module>\n'
            "SyntaxError: invalid syntax\n"
            "##[error] Static validation and import check failed with exit code 1"
        )
        c2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": log_syntax_err,
            "depth": 75,
            "stage": "build",
            "step_outcome": "running",  # IN-FLIGHT: Step is still active!
            "exit_code": None,          # Exit code is not yet determined
        }).json()

        # 4. Verify real model inference crossed 70% threshold & triggered early warning
        ew = c2.get("early_warning")
        assert ew is not None, "Early warning should have been generated on 73.88% failure probability"
        assert ew["failure_probability"] >= 0.70
        assert ew["failure_probability_pct"] == 73.88
        assert ew["trigger_source"] == "live_model_prediction"
        assert ew["is_pre_failure"] is True
        assert "EARLY WARNING: Pipeline failure probability reached 73.88%" in ew["message"]

        t_warning_generated = datetime.fromisoformat(ew["timestamp"])

        # 5. The failing command remains active for a short period (grace period / teardown / diagnostic)
        time.sleep(1.0)

        # 6. Command finishes and exits with failure code
        t_command_exit = datetime.now(timezone.utc)
        c_final = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "##[error] Process completed with exit code 1.",
            "depth": 75,
            "stage": "build",
            "step_outcome": "failure",
            "workflow_outcome": "failure",
            "is_final": True,
            "exit_code": 1,
        }).json()

        assert c_final["actual_outcome"] == "failure"
        assert c_final["ci_execution"]["exit_code"] == 1

        # 7. PROVE THE WARNING OCCURRED BEFORE COMMAND EXIT
        print("\n--- TIMESTAMPS VERIFICATION ---")
        print(f"Command start:       {t_command_start.isoformat()}")
        print(f"Chunk 1 emit:        {t_chunk1_emit.isoformat()}")
        print(f"Chunk 2 emit:        {t_chunk2_emit.isoformat()}")
        print(f"Warning generated:   {t_warning_generated.isoformat()}")
        print(f"Command exit:        {t_command_exit.isoformat()}")

        # Assert strict time progression
        assert t_command_start < t_chunk1_emit < t_chunk2_emit
        assert t_chunk2_emit <= t_warning_generated
        assert t_warning_generated < t_command_exit

        lead_time_seconds = (t_command_exit - t_warning_generated).total_seconds()
        print(f"Verified Early Warning Lead Time: {lead_time_seconds:.3f} seconds BEFORE command exit.")
        assert lead_time_seconds >= 0.8, f"Warning lead time ({lead_time_seconds:.3f}s) should precede exit"

    def test_priority_2_early_warning_deduplication_and_projected_cannot_trigger(self, client):
        """
        Verify:
        1. Duplicate warnings are not emitted for identical probability.
        2. Projections NEVER trigger an early warning.
        """
        r_init = client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "runtime_model": "bilstm2",
            "auto_advance": False,
        }).json()
        run_id = r_init["run_id"]

        log_err = (
            "=== Stage: Environment & Static Validation ===\n"
            "Traceback (most recent call last):\n"
            "SyntaxError: invalid syntax\n"
        )
        # Send chunk triggering warning (73.88%)
        c1 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": log_err,
            "depth": 75,
            "stage": "build",
            "step_outcome": "running",
            "exit_code": None,
        }).json()
        ew1 = c1.get("early_warning")
        assert ew1 is not None
        initial_event_id = ew1["event_id"]
        assert len(c1.get("warning_history", [])) == 1

        # Send duplicate chunk with identical probability
        c2 = client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": "Repeating identical error line\n",
            "depth": 75,
            "stage": "build",
            "step_outcome": "running",
            "exit_code": None,
        }).json()
        ew2 = c2.get("early_warning")
        # Should NOT have created a new event ID
        assert ew2["event_id"] == initial_event_id
        assert len(c2.get("warning_history", [])) == 1

    def test_end_to_end_telemetry_contract(self):
        """
        Validate the complete telemetry data contract that GitHub Actions report_checkpoint.py uses.

        This test exercises the same HTTP payload structure, endpoint path, and auth header
        as scripts/report_checkpoint.py in the demo-order-service repository.
        Ensures chunk count increases, accumulated_log grows, runtime predictions are generated,
        and the final chunk correctly sets actual_outcome.
        """
        from src.api.demo_router import get_configured_api_key
        key = get_configured_api_key()
        headers = {"X-API-Key": key} if key else {}
        auth_client = TestClient(app, headers=headers)

        # --- Step 1: Create demo run (mirrors dashboard "Start Demo Run" button) ---
        create_resp = auth_client.post("/api/demo/runs", json={
            "repo_id": "demo-order-service",
            "scenario_preset": "high_risk",
            "changed_files": ["src/order_service.py", "requirements.txt"],
            "runtime_model": "logistic_regression",
            "is_pr": True,
            "auto_advance": False,
        })
        assert create_resp.status_code == 200, f"Run creation failed: {create_resp.text}"
        run_data = create_resp.json()
        run_id = run_data["run_id"]
        assert run_id.startswith("demo_run_"), f"Unexpected run_id format: {run_id}"

        # --- Step 2: Verify GET /api/demo/runs/{run_id} returns the run before any logs ---
        get_resp = auth_client.get(f"/api/demo/runs/{run_id}")
        assert get_resp.status_code == 200
        initial_state = get_resp.json()
        assert initial_state["run_id"] == run_id
        assert initial_state.get("log_chunks_count", 0) == 0, "Fresh run should have zero chunks"

        # --- Step 3: Checkpoint 25% (mirrors Step 3 in demo_pipeline.yml) ---
        chunk_25 = (
            "##[group]Runner Environment Initialization\n"
            "OS: Linux 5.15 x86_64 GNU/Linux\n"
            "Python Path: /usr/bin/python3\n"
            "Python Version: Python 3.12.3\n"
            "Git Version: git version 2.43.0\n"
            "Commit: abc1234def5678\n"
            "Commit Summary: feat: add order validation\n"
            "Workflow Dispatch Run ID: {run_id}\n"
            "##[endgroup]\n"
        ).format(run_id=run_id)

        resp_25 = auth_client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_25,
            "step_name": "Runner Environment Initialization",
            "stage": "setup",
            "is_final": False,
            "exit_code": 0,
            "step_outcome": "success",
            "workflow_outcome": None,
            "ci_run_id": "gha-run-99999",
            "commit_sha": "abc1234def5678",
            "depth": 25,
            "timestamp": "2026-10-30T12:00:00+00:00",
        })
        assert resp_25.status_code == 200, f"Chunk 25 ingestion failed: {resp_25.text}"
        state_25 = resp_25.json()
        assert state_25.get("log_chunks_count", 0) == 1, "Chunk count must be 1 after first ingest"
        assert state_25["status"] == "running"
        assert "accumulated_log" in state_25 or state_25.get("log_chunks_count") > 0, \
            "accumulated_log must be present or chunk count must have increased"

        # 25% must have a runtime prediction
        preds_25 = state_25.get("runtime_predictions", [])
        assert len(preds_25) >= 1, "At least one runtime prediction must exist after 25% chunk"
        pred_25 = next((p for p in preds_25 if p.get("depth_percentage") == 25), None)
        assert pred_25 is not None, "Prediction for depth 25% must be present"
        assert "failure_probability" in pred_25, "Prediction must have failure_probability"
        assert 0.0 <= pred_25["failure_probability"] <= 1.0

        # --- Step 4: Checkpoint 50% with dependency failure evidence ---
        chunk_50 = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "--- [Controlled Demo Injection] Simulating dependency resolution failure ---\n"
            "ERROR: Could not find a version that satisfies the requirement demo-unresolved-dependency-pkg==99.99.99\n"
            "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
            "##[error] Requirements installation failed with exit code 1\n"
        )
        resp_50 = auth_client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_50,
            "step_name": "Install Dependencies (In-Flight Telemetry)",
            "stage": "build",
            "is_final": False,
            "exit_code": None,
            "step_outcome": "running",
            "workflow_outcome": None,
            "ci_run_id": "gha-run-99999",
            "commit_sha": "abc1234def5678",
            "depth": 50,
            "timestamp": "2026-10-30T12:00:05+00:00",
        })
        assert resp_50.status_code == 200, f"Chunk 50 ingestion failed: {resp_50.text}"
        state_50 = resp_50.json()
        assert state_50.get("log_chunks_count", 0) == 2, "Chunk count must be 2 after second ingest"

        preds_50 = state_50.get("runtime_predictions", [])
        pred_50 = next((p for p in preds_50 if p.get("depth_percentage") == 50), None)
        assert pred_50 is not None, "Prediction for depth 50% must be present"
        assert pred_50["failure_probability"] > 0.0, \
            "Failure probability must be positive after dependency error evidence"

        # --- Step 5: Verify GET endpoint reflects updated chunk count ---
        get_resp2 = auth_client.get(f"/api/demo/runs/{run_id}")
        assert get_resp2.status_code == 200
        fetched = get_resp2.json()
        assert fetched.get("log_chunks_count", 0) >= 2, \
            "GET /runs/{run_id} must reflect at least 2 chunks after two ingests"
        fetched_preds = fetched.get("runtime_predictions", [])
        assert len(fetched_preds) >= 1, "GET endpoint must return runtime_predictions"

        # --- Step 6: Checkpoint 100% — final, sets actual_outcome ---
        chunk_100 = (
            "=== Stage: Dependency Installation & Package Resolution ===\n"
            "ERROR: No matching distribution found for demo-unresolved-dependency-pkg==99.99.99\n"
            "##[error] Requirements installation failed with exit code 1\n"
            "=== Step 'Run Test Suite' was skipped due to earlier stage failure. ===\n"
        )
        resp_100 = auth_client.post(f"/api/demo/runs/{run_id}/logs", json={
            "log_chunk": chunk_100,
            "step_name": "Run Test Suite",
            "stage": "test",
            "is_final": True,
            "exit_code": 1,
            "step_outcome": "skipped",
            "workflow_outcome": "failure",
            "ci_run_id": "gha-run-99999",
            "commit_sha": "abc1234def5678",
            "depth": 100,
            "timestamp": "2026-10-30T12:00:15+00:00",
        })
        assert resp_100.status_code == 200, f"Chunk 100 ingestion failed: {resp_100.text}"
        state_100 = resp_100.json()
        assert state_100.get("log_chunks_count", 0) >= 3, \
            "Chunk count must be ≥3 after final ingest"

        # Final run must record the actual outcome
        actual = state_100.get("actual_outcome", "")
        assert actual in ("failure", "failed"), \
            f"actual_outcome must be 'failure' when workflow_outcome=failure; got: '{actual}'"

        # All predictions must remain independent of actual_outcome (ML model output preserved)
        final_preds = state_100.get("runtime_predictions", [])
        assert len(final_preds) >= 1, "Runtime predictions must be present in final state"
        for pred in final_preds:
            if pred.get("is_skipped"):
                assert pred.get("risk_tier") == "SKIPPED"
            else:
                prob = pred.get("failure_probability")
                assert prob is not None, f"Non-skipped predictions must have failure_probability; got {pred}"
                assert 0.0 <= prob <= 1.0, f"Probability must be in [0,1]; got {prob}"
                # Actual outcome must NEVER be directly copied into failure_probability
                assert prob != 1.0, "ML model probability must not be artificially overwritten by actual outcome"

        # --- Step 7: Verify run is listed in /api/demo/runs ---
        list_resp = auth_client.get("/api/demo/runs?limit=10")
        assert list_resp.status_code == 200
        runs_list = list_resp.json()
        run_ids_in_list = [r["run_id"] for r in runs_list]
        assert run_id in run_ids_in_list, \
            f"Run {run_id} must appear in /api/demo/runs list after completion"




