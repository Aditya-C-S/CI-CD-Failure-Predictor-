"""src/rca/advanced_rca.py

Advanced Root Cause Analysis (RCA) Engine.
Integrates:
- Raw CI/CD logs
- Parser V2 structured findings
- Runtime prediction evidence
- 8-category failure classification
- Graph/repository evidence where available
- Multi-candidate root cause identification
- Verifiable line-by-line evidence mapping
- Actionable remediation suggestions with confirmed fixes vs troubleshooting
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from src.parser.parser_v2 import parse_log_text, LogRecord
from src.rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
    CAUSAL_TIMEOUT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
)
from src.remediation.suggestions import RemediationAdvisor


# ---------------------------------------------------------------------------
# Supported Failure Categories (at least 8 categories)
# ---------------------------------------------------------------------------
class FailureCategory:
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    SYNTAX_FAILURE = "SYNTAX_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    BUILD_FAILURE = "BUILD_FAILURE"
    DEPLOYMENT_FAILURE = "DEPLOYMENT_FAILURE"
    CONFIGURATION_FAILURE = "CONFIGURATION_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


ALL_CATEGORIES = [
    FailureCategory.DEPENDENCY_FAILURE,
    FailureCategory.SYNTAX_FAILURE,
    FailureCategory.TEST_FAILURE,
    FailureCategory.BUILD_FAILURE,
    FailureCategory.DEPLOYMENT_FAILURE,
    FailureCategory.CONFIGURATION_FAILURE,
    FailureCategory.INFRASTRUCTURE_FAILURE,
    FailureCategory.UNKNOWN,
    FailureCategory.INSUFFICIENT_EVIDENCE,
]


# ---------------------------------------------------------------------------
# Evidence & Root Cause Data Structures
# ---------------------------------------------------------------------------
@dataclass
class EvidenceItem:
    """Verifiable supporting evidence with original log mapping."""
    evidence_id: str
    source_type: str  # "parser_v2" | "raw_log" | "runtime_event" | "graph_evidence"
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    line_number: Optional[int] = None
    file_path: Optional[str] = None
    step_name: Optional[str] = None
    stage_name: Optional[str] = None
    error_text: str = ""
    relationship: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RootCauseCandidate:
    """Individual root cause finding linked to its evidence."""
    cause_id: str
    category: str
    what_failed: str
    where_failed: str
    why_failed: str
    is_confirmed: bool  # True if confirmed with explicit error trace, False if suspected
    evidence_strength: str  # "STRONG" | "MODERATE" | "LIMITED"
    confidence: float  # 0.0 to 1.0
    supporting_evidence_ids: List[str] = field(default_factory=list)
    remediation_suggestions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdvancedRCAReport:
    """Comprehensive, evidence-grounded Root Cause Analysis report."""
    run_id: str
    timestamp: str
    primary_category: str
    detected_error: str
    matched_evidence: str
    relevant_pipeline_stage: str
    classification_method: str
    evidence_strength: str  # "STRONG" | "MODERATE" | "LIMITED"
    rca_confidence: float  # 0.0 to 1.0 (heuristic confidence, strictly distinct from ML probability)
    confidence_rationale: str
    root_causes: List[RootCauseCandidate] = field(default_factory=list)
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    remediation: Dict[str, Any] = field(default_factory=dict)
    graph_evidence: Optional[Dict[str, Any]] = None
    status: str = "COMPLETED"  # "COMPLETED" | "PARTIAL" | "INSUFFICIENT_EVIDENCE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "primary_category": self.primary_category,
            "detected_error": self.detected_error,
            "matched_evidence": self.matched_evidence,
            "relevant_pipeline_stage": self.relevant_pipeline_stage,
            "classification_method": self.classification_method,
            "evidence_strength": self.evidence_strength,
            "rca_confidence": round(self.rca_confidence, 4),
            "confidence_rationale": self.confidence_rationale,
            "root_causes": [rc.to_dict() for rc in self.root_causes],
            "evidence_items": [ev.to_dict() for ev in self.evidence_items],
            "remediation": self.remediation,
            "graph_evidence": self.graph_evidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdvancedRCAReport:
        rc_list = [RootCauseCandidate(**rc) for rc in data.get("root_causes", [])]
        ev_list = [EvidenceItem(**ev) for ev in data.get("evidence_items", [])]
        return cls(
            run_id=data.get("run_id", "unknown_run"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            primary_category=data.get("primary_category", FailureCategory.UNKNOWN),
            detected_error=data.get("detected_error", ""),
            matched_evidence=data.get("matched_evidence", ""),
            relevant_pipeline_stage=data.get("relevant_pipeline_stage", "unknown"),
            classification_method=data.get("classification_method", "UNKNOWN"),
            evidence_strength=data.get("evidence_strength", "LIMITED"),
            rca_confidence=data.get("rca_confidence", 0.0),
            confidence_rationale=data.get("confidence_rationale", ""),
            root_causes=rc_list,
            evidence_items=ev_list,
            remediation=data.get("remediation", {}),
            graph_evidence=data.get("graph_evidence"),
            status=data.get("status", "COMPLETED"),
        )


# ---------------------------------------------------------------------------
# Advanced RCA Engine Implementation
# ---------------------------------------------------------------------------
class AdvancedRCAEngine:
    """
    Evidence-grounded RCA engine combining Parser V2, raw log scanning,
    failure classification, and graph intelligence.
    """

    @classmethod
    def analyze(
        cls,
        log_text: str,
        parsed_record: Optional[Union[LogRecord, Dict[str, Any]]] = None,
        run_id: str = "run_default",
        graph_context: Optional[Dict[str, Any]] = None,
        exit_code: Optional[int] = None,
        pipeline_stage: Optional[str] = None,
    ) -> AdvancedRCAReport:
        """
        Produce a comprehensive RCA report from log text and/or Parser V2 records.
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        if not log_text or not log_text.strip():
            return AdvancedRCAReport(
                run_id=run_id,
                timestamp=now_ts,
                primary_category=FailureCategory.INSUFFICIENT_EVIDENCE,
                detected_error="No log content available",
                matched_evidence="Empty log stream",
                relevant_pipeline_stage=pipeline_stage or "unknown",
                classification_method="EMPTY_LOG",
                evidence_strength="LIMITED",
                rca_confidence=0.0,
                confidence_rationale="Log stream is empty; no failure evidence can be extracted.",
                root_causes=[],
                evidence_items=[],
                remediation={
                    "recommended_actions": ["Ensure CI runner streams console output to the ingestion endpoint."],
                    "terminal_commands": [],
                    "prevention_tips": ["Check runner connectivity and DEMO_API_KEY configuration."],
                },
                graph_evidence=graph_context,
                status="INSUFFICIENT_EVIDENCE",
            )

        # 1. Obtain or use Parser V2 record
        if parsed_record is None:
            parsed_record = parse_log_text(log_text, run_id=run_id)

        # Extract parsed fields
        if isinstance(parsed_record, dict):
            p_class = parsed_record.get("failure_class")
            p_subcat = parsed_record.get("failure_subcategory")
            p_file = parsed_record.get("file_path")
            p_line = parsed_record.get("line_number")
            p_msg = parsed_record.get("error_message")
            p_matched = parsed_record.get("matched_line")
            p_step = parsed_record.get("step_name")
            p_stage = parsed_record.get("stage")
            p_exit = parsed_record.get("exit_code") or exit_code
            p_ev_lines = parsed_record.get("evidence_lines") or []
        else:
            p_class = getattr(parsed_record, "failure_class", None)
            p_subcat = getattr(parsed_record, "failure_subcategory", None)
            p_file = getattr(parsed_record, "file_path", None)
            p_line = getattr(parsed_record, "line_number", None)
            p_msg = getattr(parsed_record, "error_message", None)
            p_matched = getattr(parsed_record, "matched_line", None)
            p_step = getattr(parsed_record, "step_name", None)
            p_stage = getattr(parsed_record, "stage", None)
            p_exit = getattr(parsed_record, "exit_code", None) or exit_code
            p_ev_lines = getattr(parsed_record, "evidence_lines", []) or []

        resolved_stage = p_stage or pipeline_stage or "execution"

        # Find line index mappings in raw log
        log_lines = log_text.splitlines()
        evidence_items: List[EvidenceItem] = []
        root_causes: List[RootCauseCandidate] = []

        # 2. Evidence mapping: locate exact line numbers for matched evidence
        ev_id_counter = 1

        def _find_log_line_number(pattern_text: str) -> Optional[int]:
            if not pattern_text:
                return None
            clean_pat = pattern_text.strip()
            for idx, line in enumerate(log_lines, start=1):
                if clean_pat in line:
                    return idx
            return None

        # Add parser matched line evidence if present
        if p_matched:
            found_line = _find_log_line_number(p_matched) or p_line
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{ev_id_counter}",
                    source_type="parser_v2",
                    line_number=found_line,
                    line_start=found_line,
                    line_end=found_line,
                    file_path=p_file,
                    step_name=p_step,
                    stage_name=resolved_stage,
                    error_text=p_matched.strip(),
                    relationship="Primary failure signature identified by Parser V2.",
                )
            )
            ev_id_counter += 1

        # Add auxiliary evidence lines
        for aux_line in p_ev_lines:
            if aux_line and aux_line != p_matched:
                ln = _find_log_line_number(aux_line)
                evidence_items.append(
                    EvidenceItem(
                        evidence_id=f"ev_{ev_id_counter}",
                        source_type="raw_log",
                        line_number=ln,
                        line_start=ln,
                        line_end=ln,
                        file_path=p_file,
                        step_name=p_step,
                        stage_name=resolved_stage,
                        error_text=aux_line.strip(),
                        relationship="Supporting context from error stream.",
                    )
                )
                ev_id_counter += 1

        # Scan raw log for additional critical signatures (e.g. exit codes, tracebacks)
        for idx, line in enumerate(log_lines, start=1):
            if re.search(r"##\[error\]|Process completed with exit code [1-9]|AssertionError|ModuleNotFoundError|SyntaxError", line):
                # Avoid duplicate if already covered
                if not any(ev.line_number == idx for ev in evidence_items):
                    evidence_items.append(
                        EvidenceItem(
                            evidence_id=f"ev_{ev_id_counter}",
                            source_type="raw_log",
                            line_number=idx,
                            line_start=idx,
                            line_end=idx,
                            file_path=p_file,
                            step_name=p_step,
                            stage_name=resolved_stage,
                            error_text=line.strip(),
                            relationship="Process termination or assertion error in log stream.",
                        )
                    )
                    ev_id_counter += 1

        # Add graph evidence if provided
        if graph_context and graph_context.get("affected_files"):
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{ev_id_counter}",
                    source_type="graph_evidence",
                    file_path=graph_context.get("affected_files", [None])[0],
                    step_name="Graph Blast Radius Analysis",
                    stage_name="pre_build",
                    error_text=f"Graph impact score {graph_context.get('graph_impact_score', 'N/A')} across {len(graph_context.get('affected_files', []))} files.",
                    relationship="Repository blast radius and dependency ripple potential.",
                )
            )
            ev_id_counter += 1

        # 3. Classify Failure Category & Diagnose Root Cause
        category = FailureCategory.UNKNOWN
        classification_method = "PARSER_V2_AST" if p_class else "LOG_HEURISTIC"
        detected_error = p_msg or p_matched or "Unspecified failure"
        matched_evidence = p_matched or (evidence_items[0].error_text if evidence_items else "No evidence")
        evidence_strength = "LIMITED"
        rca_confidence = 0.50
        confidence_rationale = ""

        # --- A. DEPENDENCY FAILURE ---
        if p_class == "dependency_error" or re.search(
            r"Could not find a version that satisfies the requirement|No matching distribution found|ModuleNotFoundError|ImportError|pip install.*failed",
            log_text,
            re.IGNORECASE,
        ):
            category = FailureCategory.DEPENDENCY_FAILURE
            classification_method = "PARSER_V2_DEPENDENCY_RULE"
            evidence_strength = "STRONG" if p_matched or "Could not find a version" in log_text else "MODERATE"
            rca_confidence = 0.95 if "Could not find a version" in log_text else 0.85
            confidence_rationale = (
                f"High confidence ({rca_confidence:.0%}) based on explicit pip package resolution failure and exit code {p_exit or 1}."
            )
            what_failed = "Python dependency installation failed."
            where_failed = f"Stage: {resolved_stage}" + (f", Step: {p_step}" if p_step else "")
            why_failed = (
                f"Package resolution failure detected: {p_msg or p_matched or 'One or more required packages could not be installed from PyPI'}."
            )
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "CONFIRMED_FIX",
                            "action": "Verify package name spelling and compatible version constraints in requirements.txt.",
                            "command": "pip check && pip install -r requirements.txt --dry-run",
                        },
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Ensure the target package exists on PyPI and supports Python 3.12.",
                            "command": "pip index versions <package_name>",
                        },
                    ],
                )
            )

        # --- B. SYNTAX FAILURE ---
        elif p_class == "syntax_error" or re.search(
            r"\b(SyntaxError|IndentationError|TabError)\b", log_text
        ):
            category = FailureCategory.SYNTAX_FAILURE
            classification_method = "PARSER_V2_SYNTAX_PARSER"
            evidence_strength = "STRONG" if p_file and p_line else "MODERATE"
            rca_confidence = 0.95 if p_file and p_line else 0.88
            loc_str = f"{p_file}:{p_line}" if p_file and p_line else "source file"
            confidence_rationale = (
                f"Definitive syntax exception identified at {loc_str} with AST error details."
            )
            what_failed = f"Python syntax / grammar parsing failed in {loc_str}."
            where_failed = f"{loc_str} in stage '{resolved_stage}'"
            why_failed = f"Invalid Python syntax: {p_msg or p_matched or 'unexpected token or unclosed delimiter'}."
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "CONFIRMED_FIX",
                            "action": f"Inspect line {p_line or 'N/A'} of {p_file or 'the failing file'} and correct syntax.",
                            "command": f"python -m py_compile {p_file or '*.py'}",
                        },
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Run a linter across the repository to verify file formatting.",
                            "command": "ruff check .",
                        },
                    ],
                )
            )

        # --- C. TEST FAILURE ---
        elif p_class == "test_failure" or re.search(
            r"\b(FAILURES|FAILED|AssertionError)\b.*(?:test_|tests/)", log_text
        ) or "pytest" in log_text and re.search(r"=+\s+FAILURES\s+=+", log_text):
            category = FailureCategory.TEST_FAILURE
            classification_method = "PARSER_V2_TEST_ANALYZER"
            evidence_strength = "STRONG" if "AssertionError" in log_text else "MODERATE"
            rca_confidence = 0.92
            confidence_rationale = (
                f"Unit/Integration test runner (pytest) reported failed test assertions."
            )
            what_failed = "Automated test suite failed assertions."
            where_failed = f"{p_file or 'tests/'}" + (f":{p_line}" if p_line else "")
            why_failed = f"Test assertion mismatch: {p_msg or p_matched or 'AssertionError during test execution'}."
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "CONFIRMED_FIX",
                            "action": f"Reproduce and fix the failing test assertion locally.",
                            "command": "pytest tests/ -v -k 'failed'",
                        },
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Inspect test mock fixtures and unexpected state transitions.",
                            "command": "pytest --tb=short",
                        },
                    ],
                )
            )

        # --- D. BUILD FAILURE ---
        elif p_class == "docker_build_failure" or re.search(
            r"failed to solve|COPY failed|dockerfile parse error|Cannot connect to the Docker daemon|build step failed",
            log_text,
            re.IGNORECASE,
        ):
            category = FailureCategory.BUILD_FAILURE
            classification_method = "PARSER_V2_BUILD_RULES"
            evidence_strength = "STRONG"
            rca_confidence = 0.90
            confidence_rationale = "Docker / Compiler build step produced fatal build error."
            what_failed = "Container or project compilation build step failed."
            where_failed = f"Build step: {p_step or 'Docker Build'}"
            why_failed = f"Build failure: {p_msg or p_matched or 'Docker build context or build instruction failed'}."
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "CONFIRMED_FIX",
                            "action": "Verify Dockerfile instruction syntax and local build context paths.",
                            "command": "docker build -t test-build .",
                        },
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Ensure all files copied by COPY/ADD directives exist in context.",
                            "command": "git status",
                        },
                    ],
                )
            )

        # --- E. DEPLOYMENT FAILURE ---
        elif re.search(
            r"deployment failed|kubectl.*error|helm.*error|cluster unreachable|deploy step timed out",
            log_text,
            re.IGNORECASE,
        ):
            category = FailureCategory.DEPLOYMENT_FAILURE
            classification_method = "HEURISTIC_DEPLOYMENT_ANALYZER"
            evidence_strength = "MODERATE"
            rca_confidence = 0.80
            confidence_rationale = "Target cluster deployment or rollout step failed."
            what_failed = "Deployment or rollout operation failed."
            where_failed = f"Deployment step: {p_step or 'Deploy'}"
            why_failed = "Deployment endpoint or cluster communication failed."
            is_confirmed = False

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Verify kubeconfig credentials and cluster network reachability.",
                            "command": "kubectl get nodes",
                        }
                    ],
                )
            )

        # --- F. CONFIGURATION FAILURE ---
        elif p_class == "ci_config_permission_failure" or re.search(
            r"Workflow is not valid|Invalid workflow file|Unexpected symbol.*workflow|403 Forbidden|insufficient permissions for token|GITHUB_TOKEN does not have permission",
            log_text,
            re.IGNORECASE,
        ):
            category = FailureCategory.CONFIGURATION_FAILURE
            classification_method = "PARSER_V2_CONFIG_PERMISSION_RULES"
            evidence_strength = "STRONG"
            rca_confidence = 0.90
            confidence_rationale = "Workflow YAML syntax error or missing GitHub token permissions."
            what_failed = "CI/CD workflow configuration or permissions failure."
            where_failed = f"Workflow file / {p_step or 'CI Setup'}"
            why_failed = f"Invalid workflow syntax or permission denial: {p_msg or p_matched or '403 Forbidden'}."
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "CONFIRMED_FIX",
                            "action": "Grant appropriate repository/workflow permissions to GITHUB_TOKEN in repository settings.",
                            "command": "gh auth refresh -s workflow,repo",
                        },
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Validate workflow YAML file against GitHub Actions schema.",
                            "command": "actionlint",
                        },
                    ],
                )
            )

        # --- G. INFRASTRUCTURE / ENVIRONMENT FAILURE ---
        elif p_class == "timeout" or re.search(
            r"has timed out|operation was canceled because it has timed out|runner lost communication|Terminate orphan process",
            log_text,
            re.IGNORECASE,
        ):
            category = FailureCategory.INFRASTRUCTURE_FAILURE
            classification_method = "PARSER_V2_TIMEOUT_ANALYZER"
            evidence_strength = "STRONG" if "timed out" in log_text else "MODERATE"
            rca_confidence = 0.88
            confidence_rationale = "Workflow execution timeout or runner host cancellation detected."
            what_failed = "Runner environment timed out or lost connectivity."
            where_failed = f"Runner step: {p_step or 'Pipeline Execution'}"
            why_failed = "Pipeline execution exceeded timeout threshold or runner was terminated."
            is_confirmed = True

            root_causes.append(
                RootCauseCandidate(
                    cause_id="rc_1",
                    category=category,
                    what_failed=what_failed,
                    where_failed=where_failed,
                    why_failed=why_failed,
                    is_confirmed=is_confirmed,
                    evidence_strength=evidence_strength,
                    confidence=rca_confidence,
                    supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                    remediation_suggestions=[
                        {
                            "type": "TROUBLESHOOTING",
                            "action": "Increase step timeout or profile hanging network/compute calls.",
                            "command": "timeout-minutes: 15",
                        }
                    ],
                )
            )

        # --- H. UNKNOWN / INSUFFICIENT EVIDENCE ---
        else:
            if re.search(r"exit code [1-9]|##\[error\]", log_text):
                category = FailureCategory.UNKNOWN
                classification_method = "EXIT_CODE_FALLBACK"
                evidence_strength = "LIMITED"
                rca_confidence = 0.40
                confidence_rationale = (
                    "Non-zero exit code detected but specific error patterns did not match known failure classes."
                )
                detected_error = "Generic non-zero exit code"
                what_failed = "Step exited with non-zero status code."
                where_failed = f"Stage: {resolved_stage}"
                why_failed = "A command terminated with an error, but specific exception details were not captured."
                is_confirmed = False

                root_causes.append(
                    RootCauseCandidate(
                        cause_id="rc_1",
                        category=category,
                        what_failed=what_failed,
                        where_failed=where_failed,
                        why_failed=why_failed,
                        is_confirmed=is_confirmed,
                        evidence_strength=evidence_strength,
                        confidence=rca_confidence,
                        supporting_evidence_ids=[ev.evidence_id for ev in evidence_items],
                        remediation_suggestions=[
                            {
                                "type": "TROUBLESHOOTING",
                                "action": "Enable verbose CI step logging (e.g. set -x or --verbose) to isolate failing command.",
                                "command": "set -x",
                            }
                        ],
                    )
                )
            else:
                category = FailureCategory.INSUFFICIENT_EVIDENCE
                classification_method = "CLEAN_OR_INSUFFICIENT"
                evidence_strength = "LIMITED"
                rca_confidence = 0.10
                confidence_rationale = "Zero failure signatures detected in the provided log stream."
                detected_error = "No failure detected"
                matched_evidence = "Nominal execution stream"

        # 4. Generate Remediation structure
        remediation_data: Dict[str, Any] = {
            "primary_action": (
                root_causes[0].remediation_suggestions[0]["action"]
                if root_causes and root_causes[0].remediation_suggestions
                else "Review pipeline execution logs."
            ),
            "confirmed_fixes": [
                sugg
                for rc in root_causes
                for sugg in rc.remediation_suggestions
                if sugg.get("type") == "CONFIRMED_FIX"
            ],
            "troubleshooting": [
                sugg
                for rc in root_causes
                for sugg in rc.remediation_suggestions
                if sugg.get("type") == "TROUBLESHOOTING"
            ],
            "terminal_commands": [
                sugg.get("command")
                for rc in root_causes
                for sugg in rc.remediation_suggestions
                if sugg.get("command")
            ],
        }

        return AdvancedRCAReport(
            run_id=run_id,
            timestamp=now_ts,
            primary_category=category,
            detected_error=detected_error,
            matched_evidence=matched_evidence,
            relevant_pipeline_stage=resolved_stage,
            classification_method=classification_method,
            evidence_strength=evidence_strength,
            rca_confidence=rca_confidence,
            confidence_rationale=confidence_rationale,
            root_causes=root_causes,
            evidence_items=evidence_items,
            remediation=remediation_data,
            graph_evidence=graph_context,
            status="COMPLETED" if category not in (FailureCategory.UNKNOWN, FailureCategory.INSUFFICIENT_EVIDENCE) else "PARTIAL",
        )

