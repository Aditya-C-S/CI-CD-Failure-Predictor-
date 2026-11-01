import os
import shutil
import subprocess
import tempfile
import pytest

from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient
from maintenance.diff_agent import update_graph_from_diff
from maintenance.repo_utils import resolve_repo_id, parse_remote_url
from maintenance.migrate_repo_id import migrate_legacy_nodes
from tests.test_live_neo4j_integration import is_live_neo4j_available, get_live_test_database_name


class TestRepoUtils:
    def test_explicit_repo_id_highest_precedence(self):
        assert resolve_repo_id(".", "custom-org/my-repo") == "custom-org/my-repo"

    def test_env_repo_id_precedence(self, monkeypatch):
        monkeypatch.setenv("REPO_ID", "env-org/env-repo")
        assert resolve_repo_id(".") == "env-org/env-repo"

    def test_parse_remote_url(self):
        assert parse_remote_url("https://github.com/pallets/flask.git") == "pallets/flask"
        assert parse_remote_url("git@github.com:torvalds/linux.git") == "torvalds/linux"
        assert parse_remote_url("https://gitlab.com/group/subgroup/project.git") == "group/subgroup/project"


@pytest.fixture(scope="module")
def isolated_isolation_database():
    """
    Creates an isolated Neo4j database (e.g. 'testdb') on the live Neo4j instance,
    verifying before and after that the user's default database ('neo4j') is 100% untouched.
    """
    if not is_live_neo4j_available():
        pytest.skip("Live Neo4j instance is not available or credentials not configured.")

    test_db = get_live_test_database_name()

    c_default = Neo4jClient(database="neo4j")
    with c_default.session() as s:
        res = s.run("MATCH (n) RETURN count(n) AS cnt").single()
        initial_user_node_count = res["cnt"]
    c_default.close()

    # Create isolated database via system database
    c_system = Neo4jClient(database="system")
    try:
        with c_system.session() as s:
            s.run(f"CREATE DATABASE {test_db} IF NOT EXISTS WAIT").consume()
    except Exception as e:
        c_system.close()
        pytest.skip(f"Failed to create isolated Neo4j database '{test_db}': {e}")
    c_system.close()

    yield test_db

    # Teardown: drop test database and verify user database node count is unchanged
    c_sys = Neo4jClient(database="system")
    with c_sys.session() as s:
        s.run(f"DROP DATABASE {test_db} IF EXISTS WAIT").consume()
    c_sys.close()

    c_verify = Neo4jClient(database="neo4j")
    with c_verify.session() as s:
        res = s.run("MATCH (n) RETURN count(n) AS cnt").single()
        final_user_node_count = res["cnt"]
    c_verify.close()

    assert final_user_node_count == initial_user_node_count, (
        f"SAFETY VIOLATION: User's default database node count changed from {initial_user_node_count} to {final_user_node_count}!"
    )


@pytest.fixture
def two_identical_path_repositories():
    """
    Creates two real Git repositories with identical relative paths ('math_ops.py', 'service.py')
    and identical function names ('compute', 'handle_request'), but different call graphs:
    - Repo A: handle_request() calls compute()
    - Repo B: handle_request() calls local_helper() and does NOT call compute()
    """
    dir_a = tempfile.mkdtemp(prefix="repo_a_")
    dir_b = tempfile.mkdtemp(prefix="repo_b_")

    for d in [dir_a, dir_b]:
        subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=d, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=d, check=True, capture_output=True)

    # Repo A files
    with open(os.path.join(dir_a, "math_ops.py"), "w", encoding="utf-8") as f:
        f.write("def compute():\n    return 100\n")
    with open(os.path.join(dir_a, "service.py"), "w", encoding="utf-8") as f:
        f.write("from math_ops import compute\n\ndef handle_request():\n    return compute()\n")

    subprocess.run(["git", "add", "."], cwd=dir_a, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit Repo A"], cwd=dir_a, check=True, capture_output=True)
    c1_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_a, capture_output=True, text=True, check=True).stdout.strip()

    # Repo B files (identical relative paths and names, but different internal calls)
    with open(os.path.join(dir_b, "math_ops.py"), "w", encoding="utf-8") as f:
        f.write("def compute():\n    return 999\n")
    with open(os.path.join(dir_b, "service.py"), "w", encoding="utf-8") as f:
        f.write("def local_helper():\n    return 0\n\ndef handle_request():\n    return local_helper()\n")

    subprocess.run(["git", "add", "."], cwd=dir_b, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit Repo B"], cwd=dir_b, check=True, capture_output=True)
    c1_b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_b, capture_output=True, text=True, check=True).stdout.strip()

    yield {
        "dir_a": dir_a,
        "c1_a": c1_a,
        "repo_id_a": "org/repo-a",
        "dir_b": dir_b,
        "c1_b": c1_b,
        "repo_id_b": "org/repo-b"
    }

    shutil.rmtree(dir_a, ignore_errors=True)
    shutil.rmtree(dir_b, ignore_errors=True)


class TestLiveNeo4jRepositoryIsolation:
    def test_live_multi_repo_isolation_end_to_end(self, isolated_isolation_database, two_identical_path_repositories, monkeypatch):
        """
        End-to-End Multi-Repository Isolation Verification on Live Neo4j:
        1. Full sync of Repo A and Repo B to the same test database.
        2. Assert node property isolation and scoped IDs.
        3. Assert zero cross-repository relationship leakage.
        4. Assert connected-file investigation isolation.
        5. Run incremental update on Repo A and assert Repo B remains 100% untouched.
        6. Delete a file in Repo A and assert Repo B's file is untouched.
        7. Assert idempotence on repeated updates.
        8. Assert surgical clearing via clear_repository.
        """
        db_name = isolated_isolation_database
        monkeypatch.setenv("NEO4J_DATABASE", db_name)

        r = two_identical_path_repositories
        dir_a, repo_a = r["dir_a"], r["repo_id_a"]
        dir_b, repo_b = r["dir_b"], r["repo_id_b"]

        client = Neo4jClient(database=db_name)
        # Clean testdb before starting
        client.clear_database()

        # Step 1: Parse and upload Repo A
        ext_a = Extractor(repo_id=repo_a)
        ext_a.parse_directory(dir_a, repo_id=repo_a)
        graph_a = ext_a.get_graph()
        client.upload_graph(graph_a["nodes"], graph_a["edges"], repo_id=repo_a)
        client.record_sync_state(repo_id=repo_a, target_sha=r["c1_a"], commit_verified=True)

        # Step 2: Parse and upload Repo B
        ext_b = Extractor(repo_id=repo_b)
        ext_b.parse_directory(dir_b, repo_id=repo_b)
        graph_b = ext_b.get_graph()
        client.upload_graph(graph_b["nodes"], graph_b["edges"], repo_id=repo_b)
        client.record_sync_state(repo_id=repo_b, target_sha=r["c1_b"], commit_verified=True)

        with client.session() as s:
            # Check 1: Repo A and Repo B nodes have repo_id set and are isolated
            cnt_a = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_a).single()["cnt"]
            cnt_b = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
            total_cnt = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]

            assert cnt_a > 0, "Repo A must have nodes"
            assert cnt_b > 0, "Repo B must have nodes"
            assert total_cnt == cnt_a + cnt_b, "Every node in the database must belong to a specific repo_id"

            # Check 2: Cross-repo edge leakage check (MUST BE 0)
            leak_edges = s.run(
                """
                MATCH (a)-[r]->(b)
                WHERE a.repo_id <> b.repo_id
                RETURN count(r) AS cnt
                """
            ).single()["cnt"]
            assert leak_edges == 0, f"ISOLATION BREACH: Found {leak_edges} cross-repository relationships!"

            # Check 3: Relationship graph semantics:
            # In Repo A, handle_request calls compute
            calls_a = s.run(
                """
                MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                WHERE a.name = 'handle_request' AND b.name = 'compute'
                RETURN count(r) AS cnt
                """,
                r=repo_a
            ).single()["cnt"]
            assert calls_a == 1, "Repo A handle_request must call compute"

            # In Repo B, handle_request does NOT call compute
            calls_b_compute = s.run(
                """
                MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                WHERE a.name = 'handle_request' AND b.name = 'compute'
                RETURN count(r) AS cnt
                """,
                r=repo_b
            ).single()["cnt"]
            assert calls_b_compute == 0, "Repo B handle_request must NOT call compute"

            # In Repo B, handle_request calls local_helper
            calls_b_helper = s.run(
                """
                MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                WHERE a.name = 'handle_request' AND b.name = 'local_helper'
                RETURN count(r) AS cnt
                """,
                r=repo_b
            ).single()["cnt"]
            assert calls_b_helper == 1, "Repo B handle_request must call local_helper"

        # Step 3: Connected-file investigation isolation
        connected_a = client.get_connected_files(repo_id=repo_a, file_path="service.py")
        assert any("math_ops.py" in cf for cf in connected_a), f"Repo A service.py must be connected to math_ops.py, got {connected_a}"

        connected_b = client.get_connected_files(repo_id=repo_b, file_path="service.py")
        assert not any("math_ops.py" in cf for cf in connected_b), f"Repo B service.py must NOT be connected to math_ops.py, got {connected_b}"

        # Snapshot Repo B counts before mutating Repo A
        with client.session() as s:
            repo_b_nodes_before = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
            repo_b_edges_before = s.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_b).single()["cnt"]

        # Step 4: Incremental modification to Repo A (Commit C2_A)
        with open(os.path.join(dir_a, "math_ops.py"), "w", encoding="utf-8") as f:
            f.write("def compute():\n    # Modified in Repo A\n    return 200\n")
        subprocess.run(["git", "add", "."], cwd=dir_a, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Modify compute in Repo A"], cwd=dir_a, check=True, capture_output=True)
        c2_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_a, capture_output=True, text=True, check=True).stdout.strip()

        # Run commit-aware incremental update on Repo A
        update_graph_from_diff(dir_a, base_sha=r["c1_a"], target_sha=c2_a, repo_id=repo_a)

        # Verify Repo B was 100% UNTOUCHED by Repo A's update
        with client.session() as s:
            repo_b_nodes_after = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
            repo_b_edges_after = s.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_b).single()["cnt"]
            assert repo_b_nodes_after == repo_b_nodes_before, "Repo B nodes were modified by Repo A incremental update!"
            assert repo_b_edges_after == repo_b_edges_before, "Repo B edges were modified by Repo A incremental update!"

            # Verify Repo A still preserved its CALLS relationship
            calls_a_preserved = s.run(
                """
                MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                WHERE a.name = 'handle_request' AND b.name = 'compute'
                RETURN count(r) AS cnt
                """,
                r=repo_a
            ).single()["cnt"]
            assert calls_a_preserved == 1, "Repo A must preserve CALLS relationship after incremental update"

        # Step 5: File deletion in Repo A (Commit C3_A)
        os.remove(os.path.join(dir_a, "math_ops.py"))
        subprocess.run(["git", "add", "-A"], cwd=dir_a, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Delete math_ops in Repo A"], cwd=dir_a, check=True, capture_output=True)
        c3_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_a, capture_output=True, text=True, check=True).stdout.strip()

        update_graph_from_diff(dir_a, base_sha=c2_a, target_sha=c3_a, repo_id=repo_a)

        with client.session() as s:
            # Repo A math_ops.py should be deleted
            math_ops_a = s.run(
                "MATCH (n:File {repo_id: $r}) WHERE n.name = 'math_ops.py' RETURN count(n) AS cnt",
                r=repo_a
            ).single()["cnt"]
            assert math_ops_a == 0, "Repo A math_ops.py must be deleted"

            # Repo B math_ops.py MUST REMAIN INTACT!
            math_ops_b = s.run(
                "MATCH (n:File {repo_id: $r}) WHERE n.name = 'math_ops.py' RETURN count(n) AS cnt",
                r=repo_b
            ).single()["cnt"]
            assert math_ops_b == 1, "ISOLATION BREACH: Repo B math_ops.py was deleted when Repo A was pruned!"

            # Repo B function compute must also remain intact
            compute_b = s.run(
                "MATCH (n:Function {repo_id: $r}) WHERE n.name = 'compute' RETURN count(n) AS cnt",
                r=repo_b
            ).single()["cnt"]
            assert compute_b == 1, "Repo B compute function must remain intact"

        # Step 6: Idempotence check on Repo B
        with client.session() as s:
            cnt_before_repeat = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
        # Re-upload Repo B
        client.upload_graph(graph_b["nodes"], graph_b["edges"], repo_id=repo_b)
        with client.session() as s:
            cnt_after_repeat = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
            assert cnt_after_repeat == cnt_before_repeat, "Repeated upload of Repo B must be idempotent (no duplicates)"

        # Step 7: Surgical clearing of Repo A
        client.clear_repository(repo_a)
        with client.session() as s:
            remaining_a = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_a).single()["cnt"]
            remaining_b = s.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_b).single()["cnt"]
            assert remaining_a == 0, "Repo A must have 0 nodes after clear_repository(repo_a)"
            assert remaining_b == cnt_before_repeat, "Repo B nodes must remain 100% intact after clear_repository(repo_a)!"

        client.close()

    def test_legacy_node_migration_safety(self, isolated_isolation_database, monkeypatch):
        """
        Tests migration of legacy un-scoped graph nodes:
        1. Insert un-scoped legacy node into testdb.
        2. Run migrate_legacy_nodes(default_repo_id='legacy:test').
        3. Assert node is tagged with repo_id without deleting data.
        """
        db_name = isolated_isolation_database
        monkeypatch.setenv("NEO4J_DATABASE", db_name)

        client = Neo4jClient(database=db_name)
        client.clear_database()

        # Insert a legacy node with no repo_id
        with client.session() as s:
            s.run("CREATE (n:File {id: 'file:legacy.py', name: 'legacy.py', path: '/legacy.py'})")
            s.run("CREATE (f:Function {id: 'func:legacy:foo', name: 'foo', file_path: '/legacy.py'})")
            s.run("MATCH (a {id: 'file:legacy.py'}), (b {id: 'func:legacy:foo'}) MERGE (a)-[r:CONTAINS]->(b)")

        res = migrate_legacy_nodes(default_repo_id="legacy:test", database=db_name)
        assert res["status"] == "migrated"
        assert res["migrated_nodes"] >= 2

        with client.session() as s:
            unmigrated = s.run("MATCH (n) WHERE n.repo_id IS NULL RETURN count(n) AS cnt").single()["cnt"]
            assert unmigrated == 0, "All nodes must now have repo_id"
            migrated_cnt = s.run("MATCH (n {repo_id: 'legacy:test'}) RETURN count(n) AS cnt").single()["cnt"]
            assert migrated_cnt >= 2

        client.close()
