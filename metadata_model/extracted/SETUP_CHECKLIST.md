# CI/CD Failure Prediction System - Setup Checklist

Follow this checklist to set up the project on a fresh Windows machine. Estimated time: 30-45 minutes.

## Pre-Setup

- [ ] Download and extract the ZIP package to `C:\path\to\cicd\`
- [ ] Verify directory structure:
  ```
  cicd\
  ├── orc\
  ├── Metadata-Pipeline-main\
  ├── graph-doc-gen-main\
  ├── README.md
  └── SETUP_CHECKLIST.md
  ```

---

## Phase 1: System Requirements (5 minutes)

- [ ] **Install Python 3.9 - 3.13** (if not already installed)
  - [ ] Download from https://www.python.org/downloads/
  - [ ] Check "Add Python to PATH" during installation
  - [ ] Verify: `python --version` (should show Python 3.9 - 3.13)

- [ ] **Install Git** (if not already installed)
  - [ ] Download from https://git-scm.com/download/win
  - [ ] Verify: `git --version`

- [ ] **Install Neo4j Community 5.25.0**
  - [ ] Option A (Local): Download from https://neo4j.com/download/ and extract
  - [ ] Option B (Docker): `docker run -d --name neo4j-graphdoc -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/password neo4j:5.25.0-community`
  - [ ] Verify it's running: Open http://localhost:7474 in browser

---

## Phase 2: Python Environment Setup (10 minutes)

### Step 1: Open Terminal

```powershell
# Open PowerShell as Administrator
# Navigate to the project
cd C:\path\to\cicd
```

### Step 2: Create Virtual Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\Activate.ps1

# If you get an execution policy error, run:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- [ ] You should see `(venv)` in your command prompt

### Step 3: Install Dependencies

```powershell
# Ensure you're in the virtual environment (should see (venv) in prompt)

# Install all dependencies
pip install -r orc\requirements.txt

# This may take 5-10 minutes on first install
```

- [ ] Wait for installation to complete without errors
- [ ] Verify key packages: `pip list | findstr -E "neo4j|tree-sitter|lightgbm"`

---

## Phase 3: Configuration Setup (10 minutes)

### Step 1: Create `.env` Files

```powershell
# Copy templates to .env files
Copy-Item orc\.env.example orc\.env
Copy-Item Metadata-Pipeline-main\.env.example Metadata-Pipeline-main\.env
Copy-Item graph-doc-gen-main\.env.example graph-doc-gen-main\.env
```

- [ ] All three `.env` files created

### Step 2: Configure GitHub Token

1. [ ] Create GitHub Personal Access Token:
   - Go to https://github.com/settings/personal-access-tokens/new
   - Select repository scope
   - Select "Contents: Read-only"
   - Generate and copy token (starts with `github_pat_`)

2. [ ] Edit all three `.env` files:
   ```powershell
   # Edit ORC .env
   notepad orc\.env
   # Find: GITHUB_TOKEN=your_github_pat_here
   # Replace with your token
   
   # Edit Metadata Pipeline .env
   notepad Metadata-Pipeline-main\.env
   # Same replacement
   
   # Graph Engine doesn't need GitHub token, but can be left empty
   ```

- [ ] All three `.env` files have your GitHub token

### Step 3: Configure Neo4j Connection

1. [ ] Change Neo4j default password:
   - Open http://localhost:7474
   - Login: neo4j / neo4j
   - Change password to something secure (write it down!)

2. [ ] Create Neo4j database:
   ```cypher
   # In Neo4j Browser, run:
   CREATE DATABASE graphdoc
   ```

3. [ ] Update `.env` files with Neo4j credentials:
   ```powershell
   # Edit each file and update:
   # NEO4J_URI=bolt://localhost:7687
   # NEO4J_USERNAME=neo4j
   # NEO4J_PASSWORD=your_new_password_here
   # NEO4J_DATABASE=graphdoc
   ```

- [ ] All three `.env` files have correct Neo4j configuration

### Step 4: Verify Configuration

```powershell
# Activate virtual environment if not already activated
.\venv\Scripts\Activate.ps1

# Test Neo4j connection
python orc\check_neo4j_env.py

# Expected output:
# [NEO4J] URI: bolt://localhost:7687
# [NEO4J] Database: graphdoc
# [NEO4J] Authentication: OK
# [NEO4J] Connection: OK
```

- [ ] `check_neo4j_env.py` runs without errors
- [ ] Connection status shows "OK"

---

## Phase 4: Verify Model Artifacts (2 minutes)

```powershell
# Check that trained models exist
Get-ChildItem "Metadata-Pipeline-main\Metadata Model\Models" -Recurse -Filter "*.joblib"

# Expected: 3 files per run directory
#   - base_lightgbm_model.joblib
#   - calibrated_metadata_model.joblib
#   - shap_explainer.joblib
```

- [ ] All 3 model artifact files present
- [ ] Files are not corrupted (can be opened with joblib)

---

## Phase 5: Component Testing (10 minutes)

### Test 1: Metadata Pipeline

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Test Metadata Pipeline imports
python -c "
from pathlib import Path
import sys
sys.path.insert(0, str(Path('Metadata-Pipeline-main')))
from Inference_Engine.predictor_service import PredictorService
print('[OK] Metadata Pipeline imports work')
"
```

- [ ] No import errors

### Test 2: Graph Engine

```powershell
# Test Graph Engine imports
python -c "
from pathlib import Path
import sys
sys.path.insert(0, str(Path('graph-doc-gen-main')))
from database.neo4j_client import Neo4jClient
print('[OK] Graph Engine imports work')
"
```

- [ ] No import errors

### Test 3: ORC Orchestrator

```powershell
# Test ORC imports
cd orc
python -c "
from src.orchestrator import Orchestrator
print('[OK] ORC imports work')
"
cd ..
```

- [ ] No import errors

---

## Phase 6: Run End-to-End Test (5 minutes)

### Test with a Real Repository

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Run ORC on a public repository (example)
cd orc

# Get a commit SHA from a repo you want to analyze
# Example: https://github.com/DhruvHegde/sample-repo
python -m src.main DhruvHegde/sample-repo abc1234567 --repo-path C:\temp\sample-repo

# Or, if you have a local clone:
python -m src.main owner/repo target_sha --repo-path C:\path\to\repo
```

- [ ] Command runs without errors
- [ ] Prediction result is displayed (probability, verdict, drivers)
- [ ] Graph sync status shows "SYNCHRONIZED"

### Alternative: Test with Local Commit

If you want to test with an unpushed commit:

```powershell
# Prepare a test repository
git clone https://github.com/owner/repo C:\temp\test-repo
cd C:\temp\test-repo

# Make local changes
echo "test" > newfile.txt
git add .
git commit -m "Test commit"

# Get SHAs
$target_sha = (git rev-parse HEAD)
$base_sha = (git rev-parse HEAD~1)

# Run ORC with local repository
cd C:\path\to\cicd\orc
python -m src.main owner/repo $target_sha --repo-path C:\temp\test-repo --base-sha $base_sha
```

- [ ] Prediction runs successfully for local commit
- [ ] No GitHub push required

---

## Phase 7: Optional Enhancements (5 minutes)

### Enable Webhook Mode (Optional)

If you want to use Metadata Pipeline in webhook mode:

1. [ ] Create Ngrok account: https://ngrok.com/
2. [ ] Get auth token from https://dashboard.ngrok.com
3. [ ] Update Metadata-Pipeline-main\.env:
   ```ini
   NGROK_AUTHTOKEN=your_ngrok_token_here
   ```

### Install Docker (Optional)

For production-like deployments:

```powershell
# Download Docker Desktop: https://www.docker.com/products/docker-desktop
# Install and run
docker --version
```

---

## Troubleshooting

### Python Not Found

```powershell
# Install Python from https://www.python.org/downloads/
# Make sure to check "Add Python to PATH"

# Restart PowerShell after installation
# Then verify: python --version
```

### Virtual Environment Not Activating

```powershell
# Try direct path
& '.\venv\Scripts\Activate.ps1'

# If execution policy error:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Or use alternative:
.\venv\Scripts\activate.bat
```

### Neo4j Connection Failed

```powershell
# Check if running
docker ps | findstr neo4j-graphdoc

# Or check Neo4j Desktop is running

# Verify credentials:
# - URI: bolt://localhost:7687
# - Username: neo4j
# - Password: what you set (not "neo4j" if you changed it)
```

### Missing Model Files

```powershell
# Check model directory exists
ls "Metadata-Pipeline-main\Metadata Model\Models"

# Must have at least one run_YYYYMMDD_HHMMSS directory

# If missing, contact project owner for trained models
```

### Tree-Sitter Import Error

```powershell
# Verify Python version is 3.9-3.13
python --version

# Reinstall tree-sitter packages
pip install --force-reinstall tree-sitter tree-sitter-python tree-sitter-java tree-sitter-cpp
```

---

## Final Verification

Before considering setup complete, run this verification script:

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Run verification
python -c "
import sys
from pathlib import Path
import os

print('[VERIFY] Environment Setup')
print(f'Python version: {sys.version}')
print(f'Virtual env: {sys.prefix}')

print('\n[VERIFY] Imports')

# ORC
sys.path.insert(0, 'orc/src')
from orchestrator import Orchestrator
print('✓ ORC imports')

# Metadata Pipeline
sys.path.insert(0, 'Metadata-Pipeline-main')
from Inference_Engine.predictor_service import PredictorService
print('✓ Metadata Pipeline imports')

# Graph Engine
sys.path.insert(0, 'graph-doc-gen-main')
from database.neo4j_client import Neo4jClient
print('✓ Graph Engine imports')

print('\n[VERIFY] Configuration')
from dotenv import load_dotenv
load_dotenv('orc/.env')
github_token = os.getenv('GITHUB_TOKEN')
neo4j_uri = os.getenv('NEO4J_URI')
print(f'✓ GitHub token configured: {github_token[:10]}...')
print(f'✓ Neo4j URI configured: {neo4j_uri}')

print('\n[VERIFY] Model Artifacts')
model_dir = Path('Metadata-Pipeline-main/Metadata Model/Models')
runs = list(model_dir.glob('run_*'))
if runs:
    latest_run = sorted(runs)[-1]
    joblib_files = list(latest_run.glob('*.joblib'))
    print(f'✓ Model run found: {latest_run.name}')
    print(f'✓ Model files: {len(joblib_files)} .joblib files')
else:
    print('✗ No model runs found')

print('\n[SUCCESS] All checks passed! Setup is ready.')
"
```

- [ ] Script runs without errors
- [ ] All 4 checks pass (Imports, Configuration, Model Artifacts, Neo4j Connection)

---

## Next Steps After Setup

1. [ ] Read the main **README.md** for detailed usage instructions
2. [ ] Run your first end-to-end pipeline with a real commit
3. [ ] Test with a local commit (see [Testing Local Commits](README.md#testing-local-commits) in README)
4. [ ] Integrate with your CI/CD pipeline or use webhooks
5. [ ] Monitor predictions and tune investigation threshold if needed

---

## Quick Reference Commands

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Run ORC on a repository
cd orc
python -m src.main owner/repo target_sha --repo-path path\to\repo

# Run with JSON output
python -m src.main owner/repo target_sha --json

# Verify Neo4j connection
python orc\check_neo4j_env.py

# Start Metadata Pipeline (interactive)
cd ..\Metadata-Pipeline-main
python run_pipeline.py

# Parse code directory (Graph Engine)
cd ..\graph-doc-gen-main
python cli.py parse path\to\repo --repo-id owner/repo
```

---

**Estimated Total Time**: 30-45 minutes  
**After Setup**: Ready to analyze commits and predict build failures!
