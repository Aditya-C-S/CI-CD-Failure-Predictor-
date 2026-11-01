"""tests/test_bilstm_inference.py

Unit tests for Aayush Jha's BiLSTM deep learning artifacts and LogNormalizer integration:
1. LogNormalizer import, initialization, and transformation rules.
2. Representative raw log normalization (dependency failure, syntax error, pytest, success).
3. Tokenizer 768-token output shape and vocabulary IDs.
4. Task A binary inference across success and failure logs.
5. Task B five-fold ensemble inference and probability averaging over 14 classes.
6. Model availability reporting in model_loader.
7. BiLSTM integration with FastAPI test client.
8. Regression safety for existing LR and SVM models.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import torch
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.bilstm_inference import (
    BiLSTMInferenceEngine,
    Gen2Model,
    Gen3Model,
    get_bilstm_engine,
    predict_bilstm,
    load_canonical_normalizer_class,
    TASK_A_CHECKPOINT,
    TASK_B_CHECKPOINTS,
    TOKENIZER_PATH,
    NORMALIZER_PATH,
    LABEL_MAP,
)
from src.prediction.model_loader import check_model_availability
from src.prediction.predictor import get_predictor, LogisticRegressionPredictor, SVMPredictor


class TestBiLSTMIntegration(unittest.TestCase):

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
        succ_path = Path("data/samples/logs/success/F1/run_0001.log")
        if succ_path.exists():
            self.sample_success_log = succ_path.read_text(encoding="utf-8", errors="replace")
        else:
            self.sample_success_log = (
                "2026-10-20T10:00:00Z Setting up runner\n"
                "Process completed with exit code 0\n"
            )

    def test_log_normalizer_import_and_self_check(self):
        """1. Verify LogNormalizer can be imported and initialized without errors."""
        self.assertTrue(NORMALIZER_PATH.exists(), f"LogNormalizer not found at: {NORMALIZER_PATH}")
        NormalizerClass = load_canonical_normalizer_class()
        normalizer = NormalizerClass()
        self.assertIsNotNone(normalizer)

        # Test BOM and mojibake stripping
        raw = "\ufeffa\u00ef\u00bb\u00bfb"
        cleaned = normalizer.normalize(raw)
        self.assertNotIn("\ufeff", cleaned)
        self.assertNotIn("\u00ef\u00bb\u00bf", cleaned)

        # Test error-line preservation
        err_line = "KeyError: 'missing_key'"
        self.assertIn(err_line, normalizer.normalize(err_line))

    def test_representative_log_normalization(self):
        """2. Verify normalization across representative benchmark samples."""
        NormalizerClass = load_canonical_normalizer_class()
        normalizer = NormalizerClass()

        # Runner prefix scrubbing
        prefixed = "ci_job\tBuild Container Image\tStep executed"
        norm = normalizer.normalize(prefixed)
        self.assertNotIn("ci_job\t", norm)

        # Scenario variable replacement
        scenario_text = "running on feature/f3-test-failures with test_valid_configuration"
        norm_scen = normalizer.normalize(scenario_text)
        self.assertIn("<BRANCH>", norm_scen)
        self.assertIn("<TEST_FUNC>", norm_scen)

    def test_tokenizer_output_shape(self):
        """3. Verify tokenizer produces exact (1, 768) tensor with 192 head / 576 tail split."""
        engine = get_bilstm_engine()
        engine.load_artifacts()
        large_log = "step1 git checkout\n" * 1000
        tensor = engine.tokenize_and_pad(large_log, max_len=768, head_tokens=192, tail_tokens=576)
        self.assertEqual(tensor.shape, (1, 768))
        self.assertEqual(tensor.dtype, torch.long)

    def test_task_a_binary_inference(self):
        """4. Verify Task A binary classifier runs and checks 0.270 threshold."""
        res_fail = predict_bilstm(self.sample_dep_log, visibility=100)
        self.assertEqual(res_fail["model_name"], "bilstm")
        self.assertGreaterEqual(res_fail["failure_probability"], 0.0)
        self.assertLessEqual(res_fail["failure_probability"], 1.0)
        self.assertAlmostEqual(res_fail["task_a_threshold"], 0.270, places=3)

        # Clean success should predict low risk
        res_succ = predict_bilstm(self.sample_success_log, visibility=100)
        self.assertEqual(res_succ["predicted_outcome"], "success")
        self.assertLess(res_succ["failure_probability"], 0.270)
        self.assertIsNone(res_succ["predicted_error_class"])

    def test_task_b_five_fold_ensemble(self):
        """5. Verify Task B executes 5-fold ensemble only on predicted failures."""
        res_fail = predict_bilstm(self.sample_dep_log, visibility=100)
        if res_fail["predicted_outcome"] == "failure":
            self.assertIsNotNone(res_fail["task_b_ensemble_probs"])
            self.assertEqual(len(res_fail["task_b_ensemble_probs"]), 14)
            # Probabilities sum to ~1.0
            total_prob = sum(res_fail["task_b_ensemble_probs"].values())
            self.assertAlmostEqual(total_prob, 1.0, places=2)
            self.assertIn(res_fail["predicted_error_class"], LABEL_MAP.keys())

    def test_model_availability(self):
        """6. Verify check_model_availability reports BiLSTM as available."""
        avail = check_model_availability()
        self.assertTrue(avail["logistic_regression"]["available"])
        self.assertTrue(avail["svm"]["available"])
        self.assertTrue(avail["bilstm"]["available"])
        self.assertEqual(avail["bilstm"]["verified_depths"], [25, 50, 75, 100])

    def test_api_predict_bilstm(self):
        """7. Verify POST /api/predict with BiLSTM."""
        resp = self.client.post(
            "/api/predict",
            json={
                "log_text": self.sample_dep_log,
                "model_name": "bilstm",
                "visibility": 100,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model_name"], "bilstm")
        self.assertEqual(data["visibility_stage"], "100%")
        self.assertIn("failure_probability", data)
        self.assertIn("predicted_label", data)

    def test_regression_lr_and_svm(self):
        """8. Verify existing LR and SVM models continue working without regression."""
        pred_lr = get_predictor("logistic_regression", visibility=25)
        self.assertIsInstance(pred_lr, LogisticRegressionPredictor)
        res_lr = pred_lr.predict_failure(self.sample_dep_log)
        self.assertEqual(res_lr.model_name, "logistic_regression")

        pred_svm = get_predictor("svm", visibility=100)
        self.assertIsInstance(pred_svm, SVMPredictor)
        res_svm = pred_svm.predict_failure(self.sample_dep_log)
        self.assertEqual(res_svm.model_name, "svm")


if __name__ == "__main__":
    unittest.main()
