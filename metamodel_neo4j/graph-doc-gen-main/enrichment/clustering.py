import igraph as ig
from database.neo4j_client import Neo4jClient

def cluster_graph():
    """
    Fetch the codebase graph from Neo4j, cluster nodes using Leiden community detection.
    Returns: a dictionary mapping community_id to lists of node properties.
    """
    client = Neo4jClient()
    
    # Query nodes
    with client.session() as session:
        result = session.run("MATCH (n) RETURN n.id AS id, n.name AS name, labels(n) AS labels")
        nodes_raw = [record.data() for record in result]
        
        result_edges = session.run("MATCH (a)-[r]->(b) RETURN a.id AS source, b.id AS target, type(r) AS type")
        edges_raw = [record.data() for record in result_edges]

    client.close()

    if not nodes_raw:
        return {}

    # Map Neo4j node IDs to igraph index integers
    node_id_to_idx = {n["id"]: i for i, n in enumerate(nodes_raw)}
    idx_to_node = {i: n for i, n in enumerate(nodes_raw)}

    g = ig.Graph(directed=True)
    g.add_vertices(len(nodes_raw))

    edges = []
    for e in edges_raw:
        if e["source"] in node_id_to_idx and e["target"] in node_id_to_idx:
            edges.append((node_id_to_idx[e["source"]], node_id_to_idx[e["target"]]))
    
    g.add_edges(edges)

    # Perform Leiden clustering on an undirected view
    undirected_g = g.as_undirected()
    partition = undirected_g.community_leiden(objective_function="modularity")

    clusters = {}
    for cluster_id, elements in enumerate(partition):
        cluster_nodes = [idx_to_node[idx] for idx in elements]
        if cluster_nodes:
            clusters[cluster_id] = cluster_nodes

    return clusters
