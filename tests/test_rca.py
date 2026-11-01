"""tests/test_rca.py

Unit tests for Root Cause Analysis (RCA) Engine and Remediation Advisor.
"""

from __future__ import annotations

import unittest

from src.parser.parser_v2 import parse_log_text
from src.rca.rca_engine import (
    RCAEngine,
    get_default_engine,
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
)
from src.remediation.suggestions import RemediationAdvisor


class TestRCA(unittest.TestCase):

    def setUp(self):
        self.engine = get_default_engine()

    def test_syntax_rca_diagnosis(self):
        syntax_log = (
            "job_test\tRun tests\t2026-10-20T10:00:00Z python app.py\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z   File \"app.py\", line 10\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z     def foo(\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z            ^\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z SyntaxError: '(' was never closed\n"
            "job_test\tRun tests\t2026-10-20T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        record = parse_log_text(syntax_log, run_id="test_syntax")
        report = self.engine.analyze_record(record)
        self.assertEqual(report.causal_category, CAUSAL_CODE_DEFECT)
        self.assertGreater(report.rca_confidence, 0.5)

        remediation = RemediationAdvisor.generate_remediation(report)
        self.assertGreater(len(remediation["recommended_actions"]), 0)
        self.assertGreater(len(remediation["terminal_commands"]), 0)

    def test_dependency_rca_diagnosis(self):
        dep_log = (
            "build_job\tInstall Dependencies\t2026-10-20T10:00:00Z pip install -r requirements.txt\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:02Z ERROR: Could not find a version that satisfies the requirement requests==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:02Z ERROR: No matching distribution found for requests==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        record = parse_log_text(dep_log, run_id="test_dep")
        report = self.engine.analyze_record(record)
        self.assertEqual(report.causal_category, CAUSAL_DEPENDENCY)

        remediation = RemediationAdvisor.generate_remediation(report)
        self.assertIn("pip install", " ".join(remediation["terminal_commands"]))


if __name__ == "__main__":
    unittest.main()
