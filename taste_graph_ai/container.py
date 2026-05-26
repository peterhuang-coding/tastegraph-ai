"""Dependency injection container.

All services and repositories are wired here. The container is
a singleton that holds references to all components.

Usage:
    from taste_graph_ai.container import get_container
    container = get_container()
    graph = container.taste_graph
"""

from pathlib import Path
from typing import Optional

from taste_graph_ai.config import (
    BASE_DIR,
    GRAPH_FILE,
    ensure_dirs,
)
from taste_graph_ai.graph.taste_graph import TasteGraph
from taste_graph_ai.graph.seed_loader import SeedLoader


class Container:
    """Holds all application components."""

    def __init__(self):
        self._taste_graph: Optional[TasteGraph] = None

    @property
    def taste_graph(self) -> TasteGraph:
        if self._taste_graph is None:
            self._taste_graph = self._init_graph()
        return self._taste_graph

    def _init_graph(self) -> TasteGraph:
        ensure_dirs()

        if GRAPH_FILE.exists():
            graph = TasteGraph.load(GRAPH_FILE)
        else:
            graph = TasteGraph(data_path=GRAPH_FILE)
            loader = SeedLoader(graph, BASE_DIR)
            loader.load_all()
            graph.save()

        return graph

    def reload_graph(self) -> TasteGraph:
        """Force reload graph from disk."""
        self._taste_graph = self._init_graph()
        return self._taste_graph

    def save_graph(self) -> None:
        if self._taste_graph:
            self._taste_graph.save()


# ── Singleton ────────────────────────────────────────────────

_container: Optional[Container] = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = Container()
    return _container
