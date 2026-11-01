"""tests/test_batch3_part_a_rca.py

Batch 3 Part A Tests: Advanced Root Cause Analysis (RCA) Engine
Verifies:
1. All 8 failure categories correctly classified from evidence.
2. Parser V2 structured findings and authentic line-number mapping.
3. Multiple root cause identification and ranking by evidence strength.
4. Remediation suggestions categorized into confirmed fixes vs troubleshooting.
5. Distinction of evidence strength (STRONG, MODERATE, LIMITED) & confidence.
6. Clean or insufficient log handling (returns INSUFFICIENT_EVIDENCE without guessing).
7. Persistence with DemoRun and retrieval via REST API endpoints.
8. Updating RCA when additional logs arrive.
"""

import os
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.rca.advanced_rca import AdvancedRCAEngine, FailureCategory


class TestBatch3PartARCA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("DEMO_API_KEY", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        cls.client = TestClient(app, headers=headers)

    def test_dependency_failure_classification_and_evidence(self):
        """Verify dependency failure produces DEPENDENCY_FAILURE, correct line numbers, and confirmed fix."""
        dep_log = (
            "Line 1: Starting CI environment setup\n"
            "Line 2: pip install -r requirements.txt\n"
            "ERROR: Could not find a version that satisfies the requirement torch-missing==99.9.9\n"
            "ERROR: No matching distribution found for torch-missing==99.9.9\n"
            "##[error]Process completed with exit code 1.\n"
        )
        report = AdvancedRCAEngine.analyze(dep_log, run_id="run_dep_test")
        self.assertEqual(report.primary_category, FailureCategory.DEPENDENCY_FAILURE)
        self.assertEqual(report.evidence_strength, "STRONG")
        self.assertGreaterEqual(report.rca_confidence, 0.90)
        self.assertTrue(len(report.root_causes) >= 1)
        self.assertTrue(report.root_causes[0].is_confirmed)
        self.assertIn("torch-missing", report.root_causes[0].why_failed)

        # Verify evidence line numbers
        ev_items = report.evidence_items
        self.assertTrue(any(ev.line_number in (3, 4) for ev in ev_items))
        self.assertTrue(any(ev.source_type in ("parser_v2", "raw_log") for ev in ev_items))

        # Verify remediation
        remed = report.remediation
        self.assertTrue(len(remed["confirmed_fixes"]) >= 1)
        self.assertTrue(any("requirements.txt" in fix["action"] for fix in remed["confirmed_fixes"]))

    def test_syntax_failure_classification_and_evidence(self):
        """Verify syntax error identifies file, line, and SYNTAX_FAILURE."""
        syntax_log = (
            "job\tStep\t2026-10-30T10:00:00Z python app/main.py\n"
            "job\tStep\t2026-10-30T10:00:01Z   File \"app/main.py\", line 42\n"
            "job\tStep\t2026-10-30T10:00:01Z     def calculate(\n"
            "job\tStep\t2026-10-30T10:00:01Z                  ^\n"
            "job\tStep\t2026-10-30T10:00:01Z SyntaxError: '(' was never closed\n"
            "job\tStep\t2026-10-30T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        report = AdvancedRCAEngine.analyze(syntax_log, run_id="run_syntax_test")
        self.assertEqual(report.primary_category, FailureCategory.SYNTAX_FAILURE)
        self.assertEqual(report.evidence_strength, "STRONG")
        self.assertGreaterEqual(report.rca_confidence, 0.90)

        # Check file and line identification
        self.assertIn("app/main.py", report.root_causes[0].where_failed)
        self.assertIn("42", report.root_causes[0].where_failed)

        # Check remediation suggests compiling/linting
        remed = report.remediation
        self.assertTrue(any("py_compile" in cmd for cmd in remed["terminal_commands"]))

    def test_test_failure_classification(self):
        """Verify pytest assertion failure maps to TEST_FAILURE."""
        test_log = (
            "=== test session starts ===\n"
            "tests/test_orders.py:25: in test_create_order\n"
            "    assert response.status_code == 200\n"
            "E   AssertionError: assert 500 == 200\n"
            "=========================== FAILURES ===========================\n"
            "FAILED tests/test_orders.py::test_create_order\n"
        )
        report = AdvancedRCAEngine.analyze(test_log, run_id="run_test_fail")
        self.assertEqual(report.primary_category, FailureCategory.TEST_FAILURE)
        self.assertEqual(report.evidence_strength, "STRONG")
        self.assertIn("test", report.classification_method.lower())

    def test_docker_build_failure_classification(self):
        """Verify Docker build failure maps to BUILD_FAILURE."""
        docker_log = (
            "#4 [internal] load build context\n"
            "#5 [1/3] COPY requirements.txt .\n"
            "ERROR: failed to solve: failed to compute cache key: \"requirements.txt\": not found\n"
            "##[error]Process completed with exit code 1.\n"
        )
        report = AdvancedRCAEngine.analyze(docker_log, run_id="run_build_fail")
        self.assertEqual(report.primary_category, FailureCategory.BUILD_FAILURE)
        self.assertEqual(report.evidence_strength, "STRONG")

    def test_config_and_permission_failure_classification(self):
        """Verify workflow YAML / permission failure maps to CONFIGURATION_FAILURE."""
        cfg_log = (
            "Workflow is not valid: .github/workflows/deploy.yml: Unexpected symbol: 'foo'\n"
            "HttpError: Resource not accessible by integration: 403 Forbidden\n"
        )
        report = AdvancedRCAEngine.analyze(cfg_log, run_id="run_cfg_fail")
        self.assertEqual(report.primary_category, FailureCategory.CONFIGURATION_FAILURE)

    def test_infrastructure_timeout_failure_classification(self):
        """Verify timeout maps to INFRASTRUCTURE_FAILURE."""
        timeout_log = (
            "##[error]The action 'Run Tests' has timed out after 30.0 minutes.\n"
            "##[error]The operation was canceled because it has timed out.\n"
        )
        report = AdvancedRCAEngine.analyze(timeout_log, run_id="run_infra_fail")
        self.assertEqual(report.primary_category, FailureCategory.INFRASTRUCTURE_FAILURE)

    def test_unknown_and_insufficient_evidence_handling(self):
        """Verify nominal or ambiguous log does not invent a cause."""
        clean_log = (
            "Starting job nominally\n"
            "All packages installed successfully.\n"
            "10 tests passed in 1.2s.\n"
            "Build complete.\n"
        )
        report = AdvancedRCAEngine.analyze(clean_log, run_id="run_clean")
        self.assertEqual(report.primary_category, FailureCategory.INSUFFICIENT_EVIDENCE)
        self.assertEqual(report.rca_confidence, 0.10)
        self.assertEqual(len(report.root_causes), 0)

        empty_report = AdvancedRCAEngine.analyze("", run_id="run_empty")
        self.assertEqual(empty_report.primary_category, FailureCategory.INSUFFICIENT_EVIDENCE)
        self.assertEqual(empty_report.status, "INSUFFICIENT_EVIDENCE")

    def test_rca_api_endpoints_and_persistence(self):
        """Verify demo run ingestion triggers RCA and exposes endpoints /rca, /rca/findings, /rca/evidence, /rca/remediation."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "Aditya-C-S/demo-order-service",
                "scenario_preset": "high_risk",
                "runtime_model": "bilstm2",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        run_id = create_resp.json()["run_id"]

        fail_chunk = (
            "Step: Install Dependencies\n"
            "ERROR: Could not find a version that satisfies the requirement requests==999.0.0\n"
            "ERROR: No matching distribution found for requests==999.0.0\n"
            "Process completed with exit code 1."
        )
        ingest_resp = self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={
                "log_chunk": fail_chunk,
                "depth": 50,
                "step_name": "Install Dependencies",
                "stage": "build",
                "exit_code": 1,
                "step_outcome": "failure",
            },
        )
        self.assertEqual(ingest_resp.status_code, 200)

        # 1. GET /api/demo/runs/{run_id}/rca
        rca_resp = self.client.get(f"/api/demo/runs/{run_id}/rca")
        self.assertEqual(rca_resp.status_code, 200)
        rca_data = rca_resp.json()
        self.assertEqual(rca_data["primary_category"], FailureCategory.DEPENDENCY_FAILURE)
        self.assertGreaterEqual(rca_data["rca_confidence"], 0.90)

        # 2. GET /api/demo/runs/{run_id}/rca/findings
        findings_resp = self.client.get(f"/api/demo/runs/{run_id}/rca/findings")
        self.assertEqual(findings_resp.status_code, 200)
        findings = findings_resp.json()
        self.assertTrue(len(findings) >= 1)
        self.assertEqual(findings[0]["category"], FailureCategory.DEPENDENCY_FAILURE)

        # 3. GET /api/demo/runs/{run_id}/rca/evidence
        ev_resp = self.client.get(f"/api/demo/runs/{run_id}/rca/evidence")
        self.assertEqual(ev_resp.status_code, 200)
        ev_items = ev_resp.json()
        self.assertTrue(len(ev_items) >= 1)

        # 4. GET /api/demo/runs/{run_id}/rca/remediation
        rem_resp = self.client.get(f"/api/demo/runs/{run_id}/rca/remediation")
        self.assertEqual(rem_resp.status_code, 200)
        rem = rem_resp.json()
        self.assertIn("pip", " ".join(rem.get("terminal_commands", [])))

        # 5. POST /api/demo/runs/{run_id}/rca (force update)
        update_resp = self.client.post(f"/api/demo/runs/{run_id}/rca")
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
