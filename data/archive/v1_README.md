# ready_to_train_v1 — Shared ML Dataset

**Version:** v1.0.0  
**Built:** 2026-10-20T06:11:26Z  
**Split Random Seed:** 20241201  
**Eligible Runs:** 5590 (Total snapshot files: 22360)

---

## 1. Quick Start

All paths in CSV files are relative to this folder (`ready_to_train_v1/`). You can immediately load datasets and read prefix snapshots in Python:

```python
import pandas as pd
from pathlib import Path

DATASET_DIR = Path(__file__).parent  # or path to ready_to_train_v1

# Load Task A (Binary Classification: Success vs Failure)
df_binary = pd.read_csv(DATASET_DIR / "binary_classification.csv")
train_df = df_binary[df_binary["split"] == "train"]

# Read partial log text for a sample record
sample_row = train_df.iloc[0]
log_text = (DATASET_DIR / sample_row["snapshot_path"]).read_text(encoding="utf-8")
print(f"Run: {sample_row['run_id']}, Depth: {sample_row['snapshot_depth_pct']}%, Label: {sample_row['label_outcome']}")
```

---

## 2. Directory Layout

```
ready_to_train_v1/
├── README.md                  # This documentation
├── dataset_index.csv          # Master run-level index (5,590 runs)
├── split_assignments.csv      # Group-level assignments (3,024 execution groups)
├── binary_classification.csv  # Task A dataset (22,360 rows: 5,590 runs x 4 depths)
├── failure_classification.csv # Task B dataset (13,960 rows: 3,490 failure runs x 4 depths)
├── dataset_manifest.json      # Cryptographic SHA-256 checksums & dataset metadata
├── audit_summary.md           # Dataset provenance, split methodology & statistics
└── snapshots/                 # Text prefix snapshots
    ├── F1/
    ├── F2/
    ├── F3/
    ├── F4/
    ├── F5/
    ├── F6/
    └── F7/
```

---

## 3. Tasks and Views

### Task A: Early Failure Detection (Binary Classification)
- **File:** `binary_classification.csv`
- **Objective:** Predict whether a CI/CD build will succeed or fail given an early log prefix.
- **Label column:** `label_outcome` (`success` or `failure`).
- **Features:** Text from `snapshot_path` at prefix depths 25%, 50%, 75%, and 100%.

### Task B: Failure Diagnosis (Multi-Class Classification)
- **File:** `failure_classification.csv`
- **Objective:** Predict the specific root-cause failure category from a failing build's log prefix.
- **Label column:** `label_failure_type` (14 categories, e.g., `syntax_error`, `execution_timeout`, `docker_build_failure`, `ci_config_permission_failure`, etc.).
- **Scope:** Exclusively failure runs (3,490 runs x 4 depths = 13,960 records).

---

## 4. Train / Validation / Test Splits (No Leakage)

Splits are strictly grouped by **Execution Groups** to prevent data leakage:
- **Train:** 3744 runs (66.98%)
- **Validation:** 774 runs (13.85%)
- **Test:** 1072 runs (19.18%)

### Grouping Rules:
1. Matrix workflow runs (F3, F7) are kept intact in a single split.
2. Docker template families (F5) are kept intact in a single split.
3. Fault scenario configurations (F6) are kept intact in a single split.
4. Independent executions (F1, F2, F4, F5 success, F6 success) are stratified across train/val/test.

---

## 5. Excluded and Quarantined Records

| Path | Status | Reason |
|---|---|---|
| `logs/F2/failure/test` | Excluded | 2-byte corrupted stub file |
| `logs/F2/failure/run_0005.log` | Quarantined | Missing metadata record in original dataset |
| `logs/F2/failure/run_0006.log` | Quarantined | Missing metadata record in original dataset |

These records were safely quarantined and are **not** present in `ready_to_train_v1/`.

---

## 6. Reproducibility & Integrity

To verify file integrity:
```python
import hashlib, json, pathlib

pkg = pathlib.Path("ready_to_train_v1")
manifest = json.loads((pkg / "dataset_manifest.json").read_text(encoding="utf-8"))
for rel_path, expected_hash in manifest["checksums"].items():
    file_bytes = (pkg / rel_path).read_bytes()
    assert hashlib.sha256(file_bytes).hexdigest() == expected_hash
print("All SHA-256 checksums verified successfully!")
```
