"""Validation helpers for verifying genuine F5 successful Docker build workflow runs and logs.

Ensures that only genuine, completed, and successful GitHub Actions runs
with verified affirmative BuildKit and scenario-specific evidence are accepted.
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docker.build_scenario import SCENARIO_CATALOG

# Patterns indicating failure or error in Docker build
FAILURE_PATTERNS = [
    re.compile(r"ERROR:\s*failed to solve:", re.IGNORECASE),
    re.compile(r"##\[error\]Process completed with exit code\s+([1-9]\d*)", re.IGNORECASE),
    re.compile(r"##\[error\]buildx failed with:", re.IGNORECASE),
    re.compile(r"##\[error\]docker:.*error", re.IGNORECASE),
    re.compile(r"failed to solve with frontend dockerfile", re.IGNORECASE),
    re.compile(r"dockerfile parse error", re.IGNORECASE),
    re.compile(r"SyntaxError:", re.IGNORECASE),
    re.compile(r"IndentationError:", re.IGNORECASE),
]

EXIT_CODE_REGEX = re.compile(r"Process completed with exit code\s+([1-9]\d*)")

# Patterns confirming affirmative BuildKit / Docker success
AFFIRMATIVE_BUILDKIT_PATTERNS = [
    "naming to docker.io",
    "exporting to image",
    "[SUCCESS] Docker build completed successfully",
    "Successfully built",
    "Successfully tagged",
]


def extract_repository_from_url(url: str) -> Optional[str]:
    """Extract owner/repo string from a GitHub Actions run URL."""
    if not url:
        return None
    match = re.search(r"github\.com/([^/]+/[^/]+)/actions/runs/", url)
    if match:
        return match.group(1)
    return None


def validate_workflow_run(
    run_data: Dict[str, Any],
    expected_repo: Optional[str] = None,
    expected_workflow: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate GitHub Actions workflow run record."""
    if not isinstance(run_data, dict):
        return False, "Workflow run record must be a dictionary."

    run_id = run_data.get("databaseId") or run_data.get("id")
    if not run_id:
        return False, "Missing workflow run ID."

    status = run_data.get("status")
    if status != "completed":
        return False, f"Workflow status is '{status}', expected 'completed'."

    conclusion = run_data.get("conclusion")
    if conclusion != "success":
        return False, f"Workflow conclusion is '{conclusion}', expected 'success'."

    if expected_repo:
        repo_obj = run_data.get("repository")
        repo_info = (
            repo_obj.get("nameWithOwner")
            if isinstance(repo_obj, dict)
            else (repo_obj if isinstance(repo_obj, str) else None)
        )
        url = run_data.get("url") or ""
        url_repo = extract_repository_from_url(url)

        candidate_repo = repo_info or url_repo
        if not candidate_repo:
            return False, "Repository identity cannot be established from workflow run record."

        if expected_repo.lower() != candidate_repo.lower() and expected_repo.lower() not in candidate_repo.lower():
            return False, f"Workflow repository '{candidate_repo}' does not match expected '{expected_repo}'."

    if expected_workflow:
        wf_name = (
            run_data.get("workflowName")
            or run_data.get("name")
            or run_data.get("path")
            or run_data.get("workflow_file")
        )
        if not wf_name:
            return False, "Workflow name cannot be established from workflow run record."
        if expected_workflow.lower() not in wf_name.lower():
            return False, f"Workflow '{wf_name}' does not match expected '{expected_workflow}'."

    return True, "Workflow run verified successfully."


def validate_docker_success_log(
    log_text: Optional[str],
    scenario_id: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Inspect raw workflow log content for genuine successful Docker execution."""
    if log_text is None or not log_text.strip():
        return False, "Log text is empty or missing.", None

    # 1. Check for failure patterns and non-zero exit codes
    for line in log_text.splitlines():
        trimmed = line.strip()
        exit_code_match = EXIT_CODE_REGEX.search(trimmed)
        if exit_code_match:
            return False, f"Log indicates non-zero exit code: {exit_code_match.group(0)}", None

        for fail_pat in FAILURE_PATTERNS:
            if fail_pat.search(trimmed):
                return False, f"Log contains failure pattern '{fail_pat.pattern}': {trimmed}", None

    # 2. Check for affirmative BuildKit success evidence
    matched_affirmative = None
    for line in log_text.splitlines():
        for pat in AFFIRMATIVE_BUILDKIT_PATTERNS:
            if pat in line:
                matched_affirmative = line.strip()
                break
        if matched_affirmative:
            break

    if not matched_affirmative:
        return (
            False,
            "Log lacks affirmative evidence of successful image export or completion.",
            None,
        )

    # 3. Check scenario-specific feature evidence
    if scenario_id:
        if scenario_id not in SCENARIO_CATALOG:
            return False, f"Unknown scenario_id '{scenario_id}' provided for validation.", None

        catalog_entry = SCENARIO_CATALOG[scenario_id]

        # Verify positive feature evidence
        for required_evidence in catalog_entry.get("feature_evidence", []):
            if required_evidence not in log_text:
                return (
                    False,
                    f"Scenario '{scenario_id}' lacks required feature evidence '{required_evidence}' in log.",
                    None,
                )

        # Verify negative exclusion evidence
        for forbidden_evidence in catalog_entry.get("negative_evidence", []):
            if forbidden_evidence in log_text:
                return (
                    False,
                    f"Scenario '{scenario_id}' contains unexpected negative evidence '{forbidden_evidence}' in log.",
                    None,
                )

    return True, "Affirmative Docker build success validated.", matched_affirmative


def validate_docker_success_log_file(
    log_file_path: str | Path,
    scenario_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a saved Docker success log file on disk."""
    path = Path(log_file_path)
    if not path.exists():
        return {
            "status": "error",
            "is_valid": False,
            "notes": f"File does not exist: {path}",
            "evidence": None,
        }

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as err:
        return {
            "status": "error",
            "is_valid": False,
            "notes": f"Read error: {err}",
            "evidence": None,
        }

    is_valid, notes, evidence = validate_docker_success_log(content, scenario_id=scenario_id)
    return {
        "status": "valid" if is_valid else "invalid",
        "is_valid": is_valid,
        "notes": notes,
        "evidence": evidence,
    }


REQUIRED_F5_SUCCESS_METADATA_FIELDS = {
    "run_id": str,
    "run_number": int,
    "outcome": str,
    "category_id": type(None),
    "failure_type": type(None),
    "stage": str,
    "success_family": str,
    "scenario_id": str,
    "log_file": str,
    "generation_method": str,
    "actual_execution_validated": bool,
    "workflow_status": str,
    "workflow_conclusion": str,
    "validation_status": str,
    "validation_notes": str,
    "timestamp": str,
}


def validate_f5_success_metadata(metadata: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that F5 success metadata conforms to the required schema."""
    if not isinstance(metadata, dict):
        return False, "Metadata must be a dictionary."

    for field, expected_type in REQUIRED_F5_SUCCESS_METADATA_FIELDS.items():
        if field not in metadata:
            return False, f"Missing required metadata field: '{field}'."
        val = metadata[field]
        if expected_type is type(None):
            if val is not None:
                return False, f"Field '{field}' must be null, got: {val!r}."
        elif not isinstance(val, expected_type):
            return False, f"Field '{field}' must be of type {expected_type.__name__}, got {type(val).__name__}."

    if metadata.get("outcome") != "success":
        return False, f"Field 'outcome' must be 'success', got '{metadata.get('outcome')}'."

    if metadata.get("success_family") != "F5":
        return False, f"Field 'success_family' must be 'F5', got '{metadata.get('success_family')}'."

    if metadata.get("stage") != "docker_build":
        return False, f"Field 'stage' must be 'docker_build', got '{metadata.get('stage')}'."

    if metadata.get("workflow_status") != "completed":
        return False, f"Field 'workflow_status' must be 'completed', got '{metadata.get('workflow_status')}'."

    if metadata.get("workflow_conclusion") != "success":
        return False, f"Field 'workflow_conclusion' must be 'success', got '{metadata.get('workflow_conclusion')}'."

    if metadata.get("validation_status") != "valid":
        return False, f"Field 'validation_status' must be 'valid', got '{metadata.get('validation_status')}'."

    wf_id = metadata.get("workflow_id")
    if wf_id is None or (not isinstance(wf_id, (int, str))):
        return False, f"Field 'workflow_id' must be an integer or string, got {wf_id!r}."

    gh_run_id = metadata.get("github_run_id")
    if gh_run_id is None or (not isinstance(gh_run_id, (int, str))):
        return False, f"Field 'github_run_id' must be an integer or string, got {gh_run_id!r}."

    commit_sha = metadata.get("commit_sha")
    if not commit_sha or not isinstance(commit_sha, str):
        return False, f"Field 'commit_sha' must be a non-empty string, got {commit_sha!r}."

    return True, "Metadata schema is valid."
