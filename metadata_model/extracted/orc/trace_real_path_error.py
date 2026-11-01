#!/usr/bin/env python3
"""Trace the real error - reproduce exact path where '../../../Voice_based' comes from."""
import sys
import inspect
import subprocess
import os

sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')

from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import check_working_tree_clean

print("=== Step 1: Verify Import Paths ===")
print(f"update_graph_from_diff: {inspect.getfile(update_graph_from_diff)}")
print(f"check_working_tree_clean: {inspect.getfile(check_working_tree_clean)}")

print("\n=== Step 2: Show check_working_tree_clean source ===")
source = inspect.getsource(check_working_tree_clean)
lines = source.split('\n')
for i, line in enumerate(lines, 1):
    print("[{:3d}] {}".format(i, line))

print("\n=== Step 3: Show update_graph_from_diff - the failing call ===")
source = inspect.getsource(update_graph_from_diff)
lines = source.split('\n')
# Find the check_working_tree_clean call
for i, line in enumerate(lines, 1):
    if 'check_working_tree_clean' in line:
        # Print context around it (10 lines before, 10 after)
        start = max(0, i - 11)
        end = min(len(lines), i + 10)
        print(f"Found at line {i}:")
        for j in range(start, end):
            marker = " >>> " if j == i-1 else "     "
            print("[{}:{:3d}] {}".format(marker, j+1, lines[j]))
        print()

print("\n=== Step 4: What diff returns for 0a8ef71 vs b55166a ===")
graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'
base_sha = "b55166ab666eaf439a7d37e93b583d7f0ad4f562"
target_sha = "0a8ef71ada39cf54513f0b9741ce480db1a6d1ff"

result = subprocess.run(
    ['git', 'diff', '--name-status', '-M', f'{base_sha}..{target_sha}'],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)

print(f"Git diff output:")
for line in result.stdout.splitlines():
    print(f"  {repr(line)}")

# Parse changed files as diff_agent does
added = []
modified = []
deleted = []
renamed = []

for line in result.stdout.splitlines():
    if not line:
        continue
    parts = line.split('\t')
    status = parts[0]
    if status == 'A':
        added.append(parts[1])
    elif status == 'M':
        modified.append(parts[1])
    elif status == 'D':
        deleted.append(parts[1])
    elif status.startswith('R'):
        old_path, new_path = parts[1], parts[2]
        renamed.append((old_path, new_path))

# Construct all_changed_files exactly as diff_agent does (from line 131)
all_changed_files = list(dict.fromkeys(
    added + modified + deleted + 
    [old for old, _ in renamed] + 
    [new for _, new in renamed]
))

print(f"\nall_changed_files (as diff_agent constructs): {all_changed_files}")

print("\n=== Step 5: Simulate check_working_tree_clean path logic ===")
print(f"cwd for git command: {graph_cache}")
print(f"file_paths argument: {all_changed_files}")

# This is what check_working_tree_clean does at lines 12-18
cmd = ["git", "status", "--porcelain"]
norm_paths = []
for fp in all_changed_files:
    joined = os.path.join(graph_cache, fp)
    rel = os.path.relpath(joined, graph_cache).replace("\\", "/")
    norm_paths.append(rel)
    print(f"  Input fp: {repr(fp)}")
    print(f"    os.path.join({repr(graph_cache)}, {repr(fp)})")
    print(f"    -> {repr(joined)}")
    print(f"    os.path.relpath({repr(joined)}, {repr(graph_cache)})")
    print(f"    -> {repr(rel)}")

cmd.extend(["--"] + norm_paths)

print(f"\n=== Step 6: Run git status with the constructed paths ===")
print(f"Command: {cmd}")
print(f"CWD: {graph_cache}")

result = subprocess.run(
    cmd,
    cwd=graph_cache,
    capture_output=True,
    text=True,
)

print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print(f"STDERR: {result.stderr}")
else:
    print(f"Success: {result.stdout if result.stdout else '(clean)'}")

print("\n=== Step 7: Check what HEAD points to ===")
result = subprocess.run(
    ['git', 'rev-parse', 'HEAD'],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print(f"Graph cache HEAD: {result.stdout.strip()}")
print(f"Target SHA:       {target_sha}")
print(f"Match: {result.stdout.strip() == target_sha}")
