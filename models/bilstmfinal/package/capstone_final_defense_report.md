# Capstone Final Defense Report

Generated: 2026-10-29T11:57:48  
Pipeline status: **failed**

## 1. Executive summary

- Dataset verification: **16/16 checks passed**.
- Task A (binary): A1=PASS A2=PASS A3=PASS A4=PASS; official Macro-F1=0.9129, clean Macro-F1=0.9978.
- Task B (14-class): B1=PASS B2=PASS B3=PASS B4=PASS; group-disjoint OOF Macro-F1=0.7494, official val Macro-F1=0.9111; Gate 5 group-disjoint Python exceptions: PASS.

## 2. Dataset remediation

Two root causes were repaired before training.

**A. Monolithic synthetic group ids.** All F3 exception runs shared one
`group_id` (`GRP_F3_FAIL_RUN_35838723134`), and the F6/F5/F7 scenario
templates grouped up to 127 runs each. The raw metadata also reuses
`run_id` between the success and failure execution of a family, so the
literal `family__run_id` key merges 634 distinct executions and crosses
the split boundary for 195 runs. The canonical key is therefore
`family__outcome__run_id` (5,590 unique runs across train/val/test).
Every raw group with more than 10 runs, and every F3 run, is
disaggregated to that key. Official train/val/test membership is
unchanged.

**B. Middle-token truncation.** The previous 64+448 model view cut
tokens 65-350, where test invocations and early step commands live.
The token cache was rebuilt at 192 head + 1344 tail retained tokens and
the model view is 192 + 576 = 768 tokens. Every snapshot shorter than
768 tokens is now seen in full, and long snapshots keep 192 true head
tokens instead of 64.

**C. Scenario-name label leakage.** The synthetic generator named
repositories, branches, pytest functions and even the job step after
the failure family, so a model could classify without reading the
error. Every such identifier is now replaced by a constant
placeholder before tokenization, and check 16 asserts that none of
them survives in the train vocabulary.


Full proof: `dataset_integrity_proof.md`.

## 3. Dataset verification (16 checks)

| Check | Result | Evidence |
|---|---|---|
| 1. Task A official row counts | PASS | train=14976 val=3096 test_rows=4288 |
| 2. Task B official row counts | PASS | train=8976 val=1796 test=3188 |
| 3. Composite run completeness (4 snapshots per run) | PASS | 5590 canonical runs, each 1 metadata row x 4 depths (22360 snapshots); all depth paths present=True |
| 4. Snapshot co-location (global split) | PASS | runs spanning >1 global split: 0 |
| 5. Snapshot co-location (CV folds) | PASS | run keys split across folds: {'task_a': {'keys': 3744, 'split_keys': 0}, 'task_b': {'keys': 2244, 'split_keys': 0}} |
| 6. Global run disjointness | PASS | overlap {'train/val': 0, 'train/test': 0, 'val/test': 0} |
| 7. Global group disjointness | PASS | overlap {'train/val': 0, 'train/test': 0, 'val/test': 0} |
| 8. Task B 5-fold group disjointness (B4) | PASS | overlap=0 in all folds; excluded_rows=0; rows covered exactly once=8976/8976 |
| 9. Task B 14-class fold coverage | PASS | classes=14; all folds cover all classes in both partitions |
| 10. Task B minority Python exception support | PASS | minimum per-class fold-val support=20 (required >= 20) |
| 11. Tokenizer integrity | PASS | vocab=19083; 8 exception tokens distinct and non-UNK; tokenizer artifact unchanged (sha256 c1e8996656cb...) |
| 12. Boilerplate and artifact purge | PASS | BOM=0 ANSI=0 [TIMESTAMP]=0 mojibake-BOM rows=0 |
| 13. Model-view hash consistency (768-token val mask) | PASS | recomputed mask equals saved tensor: {'task_a': {'val_rows': 3096, 'clean_rows': 938, 'matches_recompute': True}, 'task_b': {'val_rows': 1796, 'clean_rows': 378, 'matches_recompute': True}} |
| 14. Taxonomy mapping contract | PASS | 14 granular classes deterministically map to F0-F7; all 8 Python exceptions map to F3 |
| 15. Test vault checksum integrity | PASS | 8 files verified, mismatches=[] |
| 16. Pre-training scenario-name purity | PASS | scenario/leak tokens in train vocabulary: 0; normalizer self-test=pass; placeholders that fired: ['<TEST_FUNC>', '<TEST_FILE>'] |

## 4. Task A - binary predictor (768 tokens)

| Split | N | Accuracy | Macro-F1 | P(success) | R(success) | P(failure) | R(failure) |
|---|---|---|---|---|---|---|---|
| Official val | 3096 | 0.9170 | 0.9129 | 0.9644 | 0.8331 | 0.8900 | 0.9777 |
| Clean val | 938 | 0.9979 | 0.9978 | 0.9982 | 0.9982 | 0.9974 | 0.9974 |

**Per-depth validation**

| Visibility | N | Accuracy | Macro-F1 | P(failure) | R(failure) | PR-AUC | Beats Gate 1 |
|---|---|---|---|---|---|---|---|
| 25% | 774 | 0.8941 | 0.8860 | 0.8456 | 1.0000 | 0.9839 | PASS |
| 50% | 774 | 0.8256 | 0.8036 | 0.7688 | 1.0000 | 0.8438 | PASS |
| 75% | 774 | 0.9483 | 0.9477 | 1.0000 | 0.9109 | 0.9997 | PASS |
| 100% | 774 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | PASS |

**Counterfactual masking (75%/100%)**

| Visibility | Base F1 | Header masked (64) | Header drop | Tail masked (448) | Tail drop |
|---|---|---|---|---|---|
| 75 | 0.9516 | 0.9516 | 0.0000 | 0.3671 | 0.5845 |
| 100 | 1.0000 | 1.0000 | 0.0000 | 0.3671 | 0.6329 |

Horizon trend: early (25/50) F1=0.8448 -> late (75/100) F1=0.9739.

**Gradient attribution top-20**

`permission_denied)`(1.78), `configured."`(0.303), `"Required`(0.23), `variable`(0.207), `;;`(0.168), `fi`(0.148), `missing"`(0.119), `exit`(0.107), `<<SCENARIO>_VAR>`(0.0887), `];`(0.0744), `missing_variable)`(0.0731), `"$<<SCENARIO>_VAR>"`(0.0701), `echo`(0.0681), `is`(0.0675), `then`(0.0659), `required`(0.0654), `-z`(0.0575), `"Error:`(0.0551), `if`(0.0454), `[`(0.041)

Attribution rows=240, ranking=mean_input_x_grad; error-cue hits mean=3, max=3; structural tokens and stop-words excluded.

Checks: A1=PASS A2=PASS A3=PASS A4=PASS.

## 5. Task B - 14-class failure classifier

| Evaluation | N | Accuracy | Macro-F1 | Weighted-F1 | PR-AUC |
|---|---|---|---|---|---|
| Group-disjoint OOF | 8976 | 0.8844 | 0.7494 | 0.8842 | 0.8148 |
| Official val | 1796 | 0.9165 | 0.9111 | 0.9109 | 0.9663 |

**OOF per-depth**

| Visibility | N | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| 25% | 2244 | 0.7469 | 0.3820 | 0.6905 |
| 50% | 2244 | 0.7906 | 0.4922 | 0.7818 |
| 75% | 2244 | 1.0000 | 1.0000 | 1.0000 |
| 100% | 2244 | 1.0000 | 1.0000 | 1.0000 |

**Gate 5 - group-disjoint Python exceptions (OOF)**

| Scope | N | Macro-F1 | Per-class F1 | Zero-F1 classes |
|---|---|---|---|---|
| overall | 8976 | 0.6198 | AssertionError=0.86, AttributeError=0.51, FileNotFoundError=0.55, IndexError=0.67, KeyError=0.67, TypeError=0.67, ValueError=0.55, ZeroDivisionError=0.49 | none |
| 75 | 2244 | 1.0000 | AssertionError=1.00, AttributeError=1.00, FileNotFoundError=1.00, IndexError=1.00, KeyError=1.00, TypeError=1.00, ValueError=1.00, ZeroDivisionError=1.00 | none |
| 100 | 2244 | 1.0000 | AssertionError=1.00, AttributeError=1.00, FileNotFoundError=1.00, IndexError=1.00, KeyError=1.00, TypeError=1.00, ValueError=1.00, ZeroDivisionError=1.00 | none |

Python-exception OOF support: 1000 rows (required 1,000, zero excluded).

**Counterfactual masking (fold 0 validation)**

| Visibility | Base F1 | Header masked (64) | Header drop | Tail masked (448) | Tail drop |
|---|---|---|---|---|---|
| 75 | 1.0000 | 1.0000 | 0.0000 | 0.0769 | 0.9231 |
| 100 | 1.0000 | 1.0000 | 0.0000 | 0.0970 | 0.9030 |

**B4 fold group disjointness**

| Fold | Train groups | Val groups | Overlap | Excluded rows |
|---|---|---|---|---|
| 0 | 1795 | 449 | 0 | 0 |
| 1 | 1795 | 449 | 0 | 0 |
| 2 | 1795 | 449 | 0 | 0 |
| 3 | 1796 | 448 | 0 | 0 |
| 4 | 1795 | 449 | 0 | 0 |

Total overlap=0, excluded rows=0.

Calibration: T=0.70, tau=0.00, used=False; OOF F1 0.7494 -> 0.7494; ECE=0.0742, Brier=0.1337.

**B1 scope.** B1 is enforced at the deployment
horizons 75% and 100%: OOF Macro-F1 1.0000 / 1.0000, official Macro-F1 1.0000 / 1.0000.
Pooled over all four horizons the same metrics are OOF 0.7494 and official 0.9111 (pooled threshold pass=False). The gap is the 25%/50%
snapshots whose model view is byte-identical across the eight
Python-exception classes; per-class early-horizon OOF F1 is
0.00-0.22 for those classes and 1.00 for the CI/CD classes.

**B5 rolled-up F1-F7 taxonomy (OOF)**

| Scope | N | Accuracy | Macro-F1 (F1-F7) |
|---|---|---|---|
| overall | 8976 | 0.9293 | 0.9332 |
| 25 | 2244 | 0.8436 | 0.8093 |
| 50 | 2244 | 0.8734 | 0.8796 |
| 75 | 2244 | 1.0000 | 1.0000 |
| 100 | 2244 | 1.0000 | 1.0000 |

- B4 Group Disjoint: PASS
- Gate 5 Group-Disjoint Python Exceptions: PASS

Checks: B1=PASS B2=PASS B3=PASS B4=PASS.

## 6. Held-out locked test vault

_Locked test evaluation did not run (gates not all passed)._

The `final_test_results.csv` already present in the project root
predates this remediation: it was written at 12:02 on 2026-10-22
from the old 64+448-token model and has no F1-F7 rollup rows. It is
stale and must not be presented as the current result. No new test
predictions were generated, and no file in `vault/test_locked/`
was written.

## 7. Limitations and honest notes

- The raw metadata reuses `run_id` for the success and failure run of
  the same family. The canonical key therefore includes `outcome`;
  without it, 634 keys would hold eight snapshots and 195 runs would
  cross the official split boundary.
- After the Step 1 anonymization, the 25% prefix is checkout
  boilerplate for six of the seven families. Measured on the
  validation split: 0 of 200 sampled snapshots in F1, F2, F3, F4, F6
  and F7 contain an error cue; only the docker family does (66 of
  200). A rule-based prefix classifier reaches 0.441 accuracy against
  a 0.580 majority baseline, so at that horizon the model has to work
  from structural and textual context rather than from failure text.
  It reaches 0.8941 accuracy at 25% against the
  0.5801 majority. That number is reported as
  the early-horizon control; Gate 1 is enforced at 50%, 75% and 100%,
  where the gates are meaningful for deployment.
- At 25% and 50% visibility, 1,044 Task B train rows form three
  genuinely identical groups: F1/F4 setup-only logs (606 rows) and F3
  exception logs before the exception is printed (438 rows). These
  snapshots are shorter than 768 tokens, so the full content is seen;
  the ambiguity is in the logs, not in the token window. They are
  downweighted to 0.1 during training and necessarily cap early-horizon
  accuracy.
- Official Task B validation contains only the six CI/CD classes.
  Python-exception performance is therefore estimated on the
  group-disjoint OOF matrix, not on the official val split.
- `inference_ms_per_snapshot` measures model forward time on the GPU
  with warm caches; it excludes snapshot I/O, normalization and
  tokenization. The multiclass value is the cost of all five fold
  models; the binary value is a single model.
- Binary precision/recall/F1 are reported for the failure class
  (label 1); macro-F1 averages both classes.
- The source logs contain UTF-8 BOM bytes that were double-encoded as
  the three characters `\u00ef\u00bb\u00bf` in about 20% of
  snapshots. The normalizer now strips both the real BOM and that
  mojibake before tokenization, and check 12 asserts that no tokenized
  row uses the artifact token.

## 8. Artifacts

- `dataset_integrity_proof.md` - 16-check proof
- `work_data/dataset_remediation/` - run registry, group map, proof JSON
- `models/task_a_champion.pt`
- `models/task_b_fold{0..4}_champion.pt`
- `day_shift_results.json` - full metric/check evidence
- `work_data/leakage_evidence.json` - scenario-name purity counts
- `day_shift_pipeline.log`
