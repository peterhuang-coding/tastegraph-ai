from dataclasses import dataclass, field
from typing import Optional

from taste_graph_ai.domain.enums import NodeType, RelationType


@dataclass
class GraphNode:
    id: str
    type: NodeType
    label: str
    properties: dict = field(default_factory=dict)

    @property
    def weight(self) -> float:
        return self.properties.get("weight", 1.0)

    @property
    def description(self) -> str:
        return self.properties.get("description", "")


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: RelationType
    weight: float = 1.0
    feedback_count: int = 0
    last_updated: str = ""


@dataclass
class GraphQueryResult:
    node: GraphNode
    score: float
    path: list[str] = field(default_factory=list)
    path_description: str = ""
