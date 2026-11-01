"""src/api/metadata_router.py

FastAPI router exposing Module I: Pre-Build Commit Metadata Failure Predictor endpoints:
- POST /api/metadata/predict
- GET  /api/metadata/model-info
- GET  /api/metadata/scorecard
- GET  /api/metadata/charts/{chart_name}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from src.prediction.metadata_service import MetadataService

logger = logging.getLogger("metadata_api")

router = APIRouter(prefix="/api/metadata", tags=["Metadata Predictor (Module I)"])


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class SHAPDriverItem(BaseModel):
    feature: str = Field(..., description="Feature name")
    contribution: float = Field(..., description="Signed contribution to failure log-odds")


class SHAPDrivers(BaseModel):
    positive: List[SHAPDriverItem] = Field(
        default_factory=list, description="Top features pushing risk towards failure"
    )
    negative: List[SHAPDriverItem] = Field(
        default_factory=list, description="Top mitigating features pulling risk towards success"
    )


class MetadataPredictRequest(BaseModel):
    """
    Request payload for metadata failure prediction.
    Accepts either an explicit 'features' dictionary, flat key-value pairs matching the 38 schema columns,
    or a 'run_id' / 'commit_hash' + 'repository' pair to genuinely extract Git metrics.
    """
    model_config = ConfigDict(extra="allow")

    features: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dictionary containing some or all of the 38 commit/repo metadata features.",
        json_schema_extra={
            "example": {
                "git_diff_src_churn": 350,
                "total_files_changed": 12,
                "gh_diff_tests_deleted": 2,
                "log_team_size": 2.3,
                "gh_repo_age": 1200,
                "gh_test_lines_per_kloc": 85.0,
                "gh_is_pr": 1,
                "has_previous_build": 1,
            }
        },
    )
    source_hints: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional lineage source hints per feature (e.g. 'git_diff_src_churn': 'measured_git_diff')."
    )
    scenario_preset_name: Optional[str] = Field(
        default=None,
        description="Optional preset key when features are augmented from a benchmark scenario."
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Optional unified demo run ID to extract lineage & features from."
    )
    commit_hash: Optional[str] = Field(
        default=None,
        description="Commit SHA to extract genuine Git diff statistics and metadata for."
    )
    repository: Optional[str] = Field(
        default=None,
        description="Repository identifier or path for Git extraction."
    )


class MetadataPredictResponse(BaseModel):
    failure_probability: float = Field(..., description="Calibrated failure probability in [0.0, 1.0]")
    failure_probability_pct: float = Field(..., description="Calibrated failure probability percentage [0.0, 100.0]")
    raw_score: float = Field(..., description="Uncalibrated model output score")
    latency_ms: float = Field(..., description="Pure model inference latency in milliseconds")
    verdict: str = Field(..., description="Policy verdict: FAST-TRACK, STANDARD GATE, ALERT, PRE-MERGE BLOCK")
    verdict_description: str = Field(..., description="Actionable gating recommendation")
    shap_drivers: SHAPDrivers = Field(..., description="Top local risk drivers pushing score up/down")
    thresholds: Dict[str, float] = Field(..., description="Production policy decision thresholds")
    features_analyzed: Dict[str, float] = Field(..., description="Normalized 38-feature vector used for prediction")
    provenance: Optional[Dict[str, Any]] = Field(
        default=None, description="Lineage classification and origin category for each feature"
    )
    completeness: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata observation completeness score (0-100) and breakdown"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/predict", response_model=MetadataPredictResponse)
def predict_metadata_risk(req: MetadataPredictRequest, raw_request: Request) -> Dict[str, Any]:
    """
    Predict CI/CD build failure probability from commit & repository metadata before build execution.
    Extracts genuine Git diff metrics and provenance when run_id or commit_hash is supplied.
    """
    service = MetadataService.get_instance()
    if not service.is_ready:
        raise HTTPException(
            status_code=503,
            detail=f"Metadata predictor service is unavailable: {service.load_error or 'Model not initialized'}",
        )

    # 1. Check if run_id is supplied
    if req.run_id:
        try:
            from src.demo.demo_manager import UnifiedDemoManager
            mgr = UnifiedDemoManager.get_instance()
            run = mgr.get_run(req.run_id)
            if run:
                preset_name = getattr(run, "scenario_preset", None)
                cached_pred = getattr(run, "metadata_prediction", None)
                if cached_pred and "failure_probability" in cached_pred:
                    if not preset_name or cached_pred.get("scenario_preset") == preset_name:
                        return cached_pred
                if getattr(run, "feature_lineage", None) and run.feature_lineage.get("features_analyzed"):
                    res = service.predict(
                        run.feature_lineage["features_analyzed"],
                        source_hints=run.feature_lineage.get("feature_sources"),
                        scenario_preset_name=preset_name or "standard_gate",
                    )
                    res["scenario_preset"] = preset_name
                    run.metadata_prediction = res
                    run.save_checkpoint()
                    return res
                # Fallback: assemble from run commit info
                from src.demo.git_extractor import GitMetadataExtractor
                from src.demo.graph_inspector import get_demo_order_service_path
                repo_path = get_demo_order_service_path()
                lineage = GitMetadataExtractor.assemble_features_with_lineage(
                    repo_path=repo_path,
                    commit_sha=run.commit_info.get("commit_sha") if run.commit_info else None,
                    scenario_preset_name=preset_name or "standard_gate",
                )
                res = service.predict(
                    lineage["features_analyzed"],
                    source_hints=lineage["feature_sources"],
                    scenario_preset_name=lineage["scenario_preset"],
                )
                res["scenario_preset"] = lineage["scenario_preset"]
                run.metadata_prediction = res
                run.feature_lineage = lineage
                run.save_checkpoint()
                return res
        except Exception as exc:
            logger.warning("Could not resolve metadata from run_id '%s': %s", req.run_id, exc)

    # 2. Determine feature source: either req.features or raw body fields
    features_input: Dict[str, Any] = {}
    if req.features and isinstance(req.features, dict):
        features_input = dict(req.features)
    else:
        extra_fields = {
            k: v for k, v in req.model_dump().items()
            if k not in ("features", "source_hints", "scenario_preset_name", "run_id") and v is not None
        }
        if extra_fields:
            features_input = extra_fields

    from src.demo.git_extractor import CANONICAL_FEATURES
    has_schema_keys = any(k in CANONICAL_FEATURES for k in features_input.keys()) if features_input else False

    # 3. If commit_hash or repository is provided without canonical schema features, extract genuine Git metrics
    commit_sha = req.commit_hash or features_input.get("commit_hash")
    repo_name = req.repository or features_input.get("repository")

    if (commit_sha or repo_name) and not has_schema_keys:
        try:
            from src.demo.git_extractor import GitMetadataExtractor
            from src.demo.graph_inspector import get_demo_order_service_path
            from pathlib import Path

            repo_path = None
            if repo_name and ("demo-order-service" in str(repo_name) or "Aditya-C-S" in str(repo_name)):
                repo_path = get_demo_order_service_path()
            elif repo_name and Path(str(repo_name)).exists():
                repo_path = Path(str(repo_name))
            else:
                repo_path = get_demo_order_service_path()

            is_preset = bool((req.scenario_preset_name and req.scenario_preset_name != "standard_gate") or (commit_sha and str(commit_sha).startswith("preset_")))
            target_preset = req.scenario_preset_name or (commit_sha.replace("preset_", "") if commit_sha and str(commit_sha).startswith("preset_") else "standard_gate")

            lineage = GitMetadataExtractor.assemble_features_with_lineage(
                repo_path=None if is_preset else repo_path,
                commit_sha=None if is_preset else commit_sha,
                scenario_preset_name=target_preset,
            )
            return service.predict(
                lineage["features_analyzed"],
                source_hints=lineage["feature_sources"],
                scenario_preset_name=lineage["scenario_preset"],
            )
        except Exception as exc:
            logger.warning("Genuine Git feature extraction failed: %s", exc)

    if not features_input or not has_schema_keys:
        # Fallback to standard gate assembly rather than bare zero vector
        try:
            from src.demo.git_extractor import GitMetadataExtractor
            from src.demo.graph_inspector import get_demo_order_service_path
            repo_path = get_demo_order_service_path()
            lineage = GitMetadataExtractor.assemble_features_with_lineage(
                repo_path=repo_path,
                scenario_preset_name=req.scenario_preset_name or "standard_gate",
            )
            return service.predict(
                lineage["features_analyzed"],
                source_hints=lineage["feature_sources"],
                scenario_preset_name=lineage["scenario_preset"],
            )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="No metadata features provided. Please submit a non-empty 'features' dictionary or commit/repo identifier.",
            )

    try:
        # Filter down to canonical features only for the model
        model_features = {k: v for k, v in features_input.items() if k in CANONICAL_FEATURES}
        result = service.predict(
            model_features,
            source_hints=req.source_hints,
            scenario_preset_name=req.scenario_preset_name,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Feature validation error: {ve}")
    except Exception as exc:
        logger.exception("Metadata prediction error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}")


@router.get("/provenance/schema")
@router.get("/canonical-provenance")
def get_provenance_schema() -> Dict[str, Any]:
    """
    Return canonical 38-feature provenance taxonomy, categories, and observation rules.
    """
    from src.prediction.provenance import get_canonical_provenance_spec
    return get_canonical_provenance_spec()


@router.get("/model-info")
def get_metadata_model_info() -> Dict[str, Any]:
    """
    Inspect metadata model architecture, training source, schema contract, and readiness.
    """
    service = MetadataService.get_instance()
    return service.get_model_info()


@router.get("/scorecard")
def get_metadata_scorecard() -> Dict[str, Any]:
    """
    Retrieve held-out test evaluation benchmarks (ROC-AUC, PR-AUC, MCC, Brier) and feature gain importances.
    """
    service = MetadataService.get_instance()
    try:
        return service.get_scorecard()
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        logger.exception("Failed to load scorecard: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/charts/{chart_name}")
def get_metadata_chart(chart_name: str):
    """
    Serve static evaluation plots (chart_feature_importance.png, chart_calibration.png, chart_fairness.png, etc.).
    """
    service = MetadataService.get_instance()
    chart_path = service.get_chart_path(chart_name)
    if not chart_path or not chart_path.exists():
        raise HTTPException(status_code=404, detail=f"Chart '{chart_name}' not found.")
    return FileResponse(str(chart_path), media_type="image/png")


# ---------------------------------------------------------------------------
# Graph Engine (Neo4j) Endpoints
# ---------------------------------------------------------------------------

class BlastRadiusRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    repo_id: str = Field(default="sample/test-repo", description="Repository identifier")
    changed_files: List[str] = Field(
        default_factory=lambda: ["utils.py"],
        description="List of modified file paths in the commit/PR"
    )
    investigation_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Risk probability threshold above which graph investigation is executed"
    )


@router.get("/graph/status")
def get_graph_status() -> Dict[str, Any]:
    """
    Check Neo4j database health, database name, and graph metrics.
    """
    service = MetadataService.get_instance()
    return service.get_graph_status()


@router.post("/graph/blast-radius")
def analyze_blast_radius(req: BlastRadiusRequest) -> Dict[str, Any]:
    """
    Query Neo4j AST knowledge graph for affected caller and callee files (blast radius)
    and return visual Cytoscape graph elements along with deterministic Graph Impact Score.
    """
    service = MetadataService.get_instance()
    return service.analyze_blast_radius(
        repo_id=req.repo_id,
        changed_files=req.changed_files,
        investigation_threshold=req.investigation_threshold,
    )


class GraphImpactRequest(BaseModel):
    repo_id: str = Field(default="msiemens/tinydb", description="Repository identifier")
    changed_files: List[str] = Field(..., description="List of modified file paths in commit")
    total_repo_files: Optional[int] = Field(default=None, description="Optional total files in repository")


@router.post("/graph/impact")
def calculate_graph_impact_endpoint(req: GraphImpactRequest) -> Dict[str, Any]:
    """
    Calculate deterministic Graph Impact Score (0-100) from Neo4j AST graph or Tree-Sitter fallback.
    """
    service = MetadataService.get_instance()
    blast_res = service.analyze_blast_radius(
        repo_id=req.repo_id,
        changed_files=req.changed_files,
    )
    if "graph_impact_score" in blast_res:
        return blast_res["graph_impact_score"]

    from src.prediction.graph_impact import calculate_graph_impact_score
    result = calculate_graph_impact_score(
        changed_files=req.changed_files,
        nodes=blast_res.get("graph_elements", []),
        total_repo_files=req.total_repo_files,
    )
    return result.to_dict()


@router.get("/graph/repositories")
def get_graph_repositories() -> List[Dict[str, Any]]:
    """
    List all ingested repositories in Neo4j with their commit provenance and sync status.
    """
    service = MetadataService.get_instance()
    return service.get_available_repositories()


class GraphExplorerRequest(BaseModel):
    repo_id: str = Field(default="msiemens/tinydb", description="Repository identifier")
    mode: str = Field(default="blast_radius", description="'blast_radius' or 'full'")
    changed_files: Optional[List[str]] = Field(default=None, description="List of changed file paths")
    run_id: Optional[str] = Field(default=None, description="Optional unified demo run ID")
    investigation_threshold: float = Field(default=0.50, ge=0.0, le=1.0)


@router.get("/graph/explorer")
def get_graph_explorer(
    repo_id: str = "msiemens/tinydb",
    mode: str = "blast_radius",
    changed_files: Optional[str] = None,
    run_id: Optional[str] = None,
    threshold: float = 0.50,
) -> Dict[str, Any]:
    """Retrieve full or blast-radius graph data for the interactive Graph Explorer."""
    from src.demo.graph_inspector import GraphInspector
    from src.demo.demo_manager import UnifiedDemoManager

    c_files: List[str] = []
    if changed_files:
        c_files = [f.strip() for f in changed_files.split(",") if f.strip()]

    # If run_id is supplied and c_files is empty, resolve from active demo run
    if run_id:
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.get_run(run_id)
        if run:
            run_repo = getattr(run, "repo_id", None) or (run.commit_info.get("repo_id") if hasattr(run, "commit_info") else None)
            run_cf = getattr(run, "changed_files", None) or (run.commit_info.get("changed_files") if hasattr(run, "commit_info") else None)
            if not repo_id or repo_id == "msiemens/tinydb":
                repo_id = run_repo or repo_id
            if not c_files and run_cf:
                c_files = run_cf

    return GraphInspector.get_explorer_graph(
        repo_id=repo_id,
        mode=mode,
        changed_files=c_files if c_files else None,
        investigation_threshold=threshold,
    )


@router.post("/graph/explorer")
def post_graph_explorer(req: GraphExplorerRequest) -> Dict[str, Any]:
    """POST endpoint for graph explorer data with JSON payload."""
    from src.demo.graph_inspector import GraphInspector
    from src.demo.demo_manager import UnifiedDemoManager

    c_files = req.changed_files or []
    repo = req.repo_id
    if req.run_id:
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.get_run(req.run_id)
        if run:
            run_repo = getattr(run, "repo_id", None) or (run.commit_info.get("repo_id") if hasattr(run, "commit_info") else None)
            run_cf = getattr(run, "changed_files", None) or (run.commit_info.get("changed_files") if hasattr(run, "commit_info") else None)
            if not repo or repo == "msiemens/tinydb":
                repo = run_repo or repo
            if not c_files and run_cf:
                c_files = run_cf

    return GraphInspector.get_explorer_graph(
        repo_id=repo,
        mode=req.mode,
        changed_files=c_files if c_files else None,
        investigation_threshold=req.investigation_threshold,
    )

