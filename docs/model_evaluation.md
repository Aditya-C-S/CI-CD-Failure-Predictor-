# Model Evaluation & Verification Report

**Project:** AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis  
**Stage:** 10I Benchmark Review & Verification Synthesis  
**Date:** 2026-10-23  
**Status:** Canonical Reference Document  

---

## 1. Evaluation Methodology & Verification Distinction

To maintain strict scientific integrity, all models and metrics evaluated in this capstone project are categorized into two explicit tiers:

1. **Locally Verified & Reproducible (Tier 1):** Models whose code, frozen dataset splits, training pipelines, serialized `.joblib` artifacts, and prediction vectors are present in this repository and independently validated via inference against frozen test sets.
2. **Teammate-Reported Claims (Tier 2):** Models whose evaluation metrics were reported in documentation packets or PDFs, but whose serialized weights, training harnesses, and artifact files have **NOT** yet been delivered to this repository and could not be independently audited.

---

## 2. Locally Verified Model Performance (Tier 1)

All Tier 1 models were trained on the sanitized `ready_to_train_v2` dataset (5,590 runs across 22,360 snapshots) using group-disjoint splits to guarantee zero data leakage between train, validation, and test sets.

### 2.1 Task A: Early Failure Prediction (Binary Classification)

Test set: 1,072 snapshots (797 failure, 275 success; failure prevalence = 74.35%).

| Model Architecture | Visibility Depth | Test F1 (Failure) | Test Precision | Test Recall | Macro F1 | PR-AUC | ROC-AUC | Calibration ($ECE$) | Verification Status |
|---|---|---|---|---|---|---|---|---|---|
| **TF-IDF + Logistic Regression** | **25%** | **0.9719** | **0.9465** | **0.9987** | **0.9405** | **0.9917** | **0.9869** | **3.82%** | **VERIFIED BASELINE** |
| TF-IDF + Logistic Regression | 50% | 0.9719 | 0.9465 | 0.9987 | 0.9405 | 0.9917 | 0.9869 | 3.82% | Verified |
| TF-IDF + Logistic Regression | 75% | 0.9730 | 0.9487 | 0.9987 | 0.9431 | 0.9928 | 0.9886 | 3.65% | Verified |
| TF-IDF + Logistic Regression | 100% | 0.9760 | 0.9544 | 0.9987 | 0.9497 | 0.9945 | 0.9912 | 3.12% | Verified |
| TF-IDF + Linear SVM | 25% | 0.9719 | 0.9465 | 0.9987 | 0.9405 | N/A (Hinge) | N/A | N/A | Verified |
| TF-IDF + Linear SVM | 50% | 0.9719 | 0.9465 | 0.9987 | 0.9405 | N/A (Hinge) | N/A | N/A | Verified |
| TF-IDF + Linear SVM | 75% | 0.9730 | 0.9487 | 0.9987 | 0.9431 | N/A (Hinge) | N/A | N/A | Verified |
| TF-IDF + Linear SVM | 100% | 0.9760 | 0.9544 | 0.9987 | 0.9497 | N/A (Hinge) | N/A | N/A | Verified |

### 2.2 Calibration Audit for Logistic Regression @ 25% Depth
- **Brier Score:** `0.038213`
- **Expected Calibration Error ($ECE$):** `0.038282` ($3.83\%$)
- **Maximum Calibration Error ($MCE$):** `0.076840` ($7.68\%$)
- **Evaluation Finding:** The probability output is exceptionally well-calibrated, ensuring predicted failure percentages reliably reflect true risk.

---

## 3. Teammate-Reported Performance (Tier 2 - Unverified Claims)

The following metrics are derived from teammate documentation packets (`compare_models/stage10i_teammate_model_reports_review_packet.md` and `compare_models/modernbert.md`). They have **not** been independently reproduced at the artifact level.

| Model Candidate | Contributor | Architecture | Reported Depth | Reported F1 | Reported Accuracy | Current Status |
|---|---|---|---|---|---|---|
| **ModernBERT-base** | Aadarsh Koushik | Transformer (ModernBERT) | 25% | ~ 0.88 - 0.92 | ~ 87.5% | **Awaiting Weights ZIP** |
| ModernBERT-base | Aadarsh Koushik | Transformer (ModernBERT) | 100% | ~ 0.96 - 0.98 | ~ 96.2% | Awaiting Weights ZIP |
| **BiLSTM / 768-Token** | Aayush Jha | Bidirectional LSTM + Embeddings | 25% | ~ 0.85 - 0.89 | ~ 84.1% | **Awaiting Weights ZIP** |
| BiLSTM / 768-Token | Aayush Jha | Bidirectional LSTM + Embeddings | 100% | ~ 0.93 - 0.95 | ~ 92.4% | Awaiting Weights ZIP |

### 3.1 Known Limitations & Disclaimers for Deep Learning Candidates
1. **Weight Artifacts Pending:** Neither model currently has serialized checkpoint weights in the project repository.
2. **Computational Overhead:** ModernBERT requires GPU acceleration or significant CPU cycles (>350 ms latency vs <1 ms for TF-IDF + LR).
3. **Early Log Token Limits:** At 25% log depth, logs often consist of setup scripts where subword tokenization offers minimal advantage over character/word n-gram TF-IDF.
4. **Integration Policy:** When ZIP files containing weights arrive from teammates, they will be placed into `models/modernbert/` and `models/bilstm/` and benchmarked via the unified `src/prediction/` interface.

---

## 4. Model Selection Justification for Stage 11 Integration

Based on the Stage 10I evaluation review:
- **Active Primary Runtime Predictor:** **TF-IDF + Logistic Regression at 25% Log Depth**.
- **Justification:**
  - Highest defensible recall (0.9987) and precision (0.9465) at the critical early warning stage.
  - Sub-millisecond CPU inference latency ($<1\text{ ms}$).
  - Fully audited probability calibration with $ECE = 3.8\%$.
  - Zero deployment friction and zero external GPU dependency.
- **Post-Mortem Classification Reference:** **TF-IDF + Linear SVM at 100% Depth** (used when entire post-execution log is available).
