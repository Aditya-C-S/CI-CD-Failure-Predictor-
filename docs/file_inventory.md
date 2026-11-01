# Project File Inventory & Traceability Matrix

**Project:** AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis  
**Date:** 2026-10-23  
**Status:** COMPLETE & VERIFIED  

---

## 1. Source Directories Inspected

1. **Source Directory 1:** `C:\Users\Aditya CS\OneDrive\Documents\Capstone\logs\dependency-error-repo`  
   - Role: Application testbed, GitHub Actions CI workflows, failure generators, Parser V2, RCA V1 engine, verification scripts.
2. **Source Directory 2:** `C:\Users\Aditya CS\OneDrive\Documents\Capstone\Dataset`  
   - Role: Ready-to-train datasets (v1 and v2), ML experiment pipelines, serialized scikit-learn models (LR, SVM), calibration evaluations.
3. **Reference Directory:** `C:\Users\Aditya CS\OneDrive\Documents\Capstone\compare_models`  
   - Role: Model comparison audits, teammate review packets, Stage 10I selection review.

---

## 2. Component Inventory & Destination Mapping

| Original Source Path | Destination Path | Purpose / Role | Copied? | Notes / Status |
|---|---|---|---|---|
| `logs/dependency-error-repo/parser/log_parser.py` | `src/parser/log_parser.py` | Core Parser V2 implementation (3-column & GHA runner format) | Yes | Original implementation preserved untouched |
| `logs/dependency-error-repo/parser/parser_v2_tests.py` | `src/parser/parser_v2_tests.py` | Parser V2 comprehensive test suite | Yes | 100% passing |
| `logs/dependency-error-repo/parser/test_parser_extensions.py` | `src/parser/test_parser_extensions.py` | Parser extension & regression tests | Yes | Preserved for test coverage |
| `logs/dependency-error-repo/parser/validate_dataset.py` | `src/parser/validate_dataset.py` | Parser dataset integrity validator | Yes | Preserved |
| `[New File]` | `src/parser/parser_v2.py` | Facade adapter providing unified API exports | Created | Re-exports LogRecord & parse functions |
| `logs/dependency-error-repo/rca/engine.py` | `src/rca/engine.py` | Core RCA Engine & analyzer dispatcher | Yes | Preserved |
| `logs/dependency-error-repo/rca/base.py` | `src/rca/base.py` | Abstract BaseCategoryAnalyzer & helper functions | Yes | Preserved |
| `logs/dependency-error-repo/rca/schema.py` | `src/rca/schema.py` | RCAReport dataclass & causal category taxonomy | Yes | Preserved |
| `logs/dependency-error-repo/rca/rca_tests.py` | `src/rca/rca_tests.py` | RCA Engine unit and integration tests | Yes | 100% passing |
| `logs/dependency-error-repo/rca/test_regression_v2.py` | `src/rca/test_regression_v2.py` | Non-regression test suite for RCA | Yes | Preserved |
| `logs/dependency-error-repo/rca/validate_rca.py` | `src/rca/validate_rca.py` | Batch RCA validation script | Yes | Preserved |
| `logs/dependency-error-repo/rca/analyzers/*.py` | `src/rca/analyzers/*.py` | 5 category analyzers (syntax, dependency, test, timeout, fallback) | Yes | All 5 analyzers preserved |
| `[New File]` | `src/rca/rca_engine.py` | Facade adapter providing unified RCA API exports | Created | Re-exports RCAEngine & schema |
| `Dataset/ml_experiments/outputs/stage10_v2/models/taskA_LR_*.joblib` | `models/logistic_regression/artifacts/` | Serialized LR pipelines for depths 25%, 50%, 75%, 100% | Yes | Independently verified |
| `Dataset/ml_experiments/outputs/stage10_v2/models/taskB_LR_*.joblib` | `models/logistic_regression/artifacts/` | Serialized Task B multi-class LR pipelines | Yes | Preserved |
| `Dataset/ml_experiments/outputs/stage10_v2/models/taskA_SVM_*.joblib` | `models/svm/artifacts/` | Serialized LinearSVC pipelines for depths 25%, 50%, 75%, 100% | Yes | Independently verified |
| `Dataset/ml_experiments/outputs/stage10_v2/models/taskB_SVM_*.joblib` | `models/svm/artifacts/` | Serialized Task B multi-class LinearSVC pipelines | Yes | Preserved |
| `compare_models/lr_25_calibration_results.json` | `models/logistic_regression/evaluation/` | Exact probability calibration results ($ECE=3.8\%$) | Yes | Verified baseline |
| `Dataset/ml_experiments/src/*.py` | `models/logistic_regression/training/` & `models/svm/training/` | Training scripts (trainer, sanitizer, evaluator, data_loader) | Yes | Preserved for reproducibility |
| `Dataset/ml_experiments/outputs/stage10_v2/reports/*` | `models/logistic_regression/evaluation/` & `models/svm/evaluation/` | V2 retraining and leakage audit reports | Yes | Preserved |
| `[New Dir]` | `models/modernbert/` | ModernBERT model directory | Created | Awaiting weights ZIP from Aadarsh |
| `[New Dir]` | `models/bilstm/` | BiLSTM model directory | Created | Awaiting weights ZIP from Aayush |
| `Dataset/ready_to_train_v2/*.csv, *.json, *.md` | `data/processed/` | Canonical v2 dataset index, splits, and manifest | Yes | Preserves data reproducibility |
| `Dataset/ready_to_train_v2/snapshots/` (samples) | `data/samples/snapshots/` | Sample 25/50/75/100% snapshots for F1-F7 | Yes | Sampled for lightweight execution |
| `logs/dependency-error-repo/logs/` (samples) | `data/samples/logs/` | Sample raw full logs for benchmark categories | Yes | Sampled for quick testing |
| `logs/dependency-error-repo/labels.csv` | `data/raw/labels.csv` | Original benchmark run ground truth labels | Yes | Preserved |
| `Dataset/ready_to_train_v1/*` | `data/archive/` | Historical v1 dataset summaries | Yes | Preserved in archive |
| `logs/dependency-error-repo/automation/*.py` | `src/automation/*.py` | Workflow generators and validators | Yes | Preserved |
| `logs/dependency-error-repo/docker/*` | `docker/*` | Docker scenarios and Dockerfile | Yes | Preserved |
| `logs/dependency-error-repo/.github/workflows/*` | `.github/workflows/*` | GitHub Actions workflow definitions | Yes | Preserved |
| `[New File]` | `src/prediction/model_interface.py` | Model-independent prediction interface & contracts | Created | Decoupled ML layer |
| `[New File]` | `src/prediction/model_loader.py` | Model loader, artifact cache, availability checker | Created | Dynamically handles depths |
| `[New File]` | `src/prediction/predictor.py` | Concrete predictors (LR, SVM, stubs for BERT/LSTM) | Created | Factory `get_predictor()` |
| `[New File]` | `src/prediction/sanitizer.py` | Deterministic log sanitizer for prefix invariance | Created | Prevents metadata leakage |
| `[New File]` | `src/ingestion/log_streamer.py` | Progressive log streamer and snapshot generator | Created | Slices 25%, 50%, 75%, 100% |
| `[New File]` | `src/ingestion/pipeline_simulator.py` | End-to-end pipeline simulator | Created | Connects Ingestion -> ML -> Parser -> RCA -> Remediation |
| `[New File]` | `src/remediation/suggestions.py` | Actionable remediation & terminal commands generator | Created | Evidence-grounded advice |
| `[New File]` | `src/api/main.py` | FastAPI application with REST & OpenAPI endpoints | Created | Full web backend |
| `[New File]` | `frontend/index.html, style.css, app.js` | Interactive modern glassmorphic web dashboard | Created | Real-time gauge, bars, evidence |
| `[New File]` | `tests/test_parser.py` | Integration tests for Parser V2 | Created | 100% Passing |
| `[New File]` | `tests/test_prediction.py` | Unit tests for ML prediction interface | Created | 100% Passing |
| `[New File]` | `tests/test_rca.py` | Integration tests for RCA & Remediation | Created | 100% Passing |

---

## 3. Excluded Files & Rationale

1. **Virtual Environments (`venv/`, `.venv/`):** Excluded to prevent bloating and platform-dependent binary collisions. Replaced by clean `requirements.txt`.
2. **Python Cache Files (`__pycache__/`, `*.pyc`):** Excluded as generated runtime artifacts.
3. **Pytest Cache (`.pytest_cache/`):** Excluded as generated test runtime artifacts.
4. **Git Internals (`.git/` in source folders):** Excluded to prevent submodule conflicts.
5. **Raw 22,360 Snapshot Text Files:** Excluded bulk copying into project root. Full dataset index and manifest were copied to `data/processed/`, and representative samples were copied to `data/samples/snapshots/` to maintain agility and avoid overwhelming OneDrive sync.
6. **Validation Bundle Bulk Logs (`parser_rca_validation_bundle/` ~800 MB):** Excluded bulk raw logs; core evaluation reports and summary metrics were retained.
