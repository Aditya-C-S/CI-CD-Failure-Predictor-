"""Validation helpers for verifying genuine F1 successful workflow runs and logs.

This module ensures that only genuine, completed, and successful GitHub Actions runs
with verified affirmative evidence (clean syntax check and passing tests) are accepted
into the F1 success dataset.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Patterns indicating failure or error in Python CI
FAILURE_LITERAL_PATTERNS = [
    "SyntaxError:",
    "IndentationError:",
    "TabError:",
]

# Regex for non-zero process exit codes: e.g. "Process completed with exit code 1", "exit code 2", "exit code 127"
EXIT_CODE_REGEX = re.compile(r"Process completed with exit code\s+([1-9]\d*)")

# Regex for pytest failure summary: e.g. "= 1 failed, 27 passed =", "= 1 error =", etc.
PYTEST_FAILURE_SUMMARY_REGEX = re.compile(
    r"(?:=+.*?([1-9]\d*\s+failed|[1-9]\d*\s+error[s]?).*?=+|\b([1-9]\d*\s+failed)\b,\s+\d+\s+passed)"
)

# Regex for explicit test failure indicator in pytest output
PYTEST_TEST_FAILED_REGEX = re.compile(r"(?:^FAILED\s+\S+|\bFAILED\s+\[)")

# Regex for pytest failure section headers
PYTEST_FAIL_HEADER_REGEX = re.compile(r"^=+\s+(FAILURES|ERRORS)\s+=+$")

# Patterns indicating affirmative success in Python CI
SUCCESS_AFFIRMATIVE_PATTERNS = [
    "passed",
    "PASSED",
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
    """Validate GitHub Actions workflow run record.

    Args:
        run_data: Dict containing workflow run details from gh CLI or GitHub API.
        expected_repo: Expected repository string (e.g. 'DhruvHegde/dependency-error-repo').
        expected_workflow: Expected workflow name or file (e.g. 'F1 Success CI').

    Returns:
        (is_valid, reason)
    """
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


def validate_success_log(log_text: Optional[str]) -> Tuple[bool, str, Optional[str]]:
    """Inspect raw workflow log content for genuine successful execution.

    Args:
        log_text: Raw workflow log text.

    Returns:
        (is_valid, message, matched_evidence)
    """
    if log_text is None or not log_text.strip():
        return False, "Log text is empty or missing.", None

    # Check for forbidden failure patterns
    for line in log_text.splitlines():
        trimmed = line.strip()

        # 1. Non-zero exit codes (e.g. 1, 2, 127, 137)
        exit_code_match = EXIT_CODE_REGEX.search(trimmed)
        if exit_code_match:
            return (
                False,
                f"Log indicates non-zero process exit code: {exit_code_match.group(0)}",
                None,
            )

        # 2. Pytest failure summaries (e.g. "= 1 failed, 27 passed =")
        summary_match = PYTEST_FAILURE_SUMMARY_REGEX.search(trimmed)
        if summary_match:
            return (
                False,
                f"Log indicates failed pytest test run: {summary_match.group(0)}",
                None,
            )

        # 3. Explicit failed test indicator
        if PYTEST_TEST_FAILED_REGEX.search(trimmed):
            return (
                False,
                f"Log indicates pytest test failure: {trimmed}",
                None,
            )

        # 4. Pytest failure block header
        if PYTEST_FAIL_HEADER_REGEX.match(trimmed):
            return (
                False,
                f"Log contains pytest failure section header: {trimmed}",
                None,
            )

        # 5. CPython syntax/indentation/tab errors
        for lit_pat in FAILURE_LITERAL_PATTERNS:
            if lit_pat in trimmed:
                return (
                    False,
                    f"Log contains interpreter error '{lit_pat}': {trimmed}",
                    None,
                )

    # Check for affirmative evidence of successful test execution
    matched_evidence = None
    for line in log_text.splitlines():
        for pat in SUCCESS_AFFIRMATIVE_PATTERNS:
            if pat in line:
                matched_evidence = line.strip()
                break
        if matched_evidence:
            break

    if not matched_evidence:
        return (
            False,
            "Log lacks affirmative evidence of passing tests (no 'passed' indicator found).",
            None,
        )

    return True, "Affirmative success evidence validated.", matched_evidence


def validate_success_log_file(log_file_path: str | Path) -> Dict[str, Any]:
    """Validate a saved log file on disk."""
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

    is_valid, notes, evidence = validate_success_log(content)
    return {
        "status": "valid" if is_valid else "invalid",
        "is_valid": is_valid,
        "notes": notes,
        "evidence": evidence,
    }


REQUIRED_METADATA_FIELDS = {
    "run_id": str,
    "outcome": str,
    "category_id": type(None),
    "failure_type": type(None),
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


def validate_metadata(metadata: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that metadata conforms to the required schema."""
    if not isinstance(metadata, dict):
        return False, "Metadata must be a dictionary."

    for field, expected_type in REQUIRED_METADATA_FIELDS.items():
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

    if metadata.get("success_family") != "F1":
        return False, f"Field 'success_family' must be 'F1', got '{metadata.get('success_family')}'."

    if metadata.get("workflow_status") != "completed":
        return False, f"Field 'workflow_status' must be 'completed', got '{metadata.get('workflow_status')}'."

    if metadata.get("workflow_conclusion") != "success":
        return False, f"Field 'workflow_conclusion' must be 'success', got '{metadata.get('workflow_conclusion')}'."

    if metadata.get("validation_status") != "valid":
        return False, f"Field 'validation_status' must be 'valid', got '{metadata.get('validation_status')}'."

    # Validate workflow_id is present and not null
    wf_id = metadata.get("workflow_id")
    if wf_id is None or (not isinstance(wf_id, (int, str))):
        return False, f"Field 'workflow_id' must be an integer or string, got {wf_id!r}."

    # Validate commit_sha is present and not empty
    commit_sha = metadata.get("commit_sha")
    if not commit_sha or not isinstance(commit_sha, str):
        return False, f"Field 'commit_sha' must be a non-empty string, got {commit_sha!r}."

    return True, "Metadata schema is valid."
