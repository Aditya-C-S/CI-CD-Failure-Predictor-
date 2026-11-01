"""tests/test_prediction.py

Unit tests for the model-independent prediction interface and model loaders.
Validates inference across visibility depths for LR and SVM, and stub handling
for pending teammate models.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.prediction.model_interface import BasePredictor, PredictionResult
from src.prediction.model_loader import check_model_availability
from src.prediction.predictor import get_predictor, LogisticRegressionPredictor, SVMPredictor


class TestPrediction(unittest.TestCase):

    def setUp(self):
        self.sample_text = (
            "2026-10-20T10:00:00Z Setting up runner\n"
            "2026-10-20T10:00:01Z Complete job name: Python Test Suite\n"
            "2026-10-20T10:00:02Z git checkout main\n"
            "2026-10-20T10:00:03Z python -m pip install -r requirements.txt\n"
        )

    def test_logistic_regression_depth25(self):
        predictor = get_predictor("logistic_regression", visibility=25)
        self.assertIsInstance(predictor, LogisticRegressionPredictor)
        res = predictor.predict_failure(self.sample_text, visibility=25)
        self.assertIsInstance(res, PredictionResult)
        self.assertEqual(res.model_name, "logistic_regression")
        self.assertEqual(res.visibility_stage, "25%")
        self.assertGreaterEqual(res.failure_probability, 0.0)
        self.assertLessEqual(res.failure_probability, 1.0)
        self.assertIn(res.predicted_label, ["failure", "success"])

    def test_svm_depth25(self):
        predictor = get_predictor("svm", visibility=25)
        self.assertIsInstance(predictor, SVMPredictor)
        res = predictor.predict_failure(self.sample_text, visibility=25)
        self.assertIsInstance(res, PredictionResult)
        self.assertEqual(res.model_name, "svm")
        self.assertEqual(res.visibility_stage, "25%")
        self.assertGreaterEqual(res.failure_probability, 0.0)
        self.assertLessEqual(res.failure_probability, 1.0)
        self.assertIsNotNone(res.decision_score)

    def test_model_availability(self):
        avail = check_model_availability()
        self.assertTrue(avail["logistic_regression"]["available"])
        self.assertTrue(avail["svm"]["available"])
        self.assertTrue(avail["bilstm"]["available"])
        self.assertFalse(avail["modernbert"]["available"])

    def test_modernbert_stub_raises(self):
        predictor = get_predictor("modernbert", visibility=25)
        with self.assertRaises(NotImplementedError):
            predictor.predict_failure(self.sample_text)

    def test_bilstm_live_inference(self):
        predictor = get_predictor("bilstm", visibility=100)
        self.assertEqual(predictor.model_name, "bilstm")
        res = predictor.predict_failure(self.sample_text, visibility=100)
        self.assertIsInstance(res, PredictionResult)
        self.assertEqual(res.model_name, "bilstm")
        self.assertIn(res.predicted_label, ["failure", "success"])
        self.assertGreaterEqual(res.failure_probability, 0.0)
        self.assertLessEqual(res.failure_probability, 1.0)


if __name__ == "__main__":
    unittest.main()
