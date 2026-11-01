# CI/CD Failure Prediction System

A comprehensive, AI-powered failure prediction pipeline that analyzes commit metadata, builds a code dependency graph, and performs root cause analysis (RCA) on CI/CD build failures.

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Model Artifacts](#model-artifacts)
8. [Neo4j Setup](#neo4j-setup)
9. [Running Components](#running-components)
10. [Running the Complete Pipeline](#running-the-complete-pipeline)
11. [Testing Local Commits](#testing-local-commits)
12. [Understanding Output](#understanding-output)
13. [Troubleshooting](#troubleshooting)
14. [Security](#security)
15. [Limitations](#limitations)

---

## Project Overview

This system solves the problem of **predicting CI/CD build failures before they happen**. It combines three complementary approaches:

1. **Metadata-based prediction**: Analyzes commit metadata (churn, test coverage, team size, etc.) using a calibrated LightGBM model to estimate failure probability.
2. **Graph-based investigation**: Builds a code dependency graph from source code and identifies suspicious files that might be impacted by changes.
3. **Root cause analysis**: Correlates predicted risk with specific code changes and dependency relationships to explain why a commit is risky.

### Key Features

- **Fast inference**: ~3.4ms per commit prediction
- **Explainability**: SHAP drivers show which features pushed risk up or down
- **Repository isolation**: Graph data for different projects never mix
- **Flexible input**: Supports both public repositories and local-only commits
- **Production gating**: Built-in verdicts (FAST-TRACK, STANDARD GATE, ALERT, PRE-MERGE BLOCK)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR (ORC)                             │
│                                                                       │
│  Entry: python -m src.main owner/repo <target_sha>                 │
│                     [--repo-path <path>] [--base-sha <sha>]        │
└────────────┬──────────────────────────────────┬─────────────────────┘
             │                                  │
             ▼                                  ▼
    ┌─────────────────────┐          ┌──────────────────────┐
    │ METADATA PIPELINE   │          │  GRAPH ENGINE        │
    │ (Module I)          │          │                      │
    │                     │          │  - Parser (TS)       │
    │ 1. Extract 38       │          │  - Neo4j integration │
    │    features         │          │  - CGL framework     │
    │ 2. Run LightGBM     │          │  - RCA analysis      │
    │ 3. Calibrate        │          │                      │
    │ 4. SHAP drivers     │          │  Syncs graph to      │
    │                     │          │  target_sha,         │
    │ Result: Probability,│          │  identifies files    │
    │ verdict, drivers    │          │  affected by change  │
    └─────────────────────┘          └──────────────────────┘
             │                                  │
             └──────────────┬───────────────────┘
                            ▼
             ┌──────────────────────────────┐
             │   If Risk >= Threshold:      │
             │   Investigate Connected      │
             │   Files (from graph)         │
             └──────────────────────────────┘
                            │
                            ▼
             ┌──────────────────────────────┐
             │   FINAL RESULT:              │
             │   - Failure probability      │
             │   - Verdict + description    │
             │   - SHAP top drivers         │
             │   - Graph sync status        │
             │   - Suspicious files (RCA)   │
             └──────────────────────────────┘
```

### Execution Flow

1. **Commit Input**: User provides `owner/repo`, `target_sha`, and optionally `--repo-path` (for local commits) and `--base-sha` (for custom base).

2. **Prediction Phase** (Metadata Pipeline):
   - Fetch commit metadata from GitHub (or local repository)
   - Extract all 38 features (churn, team size, test coverage, etc.)
   - Run through calibrated LightGBM model
   - Compute SHAP feature drivers
   - Return failure probability and verdict

3. **Graph Synchronization Phase** (Graph Engine):
   - Parse all source files in target commit
   - Update Neo4j with code structure (files, functions, classes, calls)
   - Record commit provenance for verification
   - Identify files changed between base and target commits

4. **Investigation Phase** (if risk meets threshold):
   - Query Neo4j for files connected to changed files
   - Rank by evidence (direct changes, dependencies, graph connections)
   - Return top suspicious files with reasons

5. **Output**: Final `CommitPredictionResult` with all details (probability, verdict, drivers, sync status, suspicious files).

---

## Directory Structure

```
cicd/
├── README.md                          ← This file (main guide)
├── SETUP_CHECKLIST.md                 ← Quick setup checklist
│
├── orc/                               ← ORCHESTRATOR
│   ├── src/
│   │   ├── main.py                    (CLI entry point)
│   │   ├── orchestrator.py            (Main orchestration logic)
│   │   ├── adapters/
│   │   │   ├── metadata_adapter.py    (Bridge to Metadata Pipeline)
│   │   │   └── graph_adapter.py       (Bridge to Graph Engine)
│   │   ├── models/
│   │   │   └── result.py              (Result data structures)
│   │   ├── storage/
│   │   │   └── checkpoint.py          (Caching/resume support)
│   │   └── errors/
│   │       └── exceptions.py          (Custom exceptions)
│   ├── tests/                         (Unit and integration tests)
│   ├── requirements.txt               (All dependencies)
│   ├── .env.example                   (Configuration template)
│   └── .env                           (Your local configuration - DO NOT COMMIT)
│
├── Metadata-Pipeline-main/            ← METADATA PIPELINE (Module I)
│   ├── run_pipeline.py                (Interactive CLI entry point)
│   ├── requirements.txt               (Dependencies for this component)
│   ├── .env.example                   (Configuration template)
│   ├── .env                           (Your local configuration - DO NOT COMMIT)
│   │
│   ├── Metadata_Extractor/            (Feature extraction)
│   │   ├── main.py                    (Extraction orchestration)
│   │   └── core/
│   │       ├── git_engine.py          (Git churn metrics)
│   │       ├── github_api.py          (GitHub metadata)
│   │       ├── static_analyzer.py     (Code complexity analysis)
│   │       └── ci_analyzer.py         (CI/CD metrics)
│   │
│   ├── Inference_Engine/              (Model inference)
│   │   ├── predictor_service.py       (LightGBM + calibration + SHAP)
│   │   ├── state_manager.py           (Webhook state tracking)
│   │   └── cli_server.py              (FastAPI webhook server)
│   │
│   └── Metadata Model/                (Trained model artifacts)
│       └── Models/
│           └── run_YYYYMMDD_HHMMSS/   (Latest trained model)
│               ├── base_lightgbm_model.joblib
│               ├── calibrated_metadata_model.joblib
│               ├── shap_explainer.joblib
│               └── threshold_matrix_full.json
│
└── graph-doc-gen-main/                ← GRAPH ENGINE
    ├── cli.py                         (CLI entry point: parse, update, etc.)
    ├── requirements.txt               (Dependencies for this component)
    ├── .env.example                   (Configuration template)
    ├── .env                           (Your local configuration - DO NOT COMMIT)
    │
    ├── code_parser/
    │   └── extractor.py               (Tree-sitter code parsing)
    │
    ├── database/
    │   └── neo4j_client.py            (Neo4j connection + queries)
    │
    ├── enrichment/                    (Optional: CGL, clustering)
    │   ├── cgl.py                     (Continual Graph Learning)
    │   └── clustering.py              (Community detection)
    │
    ├── maintenance/                   (Utilities)
    │   ├── diff_agent.py              (Commit diff analysis)
    │   ├── git_utils.py               (Git operations)
    │   └── repo_utils.py              (Repository utilities)
    │
    └── tests/
        └── ... (component tests)
```

### Key Points

- **Three independent projects**, coordinated by ORC
- **No file duplication**: Each component is self-contained
- **Configuration files**: Each component has `.env` for local settings
- **Model artifacts**: Stored in `Metadata Model/Models/run_YYYYMMDD_HHMMSS/`
- **Neo4j data**: Isolated by repository ID; no cross-repo contamination

---

## Prerequisites

### System Requirements

- **OS**: Windows 10 or later (or any Windows Server version)
- **Architecture**: x64 (64-bit)
- **Disk Space**: ~5 GB (depends on repository size and caches)
- **RAM**: 8 GB minimum, 16 GB recommended

### Required Software

| Software | Version | Purpose | How to Install |
|----------|---------|---------|-----------------|
| **Python** | 3.9 - 3.13 | Runtime environment | [python.org](https://www.python.org/downloads/) |
| **Git** | 2.30+ | Repository operations | [git-scm.com](https://git-scm.com/download/win) |
| **Neo4j** | 5.25.0 (exact) | Graph database | [neo4j.com/download](https://neo4j.com/download/) |
| **LightGBM** | 4.0.0+ | ML inference | Installed via pip |
| **scikit-learn** | 1.3.0+ | ML utilities | Installed via pip |
| **SHAP** | 0.42.0+ | Feature attribution | Installed via pip |

### Optional Software

| Software | Purpose | Installation |
|----------|---------|---------------|
| **ngrok** | Webhook tunneling (for Metadata Pipeline webhook mode) | [ngrok.com](https://ngrok.com/download) or pip |
| **Docker** | Neo4j in container (alternative to local install) | [docker.com](https://www.docker.com/products/docker-desktop) |
| **VS Code** | IDE for editing/debugging | [code.visualstudio.com](https://code.visualstudio.com/) |

---

## Installation

### Step 1: Verify Python Version

```powershell
# Check installed Python version (must be 3.9 - 3.13)
python --version

# If not installed or version is wrong, download from python.org
# Make sure to check "Add Python to PATH" during installation
```

### Step 2: Verify Git Installation

```powershell
git --version

# If not installed, download from git-scm.com
```

### Step 3: Set Up Python Virtual Environment

It's recommended to use a single shared virtual environment since all components have compatible dependencies:

```powershell
# Navigate to the cicd directory
cd c:\path\to\cicd

# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\Activate.ps1

# If you get an execution policy error, run:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 4: Install All Dependencies

```powershell
# Ensure you're in the virtual environment (should see (venv) in your prompt)

# Install ORC dependencies
pip install -r orc\requirements.txt

# Verify all packages installed successfully
pip list | findstr -E "neo4j|tree-sitter|lightgbm|scikit-learn|shap|pandas"
```

### Step 5: Verify Critical Imports

```powershell
# Test that all imports work
python -c "
from pathlib import Path
import sys

# Test ORC imports
sys.path.insert(0, str(Path('orc/src')))
from orchestrator import Orchestrator
print('[✓] ORC imports OK')

# Test Metadata Pipeline imports
sys.path.insert(0, str(Path('Metadata-Pipeline-main')))
from Inference_Engine.predictor_service import PredictorService
print('[✓] Metadata Pipeline imports OK')

# Test Graph Engine imports
sys.path.insert(0, str(Path('graph-doc-gen-main')))
from database.neo4j_client import Neo4jClient
print('[✓] Graph Engine imports OK')
"
```

### Step 6: Install Neo4j

#### Option A: Local Neo4j Community Edition (Recommended for Development)

1. Download from [neo4j.com/download](https://neo4j.com/download/)
2. Choose **Community Edition** (free), version **5.25.0**
3. Extract to a location (e.g., `C:\Neo4j\neo4j-community-5.25.0`)
4. Start Neo4j:
   ```powershell
   cd C:\Neo4j\neo4j-community-5.25.0\bin
   .\neo4j.bat console
   ```
5. Verify it's running: Open `http://localhost:7474` in your browser
6. Login with default credentials (neo4j / neo4j) and change password
7. **Important**: Write down your new password, you'll need it in `.env`

#### Option B: Docker Container (Recommended for Production)

```powershell
# Pull and run Neo4j 5.25.0 in Docker
docker run -d `
  --name neo4j-graphdoc `
  -p 7687:7687 `
  -p 7474:7474 `
  -e NEO4J_AUTH=neo4j/your_password_here `
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes `
  neo4j:5.25.0-community

# Verify it's running
docker ps | findstr neo4j-graphdoc
```

#### Option C: Existing Remote Neo4j Instance

If you already have a Neo4j server running on another machine:
- Note the hostname/IP and bolt port (usually 7687)
- You'll configure this in `.env`

---

## Configuration

### Step 1: Create `.env` Files

Copy the example templates and fill in your actual values. **Never commit real `.env` files to version control.**

```powershell
cd c:\path\to\cicd

# ORC
Copy-Item orc\.env.example orc\.env
# Edit with your text editor: notepad orc\.env

# Metadata Pipeline
Copy-Item Metadata-Pipeline-main\.env.example Metadata-Pipeline-main\.env
# Edit with your text editor

# Graph Engine
Copy-Item graph-doc-gen-main\.env.example graph-doc-gen-main\.env
# Edit with your text editor
```

### Step 2: Configure GitHub Token

You need a GitHub Personal Access Token to access repositories. The token must have at least the `repo` scope to read repositories.

**To create a token:**
1. Go to https://github.com/settings/personal-access-tokens/new
2. Select **Repository access**: "Only select repositories" (choose the repos you want to analyze)
3. Select **Permissions**: 
   - Repository permissions: `Contents: Read-only`
   - Account permissions: (not needed for basic use)
4. Click **Generate token**
5. **Copy the token immediately** (you can't see it again)

**To update `.env` files:**

```powershell
# Edit orc\.env
# Find: GITHUB_TOKEN=your_github_pat_here
# Replace with your actual token starting with "github_pat_"

# Edit Metadata-Pipeline-main\.env
# Find: GITHUB_TOKEN=your_github_pat_here
# Replace with same token
```

### Step 3: Configure Neo4j Connection

Update the three `.env` files with Neo4j connection details:

```ini
# If Neo4j is running locally on default port:
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_new_neo4j_password

# If Neo4j is on another machine (replace hostname and port):
NEO4J_URI=bolt://neo4j-server.example.com:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
```

**Important**: Make sure all three `.env` files have the same Neo4j configuration so they can share the same database.

### Step 4: Verify Configuration

```powershell
# Run the configuration check
python orc\check_neo4j_env.py

# Expected output:
# [NEO4J] URI: bolt://localhost:7687
# [NEO4J] Database: graphdoc
# [NEO4J] Authentication: OK
# [NEO4J] Connection: OK
```

If this fails, check:
- Is Neo4j running? (Open http://localhost:7474 in browser)
- Is the password correct? (Try logging in at http://localhost:7474)
- Is the URI correct? (Should be `bolt://` not `http://`)

---

## Model Artifacts

### What Files Are Needed

The Metadata Pipeline requires three trained model artifacts to run inference:

1. **`calibrated_metadata_model.joblib`** — The calibrated LightGBM model (predicts failure probability in [0.0, 1.0])
2. **`base_lightgbm_model.joblib`** — Base uncalibrated model (used by SHAP)
3. **`shap_explainer.joblib`** — Pre-trained SHAP TreeExplainer (computes feature drivers)

### Location

These files must be present at:
```
Metadata-Pipeline-main/Metadata Model/Models/run_YYYYMMDD_HHMMSS/
```

Where `run_YYYYMMDD_HHMMSS` is the latest trained model run directory.

**The system automatically finds the latest run directory**, so you don't need to update code if models are retrained.

### Verification

```powershell
# Check that model artifacts exist
Get-ChildItem "Metadata-Pipeline-main\Metadata Model\Models" -Recurse -Filter "*.joblib"

# Should output 3 files per run directory:
#   - base_lightgbm_model.joblib
#   - calibrated_metadata_model.joblib
#   - shap_explainer.joblib
```

### If Models Are Missing

Models must be trained before running ORC. The repository should include pre-trained models in the packaged ZIP. If models are missing:

1. Contact the project owner for trained model artifacts
2. Place them in the correct directory structure: `Metadata Model/Models/run_YYYYMMDD_HHMMSS/`
3. Do NOT retrain models unless you have the training script and dataset

### Library Compatibility

The model files are serialized with specific versions of scikit-learn, LightGBM, and SHAP. If you get version mismatch warnings:

```
UserWarning: The joblib version 1.4.0 may not be compatible with...
```

This is usually safe to ignore, but if predictions fail or are clearly wrong, ensure you have compatible versions:

```powershell
# Check installed versions
pip show scikit-learn lightgbm shap | findstr Version
```

Recommended versions:
- scikit-learn: 1.3.0 or later
- lightgbm: 4.0.0 or later
- shap: 0.42.0 or later

---

## Neo4j Setup

### Understanding the Database

Neo4j stores your code dependency graph in a **graph database** (not relational SQL). The graph contains:

- **Nodes**: Files, Functions, Classes, Modules (labeled with `repo_id`)
- **Edges**: CALLS, IMPORTS, CONTAINS relationships
- **Properties**: commit SHA, file paths, signatures, etc.

### Repository Isolation

**Important**: ORC enforces strict repository isolation. This means:

- Each repository is identified by `repo_id` (e.g., `owner/repo`)
- Nodes and edges for different repos never mix
- Clearing a repository only affects that `repo_id`, not others

This prevents accidental contamination when analyzing multiple projects.

### Creating the Graph Database

The graph is stored in a dedicated Neo4j database called **`graphdoc`** (configured in `.env`).

#### Method 1: Using Neo4j Browser (GUI)

1. Open http://localhost:7474 in your browser
2. Login with your Neo4j credentials (default: neo4j / neo4j, then your password)
3. Run this Cypher query to create the database:
   ```cypher
   CREATE DATABASE graphdoc
   ```
4. Verify it exists:
   ```cypher
   SHOW DATABASES
   ```

#### Method 2: Using Neo4j Desktop

1. Open Neo4j Desktop
2. Click **Create** → **Local DBMS**
3. Name it `graphdoc`, set password, accept license
4. Start the DBMS

#### Method 3: Using Docker

When starting Neo4j in Docker, the `graphdoc` database is created automatically if you set the environment variable:

```powershell
docker run -d `
  --name neo4j-graphdoc `
  -p 7687:7687 `
  -p 7474:7474 `
  -e NEO4J_AUTH=neo4j/your_password_here `
  -e NEO4J_INITIAL_DBMS_DEFAULT_DATABASE=graphdoc `
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes `
  neo4j:5.25.0-community
```

### Verifying Neo4j Connection

```powershell
# Test connection before running ORC
python -c "
import os
from neo4j import GraphDatabase

uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
username = os.getenv('NEO4J_USERNAME', 'neo4j')
password = os.getenv('NEO4J_PASSWORD', '')

try:
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    print(f'✓ Connected to {uri}')
    driver.close()
except Exception as e:
    print(f'✗ Connection failed: {e}')
"
```

### Initializing the Database

When ORC first syncs a repository, it automatically initializes the graph:

```powershell
# This will create the first nodes and relationships for owner/repo
python -m orc.src.main owner/repo <target_sha> --repo-path <path>
```

After this, the database is ready. Subsequent runs for the same repo will update incrementally.

### Resetting a Repository

To clear all graph data for a specific repository and start fresh:

```powershell
# WARNING: This deletes all graph data for the repository
python -c "
import os
from neo4j import GraphDatabase

repo_id = 'owner/repo'  # Change to your repo

uri = os.getenv('NEO4J_URI')
username = os.getenv('NEO4J_USERNAME')
password = os.getenv('NEO4J_PASSWORD')
database = os.getenv('NEO4J_DATABASE', 'graphdoc')

driver = GraphDatabase.driver(uri, auth=(username, password))
with driver.session(database=database) as session:
    session.run('MATCH (n {repo_id: \$repo_id}) DETACH DELETE n', repo_id=repo_id)
    print(f'Cleared graph for {repo_id}')
driver.close()
"
```

### Monitoring Graph Size

```powershell
# Check how many nodes exist for a repository
python -c "
import os
from neo4j import GraphDatabase

repo_id = 'owner/repo'  # Change to your repo

uri = os.getenv('NEO4J_URI')
username = os.getenv('NEO4J_USERNAME')
password = os.getenv('NEO4J_PASSWORD')
database = os.getenv('NEO4J_DATABASE', 'graphdoc')

driver = GraphDatabase.driver(uri, auth=(username, password))
with driver.session(database=database) as session:
    result = session.run(
        'MATCH (n {repo_id: \$repo_id}) RETURN COUNT(n) as count',
        repo_id=repo_id
    )
    count = result.single()['count']
    print(f'Nodes for {repo_id}: {count}')
driver.close()
"
```

---

## Running Components

### Component 1: Metadata Pipeline (Module I)

The Metadata Pipeline can run in two modes:

#### Mode 1: Webhook Listener (for owned repositories)

Automatically processes commits as they are pushed to GitHub:

```powershell
# Activate your virtual environment first
.\venv\Scripts\Activate.ps1

# Run in webhook mode
cd Metadata-Pipeline-main
python run_pipeline.py

# Follow the interactive prompts:
# 1. Enter repository URL (e.g., owner/repo)
# 2. Choose mode: [1] Webhook Listener
# 3. Enter local port (default 5000)
# 4. Optionally run baseline prediction on latest commit

# The server will:
# - Start a FastAPI server on localhost:5000
# - Create an ngrok tunnel (if NGROK_AUTHTOKEN is set)
# - Register a GitHub webhook (if token has admin rights)
# - Listen for push events
# - Extract features and run predictions automatically
```

#### Mode 2: Passive Poller (for external/3rd-party repositories)

Periodically polls GitHub for new commits:

```powershell
# Activate your virtual environment first
.\venv\Scripts\Activate.ps1

# Run in poller mode
cd Metadata-Pipeline-main
python run_pipeline.py

# Follow the interactive prompts:
# 1. Enter repository URL (e.g., owner/repo)
# 2. Choose mode: [2] Passive Poller
# 3. Enter polling interval in seconds (minimum 5)

# The poller will:
# - Fetch the latest commit periodically
# - Detect new commits via ETag caching (rate-limit friendly)
# - Run predictions for each new commit
# - Print results to terminal
# - Continue monitoring until you press Ctrl+C
```

#### Component Output

The Metadata Pipeline produces:

```
[EXTRACT]   Repo: owner/repo | Branch: main
            Commit: abc1234 (abc1234567...)
            Event: MANUAL

[EXTRACT]   Files touched: 5
            Src churn: 150
            Test churn: 30
            Prev build: Yes

[TRANSFORM] All 38 features validated ✓ | Scaling contracts passed ✓

[INFERENCE] Calibrated Failure Probability: 42.50%
            Raw Score: 0.4250
            Model Latency: 3.245 ms

[SHAP TOP DRIVERS]
  Pushing risk UP:
    + git_diff_src_churn: +0.1523
    + total_files_changed: +0.0892
    + test_to_src_churn_ratio: +0.0645
  Pushing risk DOWN:
    - gh_repo_age: -0.0234
    - log_team_size: -0.0156
    - gh_test_lines_per_kloc: -0.0089

[VERDICT] STANDARD GATE — Proceed with monitoring
```

### Component 2: Graph Engine (graph-doc-gen)

The Graph Engine is usually called by ORC, but you can invoke it directly for testing:

```powershell
# Activate your virtual environment
.\venv\Scripts\Activate.ps1

cd graph-doc-gen-main

# Parse a directory (create initial graph)
python cli.py parse C:\path\to\repository --repo-id owner/repo

# Expected output:
# Initializing parsing for C:\path\to\repository (repo_id: 'owner/repo')...
# Extracted 1250 nodes and 2840 edges for 'owner/repo'.
# Parsing and upload complete.
# [PERFORMANCE] Parse time: 3.42s, Upload time: 1.23s

# Update graph incrementally
python cli.py update C:\path\to\repository --base-sha abc123 --target-sha def456 --repo-id owner/repo

# Expected output:
# Running incremental update for repo 'owner/repo'...
# Update completed: status=SUCCESS, commit_verified=True, target_sha=def456, files_parsed=45, files_pruned=12
# [PERFORMANCE] Update time: 0.87s
```

### Component 3: ORC Orchestrator (Complete Pipeline)

Run the complete end-to-end pipeline:

```powershell
# Activate your virtual environment
.\venv\Scripts\Activate.ps1

cd orc

# Run ORC on a repository
python -m src.main owner/repo <target_sha>

# Example with a local repository (for testing local commits)
python -m src.main owner/repo abc1234567 --repo-path C:\path\to\repo

# Example with custom base SHA
python -m src.main owner/repo abc1234567 --base-sha xyz9876543

# Output as JSON (for programmatic use)
python -m src.main owner/repo abc1234567 --json
```

---

## Running the Complete Pipeline

### Typical Workflow

```powershell
# 1. Ensure Neo4j is running
# 2. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 3. Run ORC on a commit
cd orc
python -m src.main owner/repo target_sha_here --repo-path path\to\repo

# Example with real values:
python -m src.main DhruvHegde/my-repo 5a3c9d4e2f1b0c9d8e7f6a5b4c3d2e1f --repo-path C:\dev\my-repo
```

### Understanding CLI Arguments

```
python -m src.main REPO_ID TARGET_SHA [OPTIONS]

Positional Arguments:
  REPO_ID              Repository identifier (owner/repo)
  TARGET_SHA           40-character commit SHA to analyze

Optional Arguments:
  --repo-path PATH     Path to local repository (default: current directory)
                       Use this to point to a cloned or local repository
  
  --base-sha SHA       Base commit SHA for diff (default: target_sha~1)
                       If target_sha is a root commit, base is empty tree
  
  --json               Output result as JSON (default: pretty text)
```

### Example Commands

#### Analyze a public GitHub repository (latest commit)

```powershell
# Assumes you have a clone at C:\dev\tensorflow
python -m src.main tensorflow/tensorflow abc1234567890def1234567890def1234567890 `
    --repo-path C:\dev\tensorflow
```

#### Analyze with custom base SHA

```powershell
# Compare two specific commits
python -m src.main myorg/myrepo HEAD~10 `
    --base-sha HEAD~11 `
    --repo-path C:\dev\myrepo
```

#### Export result as JSON

```powershell
# Capture structured output
python -m src.main owner/repo target_sha --json | Out-File result.json

# Parse with jq (if installed)
python -m src.main owner/repo target_sha --json | jq '.failure_probability'
```

---

## Testing Local Commits

The system supports analyzing **unpushed, local-only commits** without requiring them to be pushed to GitHub. This is useful for testing changes before committing.

### Step 1: Prepare a Local Test Repository

```powershell
# Clone or create a repository
git clone https://github.com/owner/repo C:\dev\test-repo
cd C:\dev\test-repo

# Create a new branch
git checkout -b test-feature

# Make some code changes
# (Edit files, add tests, etc.)

# Stage and commit (locally, not pushed)
git add .
git commit -m "Test: add new feature"

# Get your commit SHA
git rev-parse HEAD
# Output: abc1234567890def1234567890def1234567890 (save this)

# Get parent SHA (base)
git rev-parse HEAD~1
# Output: xyz9876543210abc9876543210abc9876543210 (save this)
```

### Step 2: Run ORC on the Local Commit

```powershell
cd orc

# Analyze the local commit
python -m src.main owner/repo abc1234567890def1234567890def1234567890 `
    --repo-path C:\dev\test-repo `
    --base-sha xyz9876543210abc9876543210abc9876543210
```

### Step 3: Verify Processing

The system will:

1. **Extract features** from the local commit (no GitHub API call)
2. **Run prediction** using the local commit's metadata
3. **Sync graph** by checking out the exact commit in a temporary working copy
4. **Investigate** suspicious files connected to your changes

Expected output:

```
[PREDICTION]
  Failure Probability: 28.50%
  Verdict: FAST-TRACK
  Latency: 3.2ms

[GRAPH SYNC]
  Status: SYNCHRONIZED
  Files Added: 2
  Files Modified: 5
  Files Deleted: 0

[SUSPICIOUS FILES]
  None (risk is below investigation threshold or already cached)
```

### Important Notes on Local Commits

- **GitHub API not required**: The system extracts metadata locally, so you don't need to push
- **Git required**: The local repository must be a valid Git repository
- **Base SHA required**: You should provide `--base-sha` for accurate diff analysis
- **Graph sync still happens**: Even unpushed commits are added to the graph for investigation
- **Cache behavior**: Subsequent runs use cached results; explicit `--force` may be needed to recompute

---

## Understanding Output

### Prediction Result

Each ORC run produces a `CommitPredictionResult` with:

#### Failure Probability

A calibrated score in [0.0, 1.0] representing the estimated probability that the commit will cause a CI/CD build failure.

- **0.0 (0%)**: Build will almost certainly pass
- **0.5 (50%)**: Equal chance of pass or fail
- **1.0 (100%)**: Build will almost certainly fail

#### Verdict

A gating decision based on failure probability thresholds:

| Verdict | Probability Range | Meaning |
|---------|-------------------|---------|
| **FAST-TRACK** | < 0.25 (< 25%) | Low risk, proceed with accelerated testing |
| **STANDARD GATE** | 0.25 - 0.50 (25-50%) | Moderate risk, proceed with standard checks |
| **ALERT** | 0.50 - 0.65 (50-65%) | Elevated risk, flag for manual review |
| **PRE-MERGE BLOCK** | > 0.65 (> 65%) | High risk, halt expensive runners or block merge |

#### SHAP Drivers

SHAP feature attribution shows which features had the **biggest impact** on the prediction:

**Positive drivers** (pushing risk UP):
```
+ git_diff_src_churn: +0.1523        (High source code changes)
+ total_files_changed: +0.0892       (Many files modified)
+ test_to_src_churn_ratio: +0.0645   (Few tests relative to code)
```

**Negative drivers** (pushing risk DOWN, mitigating):
```
- gh_repo_age: -0.0234               (Mature repository)
- log_team_size: -0.0156             (Larger team = more experience)
- gh_test_lines_per_kloc: -0.0089    (Good test coverage)
```

The top-3 of each are shown to explain why the model made this prediction.

### Graph Synchronization

Reports the status of code graph update:

| Field | Meaning |
|-------|---------|
| **Status** | `SYNCHRONIZED` (success) or error message |
| **Files Added** | Count of new files in target commit |
| **Files Modified** | Count of changed files |
| **Files Deleted** | Count of removed files |
| **Files Renamed** | Count of renamed files |

### Suspicious Files (RCA)

When failure probability meets the investigation threshold (default 0.50), ORC identifies files that:

1. **Were directly changed** in the commit (highest confidence)
2. **Depend on changed files** via calls or imports (medium confidence)
3. **Are connected in the graph** to changed files (lower confidence)

Each suspicious file shows:

- **File path**: Relative path in repository
- **Centrality score**: 1.0 (direct), 0.7 (dependency), or lower (graph-connected)
- **Reasons**: Evidence for why it's suspicious

Example:

```
[SUSPICIOUS FILES] (8 found)
  1. src/core/predictor.py (score: 1.0)
     • Directly modified in commit
  2. src/api/handler.py (score: 0.7)
     • Connected via CALLS relationship
  3. src/utils/helpers.py (score: 0.7)
     • Connected via IMPORTS relationship
```

### Processing Metrics

- **Latency**: Time in milliseconds for prediction computation
- **Cache status**: Whether results were reused or computed fresh
- **Parse time**: Time to extract code structure
- **Upload time**: Time to write to Neo4j

---

## Troubleshooting

### Python Version Mismatch

**Error**: `tree_sitter: no module named tree_sitter`

**Cause**: Tree-sitter binary wheels are compiled for specific Python versions (3.9-3.13, Windows x64).

**Solution**:
```powershell
# Check Python version
python --version

# Must be 3.9, 3.10, 3.11, 3.12, or 3.13
# If different, install the correct version from python.org

# Reinstall tree-sitter packages with matching Python version
pip install --force-reinstall tree-sitter tree-sitter-python tree-sitter-java tree-sitter-cpp
```

### Missing Python Packages

**Error**: `ModuleNotFoundError: No module named 'neo4j'`

**Cause**: Dependencies not installed in virtual environment.

**Solution**:
```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Reinstall all dependencies
pip install -r orc\requirements.txt

# Verify
pip list | findstr neo4j
```

### Model Artifact Not Found

**Error**: `FileNotFoundError: No trained model found.`

**Cause**: Model files missing or in wrong location.

**Solution**:
```powershell
# Check that model files exist
Get-ChildItem "Metadata-Pipeline-main\Metadata Model\Models" -Recurse -Filter "*.joblib"

# Should see 3 .joblib files in a run_YYYYMMDD_HHMMSS directory

# If missing, contact the project owner for trained models
# Place them at: Metadata-Pipeline-main\Metadata Model\Models\run_YYYYMMDD_HHMMSS\
```

### scikit-learn or LightGBM Version Warning

**Error**: `UserWarning: The joblib version may not be compatible with LightGBM...`

**Cause**: Model was trained with different library versions.

**Solution**:
```powershell
# Usually safe to ignore, but if predictions are wrong, reinstall matching versions
pip install --upgrade scikit-learn==1.3.0 lightgbm==4.0.0 joblib==1.3.0
```

### Git Executable Not Found

**Error**: `FileNotFoundError: [WinError 2] The system cannot find the file specified` (during `git` operations)

**Cause**: Git not installed or not in PATH.

**Solution**:
```powershell
# Check if Git is installed
git --version

# If not found, install from https://git-scm.com/download/win
# During installation, choose "Add Git to PATH"

# If installed but still not found, add to PATH manually
$env:PATH += ";C:\Program Files\Git\cmd"

# Verify
git --version
```

### Invalid Commit SHA

**Error**: `InvalidCommitException: Commit abc1234 not found in owner/repo`

**Cause**: Commit SHA doesn't exist in repository or local repository is not properly cloned.

**Solution**:
```powershell
# Verify the commit exists
cd C:\path\to\repo
git log --oneline | findstr abc1234

# If not found, pull latest
git pull origin main

# Or use full 40-character SHA
git rev-parse abc1234567890def1234567890def1234567890
```

### Local-Only Commit Not Found

**Error**: `RuntimeError: Commit XYZ cannot be resolved from GitHub. Trying local resolution... Not found locally either.`

**Cause**: Commit is local but `--repo-path` not provided, or path is wrong.

**Solution**:
```powershell
# Always provide --repo-path for local commits
python -m src.main owner/repo abc1234567 --repo-path C:\path\to\repo

# Verify the path is correct
ls C:\path\to\repo\.git

# Get the correct SHA
cd C:\path\to\repo
git rev-parse HEAD
```

### Neo4j Connection Failed

**Error**: `neo4j.exceptions.ServiceUnavailable: Unable to connect to bolt://localhost:7687`

**Cause**: Neo4j not running or wrong address.

**Solution**:
```powershell
# Check if Neo4j is running
# If using local installation:
cd C:\Neo4j\neo4j-community-5.25.0\bin
.\neo4j.bat console

# If using Docker:
docker ps | findstr neo4j-graphdoc

# If using Neo4j Desktop, start the DBMS from the UI

# Verify connection
python orc\check_neo4j_status.py

# Check .env file for correct URI
cat orc\.env | findstr NEO4J_URI
# Should show: NEO4J_URI=bolt://localhost:7687 (or your server)
```

### Neo4j Authentication Failed

**Error**: `neo4j.exceptions.AuthError: The client is unauthorized due to authentication failure`

**Cause**: Wrong username or password in `.env`.

**Solution**:
```powershell
# Verify Neo4j password by logging in at http://localhost:7474
# Use username "neo4j" and the password you set

# Update .env with correct password
notepad orc\.env
# Find: NEO4J_PASSWORD=
# Replace with correct password (no quotes needed)

# Also update Graph Engine .env
notepad graph-doc-gen-main\.env
```

### Wrong Neo4j Database

**Error**: `GraphSyncException: NEO4J_DATABASE not set. ORC requires explicit targeting of 'graphdoc' database.`

**Cause**: `.env` doesn't have `NEO4J_DATABASE=graphdoc` or it's set to different database.

**Solution**:
```powershell
# Update all .env files
# orc\.env
# Metadata-Pipeline-main\.env (if present)
# graph-doc-gen-main\.env

# Ensure they all have:
NEO4J_DATABASE=graphdoc

# Create the database if it doesn't exist
# Open http://localhost:7474
# Run: CREATE DATABASE graphdoc
```

### Cache-Hit or Cache-Miss Issues

**Error**: `Cache hit but stale data` or results differ between runs

**Cause**: Checkpoint cache is corrupted or outdated.

**Solution**:
```powershell
# Clear cache (will recompute on next run)
rm -Recurse -Force orc\.checkpoints\*

# Rerun the command
python -m src.main owner/repo target_sha
```

### Tree-Sitter Parsing Issues

**Error**: `tree_sitter.binding.query.QueryMatchError` or parse failures

**Cause**: Unsupported language or malformed source code.

**Solution**:
```powershell
# Supported languages: Python, Java, C++
# If analyzing other languages, parsing will fail silently

# Check log for details
python -m src.main owner/repo target_sha 2>&1 | findstr -i parse

# Ensure source code is valid
# Run through a linter (pylint, javac, clang -fsyntax-only)
```

### Windows PowerShell Path and Quoting Issues

**Error**: `Path ... not found` or `unexpected token` errors

**Cause**: Backslashes and spaces in paths need proper escaping in PowerShell.

**Solution**:
```powershell
# Use forward slashes or escaped backslashes
python -m src.main owner/repo abc1234 --repo-path 'C:\path\to\repo'
python -m src.main owner/repo abc1234 --repo-path "C:\path\to\repo"

# Or use Get-ChildItem to build paths
$repo_path = (Get-Item C:\Users\$env:USERNAME\projects\myrepo).FullName
python -m src.main owner/repo abc1234 --repo-path $repo_path
```

---

## Security

### Protecting `.env` Files

`.env` files contain secrets and must **never** be committed or shared:

```powershell
# Add .env to .gitignore
echo ".env" >> .gitignore

# Verify it's ignored
git status | findstr -i ".env"
# Should show no .env files

# Double-check before committing
git diff --cached orc\.env
```

### Managing GitHub Tokens

- **Token scope**: Use minimal scopes (e.g., `repo` for public access)
- **Rotation**: If token is exposed, regenerate immediately at https://github.com/settings/personal-access-tokens
- **Logging**: Don't log the full token; only log the last 4 characters if needed
- **Expiration**: Set token expiration to 90 days and rotate regularly

### Neo4j Authentication

- **Password**: Use a strong, random password (not `primehome`)
- **SSL/TLS**: In production, use encrypted connections (`neo4j+s://` or `neo4j+ssc://`)
- **User isolation**: Create read-only users for different teams
- **Firewall**: Restrict network access to Neo4j port (7687) from known IPs

### Repository Access

- **GitHub tokens**: Use fine-grained tokens scoped to specific repositories if possible
- **Private repos**: Only analyze repos you have permission to access
- **Data retention**: Graph data for private repos should be kept private
- **Audit logs**: Enable audit logging in Neo4j to track access

### Credential Rotation

When moving the project to a new environment:

```powershell
# 1. Create new GitHub PAT with minimal scopes
# 2. Create new Neo4j password (don't reuse from old environment)
# 3. Update .env files with new values
# 4. Test connectivity
# 5. Delete old credentials (revoke tokens, change passwords)
```

---

## Limitations and Known Issues

### Feature Support

| Feature | Status | Notes |
|---------|--------|-------|
| Python repositories | ✓ Supported | Primary language |
| Java repositories | ✓ Supported | Via Tree-sitter Java grammar |
| C++ repositories | ✓ Supported | Via Tree-sitter C++ grammar |
| JavaScript/TypeScript | ✗ Not supported | Grammar not included; can be added |
| Go, Rust, Ruby | ✗ Not supported | Grammars not included; can be added |
| Large repositories (>10k files) | ⚠ Slow | Takes 10-30 seconds for graph update |
| Monorepos | ✓ Supported | Treats as single repository (repo_id scoping) |
| Merge commits | ✓ Supported | Processes merge commits normally |
| Root commits | ✓ Supported | Base SHA is empty tree hash |

### Known Limitations

1. **No Git history traversal**: ORC analyzes individual commits, not full history
2. **Feature extraction time**: Feature extraction adds 1-5 seconds per commit (depends on repo size)
3. **Neo4j performance**: Querying connected files may be slow for dense graphs (>100k nodes)
4. **Model retraining**: Models are pre-trained; retraining requires training dataset and script
5. **Windows-only tree-sitter wheels**: Will not work on Linux or macOS without rebuilding

### Workarounds

- **For more languages**: Add Tree-sitter grammars (see graph-doc-gen documentation)
- **For faster feature extraction**: Use repository cache (enabled by default)
- **For Neo4j performance**: Create Neo4j indexes on `repo_id` and `file_path`
- **For production**: Use remote Neo4j instance for better scalability

---

## Next Steps

1. **Complete the SETUP_CHECKLIST** to verify all components are working
2. **Run a test commit** using the examples in [Running the Complete Pipeline](#running-the-complete-pipeline)
3. **Integrate with CI/CD**: Use Metadata Pipeline webhook mode or ORC CLI in your build system
4. **Monitor predictions**: Track how accurate the verdicts are for your repositories
5. **Tune thresholds**: Adjust `INVESTIGATION_THRESHOLD` based on your risk tolerance

---

## Support and Contributing

For issues, questions, or contributions:

- **GitHub Issues**: Report bugs and request features
- **Documentation**: See individual component READMEs for detailed technical info
- **Model updates**: Contact maintainers for retrained models with different feature sets

---

## License

This project is provided as-is. See the individual component directories for license information.

---

**Created**: October 2026  
**Last Updated**: October 24, 2026
