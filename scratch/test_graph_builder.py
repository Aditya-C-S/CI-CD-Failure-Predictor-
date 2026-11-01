import os
import sys

sys.path.insert(0, r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\metadata_model\extracted\graph-doc-gen-main")
from database.neo4j_client import Neo4jClient

def build_cytoscape_subgraph(repo_id, changed_files):
    client = Neo4jClient()
    nodes = {}
    edges = {}

    with client.session() as session:
        for cf in changed_files:
            norm_base = os.path.basename(cf).replace("\\", "/")
            norm_cf = cf.replace("\\", "/")

            query = """
            MATCH (origin:File {repo_id: $repo_id})
            WHERE origin.path = $cf 
               OR origin.file_path = $cf
               OR origin.rel_path = $cf
               OR origin.rel_path = $norm_cf
               OR origin.name = $norm_base
            OPTIONAL MATCH (origin)-[:CONTAINS*1..2]->(target_func:Function {repo_id: $repo_id})
            OPTIONAL MATCH (caller_func:Function {repo_id: $repo_id})-[r_call:CALLS]->(target_func)
            OPTIONAL MATCH (caller_file:File {repo_id: $repo_id})-[:CONTAINS*1..2]->(caller_func)
            RETURN origin, target_func, caller_func, caller_file
            """
            res = session.run(query, repo_id=repo_id, cf=cf, norm_cf=norm_cf, norm_base=norm_base)
            for r in res:
                origin = r["origin"]
                target_func = r["target_func"]
                caller_func = r["caller_func"]
                caller_file = r["caller_file"]

                if origin:
                    orig_id = origin.get("id") or f"file:{origin.get('name')}"
                    orig_label = origin.get("rel_path") or origin.get("name")
                    nodes[orig_id] = {
                        "id": orig_id,
                        "label": orig_label,
                        "type": "File",
                        "status": "changed",
                        "file_path": origin.get("file_path") or origin.get("path") or orig_label
                    }

                if target_func and origin:
                    tf_id = target_func.get("id") or f"func:{target_func.get('name')}"
                    nodes[tf_id] = {
                        "id": tf_id,
                        "label": f"{target_func.get('name')}()",
                        "type": "Function",
                        "status": "changed",
                        "file_path": origin.get("rel_path") or origin.get("name")
                    }
                    edge_id = f"contains:{orig_id}->{tf_id}"
                    edges[edge_id] = {
                        "id": edge_id,
                        "source": orig_id,
                        "target": tf_id,
                        "type": "CONTAINS",
                        "label": "defines"
                    }

                if caller_func:
                    cf_id = caller_func.get("id") or f"func:{caller_func.get('name')}"
                    c_file_path = caller_file.get("rel_path") if caller_file else "unknown"
                    nodes[cf_id] = {
                        "id": cf_id,
                        "label": f"{caller_func.get('name')}()",
                        "type": "Function",
                        "status": "affected",
                        "file_path": c_file_path
                    }

                    if target_func:
                        call_id = f"calls:{cf_id}->{tf_id}"
                        edges[call_id] = {
                            "id": call_id,
                            "source": cf_id,
                            "target": tf_id,
                            "type": "CALLS",
                            "label": "calls"
                        }

                if caller_file:
                    cfile_id = caller_file.get("id") or f"file:{caller_file.get('name')}"
                    cfile_label = caller_file.get("rel_path") or caller_file.get("name")
                    nodes[cfile_id] = {
                        "id": cfile_id,
                        "label": cfile_label,
                        "type": "File",
                        "status": "affected",
                        "file_path": caller_file.get("file_path") or caller_file.get("path") or cfile_label
                    }
                    if caller_func:
                        c_edge_id = f"contains:{cfile_id}->{cf_id}"
                        edges[c_edge_id] = {
                            "id": c_edge_id,
                            "source": cfile_id,
                            "target": cf_id,
                            "type": "CONTAINS",
                            "label": "defines"
                        }

    client.close()
    cytoscape_elements = (
        [{"data": n} for n in nodes.values()] +
        [{"data": e} for e in edges.values()]
    )
    print(f"Built {len(nodes)} nodes and {len(edges)} edges for Cytoscape.js ({repo_id}):")
    print(f"  Nodes count: {len(nodes)} (Files: {sum(1 for n in nodes.values() if n['type']=='File')}, Functions: {sum(1 for n in nodes.values() if n['type']=='Function')})")
    print(f"  Edges count: {len(edges)} (Calls: {sum(1 for e in edges.values() if e['type']=='CALLS')}, Contains: {sum(1 for e in edges.values() if e['type']=='CONTAINS')})")
    return cytoscape_elements

if __name__ == "__main__":
    print("--- Testing sample/test-repo ---")
    el1 = build_cytoscape_subgraph("sample/test-repo", ["utils.py"])
    print("\n--- Testing msiemens/tinydb (tinydb/storages.py) ---")
    el2 = build_cytoscape_subgraph("msiemens/tinydb", ["tinydb/storages.py"])
