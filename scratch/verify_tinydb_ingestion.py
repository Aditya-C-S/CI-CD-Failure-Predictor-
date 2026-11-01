import os
import sys

sys.path.insert(0, r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\metadata_model\extracted\graph-doc-gen-main")
from database.neo4j_client import Neo4jClient

def main():
    client = Neo4jClient()
    with client.session() as session:
        repos = [r["repo_id"] for r in session.run("MATCH (n) WHERE n.repo_id IS NOT NULL RETURN DISTINCT n.repo_id as repo_id")]
        print("Repositories in Neo4j:", repos)

        node_counts = [(r["label"], r["count"]) for r in session.run("MATCH (n {repo_id: 'msiemens/tinydb'}) RETURN labels(n)[0] as label, count(n) as count")]
        print("msiemens/tinydb node counts:", node_counts)

        edge_counts = [(r["type"], r["count"]) for r in session.run("MATCH ()-[r {repo_id: 'msiemens/tinydb'}]->() RETURN type(r) as type, count(r) as count")]
        print("msiemens/tinydb edge counts:", edge_counts)

        sync_state = client.get_sync_state("msiemens/tinydb")
        print("msiemens/tinydb SyncState:", sync_state)

        # Test connected files for a key module, e.g., 'tinydb/utils.py' or 'tinydb/database.py'
        connected = client.get_connected_files("msiemens/tinydb", "tinydb/storages.py")
        print("Connected files to 'tinydb/storages.py':", connected)

        connected_utils = client.get_connected_files("msiemens/tinydb", "tinydb/utils.py")
        print("Connected files to 'tinydb/utils.py':", connected_utils)

    client.close()

if __name__ == "__main__":
    main()
