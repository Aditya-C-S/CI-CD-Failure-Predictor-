# ready_to_train_v2 — Remediated & Sanitized ML Dataset

**Version:** v2.0.0  
**Built:** 2026-10-20T18:37:23Z  
**Split Random Seed:** 20241201  
**Eligible Runs:** 5590 (Total snapshot files: 22360)
**Release Verdict:** READY WITH DOCUMENTED LIMITATIONS

---

## 1. Quick Start

All paths in CSV files are relative to this folder (`ready_to_train_v2/`). Load and inspect:

```python
import pandas as pd
from pathlib import Path

DATASET_DIR = Path(__file__).parent  # or path to ready_to_train_v2

# Load Task A (Binary Classification: Success vs Failure)
df_binary = pd.read_csv(DATASET_DIR / "binary_classification.csv")
train_df = df_binary[df_binary["split"] == "train"]

# Read sanitized partial log text
sample_row = train_df.iloc[0]
log_text = (DATASET_DIR / sample_row["snapshot_path"]).read_text(encoding="utf-8")
print(f"Run: {sample_row['run_id']}, Depth: {sample_row['snapshot_depth_pct']}%, Label: {sample_row['label_outcome']}")
```

---

## 2. Directory Layout

```
ready_to_train_v2/
├── README.md                  # This documentation
├── DATA_DICTIONARY.md         # Schema, column descriptions, and join keys
├── CHANGELOG.md               # Detailed v1 vs v2 changelog
├── dataset_manifest.json      # Cryptographic SHA-256 checksums & metadata
├── sanitizer.py               # Self-contained reproducible log sanitizer
├── dataset_index.csv          # Master run-level index (5,590 runs)
├── split_assignments.csv      # Group-level assignments (3,024 execution groups)
├── binary_classification.csv  # Task A dataset (22,360 rows: 5,590 runs x 4 depths)
├── failure_classification.csv # Task B dataset (13,960 rows: 3,490 failure runs x 4 depths)
├── snapshots/                 # Sanitized text prefix snapshots (22,360 files)
│   ├── F1/ [failure, success]
│   ├── F2/ [failure, success]
│   ├── F3/ [failure, success]
│   ├── F4/ [failure, success]
│   ├── F5/ [failure, success]
│   ├── F6/ [failure, success]
│   └── F7/ [failure, success]
├── documentation/             # Reports, audit logs, and training guide
│   ├── stage8_remediation_report.md
│   ├── stage8_independent_release_audit.md
│   └── CI_CD_Model_Training_Guide.txt
└── scripts/                   # Reproducible dataset generation & audit scripts
    ├── generate_ready_to_train_v2.py
    └── audit_ready_to_train_v2.py
```

---

## 3. Tasks and Protocols

### Task A: Early Failure Detection (Binary Classification)
- **File:** `binary_classification.csv`
- **Objective:** Predict `failure` vs `success` from partial log text.
- **Depths:** 25%, 50%, 75% (partial observations) and 100% (full log benchmark).

### Task B: Failure Diagnosis (Multi-Class Classification)
- **File:** `failure_classification.csv`
- **Objective:** Classify the failure category into 1 of 14 raw failure labels.
- **Scope:** Exclusively failure runs (3,490 runs × 4 depths = 13,960 records).

---

## 4. Documented Release Limitations

1. **Validation Coverage for Python Exceptions (L-1):** Validation contains 0 examples of the 8 Python exception classes due to the 2-group structure of F3. Use stratified cross-validation on `train` for tuning.
2. **Line-Based Snapshot Protocol (L-2):** Snapshots are line-count prefixes, not guaranteed pre-failure observation timestamps.
3. **Composite Join Key (L-3):** Join across tables using `snapshot_path` or `(family, outcome, run_id, snapshot_depth_pct)` because `run_id` is repeated across families.
