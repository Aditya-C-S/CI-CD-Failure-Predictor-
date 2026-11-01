"""src/remediation/suggestions.py

Remediation engine that maps RCA reports and extracted failure evidence
into actionable developer suggestions, terminal commands, and prevention advice.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
    CAUSAL_TIMEOUT,
    CAUSAL_UNKNOWN,
)


class RemediationAdvisor:
    """Generates remediation advice based on RCA reports and error evidence."""

    @classmethod
    def generate_remediation(cls, rca_report: RCAReport, log_text: Optional[str] = None) -> Dict[str, Any]:
        """
        Produce actionable remediation steps for an RCA report.

        Returns
        -------
        dict
            Dict containing category, summary, commands, code_fixes, and best_practices.
        """
        causal = getattr(rca_report, "causal_category", "unknown")
        summary = getattr(rca_report, "summary", "") or "CI/CD failure detected."
        evidence = getattr(rca_report, "observed_evidence", {}) or {}
        confidence = getattr(rca_report, "rca_confidence", 0.0)

        remediation: Dict[str, Any] = {
            "causal_category": causal,
            "root_cause_summary": summary,
            "confidence": confidence,
            "recommended_actions": [],
            "terminal_commands": [],
            "code_diff_suggestion": None,
            "prevention_tips": [],
        }

        # Include suggested investigations from the RCA engine if present
        suggested = getattr(rca_report, "suggested_investigation", [])
        if suggested:
            remediation["recommended_actions"].extend(suggested)

        if causal in (CAUSAL_DEPENDENCY, "dependency", "dependency_resolution"):
            cls._remediate_dependency(evidence, summary, remediation)
        elif causal in (CAUSAL_CODE_DEFECT, "code_defect", "syntax"):
            cls._remediate_code_defect(evidence, summary, remediation)
        elif causal in (CAUSAL_TEST, CAUSAL_TEST_EXECUTION, "test_failure"):
            cls._remediate_test_failure(evidence, summary, remediation)
        elif causal in (CAUSAL_TIMEOUT, "execution_timeout", "timeout"):
            cls._remediate_timeout(evidence, summary, remediation)
        else:
            cls._remediate_fallback(evidence, summary, remediation)

        # Remove duplicate recommended actions
        remediation["recommended_actions"] = list(dict.fromkeys(remediation["recommended_actions"]))
        remediation["terminal_commands"] = list(dict.fromkeys(remediation["terminal_commands"]))
        remediation["prevention_tips"] = list(dict.fromkeys(remediation["prevention_tips"]))

        return remediation

    @staticmethod
    def _remediate_dependency(evidence: Dict[str, Any], summary: str, out: Dict[str, Any]) -> None:
        missing_pkg = evidence.get("package") or evidence.get("missing_package")
        if missing_pkg:
            out["recommended_actions"].append(f"Add '{missing_pkg}' to requirements.txt or install it in the CI pipeline step.")
            out["terminal_commands"].append(f"pip install {missing_pkg}")
            out["terminal_commands"].append(f"pip freeze > requirements.txt")
        else:
            out["recommended_actions"].append("Verify requirements.txt and package pin constraints for compatibility.")
            out["terminal_commands"].append("pip check")
            out["terminal_commands"].append("pip install -r requirements.txt --dry-run")

        out["prevention_tips"].extend([
            "Use pip-tools or Poetry to pin exact transitive dependency hashes.",
            "Enable GitHub Actions dependency caching (actions/cache) to prevent mirror network flakiness."
        ])

    @staticmethod
    def _remediate_code_defect(evidence: Dict[str, Any], summary: str, out: Dict[str, Any]) -> None:
        file_path = evidence.get("source_file") or evidence.get("file_path")
        line_num = evidence.get("source_line") or evidence.get("line_number")

        loc = f" at {file_path}:{line_num}" if file_path and line_num else ""
        out["recommended_actions"].append(f"Fix the syntax / indentation error{loc}.")
        out["terminal_commands"].append("python -m py_compile $(git ls-files '*.py')")
        out["terminal_commands"].append("ruff check . --fix")
        out["prevention_tips"].extend([
            "Install a pre-commit hook (e.g. pre-commit install) to catch syntax errors prior to push.",
            "Run linters (flake8 / ruff) locally in VSCode or PyCharm."
        ])

    @staticmethod
    def _remediate_test_failure(evidence: Dict[str, Any], summary: str, out: Dict[str, Any]) -> None:
        failed_tests = evidence.get("failed_tests") or []
        if failed_tests:
            out["recommended_actions"].append(f"Reproduce and fix failing test(s): {', '.join(failed_tests[:3])}")
            out["terminal_commands"].append(f"pytest -v {' '.join(failed_tests[:2])}")
        else:
            out["recommended_actions"].append("Review failing test assertions and mock fixture states.")
            out["terminal_commands"].append("pytest -v --tb=short")

        out["prevention_tips"].extend([
            "Ensure tests do not rely on nondeterministic state or external network calls.",
            "Run pytest -n auto to validate parallel execution locally."
        ])

    @staticmethod
    def _remediate_timeout(evidence: Dict[str, Any], summary: str, out: Dict[str, Any]) -> None:
        out["recommended_actions"].append("Increase the step or workflow timeout limit in the GitHub Actions YAML.")
        out["recommended_actions"].append("Investigate blocking infinite loops, hanging child processes, or slow network downloads.")
        out["prevention_tips"].extend([
            "Add 'timeout-minutes: 15' to each CI job to fail fast.",
            "Use aggressive test timeouts (pytest-timeout) to identify hanging test cases."
        ])

    @staticmethod
    def _remediate_fallback(evidence: Dict[str, Any], summary: str, out: Dict[str, Any]) -> None:
        out["recommended_actions"].append("Inspect the raw CI/CD runner exit code and console diagnostic output.")
        out["terminal_commands"].append("git diff HEAD~1")
        out["prevention_tips"].extend([
            "Ensure CI runners have sufficient disk space and memory.",
            "Enable verbose runner logging with ACTIONS_STEP_DEBUG=true."
        ])
