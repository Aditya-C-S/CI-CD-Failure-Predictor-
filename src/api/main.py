"""src/api/main.py

FastAPI backend application for the CI/CD Pipeline Failure Predictor
and Assisted Root Cause Analysis platform.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import (
    DATA_SAMPLES_DIR,
    FRONTEND_DIR,
    DEFAULT_MODEL,
    DEFAULT_VISIBILITY,
    SUPPORTED_VISIBILITIES,
)
from src.ingestion.pipeline_simulator import PipelineSimulator
from src.parser.parser_v2 import LogRecord, parse_log_text
from src.prediction.model_loader import check_model_availability
from src.prediction.predictor import get_predictor
from src.rca.rca_engine import get_default_engine
from src.remediation.suggestions import RemediationAdvisor
from src.prediction.metadata_service import MetadataService
from src.api.metadata_router import router as metadata_router
from src.api.demo_router import router as demo_router

logger = logging.getLogger("cicd_api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="AI-Powered CI/CD Failure Predictor & RCA Engine",
    description="End-to-end failure risk prediction, structured evidence extraction, and root cause diagnosis.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Prevent browser caching of frontend dashboard assets and entrypoints
    if request.url.path.startswith("/static") or request.url.path in ("/", "/graph-explorer"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.include_router(metadata_router)
app.include_router(demo_router)


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    log_text: str = Field(..., description="Raw CI/CD log content or snapshot prefix.")
    model_name: str = Field(default=DEFAULT_MODEL, description="Model family: logistic_regression, svm, modernbert, bilstm, bilstm2.")
    visibility: int = Field(default=DEFAULT_VISIBILITY, description="Log depth percentage: 25, 50, 75, or 100.")


class ParseRequest(BaseModel):
    log_text: str = Field(..., description="Raw CI/CD log text.")
    run_id: Optional[str] = Field(default=None, description="Optional CI run identifier.")


class RCARequest(BaseModel):
    log_text: Optional[str] = Field(default=None, description="Log text to parse and analyze.")
    log_record: Optional[Dict[str, Any]] = Field(default=None, description="Pre-parsed LogRecord dictionary.")


class SimulateRequest(BaseModel):
    log_text: str = Field(..., description="Full raw CI/CD log text.")
    model_name: str = Field(default=DEFAULT_MODEL, description="Prediction model to use.")
    run_id: str = Field(default="sim_run_01", description="CI build identifier.")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    """Health check reporting system status and model readiness."""
    models_status = check_model_availability()
    meta_service = MetadataService.get_instance()
    return {
        "status": "healthy",
        "service": "CI/CD Failure Predictor & RCA Engine",
        "version": "2.0.0",
        "models_summary": {k: v["status"] for k, v in models_status.items()},
        "metadata_model": {
            "status": "ready" if meta_service.is_ready else "unavailable",
            "version": meta_service.get_model_info()["model_version"],
            "error": meta_service.load_error,
        },
    }


@app.get("/api/health/system")
@app.get("/health/system")
def system_health_diagnostics() -> Dict[str, Any]:
    """Comprehensive diagnostic health check across all platform subsystems."""
    from src.diagnostics.system_health import SystemHealthService
    return SystemHealthService.get_system_health()


@app.get("/api/models")
def get_models() -> Dict[str, Any]:
    """Inspect model registry, supported depths, and artifact readiness."""
    return {
        "models": check_model_availability(),
        "supported_visibilities": SUPPORTED_VISIBILITIES,
        "active_default_model": DEFAULT_MODEL,
        "active_default_visibility": DEFAULT_VISIBILITY,
    }


@app.post("/api/predict")
def predict(req: PredictRequest) -> Dict[str, Any]:
    """Predict CI/CD failure probability from log snapshot."""
    if req.visibility not in SUPPORTED_VISIBILITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid visibility depth {req.visibility}. Must be one of {SUPPORTED_VISIBILITIES}.",
        )
    try:
        predictor = get_predictor(req.model_name, visibility=req.visibility)
        result = predictor.predict_failure(req.log_text, visibility=req.visibility)
        return result.to_dict()
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Batch 2 Aliases for Prediction Intelligence & Early Warnings
# ---------------------------------------------------------------------------

@app.get("/api/prediction/threshold")
def get_prediction_threshold() -> Dict[str, Any]:
    """Retrieve active early warning threshold."""
    from src.prediction.runtime_tracker import get_early_warning_threshold, DEFAULT_EARLY_WARNING_THRESHOLD
    val = get_early_warning_threshold()
    return {
        "threshold": val,
        "threshold_pct": round(val * 100.0, 1),
        "default_threshold": DEFAULT_EARLY_WARNING_THRESHOLD,
        "is_default": abs(val - DEFAULT_EARLY_WARNING_THRESHOLD) < 1e-4,
    }


class SetThresholdPayload(BaseModel):
    threshold: float = Field(..., description="Threshold between 0.0 and 1.0 (e.g. 0.70)")


@app.post("/api/prediction/threshold")
def set_prediction_threshold(req: SetThresholdPayload) -> Dict[str, Any]:
    """Update active early warning threshold."""
    from src.prediction.runtime_tracker import set_early_warning_threshold, DEFAULT_EARLY_WARNING_THRESHOLD
    try:
        updated = set_early_warning_threshold(req.threshold)
        return {
            "status": "updated",
            "threshold": updated,
            "threshold_pct": round(updated * 100.0, 1),
            "default_threshold": DEFAULT_EARLY_WARNING_THRESHOLD,
            "is_default": abs(updated - DEFAULT_EARLY_WARNING_THRESHOLD) < 1e-4,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


class ComparePayload(BaseModel):
    log_text: str = Field(..., description="Log text to evaluate across models")
    depth: int = Field(default=100, description="Pipeline depth percentage (25, 50, 75, 100)")


@app.post("/api/prediction/compare")
def compare_prediction_models(req: ComparePayload) -> Dict[str, Any]:
    """Side-by-side fair comparison across all 3 runtime models on identical evidence."""
    from src.prediction.runtime_tracker import compare_runtime_models
    report = compare_runtime_models(log_text=req.log_text, depth=req.depth)
    return report.to_dict()


@app.get("/api/prediction/history/{run_id}")
def get_prediction_history_by_run(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve chronological prediction history for a specific run ID."""
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_prediction_history(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.get("/api/prediction/risk-progression/{run_id}")
def get_risk_progression_by_run(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve structured risk progression across checkpoints for a run ID."""
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_risk_progression(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.get("/api/warnings/recent")
@app.get("/api/prediction/warning-events/recent")
def get_recent_warnings_alias(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    """Retrieve recent early warning events across all runs."""
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_recent_warnings(limit=limit)


@app.get("/api/warnings/run/{run_id}")
def get_warnings_by_run(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve early warning event history for a run ID."""
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_warnings(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.get("/api/rca/{run_id}")
def get_rca_by_run(run_id: str) -> Dict[str, Any]:
    """Retrieve comprehensive Root Cause Analysis for a run ID."""
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_rca(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# ---------------------------------------------------------------------------
# Batch 3 Scenario Aliases
# ---------------------------------------------------------------------------
@app.get("/api/scenarios")
def get_scenarios_alias() -> List[Dict[str, Any]]:
    from src.scenarios.scenario_orchestrator import get_all_scenarios
    return get_all_scenarios()


@app.get("/api/scenarios/{scenario_id}")
def get_scenario_detail_alias(scenario_id: str) -> Dict[str, Any]:
    from src.scenarios.scenario_orchestrator import get_scenario_definition
    try:
        return get_scenario_definition(scenario_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


class MainValidateScenarioPayload(BaseModel):
    scenario_id: str


@app.post("/api/scenarios/validate")
def validate_scenario_alias(req: MainValidateScenarioPayload) -> Dict[str, Any]:
    from src.scenarios.scenario_orchestrator import normalize_and_validate_scenario
    try:
        sc = normalize_and_validate_scenario(req.scenario_id)
        return {"valid": True, "scenario": sc.to_dict()}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


class MainDispatchScenarioPayload(BaseModel):
    scenario_id: str
    repo_id: str = "Aditya-C-S/demo-order-service"
    run_id: Optional[str] = None
    dry_run: bool = False
    runtime_model: str = "bilstm2"


@app.post("/api/scenarios/dispatch")
def dispatch_scenario_alias(req: MainDispatchScenarioPayload) -> Dict[str, Any]:
    from src.scenarios.scenario_orchestrator import ScenarioOrchestrator
    try:
        return ScenarioOrchestrator.dispatch(
            scenario_id=req.scenario_id,
            repo_id=req.repo_id,
            run_id=req.run_id,
            dry_run=req.dry_run,
            runtime_model=req.runtime_model,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/scenarios/runs/{run_id}/status")
def get_scenario_status_alias(run_id: str) -> Dict[str, Any]:
    from src.scenarios.scenario_orchestrator import ScenarioOrchestrator
    try:
        return ScenarioOrchestrator.get_execution_status(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# ---------------------------------------------------------------------------
# Batch 3 Part C: Run Summary Aliases
# ---------------------------------------------------------------------------
@app.get("/api/runs/{run_id}/summary")
def get_run_summary_alias(run_id: str) -> Dict[str, Any]:
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.post("/api/runs/{run_id}/summary/finalize")
def finalize_run_summary_alias(run_id: str) -> Dict[str, Any]:
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.finalize_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.post("/api/runs/{run_id}/summary/refresh")
def refresh_run_summary_alias(run_id: str) -> Dict[str, Any]:
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.refresh_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.get("/api/summaries")
def get_summaries_alias(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_recent_summaries(limit=limit)


@app.post("/api/parse")
def parse(req: ParseRequest) -> Dict[str, Any]:
    """Extract structured evidence from raw CI/CD logs using Parser V2."""
    try:
        record = parse_log_text(req.log_text, run_id=req.run_id)
        return record.to_dict()
    except Exception as e:
        logger.exception("Parser V2 failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rca")
def rca(req: RCARequest) -> Dict[str, Any]:
    """Diagnose root cause using the modular RCA rule engine."""
    engine = get_default_engine()
    try:
        if req.log_record is not None:
            report = engine.analyze_record(req.log_record)
        elif req.log_text:
            parsed = parse_log_text(req.log_text)
            report = engine.analyze_record(parsed)
        else:
            raise HTTPException(status_code=400, detail="Either 'log_text' or 'log_record' must be provided.")

        remediation = RemediationAdvisor.generate_remediation(report, log_text=req.log_text)
        rca_dict = report.to_dict()
        rca_dict["confidence"] = getattr(report, "rca_confidence", None)
        return {
            "rca_report": rca_dict,
            "remediation": remediation,
        }
    except Exception as e:
        logger.exception("RCA Engine failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> Dict[str, Any]:
    """Run full progressive pipeline simulation (Snapshots -> Prediction -> Parser V2 -> RCA -> Remediation)."""
    try:
        sim = PipelineSimulator(model_name=req.model_name)
        report = sim.simulate(log_text=req.log_text, run_id=req.run_id)
        return report.to_dict()
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.exception("Simulation failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/samples")
def list_samples() -> Dict[str, Any]:
    """List sample logs available for demonstration and testing."""
    samples = []
    logs_dir = DATA_SAMPLES_DIR / "logs"
    if logs_dir.exists():
        for f in sorted(logs_dir.rglob("*.log")):
            rel_path = f.relative_to(logs_dir).as_posix()
            parts = rel_path.split("/")
            category = parts[0] if len(parts) > 1 else "root"
            samples.append({
                "id": rel_path,
                "name": f"{category} - {f.name}",
                "category": category,
                "type": "raw_log",
                "size_bytes": f.stat().st_size,
            })

    # Also include snapshot samples
    snaps_dir = DATA_SAMPLES_DIR / "snapshots"
    if snaps_dir.exists():
        for sf in sorted(snaps_dir.rglob("*_pct025.txt")):
            rel_path = sf.relative_to(snaps_dir).as_posix()
            parts = rel_path.split("/")
            fam = parts[0]
            out = parts[1] if len(parts) > 1 else ""
            samples.append({
                "id": f"snapshots/{rel_path}",
                "name": f"Snapshot {fam} ({out}) 25%",
                "category": fam,
                "type": "snapshot",
                "size_bytes": sf.stat().st_size,
            })

    return {"count": len(samples), "samples": samples}


@app.get("/api/samples/{sample_path:path}")
def get_sample_content(sample_path: str) -> Dict[str, Any]:
    """Retrieve full content of a selected sample log."""
    base = DATA_SAMPLES_DIR
    target = (base / sample_path).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal forbidden.")
    if not target.exists() or not target.is_file():
        # Try finding in logs/
        target_in_logs = (base / "logs" / sample_path).resolve()
        if target_in_logs.exists() and target_in_logs.is_file():
            target = target_in_logs
        else:
            raise HTTPException(status_code=404, detail=f"Sample log '{sample_path}' not found.")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"filename": target.name, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Static frontend mounting
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "CI/CD Failure Predictor API is running. Dashboard index.html not found."}

    @app.get("/graph-explorer")
    def graph_explorer():
        explorer_file = FRONTEND_DIR / "graph-explorer.html"
        if explorer_file.exists():
            return FileResponse(explorer_file)
        return JSONResponse(status_code=404, content={"message": "Graph explorer page not found."})
