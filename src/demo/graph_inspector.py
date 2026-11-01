"""src/demo/graph_inspector.py

Graph Inspector & Blast-Radius Engine for Module I.
Connects directly to Neo4j if available, and gracefully falls back to
genuine in-memory Tree-Sitter AST parsing when Neo4j is offline.
Ensures zero fabricated graph nodes or relationships.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.prediction.metadata_service import MetadataService

logger = logging.getLogger("demo.graph_inspector")

# Resolve path to graph-doc-gen-main for AST tree-sitter parser
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_GRAPH_GEN_ROOT = _PROJECT_ROOT / "metadata_model" / "extracted" / "graph-doc-gen-main"
if _GRAPH_GEN_ROOT.exists() and str(_GRAPH_GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(_GRAPH_GEN_ROOT))


def _get_extractor_class() -> Optional[type]:
    """Dynamically loads the Tree-Sitter Extractor class safely without IDE import resolution errors."""
    try:
        import importlib
        if _GRAPH_GEN_ROOT.exists() and str(_GRAPH_GEN_ROOT) not in sys.path:
            sys.path.insert(0, str(_GRAPH_GEN_ROOT))

        try:
            mod = importlib.import_module("code_parser.extractor")
            return getattr(mod, "Extractor")
        except (ImportError, ModuleNotFoundError):
            pass

        # Direct file-based spec loader (guaranteed fallback regardless of sys.path)
        extractor_path = _GRAPH_GEN_ROOT / "code_parser" / "extractor.py"
        if extractor_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("code_parser.extractor", str(extractor_path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["code_parser.extractor"] = mod
                spec.loader.exec_module(mod)
                return getattr(mod, "Extractor", None)
    except Exception as exc:
        logger.warning("Could not dynamically load Extractor class: %s", exc)
    return None


def _get_neo4j_client_class() -> Optional[type]:
    """Dynamically loads the Neo4jClient class safely without IDE import resolution errors."""
    try:
        import importlib
        if _GRAPH_GEN_ROOT.exists() and str(_GRAPH_GEN_ROOT) not in sys.path:
            sys.path.insert(0, str(_GRAPH_GEN_ROOT))

        try:
            mod = importlib.import_module("database.neo4j_client")
            return getattr(mod, "Neo4jClient")
        except (ImportError, ModuleNotFoundError):
            pass

        # Direct file-based spec loader (guaranteed fallback regardless of sys.path)
        client_path = _GRAPH_GEN_ROOT / "database" / "neo4j_client.py"
        if client_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("database.neo4j_client", str(client_path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["database.neo4j_client"] = mod
                spec.loader.exec_module(mod)
                return getattr(mod, "Neo4jClient", None)
    except Exception as exc:
        logger.warning("Could not dynamically load Neo4jClient class: %s", exc)
    return None


def get_demo_order_service_path() -> Optional[Path]:
    """
    Dynamically discover the demo-order-service repository location without hardcoded paths.
    Checks:
    1. DEMO_ORDER_SERVICE_PATH environment variable (if set and exists)
    2. Sibling directory: _PROJECT_ROOT.parent / "demo-order-service"
    3. Workspace subfolder: _PROJECT_ROOT / "demo-order-service"
    """
    env_path = os.getenv("DEMO_ORDER_SERVICE_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    sibling = _PROJECT_ROOT.parent / "demo-order-service"
    if sibling.exists():
        return sibling
    subfolder = _PROJECT_ROOT / "demo-order-service"
    if subfolder.exists():
        return subfolder
    return None


class GraphInspector:
    """Coordinates blast radius analysis between Neo4j and Tree-Sitter AST parser."""

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Check live Neo4j database health and graph stats."""
        service = MetadataService.get_instance()
        return service.get_graph_status()

    @classmethod
    def get_repositories(cls) -> List[Dict[str, Any]]:
        """List ingested repositories in Neo4j with provenance metadata."""
        service = MetadataService.get_instance()
        return service.get_available_repositories()

    @classmethod
    def _try_auto_ingest_to_neo4j(cls, repo_id: str, local_repo_dir: Optional[Path] = None) -> bool:
        """Attempt to ingest local code into active Neo4j database so queries succeed."""
        try:
            ExtractorClass = _get_extractor_class()
            if not ExtractorClass:
                return False

            target_dir = local_repo_dir
            if not target_dir or not target_dir.exists():
                audit_repo_a = _PROJECT_ROOT / "metadata_model" / "extracted" / "orc" / "audit_test" / "repo_a_location1"
                demo_repo = get_demo_order_service_path()
                if (repo_id == "audit_test/repo_a" or "repo_a" in repo_id) and audit_repo_a.exists():
                    target_dir = audit_repo_a
                elif (repo_id in ("demo-order-service", "demo-org/demo-order-service") or "order-service" in repo_id or "demo-order-service" in repo_id) and demo_repo and demo_repo.exists():
                    target_dir = demo_repo
                elif repo_id == "CI-CD-Failure-Predictor":
                    target_dir = _PROJECT_ROOT / "src"

            if target_dir and target_dir.exists():
                Neo4jClientClass = _get_neo4j_client_class()
                if not Neo4jClientClass:
                    return False
                extractor = ExtractorClass(repo_id=repo_id)
                extractor.parse_directory(str(target_dir))
                client = Neo4jClientClass()
                client.upload_graph(extractor.nodes, extractor.edges, repo_id=repo_id)
                client.close()
                logger.info("Auto-ingested repo '%s' (%d nodes) into Neo4j.", repo_id, len(extractor.nodes))
                return True
        except Exception as exc:
            logger.warning("Could not auto-ingest '%s' to Neo4j: %s", repo_id, exc)
        return False

    @classmethod
    def analyze_blast_radius(
        cls,
        repo_id: str = "audit_test/repo_a",
        changed_files: Optional[List[str]] = None,
        investigation_threshold: float = 0.50,
        local_repo_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Analyze code blast radius.
        1. Attempts live Neo4j Cypher query via MetadataService.
        2. If Neo4j is unreachable/offline, falls back to genuine Tree-Sitter
           AST static traversal without inventing any nodes or relationships.
        """
        if not changed_files:
            changed_files = ["src/file_b.py"]

        service = MetadataService.get_instance()
        neo4j_status = service.get_graph_status()
        ingested_repos = neo4j_status.get("repositories", [])

        if neo4j_status.get("status") == "ONLINE" and repo_id in ingested_repos:
            ingested_repos = neo4j_status.get("repositories", [])
            if repo_id in ingested_repos:
                logger.info("Executing blast radius query against active Neo4j database.")
                res = service.analyze_blast_radius(
                    repo_id=repo_id,
                    changed_files=changed_files,
                    investigation_threshold=investigation_threshold,
                )
                res["execution_engine"] = "Neo4j Knowledge Graph (Active Bolt Connection)"
                res["database_status"] = "ONLINE"

                if res.get("blast_radius_scope") != "FILE NOT FOUND IN GRAPH" and (
                    res.get("blast_radius_count", 0) > 0 or len(res.get("graph_elements", [])) > 0
                ):
                    return res

            # If repo not in Neo4j or file not found in Neo4j, use fast genuine Tree-Sitter AST
            logger.info("Repo or file not mapped in Neo4j. Using Tree-Sitter AST static traversal.")
            ast_res = cls._ast_fallback_analysis(
                repo_id=repo_id,
                changed_files=changed_files,
                investigation_threshold=investigation_threshold,
                local_repo_dir=local_repo_dir,
                offline_reason=f"Repository or files '{', '.join(changed_files)}' not present in Neo4j.",
            )
            ast_res["execution_engine"] = "Tree-Sitter AST Static Traversal (Neo4j Target File Mismatch)"
            ast_res["database_status"] = "ONLINE (Repo Not Ingested in Neo4j)"
            return ast_res

        # Neo4j is OFFLINE: Use genuine Tree-Sitter AST in-memory extraction
        logger.info("Neo4j offline. Falling back to genuine Tree-Sitter AST parser.")
        return cls._ast_fallback_analysis(
            repo_id=repo_id,
            changed_files=changed_files,
            investigation_threshold=investigation_threshold,
            local_repo_dir=local_repo_dir,
            offline_reason=neo4j_status.get("message", "Neo4j unreachable at bolt://localhost:7687"),
        )

    @classmethod
    def _ast_fallback_analysis(
        cls,
        repo_id: str,
        changed_files: List[str],
        investigation_threshold: float,
        local_repo_dir: Optional[Path],
        offline_reason: str,
    ) -> Dict[str, Any]:
        """
        Run real Tree-Sitter AST parser on local code to extract genuine caller-callee blast radius.
        """
        # Determine directory to parse
        candidate_dirs = []
        if local_repo_dir and local_repo_dir.exists():
            candidate_dirs.append(local_repo_dir)

        if repo_id in ("demo-order-service", "demo-org/demo-order-service") or "order-service" in repo_id or "demo-order-service" in repo_id:
            demo_repo = get_demo_order_service_path()
            if demo_repo and demo_repo.exists():
                candidate_dirs.append(demo_repo)

        # Check audit_test repos
        audit_repo_a = _PROJECT_ROOT / "metadata_model" / "extracted" / "orc" / "audit_test" / "repo_a_location1"
        if audit_repo_a.exists():
            candidate_dirs.append(audit_repo_a)

        # Current workspace src
        workspace_src = _PROJECT_ROOT / "src"
        if workspace_src.exists():
            candidate_dirs.append(workspace_src)

        target_dir = candidate_dirs[0] if candidate_dirs else _PROJECT_ROOT

        try:
            ExtractorClass = _get_extractor_class()
            if ExtractorClass is None:
                raise ImportError(
                    f"Tree-Sitter Extractor is unavailable (could not find extractor.py in {_GRAPH_GEN_ROOT})"
                )

            extractor = ExtractorClass(repo_id=repo_id)
            extractor.parse_directory(str(target_dir))

            nodes = extractor.nodes
            edges = extractor.edges

            # Build lookup maps
            nodes_by_id = {n["properties"]["id"]: n for n in nodes}
            funcs_by_name: Dict[str, List[Dict[str, Any]]] = {}
            funcs_by_file: Dict[str, List[Dict[str, Any]]] = {}

            for n in nodes:
                if n["type"] == "Function":
                    fpath = n["properties"].get("rel_path") or n["properties"].get("file_path") or ""
                    fname = n["properties"].get("name")
                    funcs_by_name.setdefault(fname, []).append(n)
                    funcs_by_file.setdefault(fpath, []).append(n)

            # Trace blast radius for changed files
            norm_changed = [cf.replace("\\", "/").lstrip("/") for cf in changed_files]
            changed_base_names = [os.path.basename(cf) for cf in changed_files]

            target_func_ids = set()
            for cf in norm_changed:
                cf_base = os.path.basename(cf)
                for fpath, flist in funcs_by_file.items():
                    if cf in fpath or cf_base == os.path.basename(fpath):
                        for func in flist:
                            target_func_ids.add(func["properties"]["id"])

            affected_callers = []
            ast_relationships = []
            cy_nodes: Dict[str, Dict[str, Any]] = {}
            cy_edges: Dict[str, Dict[str, Any]] = {}

            # Add changed files to graph
            for cf in changed_files:
                cf_id = f"file:{cf}"
                cy_nodes[cf_id] = {
                    "id": cf_id,
                    "label": os.path.basename(cf),
                    "name": os.path.basename(cf),
                    "type": "File",
                    "status": "changed",
                    "file_path": cf,
                    "repo_id": repo_id,
                }

            for e in edges:
                if e["type"] == "CALLS":
                    caller_id = e["from"]
                    target_id = e["to"]
                    caller_node = nodes_by_id.get(caller_id)
                    target_node = nodes_by_id.get(target_id)

                    if target_id in target_func_ids or (
                        target_node and any(cb in (target_node["properties"].get("file_path", "")) for cb in changed_base_names)
                    ):
                        caller_name = caller_node["properties"].get("name", "func") if caller_node else "caller"
                        target_name = target_node["properties"].get("name", "func") if target_node else "callee"
                        caller_file = caller_node["properties"].get("rel_path", "unknown") if caller_node else "unknown"

                        affected_callers.append({
                            "file_path": caller_file,
                            "relationship_type": "CALLS",
                            "triggered_by": changed_files[0] if changed_files else "unknown",
                            "risk_level": "AFFECTED_DEPENDENCY",
                            "reason": f"Function {caller_name}() directly calls {target_name}() in changed file.",
                        })

                        ast_relationships.append({
                            "caller": f"{caller_name}()",
                            "relationship": "CALLS",
                            "target": f"{target_name}()",
                            "caller_file": caller_file,
                            "target_file": os.path.basename(changed_files[0]) if changed_files else "callee",
                        })

                        # Add Cytoscape elements
                        cid = f"func:{caller_name}"
                        tid = f"func:{target_name}"
                        cy_nodes[cid] = {
                            "id": cid,
                            "label": f"{caller_name}()",
                            "name": caller_name,
                            "type": "Function",
                            "status": "affected",
                            "file_path": caller_file,
                            "repo_id": repo_id,
                        }
                        cy_nodes[tid] = {
                            "id": tid,
                            "label": f"{target_name}()",
                            "name": target_name,
                            "type": "Function",
                            "status": "changed",
                            "file_path": changed_files[0] if changed_files else "",
                            "repo_id": repo_id,
                        }
                        eid = f"calls:{cid}->{tid}"
                        cy_edges[eid] = {
                            "id": eid,
                            "source": cid,
                            "target": tid,
                            "type": "CALLS",
                            "label": "calls",
                        }

            graph_elements = (
                [{"data": nd} for nd in cy_nodes.values()]
                + [{"data": ed} for ed in cy_edges.values()]
            )

            distinct_affected = sorted(list({ac["file_path"] for ac in affected_callers}))

            from src.prediction.graph_impact import calculate_graph_impact_score
            impact_res = calculate_graph_impact_score(
                changed_files=changed_files,
                nodes=list(cy_nodes.values()),
                edges=list(cy_edges.values()),
                total_repo_files=len(nodes_by_id) or len(cy_nodes),
                engine_mode="Tree-Sitter AST Static In-Memory Traversal",
            )

            return {
                "status": "COMPLETED",
                "graph_query_status": "COMPLETED_VIA_AST_FALLBACK",
                "database_status": "OFFLINE",
                "execution_engine": "Tree-Sitter AST Static In-Memory Traversal (Neo4j Offline Fallback)",
                "repo_id": repo_id,
                "parsed_directory": str(target_dir),
                "changed_files": changed_files,
                "blast_radius_count": len(distinct_affected),
                "blast_radius_file_count": len(distinct_affected),
                "blast_radius_scope": "AFFECTED DEPENDENCY" if distinct_affected else "LOCAL",
                "affected_files": affected_callers,
                "affected_caller_files": affected_callers,
                "ast_relationships": ast_relationships,
                "ast_call_relationships": ast_relationships,
                "graph_elements": graph_elements,
                "graph_impact_score": impact_res.to_dict(),
                "graph_stats": {
                    "total_nodes": len(cy_nodes),
                    "total_edges": len(cy_edges),
                    "file_nodes_count": sum(1 for n in cy_nodes.values() if n.get("type") == "File"),
                    "function_nodes_count": sum(1 for n in cy_nodes.values() if n.get("type") == "Function"),
                    "calls_edges_count": sum(1 for e in cy_edges.values() if e.get("type") == "CALLS"),
                },
                "investigation_threshold": investigation_threshold,
                "message": (
                    f"Neo4j offline. Genuinely parsed AST with Tree-Sitter from '{target_dir.name}': "
                    f"identified {len(distinct_affected)} affected file(s) and {len(ast_relationships)} call relationship(s)."
                ),
                "offline_notice": (
                    "Neo4j is currently OFFLINE at bolt://localhost:7687. "
                    "Displaying genuine Tree-Sitter AST static call hierarchy. "
                    "To start Neo4j: run 'docker run -d --name neo4j-graphdoc -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/Cicd_GraphDoc_2026_SecureKey neo4j:5.25.0-community'."
                ),
            }
        except Exception as exc:
            logger.warning("AST fallback parsing failed: %s", exc)
            from src.prediction.graph_impact import calculate_graph_impact_score
            fallback_impact = calculate_graph_impact_score(
                changed_files=changed_files,
                nodes=[],
                edges=[],
                engine_mode="Tree-Sitter Fallback Unavailable"
            )
            return {
                "status": "UNAVAILABLE",
                "graph_query_status": "UNAVAILABLE",
                "database_status": "OFFLINE",
                "execution_engine": "None",
                "repo_id": repo_id,
                "changed_files": changed_files,
                "blast_radius_count": 0,
                "affected_files": [],
                "ast_relationships": [],
                "graph_elements": [],
                "graph_impact_score": fallback_impact.to_dict(),
                "graph_stats": {"total_nodes": 0, "total_edges": 0},
                "investigation_threshold": investigation_threshold,
                "message": f"Graph analysis unavailable: {offline_reason}. AST fallback error: {exc}",
            }

    @classmethod
    def get_explorer_graph(
        cls,
        repo_id: str = "msiemens/tinydb",
        mode: str = "blast_radius",
        changed_files: Optional[List[str]] = None,
        investigation_threshold: float = 0.50,
        local_repo_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Produce dedicated interactive graph explorer elements and metadata for a repository.
        Supports two views:
        1. 'blast_radius': only the changed file, its functions, caller functions, and affected files.
        2. 'full': complete repository graph (File, Class, Function, Module) with CONTAINS, CALLS, IMPORTS,
           with changed nodes and blast radius affected nodes highlighted.
        """
        if not repo_id or not repo_id.strip():
            repo_id = "msiemens/tinydb"
        repo_id = repo_id.strip()

        if not changed_files:
            if "tinydb" in repo_id:
                changed_files = ["tinydb/storages.py"]
            elif "repo_a" in repo_id:
                changed_files = ["src/file_b.py"]
            else:
                changed_files = ["tinydb/storages.py"]

        # Run blast radius analysis first to establish ground truth
        blast_res = cls.analyze_blast_radius(
            repo_id=repo_id,
            changed_files=changed_files,
            investigation_threshold=investigation_threshold,
            local_repo_dir=local_repo_dir,
        )

        blast_elements = blast_res.get("graph_elements", [])
        blast_nodes_map: Dict[str, Dict[str, Any]] = {}
        affected_files_set = set()
        for af in blast_res.get("affected_files", []):
            if isinstance(af, dict) and af.get("file_path"):
                affected_files_set.add(af["file_path"].replace("\\", "/"))
                affected_files_set.add(os.path.basename(af["file_path"]))

        for elem in blast_elements:
            data = elem.get("data", {})
            if "source" not in data and "target" not in data:
                blast_nodes_map[data.get("id")] = data

        if mode == "blast_radius":
            nodes_count = sum(1 for e in blast_elements if "source" not in e["data"])
            edges_count = sum(1 for e in blast_elements if "source" in e["data"])
            return {
                "status": "SUCCESS",
                "repo_id": repo_id,
                "mode": "blast_radius",
                "changed_files": changed_files,
                "nodes_count": nodes_count,
                "edges_count": edges_count,
                "elements": blast_elements,
                "blast_radius_summary": {
                    "affected_files_count": blast_res.get("blast_radius_count", 0),
                    "ast_calls_count": len(blast_res.get("ast_relationships", [])),
                    "affected_files": blast_res.get("affected_files", []),
                    "scope": blast_res.get("blast_radius_scope", "LOCAL"),
                    "execution_engine": blast_res.get("execution_engine", "Neo4j Knowledge Graph"),
                    "database_status": blast_res.get("database_status", "ONLINE"),
                    "graph_impact_score": blast_res.get("graph_impact_score"),
                    "message": blast_res.get("message", ""),
                },
                "graph_impact_score": blast_res.get("graph_impact_score"),
                "stats": {
                    "total_nodes": nodes_count,
                    "total_edges": edges_count,
                    "files": sum(1 for e in blast_elements if e["data"].get("type") == "File"),
                    "functions": sum(1 for e in blast_elements if e["data"].get("type") == "Function"),
                    "classes": sum(1 for e in blast_elements if e["data"].get("type") == "Class"),
                    "calls": sum(1 for e in blast_elements if e["data"].get("type") == "CALLS"),
                    "contains": sum(1 for e in blast_elements if e["data"].get("type") == "CONTAINS"),
                },
                "available_repositories": cls.get_repositories(),
                "message": f"Rendered blast-radius subgraph for '{repo_id}' ({nodes_count} nodes, {edges_count} edges).",
            }

        # mode == 'full': fetch entire repository graph from Neo4j (or AST fallback)
        nodes_dict: Dict[str, Dict[str, Any]] = {}
        edges_dict: Dict[str, Dict[str, Any]] = {}
        execution_engine = "Neo4j Knowledge Graph"
        db_status = "ONLINE"

        service = MetadataService.get_instance()
        neo4j_status = service.get_graph_status()
        ingested_repos = neo4j_status.get("repositories", [])

        if neo4j_status.get("status") == "ONLINE" and repo_id in ingested_repos:
            try:
                Neo4jClientClass = _get_neo4j_client_class()
                if Neo4jClientClass:
                    client = Neo4jClientClass()
                    with client.session() as session:
                        # Query all nodes for this repo
                        n_query = """
                        MATCH (n {repo_id: $repo_id})
                        WHERE NOT n:SyncState
                        RETURN labels(n)[0] as type, n.id as id, n.name as name,
                               coalesce(n.rel_path, n.file_path, n.path, n.name) as rel_path,
                               n.path as path, n.file_path as file_path
                        """
                        for r in session.run(n_query, repo_id=repo_id):
                            nid = r["id"] or f"{r['type'].lower()}:{r['name']}"
                            lbl = r["name"] or r["rel_path"] or nid
                            if r["type"] == "Function" and not lbl.endswith("()"):
                                lbl = f"{lbl}()"
                            nodes_dict[nid] = {
                                "id": nid,
                                "label": lbl,
                                "name": r["name"] or lbl,
                                "type": r["type"],
                                "rel_path": r["rel_path"] or "",
                                "file_path": r["file_path"] or r["path"] or r["rel_path"] or "",
                                "repo_id": repo_id,
                                "status": "normal",
                            }

                        # Query all edges for this repo
                        e_query = """
                        MATCH (a {repo_id: $repo_id})-[r]->(b {repo_id: $repo_id})
                        WHERE NOT a:SyncState AND NOT b:SyncState
                        RETURN type(r) as type, a.id as source, b.id as target
                        """
                        for r in session.run(e_query, repo_id=repo_id):
                            if r["source"] in nodes_dict and r["target"] in nodes_dict:
                                eid = f"{r['type']}:{r['source']}->{r['target']}"
                                edges_dict[eid] = {
                                    "id": eid,
                                    "source": r["source"],
                                    "target": r["target"],
                                    "type": r["type"],
                                    "label": r["type"].lower(),
                                }
                    client.close()
            except Exception as exc:
                logger.warning("Failed to query full Neo4j graph for '%s': %s", repo_id, exc)

        # If Neo4j was offline or empty for this repo, use Tree-Sitter AST extractor
        if len(nodes_dict) == 0:
            execution_engine = "Tree-Sitter AST Static In-Memory Parser"
            db_status = "OFFLINE"
            try:
                candidate_dirs = []
                if local_repo_dir and local_repo_dir.exists():
                    candidate_dirs.append(local_repo_dir)
                demo_repo = get_demo_order_service_path()
                if ("order-service" in repo_id or "demo-order-service" in repo_id) and demo_repo and demo_repo.exists():
                    candidate_dirs.append(demo_repo)
                audit_repo_a = _PROJECT_ROOT / "metadata_model" / "extracted" / "orc" / "audit_test" / "repo_a_location1"
                if ("repo_a" in repo_id or repo_id == "audit_test/repo_a") and audit_repo_a.exists():
                    candidate_dirs.append(audit_repo_a)
                elif (_PROJECT_ROOT / "scratch" / "real_repos" / "tinydb").exists() and "tinydb" in repo_id:
                    candidate_dirs.append(_PROJECT_ROOT / "scratch" / "real_repos" / "tinydb")
                else:
                    candidate_dirs.append(_PROJECT_ROOT / "src")

                target_dir = candidate_dirs[0] if candidate_dirs else _PROJECT_ROOT
                ExtractorClass = _get_extractor_class()
                if ExtractorClass:
                    extractor = ExtractorClass(repo_id=repo_id)
                    extractor.parse_directory(str(target_dir))
                    for n in extractor.nodes:
                        nid = n["properties"].get("id") or f"{n['type'].lower()}:{n['properties'].get('name')}"
                        lbl = n["properties"].get("name") or nid
                        if n["type"] == "Function" and not lbl.endswith("()"):
                            lbl = f"{lbl}()"
                        nodes_dict[nid] = {
                            "id": nid,
                            "label": lbl,
                            "name": n["properties"].get("name") or lbl,
                            "type": n["type"],
                            "rel_path": n["properties"].get("rel_path") or "",
                            "file_path": n["properties"].get("file_path") or "",
                            "repo_id": repo_id,
                            "status": "normal",
                        }
                    for e in extractor.edges:
                        eid = f"{e['type']}:{e['from']}->{e['to']}"
                        edges_dict[eid] = {
                            "id": eid,
                            "source": e["from"],
                            "target": e["to"],
                            "type": e["type"],
                            "label": e["type"].lower(),
                        }
            except Exception as exc:
                logger.warning("Fallback full AST parsing failed: %s", exc)

        # Highlight blast radius nodes inside full graph
        norm_changed = [cf.replace("\\", "/").lstrip("/") for cf in changed_files]
        changed_bases = [os.path.basename(cf) for cf in changed_files]

        for nid, ndata in nodes_dict.items():
            # Check if this node was marked changed or affected in blast analysis
            if nid in blast_nodes_map:
                ndata["status"] = blast_nodes_map[nid].get("status", "normal")
                continue

            rp = (ndata.get("rel_path") or "").replace("\\", "/").lstrip("/")
            fp = (ndata.get("file_path") or "").replace("\\", "/").lstrip("/")
            name = ndata.get("name") or ""
            base = os.path.basename(rp or fp)

            is_changed = any(cf in rp or cf in fp or b == base or b == name for cf, b in zip(norm_changed, changed_bases))
            if is_changed:
                ndata["status"] = "changed"
            elif any(af in rp or af in fp or af == base for af in affected_files_set):
                ndata["status"] = "affected"

        full_elements = (
            [{"data": nd} for nd in nodes_dict.values()]
            + [{"data": ed} for ed in edges_dict.values()]
        )

        return {
            "status": "SUCCESS",
            "repo_id": repo_id,
            "mode": "full",
            "changed_files": changed_files,
            "nodes_count": len(nodes_dict),
            "edges_count": len(edges_dict),
            "elements": full_elements,
            "blast_radius_summary": {
                "affected_files_count": blast_res.get("blast_radius_count", 0),
                "ast_calls_count": len(blast_res.get("ast_relationships", [])),
                "affected_files": blast_res.get("affected_files", []),
                "scope": blast_res.get("blast_radius_scope", "LOCAL"),
                "execution_engine": execution_engine,
                "database_status": db_status,
                "graph_impact_score": blast_res.get("graph_impact_score"),
                "message": blast_res.get("message", ""),
            },
            "graph_impact_score": blast_res.get("graph_impact_score"),
            "stats": {
                "total_nodes": len(nodes_dict),
                "total_edges": len(edges_dict),
                "files": sum(1 for n in nodes_dict.values() if n.get("type") == "File"),
                "functions": sum(1 for n in nodes_dict.values() if n.get("type") == "Function"),
                "classes": sum(1 for n in nodes_dict.values() if n.get("type") == "Class"),
                "calls": sum(1 for e in edges_dict.values() if e.get("type") == "CALLS"),
                "contains": sum(1 for e in edges_dict.values() if e.get("type") == "CONTAINS"),
            },
            "available_repositories": cls.get_repositories(),
            "message": f"Rendered complete repository architecture for '{repo_id}' ({len(nodes_dict)} nodes, {len(edges_dict)} edges).",
        }
