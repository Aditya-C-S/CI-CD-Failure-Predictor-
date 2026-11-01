```
Untitled
```

```
ModernBERT CI/CD Failure Prediction –
Results Report
Oct 22, 2026
```

```
· @Aadarsh Koushik
```

```
All 8 ModernBERT experiments (binary and failure-type, each at 25/50/75/100% log
visibility) trained to completion on a Kaggle T4 in about 63 minutes. Binary
failure F1 is
0.964–0.999 at 25–75% visibility, but both tasks drop sharply at 100% for a
reason not yet
diagnosed, and 8 of the 14 failure types have no validation data, so their
scores are
unreliable.
```

```
Setup
Model: answerdotai/ModernBERT-base , fine-tuned fresh from the pretrained
weights
```

```
for each of the 8 experiments. No earlier results were reused.
Data: ready_to_train_v2 with the supplied train/val/test assignments unchanged.
Binary: 3,744 / 774 / 1,072 runs per depth. Failure-type (failure-only logs, 14
classes):
```

```
2,244 / 449 / 797 runs per depth.
Input: raw log text only. No paths, metadata or path-embedded labels.
Long logs: the first 128 plus the last 382 tokens (512 in total); the middle is
dropped.
Training: learning rate 2e-5, effective batch size 16, fp16, seed 42. Binary: up
to 3
epochs. Failure-type: up to 6 epochs with an inverse-square-root class-weighted
loss.
```

```
Early stopping on validation macro-F1 (patience 2).
Protocol: tuning on validation only; the test set was evaluated once, at the
end.
```

```
Hardware and time: Tesla T4; about 35.7 minutes for the 4 binary runs and 27.2
minutes for the 4 failure-type runs.
```

```
Binary results
```

```
Test set, threshold 0.5, positive class = failure. Each depth has 1,072 test
runs (797 failure,
275 success).
Depth
```

```
Accuracy Precision Recall
```

```
F1
```

```
ROCAUC
```

```
Avg.
precision
Confusion matrix
[[TN, FP], [FN, TP]]
```

# `25%` 

```
0.9571
0.9720
0.9863
```

- `0.9915` 

```
[[229, 46], [0, 797]]
```

```
0.9454
```

```
1.0000
```

```
Page 1 of 5
```

```
Untitled
```

```
Depth
Accuracy Precision Recall
F1
ROCAUC
Avg.
precision
Confusion matrix
[[TN, FP], [FN, TP]]
50%
0.9450
0.9457
0.9824 0.9637
0.9835
0.9902
[[230, 45], [14, 783]]
75%
0.9991
1.0000
0.9987
0.9994 1.0000
1.0000
[[275, 0], [1, 796]]
100% (full-log
benchmark)
0.7808
0.8377
0.8745
0.8557
0.9259
[[140, 135], [100, 697]]
0.8330
```

```
At 25% and 50%, nearly all errors are false alarms on success runs (46 and 45 of
275).
The 25% model misses no failures.
```

```
At 75%, there is 1 error in 1,072 runs.
At 100%, the model is much worse than at 75% (100 missed failures, 135 false
alarms). A
full log should contain everything the 75% log does, so this is treated as an
open
problem, not a finding (see Limitations).
Validation-tuned thresholds were 0.05, 0.45, 0.05 and 0.45 for the four depths.
They
changed only the 75% result, by one run, so 0.5 is reported.
```

```
Failure-type results
Test set, 797 failure runs, 14 classes. All 14 classes have test examples, so
macro-F1
averages all 14.
Depth
Accuracy
Macro-F1
Weighted-F1
25%
0.6901
0.4583
0.6562
50%
0.7553
0.5146
```

```
0.7304
75%
```

```
0.8118
0.5770
```

```
0.7746
100% (full-log benchmark)
0.6361
0.3504
```

```
0.5736
Per-class test F1 (n = test runs of that class):
Class
n
25%
50%
```

```
75%
```

```
100%
```

```
ci_config_permission_failure
```

```
124
```

- `1.00` 

- `1.00` 

- `1.00` 

- `1.00` 

```
dependency_resolution_failure 73
```

- `1.00` 

- `1.00` 

- `1.00` 

- `0.00` 

```
docker_build_failure
```

```
100
```

- `1.00` 

- `1.00` 

- `1.00` 

- `1.00` 

```
execution_timeout
```

```
75
```

- `0.47` 

- `1.00` 

- `1.00` 

- `1.00` 

```
Page 2 of 5
```

```
Untitled
```

```
Class
```

```
n
25%
50%
```

```
75%
```

```
100%
```

```
network_service_failure
```

```
100
```

- `1.00` 

- `1.00` 

- `1.00` 

- `1.00` 

```
syntax_error
```

```
75
```

- `0.74` 

- `1.00` 

- `1.00` 

- `0.67` 

```
AssertionError
```

```
30
```

- `1.00` 

- `1.00` 

- `1.00` 

- `0.00` 

```
AttributeError
```

```
33
```

- `0.00` 

- `0.00` 

- `0.00` 

- `0.23` 

- `FileNotFoundError` 

```
29
```

- `0.00` 

- `0.00` 

- `0.32` 

- `0.00` 

# `IndexError` 

# `26` 

- `0.00` 

- `0.00` 

- `0.00` 

- `0.00` 

# `KeyError` 

```
41
```

- `0.00` 

- `0.00` 

- `0.76` 

- `0.00` 

# `TypeError` 

```
31
```

- `0.00` 

- `0.00` 

- `0.00` 

- `0.00` 

# `ValueError` 

```
25
```

- `0.20` 

- `0.20` 

- `0.00` 

- `0.00` 

```
ZeroDivisionError
```

```
35
```

- `0.00` 

- `0.00` 

- `0.00` 

- `0.00` 

```
Six infrastructure classes (top six rows): all score 1.00 at 50% and 75%. At
25%,
```

```
execution_timeout (0.47) and syntax_error (0.74) are weaker. At 100%,
dependency_resolution_failure falls to 0.00 and syntax_error to 0.67.
Eight Python exception classes (bottom eight rows): mostly 0.00, with isolated
nonzero scores that do not repeat across depths (AssertionError is 1.00 at 25–
75% and
```

```
0.00 at 100%; KeyError is 0.76 only at 75%). These scores are unreliable, and no
conclusion should be drawn about which exceptions are learnable.
Macro-F1 therefore mostly reflects how many exception classes happen to score
above zero. It peaks at 0.5770 at 75%.
```

```
Validation has no examples of the 8 exception classes at any depth, so early
stopping
```

```
used macro-F1 over the 6 infrastructure classes only.
```

```
As in the binary task, 100% is the worst depth. The full 14×14 confusion
matrices are
```

```
saved per experiment but were not inspected for this report.
```

```
Comparison with the Stage 10 TF-IDF baselines
Binary F1 (failure) and failure-type macro-F1 on the test set. The TF-IDF
numbers are
```

```
copied from the teammate's Stage 10 report and were not re-run here.
Depth Binary F1:
TF-IDF LR
```

```
Binary F1: TFIDF SVM
```

```
Binary F1:
ModernBERT
```

```
Macro-F1:
TF-IDF LR
```

```
Macro-F1: TFIDF SVM
```

```
Macro-F1:
ModernBERT
```

# `25%` 

- `0.9719` 

- `0.9720` 

- `0.9720` 

- `0.4822` 

- `0.4910` 

- `0.4583` 

```
50%
```

- `0.9719` 

- `0.9720` 

- `0.9637` 

- `0.3889` 

- `0.3889` 

- `0.5146` 

```
Page 3 of 5
```

```
Untitled
```

```
Depth Binary F1:
TF-IDF LR
Binary F1: TFIDF SVM
Binary F1:
ModernBERT
```

```
Macro-F1:
TF-IDF LR
Macro-F1: TFIDF SVM
Macro-F1:
ModernBERT
```

```
75%
```

- `0.9994 1.0000 0.9994` 

- `0.3889` 

- `0.3889` 

- `0.5770 100%` 

- `0.9994` 

- `1.0000` 

- `0.8557` 

- `0.3889` 

- `0.7608` 

- `0.3504` 

```
For binary prediction at 25% and 75%, ModernBERT matches the TF-IDF baselines,
so
```

```
it shows no advantage on this dataset.
```

```
At 100%, ModernBERT is below both baselines on both tasks. This is the
unexplained
result.
```

```
At 50–75%, ModernBERT's higher failure-type macro-F1 comes from non-zero scores
on a few exception classes, which are unstable (see above).
The comparison is not like-for-like: the Stage 10 pipeline applied an extra log
sanitizer
```

```
and a hyperparameter grid search, while ModernBERT read the snapshot text
directly
```

```
with one fixed configuration.
```

```
Limitations and open items
```

```
1. The 100% results are unexplained. Both tasks get worse only at 100%, while
the TFIDF baselines reach about 1.00 on binary. Per-epoch training logs were not
captured in
```

```
the notebook output, so the cause is unknown. Two untested candidates: the
first-128
```

```
+ last-382 token window dropping decisive content from long full logs, and
unstable
fine-tuning. Next check: the truncated fractions in config.json and the curves
in
```

```
training_log.json for binary_100 and failure_100 . Until then, do not cite 100%
as a ModernBERT capability result.
```

```
2. Eight exception classes have no validation data. Model selection used the six
infrastructure classes only. There are about 250 training examples of the eight
classes
```

```
per depth, and 25–41 test runs per class. The Stage 10 report states that all of
these
```

```
training examples come from a single execution group; we have not verified this.
Their
```

```
scores should not be used to compare depths.
```

```
3. Single seed (42), no confidence intervals. Differences of a few points
between depths
```

```
or models may be noise.
```

```
4. Duplicate-text check was not run. Identical logs appearing in more than one
split
```

```
cannot be ruled out.
```

```
5. 100% visibility is a full-log benchmark, not an early-prediction result.
```

```
6. Synthetic data. The Stage 10 report describes the dataset as synthetic, so
these
```

```
results may not transfer to real CI/CD logs.
```

```
Page 4 of 5
```

# `Untitled` 

```
7. Not independently inspected: the numbers come from the run's saved
FINAL_REPORT.md . The failure-type confusion matrices and the training logs were
not
reviewed for this report.
```

# `Saved artifacts` 

```
Location: the Output tab of the Kaggle notebook's saved version, folder
cicd_modernbert_v2 ( /kaggle/working/cicd_modernbert_v2 during the run).
Per experiment ( experiments/binary_<depth> and experiments/failure_<depth> ):
model/ checkpoint, config.json , training_log.json , val_metrics.json ,
val_predictions.csv , test_metrics.json , test_predictions.csv , and for
failure-
```

```
type val_confusion_matrix.csv and test_confusion_matrix.csv .
Also: FINAL_REPORT.md and documentation/failure_class_support_by_depth.csv .
Notebook: ModernBERT_CI_CD_KAGGLE_v2.ipynb .
```

```
Not yet in Google Drive. The original plan saved to Drive, but the run moved to
Kaggle
```

```
after Colab's free GPU quota was exhausted. Download the Output ZIP and copy it
to
```

```
Drive or the team's shared storage so it does not depend on the Kaggle account.
```

```
Page 5 of 5
```

