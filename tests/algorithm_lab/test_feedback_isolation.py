import copy

import pytest

from experiments.algorithm_lab.ranking import rank_pack


def _candidate(cid=None, subject="s1", role="r1", **extra):
    data = {
        "id": cid,
        "subject_key": subject,
        "role": role,
        "eligible": True,
        "match_score": 0.8,
        "source_trust": 0.5,
        "age_confidence": 0.5,
    }
    data.update(extra)
    return data


def _pair(change):
    control = _candidate("x")
    treated = _candidate("x")
    treated["machine_suggestions"] = [
        {
            "suggested_id": "machine-1",
            "score": 0.99,
            "reason": "synthetic nested signal",
        }
    ]
    treated["publication"] = {
        "status": "published",
        "events": [{"type": "published", "at": "2099-01-01T00:00:00Z"}],
        "snapshot_id": "synthetic-snapshot",
    }
    treated["observations"] = [
        {
            "field": "observed_age_days",
            "value": 3650,
            "source": "synthetic-test-observer",
        },
        {
            "field": "review_count",
            "value": 12,
            "source": "synthetic-test-observer",
        },
    ]
    treated.update(change)
    return control, treated


@pytest.mark.parametrize(
    "change",
    [
        {"stats": None},
        {"stats": 0},
        {"stats": {"score": None}},
        {"stats": {"score": 0}},
        {"under_review": 0},
        {"under_review": "unknown"},
        {"under_review": True, "stats": {"score": 0, "views": 0, "reviews": 0}},
        {
            "under_review": "under_review",
            "stats": {"score": 0.0, "views": 0, "reviews": 0, "delta": 0.0},
        },
        {
            "publication": {
                "status": "published",
                "events": [],
                "snapshot_id": "a",
            }
        },
        {
            "publication": {
                "status": "draft",
                "events": [{"type": "published"}],
                "snapshot_id": "b",
            }
        },
        {"observations": None},
        {"observations": []},
        {"observations": [{"field": "observed_age_days", "value": 1}]},
        {"observations": [{"field": "observed_age_days", "value": 999999}]},
        {
            "observations": [
                {
                    "field": "views",
                    "value": None,
                    "observed_at": "2024-01-01T00:00:00Z",
                },
                {
                    "field": "views",
                    "value": 0,
                    "observed_at": "2024-01-02T00:00:00Z",
                },
            ]
        },
        {
            "observations": [
                {
                    "field": "review_count",
                    "value": 0,
                    "observed_at": "2024-02-01T10:00:00Z",
                },
                {
                    "field": "review_count",
                    "value": 3,
                    "observed_at": "2024-02-08T10:00:00Z",
                },
            ]
        },
        {"machine_suggestions": []},
        {"machine_suggestions": [{"suggested_id": "m", "score": 1.0}]},
        {
            "machine_suggestions": [{"suggested_id": "m", "score": 1.0}],
            "publication": {
                "events": [{"type": "published"}],
                "snapshots": [{"score": 1.0}, {"score": 2.0}],
            },
            "observations": [{"field": "observed_age_days", "value": 42}],
        },
        {"human_preference": 0, "preference_actor": "assistant"},
        {"human_preference": -1, "preference_actor": "assistant"},
        {"human_preference": -1, "preference_actor": "pending"},
        {"human_preference": 1, "preference_actor": "operator"},
    ],
)
def test_synthetic_nested_fields_and_non_operator_feedback_do_not_change_ranking(change):
    control, treated = _pair(change)
    control_snapshot = copy.deepcopy(control)
    treated_snapshot = copy.deepcopy(treated)

    assert rank_pack([treated], size=1) == rank_pack([control], size=1)
    assert control == control_snapshot
    assert treated == treated_snapshot


@pytest.mark.parametrize(
    "left_change,right_change,expected",
    [
        (
            {"id": "a", "match_score": 0.5},
            {"id": "b", "match_score": 0.9},
            ["b"],
        ),
        (
            {
                "id": "a",
                "match_score": 0.7,
                "observations": [
                    {"field": "observed_age_days", "value": 1}
                ],
            },
            {
                "id": "b",
                "match_score": 0.7,
                "observations": [
                    {"field": "observed_age_days", "value": 999}
                ],
            },
            ["b"],
        ),
        (
            {
                "id": "a",
                "match_score": 0.7,
                "publication": {"events": [{"type": "published"}]},
            },
            {
                "id": "b",
                "match_score": 0.7,
                "publication": {"events": []},
            },
            ["b"],
        ),
        (
            {
                "id": "a",
                "role": "r1",
                "match_score": 0.7,
                "observations": [
                    {
                        "field": "views",
                        "value": 10,
                        "observed_at": "2024-03-01T00:00:00Z",
                    }
                ],
            },
            {
                "id": "b",
                "role": "r1",
                "match_score": 0.7,
                "observations": [
                    {
                        "field": "views",
                        "value": 999,
                        "observed_at": "2024-03-02T00:00:00Z",
                    }
                ],
            },
            ["b"],
        ),
    ],
)
def test_quality_controls_order_while_synthetic_fields_are_metadata(
    left_change, right_change, expected
):
    left = _candidate(**left_change)
    right = _candidate(**right_change)
    inputs = [left, right]
    before = copy.deepcopy(inputs)

    assert rank_pack(inputs, size=1)["selected_ids"] == expected
    assert inputs == before




def test_operator_negative_feedback_excludes_but_assistant_and_pending_negative_remain():
    operator_no = _candidate(
        "operator-no",
        role="r1",
        human_preference=-1,
        preference_actor="operator",
    )
    assistant = _candidate(
        "assistant-ok",
        role="r2",
        human_preference=-1,
        preference_actor="assistant",
    )
    pending = _candidate(
        "pending-ok",
        role="r3",
        human_preference=-1,
        preference_actor="pending",
    )
    inputs = [operator_no, assistant, pending]
    before = copy.deepcopy(inputs)

    result = rank_pack(inputs, size=3)

    assert result["selected_ids"] == ["pending-ok", "assistant-ok"]
    assert "operator-no" not in result["selected_ids"]
    assert "operator-no" not in result["explanations"]
    assert inputs == before


def test_excluded_ids_use_set_membership_and_do_not_mutate_inputs():
    first = _candidate("candidate-1", role="r1")
    second = _candidate("candidate-2", role="r2")
    inputs = [first, second]
    excluded = ["candidate-1"]
    before_inputs = copy.deepcopy(inputs)
    before_excluded = copy.deepcopy(excluded)

    result = rank_pack(inputs, size=2, excluded_ids=excluded)

    assert result["selected_ids"] == ["candidate-2"]
    assert "candidate-1" not in result["selected_ids"]
    assert "candidate-1" not in result["explanations"]
    assert inputs == before_inputs
    assert excluded == before_excluded


def test_ineligible_and_invalid_identity_are_handled_without_ranking_metadata_effects():
    valid = _candidate("valid", role="r1")
    ineligible = _candidate("ineligible", role="r2", eligible=False)
    inputs = [valid, ineligible]
    before = copy.deepcopy(inputs)

    result = rank_pack(inputs, size=2)

    assert result["selected_ids"] == ["valid"]
    assert "ineligible" not in result["selected_ids"]
    assert "ineligible" not in result["explanations"]
    assert inputs == before

    invalid = _candidate(" ", role="r3")
    with pytest.raises(ValueError):
        rank_pack([valid, invalid], size=2)


def test_zero_size_returns_empty_pack_without_mutating_inputs():
    candidate = _candidate(
        "x",
        under_review="under_review",
        stats={"score": 0, "views": 0, "reviews": 0},
        observations=[
            {
                "field": "views",
                "value": 0,
                "observed_at": "2024-04-01T00:00:00Z",
            }
        ],
    )
    inputs = [candidate]
    before = copy.deepcopy(inputs)

    assert rank_pack(inputs, size=0) == {"selected_ids": [], "explanations": {}}
    assert inputs == before


def test_complete_subject_group_is_preferred_over_incomplete_group():
    complete_a = _candidate("a-1", subject="complete", role="r1", match_score=0.5)
    complete_b = _candidate("a-2", subject="complete", role="r2", match_score=0.5)
    incomplete = _candidate("b-1", subject="incomplete", role="r1", match_score=1.0)
    inputs = [incomplete, complete_a, complete_b]
    before = copy.deepcopy(inputs)

    result = rank_pack(inputs, size=2)

    assert result["selected_ids"] == ["a-2", "a-1"]
    assert inputs == before


def test_role_diversity_only_applies_within_effective_match_tie():
    diverse_but_weaker = _candidate(
        "diverse-weaker",
        role="r2",
        match_score=0.70,
        source_trust=1.0,
        age_confidence=1.0,
    )
    stronger_same_role = _candidate(
        "same-strong",
        role="r1",
        match_score=0.75,
        source_trust=1.0,
        age_confidence=1.0,
    )
    first_same_role = _candidate(
        "same-first",
        role="r1",
        match_score=0.80,
        source_trust=1.0,
        age_confidence=1.0,
    )
    inputs = [diverse_but_weaker, stronger_same_role, first_same_role]
    before = copy.deepcopy(inputs)

    result = rank_pack(inputs, size=2)

    assert result["selected_ids"] == ["same-first", "same-strong"]
    assert inputs == before


def test_role_diversity_wins_when_match_is_effectively_tied():
    first = _candidate(
        "first-same-role",
        role="r1",
        match_score=0.80,
        source_trust=1.0,
        age_confidence=1.0,
    )
    same_role = _candidate(
        "second-same-role",
        role="r1",
        match_score=0.79,
        source_trust=1.0,
        age_confidence=1.0,
    )
    diverse_role = _candidate(
        "diverse-role",
        role="r2",
        match_score=0.79,
        source_trust=1.0,
        age_confidence=1.0,
    )
    inputs = [same_role, diverse_role, first]
    before = copy.deepcopy(inputs)

    result = rank_pack(inputs, size=2)

    assert result["selected_ids"] == ["first-same-role", "diverse-role"]
    assert inputs == before


def test_same_quality_ignores_machine_publication_observation_metadata_perturbation():
    variants = []
    for cid, observed_age, events, suggestions in [
        ("plain", None, [], []),
        ("observed", 111, [{"type": "viewed"}], [{"suggested_id": "m1", "score": 0.1}]),
        (
            "published",
            222,
            [{"type": "published"}],
            [{"suggested_id": "m2", "score": 0.9}],
        ),
    ]:
        variants.append(
            _candidate(
                cid,
                role="same-role",
                observations=[{"field": "observed_age_days", "value": observed_age}],
                publication={"events": events},
                machine_suggestions=suggestions,
            )
        )

    baseline = [copy.deepcopy(candidate) for candidate in variants]
    perturbed = copy.deepcopy(baseline)
    for candidate in perturbed:
        candidate["observations"] = [
            {
                "field": "views",
                "value": None,
                "observed_at": "2024-05-01T00:00:00Z",
            },
            {
                "field": "views",
                "value": 0,
                "observed_at": "2024-05-02T00:00:00Z",
            },
            {
                "field": "review_count",
                "value": 0,
                "observed_at": "2024-05-03T00:00:00Z",
            },
        ]
        candidate["publication"] = {
            "status": "under_review",
            "events": [],
            "metrics": {"views": 0, "reviews": 0, "score": 0.0},
            "snapshots": [
                {
                    "observed_at": "2024-05-01T00:00:00Z",
                    "counts": {"views": 0, "reviews": 0},
                },
                {
                    "observed_at": "2024-05-02T00:00:00Z",
                    "counts": {"views": 0, "reviews": 0},
                },
            ],
        }
        candidate["machine_suggestions"] = []
        candidate["under_review"] = True

    expected_before = copy.deepcopy(baseline)
    expected_perturbed = copy.deepcopy(perturbed)

    before_result = rank_pack(baseline, size=3)
    after_result = rank_pack(perturbed, size=3)

    assert after_result == before_result
    assert after_result["selected_ids"] == ["published", "plain", "observed"]
    assert baseline == expected_before
    assert perturbed == expected_perturbed