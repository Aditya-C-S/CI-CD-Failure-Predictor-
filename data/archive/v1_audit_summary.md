# Audit Summary — ready_to_train_v1

**Dataset version:** v1.0.0  
**Built:** 2026-10-20T06:11:26Z  
**Split seed:** 20241201  

## 1. Provenance and Integrity

This package was generated strictly from the validated and reconciled dataset records (F1–F7).
The full file audit, schema normalisation specification, and reconciliation decisions are preserved under `dataset_audit/`.
- Original logs and metadata were accessed strictly read-only and remain completely unmodified.
- All snapshots contain only chronological log lines without injected labels or headers.
- All snapshot and CSV checksums are cryptographically validated via SHA-256 in `dataset_manifest.json`.

## 2. Run Eligibility Breakdown

| Category | Count | Status | Description |
|---|---|---|---|
| Eligible Runs | 5590 | Included | Valid, verified log + metadata pairs |
| Unmatched Logs | 2 | Quarantined | `logs/F2/failure/run_0005.log`, `run_0006.log` (no metadata) |
| Invalid File | 1 | Excluded | `logs/F2/failure/test` (2-byte stub) |
| **Total Raw Log Files** | **5593** | | |

## 3. Family Distribution

| Family | Success | Failure | Total Eligible | Train | Val | Test |
|---|---|---|---|---|---|---|
| F1 | 300 | 500 | 800 | 560 | 120 | 120 |
| F2 | 300 | 490 | 790 | 553 | 119 | 118 |
| F3 | 300 | 500 | 800 | 500 | 50 | 250 |
| F4 | 300 | 500 | 800 | 560 | 120 | 120 |
| F5 | 300 | 500 | 800 | 560 | 95 | 145 |
| F6 | 300 | 500 | 800 | 461 | 170 | 169 |
| F7 | 300 | 500 | 800 | 550 | 100 | 150 |

## 4. Train / Validation / Test Splits (Leakage Prevention)

Splits are strictly assigned at the **execution-group level** (3,024 unique groups across 5,590 runs).
Runs originating from the same GitHub workflow matrix execution, Docker template family, or shared-commit scenario are guaranteed to stay within the same split to prevent data leakage.

| Split | Run Count | Percentage |
|---|---|---|
| **train** | 3744 | 66.98% |
| **val** | 774 | 13.85% |
| **test** | 1072 | 19.18% |
| **Total** | **5590** | **100.00%** |

### Grouping & Leakage Notes by Family:
- **F1, F2, F4**: All runs are independent singletons; achieved exact 70.0% / 15.0% / 15.0% splits.
- **F3 (GitHub Actions Matrix)**: All 500 failure records originate from only 2 GitHub workflow runs (250 jobs each). Run `35838723134` (250 jobs) is assigned to `train`, and Run `35839163858` (250 jobs) is assigned to `test`. This held-out test evaluation assesses matrix generalization. F3 success runs (250 + 50) are allocated to `train` (250) and `val` (50).
- **F5 (Docker Build Failures)**: 10 template families (D1–D10, 50 runs each). 7 families assigned to `train` (350), 1 to `val` (50), 2 to `test` (100).
- **F6 (Fault Injection Scenarios)**: 4 fault scenarios (124–127 runs each). 2 scenarios assigned to `train` (251), 1 to `val` (125), 1 to `test` (124).
- **F7 (Network / Timeout Batch Runs)**: 10 failure runs (50 jobs each) split 7 train (350) / 1 val (50) / 2 test (100). 6 success runs (50 jobs each) split 4 train (200) / 1 val (50) / 1 test (50).

## 5. Failure Type Distribution (Task B)

| Failure Type | Category Count | Families |
|---|---|---|
| AssertionError | 61 | F1–F7 |
| AttributeError | 66 | F1–F7 |
| FileNotFoundError | 63 | F1–F7 |
| IndexError | 56 | F1–F7 |
| KeyError | 70 | F1–F7 |
| TypeError | 58 | F1–F7 |
| ValueError | 59 | F1–F7 |
| ZeroDivisionError | 67 | F1–F7 |
| ci_config_permission_failure | 500 | F1–F7 |
| dependency_resolution_failure | 490 | F1–F7 |
| docker_build_failure | 500 | F1–F7 |
| execution_timeout | 500 | F1–F7 |
| network_service_failure | 500 | F1–F7 |
| syntax_error | 500 | F1–F7 |

## 6. Snapshot Configurations

Prefix snapshots are generated for all 5,590 eligible runs at depths: **25%, 50%, 75%, and 100%**.
- Total snapshot files: 22,360 files.
- Formula: `lines_to_keep = max(1, math.ceil(total_lines * depth_pct / 100))`.
- Ordering: Strictly chronological order preserved.
