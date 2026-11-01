"""src/prediction/graph_impact.py

Deterministic Graph Impact Score (0 - 100) and Code Blast Radius Engine.
Calculates structural architecture impact independently from ML failure probability.
Supports both live Neo4j knowledge graphs and in-memory Tree-Sitter AST graphs.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ImpactLevel(str, Enum):
    """Categorical classification of structural change blast radius."""
    LOW = "LOW"            # 0.0 - 29.9: Localized leaf changes, minimal caller exposure
    MODERATE = "MODERATE"  # 30.0 - 64.9: Multi-file or multi-caller refactor
    HIGH = "HIGH"          # 65.0 - 100.0: Core abstractions, deep call hierarchies, wide blast radius
    UNKNOWN = "UNKNOWN"    # Insufficient graph evidence


@dataclass
class ImpactMetricsBreakdown:
    """Component metrics used in calculating the Graph Impact Score."""
    changed_files_count: int = 0
    total_repo_files: int = 0
    changed_files_ratio: float = 0.0
    changed_functions_count: int = 0
    downstream_callers_count: int = 0
    max_dependency_depth: int = 0
    high_fanin_functions_count: int = 0
    affected_test_files_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreComponentPoints:
    """Points assigned to each category in the transparent composite formula."""
    scope_points: float = 0.0          # Max 25.0 pts (files changed & repo ratio)
    caller_points: float = 0.0         # Max 30.0 pts (affected caller functions)
    depth_points: float = 0.0          # Max 15.0 pts (call propagation depth)
    centrality_points: float = 0.0     # Max 20.0 pts (high fan-in hubs modified)
    testing_points: float = 0.0        # Max 10.0 pts (test suite exposure)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GraphImpactResult:
    """Complete, self-describing Graph Impact Score result."""
    score: Optional[float]
    impact_level: str
    status: str                        # "CALCULATED" | "INSUFFICIENT_EVIDENCE"
    formula: str
    metrics: ImpactMetricsBreakdown
    components: ScoreComponentPoints
    evidence: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    engine_mode: str = "Neo4j Knowledge Graph"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["impact_level"] = self.impact_level
        return d


FORMULA_DOCUMENTATION = (
    "Graph Impact Score = min(100.0, Scope_Points (max 25) + Caller_Points (max 30) + "
    "Depth_Points (max 15) + Centrality_Points (max 20) + Testing_Points (max 10)). "
    "Scope = min(15, N_files * 3.0) + min(10, Ratio * 20.0); "
    "Callers = min(30, N_callers * 6.0); "
    "Depth = min(15, Max_Depth * 7.5); "
    "Centrality = min(20, High_Fanin_Modified * 10.0); "
    "Testing = min(10, Affected_Tests * 3.5)."
)


def calculate_graph_impact_score(
    changed_files: List[str],
    nodes: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    total_repo_files: Optional[int] = None,
    engine_mode: str = "Neo4j Knowledge Graph",
) -> GraphImpactResult:
    """
    Calculate deterministic Graph Impact Score from graph nodes and edges.

    Args:
        changed_files: List of file paths modified in the target commit.
        nodes: List of graph nodes (File, Class, Function).
        edges: List of graph edges (CONTAINS, CALLS, IMPORTS).
        total_repo_files: Optional count of all files in repository (for ratio calc).
        engine_mode: String identifying active graph backend.

    Returns:
        GraphImpactResult containing 0-100 score, evidence breakdown, and limitations.
    """
    clean_changed = [cf.replace("\\", "/").lstrip("/") for cf in changed_files if cf and cf.strip()]
    edges = edges or []

    # Check for insufficient evidence
    if not clean_changed or not nodes:
        return GraphImpactResult(
            score=None,
            impact_level=ImpactLevel.UNKNOWN.value,
            status="INSUFFICIENT_EVIDENCE",
            formula=FORMULA_DOCUMENTATION,
            metrics=ImpactMetricsBreakdown(),
            components=ScoreComponentPoints(),
            evidence=["Insufficient graph evidence: No code files or AST entities provided for analysis."],
            limitations=["Requires at least one parsed code file and AST extraction."],
            engine_mode=engine_mode,
        )

    # Index nodes
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    funcs_by_id: Dict[str, Dict[str, Any]] = {}
    files_by_id: Dict[str, Dict[str, Any]] = {}
    repo_file_paths: Set[str] = set()

    for n in nodes:
        props = n.get("properties", n)
        nid = props.get("id") or str(n.get("id", ""))
        ntype = n.get("type") or props.get("type", "Unknown")
        nodes_by_id[nid] = props
        if ntype == "Function":
            funcs_by_id[nid] = props
        elif ntype == "File":
            files_by_id[nid] = props
            fpath = props.get("rel_path") or props.get("file_path") or props.get("name") or ""
            if fpath:
                repo_file_paths.add(fpath.replace("\\", "/").lstrip("/"))

    # Identify directly changed function IDs
    changed_base_names = {cf.split("/")[-1] for cf in clean_changed}
    changed_func_ids: Set[str] = set()

    for fid, fprops in funcs_by_id.items():
        fpath = (fprops.get("rel_path") or fprops.get("file_path") or "").replace("\\", "/").lstrip("/")
        base_name = fprops.get("file_name") or (fpath.split("/")[-1] if fpath else "")
        if any(cf == fpath or cf.endswith(fpath) or fpath.endswith(cf) for cf in clean_changed) or (
            base_name and base_name in changed_base_names
        ):
            changed_func_ids.add(fid)

    # If no functions match changed files (e.g. pure doc/config files), evaluate scope only or insufficient
    if not changed_func_ids and not any(any(cf.endswith(ext) for ext in (".py", ".java", ".cpp", ".c", ".h", ".js", ".ts")) for cf in clean_changed):
        return GraphImpactResult(
            score=None,
            impact_level=ImpactLevel.UNKNOWN.value,
            status="INSUFFICIENT_EVIDENCE",
            formula=FORMULA_DOCUMENTATION,
            metrics=ImpactMetricsBreakdown(
                changed_files_count=len(clean_changed),
                total_repo_files=len(repo_file_paths) or len(clean_changed),
            ),
            components=ScoreComponentPoints(),
            evidence=[
                f"Changed files ({', '.join(clean_changed)}) contain no functions or AST definitions."
            ],
            limitations=["AST parsing is restricted to Python, Java, C++, and supported languages."],
            engine_mode=engine_mode,
        )

    # Compute incoming call degrees (Fan-in) across graph
    incoming_calls: Dict[str, Set[str]] = {}
    outgoing_calls: Dict[str, Set[str]] = {}

    for e in edges:
        if e.get("type") == "CALLS":
            src = e.get("from") or e.get("source")
            tgt = e.get("to") or e.get("target")
            if src and tgt:
                incoming_calls.setdefault(tgt, set()).add(src)
                outgoing_calls.setdefault(src, set()).add(tgt)

    # Identify callers calling changed functions
    affected_callers: Set[str] = set()
    high_fanin_modified = 0
    affected_tests: Set[str] = set()

    for c_fid in changed_func_ids:
        # Check fan-in
        callers = incoming_calls.get(c_fid, set())
        if len(callers) >= 5:
            high_fanin_modified += 1

        for clr in callers:
            if clr not in changed_func_ids:
                affected_callers.add(clr)
                clr_node = nodes_by_id.get(clr, {})
                clr_path = (clr_node.get("rel_path") or clr_node.get("file_path") or "").lower()
                if "test" in clr_path or "spec" in clr_path:
                    affected_tests.add(clr)

    # Compute maximum dependency depth (BFS up to 3 hops)
    max_depth = 0
    if changed_func_ids and affected_callers:
        max_depth = 1
        frontier = set(affected_callers)
        visited = set(changed_func_ids) | set(affected_callers)
        for depth_hop in (2, 3):
            next_frontier = set()
            for fn in frontier:
                for upstream in incoming_calls.get(fn, set()):
                    if upstream not in visited:
                        next_frontier.add(upstream)
                        visited.add(upstream)
            if next_frontier:
                max_depth = depth_hop
                frontier = next_frontier
            else:
                break

    # Quantitative Metrics
    n_files_changed = len(clean_changed)
    repo_files_count = max(total_repo_files or len(repo_file_paths), n_files_changed, 1)
    changed_ratio = min(1.0, n_files_changed / repo_files_count)
    n_fn_changed = len(changed_func_ids)
    n_callers = len(affected_callers)
    n_tests = len(affected_tests)

    # Score Components
    # 1. Scope (max 25): min(15, count * 3) + min(10, ratio * 20)
    scope_pts = min(15.0, n_files_changed * 3.0) + min(10.0, changed_ratio * 20.0)

    # 2. Callers (max 30): min(30, callers * 6.0)
    caller_pts = min(30.0, n_callers * 6.0)

    # 3. Depth (max 15): min(15, depth * 7.5)
    depth_pts = min(15.0, max_depth * 7.5)

    # 4. Centrality (max 20): min(20, high_fanin * 10.0)
    centrality_pts = min(20.0, high_fanin_modified * 10.0)

    # 5. Testing (max 10): min(10, tests * 3.5)
    testing_pts = min(10.0, n_tests * 3.5)

    raw_sum = scope_pts + caller_pts + depth_pts + centrality_pts + testing_pts
    final_score = min(100.0, round(raw_sum, 1))

    # Categorical level
    if final_score < 30.0:
        level = ImpactLevel.LOW.value
    elif final_score < 65.0:
        level = ImpactLevel.MODERATE.value
    else:
        level = ImpactLevel.HIGH.value

    # Build qualitative evidence
    evidence = []
    if n_files_changed > 0:
        evidence.append(f"Modified {n_files_changed} file(s) ({changed_ratio:.1%} of repo scope).")
    if n_fn_changed > 0:
        evidence.append(f"Directly altered {n_fn_changed} function(s) / method declaration(s).")
    if n_callers > 0:
        evidence.append(f"{n_callers} external caller function(s) directly invoke altered code.")
    else:
        evidence.append("No external functions directly invoke modified declarations (isolated change).")
    if max_depth > 1:
        evidence.append(f"Dependency propagation extends across {max_depth} calling hops.")
    if high_fanin_modified > 0:
        evidence.append(f"Modified {high_fanin_modified} high fan-in architectural hub(s) (>=5 incoming callers).")
    if n_tests > 0:
        evidence.append(f"{n_tests} test function(s) are in the direct call path of modified code.")

    # Limitations
    limitations = [
        "Dynamic Python reflection, getattr(), and eval() calls are not detectable via static AST.",
        "Cross-process HTTP and message bus RPC calls are excluded from the static in-process call graph.",
    ]

    metrics = ImpactMetricsBreakdown(
        changed_files_count=n_files_changed,
        total_repo_files=repo_files_count,
        changed_files_ratio=round(changed_ratio, 3),
        changed_functions_count=n_fn_changed,
        downstream_callers_count=n_callers,
        max_dependency_depth=max_depth,
        high_fanin_functions_count=high_fanin_modified,
        affected_test_files_count=n_tests,
    )

    components = ScoreComponentPoints(
        scope_points=round(scope_pts, 1),
        caller_points=round(caller_pts, 1),
        depth_points=round(depth_pts, 1),
        centrality_points=round(centrality_pts, 1),
        testing_points=round(testing_pts, 1),
    )

    return GraphImpactResult(
        score=final_score,
        impact_level=level,
        status="CALCULATED",
        formula=FORMULA_DOCUMENTATION,
        metrics=metrics,
        components=components,
        evidence=evidence,
        limitations=limitations,
        engine_mode=engine_mode,
    )
