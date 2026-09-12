"""Regression tests for consuming user preferences and proven source identity."""

from datetime import datetime, timedelta, timezone

import pytest

from taste_graph_ai.domain.enums import NodeType, RelationType
from taste_graph_ai.graph.taste_graph import TasteGraph


@pytest.fixture
def graph():
    graph = TasteGraph()
    graph.add_node("north_star", NodeType.CONCEPT)
    graph.add_node("minimal", NodeType.CONCEPT)
    graph.add_node("quiet", NodeType.MOOD)
    return graph


def prefer(graph, target, weight):
    graph.add_edge("concept:north_star", target, RelationType.PREFERS, weight)


def test_incoming_user_feedback_changes_score_in_both_directions(graph):
    prefer(graph, "concept:minimal", 3)
    before = graph.score_content(["minimal"])
    graph.adjust_weight("concept:north_star", "concept:minimal", 2)
    positive = graph.score_content(["minimal"])
    graph.adjust_weight("concept:north_star", "concept:minimal", -6)
    negative = graph.score_content(["minimal"])
    assert (before, positive, negative) == (3, 5, -1)


def test_avoided_concept_contributes_signed_negative_weight(graph):
    graph.add_edge("concept:north_star", "concept:minimal", RelationType.AVOIDS, -6)
    assert graph.score_content(["minimal"]) == -6


def test_unrelated_edges_do_not_change_user_preference_score(graph):
    prefer(graph, "concept:minimal", 3)
    before = graph.score_content(["minimal"])
    graph.add_edge("concept:minimal", "mood:quiet", RelationType.PREFERS, 99)
    graph.add_edge("mood:quiet", "concept:minimal", RelationType.PREFERS, 99)
    assert graph.score_content(["minimal"]) == before


def test_repeated_or_overlapping_keywords_count_each_matched_node_once(graph):
    prefer(graph, "concept:minimal", 3)
    prefer(graph, "mood:quiet", 1)
    assert graph.score_content(["minimal", "quiet"]) == 2
    assert graph.score_content(["minimal", " MINIMAL ", "minimal look", "quiet"]) == 2


@pytest.mark.parametrize("aware", [True, False])
def test_old_preference_edges_decay_for_both_timestamp_formats(graph, aware):
    prefer(graph, "concept:minimal", 8)
    old = datetime.now(timezone.utc) - timedelta(days=180, seconds=1)
    if not aware:
        old = old.replace(tzinfo=None)
    graph.graph.edges["concept:north_star", "concept:minimal"]["last_updated"] = old.isoformat()
    assert graph.score_content(["minimal"]) == 2


def test_source_id_alias_uses_existing_node_metadata(graph):
    node = graph.add_node("Editorial", NodeType.SOURCE, source_id="db-hash")
    prefer(graph, node, 3)
    assert graph.score_content(["minimal"], source_id="db-hash") == 4


def test_source_url_resolves_database_hash_to_existing_source(graph):
    node = graph.add_node("Editorial", NodeType.SOURCE, url="https://www.example.com/editorial/")
    prefer(graph, node, 3)
    before = graph.to_dict()
    assert graph.score_content(
        ["minimal"], source_id="db-hash", source_url="https://example.com/editorial/story"
    ) == 4
    assert graph.to_dict() == before


@pytest.mark.parametrize("url", [
    "https://example.com/editorial/story",
    "https://example.com/editorial?utm_source=feed",
])
def test_source_url_uses_most_specific_path_on_shared_domain(graph, url):
    root = graph.add_node("Publisher", NodeType.SOURCE, url="https://example.com")
    editorial = graph.add_node("Editorial", NodeType.SOURCE, url="https://example.com/editorial")
    fashion = graph.add_node("Fashion", NodeType.SOURCE, url="https://example.com/fashion")
    prefer(graph, root, 1)
    prefer(graph, editorial, 3)
    prefer(graph, fashion, 8)
    assert graph.score_content(["minimal"], source_url=url) == 4


def test_ambiguous_shared_domain_does_not_borrow_a_source_bonus(graph):
    for path in ("editorial", "fashion"):
        node = graph.add_node(path, NodeType.SOURCE, url=f"https://example.com/{path}")
        prefer(graph, node, 3)
    assert graph.score_content(["minimal"], source_url="https://example.com/unknown") == 1


def test_url_matching_respects_host_and_path_boundaries(graph):
    editorial = graph.add_node("Editorial", NodeType.SOURCE, url="https://example.com/editorial")
    fashion = graph.add_node("Fashion", NodeType.SOURCE, url="https://example.com/fashion")
    prefer(graph, editorial, 3)
    prefer(graph, fashion, 8)
    assert graph.score_content(["minimal"], source_url="https://example.com.evil.test/editorial") == 1
    assert graph.score_content(["minimal"], source_url="https://example.com/editorialist") == 1


def test_unique_domain_metadata_resolves_existing_source(graph):
    node = graph.add_node("Publisher", NodeType.SOURCE, domain="example.com")
    prefer(graph, node, 3)
    assert graph.score_content(["minimal"], source_url="https://www.example.com/story") == 4


def test_negative_source_preference_is_not_replaced_by_exploration_boost(graph):
    node = graph.add_node("Avoided", NodeType.SOURCE)
    graph.add_edge("concept:north_star", node, RelationType.AVOIDS, -3)
    assert graph.score_content(["minimal"], source_id=node) == -2


def test_existing_unrated_source_gets_exploration_but_unknown_source_does_not(graph):
    node = graph.add_node("New", NodeType.SOURCE)
    assert graph.score_content(["minimal"], source_id=node) == 1.3
    assert graph.score_content(["minimal"], source_id="missing") == 1
    assert graph.score_content(["minimal"], source_id="concept:minimal") == 1


def test_source_only_content_still_uses_known_source_preference(graph):
    node = graph.add_node("Editorial", NodeType.SOURCE)
    prefer(graph, node, 3)
    assert graph.score_content([], source_id=node) == 3


def test_visual_tags_match_without_duplicate_keyword_contributions(graph):
    prefer(graph, "concept:minimal", 3)
    prefer(graph, "mood:quiet", 1)
    assert graph.score_content([], visual_tags=["minimal"]) == 3
    assert graph.score_content(["minimal"], visual_tags=["minimal", "quiet"]) == 2


def test_blank_keywords_and_north_star_do_not_match_arbitrary_preferences(graph):
    prefer(graph, "concept:minimal", 3)
    assert graph.score_content(["", " ", "north_star"]) == 0


def test_duplicate_source_urls_do_not_pick_an_arbitrary_source(graph):
    for name, weight in (("First", 3), ("Second", -3)):
        node = graph.add_node(name, NodeType.SOURCE, url="https://example.com/editorial")
        prefer(graph, node, weight)
    assert graph.score_content(["minimal"], source_url="https://example.com/editorial") == 1


@pytest.mark.parametrize("source_id", ["source:032c", "legacy_wrong"])
def test_source_url_scope_overrides_conflicting_source_id_or_alias(graph, source_id):
    wrong = graph.add_node("032c", NodeType.SOURCE, url="https://vogue.com/brands/032c", source_id="legacy_wrong")
    correct = graph.add_node("Dior", NodeType.SOURCE, url="https://vogue.com/brands/dior")
    prefer(graph, wrong, 8)
    prefer(graph, correct, 3)
    assert graph.score_content(["minimal"], source_id=source_id,
                               source_url="https://vogue.com/brands/dior") == 4


def test_source_id_does_not_borrow_bonus_for_a_conflicting_unrecognized_domain(graph):
    source = graph.add_node("Editorial", NodeType.SOURCE, url="https://example.com/editorial")
    prefer(graph, source, 3)
    assert graph.score_content(["minimal"], source_id=source,
                               source_url="https://another-site.test/project/chair") == 1
    assert graph.score_content(["minimal"], source_id=source) == 4
