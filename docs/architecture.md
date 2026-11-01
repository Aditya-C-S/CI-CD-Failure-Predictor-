# System Architecture & Technical Specifications

**Project:** AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis  
**Version:** 2.0.0  
**Authors:** Antigravity / Aditya C S (Lead Investigator)  

---

## 1. Architectural Overview

The platform decouples early predictive risk estimation from retrospective root cause analysis. This architectural separation ensures that:
1. **Early Failure Prediction** operates on partial log streams (25% - 50% log depth) to catch impending failures before expensive test runners and container builds execute.
2. **Parser V2** deterministically extracts structured diagnostic facts (failed step, execution stage, error type, exit code, console snippets) without predicting intent.
3. **Root Cause Analysis (RCA)** evaluates the extracted evidence through modular category analyzers to attribute causal responsibility.
4. **Remediation Engine** synthesizes RCA reports into copyable terminal commands, configuration edits, and prevention practices.

---

## 2. End-to-End Pipeline Data Flow

```text
       +---------------------------------------------+
       |             CI/CD Execution Run             |
       +---------------------------------------------+
                              |
                              v
       +---------------------------------------------+
       |         Log Ingestion & Streamer            |
       +---------------------------------------------+
                              |
                 +------------+------------+
                 |                         |
                 v                         v
     Early Snapshot: 25% - 50%     Full Stream: 75% - 100%
                 |                         |
                 v                         v
       +--------------------+    +--------------------+
       | Failure Predictor  |    |     Parser V2      |
       | (LR / SVM / BERT)  |    | (Evidence Extract) |
       +--------------------+    +--------------------+
                 |                         |
                 |                         v
                 |               +--------------------+
                 |               | Structured Record  |
                 |               +--------------------+
                 |                         |
                 +------------+------------+
                              |
                              v
                 +--------------------------+
                 |        RCA Engine        |
                 | (5 Modular Analyzers)    |
                 +--------------------------+
                              |
                              v
                 +--------------------------+
                 |  Evidence-Grounded Report|
                 +--------------------------+
                              |
                              v
                 +--------------------------+
                 |  Remediation Advisor     |
                 |  (Commands & Best Fixes) |
                 +--------------------------+
                              |
                              v
                 +--------------------------+
                 |  FastAPI / Web Dashboard |
                 +--------------------------+
```

---

## 3. Component Specifications

### 3.1 Log Ingestion & Streamer (`src/ingestion/`)
- **`log_streamer.py`**: Deterministically extracts chronological prefixes corresponding to 25%, 50%, 75%, and 100% of pipeline execution lines.
- **`pipeline_simulator.py`**: Coordinates progressive build replay, feeding snapshots to the predictor and passing the final run to Parser V2 and RCA.

### 3.2 Model-Independent Prediction Interface (`src/prediction/`)
- **Design Principle:** Strict decoupling via the `BasePredictor` contract. Upstream API, parser, and frontend interact with models strictly through `predict_failure(log_text, visibility) -> PredictionResult`.
- **`sanitizer.py`**: Deterministically normalizes runner paths, ISO timestamps, commit hashes, GUIDs, and cloud region identifiers line-by-line with verified prefix-invariance.
- **Model Loader (`model_loader.py`)**: Dynamically resolves and caches fitted scikit-learn pipelines (`TfidfVectorizer` + `LogisticRegression` / `LinearSVC`) matched to the requested visibility depth (`depth025`, `depth050`, `depth075`, `depth100`).

### 3.3 Parser V2 (`src/parser/`)
- Supports both 3-column tab-delimited CI logs (`<job>\t<step>\t<ts> <msg>`) and GitHub Actions group runner logs (`##[group]Run <command>`).
- Normalizes ANSI escape sequences and non-printable control characters.
- Extracts execution stages (`setup`, `build`, `test`, `teardown`), failed step names, exit codes, and categorized error messages.

### 3.4 Root Cause Analysis Engine (`src/rca/`)
- Implements a priority-dispatched analyzer chain:
  1. **`SyntaxAnalyzer`**: Resolves Python `SyntaxError`, `IndentationError`, `TabError` tracebacks and culprit lines.
  2. **`DependencyAnalyzer`**: Diagnoses missing PyPI packages, incompatible version pins, and C-extension wheel build failures.
  3. **`TestFailureAnalyzer`**: Isolates pytest assertion failures and unhandled runtime exceptions within test suites.
  4. **`TimeoutAnalyzer`**: Detects step cancellation, orphan processes, and execution duration timeouts.
  5. **`FallbackAnalyzer`**: Graceful safety handler for general runtime errors or unclassified runner exits (e.g. exit 137 OOM).

### 3.5 Remediation Advisor (`src/remediation/`)
- Maps RCA causal classifications and observed evidence into:
  - Immediate developer action items.
  - Ready-to-run copyable terminal commands (e.g. `pip install`, `pip check`, `ruff check --fix`, targeted `pytest` commands).
  - Long-term prevention advice (pre-commit hooks, CI cache configuration).

### 3.6 API & Web Dashboard (`src/api/`, `frontend/`)
- **FastAPI backend:** OpenAPI documentation at `/docs`, CORS-enabled endpoints (`/api/predict`, `/api/parse`, `/api/rca`, `/api/simulate`, `/api/models`, `/api/samples`).
- **Modern Dashboard:** Glassmorphic dark UI, real-time animated risk gauge, multi-depth progression visualization, structured evidence tables, and copyable remediation blocks.

---

## 4. Log Visibility Depths

| Depth Stage | Execution Context | Intended Role |
|---|---|---|
| **25%** | Pre-build, environment setup, checkout, runner bootstrap | **Primary Early Warning Window:** Triggers failure alerts before expensive runner minutes or GPU allocations occur. |
| **50%** | Dependency installation, wheel compilation, pre-test validation | **Mid-Pipeline Checkpoint:** Validates dependency resolution success. |
| **75%** | Test suite execution, intermediate integration jobs | **Pre-Completion Detection:** Identifies failing test assertions mid-run. |
| **100%** | Full workflow log output, post-job cleanup, artifact upload | **Retrospective Post-Mortem:** Complete evidence available for Parser V2 and RCA Engine. |

---

## 5. Swapping & Adding New Models

To register a new model (such as ModernBERT or BiLSTM):
1. Place serialized weights or checkpoints into `models/<model_name>/`.
2. Subclass `BasePredictor` in `src/prediction/predictor.py`.
3. Implement `predict_failure(log_text: str, visibility: int) -> PredictionResult`.
4. Register the model in the `get_predictor()` factory function in `src/prediction/predictor.py`.
No changes are required in the Parser, RCA Engine, Remediation, API, or Dashboard.
