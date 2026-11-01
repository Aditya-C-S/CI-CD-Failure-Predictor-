# Changelog — ready_to_train_v2 vs ready_to_train_v1

All notable changes in the `ready_to_train_v2` dataset release are documented below.

## [v2.0.0] — Stage 8 Remediation Release

### 1. Deterministic Log Header & Metadata Sanitization (Fix B-1)
- **Problem in v1:** In F3 and F7 runner setup headers (line 32–33), GitHub Actions announced the full job name including the exact target failure type (e.g. `Complete job name: test-f3 (AssertionError #11)` or `Complete job name: test-f7 (external_service_outage #3)`). Tabular log lines in F1, F2, F4, and F5 encoded outcome information in the leading column (e.g., `f1-success-test` vs `dependency-test`, `f4-success` vs `timeout-test`, `docker-ci` vs `f5-docker-build`). Timestamps and runner versions differed across batches.
- **Remediation in v2:**
  - All occurrences of `Complete job name: ...` normalized to `Complete job name: [JOB_NAME]`.
  - Leading job name column in tab-delimited lines normalized to `ci_job`.
  - Repository references masked with `[REPO]`.
  - ISO-8601 timestamps and calendar dates masked with `[TIMESTAMP]`, `[DATE]`, `[VERSION_ID]`.
  - Runner versions, GUIDs, commit SHAs, and OS/region masked with `[RUNNER_VERSION]`, `[GUID]`, `[COMMIT_SHA]`.
  - Sanitization strictly preserves all diagnostic content, pytest tracebacks, compiler errors, exit codes, and chronological prefix invariance.

### 2. Group Isolation Preserved (Audit Check C-1)
- Preserved 100% of the 3,024 execution group assignments with `SPLIT_SEED = 20241201`.
- Verified zero group overlap across train, val, and test splits (0% leakage).
- All 5,590 eligible runs and 3,490 failure runs retained without arbitrary deletion.

### 3. Investigation of Short Logs (Fix D-1)
- Evaluated the proposed `MIN_LINES=40` rule.
- Finding: F5 Docker failures are 12–21 lines long because Docker build failures abort early upon reaching invalid Dockerfile instructions or missing packages. These are valid, complete executions. Excluding them would drop 500 valid failure examples and distort class proportions.
- Decision: Retained all short logs; documented that 75% depth on short logs encompasses terminal build error lines.

### 4. Snapshot Protocol Clarification (Fix E-1)
- Explicitly documented that snapshots are line-count prefixes (`math.ceil(total_lines * pct / 100)`), not guaranteed pre-failure timestamps or CI step boundaries.
- 100% snapshot defined as a post-hoc full-log classification benchmark.

### 5. Validation-Only Hyperparameter Selection Protocol (Fix F-1)
- Resolved the C-ablation grid search tie-breaking defect identified in Stage 7B and 7C:
  - Vectorizer fitted strictly on train split text.
  - C parameter selected using validation macro-F1, with secondary tie-breaking by validation log loss / margin rather than defaulting to first-in-grid (C=0.01).
  - Test set kept strictly frozen.

### 6. Packaged Documentation & Data Dictionary
- Included `DATA_DICTIONARY.md` defining all schemas and join keys.
- Included `sanitizer.py` inside the package for reproducible downstream verification.
- Re-computed complete cryptographic SHA-256 manifest.
