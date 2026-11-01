"""parser/log_parser.py

Reusable Parser V2 for raw GitHub Actions CI/CD log files.

Supports both:
  1. Structured 3-column format:
     <job-name>\\t<step-name>\\t<ISO-timestamp>Z <message>
     (used in F1 syntax, F2 dependency, and F4 timeout logs)

  2. GitHub Actions group runner format:
     <ISO-timestamp>Z <message>
     (used in F3 pytest runner logs with ##[group]Run <command> boundaries)

Public API
----------
LogRecord                                                    (dataclass schema)
parse_log_text(text: str, *, run_id=None, failure_type=None) -> LogRecord
parse_log_file(path, *, run_id=None, failure_type=None)     -> LogRecord
parse_batch(directory, *, category=None)                     -> list[LogRecord]
parse_all_categories(base_dir)                               -> dict[str, list[LogRecord]]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# 3-column structured format
_LINE_RE = re.compile(
    r"^(?P<job>[^\t]+)\t"
    r"(?P<step>[^\t]+)\t"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"(?:\s(?P<msg>.*))?$"
)

# Single-timestamp format (GHA runner lines)
_BARE_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"(?:\s(?P<msg>.*))?$"
)

# Strip ANSI control sequences, BOM, and ANSI caret sequences
_ANSI_RE = re.compile(
    r"(?:\x1b|\u001b|\^\[)\[[0-9;?]*[ -/]*[@-~]"
    r"|(?:\x1b|\u001b|\^\[)\([A-B]"
    r"|(?:\x1b|\u001b|\^\[)[=>]"
    r"|(?:\x1b|\u001b|\^\[)\][^\x07\x1b]*\x07"
    r"|\ufeff"
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Exit code annotation / process exit pattern
_EXIT_CODE_RE = re.compile(
    r"(?:##\[error\]Process completed with exit code|Process exited unexpectedly with code|exited with code|exit code)\s+(\d+)",
    re.IGNORECASE
)

# GitHub Actions timeout annotation & broader timeout signals
_TIMEOUT_RE = re.compile(
    r"(?:##\[error\]The action '(?P<step>[^']+)' has timed out after (?P<dur>\d+(?:\.\d+)?) minutes"
    r"|The job running this workflow has timed out after (?P<dur2>\d+(?:\.\d+)?) minutes"
    r"|##\[error\]The operation was canceled because it has timed out"
    r"|has timed out after (?P<dur3>\d+(?:\.\d+)?) minutes)",
    re.IGNORECASE
)

# GitHub Actions cancellation without explicit timeout text
_CANCELLATION_RE = re.compile(
    r"(?:##\[error\]The operation was canceled|The operation was canceled\.|Job cancelled|Workflow run cancelled)",
    re.IGNORECASE
)

# Orphan process termination in GHA cleanup
_ORPHAN_PROC_RE = re.compile(r"Terminate orphan process:\s+pid\s+\(\d+\)\s+\((?P<proc>[^)]+)\)")

# Syntax/Indentation error patterns
_SYNTAX_ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("TabError",         re.compile(r"\bTabError\s*:\s*(.+)")),
    ("IndentationError", re.compile(r"\bIndentationError\s*:\s*(.+)")),
    ("SyntaxError",      re.compile(r"\bSyntaxError\s*:\s*(.+)")),
]

# Standard Python traceback file pointer
_TRACEBACK_FILE_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+)')

# General Python exceptions
_GENERIC_EXCEPTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ModuleNotFoundError", re.compile(r"\bModuleNotFoundError\s*:\s*(.+)")),
    ("ImportError",         re.compile(r"\bImportError\s*:\s*(.+)")),
    ("NameError",           re.compile(r"\bNameError\s*:\s*(.+)")),
    ("TypeError",           re.compile(r"\bTypeError\s*:\s*(.+)")),
    ("ValueError",          re.compile(r"\bValueError\s*:\s*(.+)")),
    ("AttributeError",      re.compile(r"\bAttributeError\s*:\s*(.+)")),
    ("KeyError",            re.compile(r"\bKeyError\s*:\s*(.+)")),
    ("IndexError",          re.compile(r"\bIndexError\s*:\s*(.+)")),
    ("ZeroDivisionError",   re.compile(r"\bZeroDivisionError\s*:\s*(.+)")),
    ("FileNotFoundError",   re.compile(r"\bFileNotFoundError\s*:\s*(.+)")),
    ("AssertionError",      re.compile(r"\bAssertionError(?:\s*:\s*(.*))?")),
    ("PermissionError",     re.compile(r"\bPermissionError\s*:\s*(.+)")),
    ("RuntimeError",        re.compile(r"\bRuntimeError\s*:\s*(.+)")),
]

# Docker build step tag prefix (e.g. #5 1.234 or #0 0.456)
_DOCKER_PREFIX_RE = re.compile(r"^(?:#\d+(?:\s+[\d\.]+)?\s*)+")

# ---------------------------------------------------------------------------
# Docker Build Failure patterns
# ---------------------------------------------------------------------------
_DOCKER_BUILDKIT_SOLVE_RE = re.compile(
    r"(?:ERROR:\s+)?failed to solve(?:\s+with\s+frontend\s+dockerfile\.\w+)?:?\s*(.+)",
    re.IGNORECASE
)
_DOCKER_COPY_NOT_FOUND_RE = re.compile(
    r"(?:failed to calculate checksum of ref [^:]*:\s+\"([^\"]+)\":\s+not found"
    r"|COPY failed:\s+file not found in build context:\s*(.+)"
    r"|COPY failed:\s+stat\s+([^:]+):\s+no such file or directory"
    r"|failed to compute cache key:\s+\"([^\"]+)\":\s+not found)",
    re.IGNORECASE
)
_DOCKERFILE_PARSE_ERROR_RE = re.compile(
    r"(?:dockerfile parse error on line (\d+):\s*(.+)"
    r"|unknown instruction:\s*([A-Za-z0-9_-]+)"
    r"|flag needs an argument:\s*(--[A-Za-z0-9_-]+)"
    r"|stage --from index out of range:\s*(\d+)"
    r"|invalid from flag value)",
    re.IGNORECASE
)
_DOCKER_IMAGE_RESOLUTION_RE = re.compile(
    r"(?:invalid reference format(?::\s*(.+))?"
    r"|pull access denied for\s+([^\s,]+)"
    r"|repository\s+([^\s]+)\s+not found"
    r"|manifest for\s+([^\s]+)\s+not found"
    r"|failed to resolve image\s+([^\s]+))",
    re.IGNORECASE
)
_DOCKER_CONTEXT_RE = re.compile(
    r"(?:unable to prepare context:\s*(.+)"
    r"|can't stat '([^']+)':\s*No such file or directory"
    r"|error checking context:\s*'([^']+)')",
    re.IGNORECASE
)
_DOCKER_DAEMON_RE = re.compile(
    r"(?:Cannot connect to the Docker daemon at\s*([^\r\n.]+)"
    r"|Is the docker daemon running\?"
    r"|docker:\s*Cannot connect to the Docker daemon"
    r"|error during connect:\s*Get\s*\"https?://[^/]+/v[\d\.]+/info\")",
    re.IGNORECASE
)
_DOCKER_RUN_STEP_RE = re.compile(
    r"(?:#\d+\s+ERROR:\s+process \"[^\"]+\" did not complete successfully:\s+exit code:\s+(\d+)"
    r"|executor failed running \[[^\]]+\]:\s+exit code:\s+(\d+)"
    r"|The command '/bin/sh -c [^']+' returned a non-zero code:\s+(\d+))",
    re.IGNORECASE
)
_DOCKER_DOCKERFILE_NOT_FOUND_RE = re.compile(
    r"(?:failed to read dockerfile:\s*open\s+([^:]+):\s*no such file or directory"
    r"|failed to read dockerfile:\s*(.+)"
    r"|unknown flag:\s*(--[A-Za-z0-9_-]+))",
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# CI/CD Configuration and Permission Failure patterns
# ---------------------------------------------------------------------------
_CI_PERMISSION_RE = re.compile(
    r"(?:(?:HttpError:\s+)?Resource not accessible by integration"
    r"|GITHUB_TOKEN does not have permission(?:\s+to\s+([^\r\n.]+))?"
    r"|insufficient permissions for token"
    r"|Missing required permissions?:\s*([^\r\n.]+)"
    r"|Workflow does not have permission to\s+([^\r\n.]+)"
    r"|Permission to ([^\s]+) denied to ([^\s]+)"
    r"|@octokit/request-error.*:\s*Resource not accessible by integration"
    r"|api\.github\.com/.*403 Forbidden"
    r"|GraphQL error:\s*Resource not accessible by integration)",
    re.IGNORECASE
)
_CI_WORKFLOW_CONFIG_RE = re.compile(
    r"(?:Workflow is not valid:\s*(.+)"
    r"|The template is not valid(?::\s*(.+))?"
    r"|You may have invalid syntax in your workflow file(?::\s*(.+))?"
    r"|Unexpected symbol:\s*['\"]?([^'\"\r\n]+)['\"]?\s+while parsing workflow"
    r"|Invalid workflow file:\s*(.+)"
    r"|action\.(?:ya?ml) not found)",
    re.IGNORECASE
)
_CI_ACTION_INPUT_RE = re.compile(
    r"(?:Input required and not supplied:\s*([^\r\n]+)"
    r"|Required input '([^']+)' is missing"
    r"|Missing required environment variable:\s*([^\r\n]+)"
    r"|Required secret '([^']+)' is not defined)",
    re.IGNORECASE
)
_CI_AUTH_FAILURE_RE = re.compile(
    r"(?:Authentication token is invalid or expired"
    r"|unauthorized:\s*authentication required)",
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Network and External Service Failure patterns
# ---------------------------------------------------------------------------
_NET_DNS_RE = re.compile(
    r"(?:Temporary failure in name resolution"
    r"|Could not resolve host:\s*([^\s;]+)"
    r"|getaddrinfo failed"
    r"|socket\.gaierror:\s*\[Errno -2\]\s*Name or service not known"
    r"|NameResolutionError:\s*([^\r\n]+)"
    r"|dns\.resolver\.NXDOMAIN)",
    re.IGNORECASE
)
_NET_CONN_REFUSED_RE = re.compile(
    r"(?:Connection refused"
    r"|\bECONNREFUSED\b"
    r"|\[Errno 111\]\s*Connection refused"
    r"|Failed to connect to\s+([^\s:]+)(?::(\d+))?:\s*Connection refused"
    r"|urllib3\.exceptions\.NewConnectionError:.*Connection refused)",
    re.IGNORECASE
)
_NET_CONN_RESET_RE = re.compile(
    r"(?:Connection reset by peer"
    r"|\bECONNRESET\b"
    r"|\[Errno 104\]\s*Connection reset by peer"
    r"|RemoteDisconnected:\s*Remote end closed connection without response)",
    re.IGNORECASE
)
_NET_UNREACHABLE_RE = re.compile(
    r"(?:No route to host"
    r"|Network is unreachable"
    r"|Host is down"
    r"|\bEHOSTUNREACH\b"
    r"|\bENETUNREACH\b)",
    re.IGNORECASE
)
_NET_TIMEOUT_RE = re.compile(
    r"(?:Connection timed out"
    r"|connect timeout"
    r"|\bETIMEDOUT\b"
    r"|urllib3\.exceptions\.ConnectTimeoutError"
    r"|urllib3\.exceptions\.ReadTimeoutError:\s*.*Read timed out"
    r"|requests\.exceptions\.ConnectTimeout"
    r"|requests\.exceptions\.ReadTimeout"
    r"|HTTPConnectionPool.*:\s*Read timed out"
    r"|HTTPSConnectionPool.*:\s*Max retries exceeded with url)",
    re.IGNORECASE
)
_NET_SSL_RE = re.compile(
    r"(?:SSLCertVerificationError"
    r"|CERTIFICATE_VERIFY_FAILED"
    r"|certificate has expired"
    r"|certificate verify failed"
    r"|ssl\.SSLError"
    r"|requests\.exceptions\.SSLError"
    r"|urllib3\.exceptions\.SSLError"
    r"|SSL:\s*(?:TLSV1_ALERT|WRONG_VERSION_NUMBER|HANDSHAKE_FAILURE|CERT_HAS_EXPIRED))",
    re.IGNORECASE
)
_NET_HTTP_GATEWAY_RE = re.compile(
    r"(?:(?:HTTP\/[\d\.]+|HTTP Error)\s+(?:502\s+Bad\s+Gateway|503\s+Service\s+Unavailable|504\s+Gateway\s+Time-out)"
    r"|502\s+Bad\s+Gateway"
    r"|503\s+Service\s+Unavailable"
    r"|504\s+Gateway\s+Time-out"
    r"|Server disconnected before response was received)",
    re.IGNORECASE
)

# Pip failure patterns
_PIP_NO_MATCH_RE = re.compile(
    r"ERROR:\s+(?:No matching distribution found for|Could not find a version that satisfies the requirement)\s+([^\s\r\n]+)",
    re.IGNORECASE
)
_PIP_INVALID_REQ_RE = re.compile(r"ERROR:\s+Invalid requirement:\s+'([^']+)'", re.IGNORECASE)
_PIP_BUILD_FAIL_RE = re.compile(r"ERROR:\s+Failed to build\s+'([^']+)'", re.IGNORECASE)
_PIP_CONFLICT_RE = re.compile(
    r"(?:ERROR:\s+Cannot install\s+([^\s]+)|ResolutionImpossible|conflicting dependencies|Resolution failure)",
    re.IGNORECASE
)

# Pytest failure patterns (handling wrapper prefixes tox/uv/indentation)
_PYTEST_SUMMARY_FAIL_RE = re.compile(
    r"(?:^|[\s\:\>\]])FAILED\s+([^\s:]+(?:::[^\s:]+)+)\s+-\s+([A-Za-z0-9_.]+)(?::\s*(.*))?"
)
_PYTEST_SUMMARY_ERR_RE = re.compile(
    r"(?:^|[\s\:\>\]])ERROR\s+(?:collecting\s+)?([^\s\-]+)\s+-\s+([A-Za-z0-9_.]+)(?::\s*(.*))?"
)
_PYTEST_COLLECT_ERR_RE = re.compile(
    r"(?:^|[\s\:\>\]])ERROR\s+collecting\s+([^\s:]+(?:::[^\s:]+)?)(?::\s*(.*))?"
)
_PYTEST_COUNTS_RE = re.compile(r"=\s*(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?(?:(?P<passed>\d+)\s+passed)?(?:\s+in\s+[\d\.]+s)?\s*=")
_PYTEST_SESSION_RE = re.compile(r"platform\s+\w+\s+--\s+Python\s+[\d\.]+,?\s+(pytest-[\d\.]+)")


def parse_pytest_counts(text: str) -> Optional[dict[str, int]]:
    """Parse pytest summary counts header line irrespective of field ordering.

    Examples:
      === 1 failed, 5 passed in 0.03s ===
      ================= 193 passed, 5 skipped, 892 errors in 18.67s ==================
      === 2 errors in 0.45s ===
    """
    m_line = re.search(r"={2,}\s*(.*?in\s+[\d\.]+s\s*)={2,}", text)
    if not m_line:
        m_line = re.search(r"={2,}\s*(\d+\s+(?:failed|passed|errors?|skipped|xfailed|xpassed).*?)={2,}", text)
    if not m_line:
        return None
    content = m_line.group(1)
    results: dict[str, int] = {}
    for match in re.finditer(r"\b(\d+)\s+(failed|passed|errors?|skipped|xfailed|xpassed)\b", content):
        cnt, kind = int(match.group(1)), match.group(2)
        if kind.startswith("error"):
            results["errors"] = cnt
        else:
            results[kind] = cnt
    return results

# Tool detection keywords
_TOOL_KEYWORDS = ["pytest", "pip", "python", "git", "flake8", "black", "mypy", "bash", "tox", "uv", "poetry", "docker"]


def _extract_endpoint_from_line(line: str) -> Optional[str]:
    """Extract host or endpoint URL from a specific network error line."""
    m_pool = re.search(r"host='([^']+)'", line)
    if m_pool:
        return m_pool.group(1).strip()
    m_url = re.search(r"https?://([a-zA-Z0-9.-]+(?::\d+)?)", line)
    if m_url:
        return m_url.group(1).strip()
    m_host = re.search(r"(?:Could not resolve host|Failed to connect to)\s*:?\s*([a-zA-Z0-9.-]+)", line, re.IGNORECASE)
    if m_host:
        return m_host.group(1).strip()
    m_dns = re.search(r"Temporary failure in name resolution(?::\s*'([^']+)')?", line, re.IGNORECASE)
    if m_dns and m_dns.group(1):
        return m_dns.group(1).strip()
    return None


def _extract_network_endpoint(text: str) -> Optional[str]:
    """Extract host or endpoint URL from network error text without inventing one."""
    return _extract_endpoint_from_line(text)


def _clean(text: str) -> str:
    """Remove ANSI escapes, BOM, and non-printable control chars."""
    if "\ufeff" in text or "\x1b" in text or "\u001b" in text or "^[" in text:
        text = text.replace("\ufeff", "")
        text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    try:
        dt = datetime.fromisoformat(ts_str.rstrip("Z"))
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _infer_stage(step_name: Optional[str]) -> str:
    """Map a step name to a pipeline stage label."""
    if not step_name:
        return "unknown"
    lower = step_name.lower()
    if any(kw in lower for kw in ("syntax", "install", "build", "compile", "lint", "docker", "container", "image")):
        return "build"
    if any(kw in lower for kw in ("test", "pytest", "unittest", "spec")):
        return "test"
    if any(kw in lower for kw in ("deploy", "publish", "release", "push")):
        return "deploy"
    if any(kw in lower for kw in ("checkout", "setup", "set up")):
        return "setup"
    return "unknown"


# ---------------------------------------------------------------------------
# Data class schema for LogRecord (V1 preserved + V2 enriched)
# ---------------------------------------------------------------------------

@dataclass
class LogRecord:
    """Structured representation of a parsed CI/CD log."""

    # --- required V1 schema columns (preserved) ---
    run_id:        Optional[str]   = None
    timestamp:     Optional[str]   = None   # ISO-8601 UTC string
    step_name:     Optional[str]   = None
    stage:         Optional[str]   = None
    duration:      Optional[float] = None   # seconds
    status:        Optional[str]   = None   # "success" | "failure" | "unknown"
    error_type:    Optional[str]   = None
    error_message: Optional[str]   = None
    log_text:      str             = ""     # full raw log
    failure_type:  Optional[str]   = None

    # --- optional V1 enrichment columns (preserved) ---
    line_number:   Optional[int]   = None
    file_path:     Optional[str]   = None
    matched_line:  Optional[str]   = None
    exit_code:     Optional[int]   = None
    python_version: Optional[str]  = None

    # --- Parser V2: generalized failure fields ---
    failure_class:        Optional[str]   = None  # "syntax_error" | "dependency_error" | "test_failure" | "timeout" | "docker_build_failure" | "ci_config_permission_failure" | "network_service_failure" | "runtime_error" | "unknown"
    failure_subcategory:  Optional[str]   = None  # e.g. "SyntaxError", "pip_missing_dependency", "docker_copy_not_found", "token_permission_insufficient", "dns_resolution_failure", ...

    # --- step sequence ---
    step_sequence:        list[str]       = field(default_factory=list)
    failed_step:          Optional[str]   = None
    execution_path:       list[str]       = field(default_factory=list)

    # --- evidence ---
    evidence_lines:       list[str]       = field(default_factory=list)
    traceback_lines:      list[str]       = field(default_factory=list)

    # --- command/tool/framework ---
    commands_run:         list[str]       = field(default_factory=list)
    tools_detected:       list[str]       = field(default_factory=list)
    frameworks_detected:  list[str]       = field(default_factory=list)

    # --- dependency evidence (F2) ---
    failing_package:      Optional[str]   = None
    packages_attempted:   list[str]       = field(default_factory=list)
    pip_commands:         list[str]       = field(default_factory=list)

    # --- test evidence (F3) ---
    pytest_session:       Optional[str]   = None
    tests_collected:      Optional[int]   = None
    tests_passed:         Optional[int]   = None
    tests_failed:         Optional[int]   = None
    failed_test_ids:      list[str]       = field(default_factory=list)
    test_error_type:      Optional[str]   = None

    # --- timeout evidence (F4) ---
    timeout_duration_min: Optional[float] = None
    elapsed_step_seconds: Optional[float] = None
    orphan_process:       Optional[str]   = None

    # --- network evidence ---
    network_endpoint:     Optional[str]   = None

    # --- meta ---
    log_format:           Optional[str]   = None  # "structured" | "bare"
    log_line_count:       Optional[int]   = None
    parser_confidence:    float           = 0.0
    parse_errors:         list[str]       = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core parsing logic
# ---------------------------------------------------------------------------

_BOILERPLATE_STEPS = {
    "set up job", "complete job", "post checkout repository",
    "runner image provisioner", "operating system", "runner image",
    "github_token permissions"
}

def _is_boilerplate(step: str) -> bool:
    s = step.strip().lower()
    if s in _BOILERPLATE_STEPS or s.startswith("post "):
        return True
    return False


def parse_log_text(
    text: str,
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse raw CI/CD log text and return a fully structured LogRecord.
    """
    record = LogRecord(run_id=run_id, log_text=text, failure_type=failure_type)

    raw_lines = text.splitlines()
    record.log_line_count = len(raw_lines)
    if not text.strip() or not raw_lines:
        record.status = "unknown"
        record.failure_class = "unknown"
        record.failure_subcategory = "empty_log"
        record.parser_confidence = 0.0
        return record

    # 1. Parse lines and auto-detect format
    structured_entries: list[dict] = []
    bare_entries: list[dict] = []
    for raw in raw_lines:
        cleaned = _clean(raw)
        m_struct = _LINE_RE.match(cleaned)
        if m_struct:
            structured_entries.append({
                "job": m_struct.group("job"),
                "step": m_struct.group("step"),
                "ts": m_struct.group("ts"),
                "msg": (m_struct.group("msg") or "").strip(),
                "raw": cleaned,
            })
            continue
        m_bare = _BARE_LINE_RE.match(cleaned)
        if m_bare:
            bare_entries.append({
                "ts": m_bare.group("ts"),
                "msg": (m_bare.group("msg") or "").strip(),
                "raw": cleaned,
            })

    if structured_entries and len(structured_entries) >= len(bare_entries):
        record.log_format = "structured"
        parsed_stream = structured_entries
    elif bare_entries:
        record.log_format = "bare"
        parsed_stream = bare_entries
    else:
        record.log_format = "bare"
        parsed_stream = [{"ts": None, "msg": _clean(r).strip(), "raw": _clean(r)} for r in raw_lines]

    # Timestamp: first timestamp observed
    for item in parsed_stream:
        if item.get("ts"):
            record.timestamp = item["ts"]
            break

    # 2. Extract step sequence, commands, tools, frameworks
    step_sequence: list[str] = []
    seen_steps: set[str] = set()
    current_step: Optional[str] = None
    step_entry_map: dict[str, list[dict]] = {}

    commands_run: list[str] = []
    tools_detected: set[str] = set()
    frameworks_detected: set[str] = set()
    packages_attempted: list[str] = []
    pip_commands: list[str] = []

    if record.log_format == "structured":
        for entry in parsed_stream:
            step = entry.get("step")
            msg = entry.get("msg", "")

            if step:
                if step not in step_entry_map:
                    step_entry_map[step] = []
                step_entry_map[step].append(entry)

                if not _is_boilerplate(step) and step not in seen_steps:
                    seen_steps.add(step)
                    step_sequence.append(step)

            # Commands detection
            if msg.startswith("[command]"):
                cmd = msg[len("[command]"):].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif step == "Check App Syntax" and "python -c" in msg:
                if msg not in commands_run:
                    commands_run.append(msg)
            elif "pip install" in msg:
                if msg not in pip_commands:
                    pip_commands.append(msg)
                if msg not in commands_run:
                    commands_run.append(msg)

            # Attempted packages
            if msg.startswith("Collecting "):
                pkg = msg.split()[1]
                if pkg not in packages_attempted:
                    packages_attempted.append(pkg)

    else:
        # Bare / runner group format
        for entry in parsed_stream:
            msg = entry.get("msg", "")
            if "##[group]Run " in msg:
                step_cmd = msg.split("##[group]Run ", 1)[1].strip()
                current_step = step_cmd
                if current_step not in seen_steps:
                    seen_steps.add(current_step)
                    step_sequence.append(current_step)

            if current_step:
                if current_step not in step_entry_map:
                    step_entry_map[current_step] = []
                step_entry_map[current_step].append(entry)

            # Commands
            if "##[group]Run " in msg:
                cmd = msg.split("##[group]Run ", 1)[1].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif msg.startswith("[command]"):
                cmd = msg[len("[command]"):].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif "pip install" in msg:
                if msg not in pip_commands:
                    pip_commands.append(msg)
                if msg not in commands_run:
                    commands_run.append(msg)

            if msg.startswith("Collecting "):
                pkg = msg.split()[1]
                if pkg not in packages_attempted:
                    packages_attempted.append(pkg)

    record.step_sequence = step_sequence
    record.packages_attempted = packages_attempted
    record.pip_commands = pip_commands

    # Detect tools & frameworks from log messages
    full_text_lower = text.lower()
    for tool in _TOOL_KEYWORDS:
        if tool in full_text_lower or any(tool in cmd.lower() for cmd in commands_run):
            tools_detected.add(tool)

    for entry in parsed_stream:
        msg = entry.get("msg", "")
        # Python version
        if not record.python_version:
            m_pv = re.search(r"(?:CPython|Python)\s+\(?(\d+\.\d+\.\d+)\)?", msg)
            if m_pv:
                record.python_version = m_pv.group(1)
        # Pytest session & framework
        m_pytest = _PYTEST_SESSION_RE.search(msg)
        if m_pytest:
            record.pytest_session = msg
            frameworks_detected.add(m_pytest.group(1))
        # Exit code
        m_ec = _EXIT_CODE_RE.search(msg)
        if m_ec:
            record.exit_code = int(m_ec.group(1))

    record.tools_detected = sorted(tools_detected)
    record.frameworks_detected = sorted(frameworks_detected)
    record.commands_run = commands_run

    # 3. Category-specific failure detectors (in strict priority order)
    # Rule 1: ##[error] alone must NOT determine category.
    # Rule 2: Exception in pytest must be failure_class = "test_failure".
    clean_text = _clean(text)
    detected_class: Optional[str] = None
    detected_subcat: Optional[str] = None
    failed_step: Optional[str] = None
    evidence_lines: list[str] = []
    traceback_lines: list[str] = []
    confidence: float = 0.0

    # -------------------------------------------------------------
    # (A) Check for Explicit Timeout or GHA Cancellation (F4)
    #
    # Two distinct sub-cases:
    #   1. gha_timeout  - runner emits an explicit timeout annotation with a
    #                     duration (highest-confidence)
    #   2. gha_cancellation - runner emits '##[error]The operation was canceled.'
    #                     without a timeout annotation.  This is a definitive
    #                     platform-level signal (not the same as exit codes 137/143
    #                     which are OS-level and ambiguous).  Ground truth treats
    #                     these as F4; RCA reports the limitation that the
    #                     underlying trigger (timeout vs. manual vs. concurrency)
    #                     cannot be determined from the log alone.
    # -------------------------------------------------------------
    m_timeout = _TIMEOUT_RE.search(clean_text)
    if m_timeout:
        detected_class = "timeout"
        detected_subcat = "gha_timeout"
        failed_step = m_timeout.groupdict().get("step")
        dur_str = m_timeout.groupdict().get("dur") or m_timeout.groupdict().get("dur2") or m_timeout.groupdict().get("dur3")
        dur_min = float(dur_str) if dur_str else None
        record.timeout_duration_min = dur_min

        # Orphan process detection
        m_orphan = _ORPHAN_PROC_RE.search(clean_text)
        if m_orphan:
            record.orphan_process = m_orphan.group("proc")

        for entry in parsed_stream:
            msg = entry.get("msg", "")
            if "has timed out" in msg or "Terminate orphan process" in msg or "canceled because it has timed out" in msg:
                evidence_lines.append(entry.get("raw", msg))

        confidence = 1.0 if (dur_min and record.orphan_process) else 0.85

    # -------------------------------------------------------------
    # (B) Check for Syntax errors (F1) - Takes priority over generic pytest collection
    # -------------------------------------------------------------
    if not detected_class:
        for etype, pattern in _SYNTAX_ERROR_PATTERNS:
            m_syntax = pattern.search(clean_text)
            if m_syntax:
                detected_class = "syntax_error"
                detected_subcat = etype
                record.error_type = etype
                record.error_message = m_syntax.group(1).strip()
                record.matched_line = m_syntax.group(0).strip()
                break

        if detected_class == "syntax_error":
            # Extract python traceback block
            tb_block: list[str] = []
            capturing = False
            for entry in parsed_stream:
                raw_l = entry.get("raw", "")
                msg = entry.get("msg", "")
                if "Traceback (most recent call last):" in msg or ("File " in msg and not capturing):
                    capturing = True
                if capturing:
                    tb_block.append(raw_l)
                    if any(etype in msg for etype in ("SyntaxError:", "IndentationError:", "TabError:")):
                        capturing = False
            traceback_lines = tb_block
            evidence_lines = list(tb_block) if tb_block else [record.matched_line or ""]

            # Find real source file and line number (avoiding <string>)
            m_tb_file = _TRACEBACK_FILE_RE.search(clean_text)
            if m_tb_file and m_tb_file.group(1) != "<string>":
                record.file_path = m_tb_file.group(1)
                record.line_number = int(m_tb_file.group(2))
            else:
                for line in tb_block:
                    m = _TRACEBACK_FILE_RE.search(line)
                    if m and m.group(1) != "<string>":
                        record.file_path = m.group(1)
                        record.line_number = int(m.group(2))
                        break

            for step in step_sequence:
                if any(kw in step.lower() for kw in ("syntax", "check app syntax")):
                    failed_step = step
                    break
            if not failed_step:
                failed_step = "Check App Syntax"

            confidence = 1.0 if (traceback_lines and record.file_path and record.file_path != "<string>") else 0.85

    # -------------------------------------------------------------
    # (B2) Check for CI/CD Configuration & Permission Failures
    # -------------------------------------------------------------
    if not detected_class:
        m_ci_perm = None
        m_ci_wf = None
        m_ci_input = None
        m_ci_auth = None
        ci_error_lines: list[str] = []

        for entry in parsed_stream:
            step = entry.get("step")
            msg = entry.get("msg", "")
            raw = entry.get("raw", msg)

            # Skip checking boilerplate lines unless explicit failure indicator
            if step and _is_boilerplate(step) and not ("##[error]" in raw or "Resource not accessible" in msg):
                continue

            # Skip ordinary Python PermissionError (application code runtime/test failure)
            if "PermissionError:" in msg:
                continue
            # Skip container script permission denied in shell runner steps
            if "/bin/sh:" in msg and "Permission denied" in msg:
                continue

            if not m_ci_perm:
                m_ci_perm = _CI_PERMISSION_RE.search(msg)
            if not m_ci_wf:
                m_ci_wf = _CI_WORKFLOW_CONFIG_RE.search(msg)
            if not m_ci_input:
                m_ci_input = _CI_ACTION_INPUT_RE.search(msg)
            if not m_ci_auth:
                m_ci_auth = _CI_AUTH_FAILURE_RE.search(msg)

            if (
                _CI_PERMISSION_RE.search(msg)
                or _CI_WORKFLOW_CONFIG_RE.search(msg)
                or _CI_ACTION_INPUT_RE.search(msg)
                or _CI_AUTH_FAILURE_RE.search(msg)
            ):
                ci_error_lines.append(raw)

        if m_ci_perm or m_ci_wf or m_ci_input or m_ci_auth:
            detected_class = "ci_config_permission_failure"
            if m_ci_perm:
                detected_subcat = "token_permission_insufficient"
                perm_scope = m_ci_perm.group(1) if m_ci_perm.lastindex else None
                record.error_message = f"CI/CD permission denied: {perm_scope or 'Resource not accessible by integration'}"
            elif m_ci_wf:
                detected_subcat = "workflow_syntax_error"
                detail = m_ci_wf.group(1) if m_ci_wf.lastindex else ""
                record.error_message = f"Invalid workflow configuration: {detail or 'workflow syntax error'}"
            elif m_ci_input:
                detected_subcat = "action_input_missing"
                inp = m_ci_input.group(1) if m_ci_input.lastindex else ""
                record.error_message = f"Missing required workflow input/secret: {inp}"
            elif m_ci_auth:
                detected_subcat = "ci_authorization_failure"
                record.error_message = "CI service authorization failed: invalid token or authentication required"

            record.error_type = detected_subcat
            for step in reversed(step_sequence):
                if not _is_boilerplate(step):
                    failed_step = step
                    break
            if not failed_step and step_sequence:
                failed_step = step_sequence[0]
            if not failed_step:
                failed_step = "Workflow Setup"

            evidence_lines = ci_error_lines if ci_error_lines else [record.error_message]
            confidence = 0.95

    # -------------------------------------------------------------
    # (C) Check for Pytest test failure (F3)
    # -------------------------------------------------------------
    if not detected_class:
        is_test_failure = False
        pytest_failed_tests: list[str] = []
        pytest_error_type: Optional[str] = None
        pytest_err_msg: Optional[str] = None

        # Look for short test summary lines (both FAILED and ERROR)
        for entry in parsed_stream:
            msg = entry.get("msg", "")
            m_fail = _PYTEST_SUMMARY_FAIL_RE.search(msg)
            if m_fail:
                is_test_failure = True
                test_id = m_fail.group(1)
                etype = m_fail.group(2)
                emsg = (m_fail.group(3) or "").strip()
                if test_id not in pytest_failed_tests:
                    pytest_failed_tests.append(test_id)
                if not pytest_error_type:
                    pytest_error_type = etype
                    pytest_err_msg = emsg

            m_err = _PYTEST_SUMMARY_ERR_RE.search(msg)
            if m_err:
                is_test_failure = True
                test_id = m_err.group(1)
                etype = m_err.group(2)
                emsg = (m_err.group(3) or "").strip()
                if test_id not in pytest_failed_tests:
                    pytest_failed_tests.append(test_id)
                if not pytest_error_type:
                    pytest_error_type = etype
                    pytest_err_msg = emsg

            m_coll = _PYTEST_COLLECT_ERR_RE.search(msg)
            if m_coll:
                is_test_failure = True
                test_id = m_coll.group(1)
                emsg = (m_coll.group(2) or "").strip()
                if test_id not in pytest_failed_tests:
                    pytest_failed_tests.append(test_id)
                if not pytest_error_type:
                    pytest_error_type = "PytestCollectionError"
                    pytest_err_msg = emsg

        # Check for counts line (e.g. "= 1 failed, 5 passed in 0.03s =", "= 193 passed, 892 errors =")
        counts = parse_pytest_counts(text)
        if counts:
            if "passed" in counts:
                record.tests_passed = counts["passed"]
            failed_c = counts.get("failed", 0)
            errors_c = counts.get("errors", 0)
            if failed_c > 0 or errors_c > 0:
                record.tests_failed = failed_c + errors_c
                is_test_failure = True
        else:
            # Fallback legacy regexes
            m_failed_cnt = re.search(r"\b(\d+)\s+failed\b", text)
            if m_failed_cnt and re.search(r"\b\d+\s+passed\b|pytest|\bcollected\b", text):
                record.tests_failed = int(m_failed_cnt.group(1))
                if record.tests_failed > 0:
                    is_test_failure = True

            m_passed_cnt = re.search(r"\b(\d+)\s+passed\b", text)
            if m_passed_cnt:
                record.tests_passed = int(m_passed_cnt.group(1))

        has_error_header = "= ERRORS =" in text and ("pytest" in text.lower() or "platform" in text or "collected" in text or "errors in " in text)
        if is_test_failure or "= FAILURES =" in text or has_error_header:
            detected_class = "test_failure"
            if pytest_error_type:
                detected_subcat = pytest_error_type
            elif counts and counts.get("errors", 0) > 0 and counts.get("failed", 0) == 0:
                detected_subcat = "pytest_error"
            else:
                detected_subcat = "pytest_failure"

            record.test_error_type = pytest_error_type or detected_subcat
            record.failed_test_ids = pytest_failed_tests
            record.error_type = record.test_error_type
            record.error_message = pytest_err_msg

            for step in reversed(step_sequence):
                if any(kw in step.lower() for kw in ("test", "pytest", "tox", "uv")):
                    failed_step = step
                    break
            if not failed_step and step_sequence:
                failed_step = step_sequence[-1]

            # Extract pytest traceback block
            tb_collecting = False
            for entry in parsed_stream:
                raw_l = entry.get("raw", "")
                if "=== FAILURES ===" in raw_l or "=== ERRORS ===" in raw_l:
                    tb_collecting = True
                if tb_collecting:
                    traceback_lines.append(raw_l)
                    if "=== short test summary info ===" in raw_l and len(traceback_lines) > 2:
                        tb_collecting = False

            # Evidence lines: short summary lines + counts line
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if (
                    _PYTEST_SUMMARY_FAIL_RE.search(msg)
                    or _PYTEST_SUMMARY_ERR_RE.search(msg)
                    or _PYTEST_COLLECT_ERR_RE.search(msg)
                    or _PYTEST_COUNTS_RE.search(msg)
                    or (counts and re.search(r"={2,}\s*.*?\bin\s+[\d\.]+s\s*={2,}", msg))
                ):
                    evidence_lines.append(entry.get("raw", msg))

            # Pytest items collected count
            m_coll = re.search(r"collected\s+(\d+)\s+items?", text)
            if m_coll:
                record.tests_collected = int(m_coll.group(1))

            confidence = 1.0 if (pytest_failed_tests and pytest_error_type) else 0.85

    # -------------------------------------------------------------
    # (C2) GHA platform-level cancellation (F4 / gha_cancellation)
    #
    # Placed AFTER the test failure check (C) so that logs containing
    # both pytest FAILED lines and a cancellation annotation are correctly
    # classified as F3 (test failure), not F4.  Only logs where no
    # definitive test failure, syntax error, or explicit timeout is found
    # are classified here.
    # -------------------------------------------------------------
    if not detected_class:
        m_cancel = _CANCELLATION_RE.search(clean_text)
        if m_cancel:
            detected_class = "timeout"
            detected_subcat = "gha_cancellation"
            confidence = 0.7  # Definitive platform signal, but trigger is ambiguous
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if "operation was canceled" in msg.lower() or "job cancelled" in msg.lower():
                    evidence_lines.append(entry.get("raw", msg))
            if record.tests_passed and not record.tests_failed:
                record.error_message = f"Workflow step canceled by GitHub Actions runner ({record.tests_passed} tests passed)"
            else:
                record.error_message = "Workflow step canceled by GitHub Actions runner"

    # -------------------------------------------------------------
    # (D) Check for Network and External Service Failure
    # -------------------------------------------------------------
    if not detected_class:
        net_matches: list[dict[str, Any]] = []

        is_failing_context = (record.exit_code not in (None, 0)) or ("##[error]" in text)

        if is_failing_context:
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                raw = entry.get("raw", msg)

                # Skip if this line is an HTTP 401/403 (handled in auth/permission)
                if re.search(r"40[13]\s+(?:Unauthorized|Forbidden)", msg):
                    continue

                subcat = None
                if _NET_SSL_RE.search(msg):
                    subcat = "ssl_certificate_error"
                elif _NET_DNS_RE.search(msg):
                    subcat = "dns_resolution_failure"
                elif _NET_CONN_REFUSED_RE.search(msg):
                    subcat = "connection_refused"
                elif _NET_CONN_RESET_RE.search(msg):
                    subcat = "connection_reset"
                elif _NET_UNREACHABLE_RE.search(msg):
                    subcat = "host_unreachable"
                elif _NET_HTTP_GATEWAY_RE.search(msg):
                    subcat = "http_gateway_error"
                elif _NET_TIMEOUT_RE.search(msg):
                    subcat = "connection_timeout"

                if subcat:
                    ep = _extract_endpoint_from_line(msg)
                    net_matches.append({
                        "subcat": subcat,
                        "endpoint": ep,
                        "raw": raw,
                    })

            if net_matches:
                detected_class = "network_service_failure"
                primary = net_matches[0]
                detected_subcat = primary["subcat"]
                endpoint = primary["endpoint"]
                record.network_endpoint = endpoint

                if detected_subcat == "ssl_certificate_error":
                    record.error_message = f"SSL/TLS certificate verification failed connecting to {endpoint}" if endpoint else "SSL/TLS certificate verification failed: certificate expired or untrusted"
                elif detected_subcat == "dns_resolution_failure":
                    record.error_message = f"DNS resolution failure connecting to {endpoint}" if endpoint else "DNS resolution failure: temporary name resolution error"
                elif detected_subcat == "connection_refused":
                    record.error_message = f"Connection refused connecting to {endpoint}" if endpoint else "Network connection refused by target host"
                elif detected_subcat == "connection_reset":
                    record.error_message = f"Connection reset by peer connecting to {endpoint}" if endpoint else "Network connection reset by peer"
                elif detected_subcat == "host_unreachable":
                    record.error_message = f"Host unreachable: {endpoint}" if endpoint else "Network host or route unreachable"
                elif detected_subcat == "connection_timeout":
                    record.error_message = f"Connection timed out connecting to {endpoint}" if endpoint else "Network connection/read timed out"
                elif detected_subcat == "http_gateway_error":
                    record.error_message = f"HTTP gateway/server error connecting to {endpoint}" if endpoint else "HTTP gateway error (502/503/504)"

                record.error_type = detected_subcat
                for step in reversed(step_sequence):
                    if not _is_boilerplate(step):
                        failed_step = step
                        break
                if not failed_step and step_sequence:
                    failed_step = step_sequence[-1]

                evidence_lines = [m["raw"] for m in net_matches]
                confidence = 0.9 if detected_subcat not in ("connection_timeout",) else 0.75

    # -------------------------------------------------------------
    # (D2) Check for Dependency / Pip failure (F2) - Includes Docker build output
    # -------------------------------------------------------------
    if not detected_class:
        m_pip_no_match = None
        m_pip_invalid = None
        m_pip_build = None
        m_pip_conflict = None

        for entry in parsed_stream:
            msg = entry.get("msg", "")
            clean_msg = _DOCKER_PREFIX_RE.sub("", msg)

            if not m_pip_no_match:
                m_pip_no_match = _PIP_NO_MATCH_RE.search(clean_msg)
            if not m_pip_invalid:
                m_pip_invalid = _PIP_INVALID_REQ_RE.search(clean_msg)
            if not m_pip_build:
                m_pip_build = _PIP_BUILD_FAIL_RE.search(clean_msg)
            if not m_pip_conflict:
                m_pip_conflict = _PIP_CONFLICT_RE.search(clean_msg)

        if m_pip_no_match or m_pip_invalid or m_pip_build or m_pip_conflict:
            detected_class = "dependency_error"
            if m_pip_no_match:
                record.failing_package = m_pip_no_match.group(1)
                detected_subcat = "pip_missing_dependency"
                record.error_message = f"No matching distribution or requirement for {record.failing_package}"
            elif m_pip_invalid:
                record.failing_package = m_pip_invalid.group(1)
                detected_subcat = "pip_invalid_requirement"
                record.error_message = f"Invalid requirement: {record.failing_package}"
            elif m_pip_build:
                record.failing_package = m_pip_build.group(1)
                detected_subcat = "pip_build_failure"
                record.error_message = f"Failed to build {record.failing_package}"
            elif m_pip_conflict:
                pkg_match = m_pip_conflict.group(1) if m_pip_conflict.lastindex and m_pip_conflict.lastindex >= 1 else None
                record.failing_package = pkg_match
                detected_subcat = "pip_dependency_conflict"
                record.error_message = "Conflicting package dependency requirements"

            record.error_type = detected_subcat
            for step in step_sequence:
                if any(kw in step.lower() for kw in ("install", "dep", "pip", "docker", "build")):
                    failed_step = step
                    break
            if not failed_step:
                failed_step = "Install Dependencies"

            for entry in parsed_stream:
                msg = entry.get("msg", "")
                clean_msg = _DOCKER_PREFIX_RE.sub("", msg)
                if "ERROR:" in clean_msg or "ResolutionImpossible" in clean_msg:
                    evidence_lines.append(entry.get("raw", msg))

            confidence = 1.0 if record.failing_package else 0.85

    # -------------------------------------------------------------
    # (D3) Check for Docker Build Failure
    # -------------------------------------------------------------
    if not detected_class:
        m_docker_copy = None
        m_docker_parse = None
        m_docker_img = None
        m_docker_ctx = None
        m_docker_daemon = None
        m_docker_run = None
        m_docker_df_missing = None
        m_docker_solve = None

        docker_error_lines: list[str] = []
        docker_command_failed = any("docker build" in cmd.lower() for cmd in commands_run)

        for entry in parsed_stream:
            msg = entry.get("msg", "")
            raw = entry.get("raw", msg)
            clean_msg = _DOCKER_PREFIX_RE.sub("", msg)

            if not m_docker_copy:
                m_docker_copy = _DOCKER_COPY_NOT_FOUND_RE.search(clean_msg)
            if not m_docker_parse:
                m_docker_parse = _DOCKERFILE_PARSE_ERROR_RE.search(clean_msg)
            if not m_docker_img:
                m_docker_img = _DOCKER_IMAGE_RESOLUTION_RE.search(clean_msg)
            if not m_docker_ctx:
                m_docker_ctx = _DOCKER_CONTEXT_RE.search(clean_msg)
            if not m_docker_daemon:
                m_docker_daemon = _DOCKER_DAEMON_RE.search(clean_msg)
            if not m_docker_df_missing:
                m_docker_df_missing = _DOCKER_DOCKERFILE_NOT_FOUND_RE.search(clean_msg)
            if not m_docker_run:
                m_docker_run = _DOCKER_RUN_STEP_RE.search(clean_msg)
            if not m_docker_solve:
                m_docker_solve = _DOCKER_BUILDKIT_SOLVE_RE.search(clean_msg)

            if (
                "ERROR:" in msg
                or "failed to solve" in msg.lower()
                or "dockerfile parse error" in msg.lower()
                or "invalid reference format" in msg.lower()
                or "executor failed running" in msg.lower()
                or "Cannot connect to the Docker daemon" in msg
            ):
                docker_error_lines.append(raw)

        has_docker_pattern = (
            m_docker_copy or m_docker_parse or m_docker_img or m_docker_ctx
            or m_docker_daemon or m_docker_df_missing or m_docker_run or m_docker_solve
        )

        if has_docker_pattern or (docker_command_failed and record.exit_code not in (None, 0)):
            detected_class = "docker_build_failure"
            if m_docker_copy:
                detected_subcat = "docker_copy_not_found"
                target = m_docker_copy.group(1) or m_docker_copy.group(2) or m_docker_copy.group(3) or m_docker_copy.group(4)
                record.error_message = f"COPY/ADD failed: '{target}' not found in build context"
            elif m_docker_parse:
                detected_subcat = "dockerfile_parse_error"
                line_no = m_docker_parse.group(1) or ""
                detail = m_docker_parse.group(2) or m_docker_parse.group(3) or m_docker_parse.group(4) or ""
                record.error_message = f"Dockerfile parse error on line {line_no}: {detail}".strip(": ")
            elif m_docker_img:
                detected_subcat = "docker_image_resolution_error"
                ref = m_docker_img.group(1) or m_docker_img.group(2) or m_docker_img.group(3) or m_docker_img.group(4) or m_docker_img.group(5)
                record.error_message = f"Docker image resolution failure: {ref or 'invalid reference format'}"
            elif m_docker_ctx:
                detected_subcat = "docker_context_error"
                ctx = m_docker_ctx.group(1) or m_docker_ctx.group(2) or m_docker_ctx.group(3)
                record.error_message = f"Docker build context error: {ctx}"
            elif m_docker_df_missing:
                detected_subcat = "docker_dockerfile_not_found"
                df = m_docker_df_missing.group(1) or m_docker_df_missing.group(2) or m_docker_df_missing.group(3)
                record.error_message = f"Failed to read Dockerfile or invalid flag: {df}"
            elif m_docker_daemon:
                detected_subcat = "docker_daemon_error"
                record.error_message = "Cannot connect to Docker daemon: daemon not running or socket unavailable"
            elif m_docker_run:
                detected_subcat = "docker_run_step_error"
                code = m_docker_run.group(1) or m_docker_run.group(2) or m_docker_run.group(3)
                record.error_message = f"Container build command failed with exit code {code}"
            elif m_docker_solve:
                detected_subcat = "docker_buildkit_solve_error"
                record.error_message = f"Docker BuildKit solve failure: {m_docker_solve.group(1).strip()}"
            else:
                detected_subcat = "docker_build_failure"
                record.error_message = "Docker build command failed with non-zero exit code"

            record.error_type = detected_subcat
            for step in step_sequence:
                if any(kw in step.lower() for kw in ("docker", "container", "build image", "build container")):
                    failed_step = step
                    break
            if not failed_step:
                for step in step_sequence:
                    if "build" in step.lower():
                        failed_step = step
                        break
            if not failed_step:
                failed_step = "Build Container Image"

            evidence_lines = docker_error_lines if docker_error_lines else [record.error_message]
            confidence = 1.0 if has_docker_pattern else 0.85

    # -------------------------------------------------------------
    # (E) Check for Generic Runtime Python Exception (outside pytest/syntax)
    # -------------------------------------------------------------
    if not detected_class:
        for etype, pattern in _SYNTAX_ERROR_PATTERNS:
            pass  # Already checked above
        for etype, pattern in _GENERIC_EXCEPTION_PATTERNS:
            m_exc = pattern.search(text)
            if m_exc:
                detected_class = "runtime_error"
                detected_subcat = etype
                record.error_type = etype
                record.error_message = (m_exc.group(1) or "").strip()
                record.matched_line = m_exc.group(0).strip()
                break

        if detected_class == "runtime_error":
            m_tb_file = _TRACEBACK_FILE_RE.search(clean_text)
            if m_tb_file and m_tb_file.group(1) != "<string>":
                record.file_path = m_tb_file.group(1)
                record.line_number = int(m_tb_file.group(2))

            for step in reversed(step_sequence):
                if not _is_boilerplate(step):
                    failed_step = step
                    break

            confidence = 0.8

    # -------------------------------------------------------------
    # (F) OS-level signal fallback / Unknown
    # Note: GHA platform-level cancellation (##[error]The operation was canceled.)
    # is handled in section (C2) above, not here.
    # Exit codes 137/143 remain ambiguous (OOM kill, SIGTERM from any source)
    # and are kept as unknown with specific subcategory.
    # -------------------------------------------------------------
    if not detected_class:
        if record.exit_code == 137:
            detected_class = "unknown"
            detected_subcat = "process_signal_137"
            record.error_type = "ProcessSignal137"
            record.error_message = "Process terminated with exit code 137 (SIGKILL; ambiguous OOM/external cancellation signal)"
            confidence = 0.4
        elif record.exit_code == 143:
            detected_class = "unknown"
            detected_subcat = "process_signal_143"
            record.error_type = "ProcessSignal143"
            record.error_message = "Process terminated with exit code 143 (SIGTERM; ambiguous runner/system shutdown signal)"
            confidence = 0.4
        elif record.exit_code not in (None, 0) or "##[error]" in text:
            detected_class = "unknown"
            detected_subcat = "unknown_failure"
            record.error_type = "UnknownFailure"
            record.error_message = f"Process completed with exit code {record.exit_code}" if record.exit_code is not None else "Unclassified pipeline failure"
            confidence = 0.5
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if "##[error]" in msg:
                    evidence_lines.append(entry.get("raw", msg))
            if not evidence_lines and parsed_stream:
                for entry in reversed(parsed_stream[-5:]):
                    msg = entry.get("msg", "")
                    if msg:
                        evidence_lines.insert(0, entry.get("raw", msg))
        else:
            detected_class = "unknown"
            detected_subcat = None
            record.error_message = None
            confidence = 0.0

        if not failed_step and step_sequence:
            for step in reversed(step_sequence):
                if not _is_boilerplate(step):
                    failed_step = step
                    break
            if not failed_step:
                failed_step = step_sequence[-1]

    record.failure_class = detected_class
    record.failure_subcategory = detected_subcat
    record.failed_step = failed_step
    record.step_name = failed_step
    record.evidence_lines = evidence_lines
    record.traceback_lines = traceback_lines
    record.parser_confidence = confidence

    # Status
    if record.failure_class in (
        "syntax_error", "dependency_error", "test_failure", "timeout",
        "docker_build_failure", "ci_config_permission_failure", "network_service_failure",
        "runtime_error",
    ):
        record.status = "failure"
    elif record.exit_code is not None:
        record.status = "failure" if record.exit_code != 0 else "success"
    elif "##[error]" in text:
        record.status = "failure"
    elif ("complete job" in text.lower() or any(s.strip().lower() == "complete job" for s in step_sequence)) and not evidence_lines:
        record.status = "success"
    elif (record.tests_passed and record.tests_passed > 0) and (not record.tests_failed or record.tests_failed == 0) and not evidence_lines:
        record.status = "success"
    else:
        record.status = "unknown"

    # Execution path: substantive steps up to and including the failed step
    execution_path: list[str] = []
    for step in step_sequence:
        execution_path.append(step)
        if step == failed_step:
            break
    record.execution_path = execution_path

    # Stage inference
    record.stage = _infer_stage(record.failed_step or record.step_name)

    # Calculate duration of the failed step
    target_step = record.failed_step or record.step_name
    if target_step and target_step in step_entry_map:
        step_lines = step_entry_map[target_step]
        if len(step_lines) >= 2 and step_lines[0].get("ts") and step_lines[-1].get("ts"):
            t0 = _parse_ts(step_lines[0]["ts"])
            t1 = _parse_ts(step_lines[-1]["ts"])
            if t0 and t1:
                delta = round((t1 - t0).total_seconds(), 3)
                record.duration = delta
                record.elapsed_step_seconds = delta

    # Map failure_type for V1 backward compatibility if not provided
    if record.failure_type is None:
        record.failure_type = record.failure_class

    return record


def parse_log_file(
    path: Union[str, Path],
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse a single CI/CD log file and return a LogRecord.
    """
    path = Path(path)
    if run_id is None:
        run_id = path.stem

    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_log_text(text, run_id=run_id, failure_type=failure_type)


def parse_batch(
    directory: Union[str, Path],
    *,
    category: Optional[str] = None,
) -> list[LogRecord]:
    """
    Scan a directory for files, parse each as a LogRecord, and return the list.
    """
    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    files = sorted(
        f for f in dir_path.iterdir()
        if f.is_file()
        and f.suffix.lower() == ".log"
        and not f.name.startswith(".")
    )
    records: list[LogRecord] = []
    for f in files:
        rec = parse_log_file(f, failure_type=category)
        records.append(rec)
    return records


def parse_all_categories(base_dir: Union[str, Path] = "logs") -> dict[str, list[LogRecord]]:
    """
    Scan standard subdirectories (F1, F2, F3, F4, F5) under base_dir and parse all logs.
    """
    base = Path(base_dir)
    results: dict[str, list[LogRecord]] = {}
    for cat in ["F1", "F2", "F3", "F4", "F5"]:
        cat_dir = base / cat
        if not cat_dir.exists() and cat == "F1" and (base / "failure").exists():
            cat_dir = base / "failure"
        if cat_dir.exists() and cat_dir.is_dir():
            results[cat] = parse_batch(cat_dir)
        else:
            results[cat] = []
    return results
