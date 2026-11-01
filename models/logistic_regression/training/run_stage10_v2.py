"""
run_stage10_v2.py — Stage 10: Clean Retraining and Evaluation on CI/CD Dataset v2.

Overview
--------
Trains TF-IDF + Logistic Regression and TF-IDF + LinearSVC on the sanitized
ready_to_train_v2 dataset across all four snapshot depths (25/50/75/100%)
for both tasks:

  Task A — Binary success/failure prediction
  Task B — Failure-type (multi-class) classification

Leakage prevention design:
  - TF-IDF vectorizer is fitted on training text ONLY (inside sklearn Pipeline).
  - Hyperparameter selection uses validation metrics only; test set is never
    accessed until the pipeline configuration is frozen.
  - sanitize_log_text() is applied deterministically and independently to every
    split — it has no state and cannot observe other splits.
  - All v1 artifacts remain completely untouched.

Output: ml_experiments/outputs/stage10_v2/

Usage:
    python src/run_stage10_v2.py                     # full run
    python src/run_stage10_v2.py --smoke-test        # quick subset ~5 min
    python src/run_stage10_v2.py --task A            # Task A only
    python src/run_stage10_v2.py --task B            # Task B only
    python src/run_stage10_v2.py --depths 50 100     # specific depths
    python src/run_stage10_v2.py --models LR         # single model
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import sklearn

# ─── Path setup ──────────────────────────────────────────────────────────────
SRC_DIR = Path(__file__).parent
sys.path.insert(0, str(SRC_DIR))

# ─── Dataset v2 root ─────────────────────────────────────────────────────────
DATASET_DIR_V2 = Path(__file__).parent.parent.parent / "ready_to_train_v2"

# ─── Output roots for Stage 10 ───────────────────────────────────────────────
OUTPUT_DIR_V2  = Path(__file__).parent.parent / "outputs" / "stage10_v2"
MODEL_DIR_V2   = OUTPUT_DIR_V2 / "models"
REPORT_DIR_V2  = OUTPUT_DIR_V2 / "reports"
TASK_A_DIR_V2  = OUTPUT_DIR_V2 / "task_a_binary"
TASK_B_DIR_V2  = OUTPUT_DIR_V2 / "task_b_failure_type"

# ─── Imports from existing shared infrastructure ──────────────────────────────
from config import (
    SNAPSHOT_DEPTHS,
    SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST,
    RANDOM_SEED, TFIDF_NGRAM_RANGE, TFIDF_MIN_DF, TFIDF_SUBLINEAR_TF,
    TASK_A_LABEL_COL, TASK_B_LABEL_COL,
    TASK_A_PRIMARY_METRIC, TASK_B_PRIMARY_METRIC,
    LR_C_GRID, SVM_C_GRID, CLASS_WEIGHT_OPTIONS,
    LOG_ENCODING,
)
from evaluator import compute_metrics, save_results, _make_serializable
from sanitizer import sanitize_log_text, test_sanitization_invariance
from trainer import train_model, save_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_stage10_v2")


# ─────────────────────────────────────────────────────────────────────────────
# V2-specific Data Loading  (mirrors data_loader.py but uses DATASET_DIR_V2)
# ─────────────────────────────────────────────────────────────────────────────

def _melt_dataset_index_v2(di: pd.DataFrame) -> pd.DataFrame:
    """Wide to long on snapshot path columns for v2 dataset_index.csv."""
    return di.melt(
        id_vars=["run_id", "family", "outcome", "failure_type", "group_id", "split"],
        value_vars=[
            "snapshot_pct025", "snapshot_pct050",
            "snapshot_pct075", "snapshot_pct100",
        ],
        var_name="depth_col",
        value_name="snapshot_path",
    )


def load_and_validate_v2(task: str) -> pd.DataFrame:
    """
    Load and validate the v2 task CSV, attach group_id, and assert group
    isolation across splits.

    Returns a DataFrame with columns:
        snapshot_path, run_id, family, split, snapshot_depth_pct, label, group_id
    """
    task = task.upper()
    if task == "A":
        csv_path  = DATASET_DIR_V2 / "binary_classification.csv"
        label_col = TASK_A_LABEL_COL
    elif task == "B":
        csv_path  = DATASET_DIR_V2 / "failure_classification.csv"
        label_col = TASK_B_LABEL_COL
    else:
        raise ValueError(f"Unknown task: {task!r}. Use 'A' or 'B'.")

    logger.info("V2 | Loading %s ...", csv_path)
    df = pd.read_csv(csv_path)

    # Check 1: required columns
    required = {"run_id", "family", "split", "snapshot_depth_pct", "snapshot_path", label_col}
    missing = required - set(df.columns)
    assert not missing, f"Missing columns in {csv_path.name}: {missing}"

    # Check 2: snapshot_path uniqueness
    assert df["snapshot_path"].nunique() == len(df), \
        "snapshot_path is not unique — duplicates detected."

    # Check 3: expected depths
    assert set(df["snapshot_depth_pct"].unique()) == set(SNAPSHOT_DEPTHS), \
        f"Unexpected depths: {set(df['snapshot_depth_pct'].unique())}"

    # Check 4: valid splits
    valid_splits = {SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST}
    assert set(df["split"].unique()) <= valid_splits, \
        f"Unexpected split values: {set(df['split'].unique()) - valid_splits}"

    # Check 5: join group_id via dataset_index.csv
    di = pd.read_csv(DATASET_DIR_V2 / "dataset_index.csv")
    di_long = _melt_dataset_index_v2(di)
    di_key = di_long[["snapshot_path", "group_id"]].drop_duplicates(subset="snapshot_path")
    assert di_key["snapshot_path"].is_unique, \
        "snapshot_path not unique in melted dataset_index — schema error."

    n_before = len(df)
    df = df.merge(di_key, on="snapshot_path", how="left")
    assert len(df) == n_before, \
        f"Row count changed during group_id join ({n_before} -> {len(df)})."

    # Check 6: no missing group_id
    n_missing = df["group_id"].isna().sum()
    assert n_missing == 0, f"{n_missing} rows have no group_id."

    # Check 7: group-level split isolation (no cross-split groups)
    group_splits = df.groupby("group_id")["split"].nunique()
    bad = group_splits[group_splits > 1]
    assert len(bad) == 0, (
        f"{len(bad)} execution groups span multiple splits — data leakage!\n"
        f"Bad groups: {bad.index.tolist()[:5]}"
    )

    # Check 8: snapshot files exist (warning only)
    missing_files = [p for p in df["snapshot_path"] if not (DATASET_DIR_V2 / p).exists()]
    if missing_files:
        logger.warning(
            "%d snapshot files missing from disk: %s ...",
            len(missing_files), missing_files[:3],
        )

    df = df.rename(columns={label_col: "label"})
    logger.info(
        "V2 Task %s: %d rows | splits=%s | labels=%s",
        task, len(df),
        df["split"].value_counts().to_dict(),
        df["label"].value_counts().to_dict(),
    )
    return df


def get_sanitized_split_v2(
    df: pd.DataFrame,
    split: str,
    depth: int,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Load raw snapshot text from v2, apply deterministic sanitization, return
    (sanitized_texts, labels, run_ids).

    The sanitizer is stateless and is applied independently per example —
    it cannot see other splits.
    """
    subset = df[(df["split"] == split) & (df["snapshot_depth_pct"] == depth)].copy()
    if len(subset) == 0:
        raise ValueError(f"No rows for split={split!r}, depth={depth}%.")

    texts: List[str] = []
    for rel_path in subset["snapshot_path"]:
        full_path = DATASET_DIR_V2 / rel_path
        try:
            raw = full_path.read_text(encoding=LOG_ENCODING, errors="replace")
            san = sanitize_log_text(raw)
        except FileNotFoundError:
            logger.warning("File not found: %s", full_path)
            san = ""
        texts.append(san)

    sanitized_series = pd.Series(texts, index=subset.index).reset_index(drop=True)
    labels  = subset["label"].reset_index(drop=True)
    run_ids = subset["run_id"].reset_index(drop=True)
    return sanitized_series, labels, run_ids


# ─────────────────────────────────────────────────────────────────────────────
# Residual Leakage Audit
# ─────────────────────────────────────────────────────────────────────────────

def audit_residual_leakage_v2(df: pd.DataFrame, n_sample: int = 200) -> Dict[str, Any]:
    """
    Scan a random sample of v2 sanitized training snapshots for residual
    generator-specific artefacts that the sanitizer should have removed.

    Returns a dict with per-pattern hit counts and example strings.
    """
    LEAKAGE_PATTERNS: Dict[str, re.Pattern] = {
        "iso_timestamp":    re.compile(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", re.MULTILINE),
        "github_timestamp": re.compile(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", re.MULTILINE),
        "workflow_header":  re.compile(
            r"^##\[(?:group|endgroup|section|error|warning|command)\]", re.MULTILINE),
        "workflow_name_env": re.compile(
            r"\b(?:WORKFLOW|GITHUB_WORKFLOW)\s*=\s*['\"]?\S+['\"]?", re.MULTILINE | re.IGNORECASE),
        "runner_name":      re.compile(
            r"Runner name:.*\S", re.MULTILINE | re.IGNORECASE),
        "github_run_id_val": re.compile(
            r"GITHUB_RUN_ID\s*=\s*\d+", re.MULTILINE | re.IGNORECASE),
    }

    train_df = df[df["split"] == SPLIT_TRAIN]
    sample_df = train_df.sample(
        min(n_sample, len(train_df)), random_state=RANDOM_SEED
    )

    results: Dict[str, Any] = {
        "n_sampled": len(sample_df),
        "n_sample_requested": n_sample,
        "pattern_hits": {},
    }

    for pat_name, pattern in LEAKAGE_PATTERNS.items():
        hits = 0
        examples: List[str] = []
        for rel_path in sample_df["snapshot_path"]:
            full_path = DATASET_DIR_V2 / rel_path
            try:
                raw = full_path.read_text(encoding=LOG_ENCODING, errors="replace")
                sanitized = sanitize_log_text(raw)
                matches = pattern.findall(sanitized)
                if matches:
                    hits += 1
                    if len(examples) < 3:
                        examples.append(str(matches[0])[:120])
            except FileNotFoundError:
                pass
        results["pattern_hits"][pat_name] = {
            "files_with_hits": hits,
            "hit_rate_pct": round(100 * hits / max(len(sample_df), 1), 2),
            "examples": examples,
        }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# V1 vs V2 Comparison
# ─────────────────────────────────────────────────────────────────────────────

def compare_v1_v2(v2_records: List[Dict]) -> Optional[pd.DataFrame]:
    """
    Load the v1 baseline comparison CSV and produce a v1 vs v2 delta table.
    Returns None if the v1 file does not exist.
    """
    v1_path = (
        Path(__file__).parent.parent / "outputs" / "reports" / "model_comparison_all.csv"
    )
    if not v1_path.exists():
        logger.warning(
            "V1 comparison CSV not found at %s — skipping v1 vs v2 delta.", v1_path
        )
        return None

    v1_df = pd.read_csv(v1_path)
    v2_df = pd.DataFrame(v2_records)

    v1_test = v1_df[v1_df["split"] == "test"].copy()
    v2_test = v2_df[v2_df["split"] == "test"].copy()

    merge_keys = ["model", "task", "depth_pct"]
    merged = v2_test.merge(v1_test, on=merge_keys, suffixes=("_v2", "_v1"))

    for col in v1_test.columns:
        if col.startswith("test_") and pd.api.types.is_float_dtype(v1_test[col]):
            metric = col[5:]
            v2c = f"test_{metric}_v2"
            v1c = f"test_{metric}_v1"
            if v2c in merged.columns and v1c in merged.columns:
                merged[f"delta_{metric}"] = merged[v2c] - merged[v1c]

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Main Experiment Suite
# ─────────────────────────────────────────────────────────────────────────────

def run_stage10(
    tasks: List[str],
    depths: List[int],
    model_types: List[str],
    smoke_test: bool = False,
) -> None:
    """
    Full Stage 10 pipeline:
      1. Verify v2 dataset and run sanitization invariance checks.
      2. Load and validate v2 data for each task.
      3. For each (task, model, depth): sanitize -> train on train ->
         hyperparameter search on val -> evaluate on frozen test.
      4. Residual leakage audit on v2 training samples.
      5. V1 vs V2 comparison (if v1 results exist).
      6. Write comprehensive Stage 10 report.
    """
    wall_start = time.perf_counter()

    for d in [MODEL_DIR_V2, REPORT_DIR_V2, TASK_A_DIR_V2, TASK_B_DIR_V2]:
        d.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("STAGE 10 — CI/CD Dataset v2 Clean Retraining")
    logger.info("Dataset : %s", DATASET_DIR_V2)
    logger.info("Output  : %s", OUTPUT_DIR_V2)
    logger.info("Tasks   : %s | Depths: %s | Models: %s", tasks, depths, model_types)
    logger.info("Smoke   : %s", smoke_test)
    logger.info("=" * 70)

    assert DATASET_DIR_V2.exists(), f"V2 dataset not found at {DATASET_DIR_V2}"

    # Sanitization invariance check
    logger.info("Running sanitization invariance tests on v2 snapshots ...")
    invariance_res = test_sanitization_invariance(DATASET_DIR_V2, n_sample_runs=50)
    with open(REPORT_DIR_V2 / "sanitization_invariance_test.json", "w") as f:
        json.dump(invariance_res, f, indent=2)
    inv_status = invariance_res.get("passed") or invariance_res.get("status", "unknown")
    logger.info("Invariance test: status=%s", inv_status)

    all_comparison_rows: List[Dict] = []
    leakage_audits: Dict[str, Any] = {}

    for task in tasks:
        logger.info("=" * 60)
        logger.info("Task %s", task)
        logger.info("=" * 60)

        df = load_and_validate_v2(task)
        all_labels = sorted(df["label"].unique().tolist())
        target_dir = TASK_A_DIR_V2 if task == "A" else TASK_B_DIR_V2

        if smoke_test:
            logger.info("SMOKE TEST: subsampling ...")
            def _sample(sub: pd.DataFrame, n: int) -> pd.DataFrame:
                return (
                    sub.groupby("snapshot_depth_pct", group_keys=False)
                    .apply(lambda x: x.sample(min(n, len(x)), random_state=42),
                           include_groups=False)
                    .reset_index(drop=True)
                )
            train_df  = _sample(df[df["split"] == SPLIT_TRAIN], 100)
            val_df    = _sample(df[df["split"] == SPLIT_VAL],   40)
            test_df   = _sample(df[df["split"] == SPLIT_TEST],  40)
            df = pd.concat([train_df, val_df, test_df], ignore_index=True)

        logger.info("Auditing residual leakage (Task %s) ...", task)
        leakage_audits[f"task_{task}"] = audit_residual_leakage_v2(df, n_sample=200)

        for model_type in model_types:
            for depth in depths:
                logger.info("-" * 55)
                logger.info("V2 | %s | Task %s | Depth %d%%", model_type, task, depth)
                logger.info("-" * 55)

                train_texts, train_labels, train_run_ids = get_sanitized_split_v2(
                    df, SPLIT_TRAIN, depth
                )
                val_texts, val_labels, val_run_ids = get_sanitized_split_v2(
                    df, SPLIT_VAL, depth
                )
                logger.info(
                    "Train: %d | Val: %d | Classes: %s",
                    len(train_texts), len(val_texts), all_labels,
                )

                # Hyperparameter search on val only
                pipeline, best_config = train_model(
                    model_type=model_type,
                    train_texts=train_texts,
                    train_labels=train_labels,
                    val_texts=val_texts,
                    val_labels=val_labels,
                    task=task,
                    depth=depth,
                    calibrate_svm=False,
                )

                save_pipeline(pipeline, model_type, task, depth, model_dir=MODEL_DIR_V2)

                grid_path = target_dir / f"{model_type}_depth{depth:03d}" / "grid_results_v2.json"
                grid_path.parent.mkdir(parents=True, exist_ok=True)
                with open(grid_path, "w") as f:
                    json.dump(_make_serializable(best_config.get("grid_results", [])), f, indent=2)

                # Validation evaluation
                is_proba = hasattr(pipeline.named_steps["clf"], "predict_proba")
                val_preds = pipeline.predict(val_texts)
                val_scores = (
                    pipeline.predict_proba(val_texts) if is_proba
                    else pipeline.decision_function(val_texts)
                    if hasattr(pipeline.named_steps["clf"], "decision_function")
                    else None
                )
                save_results(
                    model_type=model_type, task=task, depth=depth, split="val",
                    y_true=val_labels, y_pred=val_preds, y_scores=val_scores,
                    run_ids=val_run_ids, best_config=best_config,
                    all_labels=all_labels, is_scores_proba=is_proba,
                    out_dir_override=target_dir,
                )

                # Test evaluation (pipeline frozen)
                test_texts, test_labels, test_run_ids = get_sanitized_split_v2(
                    df, SPLIT_TEST, depth
                )
                t0 = time.perf_counter()
                test_preds = pipeline.predict(test_texts)
                test_infer_time = time.perf_counter() - t0

                test_scores = (
                    pipeline.predict_proba(test_texts) if is_proba
                    else pipeline.decision_function(test_texts)
                    if hasattr(pipeline.named_steps["clf"], "decision_function")
                    else None
                )
                save_results(
                    model_type=model_type, task=task, depth=depth, split="test",
                    y_true=test_labels, y_pred=test_preds, y_scores=test_scores,
                    run_ids=test_run_ids, best_config=best_config,
                    all_labels=all_labels, is_scores_proba=is_proba,
                    out_dir_override=target_dir,
                )

                test_metrics = compute_metrics(
                    task=task, y_true=test_labels, y_pred=test_preds,
                    y_scores=test_scores, labels=all_labels,
                )
                val_metrics = compute_metrics(
                    task=task, y_true=val_labels, y_pred=val_preds,
                    y_scores=val_scores, labels=all_labels,
                )
                all_comparison_rows.append({
                    "model":        model_type,
                    "task":         task,
                    "depth_pct":    depth,
                    "split":        "test",
                    "best_C":       best_config["C"],
                    "class_weight": best_config["class_weight"],
                    "n_train":      len(train_texts),
                    "n_val":        len(val_texts),
                    "n_test":       len(test_labels),
                    "infer_time_s": round(test_infer_time, 3),
                    **{f"val_{k}": v for k, v in val_metrics.items()},
                    **{f"test_{k}": v for k, v in test_metrics.items()},
                })

    comp_df = pd.DataFrame(all_comparison_rows)
    comp_df.to_csv(REPORT_DIR_V2 / "model_comparison_v2.csv", index=False)
    logger.info("Saved v2 comparison table.")

    leakage_path = REPORT_DIR_V2 / "residual_leakage_audit_v2.json"
    with open(leakage_path, "w") as f:
        json.dump(_make_serializable(leakage_audits), f, indent=2)
    logger.info("Saved residual leakage audit.")

    delta_df = compare_v1_v2(all_comparison_rows)
    if delta_df is not None:
        delta_df.to_csv(REPORT_DIR_V2 / "v1_vs_v2_delta.csv", index=False)
        logger.info("Saved v1 vs v2 delta.")

    wall_elapsed = time.perf_counter() - wall_start
    _write_stage10_report(
        comp_df=comp_df,
        delta_df=delta_df,
        leakage_audits=leakage_audits,
        invariance_res=invariance_res,
        tasks=tasks,
        depths=depths,
        model_types=model_types,
        smoke_test=smoke_test,
        wall_elapsed=wall_elapsed,
    )

    logger.info("=" * 70)
    logger.info("Stage 10 complete: %.0f s (%.1f min)", wall_elapsed, wall_elapsed / 60)
    logger.info("Outputs: %s", OUTPUT_DIR_V2)
    logger.info("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# Report Writer
# ─────────────────────────────────────────────────────────────────────────────

def _write_stage10_report(
    comp_df: pd.DataFrame,
    delta_df: Optional[pd.DataFrame],
    leakage_audits: Dict,
    invariance_res: Dict,
    tasks: List[str],
    depths: List[int],
    model_types: List[str],
    smoke_test: bool,
    wall_elapsed: float,
) -> None:
    """Write the comprehensive Stage 10 markdown report."""
    report_path = (
        Path(__file__).parent.parent
        / "outputs" / "reports"
        / "stage10_v2_retraining_and_leakage_audit.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    H = lambda n, t: lines.append(f"\n{'#' * n} {t}\n")
    P = lambda t: lines.append(t + "\n")

    H(1, "Stage 10 — v2 Clean Retraining & Leakage Audit Report")
    P(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    P(f"**Dataset:** `ready_to_train_v2`  ")
    P(f"**Tasks:** {tasks}  ")
    P(f"**Depths:** {depths}%  ")
    P(f"**Models:** {model_types}  ")
    P(f"**Smoke test:** {smoke_test}  ")
    P(f"**Runtime:** {wall_elapsed:.0f}s ({wall_elapsed/60:.1f} min)  ")
    P(f"**Python:** {sys.version.split()[0]} | **sklearn:** {sklearn.__version__}")

    H(2, "1. Executive Summary")
    P(
        "Stage 10 trains and evaluates all baselines on the sanitized v2 dataset. "
        "The TF-IDF vectorizer is fitted exclusively on training text. "
        "Hyperparameters are selected on the validation set only; the test set is "
        "accessed once, after all configuration decisions are finalised. "
        "The sanitizer (`sanitize_log_text()`) is applied deterministically and "
        "independently to each split, removing generator-specific artefacts without "
        "introducing cross-split information."
    )

    H(2, "2. V2 Dataset Split Statistics")
    for task in tasks:
        H(3, f"Task {task}")
        csv_path = (
            DATASET_DIR_V2 / "binary_classification.csv"
            if task == "A"
            else DATASET_DIR_V2 / "failure_classification.csv"
        )
        lbl = TASK_A_LABEL_COL if task == "A" else TASK_B_LABEL_COL
        df_tmp = pd.read_csv(csv_path)
        stats = (
            df_tmp.groupby(["split", "snapshot_depth_pct"])
            .agg(n_rows=(lbl, "count"), n_unique_labels=(lbl, "nunique"))
            .reset_index()
        )
        P(stats.to_markdown(index=False))

    H(2, "3. Sanitization Invariance Test")
    inv_pass = invariance_res.get("passed") or invariance_res.get("status", "N/A")
    inv_tested = (
        invariance_res.get("n_tested")
        or invariance_res.get("runs_tested", "N/A")
    )
    inv_failed = (
        invariance_res.get("n_failed")
        or invariance_res.get("determinism_violations", "N/A")
    )
    P(
        f"- **Status:** `{inv_pass}`  \n"
        f"- **Runs tested:** {inv_tested}  \n"
        f"- **Violations:** {inv_failed}  \n"
        "\nPrefix-invariance guarantees that the sanitizer output is independent "
        "of the log file path, so no path-encoded outcome information can leak."
    )

    H(2, "4. Residual Leakage Audit (Post-Sanitization)")
    P(
        "A random sample of 200 v2 training snapshots was read, sanitized, and "
        "scanned for patterns indicating residual generator-specific artefacts."
    )
    for audit_key, audit in leakage_audits.items():
        H(3, f"Audit: {audit_key}")
        rows_a = []
        for pat_name, pat_res in audit.get("pattern_hits", {}).items():
            rows_a.append({
                "Pattern":    pat_name,
                "Files hit":  pat_res.get("files_with_hits", 0),
                "Hit rate %": pat_res.get("hit_rate_pct", 0.0),
                "Example":    str(pat_res.get("examples", [""])[0])[:80]
                              if pat_res.get("examples") else "",
            })
        if rows_a:
            P(pd.DataFrame(rows_a).to_markdown(index=False, floatfmt=".2f"))
        P(f"*(Sampled {audit.get('n_sampled', '?')} training snapshots)*")

    H(2, "5. Task A — Binary Failure Prediction Results")
    task_a = comp_df[comp_df["task"] == "A"]
    if not task_a.empty:
        cols = ["model", "depth_pct", "best_C", "class_weight", "n_train", "n_test"]
        for mc in ["test_f1_failure", "test_precision_failure",
                   "test_recall_failure", "test_macro_f1", "test_pr_auc", "test_roc_auc"]:
            if mc in task_a.columns:
                cols.append(mc)
        P(task_a[cols].sort_values(["model", "depth_pct"]).to_markdown(
            index=False, floatfmt=".4f"
        ))
    else:
        P("*(Task A not run)*")

    H(2, "6. Task B — Failure Type Classification Results")
    task_b = comp_df[comp_df["task"] == "B"]
    if not task_b.empty:
        cols = ["model", "depth_pct", "best_C", "class_weight", "n_train", "n_test"]
        for mc in ["test_macro_f1", "test_weighted_f1"]:
            if mc in task_b.columns:
                cols.append(mc)
        P(task_b[cols].sort_values(["model", "depth_pct"]).to_markdown(
            index=False, floatfmt=".4f"
        ))
        P(
            "\n> **Task B validation note:** Some F3 Python exception sub-types "
            "have zero validation examples due to limited execution groups in the "
            "val split. Hyperparameters were selected on macro-F1 over classes "
            "that appear in the validation set."
        )
    else:
        P("*(Task B not run)*")

    H(2, "7. V1 vs V2 Performance Delta (Test Set)")
    if delta_df is not None and not delta_df.empty:
        delta_cols = ["model", "task", "depth_pct"]
        for key in ["f1_failure", "macro_f1", "pr_auc", "roc_auc", "weighted_f1"]:
            for prefix in [f"test_{key}_v2", f"test_{key}_v1", f"delta_{key}"]:
                if prefix in delta_df.columns:
                    delta_cols.append(prefix)
        sub = delta_df[[c for c in dict.fromkeys(delta_cols) if c in delta_df.columns]]
        P(sub.sort_values(["task", "model", "depth_pct"]).to_markdown(
            index=False, floatfmt=".4f"
        ))
        P(
            "\nNegative delta (v2 - v1) indicates that v1 metrics were inflated by "
            "generator-specific shortcuts removed in v2. A large negative delta "
            "is evidence of label-correlated artefact leakage in v1."
        )
    else:
        P(
            "> V1 comparison table (`outputs/reports/model_comparison_all.csv`) "
            "not found. Run Stage 1-6 experiments to enable this comparison."
        )

    H(2, "8. Key Findings and Interpretation")
    if not comp_df.empty:
        a_rows = comp_df[comp_df["task"] == "A"]
        b_rows = comp_df[comp_df["task"] == "B"]
        if not a_rows.empty and "test_f1_failure" in a_rows.columns:
            best_a = a_rows.loc[a_rows["test_f1_failure"].idxmax()]
            P(
                f"**Task A best test F1 (failure):** `{best_a['test_f1_failure']:.4f}` — "
                f"{best_a['model']} at depth {best_a['depth_pct']}%."
            )
        if not b_rows.empty and "test_macro_f1" in b_rows.columns:
            best_b = b_rows.loc[b_rows["test_macro_f1"].idxmax()]
            P(
                f"**Task B best test macro-F1:** `{best_b['test_macro_f1']:.4f}` — "
                f"{best_b['model']} at depth {best_b['depth_pct']}%."
            )

    P(
        "\n**Sanitization effect:** v2 removes workflow/job names, run IDs, "
        "timestamps, and GITHUB_* variables from every snapshot. A substantial "
        "drop versus v1 confirms those artefacts were label-correlated shortcuts "
        "rather than genuine diagnostic signal.\n"
        "\n**Depth effect:** F1 is expected to increase monotonically with snapshot "
        "depth as more log content becomes available. A flat or non-monotonic "
        "pattern suggests early lines already contain the decisive information."
    )

    H(2, "9. Artefact Index")
    P("All outputs are under `ml_experiments/outputs/stage10_v2/`:\n")
    rows_art = [
        ("models/", "Fitted joblib pipelines for each (task, model, depth)"),
        ("task_a_binary/<MODEL>_depth<D>/",
         "metrics, predictions, confusion matrix, classification report — Task A"),
        ("task_b_failure_type/<MODEL>_depth<D>/", "Same for Task B"),
        ("reports/model_comparison_v2.csv", "Side-by-side result table"),
        ("reports/residual_leakage_audit_v2.json", "Post-sanitization pattern scan"),
        ("reports/sanitization_invariance_test.json", "Prefix invariance check"),
        ("reports/v1_vs_v2_delta.csv", "V1 vs V2 performance delta"),
        ("reports/stage10_v2_retraining_and_leakage_audit.md", "This report"),
    ]
    P("| Path | Contents |")
    P("|------|----------|")
    for path, desc in rows_art:
        P(f"| `{path}` | {desc} |")

    H(2, "10. Reproducibility")
    P(
        f"- **Random seed:** `{RANDOM_SEED}`  \n"
        f"- **TF-IDF ngram_range:** `{TFIDF_NGRAM_RANGE}`  \n"
        f"- **TF-IDF min_df:** `{TFIDF_MIN_DF}`  \n"
        f"- **TF-IDF sublinear_tf:** `{TFIDF_SUBLINEAR_TF}`  \n"
        f"- **LR C grid:** `{LR_C_GRID}`  \n"
        f"- **SVM C grid:** `{SVM_C_GRID}`  \n"
        f"- **Class weight options:** `{CLASS_WEIGHT_OPTIONS}`  \n"
        f"- **Platform:** `{platform.platform()}`  \n"
        f"- **sklearn version:** `{sklearn.__version__}`  \n"
    )
    P(
        "To reproduce exactly:\n"
        "```bash\n"
        "cd ml_experiments\n"
        "python src/run_stage10_v2.py\n"
        "```"
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Stage 10 report written: %s", report_path)


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 10: Clean retraining on CI/CD Dataset v2."
    )
    parser.add_argument(
        "--task", choices=["A", "B"], action="append", default=[],
        help="Task(s) to run (default: both A and B).",
    )
    parser.add_argument(
        "--depths", type=int, nargs="+", default=[25, 50, 75, 100],
        help="Snapshot depths (default: 25 50 75 100).",
    )
    parser.add_argument(
        "--models", choices=["LR", "SVM"], nargs="+", default=["LR", "SVM"],
        help="Model types (default: LR SVM).",
    )
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Run on a small subset for quick validation (~5 min).",
    )
    args = parser.parse_args()

    tasks  = args.task if args.task else ["A", "B"]
    logger.info(
        "Stage 10 | Tasks=%s | Depths=%s | Models=%s | Smoke=%s",
        tasks, args.depths, args.models, args.smoke_test,
    )
    run_stage10(
        tasks=tasks,
        depths=args.depths,
        model_types=args.models,
        smoke_test=args.smoke_test,
    )


if __name__ == "__main__":
    main()
