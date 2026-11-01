import sys
sys.path.insert(0, r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\metadata_model\extracted\graph-doc-gen-main")
from database.neo4j_client import Neo4jClient

def test_subgraph_query(repo_id, changed_files):
    client = Neo4jClient()
    with client.session() as session:
        # 1. Match origin files and their functions
        # 2. Match callers and their files
        query = """
        MATCH (origin:File {repo_id: $repo_id})
        WHERE any(cf IN $changed_files WHERE 
                  origin.path ENDS WITH cf 
               OR origin.file_path ENDS WITH cf 
               OR origin.rel_path ENDS WITH cf 
               OR origin.name = cf)
        OPTIONAL MATCH (origin)-[r_contains:CONTAINS*1..2]->(f1:Function {repo_id: $repo_id})
        OPTIONAL MATCH (caller:Function {repo_id: $repo_id})-[r_calls:CALLS]->(f1)
        OPTIONAL MATCH (caller_file:File {repo_id: $repo_id})-[:CONTAINS*1..2]->(caller)
        RETURN origin, f1, caller, caller_file, r_calls
        """
        res = session.run(query, repo_id=repo_id, changed_files=changed_files)
        records = list(res)
        print(f"Results for {repo_id} ({changed_files}): {len(records)} records")
        for r in records[:5]:
            orig = r["origin"]["name"] if r["origin"] else None
            f1 = r["f1"]["name"] if r["f1"] else None
            caller = r["caller"]["name"] if r["caller"] else None
            cfile = r["caller_file"]["name"] if r["caller_file"] else None
            print(f"  Origin: {orig} -> Func: {f1} <- Caller: {caller} (in {cfile})")
    client.close()

if __name__ == "__main__":
    print("Testing sample/test-repo:")
    test_subgraph_query("sample/test-repo", ["utils.py"])
    print("\nTesting msiemens/tinydb:")
    test_subgraph_query("msiemens/tinydb", ["tinydb/storages.py", "storages.py"])
