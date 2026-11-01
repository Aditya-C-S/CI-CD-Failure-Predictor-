#!/usr/bin/env python3
"""Verify graph engine import and check working tree clean implementation."""
import sys
sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')

from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import check_working_tree_clean
import inspect

print("[OK] Successfully imported from graph-doc-gen-main")
print(f"  update_graph_from_diff module: {update_graph_from_diff.__module__}")
print(f"  check_working_tree_clean module: {check_working_tree_clean.__module__}")

# Show the check_working_tree_clean implementation
print("\n=== check_working_tree_clean source (first 40 lines) ===")
source = inspect.getsource(check_working_tree_clean)
lines = source.split('\n')
for i, line in enumerate(lines[:40], 1):
    print("[{:3d}] {}".format(i, line))

# Find where it's called in update_graph_from_diff
print("\n=== Finding check_working_tree_clean calls in update_graph_from_diff ===")
source = inspect.getsource(update_graph_from_diff)
for i, line in enumerate(source.split('\n'), 1):
    if 'check_working_tree_clean' in line:
        print("Line {:3d}: {}".format(i, line.strip()))
