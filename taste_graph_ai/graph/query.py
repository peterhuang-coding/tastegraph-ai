from typing import Optional

from taste_graph_ai.domain.enums import NodeType, RelationType
from taste_graph_ai.graph.schema import GraphNode, GraphQueryResult
from taste_graph_ai.graph.taste_graph import TasteGraph


def find_best_path(
    graph: TasteGraph,
    keyword: str,
    target_type: Optional[NodeType] = None,
) -> Optional[GraphQueryResult]:
    """Find the best-scored path from a keyword to matching nodes."""
    # Find starting node (fuzzy match on keyword)
    start_node = None
    kw = keyword.lower()
    for node in graph.list_nodes():
        if kw in node.label.lower():
            start_node = node
            break

    if start_node is None:
        # Try creating a temporary lookup
        for node in graph.list_nodes():
            if any(part in node.label.lower() for part in kw.split()):
                start_node = node
                break

    if start_node is None:
        return None

    # BFS to find reachable nodes with accumulated preference score
    best_score = float("-inf")
    best_node = None
    best_path = []

    for target_id in graph.graph.nodes:
        if target_id == start_node.id:
            continue
        target_data = graph.graph.nodes[target_id]
        if target_type and target_data["type"] != target_type:
            continue

        try:
            path = nx_shortest_path(graph, start_node.id, target_id)
            score = 0.0
            for i in range(len(path) - 1):
                edge_data = graph.graph.edges.get((path[i], path[i + 1]))
                if edge_data:
                    score += edge_data.get("weight", 0)
            if score > best_score:
                best_score = score
                best_node = graph.get_node(target_id)
                best_path = path
        except Exception:
            continue

    if best_node is None:
        return None

    return GraphQueryResult(
        node=best_node,
        score=round(best_score, 2),
        path=best_path,
        path_description=" → ".join(
            graph.graph.nodes[n]["label"] for n in best_path
        ),
    )


def find_related_nodes(
    graph: TasteGraph,
    node_id: str,
    relation: Optional[RelationType] = None,
    max_depth: int = 2,
) -> list[GraphQueryResult]:
    """Find nodes related to a given node within max_depth hops."""
    if node_id not in graph.graph:
        return []

    results = []
    visited = {node_id}
    frontier = {node_id}

    for depth in range(max_depth):
        next_frontier = set()
        for current in frontier:
            for _, neighbor in graph.graph.out_edges(current):
                if neighbor not in visited:
                    edge_data = graph.graph.edges.get((current, neighbor))
                    edge_rel = edge_data["relation"] if edge_data else None
                    if relation is None or edge_rel == relation:
                        results.append(GraphQueryResult(
                            node=graph.get_node(neighbor),
                            score=edge_data["weight"] if edge_data else 1.0,
                            path=[current, neighbor],
                        ))
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier

    return results


def find_nodes_by_concept(
    graph: TasteGraph,
    concept_label: str,
) -> list[GraphNode]:
    """Fuzzy search for nodes matching a concept label."""
    q = concept_label.lower()
    results = []
    for node in graph.list_nodes():
        if q in node.label.lower() or any(
            q in v.lower() for v in node.properties.values() if isinstance(v, str)
        ):
            results.append(node)
    return results


def get_graph_paths(
    graph: TasteGraph,
    from_node: str,
    to_node: str,
    max_depth: int = 3,
) -> list[list[str]]:
    """Get all simple paths between two nodes up to max_depth."""
    try:
        return list(nx_all_simple_paths(graph.graph, from_node, to_node, cutoff=max_depth))
    except Exception:
        return []


# ── Internal helpers ────────────────────────────────────────

def nx_shortest_path(graph: TasteGraph, source: str, target: str) -> list[str]:
    import networkx as nx
    return nx.shortest_path(graph.graph, source=source, target=target)


def nx_all_simple_paths(graph, source, target, cutoff):
    import networkx as nx
    return nx.all_simple_paths(graph, source=source, target=target, cutoff=cutoff)
