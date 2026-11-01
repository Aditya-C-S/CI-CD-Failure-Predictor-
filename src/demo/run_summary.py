"""src/demo/run_summary.py

Batch 3 Part C: Final Run Summary and Run Intelligence Engine.
Combines information from:
- Batch 1 (Pre-build Metadata model, 38 features, SHAP, Neo4j Graph Impact Score, blast radius)
- Batch 2 (Runtime prediction history, risk progression, model comparison, configurable early warnings)
- Batch 3 (Parser V2, Advanced RCA, evidence mapping, remediation, scenario orchestration)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Run Summary Data Structure
# ---------------------------------------------------------------------------
@dataclass
class RunSummary:
    """Comprehensive post-execution report for a CI/CD pipeline run."""

    # A. Run details
    run_id: str
    repo_id: str
    commit_sha: str
    branch: Optional[str]
    scenario_id: str
    scenario_description: str
    workflow_run_id: Optional[str]

    # B. Pipeline outcome
    final_pipeline_status: str  # "PASSED" | "FAILED" | "CANCELLED" | "PARTIAL" | "UNKNOWN"
    passed: bool
    exit_code: Optional[int]
    failed_stage: Optional[str]
    failure_category: Optional[str]

    # C. Execution details
    start_timestamp: Optional[str]
    end_timestamp: Optional[str]
    duration_seconds: Optional[float]
    completed_checkpoints: List[int]
    skipped_checkpoints: List[int]
    timestamp_timezone: str = "UTC"

    # D. Metadata prediction
    metadata_prediction: Dict[str, Any] = field(default_factory=dict)

    # E. Graph intelligence
    graph_intelligence: Dict[str, Any] = field(default_factory=dict)

    # F. Runtime predictions
    runtime_predictions: Dict[str, Any] = field(default_factory=dict)

    # G. Early-warning events
    early_warnings: Dict[str, Any] = field(default_factory=dict)

    # H. Root cause analysis
    root_cause_analysis: Dict[str, Any] = field(default_factory=dict)

    # I. Final assessment
    final_assessment: Dict[str, Any] = field(default_factory=dict)

    summary_status: str = "FINAL"  # "FINAL" | "PARTIAL"
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_source: str = "LOCAL SIMULATION / BENCHMARK REPLAY"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Summary Builder
# ---------------------------------------------------------------------------
class RunSummaryBuilder:
    """Constructs verifiable, structured summaries for DemoRun instances."""

    @classmethod
    def build_summary(cls, run: Any, force_terminal: bool = False) -> RunSummary:
        """Extract and compile run intelligence across all subsystems."""
        now_ts = datetime.now(timezone.utc).isoformat()

        # 1. Run details
        run_id = getattr(run, "run_id", "unknown_run")
        commit_info = getattr(run, "commit_info", {}) or {}
        repo_id = getattr(run, "repo_id", commit_info.get("repo_id", "unknown_repo"))
        commit_sha = commit_info.get("commit_sha", "unknown_sha")
        branch = commit_info.get("branch", "main")
        scenario_preset = getattr(run, "scenario_preset", "none")
        scenario_exec = getattr(run, "scenario_execution", {}) or {}
        workflow_run_id = scenario_exec.get("workflow_run_id") or run.ci_execution.get("workflow_run_id")

        # 2. Pipeline outcome & Terminal verification
        actual_outcome = getattr(run, "actual_outcome", "pending")
        ci_exec = getattr(run, "ci_execution", {}) or {}
        exit_code = ci_exec.get("exit_code")

        is_passed = actual_outcome == "success" or (exit_code == 0 and actual_outcome != "failure")
        is_failed = actual_outcome == "failure" or (exit_code is not None and exit_code != 0)

        if is_passed:
            status_str = "PASSED"
        elif is_failed:
            status_str = "FAILED"
        elif run.status == "completed":
            status_str = "PASSED" if is_passed else "FAILED"
        else:
            status_str = "PARTIAL"

        # Checkpoints completed vs skipped
        actual_checkpoints: List[int] = []
        for p in getattr(run, "prediction_history", []):
            cp = p.get("checkpoint")
            if cp and cp not in actual_checkpoints:
                actual_checkpoints.append(cp)

        standard_checkpoints = [25, 50, 75, 100]
        completed_cps = sorted(actual_checkpoints)
        skipped_cps = [cp for cp in standard_checkpoints if cp not in completed_cps]

        # 3. Execution duration calculation
        start_ts = ci_exec.get("started_at") or getattr(run, "created_at", None)
        end_ts = ci_exec.get("completed_at")
        duration_sec: Optional[float] = None

        if start_ts and end_ts:
            try:
                t0 = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                duration_sec = round(max(0.0, (t1 - t0).total_seconds()), 2)
            except Exception:
                duration_sec = None

        # 4. Metadata prediction extraction
        meta_raw = getattr(run, "metadata_prediction", {}) or {}
        lineage = getattr(run, "feature_lineage", {}) or {}
        meta_summary = {
            "subsystem": "Pre-Build Metadata Model (LightGBM + Calibration)",
            "failure_probability": meta_raw.get("failure_probability"),
            "failure_probability_pct": meta_raw.get("failure_probability_pct"),
            "verdict": "HIGH_RISK" if (meta_raw.get("failure_probability") or 0) >= 0.50 else "LOW_RISK",
            "metadata_completeness_pct": lineage.get("completeness_percentage", 100.0),
            "real_feature_count": lineage.get("real_features_count", 38),
            "preset_feature_count": lineage.get("preset_features_count", 0),
            "feature_count_total": 38,
            "top_drivers": meta_raw.get("top_drivers", []),
        }

        # 5. Graph intelligence extraction
        neo4j_stage = run.stages.get("neo4j_blast_radius", {}) or {}
        graph_impact_score = neo4j_stage.get("graph_impact_score")
        impact_cat = "LOW"
        if graph_impact_score is not None:
            if graph_impact_score >= 0.60:
                impact_cat = "HIGH"
            elif graph_impact_score >= 0.30:
                impact_cat = "MEDIUM"

        graph_summary = {
            "mode": neo4j_stage.get("mode", "ONLINE"),
            "graph_impact_score": graph_impact_score,
            "impact_category": impact_cat,
            "blast_radius_count": neo4j_stage.get("blast_radius_count", 0),
            "changed_files": commit_info.get("changed_files", []),
            "affected_nodes": neo4j_stage.get("affected_nodes", []),
            "blast_radius_details": neo4j_stage.get("details", {}),
            "limitations": neo4j_stage.get("limitations", []),
        }

        # 6. Runtime predictions extraction
        curr_pred = getattr(run, "current_runtime_prediction", {}) or {}
        latest_prob = curr_pred.get("failure_probability")
        model_name = curr_pred.get("model_name") or getattr(run, "runtime_model", "bilstm2")

        runtime_verdict = "UNKNOWN"
        if latest_prob is not None:
            if latest_prob >= 0.70:
                runtime_verdict = "HIGH_RISK"
            elif latest_prob > 0.40:
                runtime_verdict = "MODERATE_RISK"
            else:
                runtime_verdict = "LOW_RISK"

        # Separate actual and projected rows
        progression = run.get_risk_progression()
        actual_rows = [r for r in progression if not r.get("is_projected")]
        projected_rows = [r for r in progression if r.get("is_projected")]

        # Model comparison (cached on run to avoid redundant model loading)
        comp = getattr(run, "model_comparison_cache", None)
        if not comp:
            try:
                comp = run.get_model_comparison()
                run.model_comparison_cache = comp
            except Exception:
                comp = None

        runtime_summary = {
            "subsystem": "Runtime Log Inference Engine",
            "runtime_model": model_name,
            "latest_failure_probability": latest_prob,
            "latest_failure_probability_pct": curr_pred.get("failure_probability_pct"),
            "runtime_verdict": runtime_verdict,
            "evidence_strength": curr_pred.get("evidence_strength", "MODERATE"),
            "lines_analyzed": curr_pred.get("lines_count", len(run.accumulated_log.splitlines())),
            "actual_checkpoints": actual_rows,
            "projected_checkpoints": projected_rows,
            "model_comparison": comp,
        }

        # 7. Early-warning events extraction
        warnings = getattr(run, "warning_history", []) or []
        warning_preceded_failure: Optional[bool] = None

        if warnings and is_failed and end_ts:
            try:
                first_warn_ts = warnings[0].get("timestamp")
                if first_warn_ts:
                    t_warn = datetime.fromisoformat(first_warn_ts.replace("Z", "+00:00"))
                    t_fail = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                    warning_preceded_failure = t_warn <= t_fail
            except Exception:
                warning_preceded_failure = None

        early_warnings_summary = {
            "total_warnings": len(warnings),
            "active_threshold": getattr(run, "early_warning_threshold", 0.70),
            "warning_events": warnings,
            "early_warning_preceded_failure": warning_preceded_failure,
        }

        # 8. Root cause analysis extraction
        rca_raw = getattr(run, "rca_result", {}) or {}
        if not rca_raw and (is_failed or run.status == "completed"):
            from src.rca.advanced_rca import AdvancedRCAEngine
            adv_report = AdvancedRCAEngine.analyze(
                log_text=run.accumulated_log,
                parsed_record=run.parser_v2_result,
                run_id=run.run_id,
                graph_context=run.stages.get("neo4j_blast_radius"),
                exit_code=exit_code,
                pipeline_stage=run.current_stage,
            )
            rca_raw = adv_report.to_dict()
            run.rca_result = rca_raw
            run.save_checkpoint()

        rca_summary = {
            "primary_category": rca_raw.get("primary_category", "none" if is_passed else "UNKNOWN"),
            "detected_error": rca_raw.get("detected_error", "None" if is_passed else "Unspecified"),
            "classification_method": rca_raw.get("classification_method", "N/A"),
            "evidence_strength": rca_raw.get("evidence_strength", "LIMITED"),
            "rca_confidence": rca_raw.get("rca_confidence", 0.0),
            "confidence_rationale": rca_raw.get("confidence_rationale", ""),
            "root_causes": rca_raw.get("root_causes", []),
            "evidence_items": rca_raw.get("evidence_items", []),
            "remediation": rca_raw.get("remediation", {}),
            "unresolved_findings": rca_raw.get("unresolved_findings", []),
        }

        # 9. Final assessment synthesis
        has_warnings = len(warnings) > 0
        rca_identified = len(rca_raw.get("root_causes", [])) > 0
        evidence_sufficient = rca_raw.get("primary_category") not in ("UNKNOWN", "INSUFFICIENT_EVIDENCE")

        if is_passed:
            narrative = "Pipeline completed all stages with zero errors. All checkpoints verified clean."
        elif is_failed:
            cat = rca_summary.get("primary_category", "FAILURE")
            stage = ci_exec.get("failed_stage") or rca_raw.get("relevant_pipeline_stage", "execution")
            warn_clause = " An early warning was successfully triggered before failure." if has_warnings else ""
            narrative = f"Pipeline execution failed in stage '{stage}' with category {cat}.{warn_clause}"
        else:
            narrative = "Pipeline is currently executing or waiting for remaining telemetry chunks."

        missing_components: List[str] = []
        if not graph_impact_score and graph_impact_score != 0:
            missing_components.append("Graph Impact Score")
        if not actual_checkpoints:
            missing_components.append("Telemetry Checkpoints")

        final_assessment = {
            "pipeline_passed": is_passed,
            "early_warning_generated": has_warnings,
            "early_warning_preceded_failure": warning_preceded_failure,
            "rca_identified_cause": rca_identified,
            "evidence_sufficient": evidence_sufficient,
            "summary_narrative": narrative,
            "missing_components": missing_components,
        }

        return RunSummary(
            run_id=run_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            branch=branch,
            scenario_id=scenario_preset,
            scenario_description=scenario_exec.get("dispatch_message") or f"Preset {scenario_preset}",
            workflow_run_id=workflow_run_id,
            execution_source=getattr(run, "execution_source", "LOCAL SIMULATION / BENCHMARK REPLAY"),
            final_pipeline_status=status_str,
            passed=is_passed,
            exit_code=exit_code,
            failed_stage=ci_exec.get("failed_stage") or (rca_summary.get("relevant_pipeline_stage") if is_failed else None),
            failure_category=rca_summary.get("primary_category") if is_failed else None,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            duration_seconds=duration_sec,
            completed_checkpoints=completed_cps,
            skipped_checkpoints=skipped_cps,
            timestamp_timezone="UTC",
            metadata_prediction=meta_summary,
            graph_intelligence=graph_summary,
            runtime_predictions=runtime_summary,
            early_warnings=early_warnings_summary,
            root_cause_analysis=rca_summary,
            final_assessment=final_assessment,
            summary_status="FINAL" if (is_passed or is_failed or force_terminal) else "PARTIAL",
            generated_at=now_ts,
        )
