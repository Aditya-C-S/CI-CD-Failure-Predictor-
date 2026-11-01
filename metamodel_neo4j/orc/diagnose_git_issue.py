#!/usr/bin/env python3
"""Diagnose the graph cache git issue."""
import subprocess
import os
import sys

cwd = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'

print(f"Working directory: {cwd}")
print(f"Directory exists: {os.path.isdir(cwd)}")
print()

# Check git remote URL
print("=== Git Remote Configuration ===")
result = subprocess.run('git config remote.origin.url', cwd=cwd, shell=True, capture_output=True, text=True)
print(f"Git remote URL: {result.stdout.strip()}")
print()

# Check current HEAD
print("=== Current Commit ===")
result = subprocess.run('git rev-parse HEAD', cwd=cwd, shell=True, capture_output=True, text=True)
print(f"HEAD: {result.stdout.strip()}")
print()

# Try git status
print("=== Git Status ===")
result = subprocess.run('git status', cwd=cwd, shell=True, capture_output=True, text=True)
print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print(f"Stderr:\n{result.stderr}")
else:
    print(f"Stdout:\n{result.stdout}")
print()

# Try git ls-files
print("=== Git LS-Files ===")
result = subprocess.run('git ls-files | head -5', cwd=cwd, shell=True, capture_output=True, text=True)
print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print(f"Stderr:\n{result.stderr}")
else:
    print(f"Files:\n{result.stdout}")
print()

# Check git config
print("=== Git Config ===")
result = subprocess.run('git config --local --list', cwd=cwd, shell=True, capture_output=True, text=True)
print(f"Config:\n{result.stdout}")
