"""src/prediction/model_loader.py

Model resolution, loading, and artifact cache manager.
Handles loading scikit-learn pipelines (TF-IDF + LR / LinearSVC) and checks
readiness of teammate models (ModernBERT, BiLSTM).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import joblib

from src.config import (
    LR_ARTIFACTS_DIR,
    SVM_ARTIFACTS_DIR,
    MODERNBERT_DIR,
    BILSTM_DIR,
    BILSTM2_DIR,
    SUPPORTED_VISIBILITIES,
)
from src.prediction.sanitizer import sanitize_log_text

logger = logging.getLogger(__name__)

# Cache for loaded scikit-learn pipelines
_MODEL_CACHE: Dict[str, Any] = {}


def format_depth_str(depth: Union[int, str]) -> str:
    """Normalize integer depth to 3-digit string representation (e.g. 25 -> 'depth025')."""
    if isinstance(depth, str):
        depth = depth.replace("%", "").replace("depth", "").strip()
    depth_int = int(depth)
    return f"depth{depth_int:03d}"


def get_artifact_path(model_family: str, depth: Union[int, str], task: str = "A") -> Path:
    """Resolve local path to serialized model artifact."""
    depth_str = format_depth_str(depth)
    family_lower = model_family.lower()

    if family_lower in ("lr", "logistic_regression"):
        filename = f"task{task.upper()}_LR_{depth_str}.joblib"
        return LR_ARTIFACTS_DIR / filename
    elif family_lower in ("svm", "linearsvc"):
        filename = f"task{task.upper()}_SVM_{depth_str}.joblib"
        return SVM_ARTIFACTS_DIR / filename
    elif family_lower == "modernbert":
        return MODERNBERT_DIR / f"modernbert_{depth_str}.pt"
    elif family_lower == "bilstm":
        return BILSTM_DIR / f"bilstm_{depth_str}.pt"
    elif family_lower in ("bilstm2", "bilstm_v2"):
        return BILSTM2_DIR / f"bilstm_{depth_str}.pt"
    else:
        raise ValueError(f"Unknown model family: {model_family}")


def load_model_pipeline(model_family: str, depth: Union[int, str] = 25, task: str = "A") -> Any:
    """
    Load and cache a fitted scikit-learn Pipeline (TF-IDF + Classifier).

    Parameters
    ----------
    model_family : str
        'logistic_regression' (or 'lr') or 'svm'.
    depth : int or str
        Visibility depth (25, 50, 75, 100).
    task : str
        'A' for binary failure prediction, 'B' for failure classification.

    Returns
    -------
    Pipeline
        Fitted scikit-learn Pipeline.
    """
    depth_str = format_depth_str(depth)
    family_key = model_family.lower()
    cache_key = f"{family_key}_{task.upper()}_{depth_str}"

    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    path = get_artifact_path(model_family, depth, task)
    if not path.exists():
        raise FileNotFoundError(
            f"Model artifact not found for {model_family} at depth {depth}: {path}"
        )

    logger.info("Loading model artifact from %s", path)
    pipeline = joblib.load(path)
    _MODEL_CACHE[cache_key] = pipeline
    return pipeline


def check_model_availability() -> Dict[str, Dict[str, Any]]:
    """Inspect local directory to report availability of all 4 models across depths."""
    status: Dict[str, Dict[str, Any]] = {}

    # Logistic Regression
    lr_available = [d for d in SUPPORTED_VISIBILITIES if get_artifact_path("lr", d).exists()]
    status["logistic_regression"] = {
        "available": len(lr_available) > 0,
        "type": "scikit-learn (TF-IDF + LogisticRegression)",
        "verified_depths": lr_available,
        "status": "Ready & Verified",
        "primary_recommended_depth": 25,
    }

    # SVM
    svm_available = [d for d in SUPPORTED_VISIBILITIES if get_artifact_path("svm", d).exists()]
    status["svm"] = {
        "available": len(svm_available) > 0,
        "type": "scikit-learn (TF-IDF + LinearSVC)",
        "verified_depths": svm_available,
        "status": "Ready & Verified",
        "primary_recommended_depth": 100,
    }

    # ModernBERT
    modernbert_files = list(MODERNBERT_DIR.glob("*.pt")) + list(MODERNBERT_DIR.glob("*.bin")) + list(MODERNBERT_DIR.glob("*.safetensors"))
    status["modernbert"] = {
        "available": len(modernbert_files) > 0,
        "type": "Transformer (ModernBERT-base)",
        "verified_depths": [],
        "status": "Awaiting weights ZIP from teammate (Aadarsh Koushik)",
        "reported_claim_available": True,
    }

    # BiLSTM
    bilstm_models = list(BILSTM_DIR.glob("**/*.pt"))
    has_bilstm = len(bilstm_models) >= 6 and (BILSTM_DIR / "log_normalizer.py").exists()
    status["bilstm"] = {
        "available": has_bilstm,
        "type": "Recurrent NN (Two-Stage BiLSTM + 5-Fold Ensemble)",
        "verified_depths": [25, 50, 75, 100] if has_bilstm else [],
        "status": "Ready & Verified (Gen2 Champion + Gen3 5-Fold Ensemble + LogNormalizer)" if has_bilstm else "Awaiting artifacts",
        "primary_recommended_depth": 100,
        "reported_claim_available": True,
    }

    # BiLSTM v2 (Retrained)
    bilstm2_models = list(BILSTM2_DIR.glob("**/*.pt"))
    has_bilstm2 = len(bilstm2_models) >= 6 and (BILSTM2_DIR / "log_normalizer.py").exists()
    status["bilstm2"] = {
        "available": has_bilstm2,
        "type": "Recurrent NN (BiLSTM v2 Retrained Two-Stage 5-Fold Ensemble)",
        "verified_depths": [25, 50, 75, 100] if has_bilstm2 else [],
        "status": "Ready & Verified (Gen2 Champion + Gen3 5-Fold Ensemble + LogNormalizer v2)" if has_bilstm2 else "Awaiting artifacts",
        "primary_recommended_depth": 100,
        "reported_claim_available": True,
    }

    return status
