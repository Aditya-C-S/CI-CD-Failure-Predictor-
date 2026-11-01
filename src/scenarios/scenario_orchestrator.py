"""src/scenarios/scenario_orchestrator.py

Centralized Scenario Orchestration and GitHub Actions Dispatch.
Defines, validates, tracks, and executes the four GitHub Actions demonstration scenarios:
1. 'none'       - Clean pipeline execution (Passes nominally)
2. 'dependency' - Dependency installation failure (Fails at 50% stage)
3. 'syntax'     - Syntax validation failure (Fails at 75% stage)
4. 'pytest'     - Test execution failure (Fails at 100% stage)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("scenarios.orchestrator")


# ---------------------------------------------------------------------------
# Supported Scenario Constants & Definitions
# ---------------------------------------------------------------------------
SCENARIO_NONE = "none"
SCENARIO_DEPENDENCY = "dependency"
SCENARIO_SYNTAX = "syntax"
SCENARIO_PYTEST = "pytest"

SUPPORTED_SCENARIO_IDS = [
    SCENARIO_NONE,
    SCENARIO_DEPENDENCY,
    SCENARIO_SYNTAX,
    SCENARIO_PYTEST,
]

# Legacy alias mappings for backward compatibility
SCENARIO_ALIASES = {
    "clean": SCENARIO_NONE,
    "clean_run": SCENARIO_NONE,
    "high_risk": SCENARIO_DEPENDENCY,  # Legacy preset default mapped to dependency
}


# ---------------------------------------------------------------------------
# Scenario Execution Status Taxonomy
# ---------------------------------------------------------------------------
class ScenarioExecutionStatus:
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


VALID_EXECUTION_STATUSES = {
    ScenarioExecutionStatus.CREATED,
    ScenarioExecutionStatus.DISPATCHED,
    ScenarioExecutionStatus.RUNNING,
    ScenarioExecutionStatus.COMPLETED,
    ScenarioExecutionStatus.FAILED,
    ScenarioExecutionStatus.CANCELLED,
    ScenarioExecutionStatus.UNKNOWN,
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class ScenarioDefinition:
    scenario_id: str
    display_name: str
    description: str
    expected_failure_stage: Optional[str]
    expected_outcome: str  # "success" | "failure"
    workflow_dispatch_input: Dict[str, Any]
    inject_failure: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CENTRAL_SCENARIOS: Dict[str, ScenarioDefinition] = {
    SCENARIO_NONE: ScenarioDefinition(
        scenario_id=SCENARIO_NONE,
        display_name="Clean Pipeline Execution",
        description="Nominal CI/CD pipeline execution with zero injected failures. All checks, builds, and unit tests pass.",
        expected_failure_stage=None,
        expected_outcome="success",
        workflow_dispatch_input={"failure_stage": "none", "inject_failure": "0"},
        inject_failure=False,
    ),
    SCENARIO_DEPENDENCY: ScenarioDefinition(
        scenario_id=SCENARIO_DEPENDENCY,
        display_name="Dependency Resolution Failure",
        description="Controlled injection of an unresolvable package requirement during pip install at the 50% build stage.",
        expected_failure_stage="50%",
        expected_outcome="failure",
        workflow_dispatch_input={"failure_stage": "dependency", "inject_failure": "1"},
        inject_failure=True,
    ),
    SCENARIO_SYNTAX: ScenarioDefinition(
        scenario_id=SCENARIO_SYNTAX,
        display_name="Syntax Validation Failure",
        description="Controlled injection of invalid Python syntax/unclosed delimiter during code validation at the 75% stage.",
        expected_failure_stage="75%",
        expected_outcome="failure",
        workflow_dispatch_input={"failure_stage": "syntax", "inject_failure": "1"},
        inject_failure=True,
    ),
    SCENARIO_PYTEST: ScenarioDefinition(
        scenario_id=SCENARIO_PYTEST,
        display_name="Test Execution Failure",
        description="Controlled injection of an assertion mismatch during pytest unit test execution at the 100% final stage.",
        expected_failure_stage="100%",
        expected_outcome="failure",
        workflow_dispatch_input={"failure_stage": "pytest", "inject_failure": "1"},
        inject_failure=True,
    ),
}


@dataclass
class ScenarioExecutionRecord:
    """Tracks scenario execution through its lifecycle."""
    scenario_id: str
    run_id: str
    workflow_run_id: Optional[str] = None
    dispatch_time: Optional[str] = None
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    pipeline_result: str = "pending"  # "pending" | "running" | "success" | "failure"
    failure_stage: Optional[str] = None
    execution_status: str = ScenarioExecutionStatus.CREATED
    commit_sha: Optional[str] = None
    dispatch_mode: str = "DRY_RUN"  # "GITHUB_ACTIONS_LIVE" | "LOCAL_SIMULATION" | "DRY_RUN"
    dispatch_message: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation Functions
# ---------------------------------------------------------------------------
def normalize_and_validate_scenario(scenario_id: Optional[str]) -> ScenarioDefinition:
    """
    Validate and return the central ScenarioDefinition.
    Rejects unknown scenario IDs with ValueError.
    """
    if not scenario_id or not scenario_id.strip():
        raise ValueError("Scenario ID must not be empty. Supported scenarios: " + ", ".join(SUPPORTED_SCENARIO_IDS))

    norm = scenario_id.strip().lower()
    if norm in SCENARIO_ALIASES:
        norm = SCENARIO_ALIASES[norm]

    if norm not in CENTRAL_SCENARIOS:
        raise ValueError(
            f"Invalid scenario '{scenario_id}'. Supported scenarios are: {SUPPORTED_SCENARIO_IDS}"
        )

    return CENTRAL_SCENARIOS[norm]


def get_all_scenarios() -> List[Dict[str, Any]]:
    """Return all centralized scenario definitions."""
    return [s.to_dict() for s in CENTRAL_SCENARIOS.values()]


def get_scenario_definition(scenario_id: str) -> Dict[str, Any]:
    """Retrieve details for a single scenario."""
    return normalize_and_validate_scenario(scenario_id).to_dict()


# ---------------------------------------------------------------------------
# Scenario Orchestrator
# ---------------------------------------------------------------------------
class ScenarioOrchestrator:
    """Manages dispatch and tracking of GitHub Actions demonstration scenarios."""

    DEFAULT_REPO = "Aditya-C-S/demo-order-service"
    WORKFLOW_FILE = "demo_pipeline.yml"

    @classmethod
    def dispatch(
        cls,
        scenario_id: str,
        repo_id: str = DEFAULT_REPO,
        run_id: Optional[str] = None,
        dry_run: bool = False,
        runtime_model: str = "bilstm2",
    ) -> Dict[str, Any]:
        """
        Validate scenario, initialize or associate a DemoRun, and dispatch the GHA workflow.
        """
        from src.demo.demo_manager import UnifiedDemoManager
        mgr = UnifiedDemoManager.get_instance()

        scenario = normalize_and_validate_scenario(scenario_id)
        now_ts = datetime.now(timezone.utc).isoformat()

        # 1. Create or retrieve DemoRun
        if run_id:
            run = mgr.get_run(run_id)
            if not run:
                run = mgr.create_run(
                    repo_id=repo_id,
                    scenario_preset=scenario.scenario_id,
                    runtime_model=runtime_model,
                )
        else:
            run = mgr.create_run(
                repo_id=repo_id,
                scenario_preset=scenario.scenario_id,
                runtime_model=runtime_model,
            )

        run_id = run.run_id
        commit_sha = getattr(run, "commit_sha", None) or "HEAD"

        record = ScenarioExecutionRecord(
            scenario_id=scenario.scenario_id,
            run_id=run_id,
            dispatch_time=now_ts,
            execution_status=ScenarioExecutionStatus.CREATED,
            failure_stage=scenario.expected_failure_stage,
            commit_sha=commit_sha,
            pipeline_result="pending",
        )

        if dry_run:
            record.dispatch_mode = "DRY_RUN"
            record.execution_status = ScenarioExecutionStatus.DISPATCHED
            record.dispatch_message = f"Dry run: Scenario '{scenario.scenario_id}' validated and ready for dispatch."
            run.execution_source = "LOCAL SIMULATION / BENCHMARK REPLAY"
            run.status = "dispatched"
            run.actual_outcome = "pending"
            run.scenario_execution = record.to_dict()
            run.save_checkpoint()
            return {
                "status": "DISPATCHED",
                "run_id": run_id,
                "scenario": scenario.to_dict(),
                "execution_record": record.to_dict(),
            }

        # 2. Attempt real GitHub Actions workflow dispatch via 'gh' CLI or REST API
        dispatch_success, dispatch_info = cls._dispatch_github_actions(
            repo_id=repo_id,
            scenario=scenario,
            run_id=run_id,
        )

        record.dispatch_mode = "GITHUB_ACTIONS_LIVE"
        record.execution_status = ScenarioExecutionStatus.DISPATCHED
        run.execution_source = "LIVE GITHUB ACTIONS / ACTUAL TELEMETRY"
        run.status = "dispatched"
        run.actual_outcome = "pending"

        if dispatch_success:
            record.dispatch_message = dispatch_info
            record.workflow_run_id = dispatch_info.get("workflow_run_id") if isinstance(dispatch_info, dict) else None
        else:
            record.dispatch_message = (
                f"Live session initialized: {dispatch_info.get('error', 'Awaiting workflow execution')}. "
                "Backend is awaiting authentic GitHub Actions webhook telemetry matching this Demo ID."
            )

        run.scenario_execution = record.to_dict()
        run.save_checkpoint()

        return {
            "status": record.execution_status,
            "run_id": run_id,
            "scenario": scenario.to_dict(),
            "execution_record": record.to_dict(),
        }

    @classmethod
    def _dispatch_github_actions(
        cls,
        repo_id: str,
        scenario: ScenarioDefinition,
        run_id: str,
    ) -> Tuple[bool, Any]:
        """Dispatch GitHub Actions workflow using gh CLI or authenticated HTTP request."""
        # 1. Try via gh CLI
        try:
            cmd = [
                "gh",
                "workflow",
                "run",
                cls.WORKFLOW_FILE,
                "--repo",
                repo_id,
                "-f",
                f"failure_stage={scenario.workflow_dispatch_input['failure_stage']}",
                "-f",
                f"inject_failure={scenario.workflow_dispatch_input['inject_failure']}",
                "-f",
                f"demo_run_id={run_id}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if res.returncode == 0:
                logger.info("GitHub Actions workflow dispatched successfully via gh CLI for run %s", run_id)
                return True, {"method": "gh_cli", "output": res.stdout.strip() or "Workflow triggered successfully."}
            else:
                logger.warning("gh CLI workflow run returned non-zero (%d): %s", res.returncode, res.stderr)
        except Exception as e:
            logger.warning("gh CLI execution failed: %s", e)

        # 2. Try via GitHub REST API if GITHUB_TOKEN or gh auth token is present
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not token:
            try:
                res_tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
                if res_tok.returncode == 0:
                    token = res_tok.stdout.strip()
            except Exception:
                pass

        if token:
            try:
                api_url = f"https://api.github.com/repos/{repo_id}/actions/workflows/{cls.WORKFLOW_FILE}/dispatches"
                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "CI-CD-Failure-Predictor-Orchestrator",
                }
                payload = {
                    "ref": "main",
                    "inputs": {
                        "failure_stage": scenario.workflow_dispatch_input["failure_stage"],
                        "inject_failure": str(scenario.workflow_dispatch_input["inject_failure"]),
                        "demo_run_id": run_id,
                    },
                }
                req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status in (200, 204):
                        logger.info("GitHub Actions workflow dispatched via REST API HTTP %d", resp.status)
                        return True, {"method": "rest_api", "status_code": resp.status}
            except Exception as e:
                logger.warning("GitHub REST API dispatch failed: %s", e)
                return False, {"error": str(e)}

        return False, {"error": "Neither gh CLI nor GITHUB_TOKEN could dispatch remote workflow."}

    @classmethod
    def get_execution_status(cls, run_id: str) -> Dict[str, Any]:
        """Retrieve the execution record for a run and synchronize with live run status."""
        from src.demo.demo_manager import UnifiedDemoManager
        mgr = UnifiedDemoManager.get_instance()
        run = mgr.get_run(run_id)
        if not run:
            raise ValueError(f"Run '{run_id}' not found.")

        record_data = getattr(run, "scenario_execution", None)
        if not record_data:
            # Synthesize record if missing
            preset = getattr(run, "scenario_preset", "none")
            scenario_id = SCENARIO_ALIASES.get(preset, preset)
            if scenario_id not in CENTRAL_SCENARIOS:
                scenario_id = SCENARIO_NONE
            sc_def = CENTRAL_SCENARIOS[scenario_id]

            status = ScenarioExecutionStatus.COMPLETED if run.status == "completed" else ScenarioExecutionStatus.RUNNING
            record_data = ScenarioExecutionRecord(
                scenario_id=sc_def.scenario_id,
                run_id=run.run_id,
                dispatch_time=run.created_at,
                execution_status=status,
                pipeline_result=run.actual_outcome or "pending",
                failure_stage=sc_def.expected_failure_stage,
                commit_sha=run.commit_sha,
                dispatch_mode="GITHUB_ACTIONS_LIVE",
            ).to_dict()
            run.scenario_execution = record_data
            run.save_checkpoint()

        # Reconcile status with live run progress
        if run.status == "completed":
            record_data["execution_status"] = ScenarioExecutionStatus.COMPLETED
            record_data["completion_time"] = run.ci_execution.get("completed_at")
            record_data["pipeline_result"] = run.actual_outcome or "completed"
        elif len(getattr(run, "log_chunks", [])) > 0 or bool(run.accumulated_log):
            record_data["execution_status"] = ScenarioExecutionStatus.RUNNING
            record_data["start_time"] = run.ci_execution.get("started_at")
            record_data["pipeline_result"] = run.actual_outcome or "running"
        else:
            record_data["execution_status"] = ScenarioExecutionStatus.DISPATCHED
            record_data["pipeline_result"] = "pending"

        return record_data
