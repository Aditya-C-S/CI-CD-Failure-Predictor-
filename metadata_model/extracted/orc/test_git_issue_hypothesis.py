#!/usr/bin/env python3
"""Test hypothesis: local remote path causes git issues."""
import subprocess
import tempfile
import shutil
import os

# Create a test scenario
source_repo = r'C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe'
graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'

print("=== Test 1: List git objects ===")
result = subprocess.run(
    'git rev-list --count HEAD',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
print(f"Output: {result.stdout.strip()}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")

print("\n=== Test 2: Check if Tic-Tac-Toe.py is in this commit ===")
result = subprocess.run(
    'git ls-tree -r HEAD --name-only | findstr /I "Tic-Tac-Toe"',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
print(f"Output:\n{result.stdout}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")

print("\n=== Test 3: Check file status ===")
result = subprocess.run(
    'git status Tic-Tac-Toe.py',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
print(f"Output: {result.stdout}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")

print("\n=== Test 4: Try git hash-object ===")
tic_tac_toe_path = os.path.join(graph_cache, 'Tic-Tac-Toe.py')
print(f"File exists: {os.path.exists(tic_tac_toe_path)}")
result = subprocess.run(
    f'git hash-object "{tic_tac_toe_path}"',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Return code: {result.returncode}")
print(f"Output: {result.stdout.strip()}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")

print("\n=== Test 5: Try with worktree ===")
result = subprocess.run(
    'git worktree list',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Worktrees: {result.stdout}")
if result.returncode != 0:
    print(f"Error: {result.stderr}")

print("\n=== Test 6: Check remote ===")
result = subprocess.run(
    'git remote -v',
    cwd=graph_cache,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Remotes:\n{result.stdout}")
