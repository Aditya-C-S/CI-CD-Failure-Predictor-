#!/usr/bin/env python3
"""Test the fixed graph cache creation."""
import sys
import shutil
import subprocess
import os
import stat
from pathlib import Path

def handle_remove_readonly(func, path, exc_info):
    """Error handler for shutil.rmtree to handle Windows read-only files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\orc')

from src.adapters.graph_adapter import _ensure_graph_working_copy_at_sha, GRAPH_CACHE_ROOT

repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
source_repo_path = r'C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe'
target_sha = "0a8ef71ada39cf54513f0b9741ce480db1a6d1ff"
base_sha = "b55166ab666eaf439a7d37e93b583d7f0ad4f562"

print("=== Setup ===")
print(f"Repo ID: {repo_id}")
print(f"Source repo: {source_repo_path}")
print(f"Target SHA: {target_sha}")
print(f"Graph cache root: {GRAPH_CACHE_ROOT}")

safe_repo_id = repo_id.replace("/", "__")
graph_cache_dir = GRAPH_CACHE_ROOT / safe_repo_id

print(f"\n=== Cleaning old graph cache ===")
if graph_cache_dir.exists():
    print(f"Removing: {graph_cache_dir}")
    shutil.rmtree(graph_cache_dir, onerror=handle_remove_readonly)
else:
    print("No existing graph cache")

print(f"\n=== Creating new graph working copy ===")
try:
    graph_working_copy = _ensure_graph_working_copy_at_sha(repo_id, source_repo_path, target_sha)
    print(f"[OK] Created graph working copy at: {graph_working_copy}")
except Exception as e:
    print(f"[ERROR] Failed: {e}")
    sys.exit(1)

print(f"\n=== Verify remote URL ===")
result = subprocess.run(
    'git remote -v',
    cwd=graph_working_copy,
    shell=True,
    capture_output=True,
    text=True,
)
print(f"Remote configuration:")
for line in result.stdout.splitlines():
    print(f"  {line}")

print(f"\n=== Test git status ===")
result = subprocess.run(
    'git status --porcelain',
    cwd=graph_working_copy,
    shell=True,
    capture_output=True,
    text=True,
)
if result.returncode == 0:
    print(f"[OK] git status succeeded")
else:
    print(f"[ERROR] git status failed: {result.stderr}")

print(f"\n=== Test check_working_tree_clean ===")
sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')
from maintenance.git_utils import check_working_tree_clean

# Get the changed files
result = subprocess.run(
    ['git', 'diff', '--name-status', '-M', f'{base_sha}..{target_sha}'],
    cwd=graph_working_copy,
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

print(f"Changed files: {all_changed_files}")

try:
    check_working_tree_clean(graph_working_copy, file_paths=all_changed_files)
    print(f"[OK] check_working_tree_clean passed")
except Exception as e:
    print(f"[ERROR] check_working_tree_clean failed: {e}")
    sys.exit(1)

print(f"\n=== All tests passed! ===")
