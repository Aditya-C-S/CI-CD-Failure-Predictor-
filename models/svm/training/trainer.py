"""
trainer.py — TF-IDF + Logistic Regression and TF-IDF + LinearSVC training.

Design:
- Uses scikit-learn Pipeline to couple the TF-IDF vectorizer and classifier,
  making accidental leakage (fitting vectorizer on val/test) structurally impossible.
- Pipeline is fitted on training text only.
- Validation text is transformed (not fitted) by the stored pipeline.
- Hyperparameter search is done by evaluating each grid point on the VALIDATION set.
- Test set is only accessed once, after the best hyperparameters are chosen.

All fitted pipelines are saved as joblib files so you can reload and inspect them.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from config import (
    TFIDF_NGRAM_RANGE, TFIDF_MIN_DF, TFIDF_SUBLINEAR_TF, TFIDF_MAX_FEATURES,
    LR_C_GRID, SVM_C_GRID, CLASS_WEIGHT_OPTIONS,
    RANDOM_SEED,
    TASK_A_PRIMARY_METRIC, TASK_B_PRIMARY_METRIC,
    MODEL_DIR,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline builders
# ---------------------------------------------------------------------------

def _make_tfidf() -> TfidfVectorizer:
    """
    Build a TF-IDF vectorizer with settings from config.
    The vectorizer will be fitted on training text ONLY inside a Pipeline.
    """
    return TfidfVectorizer(
        ngram_range=TFIDF_NGRAM_RANGE,
        min_df=TFIDF_MIN_DF,
        sublinear_tf=TFIDF_SUBLINEAR_TF,
        max_features=TFIDF_MAX_FEATURES,
        # Keep meaningful punctuation/digits for CI log analysis:
        # error codes, version strings, exit codes.
        token_pattern=r"(?u)\b\w+\b",
        # We are NOT applying stop-word removal — CI logs have domain-specific
        # tokens that a generic stop-word list would incorrectly remove.
        stop_words=None,
    )


def make_lr_pipeline(C: float = 1.0, class_weight: Optional[str] = None) -> Pipeline:
    """
    Create a scikit-learn Pipeline: TF-IDF → Logistic Regression.

    Parameters
    ----------
    C            : Regularisation strength (inverse). Larger → less regularisation.
    class_weight : None or "balanced". "balanced" re-weights minority class.
    """
    tfidf = _make_tfidf()
    lr = LogisticRegression(
        C=C,
        class_weight=class_weight,
        solver="saga",          # Sparse-friendly; handles L2 and L1.
        max_iter=1000,
        n_jobs=-1,
        random_state=RANDOM_SEED,
    )
    return Pipeline([("tfidf", tfidf), ("clf", lr)])


def make_svm_pipeline(C: float = 1.0, class_weight: Optional[str] = None) -> Pipeline:
    """
    Create a scikit-learn Pipeline: TF-IDF → LinearSVC.

    IMPORTANT: LinearSVC does NOT produce calibrated probabilities.
    Its decision_function() output is a raw score (distance from boundary),
    NOT a probability. We do NOT wrap it in CalibratedClassifierCV here
    because that would require a held-out calibration set from the training
    data, which adds complexity. PR-AUC for SVM is computed from decision
    scores, which is valid for ranking-based metrics.

    If probabilities are needed (e.g., for ROC-AUC that must match LR),
    pass calibrate=True to train_model().
    """
    tfidf = _make_tfidf()
    svm = LinearSVC(
        C=C,
        class_weight=class_weight,
        max_iter=2000,
        random_state=RANDOM_SEED,
    )
    return Pipeline([("tfidf", tfidf), ("clf", svm)])


# ---------------------------------------------------------------------------
# Model training with validation-set grid search
# ---------------------------------------------------------------------------

def train_model(
    model_type: str,
    train_texts: pd.Series,
    train_labels: pd.Series,
    val_texts: pd.Series,
    val_labels: pd.Series,
    task: str,
    depth: int,
    calibrate_svm: bool = False,
) -> Tuple[Pipeline, Dict[str, Any]]:
    """
    Train one model (LR or SVM) with hyperparameter selection on the validation set.

    Parameters
    ----------
    model_type   : "LR" or "SVM".
    train_texts  : Text Series for training (training split only).
    train_labels : Label Series for training.
    val_texts    : Text Series for validation (NOT used to fit the vectorizer).
    val_labels   : Label Series for validation.
    task         : "A" (binary) or "B" (multi-class).
    depth        : Snapshot depth percentage (25/50/75/100).
    calibrate_svm: If True, wrap LinearSVC in CalibratedClassifierCV using
                   cross-validation on TRAINING data only (no test leakage).

    Returns
    -------
    best_pipeline : Fitted Pipeline with best hyperparameters.
    best_config   : Dict of chosen hyperparameters and validation metric.
    """
    from evaluator import compute_metrics  # Imported here to avoid circular imports

    model_type = model_type.upper()
    if model_type == "LR":
        c_grid = LR_C_GRID
        build_fn = make_lr_pipeline
    elif model_type == "SVM":
        c_grid = SVM_C_GRID
        build_fn = make_svm_pipeline
    else:
        raise ValueError(f"Unknown model_type: {model_type!r}. Use 'LR' or 'SVM'.")

    primary_metric = TASK_A_PRIMARY_METRIC if task.upper() == "A" else TASK_B_PRIMARY_METRIC

    logger.info(
        "Hyperparameter search for %s | Task %s | Depth %d%%", model_type, task, depth
    )

    best_score  = -1.0
    best_config = {}
    best_pipeline = None

    grid_results = []
    for C in c_grid:
        for class_weight in CLASS_WEIGHT_OPTIONS:
            pipeline = build_fn(C=C, class_weight=class_weight)

            # --- FIT on training data only ---
            t0 = time.perf_counter()
            pipeline.fit(train_texts, train_labels)
            train_time = time.perf_counter() - t0

            # If SVM calibration requested, re-wrap after fitting.
            # NOTE: CalibratedClassifierCV on the FITTED LinearSVC uses
            # cross-validation on training data — it does NOT touch val/test.
            if model_type == "SVM" and calibrate_svm:
                # Extract the fitted components and rebuild with calibrated SVM
                tfidf_fitted = pipeline.named_steps["tfidf"]
                svm_fitted   = pipeline.named_steps["clf"]
                # We use the already-transformed training data for calibration
                X_train_tfidf = tfidf_fitted.transform(train_texts)
                cal_svm = CalibratedClassifierCV(svm_fitted, cv=3, method="sigmoid")
                cal_svm.fit(X_train_tfidf, train_labels)
                pipeline = Pipeline([("tfidf", tfidf_fitted), ("clf", cal_svm)])

            # --- EVALUATE on validation data (transform only, never fit) ---
            t1 = time.perf_counter()
            val_preds = pipeline.predict(val_texts)
            infer_time = time.perf_counter() - t1

            # Get decision scores (for AUC metrics)
            val_scores = None
            if hasattr(pipeline.named_steps["clf"], "predict_proba"):
                val_scores = pipeline.predict_proba(val_texts)
            elif hasattr(pipeline.named_steps["clf"], "decision_function"):
                val_scores = pipeline.decision_function(val_texts)

            metrics = compute_metrics(
                task=task,
                y_true=val_labels,
                y_pred=val_preds,
                y_scores=val_scores,
                labels=train_labels.unique().tolist(),
            )

            score = metrics.get(primary_metric, 0.0)
            logger.info(
                "  C=%-6s | class_weight=%-10s | val_%s=%.4f | train_time=%.1fs",
                C, str(class_weight), primary_metric, score, train_time
            )

            grid_results.append({
                "C": C,
                "class_weight": class_weight,
                f"val_{primary_metric}": score,
                "train_time_s": round(train_time, 2),
                "infer_time_s": round(infer_time, 3),
                **{f"val_{k}": v for k, v in metrics.items()},
            })

            if score > best_score:
                best_score    = score
                best_pipeline = pipeline
                best_config   = {
                    "model_type":   model_type,
                    "task":         task,
                    "depth_pct":    depth,
                    "C":            C,
                    "class_weight": class_weight,
                    f"val_{primary_metric}": best_score,
                    "train_time_s": round(train_time, 2),
                    "infer_time_s": round(infer_time, 3),
                    "random_seed":  RANDOM_SEED,
                    "tfidf_ngram_range": str(TFIDF_NGRAM_RANGE),
                    "tfidf_min_df": TFIDF_MIN_DF,
                    "tfidf_sublinear_tf": TFIDF_SUBLINEAR_TF,
                }

    logger.info(
        "Best %s config: C=%s, class_weight=%s, val_%s=%.4f",
        model_type, best_config["C"], best_config["class_weight"],
        primary_metric, best_score,
    )

    best_config["grid_results"] = grid_results
    return best_pipeline, best_config


def save_pipeline(
    pipeline: Pipeline,
    model_type: str,
    task: str,
    depth: int,
    model_dir: Optional[Path] = None,
) -> str:
    """
    Save a fitted pipeline as a joblib file.
    Returns the saved file path as a string.
    """
    dest = model_dir if model_dir is not None else MODEL_DIR
    dest.mkdir(parents=True, exist_ok=True)
    fname = dest / f"task{task}_{model_type}_depth{depth:03d}.joblib"
    joblib.dump(pipeline, fname, compress=3)
    logger.info("Saved pipeline: %s", fname)
    return str(fname)


def load_pipeline(model_type: str, task: str, depth: int) -> Pipeline:
    """Load a previously saved pipeline from disk."""
    fname = MODEL_DIR / f"task{task}_{model_type}_depth{depth:03d}.joblib"
    return joblib.load(fname)
