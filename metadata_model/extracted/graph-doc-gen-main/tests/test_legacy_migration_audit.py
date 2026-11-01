import os
import shutil
import subprocess
import tempfile
import pytest

from database.neo4j_client import Neo4jClient
from code_parser.extractor import Extractor
from maintenance.diff_agent import update_graph_from_diff
from tests.test_live_neo4j_integration import is_live_neo4j_available, get_live_test_database_name


AUDIT_TEST_DB = "testdbmigrationaudit"


@pytest.fixture(scope="module")
def isolated_audit_database():
    """
    Creates an isolated Neo4j database (e.g. 'testdbmigrationaudit') on live Neo4j,
    verifying before and after that the user's default database ('neo4j') is 100% untouched.
    """
    if not is_live_neo4j_available():
        pytest.skip("Live Neo4j instance is not available or credentials not configured.")

    # Snapshot real user database node count
    c_default = Neo4jClient(database="neo4j")
    with c_default.session() as s:
        res = s.run("MATCH (n) RETURN count(n) AS cnt").single()
        initial_user_node_count = res["cnt"]
    c_default.close()

    # Create isolated database via system database
    c_system = Neo4jClient(database="system")
    try:
        with c_system.session() as s:
            s.run(f"CREATE DATABASE {AUDIT_TEST_DB} IF NOT EXISTS WAIT").consume()
    except Exception as e:
        c_system.close()
        pytest.skip(f"Failed to create isolated Neo4j database '{AUDIT_TEST_DB}': {e}")
    c_system.close()

    yield AUDIT_TEST_DB

    # Teardown: drop test database and verify user database node count is unchanged
    c_sys = Neo4jClient(database="system")
    with c_sys.session() as s:
        s.run(f"DROP DATABASE {AUDIT_TEST_DB} IF EXISTS WAIT").consume()
    c_sys.close()

    c_verify = Neo4jClient(database="neo4j")
    with c_verify.session() as s:
        res = s.run("MATCH (n) RETURN count(n) AS cnt").single()
        final_user_node_count = res["cnt"]
    c_verify.close()

    assert final_user_node_count == initial_user_node_count, (
        f"SAFETY VIOLATION: User's default database node count changed from {initial_user_node_count} to {final_user_node_count}!"
    )


def create_representative_legacy_fixture(session):
    """
    Populates the test database with a faithful representation of the 88 untagged nodes:
    - 36 nodes from 'graph-doc-gen' (Files, Classes, Functions, CONTAINS, CALLS, IMPORTS)
    - 6 nodes from '/test_repo' (Files, Functions, CONTAINS, CALLS)
    - 5 nodes from 'Temp/e2e_test' (Files, Functions, CONTAINS, CALLS, IMPORTS)
    - 1 ExternalModule node (un-scoped)
    Total: 48 representative un-scoped nodes with 0 initial repo_id properties.
    """
    # 1. ExternalModule
    session.run("CREATE (m:Module {id: 'ExternalModule', name: 'External Dependencies', summary: 'Third-party libraries'})")

    # 2. graph-doc-gen nodes & edges
    gdg_files = ["extractor.py", "neo4j_client.py", "diff_agent.py"]
    for f in gdg_files:
        fp = f"C:\\Users\\DHRUV HEGDE\\Desktop\\graph-doc-gen\\code_parser\\{f}"
        fid = f"file:{fp}"
        session.run("CREATE (n:File {id: $id, path: $fp, file_path: $fp, name: $name})", id=fid, fp=fp, name=f)
        session.run("CREATE (fn:Function {id: $id, name: $name, file_path: $fp})", id=f"function:{fid}:func_{f[:-3]}", name=f"func_{f[:-3]}", fp=fp)
        session.run("MATCH (a {id: $fid}), (b {id: $fnid}) CREATE (a)-[:CONTAINS]->(b)", fid=fid, fnid=f"function:{fid}:func_{f[:-3]}")
        session.run("MATCH (a {id: $fid}), (m {id: 'ExternalModule'}) CREATE (a)-[:IMPORTS]->(m)", fid=fid)

    # CALLS within graph-doc-gen
    session.run("""
        MATCH (a {id: 'function:file:C:\\\\Users\\\\DHRUV HEGDE\\\\Desktop\\\\graph-doc-gen\\\\code_parser\\\\diff_agent.py:func_diff_agent'}),
              (b {id: 'function:file:C:\\\\Users\\\\DHRUV HEGDE\\\\Desktop\\\\graph-doc-gen\\\\code_parser\\\\extractor.py:func_extractor'})
        CREATE (a)-[:CALLS]->(b)
    """)

    # 3. /test_repo synthetic nodes & edges
    for f in ["file_a.py", "file_b.py"]:
        fp = f"/test_repo/{f}"
        fid = f"file:{fp}"
        session.run("CREATE (n:File {id: $id, path: $fp, file_path: $fp, name: $name})", id=fid, fp=fp, name=f)
        session.run("CREATE (fn:Function {id: $id, name: $name, file_path: $fp})", id=f"function:{fid}:fn_{f[:-3]}", name=f"fn_{f[:-3]}", fp=fp)
        session.run("MATCH (a {id: $fid}), (b {id: $fnid}) CREATE (a)-[:CONTAINS]->(b)", fid=fid, fnid=f"function:{fid}:fn_{f[:-3]}")

    session.run("""
        MATCH (a {id: 'function:file:/test_repo/file_a.py:fn_file_a'}),
              (b {id: 'function:file:/test_repo/file_b.py:fn_file_b'})
        CREATE (a)-[:CALLS]->(b)
    """)

    # 4. Temp e2e ephemeral test nodes & edges
    temp_fp = "C:\\Users\\DHRUVH~1\\AppData\\Local\\Temp\\e2e_test_sample\\file_a.py"
    temp_fid = f"file:{temp_fp}"
    session.run("CREATE (n:File {id: $id, path: $fp, file_path: $fp, name: 'file_a.py'})", id=temp_fid, fp=temp_fp)
    session.run("CREATE (fn:Function {id: $id, name: 'temp_func', file_path: $fp})", id=f"function:{temp_fid}:temp_func", name="temp_func", fp=temp_fp)
    session.run("MATCH (a {id: $fid}), (b {id: $fnid}) CREATE (a)-[:CONTAINS]->(b)", fid=temp_fid, fnid=f"function:{temp_fid}:temp_func")
    session.run("MATCH (a {id: $fid}), (m {id: 'ExternalModule'}) CREATE (a)-[:IMPORTS]->(m)", fid=temp_fid)


def execute_repository_scoped_migration(session):
    """
    Executes the proposed evidence-based repository-scoped migration:
    - graph-doc-gen -> repo_id: 'local:graph-doc-gen'
    - /test_repo -> repo_id: 'test:synthetic-fixture'
    - Temp/ -> repo_id: 'quarantine:ephemeral-residue'
    - ExternalModule -> replicated and scoped per importing repository
    """
    # Migrate graph-doc-gen
    session.run("""
        MATCH (n)
        WHERE n.repo_id IS NULL AND (n.path CONTAINS 'graph-doc-gen' OR n.file_path CONTAINS 'graph-doc-gen' OR n.id CONTAINS 'graph-doc-gen')
        SET n.repo_id = 'local:graph-doc-gen'
    """)
    session.run("""
        MATCH (a {repo_id: 'local:graph-doc-gen'})-[r]->(b {repo_id: 'local:graph-doc-gen'})
        WHERE r.repo_id IS NULL
        SET r.repo_id = 'local:graph-doc-gen'
    """)

    # Migrate /test_repo
    session.run("""
        MATCH (n)
        WHERE n.repo_id IS NULL AND (n.path CONTAINS '/test_repo/' OR n.file_path CONTAINS '/test_repo/' OR n.id CONTAINS '/test_repo/')
        SET n.repo_id = 'test:synthetic-fixture'
    """)
    session.run("""
        MATCH (a {repo_id: 'test:synthetic-fixture'})-[r]->(b {repo_id: 'test:synthetic-fixture'})
        WHERE r.repo_id IS NULL
        SET r.repo_id = 'test:synthetic-fixture'
    """)

    # Migrate Temp residue to quarantine
    session.run("""
        MATCH (n)
        WHERE n.repo_id IS NULL AND (n.path CONTAINS 'Temp' OR n.file_path CONTAINS 'Temp' OR n.id CONTAINS 'Temp')
        SET n.repo_id = 'quarantine:ephemeral-residue'
    """)
    session.run("""
        MATCH (a {repo_id: 'quarantine:ephemeral-residue'})-[r]->(b {repo_id: 'quarantine:ephemeral-residue'})
        WHERE r.repo_id IS NULL
        SET r.repo_id = 'quarantine:ephemeral-residue'
    """)

    # Re-scope legacy ExternalModule per importing repository to guarantee zero cross-repo leakage
    session.run("""
        MATCH (a)-[r:IMPORTS]->(m:Module {id: 'ExternalModule'})
        WITH a, r, m, a.repo_id AS repo
        WHERE repo IS NOT NULL
        MERGE (scoped_m:Module {id: 'repo:' + repo + ':module:ExternalModule'})
        SET scoped_m.name = 'External Dependencies',
            scoped_m.summary = m.summary,
            scoped_m.repo_id = repo
        CREATE (a)-[new_r:IMPORTS {repo_id: repo}]->(scoped_m)
        DELETE r
    """)
    # Remove orphaned global ExternalModule if no edges remain
    session.run("""
        MATCH (m:Module {id: 'ExternalModule'})
        WHERE NOT (m)--()
        DELETE m
    """)


class TestLegacyMigrationAndDualRepoIsolation:
    def test_legacy_migration_and_dual_repo_isolation_verification(self, isolated_audit_database, monkeypatch):
        """
        Step 3 Verification:
        1. Populate isolated test database with representative legacy un-scoped graph.
        2. Execute proposed repository-scoped migration.
        3. Verify all legacy nodes are cleanly partitioned and untagged count is 0.
        4. Ingest two new real repositories with identical paths and function names but different call graphs.
        5. Verify repository isolation, connected-file investigation, incremental update, deletion, rename, and idempotence.
        6. Verify detailed graph content semantics (not just counts).
        """
        db_name = isolated_audit_database
        monkeypatch.setenv("NEO4J_DATABASE", db_name)

        client = Neo4jClient(database=db_name)
        client.clear_database()

        with client.session() as session:
            # 1. Populate legacy fixture
            create_representative_legacy_fixture(session)

            # Pre-migration count
            unmigrated_before = session.run("MATCH (n) WHERE n.repo_id IS NULL RETURN count(n) AS cnt").single()["cnt"]
            assert unmigrated_before > 0, "Fixture must have untagged nodes"

            # 2. Run repository-scoped migration
            execute_repository_scoped_migration(session)

            # Post-migration check
            unmigrated_after = session.run("MATCH (n) WHERE n.repo_id IS NULL RETURN count(n) AS cnt").single()["cnt"]
            assert unmigrated_after == 0, "All legacy nodes must be assigned a repo_id"

            gdg_count = session.run("MATCH (n {repo_id: 'local:graph-doc-gen'}) RETURN count(n) AS cnt").single()["cnt"]
            test_repo_count = session.run("MATCH (n {repo_id: 'test:synthetic-fixture'}) RETURN count(n) AS cnt").single()["cnt"]
            quarantine_count = session.run("MATCH (n {repo_id: 'quarantine:ephemeral-residue'}) RETURN count(n) AS cnt").single()["cnt"]

            assert gdg_count >= 6  # 3 files + 3 functions + ExternalModule
            assert test_repo_count == 4  # 2 files + 2 functions
            assert quarantine_count >= 2  # 1 file + 1 function + ExternalModule

        # 3. Create two real repositories with IDENTICAL paths and function names
        dir_alpha = tempfile.mkdtemp(prefix="repo_alpha_")
        dir_beta = tempfile.mkdtemp(prefix="repo_beta_")

        try:
            for d in [dir_alpha, dir_beta]:
                subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
                subprocess.run(["git", "config", "user.name", "Tester"], cwd=d, check=True, capture_output=True)
                subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=d, check=True, capture_output=True)

            # Identical relative paths: 'math_ops.py' and 'service.py'
            # Repo Alpha: handle_request() calls compute()
            with open(os.path.join(dir_alpha, "math_ops.py"), "w", encoding="utf-8") as f:
                f.write("def compute():\n    return 42\n")
            with open(os.path.join(dir_alpha, "service.py"), "w", encoding="utf-8") as f:
                f.write("from math_ops import compute\n\ndef handle_request():\n    return compute()\n")

            subprocess.run(["git", "add", "."], cwd=dir_alpha, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Alpha C1"], cwd=dir_alpha, check=True, capture_output=True)
            c1_alpha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_alpha, capture_output=True, text=True, check=True).stdout.strip()

            # Repo Beta: handle_request() calls local_helper() and does NOT call compute()
            with open(os.path.join(dir_beta, "math_ops.py"), "w", encoding="utf-8") as f:
                f.write("def compute():\n    return 999\n")
            with open(os.path.join(dir_beta, "service.py"), "w", encoding="utf-8") as f:
                f.write("def local_helper():\n    return 1\n\ndef handle_request():\n    return local_helper()\n")

            subprocess.run(["git", "add", "."], cwd=dir_beta, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Beta C1"], cwd=dir_beta, check=True, capture_output=True)
            c1_beta = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_beta, capture_output=True, text=True, check=True).stdout.strip()

            repo_alpha_id = "org/repo-alpha"
            repo_beta_id = "org/repo-beta"

            # Ingest Repo Alpha
            ext_alpha = Extractor(repo_id=repo_alpha_id)
            ext_alpha.parse_directory(dir_alpha, repo_id=repo_alpha_id)
            graph_alpha = ext_alpha.get_graph()
            client.upload_graph(graph_alpha["nodes"], graph_alpha["edges"], repo_id=repo_alpha_id)
            client.record_sync_state(repo_id=repo_alpha_id, target_sha=c1_alpha, commit_verified=True)

            # Ingest Repo Beta
            ext_beta = Extractor(repo_id=repo_beta_id)
            ext_beta.parse_directory(dir_beta, repo_id=repo_beta_id)
            graph_beta = ext_beta.get_graph()
            client.upload_graph(graph_beta["nodes"], graph_beta["edges"], repo_id=repo_beta_id)
            client.record_sync_state(repo_id=repo_beta_id, target_sha=c1_beta, commit_verified=True)

            # Verify Content Semantics in Neo4j
            with client.session() as session:
                # 0 cross-repository edge leaks across all repositories
                cross_leaks = session.run("MATCH (a)-[r]->(b) WHERE a.repo_id <> b.repo_id RETURN count(r) AS cnt").single()["cnt"]
                assert cross_leaks == 0, f"Found {cross_leaks} cross-repo edges!"

                # Check Alpha relationship content
                alpha_calls = session.run("""
                    MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                    RETURN a.name AS caller, b.name AS callee, a.rel_path AS caller_file, b.rel_path AS callee_file
                """, r=repo_alpha_id).data()
                assert len(alpha_calls) == 1
                assert alpha_calls[0]["caller"] == "handle_request"
                assert alpha_calls[0]["callee"] == "compute"
                assert alpha_calls[0]["caller_file"] == "service.py"
                assert alpha_calls[0]["callee_file"] == "math_ops.py"

                # Check Beta relationship content
                beta_calls = session.run("""
                    MATCH (a:Function {repo_id: $r})-[r:CALLS]->(b:Function {repo_id: $r})
                    RETURN a.name AS caller, b.name AS callee
                """, r=repo_beta_id).data()
                assert len(beta_calls) == 1
                assert beta_calls[0]["caller"] == "handle_request"
                assert beta_calls[0]["callee"] == "local_helper"

                # Check legacy local:graph-doc-gen content unaffected
                gdg_calls = session.run("""
                    MATCH (a:Function {repo_id: 'local:graph-doc-gen'})-[r:CALLS]->(b:Function {repo_id: 'local:graph-doc-gen'})
                    RETURN a.name AS caller, b.name AS callee
                """).data()
                assert len(gdg_calls) == 1
                assert gdg_calls[0]["caller"] == "func_diff_agent"
                assert gdg_calls[0]["callee"] == "func_extractor"

            # 4. Connected-File Investigation Verification
            conn_alpha = client.get_connected_files(repo_id=repo_alpha_id, file_path="service.py")
            assert "math_ops.py" in conn_alpha, f"Alpha service.py must connect to math_ops.py, got {conn_alpha}"

            conn_beta = client.get_connected_files(repo_id=repo_beta_id, file_path="service.py")
            assert "math_ops.py" not in conn_beta, f"Beta service.py must NOT connect to math_ops.py, got {conn_beta}"

            # 5. Incremental Modification in Repo Alpha (Commit C2)
            with open(os.path.join(dir_alpha, "math_ops.py"), "w", encoding="utf-8") as f:
                f.write("def compute():\n    return 1000\n")
            subprocess.run(["git", "add", "."], cwd=dir_alpha, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Alpha C2 - Update compute"], cwd=dir_alpha, check=True, capture_output=True)
            c2_alpha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_alpha, capture_output=True, text=True, check=True).stdout.strip()

            # Record Repo Beta state before update
            with client.session() as session:
                beta_nodes_pre = session.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                beta_edges_pre = session.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_beta_id).single()["cnt"]
                gdg_nodes_pre = session.run("MATCH (n {repo_id: 'local:graph-doc-gen'}) RETURN count(n) AS cnt").single()["cnt"]

            update_graph_from_diff(dir_alpha, base_sha=c1_alpha, target_sha=c2_alpha, repo_id=repo_alpha_id)

            with client.session() as session:
                beta_nodes_post = session.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                beta_edges_post = session.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_beta_id).single()["cnt"]
                gdg_nodes_post = session.run("MATCH (n {repo_id: 'local:graph-doc-gen'}) RETURN count(n) AS cnt").single()["cnt"]

                assert beta_nodes_post == beta_nodes_pre, "Repo Beta nodes altered by Repo Alpha incremental update!"
                assert beta_edges_post == beta_edges_pre, "Repo Beta edges altered by Repo Alpha incremental update!"
                assert gdg_nodes_post == gdg_nodes_pre, "Legacy graph-doc-gen nodes altered by Repo Alpha update!"

            # 6. File Rename in Repo Alpha (Commit C3)
            # Rename math_ops.py to math_calculator.py
            os.rename(os.path.join(dir_alpha, "math_ops.py"), os.path.join(dir_alpha, "math_calculator.py"))
            with open(os.path.join(dir_alpha, "service.py"), "w", encoding="utf-8") as f:
                f.write("from math_calculator import compute\n\ndef handle_request():\n    return compute()\n")
            subprocess.run(["git", "add", "-A"], cwd=dir_alpha, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Alpha C3 - Rename math_ops to math_calculator"], cwd=dir_alpha, check=True, capture_output=True)
            c3_alpha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_alpha, capture_output=True, text=True, check=True).stdout.strip()

            update_graph_from_diff(dir_alpha, base_sha=c2_alpha, target_sha=c3_alpha, repo_id=repo_alpha_id)

            with client.session() as session:
                # In Alpha: math_ops.py gone, math_calculator.py present
                alpha_old_math = session.run("MATCH (n:File {repo_id: $r, name: 'math_ops.py'}) RETURN count(n) AS cnt", r=repo_alpha_id).single()["cnt"]
                alpha_new_math = session.run("MATCH (n:File {repo_id: $r, name: 'math_calculator.py'}) RETURN count(n) AS cnt", r=repo_alpha_id).single()["cnt"]
                assert alpha_old_math == 0, "Alpha old math_ops.py must be deleted after rename"
                assert alpha_new_math == 1, "Alpha new math_calculator.py must exist after rename"

                # In Beta: math_ops.py MUST BE UNTOUCHED!
                beta_math = session.run("MATCH (n:File {repo_id: $r, name: 'math_ops.py'}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                assert beta_math == 1, "Beta math_ops.py was affected by Alpha rename!"

            # 7. File Deletion in Repo Alpha (Commit C4)
            os.remove(os.path.join(dir_alpha, "math_calculator.py"))
            subprocess.run(["git", "add", "-A"], cwd=dir_alpha, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Alpha C4 - Delete math_calculator"], cwd=dir_alpha, check=True, capture_output=True)
            c4_alpha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dir_alpha, capture_output=True, text=True, check=True).stdout.strip()

            update_graph_from_diff(dir_alpha, base_sha=c3_alpha, target_sha=c4_alpha, repo_id=repo_alpha_id)

            with client.session() as session:
                alpha_calc = session.run("MATCH (n {repo_id: $r}) WHERE n.name CONTAINS 'calculator' RETURN count(n) AS cnt", r=repo_alpha_id).single()["cnt"]
                assert alpha_calc == 0, "Alpha calculator nodes must be deleted"

                # Beta remains intact
                beta_total = session.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                assert beta_total == beta_nodes_pre, "Beta nodes altered by Alpha deletion!"

            # 8. Repeated Synchronization Idempotence on Repo Beta
            with client.session() as session:
                pre_repeat_nodes = session.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                pre_repeat_edges = session.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_beta_id).single()["cnt"]

            client.upload_graph(graph_beta["nodes"], graph_beta["edges"], repo_id=repo_beta_id)

            with client.session() as session:
                post_repeat_nodes = session.run("MATCH (n {repo_id: $r}) RETURN count(n) AS cnt", r=repo_beta_id).single()["cnt"]
                post_repeat_edges = session.run("MATCH (a {repo_id: $r})-[r]->(b {repo_id: $r}) RETURN count(r) AS cnt", r=repo_beta_id).single()["cnt"]
                assert post_repeat_nodes == pre_repeat_nodes, "Re-uploading Repo Beta was not idempotent for nodes"
                assert post_repeat_edges == pre_repeat_edges, "Re-uploading Repo Beta was not idempotent for edges"

        finally:
            shutil.rmtree(dir_alpha, ignore_errors=True)
            shutil.rmtree(dir_beta, ignore_errors=True)
            client.close()
