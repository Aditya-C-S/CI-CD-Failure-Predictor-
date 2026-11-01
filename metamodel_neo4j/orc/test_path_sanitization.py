#!/usr/bin/env python3
"""Test path sanitization logic."""
import os

graph_cache = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe'
source_repo = r'C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe'

# Simulate a path from Neo4j (from previous run on source repo)
neo4j_absolute_path = r'C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe\Tic-Tac-Toe.py'

print("=== Scenario 1: Path from Neo4j is absolute and points to source repo ===")
print(f"Neo4j path: {neo4j_absolute_path}")
print(f"os.path.exists(): {os.path.exists(neo4j_absolute_path)}")
print()

print("=== Scenario 2: What diff_agent does on line 267 ===")
all_parsed_paths = [os.path.relpath(neo4j_absolute_path, graph_cache).replace("\\", "/")]
print(f"all_parsed_paths after relpath: {all_parsed_paths}")
print()

print("=== Scenario 3: The fix - validate paths before using them ===")

def sanitize_caller_path(caller_path, dir_path, repo_id):
    """
    Validate and sanitize a caller file path from Neo4j.
    
    Returns:
    - The path if valid (relative to dir_path)
    - None if invalid (points outside dir_path or to source repo)
    """
    if not caller_path:
        return None
    
    # Normalize both paths for comparison
    norm_caller = os.path.normpath(os.path.abspath(caller_path))
    norm_dir = os.path.normpath(os.path.abspath(dir_path))
    
    # Check if caller path is within dir_path
    try:
        rel_path = os.path.relpath(norm_caller, norm_dir)
        # If relpath starts with '..', it's outside the directory
        if rel_path.startswith('..'):
            print(f"  Path {caller_path} is OUTSIDE {dir_path}")
            print(f"    Relative path would be: {rel_path}")
            return None
        # Path is valid and inside dir_path
        return rel_path.replace("\\", "/")
    except ValueError:
        # On Windows, relpath raises ValueError if paths are on different drives
        print(f"  Path {caller_path} is on different drive than {dir_path}")
        return None

result = sanitize_caller_path(neo4j_absolute_path, graph_cache, "DhruvHegde/Voice_based-_Tic-Tac-Toe")
print(f"sanitized result: {result}")
print()

print("=== Scenario 4: Valid path from graph cache ===")
valid_neo4j_path = r'C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe\Tic-Tac-Toe.py'
result = sanitize_caller_path(valid_neo4j_path, graph_cache, "DhruvHegde/Voice_based-_Tic-Tac-Toe")
print(f"sanitized result: {result}")
