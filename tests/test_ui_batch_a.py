"""
tests/test_ui_batch_a.py
Validation and Integration Test Suite for UI Batch A:
- Modern Layout and Static File Serving
- ES Module Files Routing
- Health & Diagnostics API Response
- Scenario Orchestration API & Dry-Run Dispatch
- Demo ID Persistence & Retrieval
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app

@pytest.fixture(scope="module")
def client():
    return TestClient(app)

class TestUIBatchA:
    def test_frontend_root_html(self, client):
        """Test GET / returns modern HTML shell with required elements."""
        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # Verify Core Shell
        assert 'id="app-root"' in html
        assert 'class="app-sidebar"' in html
        assert 'src="/static/app.js?v=3.0"' in html

        # Verify Sidebar Routes
        for route in ["overview", "live-pipeline", "run-history", "metadata-intel", "graph-intel", "model-comparison", "rca", "demo-control", "system-health"]:
            assert f'data-route="{route}"' in html

        # Verify Views
        assert 'id="view-overview"' in html
        assert 'id="view-demo-control"' in html
        assert 'id="view-system-health"' in html

        # Verify Prominent Demo ID elements & Copy buttons
        assert 'id="active-demo-run-banner-container"' in html
        assert 'id="latest-run-card-container"' in html
        assert 'id="toast-container"' in html

    def test_static_files_served(self, client):
        """Verify all new ES modules and CSS are served under /static."""
        static_endpoints = [
            "/static/style.css",
            "/static/app.js",
            "/static/js/api.js",
            "/static/js/theme.js",
            "/static/js/navigation.js",
            "/static/js/overview.js",
            "/static/js/demo-control.js",
            "/static/js/health.js",
            "/static/js/utils.js"
        ]
        for endpoint in static_endpoints:
            res = client.get(endpoint)
            assert res.status_code == 200, f"Static resource {endpoint} not found (status {res.status_code})"
            assert len(res.content) > 50, f"Static resource {endpoint} unexpectedly empty"

    def test_api_health_endpoint_contract(self, client):
        """Verify /api/health/system fulfills 6-component diagnostics contract."""
        res = client.get("/api/health/system")
        assert res.status_code == 200
        data = res.json()

        assert "status" in data
        assert "timestamp" in data
        assert "components" in data

        comps = data["components"]
        required_subsystems = ["backend", "neo4j", "runtime_models", "metadata_model", "log_ingestion", "persistence"]
        for sub in required_subsystems:
            assert sub in comps, f"Subsystem '{sub}' missing from system health"

        # Check sub-structure
        assert "status" in comps["backend"]
        assert "status" in comps["neo4j"]
        assert "status" in comps["metadata_model"]
        assert "status" in comps["log_ingestion"]
        assert "status" in comps["persistence"]
        assert "bilstm2" in comps["runtime_models"]

    def test_scenarios_and_dispatch_contract(self, client):
        """Verify scenario loading and dispatch endpoint."""
        # 1. Fetch scenarios
        res_sc = client.get("/api/scenarios")
        assert res_sc.status_code == 200
        scenarios = res_sc.json()
        assert isinstance(scenarios, list)
        assert len(scenarios) == 4
        scenario_ids = [s["scenario_id"] for s in scenarios]
        assert set(scenario_ids) == {"none", "dependency", "syntax", "pytest"}

        # 2. Dispatch a scenario
        payload = {
            "scenario_id": "dependency",
            "repo_id": "Aditya-C-S/demo-order-service",
            "runtime_model": "bilstm2",
            "dry_run": True
        }
        res_disp = client.post("/api/scenarios/dispatch", json=payload)
        assert res_disp.status_code == 200
        disp_data = res_disp.json()

        assert "run_id" in disp_data
        assert disp_data["run_id"].startswith("demo_run_") or disp_data["run_id"].startswith("run-")
        assert disp_data["status"] == "DISPATCHED"

        # 3. Check status
        run_id = disp_data["run_id"]
        res_st = client.get(f"/api/scenarios/runs/{run_id}/status")
        assert res_st.status_code == 200
        st_data = res_st.json()
        assert st_data["scenario_id"] == "dependency"

    def test_demo_runs_and_summaries(self, client):
        """Verify runs and summaries retrieval."""
        res_runs = client.get("/api/demo/runs?limit=5")
        assert res_runs.status_code == 200
        assert isinstance(res_runs.json(), list)

        res_sum = client.get("/api/summaries?limit=5")
        assert res_sum.status_code == 200
        assert isinstance(res_sum.json(), list)
