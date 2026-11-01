import os
import shutil
import subprocess
import tempfile
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from database.neo4j_client import Neo4jClient
from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import (
    resolve_commit_sha,
    get_head_commit_sha,
    check_working_tree_clean,
    is_git_repository,
    CommitProvenanceError,
    CommitMismatchError,
    BaseCommitMismatchError,
    WorkingTreeDirtyError,
)
from code_parser.extractor import Extractor


# =====================================================================
# Fixtures for Temporary Deterministic Git Repositories
# =====================================================================

@pytest.fixture
def temp_git_repo():
    """
    Creates a temporary Git repository with 3 deterministic commits:
    - C1: initial commit with module_a.py (defines func_a) and module_b.py (calls func_a)
    - C2: modified module_a.py (adds func_a2), adds module_c.py
    - C3: modified module_b.py (adds func_b2)
    """
    temp_dir = tempfile.mkdtemp()
    
    def run_git(*args):
        res = subprocess.run(["git"] + list(args), cwd=temp_dir, capture_output=True, text=True, check=True)
        return res.stdout.strip()

    run_git("init")
    run_git("config", "user.name", "AuditUser")
    run_git("config", "user.email", "audit@example.com")

    # C1
    with open(os.path.join(temp_dir, "module_a.py"), "w", encoding="utf-8") as f:
        f.write("def func_a():\n    return 'alpha'\n")
    with open(os.path.join(temp_dir, "module_b.py"), "w", encoding="utf-8") as f:
        f.write("from module_a import func_a\n\ndef func_b():\n    return func_a()\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit 1")
    c1 = run_git("rev-parse", "HEAD")

    # C2
    with open(os.path.join(temp_dir, "module_a.py"), "a", encoding="utf-8") as f:
        f.write("\ndef func_a2():\n    return 'alpha2'\n")
    with open(os.path.join(temp_dir, "module_c.py"), "w", encoding="utf-8") as f:
        f.write("def func_c():\n    return 'gamma'\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit 2")
    c2 = run_git("rev-parse", "HEAD")

    # C3
    with open(os.path.join(temp_dir, "module_b.py"), "a", encoding="utf-8") as f:
        f.write("\ndef func_b2():\n    return 'beta2'\n")
    run_git("add", ".")
    run_git("commit", "-m", "Commit 3")
    c3 = run_git("rev-parse", "HEAD")

    yield temp_dir, c1, c2, c3
    shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# Unit Tests (Mocked Neo4j Client)
# =====================================================================

class TestCommitProvenanceUnit:
    """
    Deterministic unit tests validating provenance verification logic,
    base-SHA consistency, working tree dirty detection across all parsed files,
    error contracts, and rollback preservation using mocks.
    """

    def test_scenario_1_successful_synchronization_target_sha(self, temp_git_repo):
        """1. Successful synchronization at requested target SHA when base SHA matches."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        mock_db = {}
        mock_client = MagicMock()
        mock_tx = MagicMock()
        mock_session = MagicMock()
        mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx
        mock_client.session.return_value.__enter__.return_value = mock_session

        # Seed existing sync state matching canonical base C1
        mock_client.get_sync_state.return_value = {
            "id": "repo:test:unit:repo:sync",
            "repo_id": "test:unit:repo",
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        def fake_record(repo_id, target_sha, base_sha=None, **kwargs):
            mock_db[repo_id] = {
                "repo_id": repo_id,
                "target_sha": target_sha,
                "base_sha": base_sha,
                "status": "SYNCED",
                "commit_verified": True,
                "synced_at_iso": "2026-10-23T08:00:00Z"
            }
            return mock_db[repo_id]

        mock_client.record_sync_state.side_effect = fake_record

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            res = update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:unit:repo")

        assert res["status"] == "SUCCESS"
        assert res["commit_verified"] is True
        assert res["target_sha"] == c2
        assert res["base_sha"] == c1
        assert res["files_parsed"] > 0
        assert mock_tx.commit.called

    def test_scenario_1_base_sha_missing_prior_state_fails_closed(self, temp_git_repo):
        """1a. Fail closed if no prior SyncState exists when incremental update is requested."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = None

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(BaseCommitMismatchError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:unit:repo")

        assert "no prior verified SyncState exists" in str(exc_info.value)

    def test_scenario_1_base_sha_mismatch_fails_closed(self, temp_git_repo):
        """1b. Fail closed if graph is at commit A (c1) but caller requests diff from B (c2) to C (c3)."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c3], cwd=repo_dir, check=True, capture_output=True)

        mock_client = MagicMock()
        # Graph is at c1, but diff requests c2..c3
        mock_client.get_sync_state.return_value = {
            "id": "repo:test:unit:repo:sync",
            "repo_id": "test:unit:repo",
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(BaseCommitMismatchError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c2, target_sha=c3, repo_id="test:unit:repo")

        assert exc_info.value.current_graph_sha == c1
        assert exc_info.value.requested_base_sha == c2
        assert "does not match requested base_sha" in str(exc_info.value)

    def test_scenario_2_head_not_matching_target_sha(self, temp_git_repo):
        """2. HEAD not matching target_sha fails closed."""
        repo_dir, c1, c2, c3 = temp_git_repo
        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = {
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(CommitMismatchError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:unit:repo")

        assert exc_info.value.head_sha == c3
        assert exc_info.value.target_sha == c2

    def test_scenario_3_dirty_working_tree_files(self, temp_git_repo):
        """3. Dirty relevant changed working-tree files fail closed before graph mutation."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        with open(os.path.join(repo_dir, "module_a.py"), "a", encoding="utf-8") as f:
            f.write("\n# uncommitted change\n")

        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = {
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(WorkingTreeDirtyError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:unit:repo")

        assert any("module_a.py" in f for f in exc_info.value.dirty_files)

    def test_scenario_3_dirty_affected_caller_fails_closed(self, temp_git_repo):
        """3b. Dirty affected caller (unchanged in git diff, but parsed) fails closed."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        # module_b.py is an affected caller calling func_a in module_a.py
        # Dirty module_b.py (uncommitted change)
        with open(os.path.join(repo_dir, "module_b.py"), "a", encoding="utf-8") as f:
            f.write("\n# dirty caller edit\n")

        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = {
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        # Mock caller query so module_b.py is returned as an affected caller
        mock_session = MagicMock()
        mock_client.session.return_value.__enter__.return_value = mock_session
        caller_path = os.path.join(repo_dir, "module_b.py")
        mock_session.run.side_effect = [
            [],  # nodes
            [],  # edges
            [],  # symbols
            [{"file_path": caller_path}],  # affected caller
        ]

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(WorkingTreeDirtyError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:unit:repo")

        assert any("module_b.py" in f for f in exc_info.value.dirty_files)

    def test_scenario_3_untracked_source_file_fails_closed(self, temp_git_repo):
        """3c. Untracked file in relevant parsed source paths fails closed."""
        repo_dir, c1, c2, c3 = temp_git_repo
        untracked_file = os.path.join(repo_dir, "untracked_helper.py")
        with open(untracked_file, "w") as f:
            f.write("def helper(): pass\n")

        with pytest.raises(WorkingTreeDirtyError) as exc_info:
            check_working_tree_clean(repo_dir, file_paths=["untracked_helper.py"])

        assert any("untracked_helper.py" in f for f in exc_info.value.dirty_files)

    def test_scenario_4_invalid_or_unavailable_git_shas(self, temp_git_repo):
        """4. Invalid or unavailable Git SHAs are rejected before modifying Neo4j."""
        repo_dir, c1, c2, c3 = temp_git_repo
        mock_client = MagicMock()

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(ValueError, match="Invalid commit reference"):
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha="nonexistent_sha_xyz", repo_id="test:repo")

            with pytest.raises(ValueError, match="Both base_sha and target_sha must be provided"):
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=None, repo_id="test:repo")

    def test_scenario_5_failure_during_parsing_aborts_before_transaction(self, temp_git_repo):
        """5. Failure during AST extraction prevents starting transaction or modifying DB."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = {
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client), \
             patch.object(Extractor, "_execute_pass2", side_effect=RuntimeError("Parsing error simulated")):
            with pytest.raises(RuntimeError, match="Parsing error simulated"):
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:repo")

        assert not mock_client.upload_graph.called
        assert not mock_client.record_sync_state.called

    def test_scenario_6_rollback_preserves_previous_sync_state(self, temp_git_repo):
        """6. Rollback preserves previous successful state when graph write fails."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        mock_client = MagicMock()
        mock_tx = MagicMock()
        mock_session = MagicMock()
        mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx
        mock_client.session.return_value.__enter__.return_value = mock_session

        mock_client.get_sync_state.return_value = {
            "target_sha": c1,
            "status": "SYNCED",
            "commit_verified": True
        }
        mock_client.upload_graph.side_effect = RuntimeError("Database upload failure simulated")

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Database upload failure simulated"):
                update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id="test:repo")

        assert not mock_tx.commit.called
        assert not mock_client.record_sync_state.called

    def test_scenario_7_repeated_synchronization_same_sha(self, temp_git_repo):
        """7. Repeated synchronization of same SHA returns NO_CHANGES when graph is verified at target."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)

        mock_client = MagicMock()
        mock_client.get_sync_state.return_value = {
            "target_sha": c2,
            "status": "SYNCED",
            "commit_verified": True,
            "synced_at_iso": "2026-10-23T08:00:00Z"
        }

        with patch("maintenance.diff_agent.Neo4jClient", return_value=mock_client):
            res = update_graph_from_diff(repo_dir, base_sha=c2, target_sha=c2, repo_id="test:repo")

        assert res["status"] == "NO_CHANGES"
        assert res["commit_verified"] is True
        assert res["target_sha"] == c2
        assert res["files_parsed"] == 0

    def test_scenario_10_initial_ingestion_provenance_rules(self, temp_git_repo):
        """10. Initial ingestion establishes provenance on clean Git repo, rejects dirty/non-git."""
        repo_dir, c1, c2, c3 = temp_git_repo
        
        assert is_git_repository(repo_dir) is True
        assert check_working_tree_clean(repo_dir) is True
        head_sha = get_head_commit_sha(repo_dir)
        assert head_sha == c3

        temp_non_git = tempfile.mkdtemp()
        try:
            assert is_git_repository(temp_non_git) is False
        finally:
            shutil.rmtree(temp_non_git, ignore_errors=True)

        with open(os.path.join(repo_dir, "uncommitted.txt"), "w") as f:
            f.write("dirty")
        with pytest.raises(WorkingTreeDirtyError):
            check_working_tree_clean(repo_dir)


# =====================================================================
# Live Neo4j Integration Tests (Targeting isolated 'graphdoc' database)
# =====================================================================

class TestCommitProvenanceLiveNeo4j:
    """
    Live integration tests executed against the isolated 'graphdoc' Neo4j database.
    Verifies actual transaction commit, rollback, concurrency locking, constraint enforcement,
    and repository isolation.
    """

    @pytest.fixture(autouse=True)
    def setup_live_env(self):
        """Guarantees tests only run on isolated 'graphdoc'."""
        client = Neo4jClient()
        assert client.database == "graphdoc", (
            f"SAFETY VIOLATION: Configured database must be 'graphdoc', found '{client.database}'!"
        )
        assert not client.is_protected_database(), (
            f"SAFETY VIOLATION: 'graphdoc' must not be flagged as protected database!"
        )
        client.ensure_constraints()
        client.close()

    def test_scenario_11_confirmation_configured_database_is_graphdoc(self):
        """11. Confirmation that configured database is 'graphdoc' and legacy neo4j is safe."""
        client = Neo4jClient()
        assert client.database == "graphdoc"
        assert client.is_protected_database() is False
        client.close()

        c_legacy = Neo4jClient(database="neo4j")
        with c_legacy.session() as s:
            cnt = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
            assert cnt == 99, f"SAFETY VIOLATION: legacy neo4j database node count altered: {cnt} != 99!"
        c_legacy.close()

    def test_scenario_1_live_successful_sync_and_syncstate_retrieval(self, temp_git_repo):
        """1 & 2. Live Neo4j synchronization, SyncState creation, and client retrieval."""
        repo_dir, c1, c2, c3 = temp_git_repo
        live_repo_id = "test:live:sync:repo1"

        client = Neo4jClient()
        try:
            client.clear_repository(live_repo_id)

            # 1. Initial ingestion at C1
            subprocess.run(["git", "checkout", c1], cwd=repo_dir, check=True, capture_output=True)
            ext = Extractor(repo_id=live_repo_id)
            ext.parse_directory(repo_dir, repo_id=live_repo_id)
            g = ext.get_graph()
            client.upload_graph(g["nodes"], g["edges"], repo_id=live_repo_id)
            client.record_sync_state(
                repo_id=live_repo_id,
                target_sha=c1,
                base_sha=None,
                status="SYNCED",
                commit_verified=True,
                nodes_count=len(g["nodes"]),
                edges_count=len(g["edges"])
            )

            # 2. Checkout C2 and run incremental diff from C1 to C2
            subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)
            res = update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id=live_repo_id)
            assert res["status"] == "SUCCESS"
            assert res["commit_verified"] is True
            assert res["target_sha"] == c2
            assert res["base_sha"] == c1

            # Retrieve SyncState record using Neo4jClient method
            sync_state = client.get_sync_state(live_repo_id)
            assert sync_state is not None
            assert sync_state["repo_id"] == live_repo_id
            assert sync_state["target_sha"] == c2
            assert sync_state["base_sha"] == c1
            assert sync_state["status"] == "SYNCED"
            assert sync_state["commit_verified"] is True
            assert sync_state["files_parsed"] >= 1
            assert sync_state["nodes_count"] >= 1
        finally:
            client.clear_repository(live_repo_id)
            client.close()

    def test_scenario_1_live_base_sha_mismatch_fails_closed(self, temp_git_repo):
        """1c. Live Neo4j rejects incremental sync when graph is at C1 but caller requests C2..C3."""
        repo_dir, c1, c2, c3 = temp_git_repo
        live_repo_id = "test:live:base:mismatch"

        client = Neo4jClient()
        try:
            client.clear_repository(live_repo_id)

            # Ingest initial state at C1
            subprocess.run(["git", "checkout", c1], cwd=repo_dir, check=True, capture_output=True)
            client.record_sync_state(repo_id=live_repo_id, target_sha=c1, status="SYNCED", commit_verified=True)

            # Checkout C3 and request incremental diff C2..C3 (graph is at C1, not C2)
            subprocess.run(["git", "checkout", c3], cwd=repo_dir, check=True, capture_output=True)

            with pytest.raises(BaseCommitMismatchError) as exc_info:
                update_graph_from_diff(repo_dir, base_sha=c2, target_sha=c3, repo_id=live_repo_id)

            assert exc_info.value.current_graph_sha == c1
            assert exc_info.value.requested_base_sha == c2

            # Verify SyncState was NOT modified
            state = client.get_sync_state(live_repo_id)
            assert state["target_sha"] == c1
        finally:
            client.clear_repository(live_repo_id)
            client.close()

    def test_scenario_6_live_rollback_preserves_previous_sync_state(self, temp_git_repo):
        """6. Live rollback preserves previous SyncState when upload fails."""
        repo_dir, c1, c2, c3 = temp_git_repo
        live_repo_id = "test:live:rollback:repo"

        client = Neo4jClient()
        try:
            client.clear_repository(live_repo_id)

            # 1. Initial ingestion at C1
            subprocess.run(["git", "checkout", c1], cwd=repo_dir, check=True, capture_output=True)
            client.record_sync_state(repo_id=live_repo_id, target_sha=c1, status="SYNCED", commit_verified=True)

            # 2. Sync to C2 succeeds
            subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)
            res1 = update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id=live_repo_id)
            assert res1["status"] == "SUCCESS"
            state1 = client.get_sync_state(live_repo_id)
            assert state1["target_sha"] == c2

            # 3. Checkout C3
            subprocess.run(["git", "checkout", c3], cwd=repo_dir, check=True, capture_output=True)

            # Inject upload failure inside transaction
            with patch.object(Neo4jClient, "upload_graph", side_effect=RuntimeError("Simulated write failure")):
                with pytest.raises(RuntimeError, match="Simulated write failure"):
                    update_graph_from_diff(repo_dir, base_sha=c2, target_sha=c3, repo_id=live_repo_id)

            # 4. Verify SyncState still preserves C2, NOT C3
            state2 = client.get_sync_state(live_repo_id)
            assert state2["target_sha"] == c2
            assert state2["status"] == "SYNCED"
        finally:
            client.clear_repository(live_repo_id)
            client.close()

    def test_scenario_8_live_concurrency_locking(self):
        """8. Per-repository write lock serializes concurrent transactions for same repo_id."""
        repo_id = "test:live:concurrency:repo"
        client1 = Neo4jClient()
        client2 = Neo4jClient()

        try:
            client1.clear_repository(repo_id)

            lock_acquired = threading.Event()
            execution_order = []

            def hold_lock_worker():
                with client1.session() as s1:
                    with s1.begin_transaction() as tx1:
                        client1.acquire_repo_lock(repo_id, tx1)
                        execution_order.append("tx1_locked")
                        lock_acquired.set()
                        time.sleep(1.0)
                        tx1.commit()
                        execution_order.append("tx1_committed")

            def wait_for_lock_worker():
                lock_acquired.wait(timeout=5.0)
                with client2.session() as s2:
                    with s2.begin_transaction() as tx2:
                        client2.acquire_repo_lock(repo_id, tx2)
                        execution_order.append("tx2_locked")
                        tx2.commit()

            t1 = threading.Thread(target=hold_lock_worker)
            t2 = threading.Thread(target=wait_for_lock_worker)

            t1.start()
            t2.start()

            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

            assert execution_order == ["tx1_locked", "tx1_committed", "tx2_locked"], (
                f"Expected tx2 to wait for tx1 to release repo lock, got: {execution_order}"
            )
        finally:
            client1.clear_repository(repo_id)
            client1.close()
            client2.close()

    def test_scenario_3_live_concurrent_initial_sync_creates_single_syncstate(self):
        """3. Concurrent initial syncs for same repo_id create exactly 1 SyncState node (uniqueness constraint)."""
        repo_id = "test:live:concurrent:initial:sync"
        client = Neo4jClient()
        client.ensure_constraints()

        try:
            client.clear_repository(repo_id)

            errors = []
            def sync_worker(sha_val):
                c = Neo4jClient()
                try:
                    with c.session() as s:
                        with s.begin_transaction() as tx:
                            c.acquire_repo_lock(repo_id, tx)
                            c.record_sync_state(repo_id, target_sha=sha_val, tx=tx)
                            tx.commit()
                except Exception as e:
                    errors.append(e)
                finally:
                    c.close()

            t1 = threading.Thread(target=sync_worker, args=("sha_worker_1",))
            t2 = threading.Thread(target=sync_worker, args=("sha_worker_2",))

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Verify exactly ONE SyncState node exists in Neo4j
            with client.session() as s:
                cnt = s.run(
                    "MATCH (s:SyncState {id: $id}) RETURN count(s) AS cnt",
                    id=f"repo:{repo_id}:sync"
                ).single()["cnt"]
                assert cnt == 1, f"Concurrency error: expected 1 SyncState node, found {cnt}!"
        finally:
            client.clear_repository(repo_id)
            client.close()

    def test_scenario_9_live_isolation_between_two_repositories(self, temp_git_repo):
        """9. Isolation between two different repo_id values."""
        repo_dir, c1, c2, c3 = temp_git_repo
        subprocess.run(["git", "checkout", c1], cwd=repo_dir, check=True, capture_output=True)

        repo_a = "test:live:repo:alpha"
        repo_b = "test:live:repo:beta"

        client = Neo4jClient()
        try:
            client.clear_repository(repo_a)
            client.clear_repository(repo_b)

            # Ingest initial C1 into both repos
            client.record_sync_state(repo_id=repo_a, target_sha=c1, status="SYNCED", commit_verified=True)
            client.record_sync_state(repo_id=repo_b, target_sha=c1, status="SYNCED", commit_verified=True)

            # Ingest C1 -> C2 into repo_a only
            subprocess.run(["git", "checkout", c2], cwd=repo_dir, check=True, capture_output=True)
            res_a = update_graph_from_diff(repo_dir, base_sha=c1, target_sha=c2, repo_id=repo_a)
            assert res_a["status"] == "SUCCESS"

            # Verify SyncState records are isolated
            state_a = client.get_sync_state(repo_a)
            state_b = client.get_sync_state(repo_b)

            assert state_a["target_sha"] == c2
            assert state_b["target_sha"] == c1

            # Clearing repo_a does not touch repo_b
            client.clear_repository(repo_a)
            state_b_recheck = client.get_sync_state(repo_b)
            assert state_b_recheck is not None
            assert state_b_recheck["target_sha"] == c1
        finally:
            client.clear_repository(repo_a)
            client.clear_repository(repo_b)
            client.close()
