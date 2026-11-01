"""
evaluator.py — Metrics computation and result export.

Supports both binary (Task A) and multi-class (Task B) classification.

For Task A (binary):
  - Precision, Recall, F1 for the "failure" class (positive class).
  - Macro-F1 across both classes.
  - Confusion matrix.
  - PR-AUC / Average Precision (requires decision scores or probabilities).
  - ROC-AUC (requires decision scores or probabilities).

For Task B (multi-class):
  - Per-class Precision, Recall, F1.
  - Macro-F1 (unweighted average across all classes).
  - Confusion matrix.
  - No ROC-AUC by default (requires one-vs-rest extension with 14 classes).

NOTE: LinearSVC.decision_function() returns raw scores (not probabilities).
  These scores are valid for ranking-based metrics (PR-AUC / ROC-AUC ranking)
  but should NOT be interpreted as calibrated probabilities.
  We report this distinction in the output metadata.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from config import TASK_A_POS_LABEL, TASK_A_DIR, TASK_B_DIR, REPORT_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(
    task: str,
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    y_scores: Optional[np.ndarray] = None,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute evaluation metrics for task A or B.

    Parameters
    ----------
    task     : "A" (binary) or "B" (multi-class).
    y_true   : Ground-truth labels.
    y_pred   : Predicted labels.
    y_scores : Decision scores or probabilities.
               For binary classification: 1D array of scores for the positive class,
               or 2D array of class probabilities.
               For multi-class: 2D array (one column per class).
               Can be None if only class predictions are available.
    labels   : List of all class labels (used to order the confusion matrix).

    Returns
    -------
    Dict of metric_name → value.
    """
    task = task.upper()
    metrics = {}

    if task == "A":
        # ---- Binary classification ----
        pos_label = TASK_A_POS_LABEL   # "failure"

        metrics["precision_failure"] = precision_score(
            y_true, y_pred, pos_label=pos_label, zero_division=0
        )
        metrics["recall_failure"] = recall_score(
            y_true, y_pred, pos_label=pos_label, zero_division=0
        )
        metrics["f1_failure"] = f1_score(
            y_true, y_pred, pos_label=pos_label, zero_division=0
        )
        metrics["macro_f1"] = f1_score(
            y_true, y_pred, average="macro", zero_division=0
        )

        if y_scores is not None:
            # y_scores may be 1D (decision_function) or 2D (predict_proba).
            all_classes = labels if labels is not None else sorted(set(y_true) | set(y_pred))
            if y_scores.ndim == 2:
                # predict_proba: take the column for the positive class.
                if pos_label in all_classes:
                    pos_idx = all_classes.index(pos_label)
                    scores_1d = y_scores[:, pos_idx]
                else:
                    scores_1d = y_scores[:, 1]
            else:
                # 1D decision_function: in scikit-learn binary classification,
                # decision_function returns positive for classes_[1] and negative for classes_[0].
                # If pos_label is classes_[0], positive scores represent the negative class,
                # so scores must be negated to orient toward pos_label.
                if len(all_classes) >= 2 and all_classes[0] == pos_label:
                    scores_1d = -y_scores
                else:
                    scores_1d = y_scores

            # Binary encoding for sklearn metrics
            y_true_bin = (np.array(y_true) == pos_label).astype(int)
            try:
                metrics["pr_auc"] = average_precision_score(y_true_bin, scores_1d)
            except Exception:
                metrics["pr_auc"] = None
            try:
                metrics["roc_auc"] = roc_auc_score(y_true_bin, scores_1d)
            except Exception:
                metrics["roc_auc"] = None

    elif task == "B":
        # ---- Multi-class classification ----
        # Macro-F1 across active classes present in y_true / y_pred
        metrics["macro_f1"] = f1_score(
            y_true, y_pred, average="macro", zero_division=0
        )
        if labels is not None:
            # Macro-F1 across complete taxonomy (e.g. all 14 classes)
            metrics["macro_f1_all_classes"] = f1_score(
                y_true, y_pred, labels=labels, average="macro", zero_division=0
            )
        metrics["weighted_f1"] = f1_score(
            y_true, y_pred, average="weighted", zero_division=0
        )
        # Per-class metrics are stored separately in the report (via classification_report).

    return metrics


def compute_classification_report(
    task: str,
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    labels: Optional[List[str]] = None,
) -> Dict:
    """
    Return a classification report as a dict (includes per-class P/R/F1).
    """
    report_dict = classification_report(
        y_true, y_pred, labels=labels, output_dict=True, zero_division=0
    )
    return report_dict


def compute_confusion_matrix(
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    labels: Optional[List[str]] = None,
) -> Tuple[np.ndarray, List[str]]:
    """
    Return confusion matrix array and the ordered list of class labels.
    """
    if labels is None:
        labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    return cm, labels


# ---------------------------------------------------------------------------
# Result export
# ---------------------------------------------------------------------------

def save_results(
    model_type: str,
    task: str,
    depth: int,
    split: str,                             # "val" or "test"
    y_true: pd.Series | np.ndarray,
    y_pred: np.ndarray,
    y_scores: Optional[np.ndarray],
    run_ids: pd.Series,
    best_config: Dict,
    all_labels: List[str],
    is_scores_proba: bool = False,          # True if y_scores are probabilities
    out_dir_override: Optional[Path] = None, # Optional directory override for separate experiments
) -> None:
    """
    Save all evaluation artifacts for one (model, task, depth, split) combination.

    Artifacts saved:
      - metrics_<split>.json       : all metric values
      - confusion_matrix_<split>.csv : confusion matrix
      - classification_report_<split>.json
      - predictions_<split>.csv    : per-row predictions + scores
    """
    if out_dir_override is not None:
        out_dir = out_dir_override / f"{model_type}_depth{depth:03d}"
    else:
        out_dir = (TASK_A_DIR if task.upper() == "A" else TASK_B_DIR) / f"{model_type}_depth{depth:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Metrics ----
    metrics = compute_metrics(
        task=task,
        y_true=y_true,
        y_pred=y_pred,
        y_scores=y_scores,
        labels=all_labels,
    )
    metrics["split"]         = split
    metrics["model_type"]    = model_type
    metrics["task"]          = task
    metrics["depth_pct"]     = depth
    metrics["n_samples"]     = len(y_true)
    metrics["scores_type"]   = "probability" if is_scores_proba else "decision_score"
    metrics["best_config"]   = {k: v for k, v in best_config.items() if k != "grid_results"}

    with open(out_dir / f"metrics_{split}.json", "w") as f:
        json.dump(_make_serializable(metrics), f, indent=2)

    # ---- Classification report ----
    report = compute_classification_report(task, y_true, y_pred, labels=all_labels)
    with open(out_dir / f"classification_report_{split}.json", "w") as f:
        json.dump(report, f, indent=2)

    # ---- Confusion matrix ----
    cm, labels_ordered = compute_confusion_matrix(y_true, y_pred, labels=all_labels)
    cm_df = pd.DataFrame(cm, index=labels_ordered, columns=labels_ordered)
    cm_df.index.name = "true \\ pred"
    cm_df.to_csv(out_dir / f"confusion_matrix_{split}.csv")

    # ---- Predictions table ----
    pred_df = pd.DataFrame({
        "run_id":        run_ids.values if hasattr(run_ids, "values") else run_ids,
        "depth_pct":     depth,
        "true_label":    np.array(y_true),
        "pred_label":    y_pred,
    })
    if y_scores is not None:
        if y_scores.ndim == 1:
            pred_df["decision_score"] = y_scores
        else:
            for i, label in enumerate(all_labels):
                pred_df[f"score_{label}"] = y_scores[:, i]
    pred_df.to_csv(out_dir / f"predictions_{split}.csv", index=False)

    logger.info(
        "Saved results: %s | Task %s | %s split | depth=%d%% | metrics=%s",
        model_type, task, split, depth,
        {k: round(v, 4) if isinstance(v, float) else v
         for k, v in metrics.items() if isinstance(v, (int, float, str))},
    )


def save_comparison_table(
    task: str,
    records: List[Dict],
    out_dir: Path,
    fname: str = "model_comparison.csv",
) -> None:
    """
    Save a side-by-side comparison of LR vs SVM across all depths and splits.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    df.to_csv(out_dir / fname, index=False)
    logger.info("Saved comparison table: %s/%s", out_dir, fname)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_serializable(obj: Any) -> Any:
    """Recursively convert numpy/Python types to native JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    # IMPORTANT: check bool before int — in Python, bool is a subclass of int
    if isinstance(obj, bool):
        return obj  # bool is natively JSON serializable; return as-is
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj
