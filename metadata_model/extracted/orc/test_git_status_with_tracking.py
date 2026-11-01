#!/usr/bin/env python3
"""Test git status with tracked files and reflog issues."""
import subprocess
import os
import tempfile
import shutil

graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'

print("=== Test 1: git status on entire working tree ===")
result = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
if result.returncode == 0:
    print(f"Success: {result.stdout if result.stdout else '(clean)'}")
else:
    print(f"Error: {result.stderr}")

print("\n=== Test 2: git diff with remote ===" )
result = subprocess.run(
    ["git", "diff", "origin/master..HEAD"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")
else:
    lines = result.stdout.split('\n')[:10]
    for line in lines:
        print(f"  {line}")

print("\n=== Test 3: Simulate previous checkout state ===")
# Check if we can see what commit was previously checked out
result = subprocess.run(
    ["git", "reflog"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print("Recent reflog entries:")
for line in result.stdout.split('\n')[:5]:
    if line.strip():
        print(f"  {line}")

print("\n=== Test 4: Check for dangling refs ===")
result = subprocess.run(
    ["git", "fsck", "--lost-found"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
if result.stdout.strip():
    print(f"Fsck output:\n{result.stdout[:500]}")
else:
    print("No issues found")

print("\n=== Test 5: git status with -vvv (verbose) for detailed error ===")
result = subprocess.run(
    ["git", "status", "-v", "--porcelain"],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print(f"Stderr: {result.stderr}")
