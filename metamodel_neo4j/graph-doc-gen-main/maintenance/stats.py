import time
from database.neo4j_client import Neo4jClient

def print_performance_stats(start_time):
    """
    Computes processing time and queries Neo4j for graph statistics.
    This helps in generating technical reports and research evaluations.
    """
    elapsed = time.time() - start_time
    
    print("\n" + "="*40)
    print("      PERFORMANCE & GRAPH STATS      ")
    print("="*40)
    print(f"Total Processing Time : {elapsed:.2f} seconds")
    
    client = Neo4jClient()
    try:
        with client.session() as session:
            # Basic graph volume
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            
            # Module/clustering stats
            module_count = session.run("MATCH (m:Module) RETURN count(m) AS c").single()["c"]
            
            # Sub-type breakdown
            classes = session.run("MATCH (c:Class) RETURN count(c) AS c").single()["c"]
            functions = session.run("MATCH (f:Function) RETURN count(f) AS c").single()["c"]
            files = session.run("MATCH (f:File) RETURN count(f) AS c").single()["c"]

            # Calculates density
            density = (edge_count / node_count) if node_count > 0 else 0
            
            print(f"Total Graph Nodes     : {node_count}")
            print(f"Total Graph Edges     : {edge_count}")
            print(f"Graph Density         : {density:.2f}")
            print(f"Abstracted Modules    : {module_count} communities identified")
            print("-" * 40)
            print("Graph Composition Breakdown:")
            print(f"  - Files     : {files}")
            print(f"  - Classes   : {classes}")
            print(f"  - Functions : {functions}")

            
            estimated_size_kb = (node_count * 2.5) + (edge_count * 1.5)
            print("-" * 40)
            print(f"Est. Topological Size : ~{estimated_size_kb:.2f} KB (in-memory)")
            
    except Exception as e:
        print(f"Failed to fetch stats: {e}")
    finally:
        client.close()
    
    print("="*40 + "\n")
