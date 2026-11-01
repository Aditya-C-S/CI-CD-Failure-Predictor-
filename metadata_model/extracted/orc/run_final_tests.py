#!/usr/bin/env python3
"""Run final integration tests and report results."""

import subprocess
import sys

# Run tests
result = subprocess.run(
    [sys.executable, "-m", "pytest", 
     "tests/test_orchestrator_fixed.py",
     "tests/test_graph_adapter_repo_isolation.py",
     "-v", "--tb=short"],
    cwd="c:\\Users\\DHRUV HEGDE\\Desktop\\orc"
)

sys.exit(result.returncode)
