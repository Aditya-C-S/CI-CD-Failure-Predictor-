"""Execute real Cypher queries and caller/callee traversal on ingested graph in Neo4j."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add graph-doc-gen-main to path
sys.path.insert(0, str(Path("metadata_model/extracted/graph-doc-gen-main").resolve()))
from database.neo4j_client import Neo4jClient

load_dotenv("metadata_model/extracted/graph-doc-gen-main/.env")

client = Neo4jClient()
print("=" * 60)
print("NEO4J REAL GRAPH QUERIES & RCA TRAVERSAL EXECUTION")
print("=" * 60)

with client.session() as session:
    # Query 1: Total node count & breakdown by label
    res = session.run("MATCH (n) RETURN labels(n) as labels, count(*) as count")
    print("\n[QUERY 1] Node Counts by Label in 'graphdoc':")
    for r in res:
        print(f"  - Labels {r['labels']}: {r['count']}")

    # Query 2: Retrieve all ingested nodes for repo
    res2 = session.run(
        "MATCH (n {repo_id: $repo_id}) RETURN labels(n)[0] as type, n.id as id, n.name as name",
        repo_id="sample/test-repo"
    )
    print("\n[QUERY 2] Ingested Nodes for 'sample/test-repo':")
    for r in res2:
        print(f"  [{r['type']}] id: {r['id']}, name: {r['name']}")

    # Query 3: Retrieve relationships between nodes
    res3 = session.run(
        """
        MATCH (a {repo_id: $repo_id})-[r]->(b {repo_id: $repo_id})
        RETURN labels(a)[0] as from_type, a.name as from_name, type(r) as rel, labels(b)[0] as to_type, b.name as to_name
        """,
        repo_id="sample/test-repo"
    )
    print("\n[QUERY 3] AST Relationships Extracted:")
    for r in res3:
        print(f"  ({r['from_type']}:{r['from_name']}) -[:{r['rel']}]-> ({r['to_type']}:{r['to_name']})")

    # Query 4: SyncState provenance verification node
    res4 = session.run("MATCH (s:SyncState {repo_id: $repo_id}) RETURN s.target_sha as target_sha, s.status as status", repo_id="sample/test-repo")
    sync = res4.single()
    if sync:
        print(f"\n[QUERY 4] Verified Commit Provenance in Graph: SHA={sync['target_sha'][:10]}..., Status={sync['status']}")

# Query 5: Test Dhruv's affected caller / dependency traversal via Neo4jClient.get_connected_files
sample_utils_path = str(Path("scratch/sample_repo/utils.py").resolve())
print(f"\n[QUERY 5] Affected Caller / RCA Blast Radius Traversal for {sample_utils_path}:")
connected = client.get_connected_files(repo_id="sample/test-repo", file_path=sample_utils_path)
print(f"  Connected / Caller Files Found: {len(connected)}")
for f in connected:
    print(f"  -> {f}")

client.close()
print("\n[SUCCESS] All real graph queries executed successfully against Neo4j 'graphdoc' database!")
