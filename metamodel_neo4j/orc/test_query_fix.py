#!/usr/bin/env python3
"""
Test and fix the Neo4j investigation query.

Current query fails with: WHERE connected_path IS NOT NULL AND connected_path NOT IN $changed_paths
Error: Invalid input 'NOT'

We need to:
1. Test the original query to see exact error
2. Rewrite it using correct Cypher 5.25 syntax
3. Verify against actual graph
4. Return connected files correctly
"""

import sys
import os
from pathlib import Path

os.environ['PYTHONIOENCODING'] = 'utf-8'

# Setup paths
METADATA_PIPELINE_ROOT = Path(__file__).parent.parent / "Metadata-Pipeline-main"
GRAPH_DOC_GEN_ROOT = Path(__file__).parent.parent / "graph-doc-gen-main"
ORC_ROOT = Path(__file__).parent

sys.path.insert(0, str(METADATA_PIPELINE_ROOT))
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT))
sys.path.insert(0, str(ORC_ROOT))

from database.neo4j_client import Neo4jClient

print("=" * 80)
print("NEO4J QUERY DEBUGGING & FIX")
print("=" * 80)

client = Neo4jClient()

# ============================================================================
# TEST 1: ORIGINAL QUERY (WILL FAIL)
# ============================================================================

print("\n[1] Testing ORIGINAL query (expected to fail)...")

original_query = """
MATCH (changed_file:File) WHERE changed_file.path IN $changed_paths
OPTIONAL MATCH (changed_file)-[:CONTAINS]->(changed_sym)
OPTIONAL MATCH (changed_sym)-[:CALLS]->(callee)
OPTIONAL MATCH (caller)-[:CALLS]->(changed_sym)
WITH DISTINCT coalesce(callee.file_path, caller.file_path) AS connected_path,
       callee, caller
WHERE connected_path IS NOT NULL AND connected_path NOT IN $changed_paths
RETURN connected_path,
       size((coalesce(callee, caller))-[:CALLS]->()) AS out_degree,
       size((()-[:CALLS]->(coalesce(callee, caller)))) AS in_degree
"""

test_changed_paths = [
    r"C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main\code_parser\extractor.py"
]

try:
    with client.session() as session:
        result = session.run(original_query, changed_paths=test_changed_paths)
        records = list(result)
        print(f"  ✓ Query succeeded (unexpected!)")
        print(f"    Found {len(records)} records")
except Exception as e:
    print(f"  ✗ Query failed as expected: {e}")
    error_msg = str(e)
    if "NOT" in error_msg:
        print(f"    Error confirms: NOT operator issue")

# ============================================================================
# TEST 2: SIMPLIFIED QUERY (CHECK NODE STRUCTURE)
# ============================================================================

print("\n[2] Checking actual graph node structure...")

with client.session() as session:
    # Check if File nodes have 'path' or 'file_path' property
    result = session.run("""
        MATCH (f:File) 
        RETURN properties(f) LIMIT 1
    """)
    
    for record in result:
        props = record[0]
        print(f"  File node properties: {list(props.keys())}")

# ============================================================================
# TEST 3: FUNCTION NODES AND THEIR PROPERTIES
# ============================================================================

print("\n[3] Checking Function node properties...")

with client.session() as session:
    result = session.run("""
        MATCH (func:Function)
        RETURN properties(func) LIMIT 1
    """)
    
    for record in result:
        props = record[0]
        print(f"  Function node properties: {list(props.keys())}")

# ============================================================================
# TEST 4: RELATIONSHIP DIRECTIONS
# ============================================================================

print("\n[4] Verifying relationship directions...")

with client.session() as session:
    # Check CONTAINS relationships
    result = session.run("""
        MATCH (src)-[r:CONTAINS]->(tgt)
        RETURN labels(src)[0] as src_type, labels(tgt)[0] as tgt_type, count(*) as count
        LIMIT 5
    """)
    
    print(f"  CONTAINS relationships:")
    for record in result:
        print(f"    {record['src_type']} -[:CONTAINS]-> {record['tgt_type']}: {record['count']}")
    
    # Check CALLS relationships
    result = session.run("""
        MATCH (src)-[r:CALLS]->(tgt)
        RETURN labels(src)[0] as src_type, labels(tgt)[0] as tgt_type, count(*) as count
        LIMIT 5
    """)
    
    print(f"  CALLS relationships:")
    for record in result:
        print(f"    {record['src_type']} -[:CALLS]-> {record['tgt_type']}: {record['count']}")

# ============================================================================
# TEST 5: FIXED QUERY (CYPHER 5.25 COMPATIBLE)
# ============================================================================

print("\n[5] Testing FIXED query (Cypher 5.25 compatible)...")

# The issue: NOT IN needs to be in a proper context
# Fix: Use NONE() or WHERE NOT(...) with proper wrapping
fixed_query = """
MATCH (changed_file:File) 
WHERE changed_file.path IN $changed_paths

OPTIONAL MATCH (changed_file)-[:CONTAINS]->(changed_sym)
OPTIONAL MATCH (changed_sym)-[:CALLS]->(callee)
OPTIONAL MATCH (caller)-[:CALLS]->(changed_sym)

WITH DISTINCT 
    CASE 
        WHEN callee IS NOT NULL THEN callee
        WHEN caller IS NOT NULL THEN caller
        ELSE NULL
    END AS symbol_node,
    CASE 
        WHEN callee IS NOT NULL AND callee.file_path IS NOT NULL THEN callee.file_path
        WHEN caller IS NOT NULL AND caller.file_path IS NOT NULL THEN caller.file_path
        ELSE NULL
    END AS connected_path

WHERE connected_path IS NOT NULL
  AND NOT (connected_path IN $changed_paths)

WITH DISTINCT connected_path, symbol_node

OPTIONAL MATCH (symbol_node)-[:CALLS]->(outgoing)
OPTIONAL MATCH (incoming)-[:CALLS]->(symbol_node)

WITH connected_path, 
     count(DISTINCT outgoing) AS out_degree,
     count(DISTINCT incoming) AS in_degree

RETURN connected_path,
       out_degree,
       in_degree
"""

try:
    with client.session() as session:
        result = session.run(fixed_query, changed_paths=test_changed_paths)
        records = list(result)
        print(f"  ✓ Fixed query succeeded!")
        print(f"    Found {len(records)} connected files")
        for record in records:
            print(f"      - {record['connected_path']}: in_degree={record['in_degree']}, out_degree={record['out_degree']}")
except Exception as e:
    print(f"  ✗ Fixed query failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# TEST 6: ALTERNATIVE FIX (APOC-STYLE, IF NEEDED)
# ============================================================================

print("\n[6] Testing alternative approach (simpler Cypher)...")

alternative_query = """
MATCH (changed_file:File {path: $changed_path})
OPTIONAL MATCH (changed_file)-[:CONTAINS]->(func:Function)
OPTIONAL MATCH (func)-[call:CALLS]->(other_func:Function)

WITH DISTINCT other_func, other_func.file_path AS connected_path

WHERE connected_path IS NOT NULL
  AND connected_path <> $changed_path

WITH connected_path

OPTIONAL MATCH (f:Function)-[:CALLS]->(:Function {file_path: connected_path})
OPTIONAL MATCH (g:Function {file_path: connected_path})-[:CALLS]->()

WITH connected_path,
     count(DISTINCT f) AS in_degree,
     count(DISTINCT g) AS out_degree

RETURN connected_path, in_degree, out_degree
"""

try:
    with client.session() as session:
        for changed_path in test_changed_paths:
            result = session.run(
                alternative_query,
                changed_path=changed_path
            )
            records = list(result)
            print(f"  ✓ Alternative query succeeded for {Path(changed_path).name}!")
            print(f"    Found {len(records)} connected files")
except Exception as e:
    print(f"  ✗ Alternative query failed: {e}")

# ============================================================================
# SUMMARY & RECOMMENDATION
# ============================================================================

print("\n" + "=" * 80)
print("RECOMMENDATION")
print("=" * 80)

print("""
The issue: WHERE connected_path NOT IN $changed_paths after OPTIONAL MATCH scope

Solution options:
1. Use NOT(...IN ...) syntax instead of NOT IN
2. Use CASE statement to handle nulls (most robust)
3. Split into separate queries (simple but less efficient)

Recommended: Option 1 or 2 (preserve single query for efficiency)

The fixed query uses:
  - WHERE NOT (connected_path IN $changed_paths) instead of WHERE ... NOT IN
  - Explicit CASE statement for COALESCE 
  - Separated aggregation from path filtering
  - Compatible with Cypher 5.25
""")

client.close()
print("DONE")
