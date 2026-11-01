# Data Dictionary — ready_to_train_v2

This document defines every dataset table, column, identifier, target label, and join relationship in `ready_to_train_v2`.

---

## 1. Primary Join Keys and Cardinality

| Key / Column | Description | Scope / Cardinality |
|---|---|---|
| `snapshot_path` | Relative path to partial log text file from dataset root. **Globally Unique Primary Key** across all snapshot tables (22,360 rows). | 1-to-1 with snapshot text |
| `original_log_path` | Relative path to source raw log file in repository. Unique per run (5,590 eligible runs). | 1-to-4 with snapshots |
| `run_id` | Filename stem of original log file. **NOT globally unique** across families (e.g. `run_0001` exists in F1, F2, F4, F5). Must be joined with `family` and `outcome`. | Multi-run across families |
| `group_id` | Execution group identifier. All runs sharing a `group_id` are grouped in the same train/val/test split to prevent leakage. | 3,024 unique groups |
| `split` | Assigned split: `train` (70.16%), `val` (14.28%), or `test` (15.56%). | Fixed partition |

---

## 2. Table Specifications

### 2.1 `dataset_index.csv` (Run-Level Master Index)
- **Row count:** 5,590 rows (1 row per eligible CI/CD workflow run)
- **Columns:**
  - `run_id` (string): Log filename stem.
  - `family` (string): Failure/success family (`F1`–`F7`).
  - `outcome` (string): `failure` or `success`.
  - `failure_type` (string): Raw failure category (one of 14 classes for failure runs, empty for success).
  - `original_log_path` (string): Path to original raw log.
  - `group_id` (string): Unique execution group ID.
  - `split` (string): `train`, `val`, or `test`.
  - `snapshot_pct025` (string): Path to 25% prefix snapshot text file.
  - `snapshot_pct050` (string): Path to 50% prefix snapshot text file.
  - `snapshot_pct075` (string): Path to 75% prefix snapshot text file.
  - `snapshot_pct100` (string): Path to 100% full log text file.
  - `source_provenance` (string): Provenance metadata (`synthetic`).
  - `scenario_id` (string): Fault scenario identifier where applicable.
  - `github_run_id` (string): GitHub Actions workflow run ID where applicable.

### 2.2 `split_assignments.csv` (Execution Group Summary)
- **Row count:** 3,024 rows (1 row per execution group)
- **Columns:**
  - `group_id` (string): Unique execution group identifier.
  - `split` (string): Split partition (`train`, `val`, `test`).
  - `run_count` (integer): Number of runs in this group (1 to 250).
  - `family` (string): Family name.
  - `outcome` (string): `failure` or `success`.
  - `grouping_basis` (string): Reason for grouping (`singleton_run`, `workflow_run_matrix`, `workflow_run_batch`, `template_family`, `scenario_branch`).
  - `split_leakage_risk` (string): Leakage assessment.
  - `github_run_id` (string): GitHub workflow run ID if applicable.
  - `commit_sha` (string): Git commit SHA if applicable.

### 2.3 `binary_classification.csv` (Task A)
- **Row count:** 22,360 rows (5,590 runs × 4 depths)
- **Columns:**
  - `run_id` (string): Log stem identifier.
  - `family` (string): Family name.
  - `split` (string): Split (`train`, `val`, `test`).
  - `snapshot_depth_pct` (integer): Prefix depth (`25`, `50`, `75`, `100`).
  - `snapshot_path` (string): Path to sanitized partial log file.
  - `label_outcome` (string): Target label (`failure` or `success`).

### 2.4 `failure_classification.csv` (Task B)
- **Row count:** 13,960 rows (3,490 failure runs × 4 depths)
- **Columns:**
  - `run_id` (string): Log stem identifier.
  - `family` (string): Family name.
  - `split` (string): Split (`train`, `val`, `test`).
  - `snapshot_depth_pct` (integer): Prefix depth (`25`, `50`, `75`, `100`).
  - `snapshot_path` (string): Path to sanitized partial log file.
  - `label_failure_type` (string): Target label (1 of 14 classes).

---

## 3. Target Label Definitions (Task B — 14 Raw Failure Labels)

| Label | Family | Description |
|---|---|---|
| `AssertionError` | F3 | Pytest assertion failure during test execution. |
| `AttributeError` | F3 | Python AttributeError in application module. |
| `FileNotFoundError` | F3 | Missing file or invalid filesystem path in Python test. |
| `IndexError` | F3 | Sequence index out of range in Python test execution. |
| `KeyError` | F3 | Missing dictionary key in Python application execution. |
| `TypeError` | F3 | Operation or function applied to inappropriate object type. |
| `ValueError` | F3 | Argument received right type but inappropriate value. |
| `ZeroDivisionError` | F3 | Division or modulo by zero in numerical calculation. |
| `ci_config_permission_failure` | F6 | File permission or chmod error during CI execution. |
| `dependency_resolution_failure` | F1, F2 | Pip or package dependency conflict / resolution error. |
| `docker_build_failure` | F5 | Container image build failure in Dockerfile step. |
| `execution_timeout` | F4 | Job exceeded configured execution timeout limit. |
| `network_service_failure` | F7 | External service outage, socket timeout, or connection failure. |
| `syntax_error` | F6 | Python SyntaxError in test or source script. |
