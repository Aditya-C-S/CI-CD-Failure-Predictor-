"""src/api/demo_router.py

FastAPI router exposing endpoints for the Unified End-to-End Demo Workflow:
- POST /api/demo/runs                     Create new unified run
- GET  /api/demo/runs                     List past demo runs
- GET  /api/demo/runs/{run_id}            Get single run status & diagnostic state
- POST /api/demo/runs/{run_id}/metadata   Run pre-build metadata risk prediction & SHAP
- POST /api/demo/runs/{run_id}/blast-radius Run Neo4j / AST blast radius analysis
- POST /api/demo/runs/{run_id}/logs       Ingest live log chunk from GitHub Actions runner
- POST /api/demo/runs/{run_id}/replay     Replay benchmark sample in streaming slices
- GET  /api/demo/ci-config                Retrieve customized GitHub Actions YAML & secrets
- GET  /api/demo/presets                  Retrieve scenario presets
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.demo.demo_manager import UnifiedDemoManager
from src.demo.git_extractor import SCENARIO_PRESETS

logger = logging.getLogger("demo_api")

router = APIRouter(prefix="/api/demo", tags=["Unified End-to-End Demo"])


class CreateRunRequest(BaseModel):
    repo_id: str = Field(default="demo-org/sample-service", description="Repository identifier (owner/repo or local name)")
    commit_sha: Optional[str] = Field(default=None, description="Commit SHA to analyze (or HEAD)")
    branch: str = Field(default="main", description="Target Git branch")
    is_pr: bool = Field(default=True, description="Whether this execution is triggered by a Pull Request")
    changed_files: Optional[List[str]] = Field(default=None, description="List of modified files in the commit/PR")
    scenario_preset: str = Field(default="high_risk", description="Benchmark scenario for historical/CI defaults")
    runtime_model: str = Field(default="logistic_regression", description="Runtime prediction model: logistic_regression, svm, bilstm, bilstm2")
    local_repo_path: Optional[str] = Field(default=None, description="Optional path to local Git repository")
    auto_advance: bool = Field(default=True, description="Automatically evaluate pre-build metadata and blast radius")


class IngestLogChunkRequest(BaseModel):
    log_chunk: str = Field(..., description="Raw text of log lines or terminal output chunk")
    event_id: Optional[str] = Field(default=None, description="Optional telemetry event identifier")
    step_name: Optional[str] = Field(default="Execute Step", description="CI step name")
    stage: Optional[str] = Field(default="execution", description="Pipeline stage (setup, build, test, teardown)")
    is_final: bool = Field(default=False, description="Whether this is the final log chunk of the CI run")
    exit_code: Optional[int] = Field(default=None, description="Exit code of the step (0 for success, non-zero for failure)")
    ci_run_id: Optional[str] = Field(default=None, description="GitHub Actions or CI runner run ID")
    commit_sha: Optional[str] = Field(default=None, description="Commit SHA of the repository")
    step_outcome: Optional[str] = Field(default=None, description="Step execution outcome (success, failure, skipped)")
    workflow_outcome: Optional[str] = Field(default=None, description="Overall CI workflow outcome (success, failure)")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of the checkpoint report")
    depth: Optional[int] = Field(default=None, description="Target pipeline depth percentage (25, 50, 75, 100)")


class ReplaySampleRequest(BaseModel):
    sample_id: str = Field(default="F2/run_0005.log", description="Sample log filename or path under data/samples/logs/")
    chunk_lines: int = Field(default=40, ge=5, le=500, description="Number of lines per progressive replay chunk")


@router.post("/runs")
def create_demo_run(req: CreateRunRequest) -> Dict[str, Any]:
    """Initialize a unified demo execution run."""
    mgr = UnifiedDemoManager.get_instance()
    run = mgr.create_run(
        repo_id=req.repo_id,
        commit_sha=req.commit_sha,
        branch=req.branch,
        is_pr=req.is_pr,
        changed_files=req.changed_files,
        scenario_preset=req.scenario_preset,
        runtime_model=req.runtime_model,
        local_repo_path=req.local_repo_path,
        auto_advance=req.auto_advance,
    )
    return run.to_dict()


@router.get("/runs")
def list_demo_runs(limit: int = Query(default=20, ge=1, le=100)) -> List[Dict[str, Any]]:
    """List recent unified demo runs."""
    mgr = UnifiedDemoManager.get_instance()
    return mgr.list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_demo_run(run_id: str) -> Dict[str, Any]:
    """Retrieve complete status and stage results for a specific demo run."""
    mgr = UnifiedDemoManager.get_instance()
    run = mgr.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Demo run '{run_id}' not found.")
    return run.to_dict()


@router.post("/runs/{run_id}/metadata")
def execute_run_metadata(run_id: str) -> Dict[str, Any]:
    """Execute pre-build LightGBM failure prediction and TreeSHAP explainer for this run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.execute_metadata_prediction(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.exception("Metadata prediction failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{run_id}/blast-radius")
def execute_run_blast_radius(run_id: str) -> Dict[str, Any]:
    """Execute Neo4j AST blast radius traversal for this run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.execute_blast_radius(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.exception("Blast radius analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def get_configured_api_key() -> Optional[str]:
    """
    Retrieve DEMO_API_KEY from environment or .env file.
    Always checked before any demo-run lookup or processing.
    """
    key = os.getenv("DEMO_API_KEY")
    if key and key.strip():
        return key.strip()
    try:
        from dotenv import load_dotenv
        from src.config import PROJECT_ROOT
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            key = os.getenv("DEMO_API_KEY")
            if key and key.strip():
                return key.strip()
    except Exception:
        pass
    return None


@router.post("/runs/{run_id}/logs")
def ingest_run_log_chunk(
    run_id: str,
    req: IngestLogChunkRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Ingest a live CI log chunk.
    Automatically triggers incremental runtime prediction, Parser V2, and RCA.
    Security: If DEMO_API_KEY environment variable is configured, verifies incoming token before run lookup.
    """
    configured_key = get_configured_api_key()
    if configured_key:
        token = x_api_key
        if not token and authorization:
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            else:
                token = authorization.strip()
        if not token or token != configured_key:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid or missing API key for CI log ingestion.",
            )

    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.ingest_log_chunk(
            run_id=run_id,
            log_chunk=req.log_chunk,
            step_name=req.step_name,
            stage=req.stage,
            is_final=req.is_final,
            exit_code=req.exit_code,
            ci_run_id=req.ci_run_id,
            commit_sha=req.commit_sha,
            step_outcome=req.step_outcome,
            workflow_outcome=req.workflow_outcome,
            timestamp=req.timestamp,
            target_depth=req.depth,
            event_id=req.event_id,
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.exception("Log ingestion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{run_id}/replay")
def replay_sample_log(run_id: str, req: ReplaySampleRequest) -> Dict[str, Any]:
    """Replay a benchmark sample log in progressive chunks through the live pipeline."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.replay_sample_stream(
            run_id=run_id,
            sample_path_str=req.sample_id,
            chunk_lines=req.chunk_lines,
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except ValueError as ve:
        if "Cannot replay" in str(ve) or "live GitHub Actions" in str(ve):
            raise HTTPException(status_code=400, detail=str(ve))
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.exception("Replay failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ci-config")
def get_ci_config(
    run_id: str = Query(default="demo_run_sample", description="Target Run ID"),
    backend_url: str = Query(default="http://127.0.0.1:8000", description="Backend base URL"),
) -> Dict[str, Any]:
    """Retrieve GitHub Actions workflow YAML, required secrets, and curl commands."""
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_ci_integration_docs(run_id=run_id, backend_url=backend_url)


@router.get("/presets")
def get_scenario_presets() -> Dict[str, Any]:
    """Retrieve documented benchmark PR/commit scenarios."""
    return SCENARIO_PRESETS


# ---------------------------------------------------------------------------
# Batch 2 Endpoints: Prediction History, Risk Progression, Model Comparison, Warnings
# ---------------------------------------------------------------------------

class CompareModelsRequest(BaseModel):
    log_text: str = Field(..., description="Log text to evaluate across all models")
    depth: int = Field(default=100, description="Pipeline depth percentage (25, 50, 75, 100)")


class SetThresholdRequest(BaseModel):
    threshold: float = Field(..., description="Threshold between 0.0 and 1.0 (e.g. 0.70)")


@router.get("/runs/{run_id}/prediction-history")
def get_run_prediction_history(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve chronological runtime prediction history for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_prediction_history(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/prediction-history")
def get_recent_prediction_history(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    """Retrieve recent runtime prediction history across all runs."""
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_recent_prediction_history(limit=limit)


@router.get("/runs/{run_id}/risk-progression")
def get_run_risk_progression(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve structured multi-checkpoint risk progression for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_risk_progression(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/runs/{run_id}/model-comparison")
def get_run_model_comparison(
    run_id: str,
    depth: Optional[int] = Query(default=None, description="Depth percentage (25, 50, 75, 100)"),
) -> Dict[str, Any]:
    """Retrieve fair comparison across all 3 runtime models on this run's log evidence."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_model_comparison(run_id, depth=depth)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/compare-models")
def compare_models_endpoint(req: CompareModelsRequest) -> Dict[str, Any]:
    """Evaluate all 3 runtime models on arbitrary log text and depth."""
    from src.prediction.runtime_tracker import compare_runtime_models
    report = compare_runtime_models(log_text=req.log_text, depth=req.depth)
    return report.to_dict()


@router.get("/threshold")
def get_warning_threshold_endpoint() -> Dict[str, Any]:
    """Retrieve the current active early-warning threshold."""
    from src.prediction.runtime_tracker import get_early_warning_threshold, DEFAULT_EARLY_WARNING_THRESHOLD
    val = get_early_warning_threshold()
    return {
        "threshold": val,
        "threshold_pct": round(val * 100.0, 1),
        "default_threshold": DEFAULT_EARLY_WARNING_THRESHOLD,
        "is_default": abs(val - DEFAULT_EARLY_WARNING_THRESHOLD) < 1e-4,
    }


@router.post("/threshold")
@router.put("/threshold")
def set_warning_threshold_endpoint(req: SetThresholdRequest) -> Dict[str, Any]:
    """Update active early-warning threshold without restarting backend."""
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


@router.get("/runs/{run_id}/warnings")
def get_run_warnings(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve warning event history for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_warnings(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/warnings")
def get_recent_warnings(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    """Retrieve recent early warning events across all runs."""
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_recent_warnings(limit=limit)


# ---------------------------------------------------------------------------
# Batch 3 Part A: Advanced Root Cause Analysis (RCA) Endpoints
# ---------------------------------------------------------------------------
@router.get("/runs/{run_id}/rca")
def get_run_rca_endpoint(run_id: str) -> Dict[str, Any]:
    """Retrieve comprehensive Root Cause Analysis for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_rca(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/runs/{run_id}/rca")
def update_run_rca_endpoint(run_id: str) -> Dict[str, Any]:
    """Force recompute / update Root Cause Analysis for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.update_run_rca(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/runs/{run_id}/rca/findings")
def get_run_rca_findings_endpoint(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve individual candidate root cause findings for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_rca_findings(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/runs/{run_id}/rca/evidence")
def get_run_rca_evidence_endpoint(run_id: str) -> List[Dict[str, Any]]:
    """Retrieve structured evidence references for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_rca_evidence(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/runs/{run_id}/rca/remediation")
def get_run_rca_remediation_endpoint(run_id: str) -> Dict[str, Any]:
    """Retrieve actionable remediation suggestions for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_rca_remediation(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# ---------------------------------------------------------------------------
# Batch 3 Part B: Scenario Orchestration Endpoints
# ---------------------------------------------------------------------------
class ValidateScenarioRequest(BaseModel):
    scenario_id: str = Field(..., description="Scenario ID: none, dependency, syntax, pytest")


class DispatchScenarioRequest(BaseModel):
    scenario_id: str = Field(..., description="Scenario ID: none, dependency, syntax, pytest")
    repo_id: str = Field(default="Aditya-C-S/demo-order-service", description="Target GitHub repository")
    run_id: Optional[str] = Field(default=None, description="Optional existing run ID to associate")
    dry_run: bool = Field(default=False, description="Validate and prepare dispatch without executing remote workflow")
    runtime_model: str = Field(default="bilstm2", description="Runtime prediction model (bilstm2, svm, logistic_regression)")


@router.get("/scenarios")
def list_scenarios_endpoint() -> List[Dict[str, Any]]:
    """List the 4 centralized GitHub Actions demo scenarios."""
    from src.scenarios.scenario_orchestrator import get_all_scenarios
    return get_all_scenarios()


@router.get("/scenarios/{scenario_id}")
def get_scenario_endpoint(scenario_id: str) -> Dict[str, Any]:
    """Retrieve details for a single demo scenario."""
    from src.scenarios.scenario_orchestrator import get_scenario_definition
    try:
        return get_scenario_definition(scenario_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.post("/scenarios/validate")
def validate_scenario_endpoint(req: ValidateScenarioRequest) -> Dict[str, Any]:
    """Validate a scenario selection."""
    from src.scenarios.scenario_orchestrator import normalize_and_validate_scenario
    try:
        sc = normalize_and_validate_scenario(req.scenario_id)
        return {
            "valid": True,
            "scenario": sc.to_dict(),
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.post("/scenarios/dispatch")
def dispatch_scenario_endpoint(req: DispatchScenarioRequest) -> Dict[str, Any]:
    """Initiate a demonstration scenario through GitHub Actions workflow dispatch."""
    from src.scenarios.scenario_orchestrator import ScenarioOrchestrator
    try:
        result = ScenarioOrchestrator.dispatch(
            scenario_id=req.scenario_id,
            repo_id=req.repo_id,
            run_id=req.run_id,
            dry_run=req.dry_run,
            runtime_model=req.runtime_model,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.exception("Failed to dispatch scenario")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/scenarios/runs/{run_id}/status")
def get_scenario_run_status_endpoint(run_id: str) -> Dict[str, Any]:
    """Retrieve scenario execution lifecycle status for a run."""
    from src.scenarios.scenario_orchestrator import ScenarioOrchestrator
    try:
        return ScenarioOrchestrator.get_execution_status(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# ---------------------------------------------------------------------------
# Batch 3 Part C: Final Run Summary Endpoints
# ---------------------------------------------------------------------------
@router.get("/runs/{run_id}/summary")
def get_run_summary_endpoint(run_id: str) -> Dict[str, Any]:
    """Retrieve comprehensive post-execution summary report for a run."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.get_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/runs/{run_id}/summary/finalize")
def finalize_run_summary_endpoint(run_id: str) -> Dict[str, Any]:
    """Explicitly finalize and persist run summary."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.finalize_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/runs/{run_id}/summary/refresh")
def refresh_run_summary_endpoint(run_id: str) -> Dict[str, Any]:
    """Recompute run summary with late-arriving logs or updated RCA."""
    mgr = UnifiedDemoManager.get_instance()
    try:
        return mgr.refresh_run_summary(run_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/summaries")
def get_recent_summaries_endpoint(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    """Retrieve recent run summaries across all demo runs."""
    mgr = UnifiedDemoManager.get_instance()
    return mgr.get_recent_summaries(limit=limit)
