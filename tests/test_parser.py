"""tests/test_parser.py

Unit tests for Parser V2.
Validates structured evidence extraction across error categories and success logs.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.parser.parser_v2 import LogRecord, parse_log_text


class TestParserV2(unittest.TestCase):

    def test_syntax_error_parsing(self):
        sample_syntax_log = (
            "job_test\tRun tests\t2026-10-20T10:00:00Z python app.py\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z   File \"app.py\", line 12\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z     def broken_func(\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z                    ^\n"
            "job_test\tRun tests\t2026-10-20T10:00:01Z SyntaxError: '(' was never closed\n"
            "job_test\tRun tests\t2026-10-20T10:00:02Z ##[error]Process completed with exit code 1.\n"
        )
        record = parse_log_text(sample_syntax_log, run_id="syntax_001")
        self.assertIsInstance(record, LogRecord)
        self.assertEqual(record.status.lower(), "failure")
        self.assertIn("SyntaxError", record.error_type or record.error_message)

    def test_dependency_error_parsing(self):
        sample_dep_log = (
            "build_job\tInstall Dependencies\t2026-10-20T10:00:00Z pip install -r requirements.txt\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:02Z ERROR: Could not find a version that satisfies the requirement non_existent_pkg==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:02Z ERROR: No matching distribution found for non_existent_pkg==99.9.9\n"
            "build_job\tInstall Dependencies\t2026-10-20T10:00:03Z ##[error]Process completed with exit code 1.\n"
        )
        record = parse_log_text(sample_dep_log, run_id="dep_001")
        self.assertEqual(record.status.lower(), "failure")
        self.assertEqual(record.failure_type, "dependency_error")

    def test_success_log_parsing(self):
        sample_success_log = (
            "ci_job\tSetup Python\t2026-10-20T10:00:00Z Installed Python 3.12\n"
            "ci_job\tRun pytest\t2026-10-20T10:00:05Z ===== 15 passed in 0.42s =====\n"
            "ci_job\tPost Run\t2026-10-20T10:00:06Z Complete job name: Python Test Suite\n"
        )
        record = parse_log_text(sample_success_log, run_id="succ_001")
        self.assertEqual(record.status.lower(), "success")


if __name__ == "__main__":
    unittest.main()
