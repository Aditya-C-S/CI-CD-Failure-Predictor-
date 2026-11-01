"""rca/analyzers/fallback.py

Fallback analyzer for unknown, unclassified, and runtime errors outside F1-F4.
"""

from __future__ import annotations

from typing import Any

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
)


class FallbackAnalyzer(BaseCategoryAnalyzer):
    """Handles runtime exceptions outside pytest and unclassified/unknown failures."""

    @property
    def category_name(self) -> str:
        return "fallback"

    def can_analyze(self, record: Any) -> bool:
        # Acts as catch-all at the end of the analyzer chain
        return True

    def analyze(self, record: Any) -> RCAReport:
        failure_class = get_field(record, "failure_class") or "unknown"
        failure_subcat = get_field(record, "failure_subcategory")
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name")
        exit_code = get_field(record, "exit_code")
        error_type = get_field(record, "error_type")
        error_msg = get_field(record, "error_message") or ""
        tb_lines = get_field(record, "traceback_lines") or []
        ev_lines = get_field(record, "evidence_lines") or []
        log_line_count = get_field(record, "log_line_count") or 0

        observed_evidence: dict[str, Any] = {
            "failure_class": failure_class,
            "failure_subcategory": failure_subcat,
            "exit_code": exit_code,
            "error_type": error_type,
            "error_message": error_msg,
        }

        evidence_sources: dict[str, str] = {
            "failure_class": "parser.failure_class",
            "exit_code": "parser.exit_code",
        }
        if error_type:
            evidence_sources["error_type"] = "parser.error_type"
        if error_msg:
            evidence_sources["error_message"] = "parser.error_message"

        primary_lines = [clean_line(l) for l in (tb_lines or ev_lines)]

        investigation: list[str] = []
        limitations: list[str] = []

        if failure_class == "runtime_error":
            causal_category = CAUSAL_CODE_DEFECT
            summary = f"Runtime exception: {error_type or 'Unhandled error'}"
            likely_cause = (
                f"An unhandled {error_type or 'exception'}{(': ' + error_msg) if error_msg else ''} occurred "
                f"during step '{failed_step or 'unknown'}' outside of pytest test execution."
            )
            investigation.append(f"Inspect step '{failed_step or 'unknown'}' and trace where {error_type or 'the exception'} was raised.")
            investigation.append("Check application logs and environment variables required for this script.")
            confidence = 0.7 if error_type and tb_lines else 0.5
            rationale = "Medium evidence strength: general Python exception and traceback observed outside standard test runners."
            limitations.append("The failure occurred in a standalone script or non-test step; full test report context is unavailable.")

        elif failure_class == "docker_build_failure":
            causal_category = CAUSAL_ENVIRONMENT
            summary = f"Docker build failure: {error_type or failure_subcat or 'Build error'}"
            likely_cause = (
                f"Docker container image build failed in step '{failed_step or 'Build Container Image'}' "
                f"({failure_subcat or 'docker_build_failure'}). {error_msg if error_msg else ''}"
            ).strip()
            investigation.append(f"Inspect Dockerfile instructions around step '{failed_step or 'Build Container Image'}'.")
            investigation.append("Verify COPY/ADD file paths exist within the Docker build context.")
            investigation.append("Check base image tags and container engine configuration.")
            confidence = get_field(record, "parser_confidence") or 0.85
            rationale = "High evidence strength: explicit Docker build engine diagnostic signature matched."
            limitations.append("Underlying host file system state at the time of build can only be partially verified from console logs.")

        elif failure_class == "ci_config_permission_failure":
            causal_category = CAUSAL_ENVIRONMENT
            summary = f"CI/CD configuration/permission failure: {error_type or failure_subcat or 'Permission error'}"
            likely_cause = (
                f"CI/CD workflow execution failed due to insufficient permissions or invalid workflow configuration "
                f"in step '{failed_step or 'Workflow Setup'}'. {error_msg if error_msg else ''}"
            ).strip()
            investigation.append("Review workflow permissions block (e.g. `permissions: contents: write`) in the GitHub Actions workflow file.")
            investigation.append("Verify GITHUB_TOKEN scope and organization/repository secret permissions.")
            investigation.append("Validate workflow YAML syntax against the GitHub Actions workflow schema.")
            confidence = get_field(record, "parser_confidence") or 0.95
            rationale = "High evidence strength: explicit workflow permission, token authorization, or workflow syntax diagnostic."
            limitations.append("Repository-level permission settings and organization token policies cannot be directly inspected from log output.")

        elif failure_class == "network_service_failure":
            causal_category = CAUSAL_ENVIRONMENT
            if failure_subcat == "ssl_certificate_error":
                summary = f"Network SSL/TLS certificate verification failure: {error_type or failure_subcat}"
                likely_cause = (
                    f"Pipeline step '{failed_step or 'unknown'}' failed due to an SSL/TLS certificate verification failure "
                    f"({failure_subcat}). {error_msg if error_msg else ''}"
                ).strip()
                investigation.append("Verify SSL/TLS certificate validity, expiration, and chain configuration on remote endpoint.")
                investigation.append("Check system CA trust certificates and clock skew on the CI runner.")
                investigation.append("Consider updating expired certificates or pinning valid root CA certificates.")
                confidence = get_field(record, "parser_confidence") or 0.90
                rationale = "High evidence strength: explicit SSL certificate verification or expiration failure signature."
                limitations.append("Remote certificate authority validity cannot be repaired from within the runner without updating the remote server.")
            else:
                summary = f"Network or external service failure: {error_type or failure_subcat or 'Connectivity error'}"
                likely_cause = (
                    f"Pipeline step '{failed_step or 'unknown'}' failed due to an external network or service connection failure "
                    f"({failure_subcat or 'network_service_failure'}). {error_msg if error_msg else ''}"
                ).strip()
                investigation.append("Check network reachability, DNS resolution, and egress firewall rules from the CI runner.")
                investigation.append("Verify external service status and endpoint availability.")
                investigation.append("Consider implementing retry logic with exponential backoff for transient network requests.")
                confidence = get_field(record, "parser_confidence") or 0.85
                rationale = "High evidence strength: explicit network socket, DNS resolution, or HTTP gateway failure signature."
                limitations.append("Transient external outages or upstream service degradations cannot be fully confirmed without upstream service telemetry.")

        elif log_line_count == 0 or not get_field(record, "log_text", "").strip():
            causal_category = CAUSAL_UNKNOWN
            summary = "Empty log: no execution data recorded"
            likely_cause = "The log content is empty or unrecorded. No pipeline execution data is available for diagnosis."
            investigation.append("Verify pipeline job triggers and runner connectivity to ensure logs are uploaded properly.")
            confidence = 0.0
            rationale = "Insufficient evidence: empty log content."
            limitations.append("No log records or timestamps were found.")

        elif get_field(record, "status") == "success" or (exit_code == 0 and failure_class == "unknown" and not ev_lines):
            causal_category = CAUSAL_UNKNOWN
            step_disp = f"step '{failed_step}'" if failed_step else "all pipeline steps"
            summary = f"Pipeline execution succeeded in {step_disp}; no failure detected"
            likely_cause = "The pipeline execution completed successfully with exit code 0. No failure signature was detected."
            investigation.append("No remediation needed: pipeline execution completed successfully.")
            confidence = 1.0
            rationale = "High confidence: clean execution with exit code 0 and no error annotations."
            limitations.append("The log represents a successful pipeline execution; failure RCA does not apply.")

        else:
            causal_category = CAUSAL_UNKNOWN
            step_disp = f"step '{failed_step}'" if failed_step else "an unidentified pipeline step"
            code_disp = f" (exit code {exit_code})" if exit_code is not None else ""

            if exit_code == 137:
                summary = f"Process terminated by SIGKILL (exit code 137) in {step_disp}"
                likely_cause = (
                    f"The process in {step_disp} was forcefully terminated with exit code 137 (SIGKILL). "
                    f"This signal typically indicates system Out-Of-Memory (OOM) killer intervention, container RAM limit exhaustion, "
                    f"or external step cancellation, but log text alone does not contain conclusive proof of the specific trigger."
                )
                investigation.append(f"Check system/container memory usage and dmesg/OOM logs during step '{failed_step or 'unknown'}'.")
                investigation.append("Inspect whether the job exceeded runner memory limits or was terminated externally.")
                confidence = 0.4
                rationale = "Low evidence strength: exit code 137 (SIGKILL) observed without specific OOM or timeout annotations."
                limitations.append(
                    "Exit code 137 (SIGKILL) does not by itself prove an out-of-memory failure or timeout. Kernel OOM killing, cgroup memory exhaustion, and external step termination produce identical exit codes."
                )
            elif exit_code == 143:
                summary = f"Process terminated by SIGTERM (exit code 143) in {step_disp}"
                likely_cause = (
                    f"The process in {step_disp} was terminated with exit code 143 (SIGTERM). "
                    f"This signal indicates a termination request from the operating system or CI runner, "
                    f"such as job cancellation or runner shutdown."
                )
                investigation.append(f"Check runner logs and job cancellation events for step '{failed_step or 'unknown'}'.")
                confidence = 0.4
                rationale = "Low evidence strength: exit code 143 (SIGTERM) observed without category-specific diagnostic signatures."
                limitations.append(
                    "Exit code 143 (SIGTERM) does not by itself prove a step timeout. Runner shutdown, container stop commands, and job cancellations produce identical SIGTERM signals."
                )
            else:
                summary = f"Unknown pipeline failure in {step_disp}{code_disp}"
                likely_cause = (
                    f"Unable to determine root cause. The pipeline failed in {step_disp}{code_disp}, "
                    f"but log content did not match recognized syntax, dependency, test, or timeout diagnostic patterns."
                )
                investigation.append(f"Inspect raw console output for {step_disp} to locate unparsed error messages.")
                investigation.append("Re-run the pipeline with runner debug logging enabled (ACTIONS_RUNNER_DEBUG=true).")
                if exit_code is not None:
                    investigation.append(f"Check documentation or exit code reference for exit code {exit_code} on commands run in {step_disp}.")

                if exit_code is not None:
                    confidence = 0.4 if failed_step else 0.3
                    rationale = f"Low evidence strength: exit code {exit_code} observed without category-specific diagnostic signatures."
                    limitations.append(
                        f"Exit code {exit_code} was observed, but runner logs do not include compiler, package manager, or test runner error messages to identify the underlying trigger."
                    )
                elif failed_step:
                    confidence = 0.3
                    rationale = "Low evidence strength: failure step identified, but no recognized error signatures found."
                    limitations.append(
                        "Insufficient log evidence. Generic failure step observed without accompanying compiler, package manager, or test framework diagnostic records."
                    )
                else:
                    confidence = 0.2
                    rationale = "Insufficient evidence: no recognizable error signatures or failure exit codes."
                    limitations.append(
                        "Insufficient log evidence. Generic failure annotations were observed without accompanying compiler, package manager, or test framework diagnostic records."
                    )

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class=failure_class,
            failure_subcategory=failure_subcat,
            failed_stage=get_field(record, "stage") or "unknown",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=causal_category,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=None,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
