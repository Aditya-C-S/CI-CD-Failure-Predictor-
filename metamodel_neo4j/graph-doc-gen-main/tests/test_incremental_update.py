import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch, MagicMock
import pytest

from code_parser.extractor import Extractor
from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import get_commit_diff
from database.neo4j_client import Neo4jClient


# =====================================================================
# In-Memory Graph Simulator for Neo4j
# Faithfully simulates the Cypher queries executed by Neo4jClient and diff_agent
# =====================================================================

class InMemoryGraphDB:
    def __init__(self):
        self.nodes = {}  # id -> {type, properties}
        self.edges = set()  # set of (from, to, type)
        self.sync_state = {}  # repo_id -> dict

    def upload_graph(self, nodes, edges, repo_id=None, **kwargs):
        for n in nodes:
            n_id = n["properties"]["id"]
            if n_id not in self.nodes:
                self.nodes[n_id] = {"type": n["type"], "properties": dict(n["properties"])}
            else:
                self.nodes[n_id]["properties"].update(n["properties"])

        for e in edges:
            self.edges.add((e["from"], e["to"], e["type"]))

    def detach_delete(self, file_path=None, file_id=None):
        nodes_to_delete = set()
        for nid, data in self.nodes.items():
            props = data.get("properties", {})
            if (
                props.get("file_path") == file_path 
                or props.get("path") == file_path 
                or props.get("rel_path") == file_path 
                or props.get("id") == file_id 
                or nid == file_id
            ):
                nodes_to_delete.add(nid)

        for nid in nodes_to_delete:
            del self.nodes[nid]

        # DETACH DELETE removes all connected edges
        self.edges = {
            (src, tgt, rel)
            for (src, tgt, rel) in self.edges
            if src not in nodes_to_delete and tgt not in nodes_to_delete
        }

    def get_node_ids(self):
        return list(self.nodes.keys())

    def get_edge_dicts(self):
        return [{"from": src, "to": tgt, "type": rel} for (src, tgt, rel) in self.edges]


class MockQueryResult:
    def __init__(self, records=None):
        self._records = records or []

    def __iter__(self):
        return iter(self._records)

    def consume(self):
        return self

    def single(self):
        return self._records[0] if self._records else None


class MockSession:
    def __init__(self, db: InMemoryGraphDB):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def begin_transaction(self):
        return self

    def commit(self):
        pass

    def rollback(self):
        pass

    def run(self, query, **kwargs):
        q = query.strip()
        if "RETURN n.id AS id" in q and "MATCH (n)" in q:
            return MockQueryResult([{"id": nid} for nid in self.db.get_node_ids()])
        elif "RETURN a.id AS from" in q and ("MATCH (a)" in q or "MATCH (a)-" in q):
            return MockQueryResult([
                MagicMock(data=lambda e=edge: {"from": e["from"], "to": e["to"], "type": e["type"]})
                for edge in self.db.get_edge_dicts()
            ])
        elif "MATCH (n)" in q and ("Function" in q or "Class" in q) and "RETURN n.name AS name, n.id AS id" in q:
            changed_paths = [os.path.normpath(p) for p in kwargs.get("changed_file_paths", [])]
            changed_ids = kwargs.get("changed_file_ids", [])
            changed_rels = kwargs.get("changed_rel_paths", [])
            symbols = []
            for nid, data in self.db.nodes.items():
                if data.get("type") in ["Function", "Class"]:
                    props = data.get("properties", {})
                    fp = props.get("file_path")
                    norm_fp = os.path.normpath(fp) if fp else None
                    rel = props.get("rel_path")
                    if norm_fp not in changed_paths and nid not in changed_ids and rel not in changed_rels:
                        if props.get("name"):
                            symbols.append({"name": props["name"], "id": props["id"]})
            return MockQueryResult(symbols)
        elif "MATCH (caller)-[r:CALLS]->(callee)" in q and "RETURN DISTINCT" in q:
            changed_paths = [os.path.normpath(p) for p in kwargs.get("changed_file_paths", [])]
            changed_ids = kwargs.get("changed_file_ids", [])
            changed_rels = kwargs.get("changed_rel_paths", [])
            callers = set()
            for (src, tgt, rel) in self.db.edges:
                if rel == "CALLS":
                    tgt_data = self.db.nodes.get(tgt, {})
                    tgt_props = tgt_data.get("properties", {})
                    tgt_fp = tgt_props.get("file_path") or tgt_props.get("path")
                    tgt_rel = tgt_props.get("rel_path")
                    norm_tgt_fp = os.path.normpath(tgt_fp) if tgt_fp else None
                    if norm_tgt_fp in changed_paths or tgt in changed_ids or tgt_rel in changed_rels:
                        src_data = self.db.nodes.get(src, {})
                        src_props = src_data.get("properties", {})
                        src_fp = src_props.get("file_path") or src_props.get("path")
                        if src_fp:
                            callers.add(src_fp)
            return MockQueryResult([{"file_path": fp} for fp in callers])
        elif "DETACH DELETE n" in q:
            file_path = kwargs.get("file_path")
            file_id = kwargs.get("file_id")
            norm_fp = kwargs.get("norm_fp")
            norm_fid = kwargs.get("norm_fid")
            rel_path = kwargs.get("rel_path")
            scoped_fid = kwargs.get("scoped_fid")
            for fp, fid in [(file_path, file_id), (norm_fp, norm_fid), (rel_path, scoped_fid)]:
                if fp or fid:
                    self.db.detach_delete(file_path=fp, file_id=fid)
            return MockQueryResult([])
        elif "SyncState" in q:
            return MockQueryResult([{"id": kwargs.get("sync_id", "sync:test")}])
        return MockQueryResult([])


class MockNeo4jClient:
    def __init__(self, db: InMemoryGraphDB):
        self.db = db
        self.driver = MagicMock()
        self.driver.session.side_effect = lambda **kwargs: MockSession(self.db)

    def session(self):
        return MockSession(self.db)

    def upload_graph(self, nodes, edges, repo_id=None, **kwargs):
        self.db.upload_graph(nodes, edges, repo_id=repo_id, **kwargs)

    def ensure_constraints(self):
        pass

    def acquire_repo_lock(self, repo_id, tx):
        pass

    def record_sync_state(self, repo_id, target_sha, base_sha=None, status="SYNCED", commit_verified=True, **kwargs):
        state = {
            "id": f"repo:{repo_id}:sync",
            "repo_id": repo_id,
            "target_sha": target_sha,
            "base_sha": base_sha,
            "status": status,
            "commit_verified": commit_verified,
            "synced_at": 1000,
            "synced_at_iso": "2026-10-23T08:00:00Z",
            **kwargs,
        }
        self.db.sync_state[repo_id] = state
        return state

    def get_sync_state(self, repo_id):
        return self.db.sync_state.get(repo_id)

    def close(self):
        pass


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def repo_with_dependencies():
    """
    Creates a temporary git repository with two files having cross-file dependencies:
    - callee.py: defines compute()
    - caller.py: imports compute from callee and calls compute() in run()
    """
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
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_dir, check=True, capture_output=True)

    db = InMemoryGraphDB()
    # Populate DB with full initial parse
    ext = Extractor()
    ext.parse_directory(temp_dir)
    initial_graph = ext.get_graph()
    db.upload_graph(initial_graph["nodes"], initial_graph["edges"])

    yield temp_dir, db
    shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# Incremental Update Correctness Tests
# =====================================================================

class TestIncrementalUpdateScenarios:

    def test_modify_file_caller_loses_cross_file_calls(self, repo_with_dependencies):
        """
        Scenario 1: Modify an existing file (caller.py).
        Exposes Bug: Extractor only parses changed_files.
        Because callee.py is not parsed, compute is not in symbol_table.
        Result: caller.py loses CALLS edges to unchanged callee.py.
        """
        temp_dir, db = repo_with_dependencies
        caller_path = os.path.join(temp_dir, "caller.py")

        # Verify initial state has CALLS edge
        initial_calls = [e for e in db.edges if e[2] == "CALLS"]
        assert len(initial_calls) == 1, "Initial graph should have 1 CALLS edge"

        # Modify caller.py in working tree
        with open(caller_path, "a", encoding="utf-8") as f:
            f.write("\ndef extra():\n    return run()\n")

        # Run incremental update with mocked Neo4jClient
        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        # Compare incremental graph against full parse
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()
        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]

        inc_calls = [e for e in db.edges if e[2] == "CALLS"]

        # Full parse should have 2 CALLS edges: run->compute and extra->run
        assert len(full_calls) == 2, f"Full parse expected 2 CALLS edges, got {len(full_calls)}"

        # Check if the incremental update preserved the cross-file call run->compute
        cross_file_call_exists = any(
            "run" in src and "compute" in tgt for (src, tgt, rel) in inc_calls
        )
        assert cross_file_call_exists, (
            "Incremental update should preserve cross-file CALLS edge from caller.run to callee.compute! "
            f"Got: {inc_calls}"
        )
        assert len(inc_calls) == len(full_calls) == 2, (
            f"Incremental CALLS edges ({len(inc_calls)}) must match full parse ({len(full_calls)})"
        )

    def test_modify_callee_incoming_calls_deleted_by_detach_delete(self, repo_with_dependencies):
        """
        Scenario 5: Modify a function that is called by another, unchanged file.
        Verifies that modifying callee preserves incoming CALLS edge from unchanged caller,
        matching a full parse of the repository.
        """
        temp_dir, db = repo_with_dependencies
        callee_path = os.path.join(temp_dir, "callee.py")

        # Verify initial graph has CALLS edge
        assert len([e for e in db.edges if e[2] == "CALLS"]) == 1

        # Modify callee.py (callee changes, caller remains unchanged)
        with open(callee_path, "w", encoding="utf-8") as f:
            f.write("def compute():\n    return 100\n")

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        # Compare incremental graph with full parse
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()
        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]
        assert len(full_calls) == 1, "Full parse has 1 CALLS edge from caller to callee"

        inc_calls = [e for e in db.edges if e[2] == "CALLS"]
        incoming_call_preserved = any(
            "run" in src and "compute" in tgt for (src, tgt, rel) in inc_calls
        )
        assert incoming_call_preserved, (
            "Modifying callee should restore incoming CALLS edge from unchanged caller! "
            f"Got: {inc_calls}"
        )
        assert len(inc_calls) == len(full_calls) == 1, (
            f"Incremental CALLS edges ({len(inc_calls)}) must match full parse ({len(full_calls)})"
        )

    def test_remove_called_function_obsolete_relationships_disappear(self, repo_with_dependencies):
        """
        Requirement 4 & 5: When a called function is removed from callee.py,
        the obsolete CALLS edge must disappear and NOT be retained.
        """
        temp_dir, db = repo_with_dependencies
        callee_path = os.path.join(temp_dir, "callee.py")

        # Initial graph has CALLS edge from caller.run to callee.compute
        assert len([e for e in db.edges if e[2] == "CALLS"]) == 1

        # Remove compute() from callee.py and replace with a different function
        with open(callee_path, "w", encoding="utf-8") as f:
            f.write("def new_replacement():\n    return 999\n")

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        # Full parse has 0 CALLS edges because caller calls compute() which no longer exists
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()
        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]
        assert len(full_calls) == 0

        # Incremental graph must also have 0 CALLS edges (obsolete edge must not be blindly retained)
        inc_calls = [e for e in db.edges if e[2] == "CALLS"]
        assert len(inc_calls) == 0, (
            f"Obsolete relationship was retained! Expected 0 CALLS edges, got: {inc_calls}"
        )

    def test_add_new_python_file(self, repo_with_dependencies):
        """
        Scenario 2: Add a new Python file.
        Checks if the new file and its nodes are added to the graph.
        """
        temp_dir, db = repo_with_dependencies
        new_file_path = os.path.join(temp_dir, "new_service.py")
        with open(new_file_path, "w", encoding="utf-8") as f:
            f.write("def service_handler():\n    return True\n")

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        node_ids = db.get_node_ids()
        assert any("new_service.py" in nid for nid in node_ids), "New file node should exist in graph"
        assert any("service_handler" in nid for nid in node_ids), "New function node should exist in graph"

    def test_delete_python_file(self, repo_with_dependencies):
        """
        Scenario 3: Delete a Python file.
        Checks if deleted file nodes and its obsolete relationships are removed.
        """
        temp_dir, db = repo_with_dependencies
        callee_path = os.path.join(temp_dir, "callee.py")
        os.remove(callee_path)

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        node_ids = db.get_node_ids()
        assert not any("callee.py" in nid for nid in node_ids), (
            "Deleted file nodes should be removed from graph"
        )
        # All edges pointing to or from callee should be removed
        for (src, tgt, rel) in db.edges:
            assert "callee.py" not in src and "callee.py" not in tgt, (
                "Obsolete edges referencing deleted file must be removed"
            )

    def test_rename_python_file(self, repo_with_dependencies):
        """
        Scenario 4: Rename a Python file in working tree.
        Old file should be removed and new file should be added.
        """
        temp_dir, db = repo_with_dependencies
        callee_path = os.path.join(temp_dir, "callee.py")
        renamed_path = os.path.join(temp_dir, "renamed_callee.py")
        os.rename(callee_path, renamed_path)

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        node_ids = db.get_node_ids()
        assert not any("callee.py" in nid and "renamed" not in nid for nid in node_ids), (
            "Old file nodes should be removed"
        )
        assert any("renamed_callee.py" in nid for nid in node_ids), (
            "Renamed file node should be present"
        )

    def test_repeated_update_no_duplicate_nodes_or_edges(self, repo_with_dependencies):
        """
        Requirement 4: Verify duplicate nodes or edges are avoided when an update is repeated.
        """
        temp_dir, db = repo_with_dependencies
        new_file = os.path.join(temp_dir, "extra.py")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write("def helper_a(): pass\n")

        # Run update once
        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        count_nodes_1 = len(db.nodes)
        count_edges_1 = len(db.edges)

        # Run update a second time with exact same working tree state
        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        count_nodes_2 = len(db.nodes)
        count_edges_2 = len(db.edges)

        assert count_nodes_1 == count_nodes_2, "Repeated update must not create duplicate nodes"
        assert count_edges_1 == count_edges_2, "Repeated update must not create duplicate edges"

    def test_committed_changes_ignored_by_diff_agent(self, repo_with_dependencies):
        """
        Requirement 1: Verify whether the updater detects actual Git commits or only working-tree changes.
        diff_agent uses `git ls-files -mo`, which ignores committed changes.
        When a developer makes a Git commit, `update_graph_from_diff` sees 0 changes.
        """
        temp_dir, db = repo_with_dependencies
        callee_path = os.path.join(temp_dir, "callee.py")

        # Make a change and COMMIT it
        with open(callee_path, "a", encoding="utf-8") as f:
            f.write("\ndef committed_func(): pass\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Commit changes"], cwd=temp_dir, check=True, capture_output=True)

        # Run diff_agent
        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir)

        # Because git ls-files -mo returned empty, committed_func was never uploaded!
        node_ids = db.get_node_ids()
        committed_func_uploaded = any("committed_func" in nid for nid in node_ids)
        assert not committed_func_uploaded, (
            "Demonstrates working-tree fallback: update_graph_from_diff without SHAs only examines working tree."
        )


# =====================================================================
# Commit-Aware Incremental Update Tests (Phase 2A.3)
# =====================================================================

class TestCommitAwareIncrementalUpdate:
    @pytest.fixture
    def commit_repo_setup(self):
        """
        Creates a temporary Git repository with commit history and cross-file calls.
        Base commit (C1): callee.py defines compute(), caller.py calls compute().
        """
        temp_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_dir, check=True, capture_output=True)

        callee_path = os.path.join(temp_dir, "callee.py")
        caller_path = os.path.join(temp_dir, "caller.py")

        with open(callee_path, "w", encoding="utf-8") as f:
            f.write("def compute():\n    return 42\n")
        with open(caller_path, "w", encoding="utf-8") as f:
            f.write("from callee import compute\n\ndef run():\n    return compute()\n")

        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit C1"], cwd=temp_dir, check=True, capture_output=True)
        c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        db = InMemoryGraphDB()
        ext = Extractor()
        ext.parse_directory(temp_dir)
        db.upload_graph(ext.get_graph()["nodes"], ext.get_graph()["edges"])

        from maintenance.repo_utils import resolve_repo_id
        resolved_repo = resolve_repo_id(temp_dir)
        db.sync_state[resolved_repo] = {
            "id": f"repo:{resolved_repo}:sync",
            "repo_id": resolved_repo,
            "target_sha": c1,
            "base_sha": None,
            "status": "SYNCED",
            "commit_verified": True,
            "synced_at": 1000,
            "synced_at_iso": "2026-10-23T08:00:00Z"
        }

        yield temp_dir, db, c1
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_commit_diff_modified_file_on_clean_working_tree(self, commit_repo_setup):
        """
        Verify that commit-to-commit diff updates the graph when the working tree is completely clean.
        """
        temp_dir, db, c1 = commit_repo_setup
        caller_path = os.path.join(temp_dir, "caller.py")

        # Modify caller and COMMIT as C2
        with open(caller_path, "a", encoding="utf-8") as f:
            f.write("\ndef extra():\n    return run()\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Commit C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        # Verify working tree is clean
        status = subprocess.run(["git", "status", "--porcelain"], cwd=temp_dir, capture_output=True, text=True).stdout.strip()
        assert status == "", "Working tree must be clean"

        # Run updater with base and target SHAs
        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        # Compare with full parse of target state
        full_ext = Extractor()
        full_ext.parse_directory(temp_dir)
        full_graph = full_ext.get_graph()

        full_calls = [e for e in full_graph["edges"] if e["type"] == "CALLS"]
        inc_calls = [e for e in db.edges if e[2] == "CALLS"]

        assert len(inc_calls) == len(full_calls) == 2
        # Check both run->compute and extra->run exist
        assert any("run" in src and "compute" in tgt for (src, tgt, rel) in inc_calls)
        assert any("extra" in src and "run" in tgt for (src, tgt, rel) in inc_calls)

    def test_commit_diff_added_file(self, commit_repo_setup):
        """
        Verify added file in commit C2 is correctly uploaded to graph on clean working tree.
        """
        temp_dir, db, c1 = commit_repo_setup
        service_path = os.path.join(temp_dir, "new_service.py")

        with open(service_path, "w", encoding="utf-8") as f:
            f.write("def handle_request():\n    return True\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add service C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        node_ids = db.get_node_ids()
        assert any("new_service.py" in nid for nid in node_ids)
        assert any("handle_request" in nid for nid in node_ids)

    def test_commit_diff_deleted_file(self, commit_repo_setup):
        """
        Verify deleted file in commit C2 is pruned and obsolete edges are removed.
        """
        temp_dir, db, c1 = commit_repo_setup
        callee_path = os.path.join(temp_dir, "callee.py")

        subprocess.run(["git", "rm", "callee.py"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Delete callee C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        node_ids = db.get_node_ids()
        assert not any("callee.py" in nid for nid in node_ids), "callee.py nodes should be deleted"

        # Edge from caller to deleted callee must be gone
        inc_calls = [e for e in db.edges if e[2] == "CALLS"]
        assert len(inc_calls) == 0, "Obsolete edge to deleted callee must be pruned"

    def test_commit_diff_renamed_file(self, commit_repo_setup):
        """
        Verify renamed file in commit C2 is tracked, old nodes pruned, new nodes uploaded,
        and inbound caller re-linked to the new file.
        """
        temp_dir, db, c1 = commit_repo_setup
        subprocess.run(["git", "mv", "callee.py", "renamed_callee.py"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Rename callee C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        node_ids = db.get_node_ids()
        assert not any("callee.py" in nid and "renamed" not in nid for nid in node_ids), "Old file nodes must be gone"
        assert any("renamed_callee.py" in nid for nid in node_ids), "New file nodes must be present"

        inc_calls = [e for e in db.edges if e[2] == "CALLS"]
        # Caller should be re-linked to renamed_callee.compute
        assert any("run" in src and "renamed_callee" in tgt for (src, tgt, rel) in inc_calls), (
            f"Caller should be re-linked to renamed callee. Edges: {inc_calls}"
        )

    def test_commit_diff_repeated_update_no_duplicates(self, commit_repo_setup):
        """
        Verify running commit-diff incremental update twice does not create duplicate nodes or edges.
        """
        temp_dir, db, c1 = commit_repo_setup
        with open(os.path.join(temp_dir, "caller.py"), "a", encoding="utf-8") as f:
            f.write("\ndef another(): pass\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Commit C2"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        count_nodes_1 = len(db.nodes)
        count_edges_1 = len(db.edges)

        with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
            update_graph_from_diff(temp_dir, base_sha=c1, target_sha=c2)

        count_nodes_2 = len(db.nodes)
        count_edges_2 = len(db.edges)

        assert count_nodes_1 == count_nodes_2, "Duplicate nodes created on repeated commit update"
        assert count_edges_1 == count_edges_2, "Duplicate edges created on repeated commit update"

    def test_invalid_commit_references_rejected(self, commit_repo_setup):
        """
        Requirement 5: Reject invalid commit references with a clear error rather than reporting a successful update.
        """
        temp_dir, db, c1 = commit_repo_setup

        # Non-existent commit reference
        with pytest.raises(ValueError, match="Invalid commit reference"):
            with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
                update_graph_from_diff(temp_dir, base_sha="bad_sha_0000000", target_sha=c1)

        # Only one SHA provided
        with pytest.raises(ValueError, match="Both base_sha and target_sha must be provided"):
            with patch("maintenance.diff_agent.Neo4jClient", return_value=MockNeo4jClient(db)):
                update_graph_from_diff(temp_dir, base_sha=c1, target_sha=None)



# =====================================================================
# Safe Live Neo4j Test (Strictly Isolated, No Data Loss)
# =====================================================================

class TestLiveNeo4jSafetyVerification:
    def test_live_neo4j_safe_quarantine_verification(self):
        """
        Verifies against live Neo4j that temporary test nodes can be isolated,
        and guarantees the user's existing database nodes are completely untouched.
        """
        try:
            client = Neo4jClient()
            client.driver.verify_connectivity()
        except Exception:
            pytest.skip("Live Neo4j instance not available")

        # 1. Count existing nodes in user's database
        with client.session() as session:
            res = session.run("MATCH (n) RETURN count(n) AS cnt").single()
            initial_count = res["cnt"]

        # 2. Upload a strictly quarantined test node
        test_file_path = "C:/TEST_QUARANTINE_ISOLATION_DO_NOT_DELETE/sample.py"
        test_node = {
            "type": "File",
            "properties": {"id": f"file:{test_file_path}", "file_path": test_file_path, "name": "sample.py"}
        }
        client.upload_graph([test_node], [])

        # 3. Verify node was added
        with client.session() as session:
            res = session.run("MATCH (n) RETURN count(n) AS cnt").single()
            assert res["cnt"] == initial_count + 1

        # 4. Safely remove ONLY the quarantined test node
        with client.session() as session:
            session.run(
                "MATCH (n) WHERE n.file_path = $fp DETACH DELETE n",
                fp=test_file_path
            )

        # 5. Verify user's initial count is exactly restored
        with client.session() as session:
            res = session.run("MATCH (n) RETURN count(n) AS cnt").single()
            final_count = res["cnt"]
            assert final_count == initial_count, "User database nodes must remain untouched"

        client.close()
