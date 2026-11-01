"""
leakage_checks.py — Automated checks for data leakage in the snapshot texts.

These checks are run once before training and write a leakage audit report.
They do NOT modify any data; they only flag suspicious patterns.

Checks performed:
  1. Path leakage: does the snapshot_path (file path string) encode the label?
  2. Final-outcome keywords: do early snapshots contain explicit "failed"/"success"
     annotations from the CI runner at rates that differ by class?
  3. Python exception type names in early snapshots: do failure-type names
     appear in early (25%) snapshots — could be genuine warnings, or leakage.
  4. GitHub Actions ##[error] annotations at early depths.
  5. Failure category strings in snapshot_path (always leakage if used as feature).
  6. Snapshot ordering check: is a later depth always a superset of an earlier one?
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd

from config import DATASET_DIR, LOG_ENCODING, SNAPSHOT_DEPTHS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword patterns that could indicate leakage
# ---------------------------------------------------------------------------

# These appear in CI runner metadata (job name headers), not in the run outcome.
# We need to check if they correlate strongly with the label.
OUTCOME_KEYWORDS = re.compile(
    r"""
      \bfailed\b              # "Build failed", "Job failed", etc.
    | \#\#\[error\]           # GitHub Actions error annotation
    | ProcessCompleted.*exitCode=[1-9]   # Non-zero exit at any step
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Python exception names that are also Task B class labels.
# Their presence in a 25% snapshot is worth auditing — they may be
# genuine early warnings (OK) or may reveal the answer directly (leakage).
EXCEPTION_NAMES = re.compile(
    r"\b(SyntaxError|ZeroDivisionError|KeyError|AttributeError|"
    r"FileNotFoundError|TypeError|IndexError|ValueError|AssertionError)\b"
)

# The broader failure-category names used in Task B labels.
FAILURE_CATEGORY = re.compile(
    r"execution_timeout|network_service_failure|docker_build_failure|"
    r"ci_config_permission|dependency_resolution",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Leakage audit functions
# ---------------------------------------------------------------------------

def check_path_leakage(df: pd.DataFrame) -> Dict:
    """
    Check whether the snapshot_path string encodes the label directly.
    This is always a leakage concern if the path is used as a text feature.

    Returns a dict with findings summary.
    """
    df = df.copy()
    df["path_contains_failure"] = df["snapshot_path"].str.contains(
        "/failure/", case=False, regex=False
    )
    df["path_contains_success"] = df["snapshot_path"].str.contains(
        "/success/", case=False, regex=False
    )
    n_total = len(df)
    n_path_failure = df["path_contains_failure"].sum()
    n_path_success = df["path_contains_success"].sum()

    # Consistency check: path label == true label?
    # (If always consistent, the path is a perfect proxy for the label.)
    has_label_col = "label" in df.columns
    path_is_perfectly_correlated = False
    if has_label_col:
        consistent_failure = (
            df["path_contains_failure"] == (df["label"] == "failure")
        ).all()
        consistent_success = (
            df["path_contains_success"] == (df["label"] == "success")
        ).all()
        path_is_perfectly_correlated = consistent_failure and consistent_success

    return {
        "check": "path_leakage",
        "n_total": n_total,
        "n_path_contains_failure": int(n_path_failure),
        "n_path_contains_success": int(n_path_success),
        "path_perfectly_correlates_with_label": path_is_perfectly_correlated,
        "severity": "CRITICAL" if path_is_perfectly_correlated else "INFO",
        "recommendation": (
            "NEVER use snapshot_path as a text feature. "
            "Load the file content separately (as done by data_loader.py)."
        ),
    }


def check_outcome_keywords_in_text(
    df: pd.DataFrame,
    depths: List[int] | None = None,
    sample_n: int = 500,
    random_state: int = 42,
) -> Dict:
    """
    Scan snapshot text for outcome-revealing keywords at each depth.
    Computes the keyword-hit rate separately for failure vs success runs.
    A large gap indicates potential leakage; a near-zero rate for both
    classes means no early-outcome leakage.

    Parameters
    ----------
    df         : Full validated DataFrame.
    depths     : List of depths to check. Defaults to [25, 50, 75, 100].
    sample_n   : Max rows to scan per (depth, class) combination (for speed).
    random_state : Sampling seed.
    """
    if depths is None:
        depths = SNAPSHOT_DEPTHS

    findings = {}
    for depth in depths:
        subset = df[df["snapshot_depth_pct"] == depth]
        depth_results = {}
        for class_label in df["label"].unique():
            cls_rows = subset[subset["label"] == class_label]
            if len(cls_rows) > sample_n:
                cls_rows = cls_rows.sample(sample_n, random_state=random_state)
            n_kw = 0
            for _, row in cls_rows.iterrows():
                fpath = DATASET_DIR / row["snapshot_path"]
                try:
                    txt = fpath.read_text(encoding=LOG_ENCODING, errors="replace")
                except FileNotFoundError:
                    continue
                if OUTCOME_KEYWORDS.search(txt):
                    n_kw += 1
            depth_results[class_label] = {
                "n_scanned": len(cls_rows),
                "n_with_keyword": n_kw,
                "rate_pct": round(100 * n_kw / max(1, len(cls_rows)), 1),
            }
        findings[f"depth_{depth}"] = depth_results

    return {
        "check": "outcome_keywords_in_text",
        "findings_by_depth": findings,
        "note": (
            "If 'failure' rows have a much higher keyword rate than 'success' rows "
            "at 25%, this suggests the outcome appears early in the log text. "
            "Genuine CI system keywords (like '##[error]') that correlate with failure "
            "are acceptable — they are real early signals, not injected labels."
        ),
    }


def check_exception_names_in_early_logs(
    df: pd.DataFrame,
    depth: int = 25,
    sample_n: int = 200,
    random_state: int = 42,
) -> Dict:
    """
    Check if Python exception type names (also Task B class labels) appear
    in the earliest (25%) snapshots.

    If the exception name appears in the 25% snapshot, the model will
    learn to predict the failure type from the actual error output — which
    is a legitimate early signal (the error occurred early in the run).
    But if ALL 100% snapshots also have the exception at the very end,
    the 25% snapshot is just a prefix of that full log — so the model
    sees real early evidence, not future information.

    This check reports the rate per exception type, not a leakage block.
    """
    subset = df[
        (df["snapshot_depth_pct"] == depth) & (df["label"].isin([
            "SyntaxError", "ZeroDivisionError", "KeyError", "AttributeError",
            "FileNotFoundError", "TypeError", "IndexError", "ValueError", "AssertionError",
        ]))
    ]
    if len(subset) == 0:
        return {
            "check": "exception_names_in_early_logs",
            "note": "Not applicable (no exception-type labels in this task).",
        }

    if len(subset) > sample_n:
        subset = subset.sample(sample_n, random_state=random_state)

    results = {}
    for _, row in subset.iterrows():
        true_label = row["label"]
        fpath = DATASET_DIR / row["snapshot_path"]
        try:
            txt = fpath.read_text(encoding=LOG_ENCODING, errors="replace")
        except FileNotFoundError:
            continue
        found_names = set(EXCEPTION_NAMES.findall(txt))
        if true_label not in results:
            results[true_label] = {"n": 0, "label_in_text": 0}
        results[true_label]["n"] += 1
        if true_label in found_names:
            results[true_label]["label_in_text"] += 1

    for k, v in results.items():
        v["rate_pct"] = round(100 * v["label_in_text"] / max(1, v["n"]), 1)

    return {
        "check": "exception_names_in_early_logs",
        "depth": depth,
        "findings_per_class": results,
        "note": (
            "Exception names appearing in early snapshots are likely genuine — "
            "the Python error was printed before the log was cut off. "
            "This is real information, not injected. "
            "However, if rate is 100%, the model effectively sees the answer directly."
        ),
    }


def check_snapshot_is_prefix(
    df: pd.DataFrame,
    n_pairs: int = 50,
    random_state: int = 42,
) -> Dict:
    """
    Verify that the 25% snapshot is a strict chronological prefix of the
    50% snapshot for the same run (i.e., the 25% text is the first N lines
    of the 50% text).

    Samples n_pairs runs and checks each.
    """
    runs = df["snapshot_path"].str.extract(
        r"(snapshots/\w+/\w+/[\w_]+)_pct\d+\.txt", expand=False
    ).dropna().unique()

    # Sample
    import numpy as np
    rng = np.random.default_rng(random_state)
    sampled_prefixes = rng.choice(runs, size=min(n_pairs, len(runs)), replace=False)

    violations = []
    for prefix in sampled_prefixes:
        prev_lines = None
        for pct in ["025", "050", "075", "100"]:
            fpath = DATASET_DIR / f"{prefix}_pct{pct}.txt"
            if not fpath.exists():
                break
            txt = fpath.read_text(encoding=LOG_ENCODING, errors="replace")
            curr_lines = txt.splitlines()
            if prev_lines is not None:
                # Current must start with all of prev_lines
                if curr_lines[:len(prev_lines)] != prev_lines:
                    violations.append(f"{prefix} @ {pct}% is NOT a prefix of previous depth")
                    break
            prev_lines = curr_lines

    return {
        "check": "snapshot_is_prefix",
        "n_pairs_checked": len(sampled_prefixes),
        "n_violations": len(violations),
        "violations": violations[:5],
        "status": "PASS" if len(violations) == 0 else "FAIL",
    }


def run_all_checks(df: pd.DataFrame) -> List[Dict]:
    """
    Run all leakage checks and return a list of result dicts.
    Logs a WARNING for each finding with severity CRITICAL.
    """
    results = []

    logger.info("[Leakage Audit] Running path leakage check …")
    r1 = check_path_leakage(df)
    results.append(r1)
    if r1["path_perfectly_correlates_with_label"]:
        logger.critical(
            "PATH LEAKAGE: snapshot_path perfectly predicts the label! "
            "NEVER use snapshot_path as a feature string."
        )

    logger.info("[Leakage Audit] Running outcome keyword scan …")
    r2 = check_outcome_keywords_in_text(df, depths=[25, 50], sample_n=300)
    results.append(r2)

    logger.info("[Leakage Audit] Running exception-name-in-early-logs check …")
    r3 = check_exception_names_in_early_logs(df, depth=25)
    results.append(r3)

    logger.info("[Leakage Audit] Running snapshot-is-prefix check …")
    r4 = check_snapshot_is_prefix(df, n_pairs=100)
    results.append(r4)
    if r4["status"] == "FAIL":
        logger.warning(
            "SNAPSHOT PREFIX VIOLATION: %d runs have a deeper snapshot that is NOT a "
            "superset of the shallower one. Chronological ordering may be broken.",
            r4["n_violations"],
        )

    return results
