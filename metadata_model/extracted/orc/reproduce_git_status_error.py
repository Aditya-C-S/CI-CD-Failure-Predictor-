#!/usr/bin/env python3
"""Reproduce the exact git status error."""
import sys
import subprocess
import os

sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')

from maintenance.git_utils import check_working_tree_clean

graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'
base = "b55166ab666eaf439a7d37e93b583d7f0ad4f562"
target = "0a8ef71ada39cf54513f0b9741ce480db1a6d1ff"

# Simulate what diff_agent does
print("=== Simulating diff_agent logic ===")
print(f"Graph cache: {graph_cache}")
print(f"Base: {base}")
print(f"Target: {target}")

# Get the diff
result = subprocess.run(
    ["git", "diff", "--name-status", "-M", f"{base}..{target}"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
    check=True,
)

all_changed_files = []
for line in result.stdout.splitlines():
    if not line:
        continue
    parts = line.split('\t')
    status = parts[0]
    if status == 'A':
        all_changed_files.append(parts[1])
    elif status == 'M':
        all_changed_files.append(parts[1])
    elif status == 'D':
        all_changed_files.append(parts[1])
    elif status.startswith('R'):
        old_path, new_path = parts[1], parts[2]
        all_changed_files.append(old_path)
        all_changed_files.append(new_path)

print(f"\n=== All changed files ===")
for f in all_changed_files:
    print(f"  {repr(f)}")

print(f"\n=== Now calling check_working_tree_clean ===")
try:
    check_working_tree_clean(graph_cache, file_paths=all_changed_files)
    print("[OK] check_working_tree_clean passed")
except Exception as e:
    print(f"[ERROR] {type(e).__name__}: {e}")
    
    # Now let's debug what check_working_tree_clean actually does
    print(f"\n=== Debugging check_working_tree_clean logic ===")
    cmd = ["git", "status", "--porcelain"]
    norm_paths = []
    for fp in all_changed_files:
        rel = os.path.relpath(os.path.join(graph_cache, fp), graph_cache).replace("\\", "/")
        norm_paths.append(rel)
        print(f"File: {repr(fp)}")
        print(f"  Joined: {repr(os.path.join(graph_cache, fp))}")
        print(f"  Relative: {repr(rel)}")
    
    cmd.extend(["--"] + norm_paths)
    print(f"\n=== Git command ===")
    print(f"Command: {cmd}")
    print(f"CWD: {graph_cache}")
    
    result = subprocess.run(
        cmd,
        cwd=graph_cache,
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"\n=== Git result ===")
    print(f"Return code: {result.returncode}")
    print(f"Stdout: {repr(result.stdout)}")
    print(f"Stderr: {repr(result.stderr)}")
