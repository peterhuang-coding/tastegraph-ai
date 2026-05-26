import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import networkx as nx

from taste_graph_ai.domain.enums import NodeType, RelationType
from taste_graph_ai.graph.schema import GraphNode, GraphEdge, GraphQueryResult


class TasteGraph:
    """Core knowledge graph for taste preferences.

    Wraps a NetworkX DiGraph. All weights are on edges.
    Positive = prefers, negative = avoids.
    """

    def __init__(self, data_path: Optional[Path] = None):
        self.graph = nx.DiGraph()
        self.data_path = data_path

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.graph

    # ── Node operations ──────────────────────────────────────

    def add_node(
        self,
        label: str,
        node_type: NodeType,
        node_id: Optional[str] = None,
        **properties,
    ) -> str:
        node_id = node_id or f"{node_type.value}:{label.lower().replace(' ', '_')}"
        self.graph.add_node(
            node_id,
            type=node_type,
            label=label,
            properties=properties,
        )
        return node_id

    def remove_node(self, node_id: str) -> None:
        self.graph.remove_node(node_id)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        if node_id not in self.graph:
            return None
        data = self.graph.nodes[node_id]
        return GraphNode(
            id=node_id,
            type=data["type"],
            label=data["label"],
            properties=data.get("properties", {}),
        )

    def list_nodes(self, node_type: Optional[NodeType] = None) -> list[GraphNode]:
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            if node_type and data["type"] != node_type:
                continue
            nodes.append(GraphNode(
                id=node_id,
                type=data["type"],
                label=data["label"],
                properties=data.get("properties", {}),
            ))
        return nodes

    def search_nodes(self, query: str) -> list[GraphNode]:
        q = query.lower()
        return [
            node for node in self.list_nodes()
            if q in node.label.lower() or q in node.id.lower()
        ]

    # ── Edge operations ──────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: RelationType,
        weight: float = 1.0,
    ) -> None:
        if source_id not in self.graph or target_id not in self.graph:
            raise ValueError(f"Nodes must exist: {source_id}, {target_id}")
        self.graph.add_edge(
            source_id,
            target_id,
            relation=relation,
            weight=weight,
            feedback_count=0,
            last_updated=datetime.now().isoformat(),
        )

    def has_edge(self, source_id: str, target_id: str) -> bool:
        return self.graph.has_edge(source_id, target_id)

    def remove_edge(self, source_id: str, target_id: str) -> None:
        self.graph.remove_edge(source_id, target_id)

    def get_edge(self, source_id: str, target_id: str) -> Optional[GraphEdge]:
        if not self.graph.has_edge(source_id, target_id):
            return None
        data = self.graph.edges[source_id, target_id]
        return GraphEdge(
            source=source_id,
            target=target_id,
            relation=data["relation"],
            weight=data["weight"],
            feedback_count=data.get("feedback_count", 0),
            last_updated=data.get("last_updated", ""),
        )

    def list_edges(self, relation: Optional[RelationType] = None) -> list[GraphEdge]:
        edges = []
        for u, v, data in self.graph.edges(data=True):
            if relation and data["relation"] != relation:
                continue
            edges.append(GraphEdge(
                source=u,
                target=v,
                relation=data["relation"],
                weight=data["weight"],
                feedback_count=data.get("feedback_count", 0),
                last_updated=data.get("last_updated", ""),
            ))
        return edges

    # ── Weight operations ────────────────────────────────────

    def adjust_weight(
        self,
        source_id: str,
        target_id: str,
        delta: float,
    ) -> float:
        """Adjust edge weight by delta. Returns new weight."""
        if not self.graph.has_edge(source_id, target_id):
            raise ValueError(f"Edge not found: {source_id} -> {target_id}")
        edge = self.graph.edges[source_id, target_id]
        edge["weight"] = round(edge["weight"] + delta, 2)
        edge["feedback_count"] = edge.get("feedback_count", 0) + 1
        edge["last_updated"] = datetime.now().isoformat()
        return edge["weight"]

    def propagate_feedback(
        self,
        node_id: str,
        delta: float,
        depth: int = 2,
        decay: float = 0.5,
    ) -> list[tuple[str, str, float]]:
        """Propagate weight adjustment through graph via BFS.

        Returns list of (source, target, new_weight) for updated edges.
        """
        updated = []
        visited = {node_id}
        frontier = {node_id}

        for d in range(depth):
            next_frontier = set()
            layer_delta = delta * (decay ** d)

            for current in frontier:
                # Outgoing edges
                for _, neighbor in self.graph.out_edges(current):
                    if neighbor not in visited:
                        try:
                            new_w = self.adjust_weight(current, neighbor, layer_delta)
                            updated.append((current, neighbor, new_w))
                        except ValueError:
                            pass
                        visited.add(neighbor)
                        next_frontier.add(neighbor)

                # Incoming edges
                for neighbor, _ in self.graph.in_edges(current):
                    if neighbor not in visited:
                        try:
                            new_w = self.adjust_weight(neighbor, current, layer_delta)
                            updated.append((neighbor, current, new_w))
                        except ValueError:
                            pass
                        visited.add(neighbor)
                        next_frontier.add(neighbor)

            frontier = next_frontier

        return updated

    # ── Scoring ──────────────────────────────────────────────

    def score_content(
        self,
        keywords: list[str],
        source_id: Optional[str] = None,
        visual_tags: Optional[list[str]] = None,
    ) -> float:
        """Score content against the taste graph.

        Walks from keyword-matched concept nodes, accumulating
        edge weights along prefers/avoids paths.
        """
        if not keywords:
            return 0.0

        total_score = 0.0
        matched = 0

        for keyword in keywords:
            kw_lower = keyword.lower().strip()
            # Find matching concept nodes
            for node_id, data in self.graph.nodes(data=True):
                if data["type"] not in (NodeType.CONCEPT, NodeType.VISUAL_ELEMENT, NodeType.MOOD):
                    continue
                label = data["label"].lower()
                if kw_lower in label or label in kw_lower:
                    # Aggregate preference score from outgoing edges
                    node_score = 0.0
                    edge_count = 0
                    for _, target, edge_data in self.graph.out_edges(node_id, data=True):
                        if edge_data["relation"] in (RelationType.PREFERS, RelationType.AVOIDS):
                            node_score += edge_data["weight"]
                            edge_count += 1
                    if edge_count > 0:
                        total_score += node_score / edge_count
                    else:
                        total_score += 1.0  # Matched keyword but no edges yet
                    matched += 1

        # Source bonus
        if source_id and source_id in self.graph:
            source_bonus = 0.0
            for _, _, data in self.graph.in_edges(source_id, data=True):
                if data["relation"] == RelationType.PREFERS:
                    source_bonus += data["weight"]
            total_score += source_bonus

        return round(total_score / max(matched, 1), 2)

    # ── Persistence ──────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize graph to JSON-safe dict."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "type": data["type"].value,
                "label": data["label"],
                "properties": data.get("properties", {}),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "relation": data["relation"].value,
                "weight": data["weight"],
                "feedback_count": data.get("feedback_count", 0),
                "last_updated": data.get("last_updated", ""),
            })

        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: dict) -> "TasteGraph":
        tg = cls()
        for node in data.get("nodes", []):
            tg.graph.add_node(
                node["id"],
                type=NodeType(node["type"]),
                label=node["label"],
                properties=node.get("properties", {}),
            )
        for edge in data.get("edges", []):
            tg.graph.add_edge(
                edge["source"],
                edge["target"],
                relation=RelationType(edge["relation"]),
                weight=edge["weight"],
                feedback_count=edge.get("feedback_count", 0),
                last_updated=edge.get("last_updated", ""),
            )
        return tg

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or self.data_path
        if target is None:
            raise ValueError("No data_path configured")
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: Path) -> "TasteGraph":
        data = json.loads(path.read_text(encoding="utf-8"))
        tg = cls.from_dict(data)
        tg.data_path = path
        return tg

    # ── Stats ────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def overview(self) -> dict:
        type_counts = {}
        for _, data in self.graph.nodes(data=True):
            t = data["type"].value
            type_counts[t] = type_counts.get(t, 0) + 1

        rel_counts = {}
        for _, _, data in self.graph.edges(data=True):
            r = data["relation"].value
            rel_counts[r] = rel_counts.get(r, 0) + 1

        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "node_types": type_counts,
            "edge_relations": rel_counts,
        }
