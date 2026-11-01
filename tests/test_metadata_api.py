"""tests/test_metadata_api.py

Comprehensive tests for Metadata Model API endpoints:
- POST /api/metadata/predict (success, validation, missing fields, invalid values, SHAP)
- GET  /api/metadata/model-info (model readiness, architecture, contracts)
- GET  /api/metadata/scorecard (metrics, calibration, demographics, top gain)
- GET  /api/metadata/charts/{chart_name} (static chart serving)
- Verification that existing log-model endpoints (/health, /api/models, /api/predict) remain functional.
"""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.metadata_service import CANONICAL_FEATURE_COLUMNS


class TestMetadataAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_includes_metadata_model(self):
        """Verify that GET /health reports metadata model readiness alongside existing log models."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("models_summary", data)
        self.assertIn("metadata_model", data)
        self.assertEqual(data["metadata_model"]["status"], "ready")
        self.assertIn("run_20260926_013515", data["metadata_model"]["version"])

    def test_metadata_model_info(self):
        """Verify GET /api/metadata/model-info exposes correct metadata and schema."""
        response = self.client.get("/api/metadata/model-info")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["feature_count"], 38)
        self.assertListEqual(data["expected_features"], CANONICAL_FEATURE_COLUMNS)
        self.assertTrue(data["shap_supported"])
        self.assertIn("FAST_TRACK", data["thresholds"])
        self.assertIn("LightGBM", data["algorithm"])

    def test_metadata_scorecard(self):
        """Verify GET /api/metadata/scorecard returns verified evaluation metrics."""
        response = self.client.get("/api/metadata/scorecard")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check global metrics
        global_m = data["global_metrics"]
        self.assertAlmostEqual(global_m["roc_auc"], 0.857884, places=4)
        self.assertAlmostEqual(global_m["pr_auc"], 0.744879, places=4)
        self.assertAlmostEqual(global_m["mcc_at_50"], 0.542534, places=4)
        self.assertAlmostEqual(global_m["composite_fitness_score"], 1.426552, places=4)

        # Check calibration & demographics
        self.assertIn("dataset_demographics", data)
        self.assertEqual(data["dataset_demographics"]["total_build_events_all_splits"], 919833)
        self.assertIn("feature_importance_top_15_by_gain", data)
        self.assertIn("available_static_charts", data)
        self.assertIn("chart_calibration.png", data["available_static_charts"])

    def test_metadata_predict_low_risk_success(self):
        """Verify successful prediction on a clean, low-risk commit payload."""
        payload = {
            "features": {
                "gh_is_pr": 1,
                "gh_lang_python": 1,
                "log_team_size": 2.3,
                "log_built_commits": 6.2,
                "gh_repo_age": 1000,
                "gh_repo_num_commits": 5000,
                "tr_build_number": 100,
                "gh_sloc": 50000,
                "git_diff_src_churn": 10,
                "git_diff_test_churn": 5,
                "gh_diff_files_modified": 1,
                "gh_diff_src_files": 1,
                "gh_num_commits_on_files_touched": 5,
                "gh_test_lines_per_kloc": 100.0,
                "gh_test_cases_per_kloc": 10.0,
                "gh_asserts_cases_per_kloc": 15.0,
                "gh_by_core_team_member": 1,
                "total_files_changed": 1,
                "code_churn_density": 10.0,
                "test_to_src_churn_ratio": 0.5,
                "has_previous_build": 1,
                "gh_pr_created_at_year": 2020,
                "gh_pr_created_at_month": 6,
                "pr_dayofweek": 2,
                "git_merged_with_present": 1,
            }
        }
        response = self.client.post("/api/metadata/predict", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check probability bounds and verdict
        self.assertGreaterEqual(data["failure_probability"], 0.0)
        self.assertLessEqual(data["failure_probability"], 1.0)
        self.assertEqual(data["verdict"], "FAST-TRACK")
        self.assertGreater(data["latency_ms"], 0.0)

        # Check SHAP drivers
        shap = data["shap_drivers"]
        self.assertIn("positive", shap)
        self.assertIn("negative", shap)
        self.assertGreater(len(shap["positive"]), 0)
        self.assertGreater(len(shap["negative"]), 0)
        self.assertIn("feature", shap["positive"][0])
        self.assertIn("contribution", shap["positive"][0])

    def test_metadata_predict_high_risk_success(self):
        """Verify successful prediction on a destructive, high-risk commit payload."""
        payload = {
            "features": {
                "git_diff_src_churn": 4500,
                "total_files_changed": 50,
                "gh_diff_tests_deleted": 30,
                "gh_test_lines_per_kloc": 0.0,
                "test_to_src_churn_ratio": 0.0,
                "gh_by_core_team_member": 0,
                "code_churn_density": 90.0,
                "gh_diff_files_deleted": 15,
            }
        }
        response = self.client.post("/api/metadata/predict", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertGreater(data["failure_probability"], 0.20)
        self.assertIn("positive", data["shap_drivers"])
        self.assertIn(data["verdict"], ["FAST-TRACK", "STANDARD GATE", "ALERT", "PRE-MERGE BLOCK"])

    def test_metadata_predict_flat_json_body(self):
        """Verify support for direct flat JSON body (without nested 'features' key)."""
        payload = {
            "git_diff_src_churn": 120,
            "total_files_changed": 4,
            "gh_is_pr": 1,
            "gh_repo_age": 800,
        }
        response = self.client.post("/api/metadata/predict", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("failure_probability", data)
        self.assertEqual(data["features_analyzed"]["git_diff_src_churn"], 120.0)

    def test_metadata_predict_missing_payload(self):
        """Verify 400 rejection when payload is empty."""
        response = self.client.post("/api/metadata/predict", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No metadata features provided", response.json()["detail"])

    def test_metadata_predict_invalid_data_type(self):
        """Verify 400 rejection on unparsable non-numeric feature value."""
        payload = {
            "features": {
                "git_diff_src_churn": "not-a-number",
            }
        }
        response = self.client.post("/api/metadata/predict", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Feature 'git_diff_src_churn' has invalid non-numeric value", response.json()["detail"])

    def test_metadata_chart_serving(self):
        """Verify that static evaluation charts can be served via GET /api/metadata/charts/{name}."""
        response = self.client.get("/api/metadata/charts/chart_feature_importance.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_metadata_chart_not_found(self):
        """Verify 404 on nonexistent chart name."""
        response = self.client.get("/api/metadata/charts/nonexistent_chart.png")
        self.assertEqual(response.status_code, 404)

    def test_existing_log_prediction_endpoints_unaffected(self):
        """Verify existing log-model API endpoints remain fully functional."""
        # 1. Existing GET /api/models
        resp_models = self.client.get("/api/models")
        self.assertEqual(resp_models.status_code, 200)
        self.assertIn("models", resp_models.json())

        # 2. Existing POST /api/predict with Logistic Regression
        log_sample = "2026-10-24 10:00:00 [ERROR] Build failed due to null pointer exception in service layer."
        predict_req = {
            "log_text": log_sample,
            "model_name": "logistic_regression",
            "visibility": 25,
        }
        resp_predict = self.client.post("/api/predict", json=predict_req)
        self.assertEqual(resp_predict.status_code, 200)
        data = resp_predict.json()
        self.assertIn("failure_probability", data)
        self.assertIn("predicted_label", data)
        self.assertEqual(data["model_name"], "logistic_regression")

        # 3. Existing POST /api/parse
        parse_req = {"log_text": log_sample, "run_id": "test_run_01"}
        resp_parse = self.client.post("/api/parse", json=parse_req)
        self.assertEqual(resp_parse.status_code, 200)
        self.assertIn("error_type", resp_parse.json())
        self.assertIn("status", resp_parse.json())


if __name__ == "__main__":
    unittest.main()
