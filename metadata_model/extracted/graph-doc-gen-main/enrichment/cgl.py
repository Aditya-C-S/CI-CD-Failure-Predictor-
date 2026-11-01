import igraph as ig
import torch
import torch.nn.functional as F

class ContinualGraphLearner:
    def __init__(self, old_nodes, old_edges):
        """
        Initializes the CGL state tracking with the baseline graph before new parsing.
        """
        self.old_nodes = set(old_nodes)
        self.old_edges = old_edges

    # ==========================================
    # 1. HIERARCHICAL ORDERING (BFS EXPANSION)
    # ==========================================
    def partition_into_layers(self, new_edges):
        """
        Paper 1 (IncDE): Inter-Hierarchical Ordering.
        Uses Breadth-First Search (BFS) to partition new AST edges into learning layers
        based on their structural distance from the known 'old' graph.
        """
        layers = []
        current_known_nodes = set(self.old_nodes)
        unassigned_edges = list(new_edges)
        
        while unassigned_edges:
            next_layer_edges = []
            remaining_edges = []
            new_known_nodes = set()
            
            for edge in unassigned_edges:
                source, target = edge['from'], edge['to']
                # If the new connection touches the existing structural latent space
                if source in current_known_nodes or target in current_known_nodes:
                    next_layer_edges.append(edge)
                    new_known_nodes.add(source)
                    new_known_nodes.add(target)
                else:
                    remaining_edges.append(edge)
                    
            if not next_layer_edges:
                # Disconnected new subgraph (e.g., an entirely new independent module)
                layers.append(remaining_edges)
                break
                
            layers.append(next_layer_edges)
            current_known_nodes.update(new_known_nodes)
            unassigned_edges = remaining_edges
            
        return layers

    def calculate_structural_hubs(self, edges):
        """
        Paper 1 (IncDE): Intra-Hierarchical Ordering.
        Calculates Node Centrality (f_nc) and Betweenness Centrality (f_bc) 
        to assign distillation weights (lambda) to entities.
        """
        if not edges:
            return {}
            
        unique_nodes = list(set([e['from'] for e in edges] + [e['to'] for e in edges]))
        if not unique_nodes:
            return {}

        node_to_idx = {n: i for i, n in enumerate(unique_nodes)}
        idx_to_node = {i: n for i, n in enumerate(unique_nodes)}
        
        g = ig.Graph(directed=True)
        g.add_vertices(len(unique_nodes))
        g.add_edges([(node_to_idx[e['from']], node_to_idx[e['to']]) for e in edges])
        
        # Equation 1: Node Centrality
        degrees = g.degree(mode="all")
        N = len(unique_nodes)
        f_nc = {idx_to_node[i]: deg / max(1, N - 1) for i, deg in enumerate(degrees)}
        
        # Equation 6: Entity Betweenness Centrality
        betweenness = g.betweenness(directed=True)
        f_bc = {idx_to_node[i]: bet for i, bet in enumerate(betweenness)}
        
        # Equation 7: Combined Importance lambda weights
        hub_weights = {}
        for node in unique_nodes:
            hub_weights[node] = f_nc[node] + f_bc[node]
            
        return hub_weights

    # ==========================================
    # 2. INCREMENTAL DISTILLATION (ID)
    # ==========================================
    def incremental_distillation_loss(self, e_current, e_previous, lambda_weight):
        """
        Paper 1 (IncDE): Equation 5.
        Seamless transfer of entity representations to prevent catastrophic forgetting.
        Mathematically, this piecewise function maps perfectly to PyTorch's Huber Loss.
        """
        # Ensure inputs are tensors
        e_curr = torch.tensor(e_current, dtype=torch.float32)
        e_prev = torch.tensor(e_previous, dtype=torch.float32)
        
        # Huber Loss acts as L2 loss for small errors and L1 loss for large ones
        base_loss = F.huber_loss(e_curr, e_prev, delta=1.0, reduction='none')
        
        # Equation 9: Apply the dynamic structural weight
        return (lambda_weight * base_loss).mean().item()

    # ==========================================
    # 3. STRUCTURAL SHIFT MITIGATION (SSRM)
    # ==========================================
    def _gaussian_kernel(self, x, y, alphas=[1.0, 0.1, 0.01]):
        """Helper for SSRM: Calculates the multi-scale RBF/Gaussian kernel."""
        beta = 1.0
        dist = torch.cdist(x, y, p=2).pow(2)
        kernel_matrix = torch.zeros_like(dist)
        for alpha in alphas:
            kernel_matrix += beta * torch.exp(-alpha * dist)
        return kernel_matrix

    def maximum_mean_discrepancy(self, X_old_embeddings, Y_new_embeddings):
        """
        Paper 2 (SSRM): Equation 4.
        Calculates the MMD between the old graph structure and the new one.
        If this divergence spikes above a threshold during an update, it triggers a 
        warning that the architectural refactor is breaking the semantic latent space.
        """
        X = torch.tensor(X_old_embeddings, dtype=torch.float32)
        Y = torch.tensor(Y_new_embeddings, dtype=torch.float32)

        n_X = X.shape[0]
        n_Y = Y.shape[0]
        
        if n_X == 0 or n_Y == 0:
            return 0.0

        K_XX = self._gaussian_kernel(X, X)
        K_YY = self._gaussian_kernel(Y, Y)
        K_XY = self._gaussian_kernel(X, Y)

        # MMD^2 estimate
        mmd_sq = (
            K_XX.sum() / (n_X * n_X) +
            K_YY.sum() / (n_Y * n_Y) -
            2 * K_XY.sum() / (n_X * n_Y)
        )
        
        return torch.sqrt(torch.relu(mmd_sq)).item()