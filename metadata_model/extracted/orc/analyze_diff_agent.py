#!/usr/bin/env python3
"""Analyze diff_agent to find root cause."""
import sys
sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')

from maintenance.diff_agent import update_graph_from_diff
import inspect

# Get the specific lines around the check_working_tree_clean call
source = inspect.getsource(update_graph_from_diff)
lines = source.split('\n')

print("=== Context around first check_working_tree_clean call (around line 134) ===")
for i in range(100, 150):
    if i < len(lines):
        marker = " >>> " if i == 133 else "     "
        print("[{}:{:3d}] {}".format(marker, i+1, lines[i]))

print("\n=== Root cause analysis ===")
print("When diff_agent.py calls check_working_tree_clean(dir_path, file_paths=all_changed_files)")
print("it passes file paths from the diff (added, modified, deleted files).")
print("")
print("In check_working_tree_clean, line 16-17, it does:")
print("  rel = os.path.relpath(os.path.join(cwd, fp), cwd).replace(backslash, forward)")
print("")
print("The problem: os.path.join(cwd, fp) may produce a path outside cwd if:")
print("  1. fp contains '..' or absolute path")
print("  2. The calculation of relpath fails")
print("")
print("Then it passes this to git status with --:")
print("  git status --porcelain -- path1 path2 path3")
print("")
print("Git rejects any path that is outside the repository!")
