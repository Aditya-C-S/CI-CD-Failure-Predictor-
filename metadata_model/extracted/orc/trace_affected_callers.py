#!/usr/bin/env python3
"""Trace where affected_caller_files come from - this is the SECOND check_working_tree_clean call."""
import sys
import subprocess
import os

sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')

from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient

graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'
base_sha = "b55166ab666eaf439a7d37e93b583d7f0ad4f562"
target_sha = "0a8ef71ada39cf54513f0b9741ce480db1a6d1ff"
repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"

print("=== Step 1: Get diff and files_to_parse ===")

result = subprocess.run(
    ['git', 'diff', '--name-status', '-M', f'{base_sha}..{target_sha}'],
    cwd=graph_cache,
    capture_output=True,
    text=True,
)

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

# Files to re-parse (must exist in target tree) - from line 123-126
files_to_parse = [
    f for f in (added + modified + [new for _, new in renamed])
    if os.path.exists(os.path.join(graph_cache, f))
]

print(f"files_to_parse: {files_to_parse}")

print("\n=== Step 2: Initialize Extractor ===")
extractor = Extractor(repo_id=repo_id)
extractor.root_dir = os.path.abspath(graph_cache)
print(f"Extractor.root_dir: {extractor.root_dir}")

print("\n=== Step 3: Build changed_file_paths (absolute paths) ===")
changed_file_paths = []
changed_file_ids = []
changed_rel_paths = []

for file_name in (added + modified + deleted + [old for old, _ in renamed] + [new for _, new in renamed]):
    norm_rel = file_name.replace("\\", "/")
    changed_rel_paths.append(norm_rel)
    fp = os.path.normpath(os.path.join(graph_cache, file_name))
    changed_file_paths.append(fp)
    changed_file_ids.append(f"file:{fp}")
    if repo_id:
        changed_file_ids.append(f"repo:{repo_id}:file:{norm_rel}")
    raw_fp = os.path.join(graph_cache, file_name)
    if raw_fp != fp:
        changed_file_paths.append(raw_fp)
        changed_file_ids.append(f"file:{raw_fp}")

print(f"\nchanged_file_paths (absolute):")
for p in changed_file_paths:
    print(f"  {p}")

print(f"\nchanged_rel_paths (for IDs):")
for p in changed_rel_paths:
    print(f"  {p}")

print("\n=== Step 4: Get all nodes and edges from Neo4j ===")
print("(Skipping actual Neo4j query - would need real DB connection)")
print("Assuming: old_nodes and old_edges retrieved successfully")

affected_caller_files = set()  # This would be populated by queries

print(f"\naffected_caller_files (after DB queries): {affected_caller_files}")

print("\n=== Step 5: Build all_parsed_paths for SECOND check_working_tree_clean (line 266-267) ===")

# This is line 266-268 from diff_agent.py
all_parsed_paths = list(dict.fromkeys(
    files_to_parse + [os.path.relpath(p, graph_cache).replace("\\", "/") for p in affected_caller_files]
))

print(f"all_parsed_paths: {all_parsed_paths}")

print("\n=== Step 6: What would happen if affected_caller_files had an absolute source repo path? ===")

# Simulate a bad scenario
affected_caller_files_bad = {r'C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe\Tic-Tac-Toe.py'}
print(f"Simulated affected_caller_files (with absolute source path): {affected_caller_files_bad}")

all_parsed_paths_bad = list(dict.fromkeys(
    files_to_parse + [os.path.relpath(p, graph_cache).replace("\\", "/") for p in affected_caller_files_bad]
))
print(f"all_parsed_paths (result): {all_parsed_paths_bad}")

# Now simulate the path transformation in check_working_tree_clean
print("\n=== Step 7: Simulate check_working_tree_clean with bad paths ===")
for fp in all_parsed_paths_bad:
    joined = os.path.join(graph_cache, fp)
    print(f"Input: {repr(fp)}")
    print(f"  os.path.join(graph_cache, fp) -> {repr(joined)}")
    rel = os.path.relpath(joined, graph_cache)
    print(f"  os.path.relpath() -> {repr(rel)}")
    print()
