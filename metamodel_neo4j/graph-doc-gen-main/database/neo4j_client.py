import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

PROTECTED_DATABASES = {"neo4j", "system"}

class Neo4jClient:
    def __init__(self, database=None):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        env_db = os.getenv("NEO4J_DATABASE")
        selected_db = database if database is not None else env_db
        if selected_db is not None:
            selected_db = selected_db.strip()
            if not selected_db:
                selected_db = None
        self.database = selected_db
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def is_protected_database(self) -> bool:
        """
        Determines whether the client is targeting the default or protected database.
        When self.database is None or in PROTECTED_DATABASES, it targets the main/default graph.
        """
        if not self.database:
            return True
        return self.database.strip().lower() in PROTECTED_DATABASES

    def session(self):
        return self.driver.session(database=self.database) if self.database else self.driver.session()

    def close(self):
        self.driver.close()

    def clear_repository(self, repo_id: str):
        """
        Surgically deletes only the nodes and relationships belonging to a specific repository.
        Does not delete or affect any other repository data in the graph.
        """
        if not repo_id or not repo_id.strip():
            raise ValueError("repo_id must be provided to clear_repository().")
        clean_repo = repo_id.strip()
        with self.session() as session:
            session.run("MATCH (n {repo_id: $repo_id}) DETACH DELETE n", repo_id=clean_repo)

    def clear_database(self, force: bool = False, repo_id: str = None):
        """
        Clears all nodes and relationships in the configured database, or for a specific repo_id.
        
        Safety Guard:
        If repo_id is provided, delegates to clear_repository(repo_id).
        If repo_id is None, clearing protected/default databases requires explicit force=True.
        """
        if repo_id and repo_id.strip():
            return self.clear_repository(repo_id)

        if self.is_protected_database() and not force:
            target = self.database or "default"
            raise RuntimeError(
                f"Destructive operation blocked: clear_database() cannot be executed on protected "
                f"or default database '{target}' without explicit force=True."
            )
        with self.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def create_node(self, node_type, properties):
        with self.session() as session:
            query = f"MERGE (n:{node_type} {{id: $id}}) SET n += $props"
            session.run(query, id=properties.get("id"), props=properties)

    def create_relationship(self, from_id, to_id, rel_type):
        with self.session() as session:
            query = f"""
            MATCH (a {{id: $from_id}})
            MATCH (b {{id: $to_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            """
            session.run(query, from_id=from_id, to_id=to_id)

    def upload_graph(self, nodes, edges, repo_id: str = None, tx = None):
        print(f"Uploading {len(nodes)} nodes and {len(edges)} edges to Neo4j in batches...")
        
        # Batch Nodes by type
        nodes_by_type = {}
        for n in nodes:
            props = dict(n["properties"])
            if repo_id and "repo_id" not in props:
                props["repo_id"] = repo_id
            nodes_by_type.setdefault(n["type"], []).append(props)
            
        def _execute_nodes(runner):
            for n_type, props_list in nodes_by_type.items():
                query = f"""
                UNWIND $props_list AS props
                MERGE (n:{n_type} {{id: props.id}})
                SET n += props
                """
                runner.run(query, props_list=props_list)

        if tx is not None:
            _execute_nodes(tx)
        else:
            with self.session() as session:
                _execute_nodes(session)

        # Batch Edges by type
        edges_by_type = {}
        for e in edges:
            edge_data = {"from": e["from"], "to": e["to"]}
            edge_repo = e.get("repo_id") or repo_id
            if edge_repo:
                edge_data["repo_id"] = edge_repo
            edges_by_type.setdefault(e["type"], []).append(edge_data)

        def _execute_edges(runner):
            for e_type, e_list in edges_by_type.items():
                query = f"""
                UNWIND $e_list AS e
                MATCH (a {{id: e.from}})
                MATCH (b {{id: e.to}})
                WHERE (e.repo_id IS NULL OR (a.repo_id = e.repo_id AND b.repo_id = e.repo_id))
                MERGE (a)-[r:{e_type}]->(b)
                SET r.repo_id = coalesce(e.repo_id, r.repo_id)
                """
                runner.run(query, e_list=e_list)

        if tx is not None:
            _execute_edges(tx)
        else:
            with self.session() as session:
                _execute_edges(session)
                
        print("Upload complete.")

    def ensure_constraints(self):
        """
        Ensures necessary schema constraints exist in the target database.
        Creates a uniqueness constraint on :SyncState(id) to prevent duplicate
        SyncState nodes during concurrent initial synchronizations and enable
        Neo4j's schema-level lock serialization on MERGE.
        Safeguard: Never runs on protected or default databases.
        """
        if self.is_protected_database():
            return
        with self.session() as session:
            session.run(
                "CREATE CONSTRAINT unique_syncstate_id IF NOT EXISTS "
                "FOR (s:SyncState) REQUIRE s.id IS UNIQUE"
            )

    def acquire_repo_lock(self, repo_id: str, tx):
        """
        Acquires an exclusive write lock for this repository in Neo4j for the duration of the transaction.
        In Neo4j, updating a property on the repository-scoped SyncState node inside an open explicit
        transaction tx acquires and holds an exclusive write lock on that node until tx commits or rolls back.
        Any concurrent transaction attempting to acquire the lock for the same repo_id will wait.
        """
        if not repo_id or not repo_id.strip():
            raise ValueError("repo_id must be provided to acquire_repo_lock().")
        clean_repo = repo_id.strip()
        sync_id = f"repo:{clean_repo}:sync"
        query = """
        MERGE (s:SyncState {id: $sync_id})
        SET s.repo_id = $repo_id,
            s.lock_timestamp = datetime()
        RETURN s.id AS id
        """
        res = tx.run(query, sync_id=sync_id, repo_id=clean_repo)
        res.consume()

    def record_sync_state(
        self,
        repo_id: str,
        target_sha: str,
        base_sha: str = None,
        status: str = "SYNCED",
        commit_verified: bool = True,
        files_parsed: int = 0,
        files_pruned: int = 0,
        nodes_count: int = 0,
        edges_count: int = 0,
        tx = None
    ) -> dict:
        """
        Records or updates repository-scoped SyncState in Neo4j.
        Executes within the given transaction tx (if provided), or opens a new session.
        """
        if not repo_id or not repo_id.strip():
            raise ValueError("repo_id must be provided to record_sync_state().")
        clean_repo = repo_id.strip()
        sync_id = f"repo:{clean_repo}:sync"

        query = """
        MERGE (s:SyncState {id: $sync_id})
        SET s.repo_id = $repo_id,
            s.target_sha = $target_sha,
            s.base_sha = $base_sha,
            s.status = $status,
            s.commit_verified = $commit_verified,
            s.files_parsed = $files_parsed,
            s.files_pruned = $files_pruned,
            s.nodes_count = $nodes_count,
            s.edges_count = $edges_count,
            s.synced_at = datetime().epochMillis,
            s.synced_at_iso = toString(datetime())
        RETURN s
        """
        params = {
            "sync_id": sync_id,
            "repo_id": clean_repo,
            "target_sha": target_sha,
            "base_sha": base_sha,
            "status": status,
            "commit_verified": bool(commit_verified),
            "files_parsed": int(files_parsed),
            "files_pruned": int(files_pruned),
            "nodes_count": int(nodes_count),
            "edges_count": int(edges_count),
        }

        if tx is not None:
            res = tx.run(query, **params)
            record = res.single()
            return dict(record["s"]) if record and "s" in record else params
        else:
            with self.session() as session:
                res = session.run(query, **params)
                record = res.single()
                return dict(record["s"]) if record and "s" in record else params

    def get_sync_state(self, repo_id: str) -> dict:
        """
        Retrieves the repository-scoped SyncState dictionary for a specific repo_id.
        Returns None if no SyncState exists for this repository.
        """
        if not repo_id or not repo_id.strip():
            raise ValueError("repo_id must be provided to get_sync_state().")
        clean_repo = repo_id.strip()
        sync_id = f"repo:{clean_repo}:sync"

        with self.session() as session:
            query = "MATCH (s:SyncState {id: $sync_id}) RETURN s"
            res = session.run(query, sync_id=sync_id)
            record = res.single()
            if record and record.get("s"):
                return dict(record["s"])
            return None

    def get_connected_files(self, repo_id: str, file_path: str, max_depth: int = 1) -> list:
        """
        Finds all files in the repository that are structurally connected to the given file
        (via CALLS relationships between functions in either incoming or outgoing direction).
        
        Strict Isolation Guarantee:
        All traversals are strictly filtered by repo_id. No nodes or relationships from any
        other repository can be reached or returned.
        """
        if not repo_id or not repo_id.strip():
            raise ValueError("repo_id must be provided for repository-scoped connected-file investigation.")
        
        clean_repo = repo_id.strip()
        norm_fp = os.path.normpath(file_path).replace("\\", "/")
        norm_base = os.path.basename(file_path)

        with self.session() as session:
            query = """
            MATCH (origin:File {repo_id: $repo_id})
            WHERE origin.path = $file_path 
               OR origin.file_path = $file_path
               OR origin.rel_path = $file_path
               OR origin.rel_path = $norm_fp
               OR origin.name = $norm_base
            OPTIONAL MATCH (origin)-[:CONTAINS*1..2]->(f1:Function {repo_id: $repo_id})-[r:CALLS]-(f2:Function {repo_id: $repo_id})<-[:CONTAINS*1..2]-(target:File {repo_id: $repo_id})
            WHERE target <> origin
            RETURN DISTINCT coalesce(target.rel_path, target.file_path, target.name) AS connected_file
            """
            res = session.run(
                query,
                repo_id=clean_repo,
                file_path=file_path,
                norm_fp=norm_fp,
                norm_base=norm_base
            )
            connected = [r["connected_file"] for r in res if r.get("connected_file")]
            return sorted(list(set(connected)))


