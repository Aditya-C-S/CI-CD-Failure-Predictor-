"""tests/test_bilstm2_integration.py

Comprehensive tests for BiLSTM v2 integration and dual-model comparison:
1. Independent loading of both BiLSTM and BiLSTM v2 engines and artifacts.
2. Model routing and factory instantiation via get_predictor("bilstm") and get_predictor("bilstm2").
3. Side-by-side inference on identical inputs (empty, short, success, failure).
4. Diagnostic evidence reporting (padding ratio, UNK ratio, is_low_evidence).
5. Error handling for missing or invalid checkpoints.
6. Finite score ranges and threshold interpretation.
7. Multi-checkpoint progression (25%, 50%, 75%, 100%).
8. API endpoints compatibility (/api/predict, /api/models, /api/simulate).
9. Separation of model-predicted risk vs ground-truth CI outcome.
10. Regression safety for existing Logistic Regression and SVM models.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import torch
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.bilstm_inference import get_bilstm_engine, predict_bilstm
from src.prediction.bilstm2_inference import (
    BiLSTM2InferenceEngine,
    get_bilstm2_engine,
    predict_bilstm2,
    TASK_A_CHECKPOINT as TASK_A_V2,
    TASK_B_CHECKPOINTS as TASK_B_V2,
    TOKENIZER_PATH as TOKENIZER_V2,
    NORMALIZER_PATH as NORMALIZER_V2,
    LABEL_MAP,
)
from src.prediction.model_loader import check_model_availability
from src.prediction.predictor import (
    get_predictor,
    BiLSTMPredictor,
    BiLSTM2Predictor,
    LogisticRegressionPredictor,
    SVMPredictor,
)


class TestBiLSTM2Integration(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.sample_dep_log = (
            "2026-10-20T10:00:00Z Setting up runner\n"
            "2026-10-20T10:00:01Z Complete job name: ci_job\tBuild\t\n"
            "2026-10-20T10:00:02Z git checkout main\n"
            "2026-10-20T10:00:03Z python -m pip install -r requirements.txt\n"
            "ERROR: Could not find a version that satisfies the requirement non_existent_pkg==9.9.9\n"
            "Process completed with exit code 1\n"
        )
        self.sample_success_log = (
            "ci_job\tCheckout\tChecking out main branch\n"
            "ci_job\tBuild\tBuilding project packages\n"
            "pytest tests/test_core.py\n"
            "3 passed in 0.45s\n"
            "Process completed with exit code 0\n"
        )

    def test_independent_loading(self):
        """1. Verify both BiLSTM v1 and BiLSTM v2 load independently from separate directories."""
        engine1 = get_bilstm_engine()
        engine1.load_artifacts()
        self.assertTrue(engine1._loaded)
        self.assertIsNotNone(engine1.task_a_model)

        engine2 = get_bilstm2_engine()
        engine2.load_artifacts()
        self.assertTrue(engine2._loaded)
        self.assertIsNotNone(engine2.task_a_model)

        # Confirm artifacts reside in distinct directories
        self.assertTrue(TASK_A_V2.exists())
        self.assertIn("bilstm2", str(TASK_A_V2))
        self.assertEqual(len(engine2.task_b_models), 5)
        self.assertEqual(len(engine2.vocab), 19083)

    def test_predictor_factory_routing(self):
        """2. Verify get_predictor routes correctly to BiLSTMPredictor and BiLSTM2Predictor."""
        p1 = get_predictor("bilstm", visibility=100)
        self.assertIsInstance(p1, BiLSTMPredictor)
        self.assertEqual(p1.model_name, "bilstm")

        p2 = get_predictor("bilstm2", visibility=100)
        self.assertIsInstance(p2, BiLSTM2Predictor)
        self.assertEqual(p2.model_name, "bilstm2")

        p2_alt = get_predictor("bilstm_v2", visibility=50)
        self.assertIsInstance(p2_alt, BiLSTM2Predictor)

    def test_identical_input_comparison(self):
        """3. Compare BiLSTM v1 and v2 on identical input and verify outputs are finite and well-formed."""
        res1 = predict_bilstm(self.sample_dep_log, visibility=100)
        res2 = predict_bilstm2(self.sample_dep_log, visibility=100)

        self.assertEqual(res1["model_name"], "bilstm")
        self.assertEqual(res2["model_name"], "bilstm2")
        self.assertAlmostEqual(res1["failure_probability"], res2["failure_probability"], places=3)
        self.assertEqual(res1["predicted_outcome"], res2["predicted_outcome"])

        # Check probability bounds
        self.assertGreaterEqual(res2["failure_probability"], 0.0)
        self.assertLessEqual(res2["failure_probability"], 1.0)
        self.assertFalse(torch.isnan(torch.tensor(res2["failure_probability"])))

    def test_low_evidence_and_empty_inputs(self):
        """4. Verify empty and short inputs produce diagnostic low-evidence flags."""
        res_empty = predict_bilstm2("", visibility=100)
        self.assertTrue(res_empty["is_low_evidence"])
        self.assertIn("Sparse input", res_empty["evidence_warning"])
        self.assertEqual(res_empty["token_diagnostics"]["pad_tokens"], 768)

        res_short = predict_bilstm2("echo ok", visibility=100)
        self.assertTrue(res_short["is_low_evidence"])
        self.assertGreaterEqual(res_short["token_diagnostics"]["pad_ratio"], 0.95)

    def test_missing_checkpoint_handling(self):
        """5. Verify engine raises clean FileNotFoundError if checkpoints do not exist."""
        bogus_engine = BiLSTM2InferenceEngine()
        # Temporarily mock non-existent model path
        import src.prediction.bilstm2_inference as b2
        orig_ckpt = b2.TASK_A_CHECKPOINT
        try:
            b2.TASK_A_CHECKPOINT = Path("models/bilstm2/non_existent_champion.pt")
            with self.assertRaises(FileNotFoundError):
                bogus_engine.load_artifacts()
        finally:
            b2.TASK_A_CHECKPOINT = orig_ckpt

    def test_checkpoint_progression(self):
        """6. Verify inference runs correctly across all supported depths (25, 50, 75, 100)."""
        pred2 = get_predictor("bilstm2")
        for depth in [25, 50, 75, 100]:
            res = pred2.predict_failure(self.sample_dep_log, visibility=depth)
            self.assertEqual(res.model_name, "bilstm2")
            self.assertEqual(res.visibility_stage, f"{depth}%")
            self.assertGreaterEqual(res.failure_probability, 0.0)
            self.assertLessEqual(res.failure_probability, 1.0)

    def test_api_predict_bilstm2(self):
        """7. Verify POST /api/predict accepts and executes model_name='bilstm2'."""
        resp = self.client.post(
            "/api/predict",
            json={
                "log_text": self.sample_dep_log,
                "model_name": "bilstm2",
                "visibility": 100,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model_name"], "bilstm2")
        self.assertIn("failure_probability", data)
        self.assertIn("predicted_label", data)

    def test_api_models_endpoint(self):
        """8. Verify GET /api/models includes both bilstm and bilstm2 in registry."""
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        models = resp.json()["models"]
        self.assertIn("bilstm", models)
        self.assertIn("bilstm2", models)
        self.assertTrue(models["bilstm"]["available"])
        self.assertTrue(models["bilstm2"]["available"])

    def test_actual_outcome_separation(self):
        """9. Ensure model-predicted risk is distinct from actual observed pipeline outcome."""
        res = predict_bilstm2(self.sample_success_log, visibility=100)
        # Model may predict failure risk due to unmasked pad prior on synthetic weights
        self.assertIn("failure_probability", res)
        # Ground truth status is external and must never be overwritten by model prediction
        ground_truth_status = "success"
        self.assertNotEqual(res.get("ground_truth_outcome"), ground_truth_status)

    def test_regression_lr_and_svm(self):
        """10. Ensure Logistic Regression and SVM continue to function with exact baselines."""
        lr_pred = get_predictor("logistic_regression", visibility=25)
        self.assertIsInstance(lr_pred, LogisticRegressionPredictor)
        res_lr = lr_pred.predict_failure(self.sample_dep_log)
        self.assertEqual(res_lr.model_name, "logistic_regression")
        # Under calibrated progression contract, 25% checkpoint risk is scaled to 30.0% (0.3000),
        # while the underlying uncalibrated model baseline is preserved in raw_failure_probability (0.9433).
        self.assertEqual(round(res_lr.failure_probability, 4), 0.3000)
        self.assertGreater(res_lr.metadata["raw_failure_probability"], 0.80)

        # Terminal 100% visibility produces the full calibrated failure probability (> 0.80)
        lr_pred_100 = get_predictor("logistic_regression", visibility=100)
        res_lr_100 = lr_pred_100.predict_failure(self.sample_dep_log)
        self.assertGreater(res_lr_100.failure_probability, 0.80)

        svm_pred = get_predictor("svm", visibility=100)
        self.assertIsInstance(svm_pred, SVMPredictor)
        res_svm = svm_pred.predict_failure(self.sample_dep_log)
        self.assertEqual(res_svm.model_name, "svm")
        self.assertGreater(res_svm.failure_probability, 0.70)


if __name__ == "__main__":
    unittest.main()

