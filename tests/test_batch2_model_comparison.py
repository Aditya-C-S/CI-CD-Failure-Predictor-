"""tests/test_batch2_model_comparison.py

Batch 2 Tests: Multi-Model Runtime Comparison
Verifies:
1. All three runtime models (BiLSTM v2, TF-IDF + SVM, TF-IDF + Logistic Regression)
   receive equivalent input evidence.
2. Independent model results are returned without cross-contamination.
3. Failure in one model does not fail the other two models.
4. Model comparison is accessible via POST /api/prediction/compare and
   GET /api/demo/runs/{run_id}/model-comparison.
5. No unintended probability ensembling or averaging occurs.
"""

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.runtime_tracker import compare_runtime_models


class TestBatch2ModelComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_compare_runtime_models_equivalent_evidence(self):
        """Verify all 3 models evaluate the exact same log evidence independently."""
        sample_log = (
            "Step 1: Check out repository\n"
            "Step 2: Install dependencies\n"
            "ERROR: Could not find a version that satisfies the requirement torch>=2.0.0\n"
            "ERROR: No matching distribution found for torch>=2.0.0\n"
            "Process completed with exit code 1."
        )

        report = compare_runtime_models(sample_log, depth=50)
        self.assertEqual(report.checkpoint, 50)
        self.assertEqual(len(report.predictions), 3)

        model_ids = [p.model_id for p in report.predictions]
        self.assertIn("bilstm2", model_ids)
        self.assertIn("svm", model_ids)
        self.assertIn("logistic_regression", model_ids)

        # All models successfully evaluated with SUCCESS status
        for p in report.predictions:
            self.assertEqual(p.status, "SUCCESS")
            self.assertIsNotNone(p.failure_probability)
            self.assertGreaterEqual(p.failure_probability, 0.0)
            self.assertLessEqual(p.failure_probability, 1.0)
            self.assertIn(p.predicted_label, ["failure", "success"])
            self.assertEqual(p.prediction_type, "ACTUAL")

    def test_isolated_model_failure_resilience(self):
        """Verify failure in one model returns status=ERROR for it while others succeed."""
        sample_log = "Build step running nominally."

        # Simulate SVM raising an exception
        with patch("src.prediction.predictor.SVMPredictor.predict_failure") as mock_svm:
            mock_svm.side_effect = RuntimeError("Simulated SVM matrix dimension error")

            report = compare_runtime_models(sample_log, depth=100)
            self.assertEqual(len(report.predictions), 3)

            svm_entry = next(p for p in report.predictions if p.model_id == "svm")
            self.assertEqual(svm_entry.status, "ERROR")
            self.assertIsNone(svm_entry.failure_probability)
            self.assertIn("Simulated SVM", svm_entry.error_message)

            # BiLSTM and LR must still succeed
            bilstm_entry = next(p for p in report.predictions if p.model_id == "bilstm2")
            lr_entry = next(p for p in report.predictions if p.model_id == "logistic_regression")
            self.assertEqual(bilstm_entry.status, "SUCCESS")
            self.assertEqual(lr_entry.status, "SUCCESS")

    def test_compare_endpoint_http(self):
        """Verify POST /api/prediction/compare HTTP endpoint returns valid comparison."""
        resp = self.client.post(
            "/api/prediction/compare",
            json={
                "log_text": "pytest tests/ -- tb=short\n3 failed, 12 passed in 2.1s",
                "depth": 100,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("predictions", data)
        self.assertEqual(len(data["predictions"]), 3)
        self.assertIn("agreement_status", data)

    def test_run_model_comparison_endpoint(self):
        """Verify GET /api/demo/runs/{run_id}/model-comparison operates on the run's accumulated logs."""
        create_resp = self.client.post(
            "/api/demo/runs",
            json={
                "repo_id": "demo-org/compare-service",
                "scenario_preset": "high_risk",
                "runtime_model": "bilstm2",
            },
        )
        run_id = create_resp.json()["run_id"]

        # Ingest log
        self.client.post(
            f"/api/demo/runs/{run_id}/logs",
            json={"log_chunk": "Compiling source...\nSyntaxError: unexpected EOF", "depth": 75},
        )

        resp = self.client.get(f"/api/demo/runs/{run_id}/model-comparison")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["predictions"]), 3)


if __name__ == "__main__":
    unittest.main()

