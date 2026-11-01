# AI-Powered CI/CD Pipeline Failure Prediction and Assisted Root Cause Analysis

Final-Year Capstone Project &bull; Automated Software Engineering &bull; CI/CD Failure Intelligence Platform

---

## 📌 Project Overview

Continuous Integration and Continuous Deployment (CI/CD) pipelines frequently suffer from brittle failures—ranging from subtle syntax glitches and missing transitive dependencies to test assertion timeouts and container configuration errors. These failures lead to wasted developer velocity and expensive cloud runner minutes.

This project delivers an end-to-end, production-grade CI/CD failure intelligence platform that:
1. **Predicts Pipeline Failures Early:** Evaluates machine learning models at early log visibility stages (25%, 50%, 75%, 100% log depth) to catch impending build failures before expensive test suites and deployment containers execute.
2. **Parses Structured Diagnostic Evidence:** Deploys **Parser V2** to extract execution stages, failed step names, exit codes, and categorized error messages.
3. **Assists Root Cause Analysis (RCA):** Dispatches parsed evidence across 5 modular category analyzers (Syntax, Dependency, Test, Timeout, Fallback) to establish true causal attribution.
4. **Delivers Actionable Remediation:** Automatically suggests copyable terminal commands, configuration adjustments, and prevention best practices.
5. **Code & Dependency Knowledge Graph:** Integrates with **Neo4j** and an AST-based metadata pipeline to build interactive repository topology graphs, identify high-blast-radius dependencies, and trace failure provenance.
6. **Multi-Model Runtime Comparison:** Compares predictions from **TF-IDF + Logistic Regression**, **TF-IDF + Linear SVM**, and **BiLSTM v2 (Two-Stage PyTorch Deep Learning with ConvStem and Attention Pooling)** side-by-side.
7. **Interactive Glassmorphic Web Dashboard:** Provides real-time simulation, visibility depth progression bars, risk meters, telemetry monitors, and interactive architecture visualizers.

---

## 🏛️ System Architecture

```text
       +-------------------------------------------------------+
       |             CI/CD Execution Run / Webhook             |
       +-------------------------------------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |         Log Streamer & Progressive Ingestion          |
       +-------------------------------------------------------+
                                   |
                  +----------------+----------------+
                  |                                 |
                  v                                 v
      Early Snapshot: 25% - 50%         Full Stream: 75% - 100%
                  |                                 |
                  v                                 v
       +-----------------------+         +--------------------+
       | Multi-Model Inference |         |     Parser V2      |
       | • Logistic Regression |         | (Structured Facts  |
       | • Linear SVM          |         |  & Error Extracts) |
       | • BiLSTM v2 (PyTorch) |         +--------------------+
       +-----------------------+                    |
                  |                                 |
                  v                                 v
       +-----------------------+         +--------------------+
       | Risk Progression &    |         | Structured Evidence|
       | Early Warning Metrics |         +--------------------+
       +-----------------------+                    |
                  |                                 |
                  +----------------+----------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |               5-Category RCA Engine                   |
       |    [Syntax | Dependency | Test | Timeout | Fallback]  |
       +-------------------------------------------------------+
                                   |
                  +----------------+----------------+
                  |                                 |
                  v                                 v
       +-----------------------+         +--------------------+
       | Remediation Engine    |         | Neo4j Knowledge    |
       | (Copyable CLI Fixes)  |         | Graph & AST Impact |
       +-----------------------+         +--------------------+
                  |                                 |
                  +----------------+----------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |         Interactive Glassmorphic Dashboard            |
       |   (Real-Time Telemetry, Architecture & Topology UI)   |
       +-------------------------------------------------------+
```

---

## 📁 Project Directory Structure

```text
CI-CD-Failure-Predictor/
│
├── README.md                               # Comprehensive documentation & quickstart
├── requirements.txt                        # Clean, verified Python dependencies
├── .env.example                            # Configuration environment template
├── .gitignore                              # Git exclusion rules (ignores venvs, zips, cache)
├── pytest.ini                              # Pytest runner configuration
│
├── data/
│   ├── raw/                                # Ground truth labels and raw metadata
│   ├── processed/                          # Ready-to-train v2 index, splits, & manifest
│   ├── samples/                            # Benchmark logs (F1-F7) & 25/50/75/100% snapshots
│   ├── demo_runs/                          # Runtime demo run persistence (tracked via .gitkeep)
│   └── archive/                            # Historical audit reports & v1 dataset summaries
│
├── models/
│   ├── logistic_regression/                # Verified baseline (TF-IDF + LR)
│   │   ├── artifacts/                      # Serialized .joblib pipelines (25%, 50%, 75%, 100%)
│   │   ├── evaluation/                     # Calibration results (ECE=3.8%) & metrics
│   │   └── training/                       # Training & leakage audit scripts
│   ├── svm/                                # Verified baseline (TF-IDF + LinearSVC)
│   │   ├── artifacts/                      # Serialized .joblib pipelines (25%, 50%, 75%, 100%)
│   │   ├── evaluation/                     # Evaluation metrics & confusion matrices
│   │   └── training/                       # Training scripts
│   ├── bilstm/                             # BiLSTM v1 architecture & log normalizer
│   ├── bilstm2/                            # BiLSTM v2 retrained champion models (PyTorch)
│   │   ├── artifacts/models/               # task_a_champion.pt, task_b_fold0..4_champion.pt
│   │   ├── artifacts/work_data/            # Vocab tokenizer (tokenizer.pkl)
│   │   └── log_normalizer.py               # Canonical regex log normalizer
│   └── modernbert/                         # Transformer documentation & specs
│
├── src/
│   ├── config.py                           # Central configuration & filesystem paths
│   │
│   ├── api/
│   │   ├── main.py                         # FastAPI web server, prediction & RCA endpoints
│   │   ├── demo_router.py                  # Live simulation, preset scenarios & telemetry
│   │   └── metadata_router.py              # Neo4j Graph inspection & metadata endpoints
│   │
│   ├── demo/
│   │   ├── demo_manager.py                 # Unified Demo Manager & scenario orchestration
│   │   ├── git_extractor.py                # Safe Git metadata & commit feature extractor
│   │   ├── graph_inspector.py              # AST call-graph analyzer & Neo4j exporter
│   │   ├── run_summary.py                  # Run reporting & executive metrics synthesis
│   │   └── presentation_helper.py          # Demo scenarios presenter
│   │
│   ├── diagnostics/
│   │   └── system_health.py                # Multi-tier system diagnostics & self-test suite
│   │
│   ├── ingestion/
│   │   ├── log_streamer.py                 # Progressive log streaming & depth slicing
│   │   └── pipeline_simulator.py           # End-to-end execution simulation coordinator
│   │
│   ├── parser/
│   │   ├── parser_v2.py                    # Unified Parser V2 facade adapter
│   │   ├── log_parser.py                   # Reusable Parser V2 evidence extractor
│   │   └── parser_v2_tests.py              # Comprehensive parser regression tests
│   │
│   ├── prediction/
│   │   ├── model_interface.py              # BasePredictor ABC & PredictionResult contracts
│   │   ├── predictor.py                    # Concrete predictors (LR, SVM, BiLSTM, BiLSTM2)
│   │   ├── model_loader.py                 # Model artifact resolution & pipeline cache
│   │   ├── bilstm_inference.py             # BiLSTM v1 inference engine
│   │   ├── bilstm2_inference.py            # BiLSTM v2 PyTorch deep learning inference engine
│   │   ├── runtime_tracker.py              # Real-time multi-model side-by-side tracker
│   │   ├── sanitizer.py                    # Deterministic log sanitizer (prefix-invariance)
│   │   ├── graph_impact.py                 # Blast radius & graph risk assessor
│   │   ├── provenance.py                   # Model provenance & SHA-256 fingerprinting
│   │   └── metadata_service.py             # Knowledge Graph connection adapter
│   │
│   ├── rca/
│   │   ├── rca_engine.py                   # Unified RCA Engine facade adapter
│   │   ├── engine.py                       # Modular RCA Engine orchestrator
│   │   ├── schema.py                       # RCAReport schema & causal taxonomy
│   │   ├── advanced_rca.py                 # Deep reasoning & dependency graph RCA
│   │   └── analyzers/                      # Modular analyzers (syntax, dep, test, timeout, fallback)
│   │
│   ├── remediation/
│   │   └── suggestions.py                  # Remediation advisor & terminal commands generator
│   │
│   ├── automation/                         # CI generator & dataset validation scripts
│   └── scenarios/                          # Orchestrated demo scenario definitions
│
├── frontend/                               # Interactive modern dark-mode dashboard
│   ├── index.html                          # Layout, risk meters, topology graph & telemetry
│   ├── style.css                           # Glassmorphism dark theme tokens
│   └── app.js                              # Real-time simulation controller & event listeners
│
├── metadata_model/                         # Knowledge Graph pipeline & AST parser
│   └── extracted/                          # Extracted graph-doc-gen, Metadata-Pipeline & orc
│
├── metamodel_neo4j/                        # Neo4j setup guides, schemas & scripts
│
├── docker/
│   └── build_scenario.py                   # Docker test container automation
│
├── docs/                                   # Architecture, model evaluations & screenshots
│   ├── architecture.md                     # Deep technical specifications
│   ├── model_evaluation.md                 # Complete Tier 1 vs Tier 2 evaluation report
│   ├── file_inventory.md                   # Source-to-destination traceability matrix
│   ├── screenshots_ui_batch_b/             # UI telemetry, risk progression & modal screenshots
│   └── screenshots_ui_batch_c/             # Scenario orchestrator & summary screenshots
│
├── scripts/                                # Automated test screenshot capture & utilities
│   ├── capture_batch_b_final_screenshots.py
│   ├── capture_batch_b_final_telemetry_screenshots.py
│   ├── capture_batch_c_screenshots.py
│   ├── capture_metadata_graph_screenshots.py
│   └── capture_preset_simulation.py
│
└── tests/                                  # Comprehensive 27-suite test harness
    ├── test_parser.py                      # Integration tests for Parser V2
    ├── test_prediction.py                  # Unit tests for ML prediction & model loader
    ├── test_rca.py                         # Integration tests for RCA & Remediation
    ├── test_bilstm_inference.py            # BiLSTM v1 inference tests
    ├── test_bilstm2_integration.py         # BiLSTM v2 PyTorch checkpoint integration tests
    ├── test_batch1_graph_impact.py         # Knowledge Graph blast radius tests
    ├── test_batch1_neo4j.py                # Neo4j adapter tests
    ├── test_batch1_provenance.py           # Model provenance & checksum verification
    ├── test_batch2_early_warning.py        # 25% visibility early warning tests
    ├── test_batch2_model_comparison.py     # LR vs SVM vs BiLSTM comparison tests
    ├── test_batch2_risk_progression.py     # Progressive depth risk escalation tests
    ├── test_batch3_e2e_scenarios.py        # End-to-end preset scenario tests
    ├── test_batch3_part_a_rca.py           # RCA causal attribution tests
    ├── test_batch3_part_d_health.py        # Diagnostics & subsystem health tests
    ├── test_demo_flow.py                   # Live CI log streaming simulation tests
    ├── test_ui_batch_b.py                  # Batch B UI integration tests
    └── test_ui_batch_c.py                  # Batch C UI integration tests
```

---

## ⚡ Quickstart & Installation

### 1. Prerequisites
- **Python 3.10+** (tested and verified on Python 3.12.5)
- **Git**
- *(Optional)* **Docker & Neo4j 5.x+** (if enabling live Neo4j graph storage; fallback in-memory graph works out-of-the-box)

### 2. Environment Setup

```bash
# Clone the repository
git clone https://github.com/Aditya-C-S/CI-CD-Failure-Predictor-.git
cd CI-CD-Failure-Predictor-

# Create and activate a virtual environment
python -m venv venv

# On Windows:
.\venv\Scripts\activate

# On Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to create your local `.env`:
```bash
# Windows:
copy .env.example .env

# Linux / macOS:
cp .env.example .env
```

---

## 🚀 Running the Web Application & API

Start the FastAPI application with Uvicorn:

```bash
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

- **Interactive Dashboard:** Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.
- **Interactive OpenAPI Documentation:** Available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
- **Health Check Endpoint:** [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health).

---

## 🧪 Running Automated Tests

Run the full automated test harness with `pytest`:

```bash
# Run core unit and integration tests (prediction, parser, RCA)
pytest tests/test_prediction.py tests/test_parser.py tests/test_rca.py -v

# Run BiLSTM v2 PyTorch deep learning integration tests
pytest tests/test_bilstm2_integration.py -v

# Run Knowledge Graph & Neo4j tests
pytest tests/test_batch1_graph_impact.py tests/test_batch1_neo4j.py tests/test_batch1_provenance.py -v

# Run Multi-Model Comparison & Early Warning tests
pytest tests/test_batch2_early_warning.py tests/test_batch2_model_comparison.py tests/test_batch2_risk_progression.py -v

# Run End-to-End Scenario & System Health tests
pytest tests/test_batch3_e2e_scenarios.py tests/test_batch3_part_d_health.py -v

# Run all test suites
pytest -v
```

---

## 📊 Model Evaluation & Verified Benchmarks

### Task A: Early Failure Prediction (Binary Classification)
Evaluated on group-disjoint, leak-free test sets (1,072 snapshots; 797 failure, 275 success):

| Model Architecture | Visibility Depth | Test F1 (Failure) | Test Precision | Test Recall | PR-AUC | ROC-AUC | Calibration ($ECE$) | Verification Status |
|---|---|---|---|---|---|---|---|---|
| **TF-IDF + Logistic Regression** | **25%** | **0.9719** | **0.9465** | **0.9987** | **0.9917** | **0.9869** | **3.82%** | **Verified Baseline** |
| TF-IDF + Logistic Regression | 50% | 0.9719 | 0.9465 | 0.9987 | 0.9917 | 0.9869 | 3.82% | Verified Baseline |
| TF-IDF + Logistic Regression | 75% | 0.9730 | 0.9487 | 0.9987 | 0.9928 | 0.9886 | 3.65% | Verified Baseline |
| TF-IDF + Logistic Regression | 100% | 0.9760 | 0.9544 | 0.9987 | 0.9945 | 0.9912 | 3.12% | Verified Baseline |
| **TF-IDF + Linear SVM** | **25%** | **0.9719** | **0.9465** | **0.9987** | N/A | N/A | N/A | **Verified Baseline** |
| TF-IDF + Linear SVM | 100% | 0.9760 | 0.9544 | 0.9987 | N/A | N/A | N/A | Verified Baseline |
| **BiLSTM v2 (Two-Stage + ConvStem)** | **25%** | **0.9680** | **0.9420** | **0.9950** | **0.9880** | **0.9820** | **4.10%** | **Verified Checkpoint** |
| BiLSTM v2 (Two-Stage + ConvStem) | 100% | 0.9740 | 0.9510 | 0.9970 | 0.9920 | 0.9890 | 3.40% | Verified Checkpoint |

### Task B: Failure Category Diagnosis (Multi-Class)
- **F1 Syntax Error:** 0.98+ F1
- **F2 Dependency Error:** 0.97+ F1
- **F3 Pytest / Unit Test Failure:** 0.97+ F1
- **F4 Timeout & Hangs:** 0.96+ F1
- **F5 Container & Environment Glitch:** 0.95+ F1

---

## 🌐 REST API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the Glassmorphic Dashboard UI |
| `GET` | `/api/health` | Comprehensive multi-subsystem diagnostic health check |
| `POST` | `/api/predict` | Runs ML failure prediction on raw log text at specified visibility depth |
| `POST` | `/api/rca` | Runs Parser V2 and 5-category RCA causal attribution |
| `POST` | `/api/demo/runs/simulate` | Simulates full end-to-end CI pipeline run with live progressive updates |
| `GET` | `/api/demo/runs` | Lists persisted demo runs |
| `GET` | `/api/demo/runs/{run_id}` | Retrieves full diagnostic telemetry and RCA for a specific run |
| `POST` | `/api/demo/runs/{run_id}/logs` | Progressively streams real or synthetic log lines into a run |
| `GET` | `/api/demo/scenarios` | Lists preset demo scenarios (F1-F7, Clean Success, High-Blast-Radius) |
| `GET` | `/api/metadata/topology` | Retrieves repository AST and module dependency knowledge graph |
| `GET` | `/api/metadata/blast-radius` | Calculates blast radius and downstream failure risk for a modified file |

---

## 🔒 Security & Code Integrity

- **Environment Secrets:** Protected via `.gitignore`; credentials are never committed.
- **Log Sanitization:** Regex-based prefix invariance removes timestamps, absolute filesystem paths, runner IDs, and ANSI codes before model ingestion to guarantee zero data leakage.
- **Sandboxed Execution:** Safe, read-only AST parsing prevents arbitrary code execution when inspecting external repositories.

---

## 👥 Contributors & Capstone Information

- **Aditya C S** — Project Lead, Architecture, Early Failure Prediction Engine, Parser V2, RCA Engine, Web Dashboard, Neo4j Graph Integration
- Final-Year Capstone Project &bull; Automated Software Engineering &bull; 2026
