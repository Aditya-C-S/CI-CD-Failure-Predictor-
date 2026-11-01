"""src/config.py

Central configuration module for the CI/CD Failure Predictor project.
Loads environment variables and establishes canonical filesystem paths.
"""

from __future__ import annotations

import os
from pathlib import Path

# Base Paths
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent

# Load environment variables from project root .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

DEMO_API_KEY = os.getenv("DEMO_API_KEY")

DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_SAMPLES_DIR = DATA_DIR / "samples"
DATA_ARCHIVE_DIR = DATA_DIR / "archive"

MODELS_DIR = PROJECT_ROOT / "models"
LR_DIR = MODELS_DIR / "logistic_regression"
LR_ARTIFACTS_DIR = LR_DIR / "artifacts"
SVM_DIR = MODELS_DIR / "svm"
SVM_ARTIFACTS_DIR = SVM_DIR / "artifacts"
MODERNBERT_DIR = MODELS_DIR / "modernbert"
BILSTM_DIR = MODELS_DIR / "bilstm"
BILSTM2_DIR = MODELS_DIR / "bilstm2"

TESTS_DIR = PROJECT_ROOT / "tests"
DOCS_DIR = PROJECT_ROOT / "docs"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Server / API Configuration
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

# Default Prediction Settings
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "logistic_regression")
DEFAULT_VISIBILITY = int(os.getenv("DEFAULT_VISIBILITY", "25"))
SUPPORTED_VISIBILITIES = [25, 50, 75, 100]

# Supported Failure Categories
FAILURE_CATEGORIES = {
    "F1": "syntax_error",
    "F2": "dependency_error",
    "F3": "test_failure",
    "F4": "timeout",
    "F5": "docker_error",
    "F6": "network_io_error",
    "F7": "permission_error",
}
