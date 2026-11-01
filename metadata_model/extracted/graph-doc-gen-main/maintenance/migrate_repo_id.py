"""
Migration utility to safely annotate un-scoped legacy Neo4j graph nodes with a stable repo_id.
Safely updates existing nodes without deleting any production graph data.
"""
from database.neo4j_client import Neo4jClient


def migrate_legacy_nodes(default_repo_id: str = "legacy:default", database: str = None) -> dict:
    """
    Finds all nodes in the database where repo_id IS NULL and sets repo_id = default_repo_id.
    Also tags attached relationships where repo_id IS NULL with default_repo_id.
    Does NOT delete or recreate any existing graph data.
    """
    if not default_repo_id or not default_repo_id.strip():
        raise ValueError("default_repo_id must be provided to migrate_legacy_nodes().")

    clean_repo = default_repo_id.strip()
    client = Neo4jClient(database=database)
    try:
        with client.session() as session:
            count_res = session.run("MATCH (n) WHERE n.repo_id IS NULL RETURN count(n) AS cnt").single()
            unmigrated_count = count_res["cnt"]
            
            if unmigrated_count == 0:
                return {
                    "status": "up-to-date",
                    "migrated_nodes": 0,
                    "migrated_relationships": 0,
                    "default_repo_id": clean_repo
                }

            # Safely set repo_id on all un-scoped nodes
            node_update_res = session.run(
                """
                MATCH (n) 
                WHERE n.repo_id IS NULL 
                SET n.repo_id = $repo_id
                RETURN count(n) AS updated_nodes
                """,
                repo_id=clean_repo
            ).single()

            # Set repo_id on relationships between these nodes
            rel_update_res = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE r.repo_id IS NULL AND a.repo_id = $repo_id AND b.repo_id = $repo_id
                SET r.repo_id = $repo_id
                RETURN count(r) AS updated_rels
                """,
                repo_id=clean_repo
            ).single()

            return {
                "status": "migrated",
                "default_repo_id": clean_repo,
                "migrated_nodes": node_update_res["updated_nodes"],
                "migrated_relationships": rel_update_res["updated_rels"]
            }
    finally:
        client.close()
