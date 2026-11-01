# Stage 10I — Teammate Model Reports for Agent Review
## ModernBERT (Aadarsh) and BiLSTM (Aayush)

**Project:** AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis  
**Purpose:** Source-faithful review packet to evaluate candidate models before Stage 11 / RCA integration.

## Instructions for the reviewing agent

- Treat the teammate reports as reported claims, not independently verified results. The user currently has reports only—not ModernBERT/BiLSTM weights, evaluation scripts, or prediction vectors.
- Do not claim to run, reproduce, or audit either model at artifact level unless actual artifacts are available and inspected.
- Clearly label report-derived claims, repository evidence, independently calculated metrics, and unresolved questions.
- Keep Task A (binary success/failure) separate from Task B (14-class failure category).
- Do not compare test, validation, OOF, clean-validation, or locked-test-vault scores as equivalent.
- Check same run IDs, labels, split membership, class balance, visibility horizon, metric definitions, and threshold for fair comparison.
- Do not replace the verified LR baseline solely based on a report's higher headline score.
- Keep model risk predictions distinct from parser evidence and RCA conclusions.
- State synthetic-data transfer limitations. Report scores on synthetic logs do not establish real-world generalization.

## Project and dataset context

Dataset named in reports: `ready_to_train_v2`, 5,590 runs with snapshots at 25%, 50%, 75%, and 100% log visibility.

- **Task A:** binary failure vs success.
- **Task B:** 14 failure categories: 6 infrastructure categories and 8 Python exception categories.

A prior dataset audit identified a validation-support concern: the eight exception classes had no validation examples. It also found 250 training exception runs grouped into one group ID and 250 test exception runs grouped into another. Inspect current split files and group construction; do not assume each report fixed this correctly merely because it says integrity checks passed.

---

# Report A — Aadarsh Koushik: ModernBERT

## Reported setup

- Model: `answerdotai/ModernBERT-base`, fine-tuned from pretrained weights.
- Tasks: Task A binary prediction and Task B 14-class categorization.
- Visibility horizons: 25%, 50%, 75%, 100%.
- The updated report says frozen train/validation/test group splits were used, no group overlap remained, the test distribution matches the canonical split, duplicate checks passed, and evaluation artifacts were updated.
- It says a 25% metric inconsistency was traced to thresholding/rounding/logging, with evaluation now computed from confusion matrices and saved prediction vectors.
- It attributes the earlier 100% performance collapse to a 512-token truncation approach (first 128 + last 382 tokens) and trailing noise; 75% reportedly captures the identifying signature.
- **The user has not supplied the model checkpoint, saved predictions, or evaluation code.**

## Updated report metrics — Task A

| Visibility | Accuracy | Binary F1 | ROC-AUC |
|---|---:|---:|---:|
| 25% | 0.9720 | 0.9720 | 0.9925 |
| 50% | 0.9982 | 0.9982 | 0.9998 |
| 75% | 0.9994 | 0.9994 | 1.0000 |
| 100% | 0.8557 | 0.8557 | 0.8912 |

Confirm whether “Binary F1” is failure-class F1 or macro-F1. Recompute metrics from the predictions and labels if available. Investigate the sharp drop at 100%, including tokenization, truncation, padding, head/tail handling, and whether 100% really means the complete intended log.

## Updated report metrics — Task B

| Visibility | 14-class failure-type macro-F1 |
|---|---:|
| 25% | 0.4583 |
| 50% | 0.5140 |
| 75% | 0.5770 |
| 100% | 0.3504 |

The report says eight rare exception classes have no validation support. Inspect per-class precision/recall/F1, confusion matrices, class support, and the exact evaluation scope. Macro-F1 alone does not show which classes work.

## ModernBERT review checklist

1. Verify exact run IDs, labels, groups, and split manifests.
2. Confirm the claimed canonical test class distribution. An earlier comparison flagged an apparent conflict: earlier ModernBERT materials described 797 failures / 275 successes among 1,072 test samples, whereas the LR baseline evaluation had a different nominal distribution. The updated report says this was resolved—check the evidence rather than assume either version is right.
3. Recompute precision, recall, F1, accuracy, ROC-AUC, and PR-AUC from saved predictions; check class order and threshold.
4. Check duplicates/near-duplicates and synthetic scenario/template leakage across splits.
5. Inspect Task B per-class results, especially all eight exception classes and their validation support.
6. Measure inference latency, memory, model size, hardware needs, and calibration.
7. Do not call this independent reproduction if only the report is available.

---

# Report B — Aayush Jha: BiLSTM

## Reported setup and artifact availability

The user supplied a seven-page `BiLSTM.pdf` final defense report dated 2026-10-23. The user does **not** have the checkpoints, scripts, or complete artifacts listed by the report.

The report claims:
- 16/16 dataset integrity checks passed.
- Canonical run keys and scenario anonymization were applied.
- Token representation was expanded from 512 to 768 tokens: 192-token head + 576-token tail.
- Group-disjoint CV and a locked, air-gapped test vault were used.
- Listed artifacts: `dataset_integrity_proof.md`, `models/task_a_champion.pt`, `models/task_b_fold{0..4}_champion.pt`, `work_data/leakage_evidence.json`, `final_test_results.csv`, and `test_per_class_breakdown.csv`.

## Executive claims

- Task A: anti-cheating gates A1–A4 reportedly passed.
- Task A official validation Macro-F1: 0.9129; clean validation Macro-F1: 0.9978.
- Task B: forensic gates B1–B4 reportedly passed.
- Task B group-disjoint OOF Macro-F1: 0.7494; official validation Macro-F1: 0.9111.
- Gate 5 (group-disjoint Python exceptions) is reported as PASS.
- The report says the OOF performance gap comes from 25%/50% snapshots whose model views are byte-identical across the eight Python exception classes before traceback text appears.

These are different evaluation tracks. Do not treat OOF, official validation, clean validation, and test-vault metrics as interchangeable.

## Locked test-vault results — Task A

The report says no test row was used in training, model selection, calibration, or threshold tuning.

| Visibility | Accuracy | Failure precision | Failure recall | Failure F1 | Macro-F1 | PR-AUC | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|
| 25% | 0.9254 | 0.9088 | 1.0000 | 0.9522 | 0.8910 | 0.9936 | 0.9834 |
| 50% | 0.8750 | 0.8561 | 1.0000 | 0.9225 | 0.8002 | 0.9546 | 0.8717 |
| 75% | 0.9991 | 0.9987 | 1.0000 | 0.9994 | 0.9988 | 1.0000 | 1.0000 |
| 100% | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

Check why accuracy/F1 falls at 50% compared with 25% despite reported failure recall remaining 1.0. Verify same held-out run IDs at each horizon, test-vault isolation, and whether 75%/100% performance is due to template or terminal-signature leakage.

## Locked test-vault results — Task B

The report says there are 3,188 rows total: 797 at each visibility depth.

| Visibility | Rows | Accuracy | Precision | Recall | F1 | Macro-F1 | PR-AUC | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 25% | 797 | 0.6361 | 0.3314 | 0.4286 | 0.3509 | 0.3509 | 0.4975 | 0.9191 |
| 50% | 797 | 0.6662 | 0.4023 | 0.5000 | 0.4214 | 0.4214 | 0.4982 | 0.9275 |
| 75% | 797 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 100% | 797 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

The perfect 75%/100% 14-class result is a major claim requiring artifact-level validation. The report itself says exception categories can be indistinguishable before traceback text appears. Check whether the 14 classes have distinct evidence at 75%, or whether labels are exposed by synthetic templates, scenario markers, or preprocessing shortcuts.

## Other BiLSTM results reported

### Task A validation by horizon

| Visibility | N | Accuracy | Macro-F1 | Failure precision | Failure recall | PR-AUC |
|---|---:|---:|---:|---:|---:|---:|
| 25% | 774 | 0.8941 | 0.8860 | 0.8456 | 1.0000 | 0.9839 |
| 50% | 774 | 0.8256 | 0.8036 | 0.7688 | 1.0000 | 0.8438 |
| 75% | 774 | 0.9483 | 0.9477 | 1.0000 | 0.9109 | 0.9997 |
| 100% | 774 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

The report also gives official validation N=3,096: accuracy 0.9170, macro-F1 0.9129, success precision 0.9644, success recall 0.8331, failure precision 0.8900, failure recall 0.9777. Clean validation N=938 is reported at accuracy 0.9979 and macro-F1 0.9978. Verify how the clean subset was defined and selected; it is not a substitute for a locked test set.

### Task B validation / OOF

- Group-disjoint OOF: N=8,976; accuracy 0.8844; macro-F1 0.7494; weighted-F1 0.8842; PR-AUC 0.8148.
- Official validation: N=1,796; accuracy 0.9165; macro-F1 0.9111; weighted-F1 0.9109; PR-AUC 0.9663.
- A gate table reports a separate 0.6198 figure for group-disjoint Python-exception OOF scope. Reconcile its subset/metric definition with the overall 0.7494.
- The report says Gate 5 was evaluated at 75%/100%, where macro-F1 was 1.000, while pooled OOF is lower due to byte-identical early views for exception classes.

### Counterfactual masking / attribution

The report includes fold-0 validation masking results:
- 75%: base F1 1.0000; header masked (64) F1 1.0000 (drop 0.0000); tail masked (448) F1 0.0769 (drop 0.9231).
- 100%: base F1 1.0000; header masked F1 1.0000 (drop 0.0000); tail masked F1 0.0970 (drop 0.9030).
- Gradient attribution is reported for 240 rows. Example salient tokens include `permission_denied`, `configured`, `Required`, `variable`, `missing`, `exit`, and scenario-variable tokens.

Masking suggests reliance on tail evidence, but does not prove that evidence is valid or that leakage is absent. Inspect token spans and the synthetic log-generation rules.

### Reported data remediation

The report says:
- All F3 exception runs originally shared a monolithic group ID; F6/F5/F7 templates grouped up to 127 runs.
- Canonical key rebuilt as `family__outcome__run_id`, with 5,590 unique runs across train/validation/test.
- Raw groups with more than 10 runs and every F3 run were disaggregated; official split membership reportedly stayed unchanged.
- UTF-8 BOM bytes were double-encoded as `\u00ef\u00bb\u00bf` in 20% of snapshots; normalization removes this and a check asserts it is absent from vocabulary.

Inspect whether disaggregating groups preserves genuine dependency boundaries. Related runs sharing a source template/scenario may still leak across splits even if newly assigned IDs differ.

## BiLSTM review checklist

1. Inspect exact dataset, split manifests, group IDs, architecture, tokenizer, preprocessing, training/evaluation scripts, and integrity-check definitions.
2. Verify all 16 checks; “16/16 passed” is not enough without seeing what each check tests.
3. Inspect group identity at source/run/scenario/template level, not just canonical IDs.
4. Verify 192-head + 576-tail input construction and visibility percentages before tokenization.
5. Recompute all metrics from raw predictions and labels; inspect confusion matrices and per-class metrics.
6. Investigate the abrupt Task B macro-F1 increase from 0.4214 at 50% to 1.0000 at 75%.
7. Verify test-vault isolation and checkpoint/threshold selection.
8. Reconcile OOF, official validation, clean-validation, gate, and test-vault sample counts and metric scopes.
9. Measure inference latency, memory, hardware requirements, model size, calibration, and maintenance burden.
10. Since the user only has the PDF, do not claim checkpoint-level verification.

---

# Fair model selection before Stage 11

## Task A — early failure risk

Prioritize usefulness at 25% and 50% visibility:
- failure recall (missed failures),
- precision / false alarms,
- F1 and macro-F1,
- ROC-AUC and PR-AUC,
- calibration if displaying risk probabilities,
- latency, memory, and CPU/GPU deployment,
- consistency across identical test runs and class distributions.

### Current locally verified reference

Prior Stage 10H reproduced the TF-IDF + Logistic Regression model at 25% on a frozen 1,072-sample test set (797 failures, 275 successes):

- Failure precision: 0.946492
- Failure recall: 0.998745
- Failure F1: 0.971917
- Accuracy: 0.957090
- ROC-AUC: 0.986887
- PR-AUC: 0.991675
- Brier score: 0.038213
- ECE: 0.038282

Model path previously reported:
`Dataset/ml_experiments/outputs/stage10_v2/models/taskA_LR_depth025.joblib`

This is the currently defensible reproducible baseline, not a claim that it is impossible for ModernBERT/BiLSTM to outperform it.

## Task B — category classification

- Compare macro-F1 and per-class precision/recall/F1 over all 14 classes.
- Confirm meaningful training and validation support per class.
- Establish what evidence is actually present at each horizon.
- Distinguish early classification from full-log/post-mortem classification.
- Test transferability to unseen repositories and real CI logs.

Prior known baseline: TF-IDF + Linear SVM at 100% had a reported macro-F1 around 0.7608, but this is full-log/post-mortem classification. Early exception categorization has not been validated robustly because traceback evidence appears late.

## Required agent deliverable

Create `stage10i_model_selection_review.md` containing:

1. Executive recommendation by task and visibility horizon.
2. Inventory of files/artifacts actually inspected.
3. Claim-by-claim table: report claim, supporting evidence, status (verified/report-only/unresolved/contradicted).
4. Fair comparison table separating test, validation, OOF, clean validation, and locked test.
5. Leakage review: duplicate/template/scenario overlap, labels, preprocessing, token visibility, and test isolation.
6. Recomputed metrics if predictions exist; otherwise explicitly say “not independently reproducible from report alone.”
7. Operational comparison: latency, memory, model size, calibration, CPU/GPU, and complexity.
8. Separate Task A and Task B recommendations.
9. Stage 11 readiness: what can be integrated safely now and what must wait.
10. Missing-artifact request list for both teammates.
11. Explicit statement that report-only review is not an artifact-level audit.

## Artifact request checklist

### Aadarsh / ModernBERT
- Checkpoint/weights or accessible artifact location.
- Exact code commit and evaluation script.
- Test run IDs, labels, and predictions/logits at all four horizons.
- Confusion matrices and per-class Task B metrics.
- Split/group manifests and duplicate-check outputs.
- Tokenizer, max length, truncation/padding, and head/tail configuration.
- Threshold and metric definitions.
- Latency/resource measurements.

### Aayush / BiLSTM
- `task_a_champion.pt` and `task_b_fold{0..4}_champion.pt`, or artifact access.
- Training/evaluation scripts and code commit.
- Integrity proof and leakage evidence JSON.
- Locked test run IDs, labels, prediction vectors, per-class breakdown.
- Split/group manifest, canonical key definition, CV fold memberships.
- Tokenizer and 768-token input construction.
- Test-vault isolation and checkpoint/threshold-selection details.
- Latency/resource measurements.

Prediction vectors can help verify reported metrics, even if checkpoints are large. But predictions alone cannot establish that the training and preprocessing were leakage-free; ideally obtain predictions plus code/checkpoints.

## Final caution

ModernBERT and BiLSTM look promising from their reports, particularly at later visibility. The reported metrics are not yet enough to displace the reproduced LR baseline without checking comparable test samples, split integrity, predictions, and early-horizon utility. Keep Stage 11's model interface replaceable. ML risk should not be treated as proof of RCA, and an ML threshold should not be the only condition for running parser/RCA.
