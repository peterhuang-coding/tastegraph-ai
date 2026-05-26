import json
import re
from pathlib import Path
from typing import Optional

from taste_graph_ai.domain.enums import NodeType, RelationType
from taste_graph_ai.graph.taste_graph import TasteGraph


class SeedLoader:
    """Load existing taste data into the knowledge graph."""

    def __init__(self, graph: TasteGraph, base_dir: Path):
        self.graph = graph
        self.base_dir = Path(base_dir)

    def load_all(self) -> TasteGraph:
        self._load_taste_memory()
        self._load_taste_ip_system()
        self._load_link_sources()
        return self.graph

    def _load_taste_memory(self) -> None:
        path = self.base_dir / "taste_memory.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))

        # North star concepts
        ns = self.graph.add_node("north_star", NodeType.CONCEPT,
                                 description=" ".join(data.get("north_star", [])))

        # Preferred keywords → Concept nodes with prefers edges
        prefer = data.get("prefer", {})
        for keyword in prefer.get("keywords", []):
            node_id = self.graph.add_node(keyword, NodeType.CONCEPT,
                                          source="taste_memory.json",
                                          category="preferred_keyword")
            self.graph.add_edge(ns, node_id, RelationType.PREFERS,
                                weight=data.get("score_weights", {}).get("preferred_keyword", 3))

        # Preferred channels → Source nodes with prefers edges
        for channel in prefer.get("channels", []):
            node_id = self.graph.add_node(channel, NodeType.SOURCE,
                                          source="taste_memory.json",
                                          platform="are.na",
                                          category="preferred_channel")
            self.graph.add_edge(ns, node_id, RelationType.PREFERS,
                                weight=data.get("score_weights", {}).get("preferred_channel", 8))

        # Visual rules → VisualElement nodes
        for rule in prefer.get("visual_rules", []):
            node_id = self.graph.add_node(rule, NodeType.VISUAL_ELEMENT,
                                          source="taste_memory.json")
            self.graph.add_edge(ns, node_id, RelationType.PREFERS, weight=2)

        # Avoided keywords → Concept nodes with avoids edges
        avoid = data.get("avoid", {})
        for keyword in avoid.get("keywords", []):
            node_id = self.graph.add_node(keyword, NodeType.CONCEPT,
                                          source="taste_memory.json",
                                          category="avoided_keyword")
            self.graph.add_edge(ns, node_id, RelationType.AVOIDS,
                                weight=data.get("score_weights", {}).get("avoided_keyword", -6))

        # Visual rules to avoid
        for rule in avoid.get("visual_rules", []):
            node_id = self.graph.add_node(rule, NodeType.VISUAL_ELEMENT,
                                          source="taste_memory.json",
                                          category="avoided_visual")
            self.graph.add_edge(ns, node_id, RelationType.AVOIDS, weight=-4)

        # Feedback history
        for fb in data.get("feedback", []):
            for kw in fb.get("like", []):
                node_id = f"concept:{kw.lower().replace(' ', '_')}"
                if node_id in self.graph:
                    self.graph.adjust_weight(ns, node_id, +1)
            for kw in fb.get("avoid", []):
                node_id = f"concept:{kw.lower().replace(' ', '_')}"
                if node_id in self.graph:
                    self.graph.adjust_weight(ns, node_id, -1)

    def _load_taste_ip_system(self) -> None:
        path = self.base_dir / "taste_ip_system.md"
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")

        # Extract content pillars (## Content Pillars → ### N. Name)
        pillar_pattern = re.compile(r'###\s+\d+\.\s+(.+?)\n\n(.+?)(?=###|\Z)', re.DOTALL)
        pillars_section = text.split("## Content Pillars")
        if len(pillars_section) > 1:
            for match in pillar_pattern.finditer(pillars_section[1]):
                name = match.group(1).strip()
                purpose_block = match.group(2)
                purpose_match = re.search(r'Purpose:\s*\n(.+?)$', purpose_block, re.MULTILINE)
                purpose = purpose_match.group(1).strip() if purpose_match else ""

                pillar_id = self.graph.add_node(
                    name, NodeType.PILLAR,
                    description=purpose,
                    source="taste_ip_system.md",
                )
                ns = "concept:north_star"
                if ns in self.graph:
                    self.graph.add_edge(pillar_id, ns, RelationType.BELONGS_TO, weight=1.0)

        # Extract taste rules
        rules_section = text.split("## Taste Rules")
        if len(rules_section) > 1:
            rules_text = rules_section[1].split("##")[0]
            for line in rules_text.strip().split("\n"):
                line = line.strip("- ").strip()
                if line and not line.startswith("#"):
                    self.graph.add_node(
                        f"rule: {line[:80]}",
                        NodeType.CONCEPT,
                        description=line,
                        source="taste_ip_system.md",
                    )

        # Extract voice preferences from "Avoid:" and "Prefer:" bullets
        voice_section = text.split("## Voice")
        if len(voice_section) > 1:
            voice_text = voice_section[1]
            for avoid_line in re.findall(r'Avoid:.*?\n((?:\s*-\s*.+\n?)+)', voice_text):
                for item in re.findall(r'-\s*"(.+?)"', avoid_line):
                    node_id = self.graph.add_node(
                        f"voice: {item[:60]}",
                        NodeType.CONCEPT,
                        description=item,
                        category="avoided_voice",
                        source="taste_ip_system.md",
                    )
                    ns = "concept:north_star"
                    if ns in self.graph:
                        self.graph.add_edge(ns, node_id, RelationType.AVOIDS, weight=-3)

    def _load_link_sources(self) -> None:
        path = self.base_dir / "link_sources.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))

        # Map categories to source types
        category_map = {
            "lookbook_images": "lookbook",
            "videos": "video",
            "articles": "article",
        }

        for category, sources in data.items():
            if not isinstance(sources, list):
                continue
            source_type = category_map.get(category, "mixed")
            for src in sources:
                node_id = self.graph.add_node(
                    src["name"],
                    NodeType.SOURCE,
                    url=src.get("url", ""),
                    source_type=source_type,
                    why=src.get("why", ""),
                    source="link_sources.json",
                )
                # Link to north_star via PREFERS edge
                ns = "concept:north_star"
                if ns in self.graph:
                    self.graph.add_edge(ns, node_id, RelationType.PREFERS, weight=3)

                # Link source to related concepts based on "why" text
                why_text = src.get("why", "").lower()
                for node in list(self.graph.graph.nodes(data=True)):
                    node_id_existing = node[0]
                    node_data = node[1]
                    if node_data["type"] == NodeType.CONCEPT:
                        concept_label = node_data["label"].lower()
                        if concept_label in why_text or any(
                            word in why_text for word in concept_label.split()
                        ):
                            if not self.graph.has_edge(node_id, node_id_existing):
                                self.graph.add_edge(
                                    node_id, node_id_existing,
                                    RelationType.APPEARS_WITH,
                                    weight=1.0,
                                )
