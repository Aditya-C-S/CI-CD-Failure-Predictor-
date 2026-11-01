"""
data_loader.py — Load, validate, and split the dataset with strict leakage prevention.

Key design decisions:
- snapshot_path is the unique row identifier (it encodes family/outcome/run_id/depth).
- The split column in binary_classification.csv and failure_classification.csv is authoritative.
- group_id is obtained by joining via snapshot_path through dataset_index.csv.
- group-level split integrity is asserted; any violation raises an error immediately.
- TF-IDF is never fitted here; this module only provides text and labels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from config import (
    BINARY_CSV, FAILURE_CSV, DATASET_INDEX, SPLIT_CSV,
    DATASET_DIR, SNAPSHOT_DEPTHS,
    SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST,
    TASK_A_LABEL_COL, TASK_B_LABEL_COL,
    LOG_ENCODING,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _melt_dataset_index(di: pd.DataFrame) -> pd.DataFrame:
    """
    Convert dataset_index.csv from wide (one row per run, four snapshot columns)
    to long (one row per snapshot) so we can join on snapshot_path.
    """
    melted = di.melt(
        id_vars=["run_id", "family", "outcome", "failure_type", "group_id", "split"],
        value_vars=["snapshot_pct025", "snapshot_pct050", "snapshot_pct075", "snapshot_pct100"],
        var_name="depth_col",
        value_name="snapshot_path",
    )
    return melted


def _read_snapshot_text(snapshot_path_series: pd.Series, dataset_dir: Path) -> pd.Series:
    """
    Read log text for every snapshot_path entry.
    Returns a Series of strings aligned with the input index.

    Uses the snapshot_path (relative to dataset_dir) to locate the file.
    The path itself is NEVER included in the returned text to prevent
    outcome/family information leaking through the path string.
    """
    texts = []
    for rel_path in snapshot_path_series:
        full_path = dataset_dir / rel_path
        try:
            text = full_path.read_text(encoding=LOG_ENCODING, errors="replace")
        except FileNotFoundError:
            logger.warning("Snapshot file not found: %s", full_path)
            text = ""
        texts.append(text)
    return pd.Series(texts, index=snapshot_path_series.index)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_and_validate(task: str = "A") -> pd.DataFrame:
    """
    Load the task CSV, attach group_id from dataset_index.csv, and run
    all integrity assertions.

    Parameters
    ----------
    task : "A" for binary classification, "B" for failure-type classification.

    Returns
    -------
    DataFrame with columns:
        snapshot_path, run_id, family, split, snapshot_depth_pct,
        label (task label), group_id

    Raises
    ------
    AssertionError if any integrity check fails.
    ValueError  if an unknown task is requested.
    """
    task = task.upper()
    if task == "A":
        csv_path  = BINARY_CSV
        label_col = TASK_A_LABEL_COL
    elif task == "B":
        csv_path  = FAILURE_CSV
        label_col = TASK_B_LABEL_COL
    else:
        raise ValueError(f"Unknown task: {task!r}. Use 'A' or 'B'.")

    logger.info("Loading %s …", csv_path)
    df = pd.read_csv(csv_path)

    # ------------------------------------------------------------------
    # Check 1: expected columns present
    # ------------------------------------------------------------------
    required_cols = {"run_id", "family", "split", "snapshot_depth_pct",
                     "snapshot_path", label_col}
    missing = required_cols - set(df.columns)
    assert not missing, f"Missing columns in {csv_path.name}: {missing}"

    # ------------------------------------------------------------------
    # Check 2: snapshot_path is the unique key
    # ------------------------------------------------------------------
    assert df["snapshot_path"].nunique() == len(df), \
        "snapshot_path is NOT unique — duplicate rows detected."

    # ------------------------------------------------------------------
    # Check 3: all snapshot depths are expected
    # ------------------------------------------------------------------
    actual_depths = set(df["snapshot_depth_pct"].unique())
    expected_depths = set(SNAPSHOT_DEPTHS)
    assert actual_depths == expected_depths, \
        f"Unexpected depth values: {actual_depths} (expected {expected_depths})"

    # ------------------------------------------------------------------
    # Check 4: all splits are valid
    # ------------------------------------------------------------------
    valid_splits = {SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST}
    actual_splits = set(df["split"].unique())
    assert actual_splits <= valid_splits, \
        f"Unexpected split values: {actual_splits - valid_splits}"

    # ------------------------------------------------------------------
    # Check 5: join group_id from dataset_index.csv via snapshot_path
    # ------------------------------------------------------------------
    logger.info("Loading dataset_index.csv and joining group_id …")
    di = pd.read_csv(DATASET_INDEX)
    di_long = _melt_dataset_index(di)

    # Keep only what we need from the melted index
    di_key = di_long[["snapshot_path", "group_id"]].drop_duplicates(subset="snapshot_path")
    assert di_key["snapshot_path"].is_unique, \
        "snapshot_path is not unique in melted dataset_index — schema error."

    n_before = len(df)
    df = df.merge(di_key, on="snapshot_path", how="left")
    n_after = len(df)
    assert n_before == n_after, \
        f"Row count changed during group_id join ({n_before} → {n_after}). Check for duplicates."

    # ------------------------------------------------------------------
    # Check 6: no missing group_id assignments
    # ------------------------------------------------------------------
    n_missing_group = df["group_id"].isna().sum()
    assert n_missing_group == 0, \
        f"{n_missing_group} rows have no group_id — snapshot_path missing from dataset_index."

    # ------------------------------------------------------------------
    # Check 7: no execution group spans multiple splits
    # ------------------------------------------------------------------
    group_splits = df.groupby("group_id")["split"].nunique()
    bad_groups = group_splits[group_splits > 1]
    assert len(bad_groups) == 0, (
        f"{len(bad_groups)} execution groups span multiple splits — data leakage!\n"
        f"Bad groups: {bad_groups.index.tolist()[:5]}"
    )

    # ------------------------------------------------------------------
    # Check 8: all snapshot files actually exist on disk
    # ------------------------------------------------------------------
    missing_files = []
    for rel_path in df["snapshot_path"]:
        if not (DATASET_DIR / rel_path).exists():
            missing_files.append(rel_path)
    if missing_files:
        logger.warning("%d snapshot files are missing from disk: %s …",
                       len(missing_files), missing_files[:3])
        # Do not assert here — warn and continue; evaluation will show zeros.

    # Rename the label column to a standard name for downstream modules
    df = df.rename(columns={label_col: "label"})

    logger.info(
        "Task %s loaded: %d rows | splits: %s | labels: %s",
        task,
        len(df),
        df["split"].value_counts().to_dict(),
        df["label"].value_counts().to_dict(),
    )
    return df


def get_split(df: pd.DataFrame, split: str, depth: int) -> Tuple[pd.Series, pd.Series]:
    """
    Return (texts, labels) for a specific split and snapshot depth.

    Texts are read from disk here (not stored in the DataFrame) to avoid
    keeping all 22 k log files in memory simultaneously.

    Parameters
    ----------
    df    : Full validated DataFrame from load_and_validate().
    split : "train", "val", or "test".
    depth : Snapshot depth percentage (25, 50, 75, or 100).

    Returns
    -------
    texts  : pd.Series of log text strings.
    labels : pd.Series of label strings.
    """
    subset = df[(df["split"] == split) & (df["snapshot_depth_pct"] == depth)].copy()
    if len(subset) == 0:
        raise ValueError(f"No rows found for split={split!r}, depth={depth}%.")

    texts  = _read_snapshot_text(subset["snapshot_path"], DATASET_DIR)
    labels = subset["label"].reset_index(drop=True)
    texts  = texts.reset_index(drop=True)
    return texts, labels


def get_split_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a tidy DataFrame of row counts, unique run counts, unique group counts,
    and class counts for every (split, depth) combination.
    Useful for reporting and sanity checks.
    """
    records = []
    for split in [SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST]:
        for depth in SNAPSHOT_DEPTHS:
            subset = df[(df["split"] == split) & (df["snapshot_depth_pct"] == depth)]
            class_counts = subset["label"].value_counts().to_dict()
            records.append({
                "split":        split,
                "depth_pct":    depth,
                "n_rows":       len(subset),
                "n_unique_runs":  subset["run_id"].nunique(),
                "n_unique_groups": subset["group_id"].nunique(),
                **{f"class_{k}": v for k, v in class_counts.items()},
            })
    return pd.DataFrame(records)
