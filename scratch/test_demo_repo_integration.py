"""Verification script testing Git extraction, AST parsing, and Neo4j ingestion for demo-order-service."""

import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
GRAPH_GEN_ROOT = PROJECT_ROOT / "metadata_model" / "extracted" / "graph-doc-gen-main"
sys.path.insert(0, str(GRAPH_GEN_ROOT))

from src.demo.git_extractor import GitMetadataExtractor
from src.demo.graph_inspector import GraphInspector, _get_extractor_class, _get_neo4j_client_class, get_demo_order_service_path
from src.prediction.metadata_service import MetadataService

def main():
    demo_repo_path = get_demo_order_service_path()
    assert demo_repo_path and demo_repo_path.exists(), f"demo-order-service not found at {demo_repo_path}!"
    repo_id = "demo-order-service"

    print("=== Step 1: Git Repository & Metadata Verification ===")
    assert GitMetadataExtractor.is_git_repo(demo_repo_path), "Not recognized as git repo!"
    commit_info = GitMetadataExtractor.get_commit_info(demo_repo_path)
    print("Commit info:", commit_info)
    assert commit_info.get("available") is True
    assert commit_info.get("commit_sha") is not None

    derived, changed_files = GitMetadataExtractor.extract_diff_metrics(demo_repo_path)
    print(f"Extracted {len(changed_files)} changed files from HEAD: {changed_files}")

    print("\n=== Step 2: AST Parser (Tree-Sitter) Verification ===")
    ExtractorClass = _get_extractor_class()
    assert ExtractorClass is not None, "Extractor class could not be loaded!"
    
    extractor = ExtractorClass(repo_id=repo_id)
    extractor.parse_directory(str(demo_repo_path))
    print(f"Parsed {len(extractor.nodes)} nodes and {len(extractor.edges)} edges.")
    
    # Verify node types
    files = [n for n in extractor.nodes if n["type"] == "File"]
    functions = [n for n in extractor.nodes if n["type"] == "Function"]
    classes = [n for n in extractor.nodes if n["type"] == "Class"]
    calls = [e for e in extractor.edges if e["type"] == "CALLS"]
    contains = [e for e in extractor.edges if e["type"] == "CONTAINS"]

    print(f"Nodes breakdown: {len(files)} Files, {len(functions)} Functions, {len(classes)} Classes")
    print(f"Edges breakdown: {len(contains)} CONTAINS, {len(calls)} CALLS")
    assert len(files) >= 5, "Expected at least 5 files!"
    assert len(functions) >= 8, "Expected at least 8 functions!"
    assert len(calls) >= 5, "Expected at least 5 CALLS edges!"

    print("\nSample CALLS relationships:")
    for c in calls[:5]:
        print(f"  {c['from']} -> {c['to']}")

    print("\n=== Step 3: Neo4j Ingestion (Surgical, isolated to repo_id) ===")
    Neo4jClientClass = _get_neo4j_client_class()
    assert Neo4jClientClass is not None, "Neo4jClient class could not be loaded!"
    client = Neo4jClientClass()
    client.driver.verify_connectivity()

    # Verify existing repos before upload
    service = MetadataService.get_instance()
    initial_status = service.get_graph_status()
    print("Initial Neo4j repos:", initial_status.get("repositories"))

    # Upload graph with repo_id
    client.upload_graph(extractor.nodes, extractor.edges, repo_id=repo_id)
    # Record SyncState
    if hasattr(client, "set_sync_state"):
        client.set_sync_state(
            repo_id=repo_id,
            target_sha=commit_info["commit_sha"],
            status="SYNCED",
            commit_verified=True,
            nodes_count=len(extractor.nodes),
            edges_count=len(extractor.edges),
            files_parsed=len(files),
        )

    # Re-check status
    updated_status = service.get_graph_status()
    print("Updated Neo4j repos:", updated_status.get("repositories"))
    assert repo_id in updated_status.get("repositories"), f"Expected '{repo_id}' in Neo4j repositories!"

    print("\n=== Step 4: Blast Radius Analysis for 'src/validator.py' ===")
    blast_res = GraphInspector.analyze_blast_radius(
        repo_id=repo_id,
        changed_files=["src/validator.py"],
        local_repo_dir=demo_repo_path,
    )
    print("Blast radius scope:", blast_res.get("blast_radius_scope"))
    print("Blast radius count:", blast_res.get("blast_radius_count"))
    print("Execution engine:", blast_res.get("execution_engine"))
    print("Affected files:", blast_res.get("affected_callers"))
    print(f"Graph elements in subgraph: {len(blast_res.get('graph_elements', []))}")

    assert blast_res.get("blast_radius_count", 0) > 0, "Expected non-zero blast radius for validator.py!"
    client.close()
    print("\n>>> All verification steps passed successfully! <<<")

if __name__ == "__main__":
    main()
