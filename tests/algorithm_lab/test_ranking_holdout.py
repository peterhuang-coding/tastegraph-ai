import copy
import random

import pytest

from experiments.algorithm_lab.ranking import rank_pack


def make(cid, subject="s1", role="r1", eligible=True, **extra):
    item = {"id": cid, "subject_key": subject, "role": role, "eligible": eligible}
    item.update(extra)
    return item


def valid_result(result, size):
    assert isinstance(result, dict)
    ids = result["selected_ids"]
    explanations = result["explanations"]
    assert isinstance(ids, list)
    assert isinstance(explanations, dict)
    assert len(ids) == len(set(ids))
    assert len(ids) <= size
    assert set(explanations) == set(ids)
    assert all(isinstance(x, str) and x for x in ids)
    assert all(isinstance(v, str) and v for v in explanations.values())
    return ids


def test_size_zero_is_empty():
    assert rank_pack([], size=0) == {"selected_ids": [], "explanations": {}}


@pytest.mark.parametrize("bad_size", [-1, 1.0, True, False, None, "2"])
def test_bad_size(bad_size):
    with pytest.raises(ValueError):
        rank_pack([make("a")], size=bad_size)


@pytest.mark.parametrize("bad_excluded", [1, 1.2, object(), [["x"]], [{"x"}]])
def test_bad_excluded_iterable_or_members(bad_excluded):
    with pytest.raises(ValueError):
        rank_pack([make("a")], excluded_ids=bad_excluded)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"id": "a"},
        {"id": "a", "subject_key": "s"},
        {"id": "", "subject_key": "s", "role": "r"},
        {"id": " ", "subject_key": "s", "role": "r"},
        {"id": "a", "subject_key": "", "role": "r"},
        {"id": "a", "subject_key": "s", "role": ""},
        {"id": 1, "subject_key": "s", "role": "r"},
        {"id": "a", "subject_key": 2, "role": "r"},
        {"id": "a", "subject_key": "s", "role": 3},
    ],
)
def test_invalid_identity(bad):
    with pytest.raises(ValueError):
        rank_pack([bad], size=1)


def test_duplicate_ids_rejected_even_when_excluded():
    with pytest.raises(ValueError):
        rank_pack([make("dup"), make("dup")], excluded_ids=["dup"])


def test_excluded_iterables_accepted_and_inputs_not_mutated():
    candidates = [
        make("a", role="cover", match_score=0.9, source_trust=0.5),
        make("b", role="inside", match_score=0.8),
    ]
    snapshot = copy.deepcopy(candidates)
    first = rank_pack(candidates, size=2, excluded_ids=("a",))
    for excluded in (["a"], {"a"}, frozenset(["a"]), iter(["a"])):
        assert rank_pack(candidates, size=2, excluded_ids=excluded) == first
    assert candidates == snapshot
    assert valid_result(first, 2) == ["b"]


def test_inputs_are_not_mutated_and_order_invariant_200():
    rng = random.Random(200)
    nan = float("nan")
    inf = float("inf")
    base = [
        make("a", role="cover", match_score=0.9, source_trust=0.5, age_confidence=0.2),
        make("b", role="inside", match_score=0.8),
        make("c", subject="s2", role="cover", match_score=0.95),
        make("d", role="detail", match_score=nan),
        make("e", role="other", eligible=False, weird=inf),
    ]
    snapshot = copy.deepcopy(base)
    first = rank_pack(base, size=2, excluded_ids=["c"])
    for _ in range(200):
        shuffled = base[:]
        rng.shuffle(shuffled)
        assert rank_pack(shuffled, size=2, excluded_ids=["c"]) == first
    assert copy.deepcopy(base) == snapshot
    assert base[3]["match_score"] is nan
    assert base[4]["weird"] is inf


def test_excluded_and_ineligible_never_selected_and_enlargement_200():
    rng = random.Random(2001)
    roles = ["cover", "inside", "detail", "wide", "back"]
    for _ in range(200):
        candidates = []
        for subject in ("alpha", "beta", "gamma"):
            for i, role in enumerate(roles):
                candidates.append(
                    make(
                        f"{subject}-{i}",
                        subject=subject,
                        role=role,
                        match_score=rng.random(),
                        source_trust=rng.choice([None, rng.random(), float("inf")]),
                        age_confidence=rng.choice([None, rng.random(), float("-inf")]),
                        eligible=rng.random() > 0.12,
                    )
                )
        rng.shuffle(candidates)
        excluded = [c["id"] for c in candidates if rng.random() < 0.25]
        ineligible = {c["id"] for c in candidates if c.get("eligible") is not True}
        forbidden = set(excluded) | ineligible
        ids = valid_result(rank_pack(candidates, size=3, excluded_ids=excluded), 3)
        assert not (set(ids) & forbidden)

        additions = [
            c["id"]
            for c in candidates
            if c["id"] not in excluded and rng.random() < 0.2
        ]
        more_excluded = excluded + additions
        ids2 = valid_result(
            rank_pack(candidates, size=3, excluded_ids=more_excluded), 3
        )
        newly_forbidden = set(more_excluded) | ineligible
        assert not (set(ids2) & newly_forbidden)
        # Previously chosen items that become excluded may disappear, but must
        # never be reintroduced by the enlarged exclusion set.
        assert not (set(ids2) & set(additions))


def test_missing_optional_fields_and_non_finite_values_are_supported():
    candidates = [
        make("a", match_score=None, source_trust=None, age_confidence=None),
        make("b", match_score=float("nan"), source_trust="x", age_confidence={}),
        make("c", match_score=float("inf"), source_trust=[], age_confidence=True),
        make("d", match_score=-2.0, source_trust=3.0, age_confidence=float("-inf")),
        make("e", match_score=2.0),
    ]
    ids = valid_result(rank_pack(candidates, size=5), 5)
    assert set(ids) == {"a", "b", "c", "d", "e"}


def test_operator_negative_does_not_bleed_to_identical_assistant_candidate():
    candidates = [
        make(
            "operator-best",
            role="cover",
            match_score=1.0,
            preference_actor="operator",
            human_preference=-1,
        ),
        make(
            "assistant-best",
            role="cover",
            match_score=1.0,
            preference_actor="assistant",
            human_preference=-1,
        ),
        make("neutral", role="inside", match_score=1.0),
    ]
    ids = rank_pack(candidates, size=2)["selected_ids"]
    assert "operator-best" not in ids
    assert "assistant-best" in ids


def test_selection_remains_within_one_subject_even_for_role_diversity():
    candidates = [
        make("a-cover", "alpha", "cover", match_score=0.70),
        make("a-inside", "alpha", "inside", match_score=0.69),
        make("b-cover", "beta", "cover", match_score=0.95),
        make("b-detail", "beta", "detail", match_score=0.50),
        make("g-other", "gamma", "other", match_score=0.99),
    ]
    ids = rank_pack(candidates, size=2)["selected_ids"]
    subjects = {cid.split("-", 1)[0] for cid in ids}
    assert len(ids) == 2
    assert len(subjects) == 1


def test_missing_eligible_field_is_excluded_but_not_invalid():
    item = {"id": "a", "subject_key": "s", "role": "r", "match_score": 1.0}
    assert rank_pack([item], size=1) == {"selected_ids": [], "explanations": {}}


def test_role_diversity_tie_does_not_cross_subject():
    candidates = [
        make("same-1", "same", "cover", match_score=0.80),
        make("same-2", "same", "cover", match_score=0.795),
        make("other-role", "other", "inside", match_score=0.79),
    ]
    ids = rank_pack(candidates, size=2)["selected_ids"]
    assert len(ids) == 2
    assert set(ids) <= {"same-1", "same-2"}
