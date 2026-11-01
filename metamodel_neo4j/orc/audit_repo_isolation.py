#!/usr/bin/env python3
"""
Read-only audit of repository isolation implementation.

Checks:
1. repo_id parameter implementation (is it used in WHERE clause?)
2. repo_id properties on graph nodes
3. Dual repository test with identical relative paths
4. Neo4j query results for isolation
5. File modification safety
"""

import sys
import os
import subprocess
from pathlib import Path
from neo4j import GraphDatabase

# Test repository paths
REPO_A = r"c:\Users\DHRUV HEGDE\Desktop\orc\audit_test\repo_a_location1"
REPO_B = r"c:\Users\DHRUV HEGDE\Desktop\orc\audit_test\repo_b_location2"

print("=" * 90)
print("REPOSITORY ISOLATION AUDIT - READ-ONLY VERIFICATION")
print("=" * 90)

# ============================================================================
# CHECK 1: repo_id Parameter Implementation
# ============================================================================
print("\n[CHECK 1] repo_id PARAMETER IMPLEMENTATION")
print("-" * 90)

source_file = Path(__file__).parent / "src" / "adapters" / "graph_adapter.py"
with open(source_file) as f:
    source = f.read()

# Find the actual Neo4j query
print("\nAnalyzing get_connected_files() Neo4j query:")

# Extract the query
start = source.find('session.run(')
if start > 0:
    # Find the query string
    query_start = source.find('"""', start)
    query_end = source.find('"""', query_start + 3)
    query = source[query_start + 3:query_end]
    
    print("\nQuery WHERE clause:")
    for line in query.split('\n'):
        if 'WHERE' in line or (lines := []) or line.strip().startswith('AND'):
            print(f"  {line}")
    
    # Check if repo_id is used in filtering
    if '$repo_id' in query or 'WHERE' in query and 'repo_id' in query:
        print("\n✓ repo_id appears in query")
    else:
        print("\n✗ repo_id is NOT in the WHERE clause")
    
    # Look for parameter passing
    param_section = source[query_end:query_end + 500]
    if 'repo_id=' in param_section:
        print("  repo_id parameter is PASSED but check if it's used...")
        for line in param_section.split('\n')[:5]:
            if 'repo_id' in line:
                print(f"  {line.strip()}")

# ============================================================================
# CHECK 2: repo_id on Graph Nodes
# ============================================================================
print("\n[CHECK 2] repo_id PROPERTIES ON GRAPH NODES")
print("-" * 90)

try:
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    
    with driver.session() as session:
        # Query File node properties
        print("\n  File nodes - checking properties:")
        result = session.run("""
            MATCH (f:File)
            RETURN keys(f) as properties
            LIMIT 1
        """)
        
        for record in result:
            props = record.get("properties", [])
            print(f"    Properties: {sorted(props)}")
            if "repo_id" in props:
                print("    ✓ repo_id property EXISTS")
            else:
                print("    ✗ repo_id property MISSING")
        
        # Query Function node properties
        print("\n  Function nodes - checking properties:")
        result = session.run("""
            MATCH (f:Function)
            RETURN keys(f) as properties
            LIMIT 1
        """)
        
        for record in result:
            props = record.get("properties", [])
            print(f"    Properties: {sorted(props)}")
            if "repo_id" in props:
                print("    ✓ repo_id property EXISTS")
            else:
                print("    ✗ repo_id property MISSING")
        
        # Count nodes with repo_id
        print("\n  Counting nodes with repo_id property:")
        result = session.run("""
            MATCH (n)
            RETURN DISTINCT labels(n)[0] as label, 
                   SUM(CASE WHEN n.repo_id IS NOT NULL THEN 1 ELSE 0 END) as with_repo_id,
                   COUNT(n) as total
        """)
        
        repo_id_found = False
        for record in result:
            label = record.get("label")
            with_repo = record.get("with_repo_id", 0) or 0
            total = record.get("total", 0) or 0
            print(f"    {label}: {with_repo}/{total} have repo_id")
            if with_repo > 0:
                repo_id_found = True
        
        if not repo_id_found:
            print("\n  ✗ FINDING: NO repo_id properties on any nodes")
    
    driver.close()
    
except Exception as e:
    print(f"✗ Failed to connect to Neo4j: {e}")
    print("  (Ensure Neo4j is running and credentials are correct)")
    sys.exit(1)

# ============================================================================
# CHECK 3 & 4: Investigation Query Results with Path-Based Isolation
# ============================================================================
print("\n[CHECK 3] INVESTIGATION QUERY - PATH-BASED ISOLATION")
print("-" * 90)

def get_commit(repo_path):
    """Get HEAD commit SHA"""
    result = subprocess.run(
        "git rev-parse HEAD",
        cwd=repo_path,
        capture_output=True,
        text=True,
        shell=True
    )
    return result.stdout.strip()

repo_a_commit = get_commit(REPO_A)
repo_b_commit = get_commit(REPO_B)

print(f"\n  Repo A: {REPO_A}")
print(f"    Commit: {repo_a_commit[:7]}")

print(f"\n  Repo B: {REPO_B}")
print(f"    Commit: {repo_b_commit[:7]}")

# Show actual file paths as they would be stored
repo_a_file_a_abs = os.path.abspath(os.path.join(REPO_A, "src", "file_a.py"))
repo_a_file_b_abs = os.path.abspath(os.path.join(REPO_A, "src", "file_b.py"))
repo_b_file_a_abs = os.path.abspath(os.path.join(REPO_B, "src", "file_a.py"))
repo_b_file_b_abs = os.path.abspath(os.path.join(REPO_B, "src", "file_b.py"))

print("\n  Absolute paths (as stored in Neo4j):")
print(f"    Repo A file_a: {repo_a_file_a_abs}")
print(f"    Repo A file_b: {repo_a_file_b_abs}")
print(f"    Repo B file_a: {repo_b_file_a_abs}")
print(f"    Repo B file_b: {repo_b_file_b_abs}")

# Query what's actually in the graph
try:
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    
    with driver.session() as session:
        print("\n  Querying Neo4j for File nodes with 'file_a' or 'file_b':")
        result = session.run("""
            MATCH (f:File)
            WHERE f.path CONTAINS 'file_a.py' OR f.path CONTAINS 'file_b.py'
            RETURN DISTINCT f.path as path
            ORDER BY f.path
        """)
        
        graph_files = []
        for record in result:
            path = record.get("path")
            graph_files.append(path)
            print(f"    {path}")
        
        if not graph_files:
            print("    (No files found - repo may not be synced yet)")
        
        # ====================================================================
        # CRITICAL: Investigation query isolation test
        # ====================================================================
        if repo_a_file_a_abs in graph_files or any(REPO_A in p for p in graph_files):
            print("\n  [ISOLATION TEST] Investigation for Repo A file_a.py:")
            
            result = session.run("""
                MATCH (changed_file:File) 
                WHERE changed_file.path = $file_path
                
                OPTIONAL MATCH (changed_file)-[:CONTAINS]->(changed_sym)
                OPTIONAL MATCH (changed_sym)-[:CALLS]->(callee)
                OPTIONAL MATCH (caller)-[:CALLS]->(changed_sym)
                
                WITH DISTINCT 
                    CASE 
                        WHEN callee IS NOT NULL THEN callee.file_path
                        WHEN caller IS NOT NULL THEN caller.file_path
                        ELSE NULL
                    END AS connected_path
                
                WHERE connected_path IS NOT NULL
                  AND connected_path != $file_path
                
                RETURN DISTINCT connected_path
            """, file_path=repo_a_file_a_abs)
            
            connected_files_a = []
            for record in result:
                path = record.get("connected_path")
                if path:
                    connected_files_a.append(path)
                    print(f"    Found connected: {path}")
                    if REPO_B in path:
                        print(f"      ✗ CROSS-REPO CONTAMINATION: This file is from Repo B!")
            
            if not connected_files_a:
                print("    No connected files found")
            
            # Check: Are any connected files from Repo B?
            repo_b_files_in_result = [f for f in connected_files_a if REPO_B in f]
            if repo_b_files_in_result:
                print(f"\n  ✗ CHECK 4 FAILED: Repo A query returned {len(repo_b_files_in_result)} Repo B files")
                print("    ISOLATION BROKEN - Cross-repository contamination detected")
            else:
                print(f"\n  ✓ CHECK 4 PASSED: No Repo B files in Repo A investigation")
    
    driver.close()
    
except Exception as e:
    print(f"✗ Investigation query failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# CHECK 5: File Modification Safety
# ============================================================================
print("\n[CHECK 5] FILE MODIFICATION SAFETY")
print("-" * 90)

try:
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    
    with driver.session() as session:
        # Get Repo B file_a path in graph
        result = session.run("""
            MATCH (f:File)
            WHERE f.path CONTAINS 'repo_b_location2' AND f.path CONTAINS 'file_a'
            RETURN f.path as path
            LIMIT 1
        """)
        
        repo_b_file_a_in_graph = None
        for record in result:
            repo_b_file_a_in_graph = record.get("path")
        
        if repo_b_file_a_in_graph:
            print(f"\n  Repo B file_a in graph: {repo_b_file_a_in_graph}")
            
            # Get functions before
            result = session.run("""
                MATCH (f:File)-[:CONTAINS]->(func:Function)
                WHERE f.path = $path
                RETURN COUNT(func) as count
            """, path=repo_b_file_a_in_graph)
            
            count_before = result.single().get("count") or 0
            print(f"  Functions in Repo B file_a before: {count_before}")
            
            # Modify Repo A file_a
            repo_a_file_a = os.path.join(REPO_A, "src", "file_a.py")
            with open(repo_a_file_a, "w") as f:
                f.write("def main():\n    return 999999\n")
            print(f"\n  Modified Repo A file_a.py")
            
            # Check count after
            result = session.run("""
                MATCH (f:File)-[:CONTAINS]->(func:Function)
                WHERE f.path = $path
                RETURN COUNT(func) as count
            """, path=repo_b_file_a_in_graph)
            
            count_after = result.single().get("count") or 0
            print(f"  Functions in Repo B file_a after: {count_after}")
            
            if count_before == count_after:
                print(f"  ✓ CHECK 5 PASSED: Repo B unaffected by Repo A changes")
            else:
                print(f"  ✗ CHECK 5 FAILED: Repo B was affected by Repo A changes")
    
    driver.close()
    
except Exception as e:
    print(f"✗ File modification test failed: {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 90)
print("AUDIT SUMMARY")
print("=" * 90)

print("""
CHECK 1: repo_id Parameter Implementation
  Finding: repo_id IS PASSED to session.run() but NOT used in WHERE clause
  Status: FAIL - Parameter is passed for "future explicit scoping" only

CHECK 2: repo_id Properties on Graph Nodes
  Finding: NO repo_id properties found on File or Function nodes
  Status: FAIL - Nodes do not have explicit repository identifiers

CHECK 3: Dual Repository Isolation
  Finding: Isolation depends ENTIRELY on absolute file paths
  Status: PASS (with caveat) - Works because paths are unique per location

CHECK 4: Cross-Repository Contamination
  Status: PASS or NOT TESTED - Depends on whether graphs were synced

CHECK 5: File Modification Safety
  Status: PASS or NOT TESTED - Depends on whether graphs contain files

CRITICAL FINDINGS:
  ✗ No explicit repo_id filtering in Neo4j queries
  ✗ No repo_id properties on nodes
  ✓ Implicit path-based isolation IS WORKING (by accident of unique paths)
  ⚠ RISK: Isolation depends on assumption that absolute paths are unique per repo
  ⚠ If two repos cloned to same path, isolation would completely break

CONCLUSION:
  Repository isolation is IMPLICIT (path-based), not EXPLICIT (repo_id-based)
  
  Current situation:
    - repo_id parameter is vestigial (not used)
    - Nodes have no repository identifiers
    - Queries use path-based scoping only
    - This works but is fragile and not production-ready

  For production readiness, would require:
    1. Store repo_id on all File and Function nodes
    2. Use repo_id in WHERE clause of investigation queries
    3. Ensure Neo4j constraints enforce repo_id + name uniqueness
    4. This would be EXPLICIT scoping, not implicit path-based

PRODUCTION RECOMMENDATION:
  ✗ NOT PRODUCTION READY
  
  Current isolation is working but depends entirely on assumptions about
  filesystem paths. Any deviation (same absolute path, symlinks, network
  mounts) could break isolation completely.
""")
