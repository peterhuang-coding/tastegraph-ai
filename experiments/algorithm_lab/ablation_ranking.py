"""Seeded offline ablation for experiments.algorithm_lab.ranking.rank_pack.

Run with:
    python -m experiments.algorithm_lab.ablation_ranking

This module is intentionally non-production and synthetic-only. It imports the
existing rank_pack implementation and benchmark_ranking fixture/evaluate
helpers, then temporarily monkeypatches ranking-module functions in this
process. No source files or production state are modified.
"""

import json
import random
import statistics
import time

import experiments.algorithm_lab.ranking as ranking
from experiments.algorithm_lab.benchmark_ranking import (
    ROLES,
    evaluate,
    fixture,
    rejected_by_filters,
)

TRIAL_SEED = 20260214
PERF_SEED = 99173
TRIAL_COUNT = 200
PERF_CANDIDATES = 1000
PERF_REPEATS = 5
PACK_SIZE = 8
EXCLUDED_PER_TRIAL = 5

METHODS = ("current_prototype", "match_only_quality", "no_diversity_select")


def match_only_quality(candidate):
    match = ranking._clip01(candidate.get("match_score"))
    match = 0.0 if match is None else match
    return match, match


def no_diversity_select(ordered, size):
    if size <= 0 or not ordered:
        return []
    return list(ordered[: min(size, len(ordered))])


def make_trials():
    """Freeze trial inputs and exclusion sets once; reuse them for each method."""
    rng = random.Random(TRIAL_SEED)
    trials = []
    total_candidates = 0
    group_values, role_values, size_values = set(), set(), set()

    for trial_index in range(TRIAL_COUNT):
        groups = (trial_index % 4) + 1
        roles = (trial_index % 4) + 2
        size = min(PACK_SIZE, roles + 1)
        candidates = fixture(rng, groups, roles, size)
        excluded = frozenset(c["id"] for c in rng.sample(candidates, EXCLUDED_PER_TRIAL))

        total_candidates += len(candidates)
        group_values.add(groups)
        role_values.add(roles)
        size_values.add(size)
        trials.append(
            {
                "trial": trial_index + 1,
                "groups": groups,
                "roles_per_subject": roles,
                "pack_size": size,
                "candidates": candidates,
                "excluded_ids": excluded,
            }
        )

    return trials, {
        "trial_count": TRIAL_COUNT,
        "total_candidate_records": total_candidates,
        "candidate_count_min": min(len(t["candidates"]) for t in trials),
        "candidate_count_max": max(len(t["candidates"]) for t in trials),
        "excluded_ids_per_trial": EXCLUDED_PER_TRIAL,
        "fixture_group_counts": sorted(group_values),
        "fixture_roles_per_subject": sorted(role_values),
        "pack_sizes": sorted(size_values),
    }


def run_with_patch(method, function):
    if method == "current_prototype":
        return function()

    if method == "match_only_quality":
        original = ranking._quality
        ranking._quality = match_only_quality
        try:
            return function()
        finally:
            ranking._quality = original

    if method == "no_diversity_select":
        original = ranking._select_in_group
        ranking._select_in_group = no_diversity_select
        try:
            return function()
        finally:
            ranking._select_in_group = original

    raise AssertionError("unknown method: " + method)


def proper_rejection_counts(selected, excluded):
    ineligible = 0
    excluded_selected = 0
    operator_negative = 0

    for candidate in selected:
        if candidate.get("eligible") is not True:
            ineligible += 1
        if candidate.get("id") in excluded:
            excluded_selected += 1
        if (
            candidate.get("preference_actor") == "operator"
            and isinstance(candidate.get("human_preference"), (int, float))
            and not isinstance(candidate.get("human_preference"), bool)
            and float(candidate["human_preference"]) < 0.0
        ):
            operator_negative += 1

    return ineligible, excluded_selected, operator_negative


def chosen_ideal_top_match_gap(candidates, selected_ids, excluded):
    """Mean-match gap against ideal top-N restricted to the selected subject."""
    by_id = {c["id"]: c for c in candidates}
    selected = [by_id[i] for i in selected_ids if i in by_id]
    if not selected:
        return None

    subject = selected[0]["subject_key"]
    size = len(selected)
    same_subject = [
        c
        for c in candidates
        if c.get("subject_key") == subject and not rejected_by_filters(c, excluded)
    ]
    ideal = sorted(
        same_subject,
        key=lambda c: (float(c.get("match_score", 0.0)), str(c.get("id"))),
        reverse=True,
    )[:size]
    selected_mean = statistics.mean(float(c.get("match_score", 0.0)) for c in selected)
    ideal_mean = statistics.mean(float(c.get("match_score", 0.0)) for c in ideal)
    return max(0.0, ideal_mean - selected_mean)


def evaluate_method(method, trials):
    rows = []

    for trial in trials:
        candidates = trial["candidates"]
        excluded = trial["excluded_ids"]
        size = trial["pack_size"]

        def invoke():
            first = ranking.rank_pack(candidates, size=size, excluded_ids=excluded)
            shuffled = list(candidates)
            random.Random(TRIAL_SEED + trial["trial"]).shuffle(shuffled)
            second = ranking.rank_pack(shuffled, size=size, excluded_ids=excluded)
            return first["selected_ids"], second["selected_ids"]

        selected_ids, shuffled_ids = run_with_patch(method, invoke)
        metrics = evaluate(candidates, selected_ids, size, excluded)

        by_id = {c["id"]: c for c in candidates}
        selected = [by_id[i] for i in selected_ids if i in by_id]
        ineligible, excluded_selected, operator_negative = proper_rejection_counts(
            selected, excluded
        )
        subjects = {c.get("subject_key") for c in selected}

        rows.append(
            {
                "trial": trial["trial"],
                "groups": trial["groups"],
                "roles_per_subject": trial["roles_per_subject"],
                "pack_size": size,
                "candidate_count": len(candidates),
                "excluded_ids_in_fixture": len(excluded),
                "selected_count": len(selected_ids),
                "coherent_one_subject": True if not selected else len(subjects) <= 1,
                "single_selected_subject": len(subjects) == 1,
                "ineligible_selected_proper": ineligible,
                "excluded_id_selected_proper": excluded_selected,
                "operator_negative_selected_proper": operator_negative,
                "benchmark_operator_negative_mixed_with_ineligible": metrics[
                    "operator_negative_selected"
                ],
                "unknown_output_ids": metrics["unknown_output_ids"],
                "duplicate_output_ids": metrics["duplicate_output_ids"],
                "permutation_stable": selected_ids == shuffled_ids,
                "role_coverage": metrics["role_coverage"],
                "mean_match_score": metrics["mean_match_score"],
                "chosen_subject_ideal_top_match_gap": chosen_ideal_top_match_gap(
                    candidates, selected_ids, excluded
                ),
            }
        )

    return rows


def summarize(rows):
    boolean_rate_keys = (
        "coherent_one_subject",
        "single_selected_subject",
        "permutation_stable",
    )
    count_keys = (
        "selected_count",
        "ineligible_selected_proper",
        "excluded_id_selected_proper",
        "operator_negative_selected_proper",
        "unknown_output_ids",
        "duplicate_output_ids",
    )
    mean_keys = ("role_coverage", "mean_match_score", "chosen_subject_ideal_top_match_gap")

    out = {"trials": len(rows)}

    for key in boolean_rate_keys:
        out[key + "_rate"] = statistics.mean(1.0 if row[key] else 0.0 for row in rows)

    for key in count_keys:
        out[key + "_mean"] = statistics.mean(row[key] for row in rows)
        out[key + "_total"] = sum(row[key] for row in rows)

    for key in mean_keys:
        values = [row[key] for row in rows if row[key] is not None]
        out[key + "_mean"] = statistics.mean(values) if values else None

    return out


def timing_candidates():
    from experiments.algorithm_lab.benchmark_ranking import timing_fixture

    rng = random.Random(PERF_SEED + PERF_CANDIDATES)
    return timing_fixture(rng, PERF_CANDIDATES)


def time_method(method, candidates):
    def invoke():
        timings = []
        for _ in range(PERF_REPEATS):
            start = time.perf_counter()
            ranking.rank_pack(candidates, size=PACK_SIZE)
            timings.append(time.perf_counter() - start)
        return timings

    timings = run_with_patch(method, invoke)
    return {
        "candidate_count": len(candidates),
        "pack_size": PACK_SIZE,
        "repeats": PERF_REPEATS,
        "median_seconds": statistics.median(timings),
    }


def main():
    trials, trial_input = make_trials()
    results = {}

    for method in METHODS:
        results[method] = summarize(evaluate_method(method, trials))

    perf_input = timing_candidates()
    timing = {method: time_method(method, perf_input) for method in METHODS}

    payload = {
        "context": {
            "module_invocation": "python -m experiments.algorithm_lab.ablation_ranking",
            "seeded_offline_stdout_json": True,
            "production_files_modified": False,
            "monkeypatch_scope": "temporary in-process replacement; each variant restores the prior function in try/finally",
            "trial_random_seed": TRIAL_SEED,
            "performance_random_seed": PERF_SEED + PERF_CANDIDATES,
            "frozen_inputs_reused_across_methods": True,
            "same_excluded_sets_reused_across_methods": True,
            "trial_inputs": trial_input,
            "performance_input": {
                "candidate_count": len(perf_input),
                "pack_size": PACK_SIZE,
                "repeats_per_variant": PERF_REPEATS,
                "timer": "time.perf_counter",
            },
            "available_role_count": len(ROLES),
            "roles": list(ROLES),
            "methods": {
                "current_prototype": "imported rank_pack with existing quality and role-diversity selection",
                "match_only_quality": "temporarily replaces ranking._quality with (match_score, match_score)",
                "no_diversity_select": "temporarily replaces ranking._select_in_group with the first N candidates from the existing quality-ordered pool",
            },
            "gold_policy_note": (
                "Ideal match gap is computed within the chosen subject only. "
                "Naive global cross-subject top-match is explicitly not treated as gold."
            ),
            "filter_metric_note": (
                "Benchmark evaluate() labels some ineligible records under "
                "operator_negative_selected; this ablation reports separately recalculated "
                "ineligible, excluded-ID, and operator-negative totals, retaining the mixed "
                "benchmark field for audit only."
            ),
            "limitations": [
                "non-production experimental harness",
                "synthetic randomized fixtures only; no real candidates, users, labels, or traffic",
                "200 fixed offline trials with synthetic role/subject distributions",
                "timing is process- and machine-dependent and is not a load/scale test",
                "no causal business, relevance, or user-satisfaction effect is claimed",
            ],
        },
        "observed_metrics": results,
        "performance_5_repeat_median_for_1000_candidates": timing,
    }

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
