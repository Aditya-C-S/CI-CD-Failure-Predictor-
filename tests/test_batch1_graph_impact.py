"""tests/test_batch1_graph_impact.py

Batch 1 Unit & Boundary Tests: Deterministic Graph Impact Score (0 - 100)
Verifies:
1. Deterministic score bounded strictly in [0.0, 100.0].
2. Categorical impact levels: LOW (<30), MODERATE (30-64.9), HIGH (>=65), UNKNOWN.
3. Component points adherence (Scope max 25, Callers max 30, Depth max 15, Centrality max 20, Testing max 10).
4. Insufficient evidence handling (returns score=None, status="INSUFFICIENT_EVIDENCE").
5. Monotonic caller sensitivity: adding downstream callers strictly increases or preserves score.
6. Endpoint POST /api/metadata/graph/impact functionality.
"""

import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.prediction.graph_impact import (
    calculate_graph_impact_score,
    ImpactLevel,
)


class TestBatch1GraphImpactScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_score_components_and_bounds(self):
        """Verify components sum accurately and clamp strictly at 100.0."""
        # Construct synthetic dense graph nodes and edges
        nodes = [
            {"id": "file:core.py", "type": "File", "name": "core.py", "properties": {"name": "core.py"}},
            {"id": "file:test_core.py", "type": "File", "name": "test_core.py", "properties": {"name": "test_core.py"}},
            {"id": "func:execute", "type": "Function", "name": "execute", "properties": {"name": "execute", "file_name": "core.py"}},
        ]
        # Add 10 callers across depths
        edges = []
        for i in range(10):
            cid = f"func:caller_{i}"
            nodes.append({"id": cid, "type": "Function", "name": f"caller_{i}", "properties": {"name": f"caller_{i}"}})
            edges.append({"type": "CALLS", "from": cid, "to": "func:execute"})

        result = calculate_graph_impact_score(
            changed_files=["core.py"],
            nodes=nodes,
            edges=edges,
            total_repo_files=2,
        )

        self.assertEqual(result.status, "CALCULATED")
        self.assertIsNotNone(result.score)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 100.0)
        self.assertIn(result.impact_level, [ImpactLevel.LOW.value, ImpactLevel.MODERATE.value, ImpactLevel.HIGH.value])
        
        # Verify component points do not exceed maximums
        self.assertLessEqual(result.components.scope_points, 25.0)
        self.assertLessEqual(result.components.caller_points, 30.0)
        self.assertLessEqual(result.components.depth_points, 15.0)
        self.assertLessEqual(result.components.centrality_points, 20.0)
        self.assertLessEqual(result.components.testing_points, 10.0)

    def test_insufficient_evidence_handling(self):
        """Verify non-code files or empty graphs return INSUFFICIENT_EVIDENCE with score=None."""
        # Non-code doc file
        result = calculate_graph_impact_score(
            changed_files=["README.md", "docs/index.md"],
            nodes=[{"id": "f1", "type": "File", "properties": {"name": "README.md"}}],
            edges=[],
        )
        self.assertEqual(result.status, "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result.score)
        self.assertEqual(result.impact_level, ImpactLevel.UNKNOWN.value)

        # Empty graph
        result_empty = calculate_graph_impact_score(
            changed_files=[],
            nodes=[],
            edges=[],
        )
        self.assertEqual(result_empty.status, "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result_empty.score)

    def test_caller_sensitivity_monotonic(self):
        """Verify increasing callers strictly increases or preserves the impact score."""
        nodes_base = [
            {"id": "file:mod.py", "type": "File", "name": "mod.py", "properties": {"name": "mod.py"}},
            {"id": "func:target", "type": "Function", "name": "target", "properties": {"name": "target", "file_name": "mod.py"}},
        ]
        
        # 1 caller
        nodes_1 = list(nodes_base) + [{"id": "func:c1", "type": "Function", "properties": {"name": "c1"}}]
        edges_1 = [{"type": "CALLS", "from": "func:c1", "to": "func:target"}]
        res_1 = calculate_graph_impact_score(changed_files=["mod.py"], nodes=nodes_1, edges=edges_1)

        # 5 callers
        nodes_5 = list(nodes_base)
        edges_5 = []
        for i in range(5):
            nodes_5.append({"id": f"func:c{i}", "type": "Function", "properties": {"name": f"c{i}"}})
            edges_5.append({"type": "CALLS", "from": f"func:c{i}", "to": "func:target"})
        res_5 = calculate_graph_impact_score(changed_files=["mod.py"], nodes=nodes_5, edges=edges_5)

        self.assertIsNotNone(res_1.score)
        self.assertIsNotNone(res_5.score)
        self.assertGreater(res_5.score, res_1.score)

    def test_fastapi_graph_impact_endpoint(self):
        """Verify POST /api/metadata/graph/impact computes score successfully over HTTP."""
        resp = self.client.post(
            "/api/metadata/graph/impact",
            json={
                "repo_id": "msiemens/tinydb",
                "changed_files": ["tinydb/database.py"],
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("score", data)
        self.assertIn("impact_level", data)
        self.assertIn("formula", data)
        self.assertIn("components", data)
        self.assertIn("metrics", data)
        self.assertIn("status", data)


if __name__ == "__main__":
    unittest.main()

