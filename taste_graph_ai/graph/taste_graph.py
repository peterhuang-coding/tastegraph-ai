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

        Multi-layer scoring:
        1. Keyword match: find concept/mood/visual_element nodes matching keywords,
           aggregate edge weights (prefers +, avoids -)
        2. Source bonus: established sources get weight-based bonus,
           new sources get exploration uplift
        3. Time decay: edges older than 90 days are down-weighted
        4. Returns a float typically in 0-15 range.

        Callers should normalize by TASTE_SCORE_NORMALIZATION_FACTOR (default 10.0).
        """
        if not keywords:
            return 0.0

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        decay_half_life_days = 90  # edges older than this are halved in weight

        total_score = 0.0
        matched = 0
        source_ids_seen: set[str] = set()  # for diversity tracking

        for keyword in keywords:
            kw_lower = keyword.lower().strip()
            if not kw_lower:
                continue
            # Find matching concept nodes
            for node_id, data in self.graph.nodes(data=True):
                if data["type"] not in (
                    NodeType.CONCEPT, NodeType.VISUAL_ELEMENT, NodeType.MOOD,
                ):
                    continue
                label = data["label"].lower()
                if kw_lower in label or label in kw_lower:
                    # Aggregate preference score from outgoing edges
                    node_score = 0.0
                    edge_count = 0
                    for _, target, edge_data in self.graph.out_edges(node_id, data=True):
                        if edge_data["relation"] in (
                            RelationType.PREFERS, RelationType.AVOIDS,
                        ):
                            weight = edge_data["weight"]
                            # Apply time decay
                            last_updated = edge_data.get("last_updated", "")
                            if last_updated:
                                try:
                                    edge_time = datetime.fromisoformat(last_updated)
                                    age_days = (now - edge_time).days
                                    if age_days > decay_half_life_days:
                                        weight *= 0.5 ** (
                                            age_days / decay_half_life_days
                                        )
                                except (ValueError, TypeError):
                                    pass
                            node_score += weight
                            edge_count += 1
                            # Track source for diversity
                            source_ids_seen.add(target)

                    if edge_count > 0:
                        total_score += node_score / edge_count
                    else:
                        total_score += 1.0  # Matched keyword but no edges yet
                    matched += 1

        # Source bonus: established sources get weight-based bonus,
        # new/exploratory sources get a small uplift to ensure visibility
        if source_id and source_id in self.graph:
            source_bonus = 0.0
            in_edge_count = 0
            for _, _, data in self.graph.in_edges(source_id, data=True):
                if data["relation"] == RelationType.PREFERS:
                    source_bonus += data["weight"]
                    in_edge_count += 1
            # Cold-start boost: sources with few connections get baseline boost
            if in_edge_count == 0:
                source_bonus = 0.3  # Pure exploration
            elif in_edge_count < 3:
                source_bonus = max(source_bonus, 0.15)  # Under-connected boost
            total_score += source_bonus

        # Diversity penalty: repeated same-source matches → mild penalty
        diversity_penalty = max(0, (len(source_ids_seen) - 3) * 0.05)
        total_score -= diversity_penalty

        return round(total_score / max(matched, 1), 2)

    # ── Graph Enrichment ─────────────────────────────────────

    def enrich_from_crawl(
        self,
        source_name: str,
        source_url: str = "",
        visible_text: str = "",
        page_title: str = "",
        alt_texts: list[str] | None = None,
    ) -> int:
        """Auto-enrich graph from crawl output.

        Creates concept nodes from crawl page text and links them to
        the source via APPEARS_WITH edges with cumulative weights.

        Returns count of new nodes created.
        """
        if not visible_text and not page_title:
            return 0

        # Find or create source node
        source_node_id = None
        for node_id, data in self.graph.nodes(data=True):
            if data["type"] == NodeType.SOURCE and data["label"] == source_name:
                source_node_id = node_id
                break
        if not source_node_id:
            source_node_id = self.add_node(
                source_name, NodeType.SOURCE,
                auto_discovered=True,
                source="crawl_enrichment",
                url=source_url,
            )

        # Extract candidate keywords from visible text + title + alt texts
        text_blob = f"{page_title} {visible_text}"
        if alt_texts:
            text_blob += " " + " ".join(alt_texts)

        # Simple keyword extraction: find capitalized words, compound nouns,
        # and material/color/object indicators in the visible text
        import re
        new_count = 0
        # Extract: brands (ALL_CAPS words), colors (common color words),
        # materials (fabric/texture words), objects (compound nouns)
        found_concepts: list[tuple[str, NodeType]] = []

        # Color detection
        color_words = [
            "black", "white", "grey", "gray", "navy", "olive", "beige",
            "cream", "khaki", "brown", "tan", "charcoal", "slate", "sand",
            "stone", "ivory", "camel", "burgundy", "rust", "sage",
            "黑色", "白色", "灰色", "蓝色", "橄榄色", "米色", "棕色",
        ]
        for cw in color_words:
            if cw.lower() in text_blob.lower():
                found_concepts.append((cw.capitalize(), NodeType.COLOR))

        # Material detection
        material_words = [
            "cotton", "wool", "silk", "linen", "leather", "denim", "canvas",
            "nylon", "polyester", "cashmere", "tweed", "gabardine", "ripstop",
            "concrete", "steel", "glass", "wood", "stone", "aluminum",
            "棉", "羊毛", "丝", "亚麻", "皮革", "牛仔", "帆布",
            "混凝土", "钢", "玻璃", "木头", "石材",
        ]
        for mw in material_words:
            if mw.lower() in text_blob.lower():
                found_concepts.append((mw.capitalize(), NodeType.OBJECT))

        # Brand detection: ALL_CAPS words of 2+ chars in visible text
        caps_matches = re.findall(r'\b([A-Z][A-Z0-9]{1,}(?:\s+[A-Z][A-Z0-9]{1,})?)\b', text_blob)
        for brand in caps_matches[:5]:
            if len(brand) >= 2:
                found_concepts.append((brand.strip(), NodeType.BRAND))

        # Create nodes and edges
        for concept_label, node_type in found_concepts:
            node_id = f"{node_type.value}:{concept_label.lower().replace(' ', '_')}"
            if node_id not in self.graph:
                self.add_node(
                    concept_label, node_type,
                    node_id=node_id,
                    source="crawl_enrichment",
                )
                new_count += 1

            # APPEARS_WITH edge with cumulative weight
            if self.has_edge(source_node_id, node_id):
                # Increment existing weight
                edge = self.graph.edges[source_node_id, node_id]
                current_weight = edge.get("weight", 0.0)
                edge["weight"] = min(current_weight + 0.15, 1.0)
                edge["last_updated"] = datetime.now().isoformat()
            else:
                self.add_edge(
                    source_node_id, node_id,
                    RelationType.APPEARS_WITH,
                    weight=0.3,
                )

        return new_count

    def enrich_from_content(
        self,
        source_name: str,
        entities: dict,
    ) -> int:
        """Auto-create nodes and edges from AI-extracted entities.

        `entities` format: {brands, designers, colors, materials, moods, objects, locations}
        Returns count of new nodes created.
        """
        source_node_id = None
        # Find source node by name
        for node_id, data in self.graph.nodes(data=True):
            if data["type"].value == "source" and data["label"] == source_name:
                source_node_id = node_id
                break
        if not source_node_id:
            source_node_id = self.add_node(
                source_name, NodeType.SOURCE,
                auto_discovered=True,
                source="ai_entity_extraction",
            )

        category_map = {
            "brands": NodeType.BRAND,
            "designers": NodeType.BRAND,  # Designers stored as BRAND nodes
            "colors": NodeType.COLOR,
            "materials": NodeType.OBJECT,  # Materials stored as OBJECT nodes
            "moods": NodeType.MOOD,
            "objects": NodeType.OBJECT,
            "locations": NodeType.LOCATION,
        }

        new_count = 0
        for category, node_type in category_map.items():
            items = entities.get(category, [])
            for item in items:
                item = item.strip()
                if not item:
                    continue
                node_id = f"{node_type.value}:{item.lower().replace(' ', '_')}"
                if node_id not in self.graph:
                    self.add_node(
                        item, node_type,
                        node_id=node_id,
                        source="ai_entity_extraction",
                    )
                    new_count += 1
                # Link source to entity via APPEARS_WITH with cumulative weight.
                # First appearance: weight=0.3. Each repeat: +0.15, cap at 1.0.
                if self.has_edge(source_node_id, node_id):
                    edge = self.graph.edges[source_node_id, node_id]
                    current_weight = edge.get("weight", 0.0)
                    edge["weight"] = min(current_weight + 0.15, 1.0)
                    edge["last_updated"] = datetime.now().isoformat()
                else:
                    self.add_edge(
                        source_node_id, node_id,
                        RelationType.APPEARS_WITH,
                        weight=0.3,
                    )

        return new_count

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
