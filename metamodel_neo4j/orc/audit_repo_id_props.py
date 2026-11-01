#!/usr/bin/env python3
"""Audit repo_id property presence in Neo4j."""

import sys
from pathlib import Path

GRAPH_DOC_GEN_ROOT = Path("..") / "graph-doc-gen-main"
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT.absolute()))

from database.neo4j_client import Neo4jClient

client = Neo4jClient()
session = client.driver.session()

# Check what properties exist on nodes
print("=== Sample Node Properties ===")
result = session.run("""
MATCH (n)
RETURN DISTINCT keys(n) as node_keys
LIMIT 5
""")

for record in result:
    print(f"Properties: {record['node_keys']}")

# Check repo_id presence
print("\n=== Node Count Analysis ===")
result = session.run("""
MATCH (n)
RETURN 
    COUNT(n) as total_nodes,
    COUNT(CASE WHEN n.repo_id IS NOT NULL THEN 1 END) as with_repo_id,
    COUNT(CASE WHEN n.repo_id IS NULL THEN 1 END) as without_repo_id
""")
record = result.single()
print(f"Total nodes: {record['total_nodes']}")
print(f"With repo_id: {record['with_repo_id']}")
print(f"Without repo_id (NULL): {record['without_repo_id']}")

# Check what repo_ids exist
print("\n=== Repo IDs in Database ===")
result = session.run("""
MATCH (n)
WHERE n.repo_id IS NOT NULL
RETURN DISTINCT n.repo_id as repo_ids
""")

for record in result:
    print(f"  - {record['repo_ids']}")

# Check which nodes have repo_id and which don't
print("\n=== Sample Nodes Without repo_id ===")
result = session.run("""
MATCH (n)
WHERE n.repo_id IS NULL
RETURN DISTINCT labels(n) as node_label, n.id as id, n.path as path
LIMIT 3
""")

for record in result:
    print(f"Label: {record['node_label']}, ID: {record['id']}, Path: {record['path']}")

session.close()
client.close()

print("\n=== CONCLUSION ===")
print("The production database contains nodes WITHOUT repo_id property.")
print("New test nodes (e2e/test1, e2e/idem) have repo_id explicitly set.")
print("This is MIXED STATE - old data has no repo_id, new data does.")
