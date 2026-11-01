import sys
sys.path.insert(0, r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\metadata_model\extracted\graph-doc-gen-main")
from database.neo4j_client import Neo4jClient

def list_repo_files(repo_id):
    client = Neo4jClient()
    with client.session() as session:
        res = session.run("MATCH (f:File {repo_id: $repo_id}) RETURN f.name as name, f.rel_path as rel_path ORDER BY f.rel_path", repo_id=repo_id)
        files = list(res)
        print(f"\nFiles for {repo_id} ({len(files)} files):")
        for f in files:
            print(f"  {f['rel_path']} ({f['name']})")
    client.close()

if __name__ == "__main__":
    list_repo_files("sample/test-repo")
    list_repo_files("msiemens/tinydb")
