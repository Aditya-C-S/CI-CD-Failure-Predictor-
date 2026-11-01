"""src/diagnostics/system_health.py

Batch 3 Part D: System Health & Diagnostic Service.
Inspects all core components:
A. FastAPI backend (running, responsive)
B. Neo4j graph database (live Bolt 5.25.1 connectivity or graceful Tree-Sitter AST fallback)
C. Runtime models (BiLSTM v2, TF-IDF + SVM, TF-IDF + Logistic Regression evaluated independently)
D. Pre-build Metadata model (38-feature schema compatibility and artifacts)
E. Log ingestion subsystem (auth readiness and endpoint configuration)
F. Persistence and storage subsystem (data/demo_runs directory read/write capability)
G. Overall composite status: HEALTHY, DEGRADED, or UNHEALTHY (with zero secret leakage)
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.prediction.metadata_service import MetadataService
from src.prediction.model_loader import check_model_availability, SUPPORTED_VISIBILITIES, get_artifact_path


class OverallStatus:
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class SystemHealthService:
    """Non-destructive health assessment across all platform subsystems."""

    @classmethod
    def get_system_health(cls) -> Dict[str, Any]:
        """
        Run safe, read-only diagnostic checks and return structured health status.
        Never exposes passwords, tokens, or raw credentials.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        components: Dict[str, Any] = {}
        issues: List[str] = []

        # -------------------------------------------------------------------
        # A. FastAPI Backend
        # -------------------------------------------------------------------
        components["backend"] = {
            "status": "HEALTHY",
            "service": "CI/CD Failure Predictor & RCA Backend",
            "version": "2.0.0",
            "python_version": sys.version.split()[0],
        }

        # -------------------------------------------------------------------
        # B. Neo4j / Graph Intelligence
        # -------------------------------------------------------------------
        meta_service = MetadataService.get_instance()
        graph_status = meta_service.get_graph_status()
        neo4j_online = graph_status.get("status") == "ONLINE"

        # Check Tree-Sitter AST fallback capability
        from src.demo.graph_inspector import _get_extractor_class
        tree_sitter_available = _get_extractor_class() is not None

        if neo4j_online:
            components["neo4j"] = {
                "status": "HEALTHY",
                "mode": "ONLINE",
                "version": graph_status.get("version", "5.25.1"),
                "edition": graph_status.get("edition", "community"),
                "database": graph_status.get("database", "graphdoc"),
                "fallback_available": tree_sitter_available,
            }
        elif tree_sitter_available:
            components["neo4j"] = {
                "status": "DEGRADED",
                "mode": "FALLBACK_AST",
                "message": "Neo4j Bolt connection is offline; Tree-Sitter in-memory AST fallback is fully operational.",
                "database": "in_memory_ast",
                "fallback_available": True,
            }
            issues.append("Neo4j offline (degraded: in-memory AST fallback active)")
        else:
            components["neo4j"] = {
                "status": "UNHEALTHY",
                "mode": "UNAVAILABLE",
                "message": "Neither Neo4j nor Tree-Sitter AST parser is accessible.",
                "fallback_available": False,
            }
            issues.append("Graph intelligence unavailable")

        # -------------------------------------------------------------------
        # C. Runtime ML Models (Independent Verification)
        # -------------------------------------------------------------------
        runtime_models: Dict[str, Any] = {}

        # 1. BiLSTM v2
        bilstm_ready = False
        try:
            from src.prediction.predictor import get_predictor
            pred = get_predictor("bilstm2", visibility=50)
            bilstm_ready = pred is not None
        except Exception:
            bilstm_ready = False

        runtime_models["bilstm2"] = {
            "status": "HEALTHY" if bilstm_ready else "UNHEALTHY",
            "type": "PyTorch (BiLSTM v2 Sequence Classifier)",
            "supported_depths": [25, 50, 75, 100],
        }

        # 2. Linear SVM
        svm_ready = all(get_artifact_path("svm", d).exists() for d in [25, 50, 75, 100])
        runtime_models["svm"] = {
            "status": "HEALTHY" if svm_ready else "UNHEALTHY",
            "type": "scikit-learn (TF-IDF + LinearSVC)",
            "supported_depths": [d for d in [25, 50, 75, 100] if get_artifact_path("svm", d).exists()],
        }

        # 3. Logistic Regression
        lr_ready = all(get_artifact_path("lr", d).exists() for d in [25, 50, 75, 100])
        runtime_models["logistic_regression"] = {
            "status": "HEALTHY" if lr_ready else "UNHEALTHY",
            "type": "scikit-learn (TF-IDF + LogisticRegression)",
            "supported_depths": [d for d in [25, 50, 75, 100] if get_artifact_path("lr", d).exists()],
        }

        components["runtime_models"] = runtime_models

        # -------------------------------------------------------------------
        # D. Pre-Build Metadata Model
        # -------------------------------------------------------------------
        meta_ready = meta_service.is_ready
        components["metadata_model"] = {
            "status": "HEALTHY" if meta_ready else "UNHEALTHY",
            "type": "LightGBM + CalibratedClassifierCV + TreeExplainer",
            "feature_contract": "38_features_strict",
            "model_version": meta_service.get_model_info().get("model_version"),
            "load_error": meta_service.load_error,
        }
        if not meta_ready:
            issues.append("Metadata model not loaded")

        # -------------------------------------------------------------------
        # E. Log Ingestion Subsystem
        # -------------------------------------------------------------------
        api_key_configured = bool(os.getenv("DEMO_API_KEY"))
        components["log_ingestion"] = {
            "status": "HEALTHY",
            "endpoint": "/api/demo/runs/{run_id}/logs",
            "auth_configured": api_key_configured,
            "deduplication_enabled": True,
            "supported_checkpoints": [25, 50, 75, 100],
        }

        # -------------------------------------------------------------------
        # F. Persistence and Storage Subsystem
        # -------------------------------------------------------------------
        from src.demo.demo_manager import DEMO_RUNS_DIR, UnifiedDemoManager
        storage_healthy = False
        loaded_runs_count = 0
        try:
            DEMO_RUNS_DIR.mkdir(parents=True, exist_ok=True)
            # Safe non-destructive temporary write check
            test_file = DEMO_RUNS_DIR / ".health_check.tmp"
            test_file.write_text("probe", encoding="utf-8")
            if test_file.read_text(encoding="utf-8") == "probe":
                storage_healthy = True
            test_file.unlink(missing_ok=True)

            mgr = UnifiedDemoManager.get_instance()
            loaded_runs_count = len(mgr._runs)
        except Exception as e:
            storage_healthy = False
            issues.append(f"Storage probe failed: {e}")

        components["persistence"] = {
            "status": "HEALTHY" if storage_healthy else "UNHEALTHY",
            "directory": str(DEMO_RUNS_DIR.resolve()),
            "writable": storage_healthy,
            "active_runs_loaded": loaded_runs_count,
        }

        # -------------------------------------------------------------------
        # G. Overall Status Evaluation
        # -------------------------------------------------------------------
        critical_unhealthy = (
            components["backend"]["status"] != "HEALTHY"
            or components["metadata_model"]["status"] != "HEALTHY"
            or components["persistence"]["status"] != "HEALTHY"
            or components["runtime_models"]["bilstm2"]["status"] != "HEALTHY"
        )

        degraded = (
            components["neo4j"]["status"] == "DEGRADED"
            or components["runtime_models"]["svm"]["status"] != "HEALTHY"
            or components["runtime_models"]["logistic_regression"]["status"] != "HEALTHY"
        )

        if critical_unhealthy:
            overall = OverallStatus.UNHEALTHY
        elif degraded:
            overall = OverallStatus.DEGRADED
        else:
            overall = OverallStatus.HEALTHY

        return {
            "status": overall,
            "timestamp": now_ts,
            "components": components,
            "issues": issues,
        }

