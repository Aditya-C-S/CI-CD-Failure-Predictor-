import pytest
from database.neo4j_client import Neo4jClient
from tests.test_live_neo4j_integration import is_live_neo4j_available

REL_TEST_DB = "testdbrepotagging"

@pytest.fixture(scope="module")
def isolated_rel_test_db():
    if not is_live_neo4j_available():
        pytest.skip("Live Neo4j instance not available.")

    # 1. Snapshot original neo4j count
    c_orig = Neo4jClient(database="neo4j")
    with c_orig.session() as s:
        orig_count = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
    c_orig.close()

    # 2. Create isolated database
    c_sys = Neo4jClient(database="system")
    try:
        with c_sys.session() as s:
            s.run(f"CREATE DATABASE {REL_TEST_DB} IF NOT EXISTS WAIT").consume()
    except Exception as e:
        c_sys.close()
        pytest.skip(f"Failed to create test db: {e}")
    c_sys.close()

    yield REL_TEST_DB

    # 3. Teardown
    c_sys = Neo4jClient(database="system")
    with c_sys.session() as s:
        s.run(f"DROP DATABASE {REL_TEST_DB} IF EXISTS WAIT").consume()
    c_sys.close()

    c_verify = Neo4jClient(database="neo4j")
    with c_verify.session() as s:
        final_count = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
    c_verify.close()
    assert final_count == orig_count, f"SAFETY VIOLATION: Production database node count changed from {orig_count} to {final_count}!"


def test_uploaded_relationships_receive_repo_id(isolated_rel_test_db, monkeypatch):
    monkeypatch.setenv("NEO4J_DATABASE", isolated_rel_test_db)
    client = Neo4jClient()
    try:
        client.clear_database()

        nodes = [
            {"type": "File", "properties": {"id": "repo:org/alpha:file:a.py", "name": "a.py", "repo_id": "org/alpha"}},
            {"type": "Function", "properties": {"id": "repo:org/alpha:func:foo", "name": "foo", "repo_id": "org/alpha"}},
            {"type": "Function", "properties": {"id": "repo:org/alpha:func:bar", "name": "bar", "repo_id": "org/alpha"}}
        ]
        edges = [
            {"from": "repo:org/alpha:file:a.py", "to": "repo:org/alpha:func:foo", "type": "CONTAINS"},
            {"from": "repo:org/alpha:func:foo", "to": "repo:org/alpha:func:bar", "type": "CALLS"}
        ]

        client.upload_graph(nodes, edges, repo_id="org/alpha")

        with client.session() as s:
            edge_rows = s.run("MATCH (a)-[r]->(b) RETURN type(r) AS t, r.repo_id AS repo_id").data()
            assert len(edge_rows) == 2
            for er in edge_rows:
                assert er["repo_id"] == "org/alpha", f"Edge {er['t']} missing repo_id org/alpha: {er}"
    finally:
        client.close()


def test_cross_repository_relationship_creation_blocked(isolated_rel_test_db, monkeypatch):
    monkeypatch.setenv("NEO4J_DATABASE", isolated_rel_test_db)
    client = Neo4jClient()
    try:
        client.clear_database()

        # Seed node in alpha and node in beta
        nodes_alpha = [
            {"type": "Function", "properties": {"id": "repo:org/alpha:func:sender", "name": "sender", "repo_id": "org/alpha"}}
        ]
        nodes_beta = [
            {"type": "Function", "properties": {"id": "repo:org/beta:func:receiver", "name": "receiver", "repo_id": "org/beta"}}
        ]
        client.upload_graph(nodes_alpha, [], repo_id="org/alpha")
        client.upload_graph(nodes_beta, [], repo_id="org/beta")

        # Attempt to create cross-repo edge via repository-scoped upload
        cross_edge = [
            {"from": "repo:org/alpha:func:sender", "to": "repo:org/beta:func:receiver", "type": "CALLS"}
        ]
        client.upload_graph([], cross_edge, repo_id="org/alpha")

        # Verify edge was NOT created
        with client.session() as s:
            count = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
            assert count == 0, f"Cross-repository edge was illegally created! Found {count} edges."
    finally:
        client.close()


def test_existing_relationships_tagged_on_merge(isolated_rel_test_db, monkeypatch):
    monkeypatch.setenv("NEO4J_DATABASE", isolated_rel_test_db)
    client = Neo4jClient()
    try:
        client.clear_database()

        # 1. Manually create legacy nodes and an untagged relationship
        with client.session() as s:
            s.run("CREATE (:File {id: 'f1', repo_id: 'org/gamma'})-[:CONTAINS]->(:Function {id: 'fn1', repo_id: 'org/gamma'})")
            # Verify relationship initially has no repo_id
            init_repo = s.run("MATCH ()-[r:CONTAINS]->() RETURN r.repo_id AS repo_id").single()["repo_id"]
            assert init_repo is None

        # 2. Upload same edge with repo_id="org/gamma"
        edges = [
            {"from": "f1", "to": "fn1", "type": "CONTAINS"}
        ]
        client.upload_graph([], edges, repo_id="org/gamma")

        # 3. Verify relationship was updated with repo_id
        with client.session() as s:
            rel_data = s.run("MATCH ()-[r:CONTAINS]->() RETURN count(r) AS cnt, r.repo_id AS repo_id").single()
            assert rel_data["cnt"] == 1, "Duplicate edge created instead of merging!"
            assert rel_data["repo_id"] == "org/gamma", f"Expected r.repo_id='org/gamma', got {rel_data['repo_id']}"
    finally:
        client.close()
