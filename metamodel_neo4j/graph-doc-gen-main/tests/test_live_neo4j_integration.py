import os
import shutil
import subprocess
import tempfile
import pytest

from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient
from maintenance.diff_agent import update_graph_from_diff


PROTECTED_TEST_DATABASES = {"neo4j", "system"}


def get_live_test_database_name():
    """
    Explicitly retrieves the dedicated test database name.
    Fails closed if the configuration is missing, empty, or targets a protected database.
    """
    db_name = os.getenv("NEO4J_TEST_DATABASE", "testdb")
    if not db_name or not db_name.strip():
        raise RuntimeError(
            "FAIL CLOSED: Dedicated test database name is missing or empty. "
            "Live tests must explicitly select a separate test database."
        )
    clean_db = db_name.strip()
    if clean_db.lower() in PROTECTED_TEST_DATABASES:
        raise RuntimeError(
            f"FAIL CLOSED: Configured test database '{clean_db}' is a protected/main database. "
            f"Live tests are strictly prohibited from targeting protected or main databases."
        )
    return clean_db


def is_live_neo4j_available():
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not (uri and user and password):
        return False
    try:
        c = Neo4jClient()
        c.driver.verify_connectivity()
        c.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def isolated_neo4j_database():
    """
    Creates an isolated Neo4j database on the live Neo4j Enterprise instance,
    verifying before and after that the user's default database ('neo4j') is 100% untouched.
    Fails closed if the test database configuration is missing or targets a main/protected DB.
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
def isolated_git_repo():
    """Creates a temporary git repository with two files having cross-file dependencies."""
    temp_dir = tempfile.mkdtemp()
    subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_dir, check=True, capture_output=True)

    callee_code = "def compute():\n    return 42\n"
    caller_code = "from callee import compute\n\ndef run():\n    return compute()\n"

    with open(os.path.join(temp_dir, "callee.py"), "w", encoding="utf-8") as f:
        f.write(callee_code)
    with open(os.path.join(temp_dir, "caller.py"), "w", encoding="utf-8") as f:
        f.write(caller_code)

    subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit C1"], cwd=temp_dir, check=True, capture_output=True)
    c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

    yield temp_dir, c1
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestRealNeo4jIncrementalUpdate:
    def test_live_callee_modification_preserves_cross_file_calls(self, isolated_neo4j_database, isolated_git_repo, monkeypatch):
        """
        End-to-End on Real Neo4j:
        1. Initialize isolated 'testdb' with C1.
        2. Commit modification to callee as C2 (working tree clean).
        3. Run update_graph_from_diff with C1 and C2 targeting 'testdb'.
        4. Verify cross-file CALLS relationship is preserved.
        5. Verify repeated update is idempotent (no duplicates).
        6. Compare against full parse of C2.
        """
        db_name = isolated_neo4j_database
        monkeypatch.setenv("NEO4J_DATABASE", db_name)
        temp_dir, c1 = isolated_git_repo

        client = Neo4jClient(database=db_name)
        client.clear_database()

        # Step 1: Upload initial C1 graph into testdb
        ext = Extractor()
        ext.parse_directory(temp_dir)
        g1 = ext.get_graph()
        client.upload_graph(g1["nodes"], g1["edges"])

        # Verify initial state in real Neo4j
        with client.session() as s:
            r = s.run("MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN a.id AS from, b.id AS to").data()
            assert len(r) == 1, "Initial graph in Neo4j must have 1 CALLS edge"
            assert "run" in r[0]["from"] and "compute" in r[0]["to"]

        # Step 2: Modify callee and commit as C2
        callee_path = os.path.join(temp_dir, "callee.py")
        with open(callee_path, "w", encoding="utf-8") as f:
            f.write("def compute():\n    return 9999\n")

        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Modify compute in C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        # Verify working tree is clean
        status = subprocess.run(["git", "status", "--porcelain"], cwd=temp_dir, capture_output=True, text=True).stdout.strip()
        assert status == "", "Working tree must be clean"

        # Step 3: Run commit-aware updater against real Neo4j testdb
        update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        # Step 4: Verify cross-file CALLS relationship is preserved in real Neo4j
        with client.session() as s:
            r = s.run("MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN a.id AS from, b.id AS to").data()
            assert len(r) == 1, f"Expected 1 CALLS edge in Neo4j, got {len(r)}: {r}"
            assert "run" in r[0]["from"] and "compute" in r[0]["to"]

            node_count = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
            edge_count = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]

        # Step 5: Verify repeated update is idempotent (no duplicates in real Neo4j)
        update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        with client.session() as s:
            node_count_rep = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
            edge_count_rep = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
            assert node_count_rep == node_count, "Repeated update created duplicate nodes in Neo4j"
            assert edge_count_rep == edge_count, "Repeated update created duplicate edges in Neo4j"

        # Step 6: Compare against complete parse of target commit C2
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()

        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]
        assert len(full_calls) == 1
        with client.session() as s:
            r = s.run("MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN a.id AS from, b.id AS to").data()
            assert r[0]["from"] == full_calls[0]["from"]
            assert r[0]["to"] == full_calls[0]["to"]

        client.close()

    def test_live_rename_and_deletion_pruning(self, isolated_neo4j_database, isolated_git_repo, monkeypatch):
        """
        End-to-End on Real Neo4j:
        1. Start from C1.
        2. Commit C2 that adds to_delete.py.
        3. Commit C3 that renames callee.py -> renamed_callee.py and deletes to_delete.py.
        4. Run incremental update between C2 and C3.
        5. Verify obsolete nodes and relationships disappear.
        6. Verify caller is re-linked to renamed_callee.
        7. Compare against complete parse of C3.
        """
        db_name = isolated_neo4j_database
        monkeypatch.setenv("NEO4J_DATABASE", db_name)
        temp_dir, c1 = isolated_git_repo

        client = Neo4jClient(database=db_name)
        client.clear_database()

        # Add to_delete.py and commit as C2
        with open(os.path.join(temp_dir, "to_delete.py"), "w", encoding="utf-8") as f:
            f.write("def temporary_util(): return True\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add to_delete.py C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        # Populate initial state for C2 into testdb
        ext = Extractor()
        ext.parse_directory(temp_dir)
        g2 = ext.get_graph()
        client.upload_graph(g2["nodes"], g2["edges"])

        with client.session() as s:
            r = s.run("MATCH (n) WHERE n.name = 'temporary_util' RETURN count(n) AS cnt").single()["cnt"]
            assert r == 1, "temporary_util must exist in initial state"

        # Commit C3: rename callee.py -> renamed_callee.py and delete to_delete.py
        subprocess.run(["git", "mv", "callee.py", "renamed_callee.py"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "rm", "to_delete.py"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Rename callee and delete util C3"], cwd=temp_dir, check=True, capture_output=True)
        c3 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        # Run updater from C2 to C3
        update_graph_from_diff(temp_dir, base_sha=c2, target_sha=c3)

        # Verify obsolete nodes were removed
        with client.session() as s:
            cnt_deleted = s.run("MATCH (n) WHERE n.name = 'temporary_util' RETURN count(n) AS cnt").single()["cnt"]
            assert cnt_deleted == 0, "Deleted file's nodes must be pruned from Neo4j"

            cnt_old_callee = s.run("MATCH (n) WHERE n.file_path CONTAINS 'callee.py' AND NOT n.file_path CONTAINS 'renamed' RETURN count(n) AS cnt").single()["cnt"]
            assert cnt_old_callee == 0, "Old renamed file's nodes must be pruned from Neo4j"

            cnt_new_callee = s.run("MATCH (n) WHERE n.file_path CONTAINS 'renamed_callee.py' RETURN count(n) AS cnt").single()["cnt"]
            assert cnt_new_callee > 0, "New renamed file's nodes must exist in Neo4j"

            # Inbound caller re-linked to renamed_callee
            r = s.run("MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN a.id AS from, b.id AS to").data()
            assert len(r) == 1, f"Expected 1 CALLS edge in Neo4j, got: {r}"
            assert "renamed_callee" in r[0]["to"], f"Caller must be re-linked to renamed file: {r[0]['to']}"

        # Compare with full parse of target commit C3
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()

        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]
        assert len(full_calls) == 1
        with client.session() as s:
            r = s.run("MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN a.id AS from, b.id AS to").data()
            assert r[0]["from"] == full_calls[0]["from"]
            assert r[0]["to"] == full_calls[0]["to"]

        client.close()
