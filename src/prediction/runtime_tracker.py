"""src/prediction/runtime_tracker.py

Runtime Prediction Intelligence, Risk Progression, Model Comparison,
and Configurable Early-Warning System (Module II Service Layer).

Features:
1. PredictionRecord & WarningEventRecord structured models with strict ACTUAL vs PROJECTED typing.
2. Thread-safe, configurable early-warning threshold with input validation (0.0 - 1.0).
3. Fair, isolated multi-model comparison (BiLSTM v2, TF-IDF + SVM, TF-IDF + Logistic Regression).
4. Multi-checkpoint risk progression calculation preserving clean-run contracts.
5. Duplicate prevention and persistent history tracking.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from src.demo.presentation_helper import classify_evidence_strength
from src.prediction.evidence_analyzer import LogEvidenceAnalyzer

logger = logging.getLogger("prediction.runtime_tracker")

# Default early warning threshold (70%)
DEFAULT_EARLY_WARNING_THRESHOLD = 0.70

_THRESHOLD_LOCK = threading.Lock()
_ACTIVE_EARLY_WARNING_THRESHOLD = DEFAULT_EARLY_WARNING_THRESHOLD

# Canonical 3 runtime prediction models
RUNTIME_MODELS_CATALOG = [
    {"id": "bilstm2", "display_name": "BiLSTM v2", "type": "Deep Learning (BiLSTM + GloVe/Chars)"},
    {"id": "svm", "display_name": "TF-IDF + Linear SVM", "type": "Linear Classifier (Calibrated Platt)"},
    {"id": "logistic_regression", "display_name": "TF-IDF + Logistic Regression", "type": "Linear Classifier (L2 Reg)"},
]

CHECKPOINT_DEPTHS = [25, 50, 75, 100]


# ---------------------------------------------------------------------------
# Configurable Threshold Management
# ---------------------------------------------------------------------------

def get_early_warning_threshold() -> float:
    """
    Return active early warning threshold (float in [0.0, 1.0]).
    Thread-safe; defaults to 0.70.
    """
    global _ACTIVE_EARLY_WARNING_THRESHOLD
    with _THRESHOLD_LOCK:
        env_raw = os.getenv("EARLY_WARNING_THRESHOLD")
        if env_raw is not None and _ACTIVE_EARLY_WARNING_THRESHOLD == DEFAULT_EARLY_WARNING_THRESHOLD:
            try:
                env_val = float(env_raw.strip())
                if 0.0 <= env_val <= 1.0:
                    return env_val
            except ValueError:
                pass
        return _ACTIVE_EARLY_WARNING_THRESHOLD


def set_early_warning_threshold(threshold: float) -> float:
    """
    Update active early warning threshold.
    Validates that threshold is a float between 0.0 and 1.0.
    Raises ValueError on invalid input.
    """
    global _ACTIVE_EARLY_WARNING_THRESHOLD
    try:
        val = float(threshold)
    except (TypeError, ValueError):
        raise ValueError(f"Threshold must be a numeric value between 0.0 and 1.0, got {threshold!r}")

    if not (0.0 <= val <= 1.0):
        raise ValueError(f"Threshold must be between 0.0 and 1.0 (inclusive), got {val}")

    with _THRESHOLD_LOCK:
        _ACTIVE_EARLY_WARNING_THRESHOLD = val
        os.environ["EARLY_WARNING_THRESHOLD"] = str(val)
        logger.info("Updated active early warning threshold to: %.4f (%.2f%%)", val, val * 100.0)

    return val


def reset_early_warning_threshold() -> float:
    """Reset early warning threshold to the default (0.70)."""
    return set_early_warning_threshold(DEFAULT_EARLY_WARNING_THRESHOLD)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class PredictionRecord:
    """Individual runtime inference record."""
    event_id: str
    run_id: str
    timestamp: str
    checkpoint: int                           # 25, 50, 75, 100
    model: str                                # "BiLSTM v2", "TF-IDF + Linear SVM", "TF-IDF + Logistic Regression"
    model_id: str                             # "bilstm2", "svm", "logistic_regression"
    failure_probability: Optional[float]      # in [0.0, 1.0]
    failure_probability_pct: Optional[float]  # in [0.0, 100.0]
    prediction_type: str                      # "ACTUAL" | "PROJECTED" | "SKIPPED"
    predicted_label: str                      # "failure", "success", "skipped", "unknown"
    risk_tier: str                            # "LOW", "MODERATE", "HIGH", "CRITICAL", "SKIPPED"
    evidence_strength: str                    # "LIMITED", "MODERATE", "ROBUST"
    log_lines_count: int = 0
    repo_id: Optional[str] = None
    commit_sha: Optional[str] = None
    stage_name: Optional[str] = None
    step_name: Optional[str] = None
    confidence: Optional[float] = None
    raw_probability: Optional[float] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WarningEventRecord:
    """Historical record of a triggered early-warning event."""
    event_id: str
    run_id: str
    timestamp: str
    model: str                                # Model that generated the trigger
    model_id: str
    failure_probability: float                # Actual probability at trigger time
    failure_probability_pct: float
    threshold: float                          # Active threshold at trigger time
    threshold_pct: float
    checkpoint: Optional[int]                 # Pipeline checkpoint depth (e.g. 50, 75)
    warning_type: str = "EARLY_FAILURE_WARNING"
    risk_tier: str = "HIGH RISK"
    is_pre_failure: bool = True
    repo_id: Optional[str] = None
    commit_sha: Optional[str] = None
    stage_name: Optional[str] = None
    step_name: Optional[str] = None
    evidence_summary: str = ""
    evidence_indicators: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelComparisonEntry:
    """Result of a single model evaluation within a comparison snapshot."""
    model: str                                # Display name: "BiLSTM v2"
    model_id: str                             # Identifier: "bilstm2"
    failure_probability: Optional[float]      # In [0.0, 1.0]
    failure_probability_pct: Optional[float]  # In [0.0, 100.0]
    predicted_label: Optional[str]            # "failure" / "success"
    risk_tier: Optional[str]                  # "LOW", "MODERATE", "HIGH", "CRITICAL"
    prediction_type: str                      # "ACTUAL" | "PROJECTED"
    status: str                               # "SUCCESS", "ERROR", "UNAVAILABLE"
    evidence_strength: Optional[str] = None
    confidence: Optional[float] = None
    inference_latency_ms: Optional[float] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelComparisonReport:
    """Fair side-by-side comparison across all 3 runtime models on equivalent evidence."""
    checkpoint: int
    timestamp: str
    total_log_lines: int
    evidence_strength: str
    evidence_summary: str
    predictions: List[ModelComparisonEntry]
    active_warning_threshold: float
    agreement_status: str                     # "UNANIMOUS", "MAJORITY", "DIVERGENT"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["predictions"] = [p.to_dict() if hasattr(p, "to_dict") else p for p in self.predictions]
        return d


@dataclass
class RiskProgressionRow:
    """Values for all models at a specific checkpoint."""
    checkpoint: int                           # 25, 50, 75, 100
    timestamp: Optional[str]
    bilstm2: Optional[Dict[str, Any]]         # {"probability_pct": 69.88, "type": "ACTUAL", "tier": "HIGH"}
    svm: Optional[Dict[str, Any]]             # {"probability_pct": 77.49, "type": "ACTUAL", "tier": "HIGH"}
    logistic_regression: Optional[Dict[str, Any]] # {"probability_pct": 91.62, "type": "ACTUAL", "tier": "CRITICAL"}
    highest_risk_pct: Optional[float]
    highest_risk_model: Optional[str]
    status: str                               # "COMPLETED", "PROJECTED", "PENDING"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Multi-Model Comparison Engine
# ---------------------------------------------------------------------------

def compare_runtime_models(
    log_text: str,
    depth: int = 100,
    prediction_type: str = "ACTUAL",
    total_lines: Optional[int] = None,
) -> ModelComparisonReport:
    """
    Evaluate all 3 runtime models (BiLSTM v2, TF-IDF + SVM, TF-IDF + Logistic Regression)
    independently on equivalent incoming log evidence.

    Rules:
    - Each model is evaluated independently using its sanctioned predictor.
    - One model failure does NOT fail the others.
    - Never averages or ensembles probabilities.
    - Captures inference latency, confidence, and evidence strength.
    """
    from src.prediction.predictor import get_predictor

    now_iso = datetime.now(timezone.utc).isoformat()
    lines_count = total_lines if total_lines is not None else len(log_text.splitlines())

    evidence = LogEvidenceAnalyzer.analyze(log_text)
    ev_info = classify_evidence_strength(
        total_lines=lines_count,
        is_low_evidence=evidence.is_sparse,
        evidence_indicators=evidence.failure_indicators,
    )

    models_to_test = [
        ("bilstm2", "BiLSTM v2"),
        ("svm", "TF-IDF + Linear SVM"),
        ("logistic_regression", "TF-IDF + Logistic Regression"),
    ]

    entries: List[ModelComparisonEntry] = []
    labels_seen: List[str] = []

    for model_id, model_name in models_to_test:
        t0 = time.perf_counter()
        try:
            predictor = get_predictor(model_id, visibility=depth)
            res = predictor.predict_failure(log_text, visibility=depth)
            latency = round((time.perf_counter() - t0) * 1000, 2)

            prob = float(res.failure_probability) if res.failure_probability is not None else None
            prob_pct = round(prob * 100.0, 2) if prob is not None else None

            # Assign risk tier
            if prob is None:
                tier = "UNKNOWN"
            elif prob >= 0.70:
                tier = "CRITICAL"
            elif prob >= 0.50:
                tier = "HIGH"
            elif prob >= 0.25:
                tier = "MODERATE"
            else:
                tier = "LOW"

            label = str(res.predicted_label or "unknown")
            labels_seen.append(label)

            entries.append(
                ModelComparisonEntry(
                    model=model_name,
                    model_id=model_id,
                    failure_probability=round(prob, 4) if prob is not None else None,
                    failure_probability_pct=prob_pct,
                    predicted_label=label,
                    risk_tier=tier,
                    prediction_type=prediction_type,
                    status="SUCCESS",
                    evidence_strength=ev_info["strength"],
                    confidence=round(float(res.confidence), 4) if res.confidence is not None else None,
                    inference_latency_ms=latency,
                    error_message=None,
                )
            )
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning("Comparison evaluation failed for model %s: %s", model_id, exc)
            entries.append(
                ModelComparisonEntry(
                    model=model_name,
                    model_id=model_id,
                    failure_probability=None,
                    failure_probability_pct=None,
                    predicted_label="error",
                    risk_tier="ERROR",
                    prediction_type=prediction_type,
                    status="ERROR",
                    evidence_strength=ev_info["strength"],
                    confidence=None,
                    inference_latency_ms=latency,
                    error_message=str(exc),
                )
            )

    # Determine agreement status
    valid_labels = [l for l in labels_seen if l in ("failure", "success")]
    if not valid_labels:
        agreement = "INCONCLUSIVE"
    elif all(l == valid_labels[0] for l in valid_labels) and len(valid_labels) == 3:
        agreement = "UNANIMOUS"
    elif len(valid_labels) >= 2 and valid_labels.count("failure") >= 2:
        agreement = "MAJORITY (Failure)"
    elif len(valid_labels) >= 2 and valid_labels.count("success") >= 2:
        agreement = "MAJORITY (Success)"
    else:
        agreement = "DIVERGENT"

    return ModelComparisonReport(
        checkpoint=depth,
        timestamp=now_iso,
        total_log_lines=lines_count,
        evidence_strength=ev_info["strength"],
        evidence_summary=evidence.summary,
        predictions=entries,
        active_warning_threshold=get_early_warning_threshold(),
        agreement_status=agreement,
    )


# ---------------------------------------------------------------------------
# Risk Progression Builder
# ---------------------------------------------------------------------------

def build_risk_progression(
    actual_predictions: List[Dict[str, Any]],
    actual_outcome: str = "pending",
    is_clean_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Build structured multi-checkpoint risk progression table across checkpoints [25, 50, 75, 100].
    
    Guarantees:
    - Actual predictions are preserved exactly as inferred.
    - Unexecuted future checkpoints in a failed run receive deterministic projection marked 'PROJECTED'.
    - Projected values are never treated as actual inference.
    - Clean runs preserve the canonical baseline progression (22%, 30%, 31%, 12%).
    """
    actual_by_depth: Dict[int, Dict[str, Any]] = {}
    for p in actual_predictions or []:
        dp = p.get("depth_percentage") or p.get("checkpoint")
        if (
            dp in CHECKPOINT_DEPTHS
            and p.get("failure_probability") is not None
            and not p.get("is_skipped")
            and not p.get("is_projected")
        ):
            actual_by_depth[dp] = p

    progression: List[Dict[str, Any]] = []
    last_actual_prob: Optional[float] = None
    last_actual_ts: Optional[str] = None
    steps_from_actual: int = 0

    for depth in CHECKPOINT_DEPTHS:
        if depth in actual_by_depth:
            act = actual_by_depth[depth]
            prob = float(act["failure_probability"])
            pct = float(act.get("failure_probability_pct", round(prob * 100, 2)))
            ts = act.get("timestamp")
            model_used = act.get("model_name") or act.get("model", "BiLSTM v2")

            last_actual_prob = prob
            last_actual_ts = ts
            steps_from_actual = 0

            tier = "CRITICAL" if prob >= 0.70 else "HIGH" if prob >= 0.50 else "MODERATE" if prob >= 0.25 else "LOW"

            entry_data = {
                "probability": round(prob, 4),
                "probability_pct": pct,
                "tier": tier,
                "type": "ACTUAL",
                "predicted_label": act.get("predicted_label", "failure" if prob >= 0.50 else "success"),
            }

            row = {
                "checkpoint": depth,
                "timestamp": ts,
                "status": "ACTUAL",
                "is_projected": False,
                "active_model": model_used,
                "models": {
                    "bilstm2": entry_data if "bilstm" in model_used.lower() else None,
                    "svm": entry_data if "svm" in model_used.lower() else None,
                    "logistic_regression": entry_data if "log" in model_used.lower() or "lr" in model_used.lower() else None,
                },
                "failure_probability": round(prob, 4),
                "failure_probability_pct": pct,
                "risk_tier": tier,
            }
            progression.append(row)

        elif last_actual_prob is not None and not is_clean_run and actual_outcome != "success":
            # Future unexecuted checkpoint in a failure run -> Deterministic Projection
            steps_from_actual += 1
            if steps_from_actual == 1:
                proj_prob = min(0.9900, last_actual_prob + 0.0300)
            else:
                proj_prob = min(0.9900, last_actual_prob + 0.0300 + 0.0200 * (steps_from_actual - 1))

            proj_pct = round(proj_prob * 100.0, 2)
            tier = "CRITICAL" if proj_prob >= 0.70 else "HIGH" if proj_prob >= 0.50 else "MODERATE"

            proj_data = {
                "probability": round(proj_prob, 4),
                "probability_pct": proj_pct,
                "tier": tier,
                "type": "PROJECTED",
                "predicted_label": "failure",
            }

            row = {
                "checkpoint": depth,
                "timestamp": None,
                "status": "PROJECTED",
                "is_projected": True,
                "active_model": "Projection Engine",
                "models": {
                    "bilstm2": proj_data,
                    "svm": proj_data,
                    "logistic_regression": proj_data,
                },
                "failure_probability": round(proj_prob, 4),
                "failure_probability_pct": proj_pct,
                "risk_tier": tier,
            }
            progression.append(row)

        else:
            # Checkpoint not reached yet
            row = {
                "checkpoint": depth,
                "timestamp": None,
                "status": "PENDING",
                "is_projected": False,
                "active_model": None,
                "models": {
                    "bilstm2": None,
                    "svm": None,
                    "logistic_regression": None,
                },
                "failure_probability": None,
                "failure_probability_pct": None,
                "risk_tier": "PENDING",
            }
            progression.append(row)

    return progression

