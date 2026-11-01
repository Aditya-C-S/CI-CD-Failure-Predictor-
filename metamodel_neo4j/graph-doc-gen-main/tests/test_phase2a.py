import os
import tempfile
import shutil
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from code_parser.extractor import Extractor
from maintenance.git_utils import get_commit_diff
from maintenance.diff_agent import update_graph_from_diff
from enrichment.cgl import ContinualGraphLearner


# =====================================================================
# 1. Extractor Smoke & Behavior Tests
# =====================================================================

class TestExtractorSmoke:
    @pytest.fixture
    def sample_repo(self):
        """Create a temporary multi-file Python repository with cross-file dependencies."""
        temp_dir = tempfile.mkdtemp()
        
        # module_a.py: Defines a class and a function
        file_a = os.path.join(temp_dir, "module_a.py")
        with open(file_a, "w", encoding="utf-8") as f:
            f.write(
                "class Service:\n"
                "    def process(self):\n"
                "        return 42\n\n"
                "def helper():\n"
                "    s = Service()\n"
                "    return s.process()\n"
            )

        # module_b.py: Imports and calls module_a helper
        file_b = os.path.join(temp_dir, "module_b.py")
        with open(file_b, "w", encoding="utf-8") as f:
            f.write(
                "from module_a import helper\n\n"
                "def run():\n"
                "    return helper()\n"
            )

        # ignored file
        ignored_file = os.path.join(temp_dir, "ignored.py")
        with open(ignored_file, "w", encoding="utf-8") as f:
            f.write("def ignored_func(): pass\n")

        # .gitignore
        gitignore = os.path.join(temp_dir, ".gitignore")
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write("ignored.py\n")

        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_parse_directory_node_types(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        node_types = {n["type"] for n in graph["nodes"]}
        assert "File" in node_types, "Graph should contain File nodes"
        assert "Class" in node_types, "Graph should contain Class nodes"
        assert "Function" in node_types, "Graph should contain Function nodes"

    def test_parse_directory_files_and_symbols(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        names = [n["properties"].get("name") for n in graph["nodes"]]
        assert "Service" in names, "Class Service must be extracted"
        assert "process" in names, "Method process must be extracted"
        assert "helper" in names, "Function helper must be extracted"
        assert "run" in names, "Function run must be extracted"

    def test_parse_directory_contains_edges(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        contains_edges = [e for e in graph["edges"] if e["type"] == "CONTAINS"]
        assert len(contains_edges) >= 4, "Should have CONTAINS edges for files and classes/functions"

    def test_parse_directory_calls_edges(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        call_edges = [e for e in graph["edges"] if e["type"] == "CALLS"]
        assert len(call_edges) >= 1, "Should have CALLS edges between calling functions and targets"

    def test_parse_directory_imports_edges(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        import_edges = [e for e in graph["edges"] if e["type"] == "IMPORTS"]
        assert len(import_edges) >= 1, "Should have IMPORTS edge between module_b and module_a"

    def test_gitignore_respected(self, sample_repo):
        extractor = Extractor()
        extractor.parse_directory(sample_repo)
        graph = extractor.get_graph()

        paths = [n["properties"].get("path", "") for n in graph["nodes"]]
        assert not any("ignored.py" in p for p in paths), "ignored.py should not be parsed due to .gitignore"

    def test_embeddings_optional_without_api_key(self, sample_repo):
        with patch.dict(os.environ, {}, clear=True):
            extractor = Extractor()
            assert extractor.embedder is None, "Embedder should be None when GEMINI_API_KEY is unset"
            extractor.parse_directory(sample_repo)
            graph = extractor.get_graph()
            assert len(graph["nodes"]) > 0, "Graph extraction should succeed without embeddings"
            # Every node embedding property should be None
            for n in graph["nodes"]:
                assert n["properties"].get("embedding") is None

    def test_parse_file_pass1_accepts_add_nodes_kwarg(self, sample_repo):
        extractor = Extractor()
        file_a = os.path.join(sample_repo, "module_a.py")
        # Should not raise TypeError: _parse_file_pass1() got an unexpected keyword argument 'add_nodes'
        extractor._parse_file_pass1(file_a, ".py", add_nodes=True)
        assert len(extractor.nodes) > 0


# =====================================================================
# 2. Git Diff Utilities Tests
# =====================================================================

class TestGetCommitDiff:
    @pytest.fixture
    def git_repo(self):
        """Initializes a temporary git repository with commit history."""
        temp_dir = tempfile.mkdtemp()
        
        # Git config
        subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_dir, check=True, capture_output=True)

        # Base commit (C1): create file1.py and to_delete.py and to_rename.py
        with open(os.path.join(temp_dir, "file1.py"), "w") as f:
            f.write("# file1 initial\n")
        with open(os.path.join(temp_dir, "to_delete.py"), "w") as f:
            f.write("# delete me\n")
        with open(os.path.join(temp_dir, "to_rename.py"), "w") as f:
            f.write("# rename me\n" * 20)

        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_dir, check=True, capture_output=True)
        c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        # Target commit (C2):
        # - modify file1.py
        # - delete to_delete.py
        # - rename to_rename.py -> renamed.py
        # - add new_file.py
        with open(os.path.join(temp_dir, "file1.py"), "a") as f:
            f.write("# modified\n")
        os.remove(os.path.join(temp_dir, "to_delete.py"))
        os.rename(os.path.join(temp_dir, "to_rename.py"), os.path.join(temp_dir, "renamed.py"))
        with open(os.path.join(temp_dir, "new_file.py"), "w") as f:
            f.write("# brand new\n")

        subprocess.run(["git", "add", "-A"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Second commit"], cwd=temp_dir, check=True, capture_output=True)
        c2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=temp_dir, capture_output=True, text=True, check=True).stdout.strip()

        yield temp_dir, c1, c2
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_diff_detects_added(self, git_repo):
        cwd, c1, c2 = git_repo
        diff = get_commit_diff(c1, c2, cwd=cwd)
        assert "new_file.py" in diff["added"]

    def test_diff_detects_modified(self, git_repo):
        cwd, c1, c2 = git_repo
        diff = get_commit_diff(c1, c2, cwd=cwd)
        assert "file1.py" in diff["modified"]

    def test_diff_detects_deleted(self, git_repo):
        cwd, c1, c2 = git_repo
        diff = get_commit_diff(c1, c2, cwd=cwd)
        assert "to_delete.py" in diff["deleted"]

    def test_diff_detects_renamed(self, git_repo):
        cwd, c1, c2 = git_repo
        diff = get_commit_diff(c1, c2, cwd=cwd)
        assert any(old == "to_rename.py" and new == "renamed.py" for old, new in diff["renamed"])

    def test_diff_same_commit_is_empty(self, git_repo):
        cwd, c1, _ = git_repo
        diff = get_commit_diff(c1, c1, cwd=cwd)
        assert diff == {"added": [], "modified": [], "deleted": [], "renamed": []}

    def test_diff_keys_structure(self, git_repo):
        cwd, c1, c2 = git_repo
        diff = get_commit_diff(c1, c2, cwd=cwd)
        for expected_key in ["added", "modified", "deleted", "renamed"]:
            assert expected_key in diff
            assert isinstance(diff[expected_key], list)


# =====================================================================
# 3. Diff Agent with Mocks (Incremental Graph Update)
# =====================================================================

class TestDiffAgentWithMocks:
    @pytest.fixture
    def git_workdir(self):
        """Temporary git repo with unstaged/uncommitted changes."""
        temp_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_dir, check=True, capture_output=True)

        # Commit an initial file
        fpath = os.path.join(temp_dir, "app.py")
        with open(fpath, "w") as f:
            f.write("def entry(): pass\n")
        subprocess.run(["git", "add", "."], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=temp_dir, check=True, capture_output=True)

        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("maintenance.diff_agent.Neo4jClient")
    def test_update_graph_no_changes(self, mock_client_cls, git_workdir):
        # When working tree is clean, update_graph_from_diff should gracefully exit early
        update_graph_from_diff(git_workdir)
        mock_client_cls.assert_not_called()

    @patch("maintenance.diff_agent.Neo4jClient")
    def test_update_graph_modified_file_calls_upload(self, mock_client_cls, git_workdir):
        # Modify app.py in working tree
        fpath = os.path.join(git_workdir, "app.py")
        with open(fpath, "a") as f:
            f.write("\ndef another_func(): return 1\n")

        # Mock the Neo4j client and its session
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_session = MagicMock()
        mock_instance.session.return_value.__enter__.return_value = mock_session
        mock_instance.driver.session.return_value.__enter__.return_value = mock_session
        mock_session.begin_transaction.return_value.__enter__.return_value = mock_session

        # Baseline graph queries return empty lists
        mock_session.run.return_value = []

        update_graph_from_diff(git_workdir)

        # Verify client calls
        assert mock_instance.upload_graph.called, "client.upload_graph should be called for changed files"
        assert mock_instance.close.called, "client.close should be called"
        # Verify detach delete query was issued for changed file
        executed_queries = [call.args[0] for call in mock_session.run.call_args_list if len(call.args) > 0]
        assert any("DETACH DELETE" in q for q in executed_queries)

    def test_update_graph_non_git_repo(self):
        non_git_dir = tempfile.mkdtemp()
        try:
            # Should not raise exception
            update_graph_from_diff(non_git_dir)
        finally:
            shutil.rmtree(non_git_dir, ignore_errors=True)


# =====================================================================
# 4. Continual Graph Learning (CGL) Utilities
# =====================================================================

class TestCGLUtilities:
    def test_partition_into_layers_connected(self):
        old_nodes = ["n1", "n2"]
        old_edges = [{"from": "n1", "to": "n2", "type": "CALLS"}]
        cgl = ContinualGraphLearner(old_nodes, old_edges)

        # Layer 1 connects to old_nodes; Layer 2 connects only to Layer 1 nodes
        new_edges = [
            {"from": "n1", "to": "n3", "type": "CALLS"},  # touches n1 -> layer 0
            {"from": "n3", "to": "n4", "type": "CALLS"},  # touches n3 -> layer 1
        ]
        layers = cgl.partition_into_layers(new_edges)
        assert len(layers) == 2
        assert layers[0] == [{"from": "n1", "to": "n3", "type": "CALLS"}]
        assert layers[1] == [{"from": "n3", "to": "n4", "type": "CALLS"}]

    def test_partition_into_layers_disconnected(self):
        old_nodes = ["n1"]
        cgl = ContinualGraphLearner(old_nodes, [])

        # Completely isolated new subgraph
        new_edges = [
            {"from": "x", "to": "y", "type": "CALLS"},
            {"from": "y", "to": "z", "type": "CALLS"},
        ]
        layers = cgl.partition_into_layers(new_edges)
        assert len(layers) == 1
        assert len(layers[0]) == 2

    def test_calculate_structural_hubs(self):
        cgl = ContinualGraphLearner([], [])
        # Star graph where center 'hub' connects to a, b, c
        edges = [
            {"from": "hub", "to": "a", "type": "CALLS"},
            {"from": "hub", "to": "b", "type": "CALLS"},
            {"from": "hub", "to": "c", "type": "CALLS"},
        ]
        weights = cgl.calculate_structural_hubs(edges)
        assert "hub" in weights
        assert weights["hub"] > weights["a"]
        assert weights["hub"] > weights["b"]
        assert weights["hub"] > weights["c"]

    def test_calculate_structural_hubs_empty(self):
        cgl = ContinualGraphLearner([], [])
        weights = cgl.calculate_structural_hubs([])
        assert weights == {}

    def test_incremental_distillation_loss(self):
        cgl = ContinualGraphLearner([], [])
        e_curr = [0.1, 0.2, 0.3]
        e_prev = [0.1, 0.2, 0.3]
        # Identical embeddings -> zero loss
        loss = cgl.incremental_distillation_loss(e_curr, e_prev, lambda_weight=1.0)
        assert abs(loss) < 1e-6

        # Different embeddings -> positive loss
        e_diff = [0.5, 0.8, 0.9]
        loss_diff = cgl.incremental_distillation_loss(e_curr, e_diff, lambda_weight=1.0)
        assert loss_diff > 0

    def test_maximum_mean_discrepancy(self):
        cgl = ContinualGraphLearner([], [])
        emb1 = [[1.0, 0.0], [0.0, 1.0]]
        # Identical distribution -> MMD approx 0
        mmd_same = cgl.maximum_mean_discrepancy(emb1, emb1)
        assert mmd_same < 1e-5

        # Different distribution -> MMD > 0
        emb2 = [[10.0, 10.0], [20.0, 20.0]]
        mmd_diff = cgl.maximum_mean_discrepancy(emb1, emb2)
        assert mmd_diff > 0


# =====================================================================
# 5. Live Neo4j Integration (BLOCKED when Neo4j is offline)
# =====================================================================

def is_neo4j_available():
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not (uri and user and password):
        return False
    try:
        from database.neo4j_client import Neo4jClient
        client = Neo4jClient()
        client.driver.verify_connectivity()
        client.close()
        return True
    except Exception:
        return False

class TestLiveNeo4jIntegration:
    @pytest.mark.skipif(not is_neo4j_available(), reason="BLOCKED: Live Neo4j instance is not running or credentials not configured in .env")
    def test_live_neo4j_connectivity(self):
        from database.neo4j_client import Neo4jClient
        client = Neo4jClient()
        client.driver.verify_connectivity()
        client.close()

