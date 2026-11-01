"""parser/test_parser_extensions.py

Comprehensive test suite verifying the extensions to Parser V2:
1. Docker Build Failure Detection (positive, negative, ambiguous, competing pip inside docker)
2. CI/CD Configuration and Permission Failure Detection (positive, negative boilerplate, python PermissionError, competing)
3. Network and Service Failure Detection (positive DNS/refusal/reset/timeout/502-504, negative successful retries, competing job timeout)
4. Fallback and Robust Unknown Classification (empty logs, exit code 137, exit code 143, generic exit codes)
5. Preservation of Existing Categories (syntax, dependency, test failure, timeout, runtime error)
6. RCA Engine Integration & Compatibility across all new categories.
"""

import unittest
from pathlib import Path

from parser.log_parser import parse_log_text, parse_log_file, LogRecord
from rca.engine import analyze_record
from rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
    CAUSAL_TIMEOUT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
)

BASE_DIR = Path(__file__).resolve().parent.parent / "logs"


# =============================================================================
# 1. Docker Build Failure Tests (Step 2)
# =============================================================================

class TestDockerBuildFailureDetection(unittest.TestCase):
    """Test dedicated recognition of Docker build errors and edge cases."""

    def test_docker_buildkit_solve_checksum_missing_file_positive(self):
        """Positive: BuildKit ref checksum missing file (D1)."""
        log_text = (
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:00.600Z ##[group]Run docker build\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:00.750Z [command]/usr/bin/docker build -t app:01 .\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:02.000Z #4 [2/2] COPY config/settings.yaml /app/data/\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:02.200Z #4 ERROR: failed to calculate checksum of ref buildref: \"/config/settings.yaml\": not found\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:02.300Z ERROR: failed to solve: failed to calculate checksum of ref buildref: \"/config/settings.yaml\": not found\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:03:02.350Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "docker_copy_not_found")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.failed_step, "Build Container Image")
        self.assertEqual(rec.stage, "build")
        self.assertGreaterEqual(rec.parser_confidence, 0.85)
        self.assertTrue(len(rec.evidence_lines) >= 1)
        self.assertTrue(any("failed to calculate checksum" in l for l in rec.evidence_lines))

    def test_docker_parse_error_unknown_instruction_positive(self):
        """Positive: Dockerfile unknown instruction parse error (D2)."""
        log_text = (
            "docker-ci\tBuild Container Image\t2026-08-16T11:06:01.000Z ##[group]Run docker build\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:06:01.270Z #1 ERROR: dockerfile parse error on line 3: unknown instruction: INCLUDELIB\n"
            "docker-ci\tBuild Container Image\t2026-08-16T11:06:01.400Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "dockerfile_parse_error")
        self.assertEqual(rec.status, "failure")
        self.assertIn("INCLUDELIB", rec.error_message)

    def test_docker_invalid_image_reference_positive(self):
        """Positive: Invalid repository image reference format (D4)."""
        log_text = (
            "ci\tBuild Image\t2026-08-16T11:12:01.000Z [command]docker build -t MyOrg_AppService/Server:1.0 .\n"
            "ci\tBuild Image\t2026-08-16T11:12:01.270Z #2 ERROR: invalid reference format: repository name must be lowercase\n"
            "ci\tBuild Image\t2026-08-16T11:12:01.370Z ERROR: failed to solve: invalid reference format: repository name must be lowercase\n"
            "ci\tBuild Image\t2026-08-16T11:12:01.400Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "docker_image_resolution_error")
        self.assertEqual(rec.status, "failure")

    def test_docker_daemon_connection_error_positive(self):
        """Positive: Docker daemon connection failure."""
        log_text = (
            "ci\tBuild Step\t2026-08-16T11:00:00Z [command]docker build .\n"
            "ci\tBuild Step\t2026-08-16T11:00:01Z Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n"
            "ci\tBuild Step\t2026-08-16T11:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "docker_daemon_error")
        self.assertEqual(rec.status, "failure")

    def test_docker_mention_in_runner_setup_negative(self):
        """Negative: Mention of Docker in runner image software header without error."""
        log_text = (
            "ci\tSet up job\t2026-08-16T11:00:00Z Runner Image: ubuntu-22.04\n"
            "ci\tSet up job\t2026-08-16T11:00:01Z Included Software: Buildx v0.35.0, Docker 28.0.4\n"
            "ci\tCheckout\t2026-08-16T11:00:02Z git checkout main\n"
            "ci\tComplete job\t2026-08-16T11:00:03Z Process completed with exit code 0.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.status, "success")

    def test_docker_ambiguous_exit_code_without_pattern(self):
        """Ambiguous: docker build command fails with non-zero code but no specific BuildKit diagnostic."""
        log_text = (
            "ci\tBuild Image\t2026-08-16T11:00:00Z [command]docker build -t app:latest .\n"
            "ci\tBuild Image\t2026-08-16T11:00:05Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "docker_build_failure")
        self.assertEqual(rec.status, "failure")
        self.assertGreaterEqual(rec.parser_confidence, 0.8)

    def test_docker_build_with_pip_dependency_error_takes_dependency_priority(self):
        """Competing signature: Pip dependency failure inside Docker build MUST classify as dependency_error."""
        log_text = (
            "docker-ci\tBuild Container\t2026-08-16T11:00:00Z [command]docker build -t myapp .\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:01Z #5 [2/3] RUN pip install non_existent_library_998877==2.1\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:02Z #5 1.234 ERROR: Could not find a version that satisfies the requirement non_existent_library_998877==2.1\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:03Z #5 1.235 ERROR: No matching distribution found for non_existent_library_998877==2.1\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:04Z #5 ERROR: process \"/bin/sh -c pip install non_existent_library_998877==2.1\" did not complete successfully: exit code: 1\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:05Z ERROR: failed to solve: process \"/bin/sh -c pip install non_existent_library_998877==2.1\" did not complete successfully: exit code: 1\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:06Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "dependency_error")
        self.assertEqual(rec.failing_package, "non_existent_library_998877==2.1")
        self.assertNotEqual(rec.failure_class, "docker_build_failure")

    def test_docker_real_f5_log_parsing(self):
        """Verify on real F5 log file if present."""
        f5_path = BASE_DIR / "F5" / "run_0501.log"
        if not f5_path.exists():
            self.skipTest("F5/run_0501.log not found")
        rec = parse_log_file(f5_path)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "docker_copy_not_found")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.failed_step, "Build Container Image")


# =============================================================================
# 2. CI/CD Configuration and Permission Failure Tests (Step 3)
# =============================================================================

class TestCIConfigPermissionFailureDetection(unittest.TestCase):
    """Test dedicated recognition of workflow permission and configuration errors."""

    def test_resource_not_accessible_by_integration_positive(self):
        """Positive: GITHUB_TOKEN lacks permission (Resource not accessible by integration)."""
        log_text = (
            "ci\tCreate Release\t2026-08-17T09:00:00Z ##[group]Run actions/create-release@v1\n"
            "ci\tCreate Release\t2026-08-17T09:00:01Z HttpError: Resource not accessible by integration\n"
            "ci\tCreate Release\t2026-08-17T09:00:02Z ##[error]Resource not accessible by integration\n"
            "ci\tCreate Release\t2026-08-17T09:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertEqual(rec.failure_subcategory, "token_permission_insufficient")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.failed_step, "Create Release")
        self.assertGreaterEqual(rec.parser_confidence, 0.9)
        self.assertTrue(len(rec.evidence_lines) >= 1)

    def test_workflow_template_syntax_invalid_positive(self):
        """Positive: Invalid workflow syntax or schema structure."""
        log_text = (
            "workflow-init\tSet up job\t2026-08-17T09:00:00Z ##[error]Workflow is not valid: .github/workflows/deploy.yml (Line: 15, Col: 5): Unexpected symbol: 'bar'\n"
            "workflow-init\tSet up job\t2026-08-17T09:00:01Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertEqual(rec.failure_subcategory, "workflow_syntax_error")
        self.assertEqual(rec.status, "failure")

    def test_missing_required_input_positive(self):
        """Positive: Action input missing."""
        log_text = (
            "ci\tPublish Step\t2026-08-17T09:00:00Z ##[error]Input required and not supplied: npm_token\n"
            "ci\tPublish Step\t2026-08-17T09:00:01Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertEqual(rec.failure_subcategory, "action_input_missing")
        self.assertEqual(rec.status, "failure")

    def test_boilerplate_github_token_permissions_negative(self):
        """Negative: Normal GITHUB_TOKEN Permissions header in successful run MUST NOT trigger failure."""
        log_text = (
            "ci\tSet up job\t2026-08-17T09:00:00Z ##[group]GITHUB_TOKEN Permissions\n"
            "ci\tSet up job\t2026-08-17T09:00:01Z Contents: read\n"
            "ci\tSet up job\t2026-08-17T09:00:02Z Metadata: read\n"
            "ci\tSet up job\t2026-08-17T09:00:03Z Packages: read\n"
            "ci\tSet up job\t2026-08-17T09:00:04Z ##[endgroup]\n"
            "ci\tRun Step\t2026-08-17T09:00:05Z echo 'all passed'\n"
            "ci\tComplete job\t2026-08-17T09:00:06Z Process completed with exit code 0.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertEqual(rec.status, "success")

    def test_python_permission_error_in_app_code_negative(self):
        """Negative: Python PermissionError in app code belongs to runtime_error, not CI config."""
        log_text = (
            "ci\tRun Script\t2026-08-17T09:00:00Z python migrate.py\n"
            "ci\tRun Script\t2026-08-17T09:00:01Z Traceback (most recent call last):\n"
            "ci\tRun Script\t2026-08-17T09:00:02Z   File \"migrate.py\", line 12, in <module>\n"
            "ci\tRun Script\t2026-08-17T09:00:03Z     with open('/etc/app.conf', 'w') as f:\n"
            "ci\tRun Script\t2026-08-17T09:00:04Z PermissionError: [Errno 13] Permission denied: '/etc/app.conf'\n"
            "ci\tRun Script\t2026-08-17T09:00:05Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertEqual(rec.failure_class, "runtime_error")

    def test_github_api_403_not_classified_as_network_failure(self):
        """Competing: GitHub API 403 authorization error must not become a network failure."""
        log_text = (
            "ci\tPost Comment\t2026-08-17T09:00:00Z Calling GitHub API\n"
            "ci\tPost Comment\t2026-08-17T09:00:01Z GET https://api.github.com/repos/owner/repo/issues/1/comments 403 Forbidden\n"
            "ci\tPost Comment\t2026-08-17T09:00:02Z ##[error]Resource not accessible by integration\n"
            "ci\tPost Comment\t2026-08-17T09:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "ci_config_permission_failure")
        self.assertNotEqual(rec.failure_class, "network_service_failure")


# =============================================================================
# 3. Network and Service Failure Tests (Step 4)
# =============================================================================

class TestNetworkServiceFailureDetection(unittest.TestCase):
    """Test dedicated recognition of external network and service failures."""

    def test_dns_resolution_failure_positive(self):
        """Positive: Temporary failure in name resolution."""
        log_text = (
            "ci\tFetch Artifact\t2026-08-18T10:00:00Z curl -sSf https://artifacts.internal.net/pkg.tar.gz\n"
            "ci\tFetch Artifact\t2026-08-18T10:00:02Z curl: (6) Could not resolve host: artifacts.internal.net; Temporary failure in name resolution\n"
            "ci\tFetch Artifact\t2026-08-18T10:00:03Z ##[error]Process completed with exit code 6.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "dns_resolution_failure")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.failed_step, "Fetch Artifact")
        self.assertIn("artifacts.internal.net", rec.network_endpoint or rec.error_message)
        self.assertGreaterEqual(rec.parser_confidence, 0.85)

    def test_connection_refused_positive(self):
        """Positive: Connection refused to external database service."""
        log_text = (
            "ci\tWait For DB\t2026-08-18T10:00:00Z nc -z db.service.local 5432\n"
            "ci\tWait For DB\t2026-08-18T10:00:01Z Failed to connect to db.service.local:5432: Connection refused\n"
            "ci\tWait For DB\t2026-08-18T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "connection_refused")
        self.assertEqual(rec.status, "failure")

    def test_http_502_bad_gateway_positive(self):
        """Positive: HTTP 502 Bad Gateway response during deployment step."""
        log_text = (
            "ci\tDeploy API\t2026-08-18T10:00:00Z curl -X POST https://api.prod.example.com/deploy\n"
            "ci\tDeploy API\t2026-08-18T10:00:05Z HTTP/1.1 502 Bad Gateway\n"
            "ci\tDeploy API\t2026-08-18T10:00:06Z ##[error]Deployment webhook returned 502 Bad Gateway\n"
            "ci\tDeploy API\t2026-08-18T10:00:07Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "http_gateway_error")
        self.assertEqual(rec.status, "failure")

    def test_connection_timeout_outside_job_timeout_positive(self):
        """Positive: Network read/connection timeout without job wall-clock timeout."""
        log_text = (
            "ci\tFetch Data\t2026-08-18T10:00:00Z python fetch_data.py\n"
            "ci\tFetch Data\t2026-08-18T10:00:30Z urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='data.example.org', port=443): Read timed out.\n"
            "ci\tFetch Data\t2026-08-18T10:00:31Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "connection_timeout")
        self.assertNotEqual(rec.failure_class, "timeout")

    def test_successful_retry_negative(self):
        """Negative: Transient retry followed by successful completion must NOT be classified as network failure."""
        log_text = (
            "ci\tInstall Packages\t2026-08-18T10:00:00Z pip install requests\n"
            "ci\tInstall Packages\t2026-08-18T10:00:01Z WARNING: Retrying (Retry(total=2...)) after connection broken by 'ConnectionRefusedError': Connection refused\n"
            "ci\tInstall Packages\t2026-08-18T10:00:03Z Successfully installed requests-2.31.0\n"
            "ci\tInstall Packages\t2026-08-18T10:00:04Z Process completed with exit code 0.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.status, "success")

    def test_explicit_job_timeout_takes_priority_over_network(self):
        """Competing: Explicit GHA job timeout must remain timeout class, not network."""
        log_text = (
            "ci\tRun Tests\t2026-08-18T10:00:00Z ##[group]Run test suite\n"
            "ci\tRun Tests\t2026-08-18T10:05:00Z ##[error]The action 'Run Tests' has timed out after 5.0 minutes.\n"
            "ci\tRun Tests\t2026-08-18T10:05:01Z Connection timed out.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "timeout")
        self.assertNotEqual(rec.failure_class, "network_service_failure")

    def test_pytest_network_exception_stays_test_failure(self):
        """Competing: Pytest failure with network exception must remain test_failure."""
        log_text = (
            "ci\tRun Tests\t2026-08-18T10:00:00Z ##[group]Run pytest\n"
            "ci\tRun Tests\t2026-08-18T10:00:05Z FAILED tests/test_remote.py::test_api_call - requests.exceptions.ConnectTimeout: Connection timed out\n"
            "ci\tRun Tests\t2026-08-18T10:00:06Z = 1 failed in 0.50s =\n"
            "ci\tRun Tests\t2026-08-18T10:00:07Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "test_failure")
        self.assertNotEqual(rec.failure_class, "network_service_failure")


# =============================================================================
# 4. Unknown and Fallback Classification Tests (Step 5)
# =============================================================================

class TestUnknownAndFallbackClassification(unittest.TestCase):
    """Test robust fallback and uncertainty preservation for unknown logs."""

    def test_empty_log_is_unknown(self):
        rec = parse_log_text("")
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.failure_subcategory, "empty_log")
        self.assertEqual(rec.status, "unknown")
        self.assertEqual(rec.parser_confidence, 0.0)

    def test_exit_code_137_without_gha_annotation_is_unknown(self):
        """Exit code 137 alone does not prove OOM or timeout; remains unknown."""
        log_text = (
            "ci\tHeavy Step\t2026-08-19T14:00:00Z Running computation...\n"
            "ci\tHeavy Step\t2026-08-19T14:01:00Z ##[error]Process completed with exit code 137.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.failure_subcategory, "process_signal_137")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.parser_confidence, 0.4)

    def test_exit_code_143_without_gha_annotation_is_unknown(self):
        """Exit code 143 alone does not prove timeout; remains unknown."""
        log_text = (
            "ci\tWorker Step\t2026-08-19T14:00:00Z Starting worker...\n"
            "ci\tWorker Step\t2026-08-19T14:01:00Z ##[error]Process completed with exit code 143.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.failure_subcategory, "process_signal_143")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.parser_confidence, 0.4)

    def test_unexplained_exit_code_1_is_unknown(self):
        log_text = (
            "ci\tCustom Script\t2026-08-19T14:00:00Z echo 'running unknown binary'\n"
            "ci\tCustom Script\t2026-08-19T14:00:01Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.failure_subcategory, "unknown_failure")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.parser_confidence, 0.5)


# =============================================================================
# 5. RCA Engine Integration Tests (Step 8)
# =============================================================================

class TestRCAEngineIntegrationWithNewCategories(unittest.TestCase):
    """Test that all three new categories produce structured RCAReport via FallbackAnalyzer."""

    def test_rca_report_for_docker_build_failure(self):
        rec = LogRecord(
            run_id="docker_test_01",
            failure_class="docker_build_failure",
            failure_subcategory="docker_copy_not_found",
            error_message="COPY failed: '/app/config.yaml' not found in build context",
            failed_step="Build Container Image",
            status="failure",
            parser_confidence=0.9,
            evidence_lines=["#4 ERROR: failed to calculate checksum: not found"],
        )
        report = analyze_record(rec)
        self.assertIsInstance(report, RCAReport)
        self.assertEqual(report.failure_class, "docker_build_failure")
        self.assertEqual(report.causal_category, CAUSAL_ENVIRONMENT)
        self.assertIn("Docker", report.summary)
        self.assertTrue(len(report.suggested_investigation) >= 1)
        self.assertGreaterEqual(report.rca_confidence, 0.8)

    def test_rca_report_for_ci_config_permission_failure(self):
        rec = LogRecord(
            run_id="ci_perm_test_01",
            failure_class="ci_config_permission_failure",
            failure_subcategory="token_permission_insufficient",
            error_message="CI/CD permission denied: Resource not accessible by integration",
            failed_step="Create Release",
            status="failure",
            parser_confidence=0.95,
            evidence_lines=["HttpError: Resource not accessible by integration"],
        )
        report = analyze_record(rec)
        self.assertIsInstance(report, RCAReport)
        self.assertEqual(report.failure_class, "ci_config_permission_failure")
        self.assertEqual(report.causal_category, CAUSAL_ENVIRONMENT)
        self.assertIn("permission", report.summary.lower())
        self.assertTrue(len(report.suggested_investigation) >= 1)

    def test_rca_report_for_network_service_failure(self):
        rec = LogRecord(
            run_id="net_test_01",
            failure_class="network_service_failure",
            failure_subcategory="dns_resolution_failure",
            error_message="DNS resolution failure connecting to api.internal",
            network_endpoint="api.internal",
            failed_step="Fetch Artifact",
            status="failure",
            parser_confidence=0.9,
            evidence_lines=["Temporary failure in name resolution"],
        )
        report = analyze_record(rec)
        self.assertIsInstance(report, RCAReport)
        self.assertEqual(report.failure_class, "network_service_failure")
        self.assertEqual(report.causal_category, CAUSAL_ENVIRONMENT)
        self.assertIn("Network", report.summary)
        self.assertTrue(len(report.suggested_investigation) >= 1)

    def test_rca_report_for_successful_log_not_treated_as_failure(self):
        """Verify that successful logs (status='success') are NOT diagnosed as pipeline failures."""
        log_text = (
            "ci\tBuild\t2026-08-19T10:00:00Z Build succeeded\n"
            "ci\tTest\t2026-08-19T10:00:05Z All tests passed\n"
            "ci\tComplete job\t2026-08-19T10:00:06Z Process completed with exit code 0.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.status, "success")
        self.assertEqual(rec.failure_class, "unknown")

        from rca.engine import get_default_engine
        report = get_default_engine().analyze_record(rec)
        self.assertIsInstance(report, RCAReport)
        self.assertIn("succeeded", report.summary.lower())
        self.assertEqual(report.rca_confidence, 1.0)
        self.assertIn("completed successfully", report.likely_cause.lower())


# =============================================================================
# 6. Additional Precedence, Conflict & Serialization Tests
# =============================================================================

class TestAdditionalPrecedenceAndCompatibility(unittest.TestCase):
    """Test overlapping edge cases, container vs CI permissions, and serialization compatibility."""

    def test_docker_container_permission_denied_vs_ci_permission(self):
        """Conflict check: Container script permission failure during build must be docker_build_failure, not CI permission."""
        log_text = (
            "docker-ci\tBuild Container\t2026-08-16T11:00:00Z ##[group]Run docker build -t app .\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:01Z #5 [2/2] RUN ./build.sh\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:02Z #5 /bin/sh: ./build.sh: Permission denied\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:03Z #5 ERROR: process \"/bin/sh -c ./build.sh\" did not complete successfully: exit code: 126\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:04Z ERROR: failed to solve: process \"/bin/sh -c ./build.sh\" did not complete successfully: exit code: 126\n"
            "docker-ci\tBuild Container\t2026-08-16T11:00:05Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertNotEqual(rec.failure_class, "ci_config_permission_failure")

    def test_pip_dns_resolution_failure_vs_dependency_error(self):
        """Conflict check: Pip failing due to DNS resolution failure must be network_service_failure, not dependency_error."""
        log_text = (
            "ci\tInstall Dependencies\t2026-08-19T10:00:00Z pip install requests\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:02Z WARNING: Retrying (Retry(total=4...)) after connection broken by 'NameResolutionError(\"<urllib3.connection.HTTPSConnection object>: Failed to resolve \\'pypi.org\\' ([Errno -2] Name or service not known)\")'\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:05Z ERROR: Could not find a version that satisfies the requirement requests (from versions: none)\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:06Z Could not resolve host: pypi.org; Temporary failure in name resolution\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:07Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")

    def test_network_endpoint_backward_compatibility_and_serialization(self):
        """Serialization check: LogRecord.to_dict() and parse_logs.COLUMNS mapping remain valid."""
        rec = parse_log_text(
            "ci\tFetch\t2026-08-19T10:00:00Z curl https://api.prod.company.com/v1\n"
            "ci\tFetch\t2026-08-19T10:00:01Z Failed to connect to api.prod.company.com: Connection refused\n"
            "ci\tFetch\t2026-08-19T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.network_endpoint, "api.prod.company.com")

        # to_dict compatibility
        d = rec.to_dict()
        self.assertIn("network_endpoint", d)
        self.assertEqual(d["network_endpoint"], "api.prod.company.com")

        # CSV row serialization compatibility with parse_logs.py
        from parse_logs import COLUMNS, _record_to_row
        row = _record_to_row(rec)
        self.assertEqual(set(row.keys()), set(COLUMNS))
        self.assertEqual(row["failure_type"], "network_service_failure")

    def test_docker_classification_from_pure_text_without_metadata(self):
        """Evidence check: Verifies Docker logs classify from text evidence alone without run_id or file paths."""
        pure_text = (
            "2026-08-16T11:03:00Z ##[group]Run docker build\n"
            "2026-08-16T11:03:01Z #4 ERROR: dockerfile parse error on line 6: flag needs an argument: --from\n"
            "2026-08-16T11:03:02Z ##[error]Process completed with exit code 1.\n"
        )
        # Calling with only positional text argument
        rec = parse_log_text(pure_text)
        self.assertEqual(rec.failure_class, "docker_build_failure")
        self.assertEqual(rec.failure_subcategory, "dockerfile_parse_error")
        self.assertEqual(rec.status, "failure")



    def test_docker_setup_header_with_subsequent_runtime_error_outside_docker(self):
        """Gap 1: Runner mentions Docker tools, but step runs Python app failing with RuntimeError."""
        log_text = (
            "ci\tSet up job\t2026-08-16T11:00:00Z Included Software: Docker 28.0.4, Buildx\n"
            "ci\tRun App\t2026-08-16T11:00:01Z python app.py\n"
            "ci\tRun App\t2026-08-16T11:00:02Z Traceback (most recent call last):\n"
            "ci\tRun App\t2026-08-16T11:00:03Z   File \"app.py\", line 15, in <module>\n"
            "ci\tRun App\t2026-08-16T11:00:04Z RuntimeError: Failed to initialize worker pool\n"
            "ci\tRun App\t2026-08-16T11:00:05Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "runtime_error")
        self.assertEqual(rec.failure_subcategory, "RuntimeError")
        self.assertNotEqual(rec.failure_class, "docker_build_failure")

    def test_pip_connection_refused_vs_dependency_error(self):
        """Gap 4: Pip failing due to connection refused to index server must be network_service_failure."""
        log_text = (
            "ci\tInstall Dependencies\t2026-08-19T10:00:00Z pip install flask\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:01Z Failed to connect to pypi.org:443: Connection refused\n"
            "ci\tInstall Dependencies\t2026-08-19T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "connection_refused")
        self.assertEqual(rec.network_endpoint, "pypi.org")

    def test_pytest_assertion_vs_unhandled_exception_vs_runtime_error(self):
        """Gap 5: Test assertion vs unhandled test exception vs runtime error outside pytest."""
        # 1. Pytest AssertionError -> test_failure / AssertionError -> CAUSAL_TEST
        pytest_assert_text = (
            "ci\tRun Tests\t2026-08-19T10:00:00Z ##[group]Run pytest\n"
            "ci\tRun Tests\t2026-08-19T10:00:01Z FAILED tests/test_calc.py::test_math - AssertionError: assert 1 == 2\n"
            "ci\tRun Tests\t2026-08-19T10:00:02Z = 1 failed, 4 passed in 0.20s =\n"
            "ci\tRun Tests\t2026-08-19T10:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec_assert = parse_log_text(pytest_assert_text)
        self.assertEqual(rec_assert.failure_class, "test_failure")
        self.assertEqual(rec_assert.test_error_type, "AssertionError")
        rep_assert = analyze_record(rec_assert)
        self.assertEqual(rep_assert.causal_category, CAUSAL_TEST)

        # 2. Pytest ZeroDivisionError -> test_failure / ZeroDivisionError -> CAUSAL_TEST_EXECUTION
        pytest_exc_text = (
            "ci\tRun Tests\t2026-08-19T10:00:00Z ##[group]Run pytest\n"
            "ci\tRun Tests\t2026-08-19T10:00:01Z FAILED tests/test_calc.py::test_div - ZeroDivisionError: division by zero\n"
            "ci\tRun Tests\t2026-08-19T10:00:02Z = 1 failed, 4 passed in 0.20s =\n"
            "ci\tRun Tests\t2026-08-19T10:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec_exc = parse_log_text(pytest_exc_text)
        self.assertEqual(rec_exc.failure_class, "test_failure")
        self.assertEqual(rec_exc.test_error_type, "ZeroDivisionError")
        rep_exc = analyze_record(rec_exc)
        self.assertEqual(rep_exc.causal_category, CAUSAL_TEST_EXECUTION)

        # 3. Outside pytest script ZeroDivisionError -> runtime_error -> CAUSAL_CODE_DEFECT
        script_exc_text = (
            "ci\tRun Script\t2026-08-19T10:00:00Z python script.py\n"
            "ci\tRun Script\t2026-08-19T10:00:01Z Traceback (most recent call last):\n"
            "ci\tRun Script\t2026-08-19T10:00:02Z   File \"script.py\", line 5, in <module>\n"
            "ci\tRun Script\t2026-08-19T10:00:03Z ZeroDivisionError: division by zero\n"
            "ci\tRun Script\t2026-08-19T10:00:04Z ##[error]Process completed with exit code 1.\n"
        )
        rec_script = parse_log_text(script_exc_text)
        self.assertEqual(rec_script.failure_class, "runtime_error")
        self.assertEqual(rec_script.error_type, "ZeroDivisionError")
        rep_script = analyze_record(rec_script)
        self.assertEqual(rep_script.causal_category, CAUSAL_CODE_DEFECT)

    def test_generic_log_word_error_does_not_trigger_syntax_error(self):
        """Gap 6: Generic log lines containing 'error' without compiler syntax diagnostic must not be syntax_error."""
        log_text = (
            "ci\tLint\t2026-08-19T10:00:00Z Running code linter\n"
            "ci\tLint\t2026-08-19T10:00:01Z error: rule E501 line too long (88 > 79 characters)\n"
            "ci\tLint\t2026-08-19T10:00:02Z 1 error found in 12 files\n"
            "ci\tLint\t2026-08-19T10:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "syntax_error")
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.failure_subcategory, "unknown_failure")

    def test_truncated_incomplete_log_without_exit_code_is_unknown_with_low_confidence(self):
        """Gap 7: Incomplete truncated log without exit code or error annotation remains unknown with low confidence."""
        log_text = (
            "ci\tSet up job\t2026-08-19T10:00:00Z Starting Runner\n"
            "ci\tSet up job\t2026-08-19T10:00:01Z Runner Image: ubuntu-22.04\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown")
        self.assertIsNone(rec.failure_subcategory)
        self.assertEqual(rec.status, "unknown")
        self.assertLessEqual(rec.parser_confidence, 0.3)

    def test_successful_run_with_deprecation_and_retry_warnings_remains_clean_rca(self):
        """Gap 8: Successful run with warnings must not receive a failure diagnosis."""
        log_text = (
            "ci\tBuild\t2026-08-19T10:00:00Z pip install --upgrade pip\n"
            "ci\tBuild\t2026-08-19T10:00:01Z WARNING: Retrying (Retry(total=2...)) after connection broken\n"
            "ci\tBuild\t2026-08-19T10:00:02Z npm WARN deprecated querystring@0.2.0: Use the URLSearchParams API instead.\n"
            "ci\tBuild\t2026-08-19T10:00:03Z Build completed successfully.\n"
            "ci\tComplete job\t2026-08-19T10:00:04Z Process completed with exit code 0.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.status, "success")
        self.assertEqual(rec.failure_class, "unknown")
        report = analyze_record(rec)
        self.assertEqual(report.causal_category, CAUSAL_UNKNOWN)
        self.assertEqual(report.rca_confidence, 1.0)
        self.assertIn("succeeded", report.summary.lower())
        self.assertIn("no failure detected", report.summary.lower())

    def test_contradictory_pytest_failure_followed_by_cancellation_precedence(self):
        """Gap 9: Pytest test failure followed by platform cancellation annotation preserves test_failure."""
        log_text = (
            "ci\tRun Tests\t2026-08-19T10:00:00Z ##[group]Run pytest\n"
            "ci\tRun Tests\t2026-08-19T10:00:01Z FAILED tests/test_core.py::test_init - AssertionError: Expected status 200 but got 500\n"
            "ci\tRun Tests\t2026-08-19T10:00:02Z = 1 failed, 2 passed in 0.50s =\n"
            "ci\tRun Tests\t2026-08-19T10:00:03Z ##[error]The operation was canceled.\n"
            "ci\tRun Tests\t2026-08-19T10:00:04Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "test_failure")
        self.assertNotEqual(rec.failure_class, "timeout")
        self.assertEqual(rec.test_error_type, "AssertionError")

    def test_rca_report_for_exit_137_and_143_preserves_limitation_and_low_confidence(self):
        """Gap 10: Exit codes 137 and 143 must retain low confidence and explicit OOM/timeout ambiguity limitations."""
        # 137
        rec_137 = parse_log_text(
            "ci\tHeavy Job\t2026-08-19T10:00:00Z Running heavy job\n"
            "ci\tHeavy Job\t2026-08-19T10:00:05Z ##[error]Process completed with exit code 137.\n"
        )
        self.assertEqual(rec_137.failure_class, "unknown")
        self.assertEqual(rec_137.failure_subcategory, "process_signal_137")
        rep_137 = analyze_record(rec_137)
        self.assertEqual(rep_137.rca_confidence, 0.4)
        self.assertTrue(any("does not by itself prove" in lim.lower() for lim in rep_137.limitations))

        # 143
        rec_143 = parse_log_text(
            "ci\tWorker\t2026-08-19T10:00:00Z Running worker\n"
            "ci\tWorker\t2026-08-19T10:00:05Z ##[error]Process completed with exit code 143.\n"
        )
        self.assertEqual(rec_143.failure_class, "unknown")
        self.assertEqual(rec_143.failure_subcategory, "process_signal_143")
        rep_143 = analyze_record(rec_143)
        self.assertEqual(rep_143.rca_confidence, 0.4)
        self.assertTrue(any("does not by itself prove" in lim.lower() for lim in rep_143.limitations))


# =============================================================================
# 6. Stage 10F Regression Tests (Pytest Errors, SSL, Endpoint Attribution, Cancellation)
# =============================================================================

class TestStage10FFixes(unittest.TestCase):
    """Targeted regression tests for Stage 10F bug fixes."""

    def test_pytest_errors_summary_fastapi_pattern(self):
        """Verify that pytest runs with '= ... errors in ...s =' and ERROR entries are classified as test_failure."""
        log_text = (
            "ci\tTest\t2026-09-09T13:46:00Z platform linux -- Python 3.11.16, pytest-8.3.2, pluggy-1.5.0\n"
            "ci\tTest\t2026-09-09T13:46:01Z collected 1090 items\n"
            "ci\tTest\t2026-09-09T13:46:10Z === ERRORS ===\n"
            "ci\tTest\t2026-09-09T13:46:11Z ERROR tests/test_union_body.py - DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated\n"
            "ci\tTest\t2026-09-09T13:46:12Z ================= 193 passed, 5 skipped, 892 errors in 18.67s ==================\n"
            "ci\tTest\t2026-09-09T13:46:13Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "test_failure")
        self.assertEqual(rec.test_error_type, "DeprecationWarning")
        self.assertEqual(rec.tests_failed, 892)
        self.assertEqual(rec.tests_passed, 193)
        self.assertIn("tests/test_union_body.py", rec.failed_test_ids)

        report = analyze_record(rec)
        self.assertEqual(report.causal_category, "test_execution_failure")
        self.assertIn("DeprecationWarning", report.summary)

    def test_pytest_collection_error(self):
        """Verify that pytest collection errors are recognized as test_failure."""
        log_text = (
            "ci\tTest\t2026-09-09T14:00:00Z platform linux -- Python 3.12.0, pytest-8.2.0\n"
            "ci\tTest\t2026-09-09T14:00:01Z ERROR collecting tests/test_broken.py: ImportError: No module named 'foo'\n"
            "ci\tTest\t2026-09-09T14:00:02Z ==================== 1 error in 0.12s ====================\n"
            "ci\tTest\t2026-09-09T14:00:03Z ##[error]Process completed with exit code 2.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "test_failure")
        self.assertEqual(rec.test_error_type, "PytestCollectionError")
        self.assertEqual(rec.tests_failed, 1)

    def test_generic_error_word_outside_pytest_negative(self):
        """Negative: Generic 'error:' lines in build logs must not trigger test_failure."""
        log_text = (
            "ci\tCompile\t2026-09-09T15:00:00Z gcc -o main main.c\n"
            "ci\tCompile\t2026-09-09T15:00:01Z error: expected ';' before '}' token\n"
            "ci\tCompile\t2026-09-09T15:00:02Z 1 error generated.\n"
            "ci\tCompile\t2026-09-09T15:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertNotEqual(rec.failure_class, "test_failure")

    def test_ssl_certificate_verification_failure_positive(self):
        """Positive: SSL certificate verification failure classified as ssl_certificate_error."""
        log_text = (
            "ci\tDownload\t2026-09-09T16:00:00Z python fetch_assets.py\n"
            "ci\tDownload\t2026-09-09T16:00:01Z HTTPSConnectionPool(host='expired.badssl.com', port=443): Max retries exceeded with url: / "
            "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired')))\n"
            "ci\tDownload\t2026-09-09T16:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        self.assertEqual(rec.failure_subcategory, "ssl_certificate_error")
        self.assertEqual(rec.network_endpoint, "expired.badssl.com")
        self.assertIn("expired.badssl.com", rec.error_message)

        report = analyze_record(rec)
        self.assertEqual(report.causal_category, "environment_failure")
        self.assertIn("SSL/TLS certificate verification failure", report.summary)
        self.assertTrue(any("certificate" in inv.lower() for inv in report.suggested_investigation))

    def test_mixed_host_sphinx_linkcheck_endpoint_attribution(self):
        """Verify run_28724831944 pattern: SSL error on host A must NOT be reported as DNS error."""
        log_text = (
            "ci\tBuild docs\t2026-07-05T00:50:13Z WARNING: broken link: https://daniel.roygreenfeld.com/pytest.html "
            "(HTTPSConnectionPool(host='daniel.roygreenfeld.com', port=443): Max retries exceeded with url: /pytest.html "
            "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired'))))\n"
            "ci\tBuild docs\t2026-07-05T00:50:36Z WARNING: timeout http://lists.idyll.org/pipermail "
            "HTTPConnectionPool(host='lists.idyll.org', port=80): Max retries exceeded with url: / (Caused by ConnectTimeoutError(...))\n"
            "ci\tBuild docs\t2026-07-05T00:51:31Z WARNING: broken link: https://no-color.org/ "
            "(HTTPSConnectionPool(host='no-color.org', port=443): Max retries exceeded with url: / "
            "(Caused by NameResolutionError('Failed to resolve no-color.org ([Errno -3] Temporary failure in name resolution)')))\n"
            "ci\tBuild docs\t2026-07-05T00:55:00Z ##[error]Process completed with exit code 2.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "network_service_failure")
        # Primary failure must be the SSL error on daniel.roygreenfeld.com, NOT DNS
        self.assertEqual(rec.failure_subcategory, "ssl_certificate_error")
        self.assertEqual(rec.network_endpoint, "daniel.roygreenfeld.com")
        self.assertNotIn("dns", rec.error_message.lower())

        report = analyze_record(rec)
        self.assertEqual(report.causal_category, "environment_failure")
        self.assertIn("SSL/TLS", report.summary)

    def test_cancellation_with_clean_passing_tests(self):
        """Verify Starlette pattern: cancellation signal after all tests passed explains matrix/external cause."""
        log_text = (
            "ci\tRun Tests\t2026-06-30T20:31:00Z platform linux -- Python 3.12.3, pytest-9.0.3\n"
            "ci\tRun Tests\t2026-06-30T20:31:47Z ======================== 986 passed, 2 xfailed in 7.30s ========================\n"
            "ci\tRun Tests\t2026-06-30T20:31:55Z ##[error]The operation was canceled.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "timeout")
        self.assertEqual(rec.failure_subcategory, "gha_cancellation")
        self.assertEqual(rec.tests_passed, 986)

        report = analyze_record(rec)
        self.assertEqual(report.causal_category, "execution_timeout")
        self.assertIn("passed", report.summary.lower())
        self.assertIn("986 passed", report.likely_cause.lower())
        self.assertIn("fail-fast", report.likely_cause.lower())


if __name__ == "__main__":
    unittest.main()

