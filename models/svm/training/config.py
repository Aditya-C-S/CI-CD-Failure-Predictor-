"""
config.py — Central configuration for all ML experiments.

All file paths, random seeds, hyperparameter grids, and experiment
settings live here so you only need to change one file to adapt the
experiments to a new machine or dataset version.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Root of the ready_to_train_v1 dataset package (the extracted ZIP).
# Change this if you move the dataset elsewhere.
DATASET_DIR = Path(__file__).parent.parent.parent / "ready_to_train_v1"

# Output directory for all experiment artifacts.
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"

# Sub-directories (created automatically by the experiment runner).
MODEL_DIR   = OUTPUT_DIR / "models"
REPORT_DIR  = OUTPUT_DIR / "reports"
TASK_A_DIR  = OUTPUT_DIR / "task_a_binary"
TASK_B_DIR  = OUTPUT_DIR / "task_b_failure_type"

# Header-sanitized experiment output directory (Stage 7)
OUTPUT_DIR_SANITIZED = OUTPUT_DIR / "header_sanitized"
MODEL_DIR_SANITIZED   = OUTPUT_DIR_SANITIZED / "models"
REPORT_DIR_SANITIZED  = OUTPUT_DIR_SANITIZED / "reports"
TASK_A_DIR_SANITIZED  = OUTPUT_DIR_SANITIZED / "task_a_binary"
TASK_B_DIR_SANITIZED  = OUTPUT_DIR_SANITIZED / "task_b_failure_type"

# ---------------------------------------------------------------------------
# Dataset files (relative to DATASET_DIR)
# ---------------------------------------------------------------------------

BINARY_CSV     = DATASET_DIR / "binary_classification.csv"
FAILURE_CSV    = DATASET_DIR / "failure_classification.csv"
DATASET_INDEX  = DATASET_DIR / "dataset_index.csv"
SPLIT_CSV      = DATASET_DIR / "split_assignments.csv"
MANIFEST_JSON  = DATASET_DIR / "dataset_manifest.json"

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

RANDOM_SEED = 42   # Fixed seed for all models and train/val/test splits.

# ---------------------------------------------------------------------------
# Snapshot depths to evaluate
# ---------------------------------------------------------------------------

SNAPSHOT_DEPTHS = [25, 50, 75, 100]  # percentage values used in the dataset

# ---------------------------------------------------------------------------
# Split labels (as they appear in the CSV)
# ---------------------------------------------------------------------------

SPLIT_TRAIN = "train"
SPLIT_VAL   = "val"
SPLIT_TEST  = "test"

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

TASK_A_NAME      = "binary_failure_prediction"
TASK_A_LABEL_COL = "label_outcome"
TASK_A_POS_LABEL = "failure"   # the "positive" class for precision/recall

TASK_B_NAME      = "failure_type_classification"
TASK_B_LABEL_COL = "label_failure_type"

# ---------------------------------------------------------------------------
# TF-IDF settings (starting configuration)
# ---------------------------------------------------------------------------

TFIDF_NGRAM_RANGE = (1, 2)   # word unigrams + bigrams
TFIDF_MIN_DF      = 3        # ignore tokens appearing in fewer than 3 docs
TFIDF_SUBLINEAR_TF = True    # apply log(1+tf) — helps with long CI logs
TFIDF_MAX_FEATURES = None    # no vocabulary cap by default; set int to limit

# ---------------------------------------------------------------------------
# Hyperparameter search grids (tuned on validation set only)
# ---------------------------------------------------------------------------

# Logistic Regression C values to try (regularisation inverse strength).
LR_C_GRID = [0.01, 0.1, 1.0, 10.0]

# LinearSVC C values to try.
SVM_C_GRID = [0.01, 0.1, 1.0, 10.0]

# Class weight options (compared on validation; "balanced" helps with skew).
CLASS_WEIGHT_OPTIONS = [None, "balanced"]

# ---------------------------------------------------------------------------
# Evaluation settings
# ---------------------------------------------------------------------------

# For binary Task A: primary metric used to pick the best hyperparameters.
TASK_A_PRIMARY_METRIC = "f1_failure"   # F1 of the "failure" class

# For multi-class Task B: primary metric for model selection.
TASK_B_PRIMARY_METRIC = "macro_f1"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

# Maximum number of CV folds for grid search (we use a single train/val
# split instead, so this is only used if you switch to cross-validation).
CV_FOLDS = 5

# Encoding used when reading log text files.
LOG_ENCODING = "utf-8"
