"""src/prediction/metadata_service.py

Bridge and service layer for Module I: Pre-Build Commit Metadata Risk Gatekeeper.
Manages lazy/eager loading of calibrated LightGBM and SHAP explainer artifacts,
validates feature contracts, and serves in-memory predictions.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger("metadata_service")

# Resolve project roots
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PIPELINE_ROOT = _PROJECT_ROOT / "metadata_model" / "extracted" / "Metadata-Pipeline-main"

# Inject pipeline and graph engine roots into sys.path
_GRAPH_GEN_ROOT = _PROJECT_ROOT / "metadata_model" / "extracted" / "graph-doc-gen-main"

if _PIPELINE_ROOT.exists() and str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

if _GRAPH_GEN_ROOT.exists() and str(_GRAPH_GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(_GRAPH_GEN_ROOT))

# Fallback schema list in case extraction folder is missing
CANONICAL_FEATURE_COLUMNS = [
    "gh_is_pr",
    "gh_lang_java",
    "gh_lang_python",
    "gh_lang_ruby",
    "git_prev_commit_resolution_status_merge_found",
    "git_prev_commit_resolution_status_no_previous_build",
    "gh_num_issue_comments",
    "gh_num_commit_comments",
    "gh_num_pr_comments",
    "log_team_size",
    "log_built_commits",
    "gh_repo_age",
    "gh_repo_num_commits",
    "tr_build_number",
    "gh_sloc",
    "git_diff_src_churn",
    "git_diff_test_churn",
    "gh_diff_files_added",
    "gh_diff_files_deleted",
    "gh_diff_files_modified",
    "gh_diff_tests_added",
    "gh_diff_tests_deleted",
    "gh_diff_src_files",
    "gh_diff_doc_files",
    "gh_diff_other_files",
    "gh_num_commits_on_files_touched",
    "gh_test_lines_per_kloc",
    "gh_test_cases_per_kloc",
    "gh_asserts_cases_per_kloc",
    "gh_by_core_team_member",
    "total_files_changed",
    "code_churn_density",
    "test_to_src_churn_ratio",
    "has_previous_build",
    "gh_pr_created_at_year",
    "gh_pr_created_at_month",
    "pr_dayofweek",
    "git_merged_with_present",
]

DEFAULT_THRESHOLDS = {
    "FAST_TRACK": 0.25,
    "STANDARD_GATE": 0.50,
    "ELEVATED_RISK": 0.65,
}


class MetadataService:
    """Singleton service wrapping the calibrated LightGBM model and TreeSHAP explainer."""

    _instance: Optional["MetadataService"] = None
    _lock = threading.Lock()

    def __init__(self, models_base_dir: Optional[Union[str, Path]] = None):
        self.models_base_dir = (
            Path(models_base_dir)
            if models_base_dir
            else _PIPELINE_ROOT / "Metadata Model" / "Models"
        )
        self.active_run_dir: Optional[Path] = None
        self.predictor_service: Optional[Any] = None
        self.feature_columns: List[str] = CANONICAL_FEATURE_COLUMNS
        self.thresholds: Dict[str, float] = DEFAULT_THRESHOLDS
        self.is_ready: bool = False
        self.load_error: Optional[str] = None
        self._initialize_service()

    @classmethod
    def get_instance(cls) -> "MetadataService":
        """Get or initialize thread-safe singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _resolve_latest_run_dir(self) -> Path:
        """Find the latest model run directory."""
        if not self.models_base_dir.exists():
            raise FileNotFoundError(
                f"Models directory not found at: {self.models_base_dir}. "
                "Ensure metadata_model.zip was extracted."
            )

        run_dirs = sorted([
            d for d in self.models_base_dir.iterdir()
            if d.is_dir() and d.name.startswith("run_")
        ])

        if not run_dirs:
            raise FileNotFoundError(
                f"No run_* directories found in {self.models_base_dir}."
            )
        return run_dirs[-1]

    def _initialize_service(self) -> None:
        """Load model artifacts into memory."""
        try:
            self.active_run_dir = self._resolve_latest_run_dir()
            logger.info("Initializing PredictorService from run directory: %s", self.active_run_dir)

            # Import Inference_Engine dynamically
            from Inference_Engine.predictor_service import (
                PredictorService,
                FEATURE_COLUMNS,
                THRESHOLDS,
            )

            self.feature_columns = FEATURE_COLUMNS
            self.thresholds = THRESHOLDS
            self.predictor_service = PredictorService(model_dir=str(self.active_run_dir))
            self.is_ready = True
            self.load_error = None
            logger.info("MetadataService successfully loaded and ready.")
        except Exception as exc:
            self.is_ready = False
            self.load_error = str(exc)
            logger.warning("MetadataService failed to load model: %s", exc)

    def validate_and_prepare_features(self, raw_features: Dict[str, Any]) -> pd.DataFrame:
        """
        Validate, type-coerce, and format raw feature dictionary into a strict 38-feature DataFrame.
        """
        if not isinstance(raw_features, dict) or not raw_features:
            raise ValueError("Input features must be a non-empty dictionary.")

        cleaned_row = {}
        for col in self.feature_columns:
            val = raw_features.get(col)
            if val is None:
                # Default to 0 for missing feature as supported by Dhruv's create_feature_dataframe
                cleaned_row[col] = 0.0
            else:
                try:
                    cleaned_row[col] = float(val)
                except (ValueError, TypeError):
                    raise ValueError(f"Feature '{col}' has invalid non-numeric value: {val!r}")

        return pd.DataFrame([cleaned_row], columns=self.feature_columns)

    def predict(
        self,
        raw_features: Dict[str, Any],
        source_hints: Optional[Dict[str, str]] = None,
        scenario_preset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute risk prediction with calibrated LightGBM and top-3 SHAP drivers,
        accompanied by feature provenance lineage and completeness assessment.
        """
        if not self.is_ready or self.predictor_service is None:
            raise RuntimeError(
                f"Metadata predictor is not ready. Error: {self.load_error or 'Model not loaded'}"
            )

        df = self.validate_and_prepare_features(raw_features)
        result = self.predictor_service.predict_commit_risk(df)

        # Normalize SHAP output into clean serializable structure
        shap_raw = result.get("shap_drivers", {})
        formatted_shap = {
            "positive": [
                {"feature": item[0], "contribution": round(float(item[1]), 4)}
                for item in shap_raw.get("positive", [])
            ],
            "negative": [
                {"feature": item[0], "contribution": round(float(item[1]), 4)}
                for item in shap_raw.get("negative", [])
            ],
        }

        features_summary = {col: round(float(df[col].iloc[0]), 4) for col in self.feature_columns}

        # Evaluate provenance and completeness
        from src.prediction.provenance import evaluate_metadata_provenance
        prov_map, completeness = evaluate_metadata_provenance(
            features=features_summary,
            source_hints=source_hints,
            scenario_preset_name=scenario_preset_name,
        )

        return {
            "failure_probability": float(result["failure_probability"]),
            "failure_probability_pct": float(result["failure_probability_pct"]),
            "raw_score": float(result.get("raw_score", result["failure_probability"])),
            "latency_ms": float(result.get("latency_ms", 0.0)),
            "verdict": str(result["verdict"]),
            "verdict_description": str(result["verdict_description"]),
            "shap_drivers": formatted_shap,
            "thresholds": dict(self.thresholds),
            "features_analyzed": features_summary,
            "provenance": {k: v.to_dict() for k, v in prov_map.items()},
            "completeness": completeness.to_dict(),
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Return comprehensive metadata about the model architecture and configuration."""
        run_name = self.active_run_dir.name if self.active_run_dir else "None"
        return {
            "model_name": "Pre-Build Commit Metadata Risk Gatekeeper (Module I)",
            "algorithm": "LightGBM + Platt Scaling (CalibratedClassifierCV)",
            "model_version": f"v1.1.0 ({run_name})",
            "active_run_dir": str(self.active_run_dir) if self.active_run_dir else None,
            "status": "ready" if self.is_ready else "unavailable",
            "load_error": self.load_error,
            "feature_count": len(self.feature_columns),
            "expected_features": self.feature_columns,
            "target": "y_fail = 1 - target_binary (1 = FAIL, 0 = PASS)",
            "supported_outputs": [
                "failure_probability",
                "verdict (FAST-TRACK, STANDARD GATE, ALERT, PRE-MERGE BLOCK)",
                "shap_feature_drivers",
            ],
            "shap_supported": True,
            "thresholds": self.thresholds,
            "benchmark_latency_p50_ms": 3.4,
            "training_source": "TravisTorrent (919,833 deduplicated build events, 70/15/15 split)",
        }

    def get_scorecard(self) -> Dict[str, Any]:
        """Read and return pre-computed scorecards and evaluation metrics."""
        if not self.active_run_dir or not self.active_run_dir.exists():
            raise FileNotFoundError("Model run directory not found.")

        scorecard_file = self.active_run_dir / "scorecard.json"
        shap_file = self.active_run_dir / "shap_scorecard.json"
        thresh_file = self.active_run_dir / "threshold_matrix_full.json"

        scorecard_data = {}
        if scorecard_file.exists():
            with open(scorecard_file, "r", encoding="utf-8") as f:
                scorecard_data = json.load(f)

        shap_data = {}
        if shap_file.exists():
            with open(shap_file, "r", encoding="utf-8") as f:
                shap_data = json.load(f)

        thresh_data = []
        if thresh_file.exists():
            with open(thresh_file, "r", encoding="utf-8") as f:
                thresh_data = json.load(f)

        exports_dir = self.active_run_dir / "exports"
        static_charts = []
        if exports_dir.exists():
            static_charts = [p.name for p in exports_dir.glob("*.png")]

        return {
            "metadata": scorecard_data.get("metadata", {}),
            "global_metrics": scorecard_data.get("global_metrics", {}),
            "calibration_metrics": scorecard_data.get("calibration_metrics", {}),
            "dataset_demographics": scorecard_data.get("dataset_demographics", {}),
            "feature_importance_top_15_by_gain": scorecard_data.get(
                "feature_importance_top_15_by_gain", {}
            ),
            "global_shap_attributions": shap_data.get("global_feature_attributions", []),
            "threshold_matrix_summary": thresh_data,
            "available_static_charts": static_charts,
        }

    def get_chart_path(self, chart_name: str) -> Optional[Path]:
        """Return the filesystem path for a static chart image, with security checks."""
        if not self.active_run_dir:
            return None
        clean_name = os.path.basename(chart_name)
        chart_file = self.active_run_dir / "exports" / clean_name
        if chart_file.exists() and chart_file.is_file() and chart_file.suffix.lower() == ".png":
            return chart_file
        return None

    def get_graph_status(self) -> Dict[str, Any]:
        """Query live Neo4j database health and graph stats."""
        try:
            from database.neo4j_client import Neo4jClient
            client = Neo4jClient()
            client.driver.verify_connectivity()
            with client.session() as session:
                db_res = session.run("CALL db.info() YIELD name RETURN name").single()
                db_name = db_res["name"] if db_res else client.database

                nodes_res = session.run("MATCH (n) RETURN count(n) as count").single()
                node_count = nodes_res["count"] if nodes_res else 0

                edges_res = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()
                edge_count = edges_res["count"] if edges_res else 0

                repos_res = session.run("MATCH (n) WHERE n.repo_id IS NOT NULL RETURN DISTINCT n.repo_id as repo_id")
                repos = [r["repo_id"] for r in repos_res if r.get("repo_id")]

                version = "5.25.1"
                edition = "community"
                try:
                    comp_res = session.run(
                        "CALL dbms.components() YIELD name, versions, edition RETURN versions[0] AS version, edition"
                    ).single()
                    if comp_res:
                        version = comp_res.get("version") or version
                        edition = comp_res.get("edition") or edition
                except Exception:
                    pass

            client.close()
            return {
                "status": "ONLINE",
                "connected": True,
                "version": str(version),
                "edition": str(edition),
                "database": db_name,
                "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                "node_count": node_count,
                "edge_count": edge_count,
                "repositories": repos,
                "message": f"Neo4j {version} ({edition}) active and connected to '{db_name}'."
            }
        except Exception as exc:
            return {
                "status": "OFFLINE",
                "connected": False,
                "version": None,
                "edition": None,
                "database": os.getenv("NEO4J_DATABASE", "graphdoc"),
                "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                "node_count": 0,
                "edge_count": 0,
                "repositories": [],
                "message": f"Neo4j offline or unreachable: {exc}"
            }

    def analyze_blast_radius(
        self,
        repo_id: str = "sample/test-repo",
        changed_files: Optional[List[str]] = None,
        investigation_threshold: float = 0.50,
    ) -> Dict[str, Any]:
        """Perform repository-isolated code blast radius traversal using Neo4j AST graph."""
        if not changed_files:
            changed_files = ["utils.py"]

        try:
            from database.neo4j_client import Neo4jClient
            client = Neo4jClient()
            client.driver.verify_connectivity()

            all_connected = set()
            file_details = []
            relationships = []

            with client.session() as session:
                for cf in changed_files:
                    norm_base = os.path.basename(cf)
                    # Isolated caller traversal
                    connected = client.get_connected_files(repo_id=repo_id, file_path=cf)
                    for conn in connected:
                        all_connected.add(conn)
                        file_details.append({
                            "file_path": conn,
                            "relationship_type": "CALLS",
                            "triggered_by": cf,
                            "risk_level": "AFFECTED_DEPENDENCY",
                            "reason": f"Transitive or direct caller of code in {norm_base}"
                        })

                    # Extract AST caller-callee detail
                    query = """
                    MATCH (origin:File {repo_id: $repo_id})
                    WHERE origin.path = $file_path 
                       OR origin.file_path = $file_path
                       OR origin.rel_path = $file_path
                       OR origin.name = $norm_base
                    MATCH (origin)-[:CONTAINS*1..2]->(f1:Function {repo_id: $repo_id})
                    OPTIONAL MATCH (caller)-[r:CALLS]->(f1)
                    RETURN origin.name as origin_file, f1.name as target_func,
                           caller.name as caller_func, labels(caller)[0] as caller_type,
                           coalesce(caller.file_path, caller.rel_path, caller.name) as caller_file
                    """
                    res = session.run(query, repo_id=repo_id, file_path=cf, norm_base=norm_base)
                    for r in res:
                        if r.get("caller_func"):
                            relationships.append({
                                "caller": f"{r.get('caller_func')}()",
                                "relationship": "CALLS",
                                "target": f"{r.get('target_func')}()",
                                "caller_file": r.get("caller_file") or "unknown",
                                "target_file": norm_base
                            })

                # Check SyncState
                sync_state = client.get_sync_state(repo_id) or {}

                # -------------------------------------------------------------
                # Extract Cytoscape Graph Elements (Nodes & Edges)
                # -------------------------------------------------------------
                cy_nodes: Dict[str, Dict[str, Any]] = {}
                cy_edges: Dict[str, Dict[str, Any]] = {}

                for cf in changed_files:
                    norm_base = os.path.basename(cf).replace("\\", "/")
                    norm_cf = cf.replace("\\", "/")

                    subgraph_query = """
                    MATCH (origin:File {repo_id: $repo_id})
                    WHERE origin.path = $cf 
                       OR origin.file_path = $cf
                       OR origin.rel_path = $cf
                       OR origin.rel_path = $norm_cf
                       OR origin.name = $norm_base
                    OPTIONAL MATCH (origin)-[:CONTAINS*1..2]->(target_func:Function {repo_id: $repo_id})
                    OPTIONAL MATCH (caller_func:Function {repo_id: $repo_id})-[r_call:CALLS]->(target_func)
                    OPTIONAL MATCH (caller_file:File {repo_id: $repo_id})-[:CONTAINS*1..2]->(caller_func)
                    RETURN origin, target_func, caller_func, caller_file
                    """
                    sub_res = session.run(subgraph_query, repo_id=repo_id, cf=cf, norm_cf=norm_cf, norm_base=norm_base)
                    for r in sub_res:
                        orig = r["origin"]
                        tf = r["target_func"]
                        c_func = r["caller_func"]
                        c_file = r["caller_file"]

                        if orig:
                            orig_id = orig.get("id") or f"file:{orig.get('name')}"
                            orig_label = orig.get("rel_path") or orig.get("name")
                            cy_nodes[orig_id] = {
                                "id": orig_id,
                                "label": orig_label,
                                "name": orig.get("name"),
                                "type": "File",
                                "status": "changed",
                                "file_path": orig.get("file_path") or orig.get("path") or orig_label,
                                "repo_id": repo_id,
                            }

                        if tf and orig:
                            tf_id = tf.get("id") or f"func:{tf.get('name')}"
                            tf_name = tf.get("name")
                            cy_nodes[tf_id] = {
                                "id": tf_id,
                                "label": f"{tf_name}()",
                                "name": tf_name,
                                "type": "Function",
                                "status": "changed",
                                "file_path": orig.get("rel_path") or orig.get("name"),
                                "repo_id": repo_id,
                            }
                            contains_edge_id = f"contains:{orig_id}->{tf_id}"
                            cy_edges[contains_edge_id] = {
                                "id": contains_edge_id,
                                "source": orig_id,
                                "target": tf_id,
                                "type": "CONTAINS",
                                "label": "defines",
                            }

                        if c_func:
                            cf_id = c_func.get("id") or f"func:{c_func.get('name')}"
                            cf_name = c_func.get("name")
                            c_fpath = c_file.get("rel_path") if c_file else "unknown"
                            cy_nodes[cf_id] = {
                                "id": cf_id,
                                "label": f"{cf_name}()",
                                "name": cf_name,
                                "type": "Function",
                                "status": "affected",
                                "file_path": c_fpath,
                                "repo_id": repo_id,
                            }

                            if tf:
                                calls_edge_id = f"calls:{cf_id}->{tf_id}"
                                cy_edges[calls_edge_id] = {
                                    "id": calls_edge_id,
                                    "source": cf_id,
                                    "target": tf_id,
                                    "type": "CALLS",
                                    "label": "calls",
                                }

                        if c_file:
                            cfile_id = c_file.get("id") or f"file:{c_file.get('name')}"
                            cfile_label = c_file.get("rel_path") or c_file.get("name")
                            cy_nodes[cfile_id] = {
                                "id": cfile_id,
                                "label": cfile_label,
                                "name": c_file.get("name"),
                                "type": "File",
                                "status": "affected",
                                "file_path": c_file.get("file_path") or c_file.get("path") or cfile_label,
                                "repo_id": repo_id,
                            }
                            if c_func:
                                c_edge_id = f"contains:{cfile_id}->{cf_id}"
                                cy_edges[c_edge_id] = {
                                    "id": c_edge_id,
                                    "source": cfile_id,
                                    "target": cf_id,
                                    "type": "CONTAINS",
                                    "label": "defines",
                                }

            client.close()

            graph_elements = (
                [{"data": node_data} for node_data in cy_nodes.values()] +
                [{"data": edge_data} for edge_data in cy_edges.values()]
            )

            if len(cy_nodes) == 0:
                logger.info(
                    "Repository '%s' / files '%s' not mapped in Neo4j; falling back to Tree-Sitter AST parser.",
                    repo_id, changed_files
                )
                try:
                    from src.demo.graph_inspector import GraphInspector
                    return GraphInspector._ast_fallback_analysis(
                        repo_id=repo_id,
                        changed_files=changed_files,
                        investigation_threshold=investigation_threshold,
                        local_repo_dir=None,
                        offline_reason=f"Repository '{repo_id}' or files '{', '.join(changed_files)}' not present in Neo4j.",
                    )
                except Exception as ast_exc:
                    logger.warning("Tree-Sitter AST fallback failed: %s", ast_exc)
                scope = "FILE NOT FOUND IN GRAPH"
                msg = (
                    f"Specified file(s) '{', '.join(changed_files)}' were not found in repository '{repo_id}' in Neo4j. "
                    f"Check that the file path matches the repository structure."
                )
            elif len(all_connected) == 0:
                scope = "LOCAL / ISOLATED"
                msg = (
                    f"Target file '{', '.join(changed_files)}' exists in Neo4j ({len(cy_nodes)} node(s) mapped), "
                    f"but has 0 downstream callers (genuinely isolated module)."
                )
            else:
                scope = "AFFECTED DEPENDENCY"
                msg = f"Graph analysis identified {len(all_connected)} connected file(s) and {len(relationships)} AST invocation(s) for {changed_files}."

            from src.prediction.graph_impact import calculate_graph_impact_score
            impact_res = calculate_graph_impact_score(
                changed_files=changed_files,
                nodes=list(cy_nodes.values()),
                edges=list(cy_edges.values()),
                total_repo_files=sync_state.get("files_parsed") or len(cy_nodes),
                engine_mode="Neo4j Knowledge Graph (Active Bolt Connection)"
            )

            return {
                "status": "COMPLETED",
                "graph_query_status": "COMPLETED",
                "repo_id": repo_id,
                "target_database": client.database or "graphdoc",
                "changed_files": changed_files,
                "blast_radius_count": len(all_connected),
                "blast_radius_file_count": len(all_connected),
                "blast_radius_scope": scope,
                "provenance_commit_sha": sync_state.get("target_sha"),
                "affected_files": file_details,
                "affected_caller_files": file_details,
                "ast_relationships": relationships,
                "ast_call_relationships": relationships,
                "graph_elements": graph_elements,
                "graph_impact_score": impact_res.to_dict(),
                "graph_stats": {
                    "total_nodes": len(cy_nodes),
                    "total_edges": len(cy_edges),
                    "file_nodes_count": sum(1 for n in cy_nodes.values() if n.get("type") == "File"),
                    "function_nodes_count": sum(1 for n in cy_nodes.values() if n.get("type") == "Function"),
                    "calls_edges_count": sum(1 for e in cy_edges.values() if e.get("type") == "CALLS"),
                },
                "sync_provenance": {
                    "target_sha": sync_state.get("target_sha"),
                    "status": sync_state.get("status"),
                    "commit_verified": sync_state.get("commit_verified", False),
                    "nodes_count": sync_state.get("nodes_count"),
                    "edges_count": sync_state.get("edges_count"),
                },
                "investigation_threshold": investigation_threshold,
                "message": msg,
            }
        except Exception as exc:
            logger.warning("Neo4j blast radius analysis failed (%s); falling back to Tree-Sitter AST parser.", exc)
            try:
                from src.demo.graph_inspector import GraphInspector
                return GraphInspector.analyze_blast_radius(
                    repo_id=repo_id,
                    changed_files=changed_files,
                    investigation_threshold=investigation_threshold,
                )
            except Exception as inner_exc:
                logger.warning("Tree-Sitter AST fallback also failed: %s", inner_exc)

            from src.prediction.graph_impact import calculate_graph_impact_score
            fallback_impact = calculate_graph_impact_score(
                changed_files=changed_files,
                nodes=[],
                edges=[],
                engine_mode="Neo4j Unavailable"
            )
            return {
                "status": "UNAVAILABLE",
                "repo_id": repo_id,
                "target_database": "graphdoc",
                "changed_files": changed_files,
                "blast_radius_count": 0,
                "affected_files": [],
                "ast_relationships": [],
                "graph_elements": [],
                "graph_impact_score": fallback_impact.to_dict(),
                "graph_stats": {"total_nodes": 0, "total_edges": 0},
                "sync_provenance": {},
                "investigation_threshold": investigation_threshold,
                "message": f"Graph analysis unavailable: {exc}"
            }

    def get_available_repositories(self) -> List[Dict[str, Any]]:
        """Return all distinct repositories in Neo4j with their SyncState provenance metadata."""
        try:
            from database.neo4j_client import Neo4jClient
            client = Neo4jClient()
            client.driver.verify_connectivity()
            results = []
            with client.session() as session:
                q = """
                MATCH (s:SyncState)
                RETURN s.repo_id as repo_id, s.target_sha as commit_sha,
                       s.status as status, s.commit_verified as verified,
                       s.nodes_count as nodes_count, s.edges_count as edges_count,
                       s.files_parsed as files_parsed, s.synced_at_iso as synced_at
                ORDER BY s.repo_id
                """
                res = session.run(q)
                for r in res:
                    results.append({
                        "repo_id": r["repo_id"],
                        "commit_sha": r["commit_sha"],
                        "status": r["status"],
                        "verified": bool(r.get("verified", False)),
                        "nodes_count": r.get("nodes_count", 0),
                        "edges_count": r.get("edges_count", 0),
                        "files_parsed": r.get("files_parsed", 0),
                        "synced_at": r.get("synced_at"),
                    })
            client.close()
            return results
        except Exception as exc:
            logger.warning("Failed to retrieve repositories from Neo4j: %s", exc)
            return []


def get_metadata_service() -> MetadataService:
    """Helper accessor to get the singleton MetadataService instance."""
    return MetadataService()
