import subprocess
import os
from typing import Dict, Any, Optional

from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient
from enrichment.cgl import ContinualGraphLearner
from maintenance.git_utils import (
    get_commit_diff,
    resolve_commit_sha,
    get_head_commit_sha,
    check_working_tree_clean,
    is_git_repository,
    CommitProvenanceError,
    CommitMismatchError,
    BaseCommitMismatchError,
    WorkingTreeDirtyError,
)
from maintenance.repo_utils import resolve_repo_id


def update_graph_from_diff(
    dir_path: str,
    base_sha: Optional[str] = None,
    target_sha: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Incrementally synchronizes a Neo4j repository graph based on Git changes.
    
    Implements Option 1: Strict Working-Tree Verification.
    
    Contract:
    - Returns a structured dictionary containing:
        - status: "SUCCESS" | "NO_CHANGES" | "FAILED"
        - repo_id: str
        - target_sha: canonical 40-character target commit SHA (or None for working-tree diff)
        - base_sha: canonical 40-character base commit SHA (or None)
        - commit_verified: bool (True only when strict commit verification & sync succeed)
        - files_parsed: int
        - files_pruned: int
        - nodes_count: int
        - edges_count: int
        - synced_at: str | None
        - error: str | None
    
    Safety Guarantees:
    - Base-SHA Consistency: Retrieves the repository's existing SyncState from Neo4j.
      Fails closed with BaseCommitMismatchError if no prior verified state exists or if the
      graph's current target_sha does not equal requested base_sha.
    - Working-Tree Cleanliness: Fails closed with WorkingTreeDirtyError if uncommitted or untracked
      changes exist in any parsed source file (changed files or affected callers).
    - Commit Alignment: Fails closed with CommitMismatchError if HEAD != target_sha.
    - Transaction Atomicity: Repository concurrency lock, file pruning, node ingestion,
      relationship ingestion, and SyncState update execute in a single Neo4j transaction.
    """
    resolved_repo_id = resolve_repo_id(dir_path, repo_id)
    canonical_target_sha: Optional[str] = None
    canonical_base_sha: Optional[str] = None
    commit_verified = False

    # 1. Validate SHA arguments
    if (base_sha is not None and target_sha is None) or (base_sha is None and target_sha is not None):
        raise ValueError("Both base_sha and target_sha must be provided for commit-aware diffing, or neither for working-tree diffing.")

    client = Neo4jClient()
    try:
        # Guarantee schema uniqueness constraint for concurrency serialization
        client.ensure_constraints()

        # 2. Commit provenance verification & diff collection
        if base_sha is not None and target_sha is not None:
            if not is_git_repository(dir_path):
                raise CommitProvenanceError(f"Directory '{dir_path}' is not a valid git repository work tree.")

            # Resolve to canonical 40-char SHA hashes
            canonical_target_sha = resolve_commit_sha(target_sha, cwd=dir_path)
            canonical_base_sha = resolve_commit_sha(base_sha, cwd=dir_path)

            # Retrieve existing SyncState to verify base-SHA consistency
            existing_sync = client.get_sync_state(resolved_repo_id)

            # Check repeated sync of already synchronized target commit (idempotent no-op)
            if (
                existing_sync
                and existing_sync.get("commit_verified")
                and existing_sync.get("target_sha") == canonical_target_sha
                and (canonical_base_sha == canonical_target_sha or existing_sync.get("base_sha") == canonical_base_sha)
            ):
                return {
                    "status": "NO_CHANGES",
                    "repo_id": resolved_repo_id,
                    "target_sha": canonical_target_sha,
                    "base_sha": canonical_base_sha,
                    "commit_verified": True,
                    "files_parsed": 0,
                    "files_pruned": 0,
                    "nodes_count": 0,
                    "edges_count": 0,
                    "synced_at": existing_sync.get("synced_at_iso") or str(existing_sync.get("synced_at")),
                    "error": None,
                }

            # If identical SHAs requested but graph is not at target_sha, fail closed
            if canonical_base_sha == canonical_target_sha:
                raise BaseCommitMismatchError(
                    current_graph_sha=existing_sync.get("target_sha") if existing_sync else None,
                    requested_base_sha=canonical_base_sha,
                    repo_id=resolved_repo_id
                )

            # Enforce base-SHA consistency against existing graph state
            if existing_sync is None or not existing_sync.get("commit_verified"):
                raise BaseCommitMismatchError(
                    current_graph_sha=None,
                    requested_base_sha=canonical_base_sha,
                    repo_id=resolved_repo_id
                )
            if existing_sync.get("target_sha") != canonical_base_sha:
                raise BaseCommitMismatchError(
                    current_graph_sha=existing_sync.get("target_sha"),
                    requested_base_sha=canonical_base_sha,
                    repo_id=resolved_repo_id
                )

            # Verify HEAD matches target_sha
            head_sha = get_head_commit_sha(dir_path)
            if head_sha != canonical_target_sha:
                raise CommitMismatchError(head_sha=head_sha, target_sha=canonical_target_sha)

            try:
                diff = get_commit_diff(canonical_base_sha, canonical_target_sha, cwd=dir_path)
            except subprocess.CalledProcessError as e:
                raise CommitProvenanceError(
                    f"Invalid commit reference or git diff failed between '{canonical_base_sha}' and '{canonical_target_sha}'."
                ) from e

            added = diff.get("added", [])
            modified = diff.get("modified", [])
            deleted = diff.get("deleted", [])
            renamed = diff.get("renamed", [])

            # Files to re-parse (must exist in target tree)
            files_to_parse = [
                f for f in (added + modified + [new for _, new in renamed])
                if os.path.exists(os.path.join(dir_path, f))
            ]
            # Files whose old nodes/edges must be pruned
            files_to_prune = list(dict.fromkeys(modified + deleted + [old for old, _ in renamed]))
            
            # All paths considered changed for cross-file dependency tracking
            all_changed_files = list(dict.fromkeys(added + modified + deleted + [old for old, _ in renamed] + [new for _, new in renamed]))

            # Verify working-tree cleanliness for all changed files before proceeding
            check_working_tree_clean(dir_path, file_paths=all_changed_files)
        else:
            # Working-tree mode
            try:
                result = subprocess.run(
                    ["git", "ls-files", "-mo", "--exclude-standard"],
                    cwd=dir_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                all_changed_files = [f for f in result.stdout.strip().split('\n') if f]
            except subprocess.CalledProcessError:
                print("Error: Directory is not a valid git repository or git command failed.")
                return {
                    "status": "FAILED",
                    "repo_id": resolved_repo_id,
                    "target_sha": None,
                    "base_sha": None,
                    "commit_verified": False,
                    "files_parsed": 0,
                    "files_pruned": 0,
                    "nodes_count": 0,
                    "edges_count": 0,
                    "synced_at": None,
                    "error": "Directory is not a valid git repository or git command failed."
                }

            files_to_parse = [f for f in all_changed_files if os.path.exists(os.path.join(dir_path, f))]
            files_to_prune = all_changed_files
            if is_git_repository(dir_path):
                canonical_target_sha = get_head_commit_sha(dir_path)

        if not all_changed_files:
            print("No changed files detected by Git.")
            return {
                "status": "NO_CHANGES",
                "repo_id": resolved_repo_id,
                "target_sha": canonical_target_sha,
                "base_sha": canonical_base_sha,
                "commit_verified": bool(canonical_target_sha and (base_sha is not None)),
                "files_parsed": 0,
                "files_pruned": 0,
                "nodes_count": 0,
                "edges_count": 0,
                "synced_at": None,
                "error": None,
            }

        print(f"Detected {len(all_changed_files)} changed files in repo '{resolved_repo_id}'. Initializing Continual Graph Learning (CGL)...")

        extractor = Extractor(repo_id=resolved_repo_id)
        extractor.root_dir = os.path.abspath(dir_path)

        changed_file_paths = []
        changed_file_ids = []
        changed_rel_paths = []
        for file_name in all_changed_files:
            norm_rel = file_name.replace("\\", "/")
            changed_rel_paths.append(norm_rel)
            fp = os.path.normpath(os.path.join(dir_path, file_name))
            changed_file_paths.append(fp)
            changed_file_ids.append(f"file:{fp}")
            if resolved_repo_id:
                changed_file_ids.append(f"repo:{resolved_repo_id}:file:{norm_rel}")
            raw_fp = os.path.join(dir_path, file_name)
            if raw_fp != fp:
                changed_file_paths.append(raw_fp)
                changed_file_ids.append(f"file:{raw_fp}")

        affected_caller_files = set()

        # Pre-seed symbol table and callers using read-only queries
        with client.session() as session:
            res_nodes = session.run(
                "MATCH (n) WHERE (n.repo_id = $repo_id OR ($repo_id IS NULL AND n.repo_id IS NULL)) RETURN n.id AS id",
                repo_id=resolved_repo_id
            )
            old_nodes = [r["id"] for r in res_nodes]
            
            res_edges = session.run(
                """
                MATCH (a)-[r]->(b) 
                WHERE (a.repo_id = $repo_id OR ($repo_id IS NULL AND a.repo_id IS NULL))
                  AND (b.repo_id = $repo_id OR ($repo_id IS NULL AND b.repo_id IS NULL))
                RETURN a.id AS from, b.id AS to, type(r) AS type
                """,
                repo_id=resolved_repo_id
            )
            old_edges = [r.data() for r in res_edges]

            # 1. Pre-seed symbol table with known functions and classes from unchanged files in this repo
            res_symbols = session.run(
                """
                MATCH (n) 
                WHERE (n.repo_id = $repo_id OR ($repo_id IS NULL AND n.repo_id IS NULL))
                  AND (n:Function OR n:Class) 
                  AND NOT (n.file_path IN $changed_file_paths OR n.rel_path IN $changed_rel_paths OR n.id IN $changed_file_ids)
                  AND n.name IS NOT NULL
                RETURN n.name AS name, n.id AS id
                """,
                repo_id=resolved_repo_id,
                changed_file_paths=changed_file_paths,
                changed_file_ids=changed_file_ids,
                changed_rel_paths=changed_rel_paths
            )
            for r in res_symbols:
                if r.get("name") and r.get("id"):
                    extractor.symbol_table[r["name"]] = r["id"]

            # 2. Identify unchanged files in this repo that call functions/classes in changed files
            res_callers = session.run(
                """
                MATCH (caller)-[r:CALLS]->(callee)
                WHERE (caller.repo_id = $repo_id OR ($repo_id IS NULL AND caller.repo_id IS NULL))
                  AND (callee.repo_id = $repo_id OR ($repo_id IS NULL AND callee.repo_id IS NULL))
                  AND (callee.file_path IN $changed_file_paths OR callee.rel_path IN $changed_rel_paths OR callee.id IN $changed_file_ids)
                RETURN DISTINCT coalesce(caller.file_path, caller.path) AS file_path
                """,
                repo_id=resolved_repo_id,
                changed_file_paths=changed_file_paths,
                changed_file_ids=changed_file_ids,
                changed_rel_paths=changed_rel_paths
            )
            for r in res_callers:
                cfp = r.get("file_path")
                if cfp and cfp not in changed_file_paths and os.path.exists(cfp):
                    affected_caller_files.add(cfp)

        cgl = ContinualGraphLearner(old_nodes, old_edges)

        # Ensure working-tree cleanliness for all parsed source files (changed files + affected callers)
        all_parsed_paths = list(dict.fromkeys(
            files_to_parse + [os.path.relpath(p, dir_path).replace("\\", "/") for p in affected_caller_files]
        ))
        if base_sha is not None and all_parsed_paths:
            check_working_tree_clean(dir_path, file_paths=all_parsed_paths)

        # Parse files BEFORE destructive database writes
        # Pass 1a: Parse changed files and add their nodes
        for file_name in files_to_parse:
            file_path = os.path.join(dir_path, file_name)
            if os.path.exists(file_path):
                ext = os.path.splitext(file_path)[1]
                extractor._parse_file_pass1(file_path, ext, add_nodes=True)

        # Pass 1b: Parse affected callers for AST caching and Pass 2 re-evaluation (do not duplicate nodes)
        for caller_path in affected_caller_files:
            if os.path.exists(caller_path):
                ext = os.path.splitext(caller_path)[1]
                extractor._parse_file_pass1(caller_path, ext, add_nodes=False)

        # Executes second pass to map CALLS and IMPORTS across all cached ASTs
        extractor._execute_pass2()
        new_graph = extractor.get_graph()

        # Applying Continual Learning Order & Identify Hubs
        if new_graph["edges"]:
            layers = cgl.partition_into_layers(new_graph["edges"])
            hub_weights = cgl.calculate_structural_hubs(new_graph["edges"])
            print(f"CGL Layering: Partitioned update into {len(layers)} BFS propagation layers.")
            print(f"CGL Centrality: Identified {len([w for w in hub_weights.values() if w > 0.5])} major structural hubs.")

        # Atomic Graph Mutation: Single Neo4j Transaction
        # Concurrency Lock -> Prune -> Ingest Nodes -> Ingest Edges -> Record SyncState -> Commit
        commit_verified_flag = bool(canonical_target_sha and (base_sha is not None))
        sync_state_record = None

        with client.session() as session:
            with session.begin_transaction() as tx:
                # 1. Acquire per-repository write lock on SyncState node
                client.acquire_repo_lock(resolved_repo_id, tx)

                # 2. Localized Subgraph Pruning strictly scoped to repo_id
                prune_query = """
                MATCH (n) 
                WHERE (n.repo_id = $repo_id OR ($repo_id IS NULL AND n.repo_id IS NULL))
                  AND (n.file_path = $file_path OR n.id = $file_id OR n.file_path = $norm_fp OR n.id = $norm_fid OR n.rel_path = $rel_path OR n.id = $scoped_fid)
                DETACH DELETE n
                """
                for file_name in files_to_prune:
                    file_path = os.path.join(dir_path, file_name)
                    rel_path = file_name.replace("\\", "/")
                    file_id = f"file:{file_path}"
                    norm_fp = os.path.normpath(file_path)
                    norm_fid = f"file:{norm_fp}"
                    scoped_fid = f"repo:{resolved_repo_id}:file:{rel_path}" if resolved_repo_id else file_id

                    tx.run(
                        prune_query,
                        file_path=file_path,
                        file_id=file_id,
                        norm_fp=norm_fp,
                        norm_fid=norm_fid,
                        rel_path=rel_path,
                        scoped_fid=scoped_fid,
                        repo_id=resolved_repo_id
                    )

                # 3. Upload new nodes and edges within the same transaction
                print(f"Incremental update: Uploading {len(new_graph['nodes'])} nodes and {len(new_graph['edges'])} edges for repo '{resolved_repo_id}'.")
                client.upload_graph(new_graph["nodes"], new_graph["edges"], repo_id=resolved_repo_id, tx=tx)

                # 4. Record verified SyncState within the same transaction
                sync_state_record = client.record_sync_state(
                    repo_id=resolved_repo_id,
                    target_sha=canonical_target_sha or "working-tree",
                    base_sha=canonical_base_sha,
                    status="SYNCED",
                    commit_verified=commit_verified_flag,
                    files_parsed=len(files_to_parse),
                    files_pruned=len(files_to_prune),
                    nodes_count=len(new_graph["nodes"]),
                    edges_count=len(new_graph["edges"]),
                    tx=tx
                )

                # 5. Commit transaction atomically
                tx.commit()
    finally:
        client.close()

    print("Incremental maintenance complete.")
    synced_at = sync_state_record.get("synced_at_iso") if sync_state_record else None

    return {
        "status": "SUCCESS",
        "repo_id": resolved_repo_id,
        "target_sha": canonical_target_sha,
        "base_sha": canonical_base_sha,
        "commit_verified": commit_verified_flag,
        "files_parsed": len(files_to_parse),
        "files_pruned": len(files_to_prune),
        "nodes_count": len(new_graph["nodes"]),
        "edges_count": len(new_graph["edges"]),
        "synced_at": synced_at,
        "error": None,
    }