"""Canonical log normalizer used by the Capstone Module II log models.

Strips CI boilerplate, anonymizes scenario identifiers, and replaces
high-cardinality values (hashes, ids, paths, timestamps) with constant
placeholders, while leaving any line that carries an error cue untouched so
failure signal is preserved.

Extracted verbatim from preprocess_and_cache.py (LogNormalizer) in the capstone
repo. Standard library only.

Usage:
    from log_normalizer import LogNormalizer
    clean = LogNormalizer().normalize(raw_log_text)
"""
import re
from typing import List


# Canonical replacement patterns (ordered by specificity)
CANONICAL_PATTERNS = [
    # SHA hashes (40+ hex chars, git shas, etc.)
    (re.compile(r'\b[0-9a-f]{40,}\b'), "<SHA>"),
    # SHA256 (64 hex chars)
    (re.compile(r'\b[0-9a-f]{64}\b'), "<SHA256>"),
    # MD5 (32 hex chars)
    (re.compile(r'\b[0-9a-f]{32}\b'), "<MD5>"),
    # UUIDs
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE), "<UUID>"),
    # IPv4 addresses
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "<IP>"),
    # IPv6 addresses (simplified)
    (re.compile(r'\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b', re.IGNORECASE), "<IPv6>"),
    # MAC addresses
    (re.compile(r'\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b', re.IGNORECASE), "<MAC>"),
    # Hex numbers (0x prefix, 8+ hex chars)
    (re.compile(r'\b0x[0-9a-f]{8,}\b', re.IGNORECASE), "<HEX>"),
    # Hex numbers (bare, 8+ hex chars, not part of word)
    (re.compile(r'(?<![0-9a-f])[0-9a-f]{8,}(?![0-9a-f])', re.IGNORECASE), "<HEX>"),
    # Docker image digests (sha256:...)
    (re.compile(r'sha256:[0-9a-f]{64}'), "sha256:<SHA256>"),
    # File paths (Unix-style, 3+ segments)
    (re.compile(r'(?:/[^/\s]+){3,}'), "<PATH>"),
    # File paths (Windows-style)
    (re.compile(r'(?:[A-Za-z]:(?:\\[^\\\s]+){2,})|(?:\\\\[^\\\s]+(?:\\[^\\\s]+){2,})'), "<WINPATH>"),
    # URLs
    (re.compile(r'https?://[^\s]+'), "<URL>"),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "<EMAIL>"),
    # Version numbers (semver-like)
    (re.compile(r'\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\b'), "<VERSION>"),
    # Timestamps (ISO-like)
    (re.compile(r'\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b'), "<TIMESTAMP>"),
    # Long numbers (10+ digits, likely IDs/timestamps)
    (re.compile(r'\b\d{10,}\b'), "<LONGNUM>"),
    # Kubernetes resource names (namespace/name)
    (re.compile(r'\b[a-z0-9-]+/[a-z0-9-]+\b'), "<K8S_RES>"),
]

# Boilerplate stripped before tokenization so the model cannot memorize template
# prefixes (runner label, job step, timestamp placeholder, ANSI color codes).
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
CARET_ESCAPE = re.compile(r'\^\[\[[0-9;]*m')
BOILERPLATE_PATTERNS = [
    # The runner prefix is "ci_job\t<step name>\t". Step names are written by
    # the scenario generator ("Execute F6 Scenario", "Build Container Image")
    # and leak the family, so the whole prefix is removed first.
    re.compile(r'^\s*ci_job\t[^\t]*\t', re.MULTILINE),
    ANSI_ESCAPE,
    CARET_ESCAPE,
    re.compile(r'\[TIMESTAMP\]', re.IGNORECASE),
    re.compile(r'<TIMESTAMP>', re.IGNORECASE),
    re.compile(r'\bci_job\b', re.IGNORECASE),
    re.compile(r'\bCheckout\b', re.IGNORECASE),
    re.compile(r'Set up job', re.IGNORECASE),
    re.compile(r'\[command\]', re.IGNORECASE),
    re.compile(r'^\s*##\[(?:section|group|endgroup|command)\].*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*(?:Current runner version|Runner Image|Image Release|Included Software|'
               r'Operating System|Runner\.Worker|Prepare all required actions|'
               r'Download action repository).*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*(?:Starting|Finishing):\s.*$', re.MULTILINE | re.IGNORECASE),
    # GitHub Actions git checkout/post-job dumps. These lines are identical in
    # every family and were the top gradient-attribution tokens (A4 failure).
    re.compile(r'^.*/usr/bin/git\b.*$', re.MULTILINE),
    re.compile(r'^.*\bgit version \d+\.\d+.*$', re.MULTILINE),
    re.compile(r'^.*\bSyncing repository:.*$', re.MULTILINE),
    re.compile(r'^.*\bTemporarily overriding HOME=.*$', re.MULTILINE),
    re.compile(r'^.*Adding repository directory to the temporary git global config.*$',
               re.MULTILINE),
    re.compile(r'^.*\bPost job cleanup\..*$', re.MULTILINE),
    re.compile(r'^.*Cleaning up orphan processes.*$', re.MULTILINE),
    re.compile(r'^.*\bNode (?:20|24) is being deprecated\b.*$', re.MULTILINE),
    re.compile(r'^.*##\[warning\]Node\.js 20 is deprecated\b.*$', re.MULTILINE),
    # The Docker Buildx setup step exists only in the docker-build family.
    # Substring match: buildx is often glued to a container name
    # (buildx_buildkit_builder-...), where \b never matches.
    re.compile(r'^.*buildx.*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'\.pytest_cache\b'),
    # ##[group] markers appear after the runner prefix, so anchor anywhere.
    re.compile(r'^.*##\[(?:section|group|endgroup|command)\].*$', re.MULTILINE),
    re.compile('﻿'),  # UTF-8 BOM
    re.compile('ï»¿'),  # UTF-8 BOM bytes decoded as latin-1/cp1252
]

# Scenario-identifying identifiers (label leakage documented in
# work_data/leakage_evidence.json). Values are anonymous placeholders so the
# model keeps a constant token instead of a family-correlated name.
SCENARIO_PATTERNS = [
    # Repository / image names.
    (re.compile(r'\b[\w\-]*error[\w\-]*repo\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\blog[-_]generation\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bsynthetic[-_][\w\-]+', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bscenario[-_][\w\-]+', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\brunner-images\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bDhruvHegde\b', re.IGNORECASE), '<USER>'),
    # Branch names carry the scenario ("feature/f3-test-failures") and, for
    # green runs, the outcome ("feature/success").
    (re.compile(r'\bfeature/[\w./\-]+'), '<BRANCH>'),
    # Family IDs and scenario variables (F6, F6_REQUIRED_TOKEN, SCENARIO_ID).
    (re.compile(r'\b[fF][1-7][_\-][A-Za-z0-9_\-]+'), '<SCENARIO_VAR>'),
    (re.compile(r'\bF[1-7]\b'), '<SCENARIO>'),
    (re.compile(r'(?<![A-Za-z0-9])scenarios?(?![A-Za-z0-9])', re.IGNORECASE),
     '<SCENARIO>'),
    # Pytest files and functions. Applied longest-first so ".py" is consumed
    # by the file rule, and never matches the Python exception class names.
    (re.compile(r'\b[A-Za-z0-9_]*test_[A-Za-z0-9_]+\.py\b'), '<TEST_FILE>'),
    (re.compile(r'\btest_[A-Za-z0-9_]+\b'), '<TEST_FUNC>'),
]

# Error-preserving patterns (DO NOT canonicalize - these carry failure signal)
ERROR_PATTERNS = [
    r'error', r'failed', r'failure', r'exception', r'traceback',
    r'assertionerror', r'attributeerror', r'filenotfounderror', r'indexerror',
    r'keyerror', r'typeerror', r'valueerror', r'zerodivisionerror',
    r'syntaxerror', r'importError', r'modulenotfounderror',
    r'permission denied', r'connection refused', r'timeout',
    r'out of memory', r'oom', r'killed', r'segfault',
    r'no space left', r'disk full', r'network.*unreachable',
    r'exit code', r'returned non-zero', r'command failed', r'fatal:',
    r'\bhttp[/ ]?\d?\.?\d?\s*[45]\d{2}\b', r'status code\s*[45]\d{2}',
    r'npm err!', r'could not resolve', r'permission denied',
]

class LogNormalizer:
    """Applies canonical token replacement while preserving error semantics."""

    def __init__(self):
        self.patterns = CANONICAL_PATTERNS
        self.error_keywords = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]

    def normalize(self, text: str) -> str:
        """Apply boilerplate scrubbing and canonical replacements to log text."""
        # Scrub template markers on every line, including error lines, so the
        # model cannot key on the runner prefix or color codes.
        for pattern in BOILERPLATE_PATTERNS:
            text = pattern.sub(' ', text)

        # Anonymize scenario identifiers on every line, including error lines.
        for pattern, replacement in SCENARIO_PATTERNS:
            text = pattern.sub(replacement, text)

        # Protect error-bearing lines from high-cardinality ID replacement.
        lines = text.split('\n')
        protected_lines = set()

        for i, line in enumerate(lines):
            for pattern in self.error_keywords:
                if pattern.search(line):
                    protected_lines.add(i)
                    break

        # Apply canonical replacements to non-protected lines
        normalized_lines = []
        for i, line in enumerate(lines):
            if i in protected_lines:
                normalized_lines.append(line)
            else:
                normalized_line = line
                for pattern, replacement in self.patterns:
                    normalized_line = pattern.sub(replacement, normalized_line)
                normalized_lines.append(normalized_line)

        return '\n'.join(normalized_lines)

    def normalize_batch(self, texts: List[str]) -> List[str]:
        """Normalize a batch of texts."""
        return [self.normalize(t) for t in texts]


_default = LogNormalizer()


def normalize_log(text: str) -> str:
    """Normalize one log snapshot with the shared default normalizer."""
    return _default.normalize(text)


if __name__ == "__main__":
    n = LogNormalizer()
    # Error-bearing lines are preserved verbatim.
    assert n.normalize("KeyError: 'missing'") == "KeyError: 'missing'"
    # Runner prefix and scenario identifiers are scrubbed.
    out = n.normalize("ci_job\tBuild Container Image\tERROR: boom")
    assert "ci_job" not in out and "ERROR: boom" in out, out
    out = n.normalize("on feature/f3-test-failures at test_rate_limit_exceeded")
    assert "<BRANCH>" in out and "<TEST_FUNC>" in out and "f3" not in out, out
    # High-cardinality ids on non-error lines are canonicalized.
    out = n.normalize("commit 4f9a1c2b8d3e5f6a7b8c9d0e1f2a3b4c5d6e7f80")
    assert "<SHA>" in out, out
    # BOM bytes (real and mojibake) are removed.
    assert "\ufeff" not in n.normalize("a\ufeffb")
    assert "ï»¿" not in n.normalize("aï»¿b")
    print("log_normalizer.py self-check: pass")
