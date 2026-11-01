"""src/prediction/predictor.py

Concrete predictor implementations for Logistic Regression, SVM,
and pending deep learning models (ModernBERT, BiLSTM).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional, Union

import numpy as np

from src.prediction.evidence_analyzer import (
    LogEvidenceAnalyzer,
    calibrate_model_probability,
    apply_checkpoint_calibration_adjustment,
)
from src.prediction.model_interface import BasePredictor, PredictionResult
from src.prediction.model_loader import load_model_pipeline, check_model_availability
from src.prediction.sanitizer import sanitize_log_text

logger = logging.getLogger(__name__)


class LogisticRegressionPredictor(BasePredictor):
    """Predictor using TF-IDF + Logistic Regression pipeline across visibility stages."""

    def __init__(self, visibility: Union[int, str] = 25):
        super().__init__(model_name="logistic_regression", visibility=visibility)

    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        t0 = time.perf_counter()
        depth = self._normalize_visibility(visibility if visibility is not None else self.visibility)

        # 1. Deterministic sanitization
        clean_text = sanitize_log_text(log_text)

        # 2. Pipeline inference
        pipeline = load_model_pipeline("logistic_regression", depth=depth, task="A")
        raw_pred = pipeline.predict([clean_text])[0]
        raw_proba = pipeline.predict_proba([clean_text])[0]

        # 3. Probability alignment
        classes = list(pipeline.classes_)
        if "failure" in classes:
            fail_idx = classes.index("failure")
            raw_failure_prob = float(raw_proba[fail_idx])
        else:
            raw_failure_prob = float(raw_proba[0])

        # 4. Evidence-aware calibration & Checkpoint refinement
        evidence = LogEvidenceAnalyzer.analyze(log_text)
        is_sparse = evidence.is_sparse or len(clean_text.splitlines()) < 20
        base_calibrated_prob, raw_label = calibrate_model_probability(
            raw_prob=raw_failure_prob,
            evidence=evidence,
            is_sparse_or_padding=is_sparse,
            depth=depth,
            model_name="logistic_regression",
        )
        calibrated_prob, checkpoint_adj = apply_checkpoint_calibration_adjustment(
            base_calibrated_prob=base_calibrated_prob,
            depth=depth,
            raw_prob=raw_failure_prob,
            evidence=evidence,
            model_name="logistic_regression",
        )

        if calibrated_prob >= 0.50 and not evidence.has_success_evidence:
            predicted_label = "failure"
        elif calibrated_prob < 0.50 and not evidence.has_failure_evidence:
            predicted_label = "success"
        else:
            predicted_label = raw_label

        latency_ms = (time.perf_counter() - t0) * 1000

        return PredictionResult(
            failure_probability=calibrated_prob,
            predicted_label=predicted_label,
            model_name="logistic_regression",
            visibility_stage=f"{depth}%",
            decision_score=None,
            confidence=max(raw_proba),
            metadata={
                "raw_failure_probability": round(raw_failure_prob, 4),
                "raw_predicted_label": str(raw_pred),
                "base_calibrated_failure_probability": round(base_calibrated_prob, 4),
                "checkpoint_adjustment": checkpoint_adj,
                "calibrated_failure_probability": calibrated_prob,
                "calibration_applied": True,
                "calibration_method": "evidence_aware_sparsity_calibration",
                "calibration_type": "evidence_adjusted_risk_heuristic",
                "evidence_score": round(evidence.evidence_score, 4),
                "evidence_indicators": evidence.failure_indicators if evidence.has_failure_evidence else evidence.success_indicators,
                "evidence_report": evidence.to_dict(),
                "is_low_evidence": is_sparse,
                "inference_latency_ms": round(latency_ms, 2),
                "sanitized_length": len(clean_text),
                "depth_artifact": f"taskA_LR_depth{depth:03d}.joblib",
                "score_type": "probability",
            },
        )


class SVMPredictor(BasePredictor):
    """Predictor using TF-IDF + LinearSVC pipeline across visibility stages."""

    def __init__(self, visibility: Union[int, str] = 25):
        super().__init__(model_name="svm", visibility=visibility)

    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        t0 = time.perf_counter()
        depth = self._normalize_visibility(visibility if visibility is not None else self.visibility)

        # 1. Deterministic sanitization
        clean_text = sanitize_log_text(log_text)

        # 2. Pipeline inference
        pipeline = load_model_pipeline("svm", depth=depth, task="A")
        raw_pred = pipeline.predict([clean_text])[0]
        decision = float(pipeline.decision_function([clean_text])[0])

        # In LinearSVC binary with classes ['failure', 'success']:
        # decision > 0 is 'success', decision < 0 is 'failure'.
        # Raw sigmoidal mapping for failure probability:
        raw_sigmoid_fail_prob = 1.0 / (1.0 + math.exp(min(max(decision, -20.0), 20.0)))

        # 3. Evidence-aware calibration & Checkpoint refinement
        evidence = LogEvidenceAnalyzer.analyze(log_text)
        is_sparse = evidence.is_sparse or len(clean_text.splitlines()) < 20
        base_calibrated_prob, raw_label = calibrate_model_probability(
            raw_prob=raw_sigmoid_fail_prob,
            evidence=evidence,
            is_sparse_or_padding=is_sparse,
            depth=depth,
            model_name="svm",
        )
        calibrated_prob, checkpoint_adj = apply_checkpoint_calibration_adjustment(
            base_calibrated_prob=base_calibrated_prob,
            depth=depth,
            raw_prob=raw_sigmoid_fail_prob,
            evidence=evidence,
            model_name="svm",
        )

        if calibrated_prob >= 0.50 and not evidence.has_success_evidence:
            predicted_label = "failure"
        elif calibrated_prob < 0.50 and not evidence.has_failure_evidence:
            predicted_label = "success"
        else:
            predicted_label = raw_label

        latency_ms = (time.perf_counter() - t0) * 1000

        return PredictionResult(
            failure_probability=calibrated_prob,
            predicted_label=predicted_label,
            model_name="svm",
            visibility_stage=f"{depth}%",
            decision_score=decision,
            confidence=abs(decision),
            metadata={
                "raw_failure_probability": round(raw_sigmoid_fail_prob, 4),
                "raw_decision_score": round(decision, 4),
                "raw_predicted_label": str(raw_pred),
                "base_calibrated_failure_probability": round(base_calibrated_prob, 4),
                "checkpoint_adjustment": checkpoint_adj,
                "calibrated_failure_probability": calibrated_prob,
                "calibration_applied": True,
                "calibration_method": "evidence_aware_sparsity_calibration",
                "calibration_type": "evidence_adjusted_risk_heuristic",
                "evidence_score": round(evidence.evidence_score, 4),
                "evidence_indicators": evidence.failure_indicators if evidence.has_failure_evidence else evidence.success_indicators,
                "evidence_report": evidence.to_dict(),
                "is_low_evidence": is_sparse,
                "inference_latency_ms": round(latency_ms, 2),
                "sanitized_length": len(clean_text),
                "depth_artifact": f"taskA_SVM_depth{depth:03d}.joblib",
                "loss": "hinge",
                "score_type": "uncalibrated_sigmoid_risk_score",
                "is_calibrated": False,
            },
        )


class ModernBERTPredictor(BasePredictor):
    """Stub adapter for ModernBERT model pending arrival of weights ZIP from teammates."""

    def __init__(self, visibility: Union[int, str] = 25):
        super().__init__(model_name="modernbert", visibility=visibility)

    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        raise NotImplementedError(
            "ModernBERT weights are currently pending arrival from teammate (Aadarsh Koushik). "
            "Please drop the weights ZIP package into models/modernbert/ to enable live inference. "
            "In the interim, use 'logistic_regression' or 'svm'."
        )


class BiLSTMPredictor(BasePredictor):
    """Adapter for Aayush Jha's two-stage BiLSTM failure prediction and 5-fold diagnosis pipeline."""

    def __init__(self, visibility: Union[int, str] = 100):
        super().__init__(model_name="bilstm", visibility=visibility)

    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        depth = self._normalize_visibility(visibility if visibility is not None else self.visibility)
        from src.prediction.bilstm_inference import predict_bilstm
        res = predict_bilstm(log_text=log_text, visibility=depth)
        meta = dict(res)
        meta["raw_failure_probability"] = res.get("raw_task_a_probability", res.get("failure_probability"))
        meta["base_calibrated_failure_probability"] = res.get("base_calibrated_failure_probability", res.get("failure_probability"))
        meta["checkpoint_adjustment"] = res.get("checkpoint_adjustment", 0.0)
        meta["calibrated_failure_probability"] = res.get("failure_probability")
        return PredictionResult(
            failure_probability=res["failure_probability"],
            predicted_label=res["predicted_outcome"],
            model_name="bilstm",
            visibility_stage=f"{depth}%",
            decision_score=res.get("task_a_probability"),
            confidence=res.get("ensemble_confidence"),
            predicted_error_class=res.get("predicted_error_class"),
            metadata=meta,
        )


class BiLSTM2Predictor(BasePredictor):
    """Adapter for BiLSTM v2 (Retrained package) failure prediction and 5-fold diagnosis pipeline."""

    def __init__(self, visibility: Union[int, str] = 100):
        super().__init__(model_name="bilstm2", visibility=visibility)

    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        depth = self._normalize_visibility(visibility if visibility is not None else self.visibility)
        from src.prediction.bilstm2_inference import predict_bilstm2
        res = predict_bilstm2(log_text=log_text, visibility=depth)
        meta = dict(res)
        meta["raw_failure_probability"] = res.get("raw_task_a_probability", res.get("failure_probability"))
        meta["base_calibrated_failure_probability"] = res.get("base_calibrated_failure_probability", res.get("failure_probability"))
        meta["checkpoint_adjustment"] = res.get("checkpoint_adjustment", 0.0)
        meta["calibrated_failure_probability"] = res.get("failure_probability")
        meta["model_equivalence_note"] = "BiLSTM v1 and v2 share identical checkpoint weights (task_a_champion.pt SHA256: 447ae743...)"
        return PredictionResult(
            failure_probability=res["failure_probability"],
            predicted_label=res["predicted_outcome"],
            model_name="bilstm2",
            visibility_stage=f"{depth}%",
            decision_score=res.get("task_a_probability"),
            confidence=res.get("ensemble_confidence"),
            predicted_error_class=res.get("predicted_error_class"),
            metadata=meta,
        )


def get_predictor(model_name: str = "logistic_regression", visibility: Union[int, str] = 25) -> BasePredictor:
    """
    Factory function to instantiate the requested failure predictor.

    Parameters
    ----------
    model_name : str
        'logistic_regression' (or 'lr'), 'svm', 'modernbert', 'bilstm', 'bilstm2'.
    visibility : int or str
        Default visibility stage (25, 50, 75, 100).
    """
    normalized = model_name.lower().strip()
    if normalized in ("lr", "logistic_regression", "logistic"):
        return LogisticRegressionPredictor(visibility=visibility)
    elif normalized in ("svm", "linearsvc", "linear_svm"):
        return SVMPredictor(visibility=visibility)
    elif normalized in ("modernbert", "bert"):
        return ModernBERTPredictor(visibility=visibility)
    elif normalized in ("bilstm", "lstm"):
        return BiLSTMPredictor(visibility=visibility)
    elif normalized in ("bilstm2", "bilstm_v2", "bilstmv2"):
        return BiLSTM2Predictor(visibility=visibility)
    else:
        raise ValueError(
            f"Unsupported model: '{model_name}'. Choose from 'logistic_regression', 'svm', 'modernbert', 'bilstm', 'bilstm2'."
        )
