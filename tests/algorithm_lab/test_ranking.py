"""Behavior tests for the offline ranking experiment.

All candidates are synthetic local data. These tests avoid asserting a
invented weighting formula; they assert observable contract behavior.
"""

import pytest

from experiments.algorithm_lab.ranking import rank_pack


def candidate(
    cid,
    subject="s1",
    role="detail",
    match=0.8,
    trust=0.7,
    age=0.9,
    pref=0.0,
    actor="operator",
    eligible=True,
):
    return {
        "id": cid,
        "subject_key": subject,
        "role": role,
        "match_score": match,
        "source_trust": trust,
        "age_confidence": age,
        "human_preference": pref,
        "preference_actor": actor,
        "eligible": eligible,
    }


def test_empty_candidates_returns_empty_pack():
    result = rank_pack([])
    assert result["selected_ids"] == []
    assert result["explanations"] == {}


def test_size_larger_than_available_returns_all_eligible_candidates():
    data = [candidate("a"), candidate("b", subject="s1")]
    result = rank_pack(data, size=8)
    assert set(result["selected_ids"]) == {"a", "b"}
    assert set(result["explanations"]) == {"a", "b"}


def test_excludes_ineligible_candidates_even_when_otherwise_strong():
    data = [
        candidate("bad", match=1.0, trust=1.0, age=1.0, eligible=False),
        candidate("ok", match=0.1),
    ]
    result = rank_pack(data, size=4)
    assert result["selected_ids"] == ["ok"]


def test_excluded_ids_are_never_selected():
    data = [candidate("a", match=0.95), candidate("b", match=0.9)]
    result = rank_pack(data, size=4, excluded_ids={"a"})
    assert "a" not in result["selected_ids"]
    assert result["selected_ids"] == ["b"]


def test_operator_negative_preference_is_hard_exclusion():
    data = [
        candidate("disliked", match=1.0, pref=-1.0, actor="operator"),
        candidate("plain", match=0.2),
    ]
    result = rank_pack(data, size=4)
    assert result["selected_ids"] == ["plain"]


def test_assistant_negative_feedback_does_not_create_human_preference():
    data = [
        candidate("machine-negative", match=0.99, pref=-1.0, actor="assistant"),
        candidate("weaker", match=0.2),
    ]
    result = rank_pack(data, size=4)
    # Strong coherent match should not be banned by a non-operator signal.
    assert result["selected_ids"][0] == "machine-negative"


def test_pending_negative_feedback_does_not_create_human_preference():
    data = [
        candidate("pending-negative", match=0.99, pref=-1.0, actor="pending"),
        candidate("weaker", match=0.2),
    ]
    result = rank_pack(data, size=4)
    assert "pending-negative" in result["selected_ids"]
    assert result["selected_ids"][0] == "pending-negative"


def test_assistant_positive_feedback_is_not_counted_as_operator_preference():
    data = [
        candidate("machine-loved", match=0.3, pref=1.0, actor="assistant"),
        candidate("better-match", match=0.9, pref=0.0, actor="operator"),
    ]
    result = rank_pack(data, size=1)
    assert result["selected_ids"] == ["better-match"]


def test_selected_pack_keeps_one_subject_key_coherent():
    data = [
        candidate("red-1", subject="red-shoe", role="front", match=0.90),
        candidate("red-2", subject="red-shoe", role="side", match=0.88),
        candidate("blue-1", subject="blue-hat", role="front", match=0.89),
        candidate("blue-2", subject="blue-hat", role="side", match=0.87),
    ]
    result = rank_pack(data, size=2)
    selected = result["selected_ids"]
    subjects = {item["subject_key"] for item in data if item["id"] in selected}
    assert len(subjects) == 1


def test_does_not_cross_subjects_just_to_balance_roles():
    data = [
        candidate("same-front", subject="chair", role="front", match=0.93),
        candidate("same-side", subject="chair", role="side", match=0.92),
        candidate("other-back", subject="lamp", role="back", match=0.91),
    ]
    result = rank_pack(data, size=2)
    assert set(result["selected_ids"]).issubset({"same-front", "same-side"})


def test_same_role_allowed_for_multiple_angles_when_coherent():
    data = [
        candidate("chair-detail-a", subject="chair", role="detail", match=0.95),
        candidate("chair-detail-b", subject="chair", role="detail", match=0.94),
        candidate("chair-wide", subject="chair", role="wide", match=0.50),
    ]
    result = rank_pack(data, size=2)
    assert set(result["selected_ids"]) == {"chair-detail-a", "chair-detail-b"}


def test_comparable_match_quality_prefers_role_diversity():
    data = [
        candidate("front-1", subject="bag", role="front", match=0.800),
        candidate("front-2", subject="bag", role="front", match=0.799),
        candidate("side-1", subject="bag", role="side", match=0.798),
    ]
    result = rank_pack(data, size=2)
    selected_roles = {item["role"] for item in data if item["id"] in result["selected_ids"]}
    assert selected_roles == {"front", "side"}


def test_equal_scores_are_deterministic_across_calls():
    data = [
        candidate("z", subject="mug", role="front", match=0.7),
        candidate("a", subject="mug", role="side", match=0.7),
        candidate("m", subject="mug", role="back", match=0.7),
    ]
    first = rank_pack(data, size=2)
    second = rank_pack(list(reversed(data)), size=2)
    assert first["selected_ids"] == second["selected_ids"]
    assert len(first["selected_ids"]) == 2


def test_result_is_deterministic_for_identical_inputs():
    data = [candidate("a", match=0.5), candidate("b", match=0.6)]
    assert rank_pack(data, size=1) == rank_pack([dict(x) for x in data], size=1)


def test_missing_optional_metrics_are_ignored_without_failure():
    minimal = {
        "id": "minimal",
        "subject_key": "vase",
        "role": "front",
        "eligible": True,
    }
    complete = candidate("complete", subject="vase", role="side")
    result = rank_pack([minimal, complete], size=2)
    assert set(result["selected_ids"]) == {"minimal", "complete"}
    for selected_id, explanation in result["explanations"].items():
        assert isinstance(explanation, str)
        assert selected_id in explanation or "vase" in explanation


def test_every_selected_id_has_an_explanation_and_no_phantom_explanation():
    data = [candidate("a"), candidate("b"), candidate("c", eligible=False)]
    result = rank_pack(data, size=2)
    assert set(result["explanations"]) == set(result["selected_ids"])
    for text in result["explanations"].values():
        assert isinstance(text, str)
        assert text.strip()


def test_input_collection_and_candidate_dicts_are_not_mutated():
    data = [candidate("a"), candidate("b")]
    snapshots = [dict(item) for item in data]
    rank_pack(data, size=1, excluded_ids={"b"})
    assert data == snapshots


def test_size_zero_returns_empty_selection():
    result = rank_pack([candidate("a"), candidate("b")], size=0)
    assert result["selected_ids"] == []
    assert result["explanations"] == {}


def test_excluded_ids_accepts_list_tuple_set_and_iterable():
    data = [candidate("a"), candidate("b"), candidate("c")]
    for excluded in (["a"], ("a",), {"a"}, iter(["a"])):
        result = rank_pack(data, size=3, excluded_ids=excluded)
        assert "a" not in result["selected_ids"]
        assert set(result["selected_ids"]) == {"b", "c"}


def test_source_and_date_do_not_override_subject_coherence():
    data = [
        candidate("weak-trusted", subject="desk", role="front", match=0.60, trust=1.0, age=1.0),
        candidate("desk-side", subject="desk", role="side", match=0.59, trust=0.2, age=0.2),
        candidate("other-strong", subject="sofa", role="back", match=0.95, trust=1.0, age=1.0),
    ]
    result = rank_pack(data, size=2)
    subjects = {item["subject_key"] for item in data if item["id"] in result["selected_ids"]}
    assert subjects == {"desk"}


def test_non_operator_signal_cannot_explain_human_preference():
    data = [candidate("x", pref=-1.0, actor="assistant")]
    result = rank_pack(data, size=1)
    explanation = result["explanations"]["x"].lower()
    assert "human negative" not in explanation
    assert "operator negative" not in explanation
