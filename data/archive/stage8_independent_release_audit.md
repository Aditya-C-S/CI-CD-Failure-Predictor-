# Stage 8 — Independent Release Audit Report: `ready_to_train_v2`

**Project:** AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis  
**Audit Target:** `ready_to_train_v2.zip` and `ready_to_train_v2/`  
**Audit Date:** 2026-10-21  
**Auditor:** Antigravity Autonomous Audit Agent (Independent Verification)  
**Audit Standard:** 13-Point Forensic Release Verification Protocol  
**Final Release Verdict:** **`READY WITH DOCUMENTED LIMITATIONS`**  

---

## 1. Audit Declaration and Methodology

This audit provides an independent, programmatic forensic verification of the remediated dataset package `ready_to_train_v2.zip` and its directory structure `ready_to_train_v2/`.

The audit was executed by running `dataset_audit/audit_ready_to_train_v2.py`. It did not trust internal assertions or script return codes; instead, it re-scanned raw files, recomputed cryptographic checksums, validated relational joins across all CSVs, checked execution-group boundary isolation, evaluated label distributions, verified prefix invariance, and searched for residual target shortcuts.

Every check is strictly classified as **`PASS`**, **`FAIL`**, or **`UNRESOLVED`**.

---

## 2. 13-Check Forensic Audit Results

| Check ID | Verification Area | Target Standard | Measured Result | Verdict |
|---|---|---|---|---|
| **Check 1** | Archive Integrity & Test Extraction | Valid ZIP, 100% CRC-32 match, successful extraction of manifest | Valid ZIP, CRC-32 test passed on all 22,370 archive members, manifest extracted cleanly. Archive size: 50,610,145 bytes. | **PASS** |
| **Check 2** | CSV Schemas & Row Integrity | Expected row counts, 0 nulls in keys/labels, 0 duplicate paths, exactly 14 classes | `dataset_index`: 5,590 rows; `split_assignments`: 3,024 rows; `binary_classification`: 22,360 rows; `failure_classification`: 13,960 rows. 0 nulls. 0 duplicate paths. Exactly 14 classes. | **PASS** |
| **Check 3** | Split Mapping Consistency | 100% agreement between runs and snapshots across all tables | 0 split mismatches between `dataset_index.csv`, `binary_classification.csv`, and `failure_classification.csv`. | **PASS** |
| **Check 4** | Execution Group Isolation | Zero overlap of `group_id` across train, val, and test splits (0% leakage) | Train: 2,115 groups; Val: 454 groups; Test: 455 groups. Cross-split group overlap: **0** (0% group leakage). | **PASS** |
| **Check 5** | Snapshot Label Agreement | 100% agreement of `label_outcome` and `label_failure_type` with parent run | Binary label mismatches: **0**; Failure label mismatches: **0**. | **PASS** |
| **Check 6** | Snapshot Files & Prefix Invariance | All 22,360 snapshot files exist, paths unique, strict chronological prefix invariance | All 22,360 snapshot files exist. 0 missing. 102 sampled runs across all families verified: 0 prefix violations ($25\% \subset 50\% \subset 75\% \subset 100\%$). | **PASS** |
| **Check 7** | Class Distribution Mapping | Full accounting of all 14 failure classes across splits and snapshot depths | All 14 classes mapped across train, val, test at depths 25%, 50%, 75%, 100%. Distribution fully documented. | **PASS** |
| **Check 8** | Failure-Class Validation Support | Adequate validation support for all 14 failure classes | Supported in Val: 6 classes. Unsupported in Val: **8 classes** (all Python exceptions in F3 have 0 validation runs). Documented Limitation L-1. | **FAIL** |
| **Check 9** | Residual Shortcut Scan | Complete absence of runner header exception names and unmasked job names | Scanned 1,118 snapshots across all families, splits, depths. Residual setup header shortcuts: **0**. Unmasked tabular workflow names: **0**. | **PASS** |
| **Check 10** | Confounding & Short Log Analysis | Masked timestamps, quantified short logs (<40 lines) | Raw ISO-8601 timestamps: **0**. All 500 valid F5 Docker failure runs (12–21 lines) retained with disclosure. | **PASS** |
| **Check 11** | Split Assignment Reproducibility | Deterministic split generation with fixed seed `20241201` | Re-ran `assign_splits` with seed `20241201`. Discrepancies with `split_assignments.csv`: **0**. | **PASS** |
| **Check 12** | Cryptographic Manifest Verification | 100% agreement with `dataset_manifest.json` SHA-256 hashes | Recomputed SHA-256 for all 22,369 packaged files. Missing: **0**. Hash mismatches: **0** (verified in 193.7s). | **PASS** |
| **Check 13** | Baseline v1 Preservation | Original v1 archive and extracted files completely unchanged | `ready_to_train_v1.zip` SHA-256 matches expected `563a185061848d6b...`. All 4 v1 CSV hashes match expected. | **PASS** |

---

## 3. Detailed Audit Evidence and Findings

### 3.1 Check 1 & Check 12: Cryptographic Verification and Manifest Integrity
- **Archive File:** `ready_to_train_v2.zip`
- **File Size:** 50,610,145 bytes (48.27 MB)
- **SHA-256:** `8a22bbc0f3383484162f4fa3a681beb6abb2187e6dafca6954b4daedad18f042`
- **Archive Members:** 22,370 entries
- **Manifest File:** `ready_to_train_v2/dataset_manifest.json`
- **Manifest Entries:** 22,369 files (22,360 snapshots, 4 CSV files, 4 markdown files, 1 python module)
- **Exhaustive Hash Check:** 100% of all 22,369 files matched their manifest SHA-256 hashes with zero mismatches and zero missing files.

### 3.2 Check 4: Execution Group Isolation
Execution groups strictly prevent multi-run matrix leakage, template leakage, and scenario leakage:

| Split | Unique Execution Groups | Percentage of Groups | Eligible Runs | Percentage of Runs | Group Overlap |
|---|---|---|---|---|---|
| **train** | 2,115 | 69.94% | 3,744 | 66.98% | — |
| **val** | 454 | 15.01% | 774 | 13.85% | 0 with train |
| **test** | 455 | 15.05% | 1,072 | 19.18% | 0 with train/val |
| **Total** | **3,024** | **100.00%** | **5,590** | **100.00%** | **0 (Zero Leakage)** |

### 3.3 Check 7 & Check 8: Failure Class Distribution and Validation Support

The table below documents the run-level support for each of the 14 raw failure classes across splits (each run yields 4 snapshot depths: 25%, 50%, 75%, 100%):

| Failure Class | Family | Train Runs | Val Runs | Test Runs | Total Runs | Val Support Status |
|---|---|---|---|---|---|---|
| `AssertionError` | F3 | 31 | **0** | 30 | 61 | **UNSUPPORTED (L-1)** |
| `AttributeError` | F3 | 33 | **0** | 33 | 66 | **UNSUPPORTED (L-1)** |
| `FileNotFoundError` | F3 | 34 | **0** | 29 | 63 | **UNSUPPORTED (L-1)** |
| `IndexError` | F3 | 30 | **0** | 26 | 56 | **UNSUPPORTED (L-1)** |
| `KeyError` | F3 | 29 | **0** | 41 | 70 | **UNSUPPORTED (L-1)** |
| `TypeError` | F3 | 27 | **0** | 31 | 58 | **UNSUPPORTED (L-1)** |
| `ValueError` | F3 | 34 | **0** | 25 | 59 | **UNSUPPORTED (L-1)** |
| `ZeroDivisionError` | F3 | 32 | **0** | 35 | 67 | **UNSUPPORTED (L-1)** |
| `ci_config_permission_failure` | F6 | 251 | 125 | 124 | 500 | **SUPPORTED** |
| `dependency_resolution_failure` | F1, F2 | 343 | 74 | 73 | 490 | **SUPPORTED** |
| `docker_build_failure` | F5 | 350 | 50 | 100 | 500 | **SUPPORTED** |
| `execution_timeout` | F4 | 350 | 75 | 75 | 500 | **SUPPORTED** |
| `network_service_failure` | F7 | 350 | 50 | 100 | 500 | **SUPPORTED** |
| `syntax_error` | F6 | 350 | 75 | 75 | 500 | **SUPPORTED** |
| **Total Failure Runs** | | **2,492** | **449** | **549** | **3,490** | **6 Supported / 8 Unsupported** |

### 3.4 Check 9: Residual Shortcut Scan
A forensic scan across 1,118 snapshot files across all 7 families, outcomes, splits, and depths tested for residual synthetic shortcuts:
1. `Complete job name:\s*test-f3\s*\(` (F3 setup header): **0 occurrences** (neutralized to `Complete job name: [JOB_NAME]`).
2. `Complete job name:\s*test-f7\s*\(` (F7 setup header): **0 occurrences** (neutralized to `Complete job name: [JOB_NAME]`).
3. Leading tabular workflow names (`f1-success-test\t`, `dependency-test\t`, `docker-ci\t`): **0 occurrences** (normalized to `ci_job\t`).
4. Raw ISO-8601 timestamps (`2026-08-19T...`, `2026-10-18T...`): **0 occurrences** (masked with `[TIMESTAMP]`).
5. Residual diagnostic evidence check: Confirmed that genuine stack traces, compiler errors, pytest failure messages, and exit codes remain intact in 100% of scanned failure snapshots.

### 3.5 Check 10: Short Logs Analysis
- Analysis of all 500 F5 failure logs confirmed lengths of 12 to 21 lines.
- Because Docker build failures abort execution at the failing Dockerfile instruction, these are valid, complete runs.
- Rejecting `MIN_LINES=40` prevented the improper deletion of 500 legitimate failure runs.
- At 75% depth, snapshots for short Docker runs contain the terminal build failure line; this is documented in the usage rules.

### 3.6 Check 13: Baseline v1 Preservation Verification
Baseline files were verified before and after remediation:
- `ready_to_train_v1.zip`: SHA-256 = `563a185061848d6b7ac66d0772c772984b03f95eff6fbe5744673548b65176fb` (**MATCH**)
- `ready_to_train_v1/dataset_index.csv`: SHA-256 = `bb57ef671aa24c57b932ca814812aa2879aae946d923528e5faf93f0be3e13d9` (**MATCH**)
- `ready_to_train_v1/split_assignments.csv`: SHA-256 = `e49a5c1f3548c1253364a4107916f83bcbdb170400070f073759acb848806f02` (**MATCH**)
- `ready_to_train_v1/binary_classification.csv`: SHA-256 = `59a73c1165e55e5e6b74b6d27bf80e424bd80d9942db8ebc90de3ff029ba8be8` (**MATCH**)
- `ready_to_train_v1/failure_classification.csv`: SHA-256 = `fabae53ea80600675d7127f6cd1428725953db899c3c8df188982373dabeba71` (**MATCH**)

---

## 4. Defect Remediation Summary: Fixed vs Unfixed

| Defect / Concern | Initial Diagnosis | Resolution Status in v2 | Technical Rationale |
|---|---|---|---|
| **D-1: Header Shortcut** | Setup lines announced target class (`AssertionError #11`, etc.) | **FIXED** | Deterministic regex normalizes `Complete job name:` to `[JOB_NAME]`. |
| **D-2: Tabular Job Names** | Workflow names in column 1 encoded outcome | **FIXED** | Normalized leading tab-delimited column to generic `ci_job`. |
| **D-3: Timestamps & Metadata** | Temporal batches and runner versions leaked label | **FIXED** | Masked ISO timestamps, dates, versions, GUIDs, and commit SHAs. |
| **D-4: F3 Validation Coverage** | 0 validation runs for 8 Python exception classes | **UNFIXED (LIMITATION)** | Independent F3 generation blocked by lack of live remote GitHub Actions runner infrastructure. Splitting matrix jobs between train and val is prohibited by group leakage rules. Formally documented as Limitation L-1. |
| **D-5: Short Docker Logs** | F5 logs are 12–21 lines; proposed `MIN_LINES=40` | **RETAINED WITH DISCLOSURE** | F5 runs are valid complete builds. Excluding them would drop 500 valid runs. Disclosed that 75% depth reaches terminal error. |
| **D-6: C Tie-Breaking Grid Search** | Grid search defaulted to C=0.01 on ties | **FIXED IN PROTOCOL** | Protocol mandates secondary tie-breaking via validation log loss (LR) or margin loss / default C=1.0 (SVM). |
| **D-7: Join Key Ambiguity** | `run_id` is not globally unique | **FIXED IN DOCUMENTATION** | Data dictionary defines `snapshot_path` as primary key and documents composite join keys. |

---

## 5. Formal Release Limitations

1. **Release Limitation L-1 (Zero Validation Support for Python Exceptions):**
   - The validation split contains 0 examples of the 8 Python exception classes.
   - *Impact:* Direct validation set evaluation measures performance on 6 failure classes.
   - *Requirement:* All 14-class hyperparameter tuning must use **Stratified 5-Fold Cross-Validation on the `train` split**.
2. **Release Limitation L-2 (Line-Count Prefix Protocol):**
   - Partial snapshots represent line-count prefixes, not guaranteed pre-failure timestamps.
   - *Impact:* At 75% depth, short logs reach terminal error lines.
   - *Requirement:* The 100% snapshot must be evaluated as a full-log classification benchmark.
3. **Release Limitation L-3 (Composite Join Key Requirement):**
   - `run_id` is repeated across families.
   - *Requirement:* All relational joins must use `snapshot_path` or `(family, outcome, run_id, snapshot_depth_pct)`.

---

## 6. Final Release Verdict

Per the governing Stage 8 audit instructions:
- Checks 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, and 13 evaluated to **`PASS`**.
- Check 8 evaluated to **`FAIL`** due to the structural 2-group limitation of F3, which is fully documented as Limitation L-1.
- No critical integrity, leakage, or shortcut checks failed.

**Final Release Verdict:**
# `READY WITH DOCUMENTED LIMITATIONS`

The remediated package `ready_to_train_v2.zip` is approved for immediate project team use under the documented protocol rules.
