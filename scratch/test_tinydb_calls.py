import sys
sys.path.insert(0, r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\metadata_model\extracted\graph-doc-gen-main")
from database.neo4j_client import Neo4jClient

def test_calls(repo_id, changed_file):
    client = Neo4jClient()
    with client.session() as session:
        # Match the changed file
        q = """
        MATCH (origin:File {repo_id: $repo_id})
        WHERE origin.rel_path = $changed_file OR origin.name = $changed_file
        MATCH (origin)-[:CONTAINS*1..2]->(f1:Function {repo_id: $repo_id})
        MATCH (caller:Function {repo_id: $repo_id})-[r:CALLS]->(f1)
        MATCH (caller_file:File {repo_id: $repo_id})-[:CONTAINS*1..2]->(caller)
        WHERE caller_file <> origin
        RETURN caller_file.rel_path as caller_file,
               caller.name as caller_func,
               f1.name as target_func,
               origin.rel_path as target_file
        ORDER BY caller_file, caller_func
        """
        res = list(session.run(q, repo_id=repo_id, changed_file=changed_file))
        print(f"\nDirect callers of {changed_file} in {repo_id} ({len(res)} call relationships):")
        for r in res[:10]:
            print(f"  {r['caller_file']} -> {r['caller_func']}() calls {r['target_func']}() [{r['target_file']}]")
    client.close()

if __name__ == "__main__":
    test_calls("sample/test-repo", "utils.py")
    test_calls("msiemens/tinydb", "tinydb/storages.py")
    test_calls("msiemens/tinydb", "tinydb/utils.py")
