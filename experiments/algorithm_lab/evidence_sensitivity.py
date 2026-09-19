import itertools
import json

from experiments.algorithm_lab.ranking import rank_pack

GAPS = [0.0, 0.005, 0.01, 0.05, 0.10, 0.20]
FEATURE_VALUES = [None, 0.0, 0.5, 1.0]
SUBJECT = "same-subject"
ROLE = "same-role"


def candidate(cid, match, trust, age):
    candidate_data = {
        "id": cid,
        "subject_key": SUBJECT,
        "role": ROLE,
        "eligible": True,
        "match_score": match,
    }
    # Missing keys are swept separately from explicit numeric zero. In the
    # current quality function both contribute zero additive score, so they
    # may have different semantics/explanations but have the same numerical
    # contribution here.
    if trust is not None:
        candidate_data["source_trust"] = trust
    if age is not None:
        candidate_data["age_confidence"] = age
    return candidate_data


def quality(match, trust, age):
    value = 0.86 * match
    if trust is not None:
        value += 0.08 * trust
    if age is not None:
        value += 0.06 * age
    return value


def match_only_selected_id(stronger, weaker):
    # Direct match-only control: select solely by the higher raw match score.
    # Ties are resolved only for returning a concrete ID; they are counted
    # separately below and are not counted as lower-match selections.
    return max(
        (stronger, weaker),
        key=lambda item: (
            item["match_score"],
            item["role"],
            item["id"],
        ),
    )["id"]


def main():
    # Every case is exactly: same subject, two candidates, requested size 1,
    # both eligible, and no human_feedback / preference fields of any kind.
    expected_cases = len(GAPS) * (len(FEATURE_VALUES) ** 4)
    by_gap = {}
    observed_cases = 0
    fixed_lower_match_selections = 0
    control_lower_match_selections = 0
    total_ties = 0
    total_finite = 0
    counterexamples = []

    for gap in GAPS:
        stronger_match = 0.8
        weaker_match = round(0.8 - gap, 6)
        gap_record = {
            "gap": gap,
            "stronger_match": stronger_match,
            "weaker_match": weaker_match,
            "cases": 0,
            "fixed_rank_selects_lower_match": 0,
            "raw_match_only_control_selects_lower_match": 0,
            "equal_raw_match_ties": 0,
            "fixed_rank_selects_lower_match_rate": None,
            "raw_match_only_control_selects_lower_match_rate": None,
        }

        for stronger_trust, stronger_age, weaker_trust, weaker_age in itertools.product(
            FEATURE_VALUES, repeat=4
        ):
            stronger = candidate(
                "stronger", stronger_match, stronger_trust, stronger_age
            )
            weaker = candidate(
                "weaker", weaker_match, weaker_trust, weaker_age
            )

            result = rank_pack([stronger, weaker], size=1)
            selected_id = result["selected_ids"][0]
            control_selected_id = match_only_selected_id(stronger, weaker)

            stronger_quality = quality(
                stronger_match, stronger_trust, stronger_age
            )
            weaker_quality = quality(
                weaker_match, weaker_trust, weaker_age
            )

            is_tie = stronger_match == weaker_match

            if is_tie:
                gap_record["equal_raw_match_ties"] += 1
                total_ties += 1
            else:
                if selected_id == "weaker":
                    gap_record["fixed_rank_selects_lower_match"] += 1
                    fixed_lower_match_selections += 1

                if control_selected_id == "weaker":
                    gap_record[
                        "raw_match_only_control_selects_lower_match"
                    ] += 1
                    control_lower_match_selections += 1

            reported_values = [
                gap,
                stronger_match,
                weaker_match,
                stronger_quality,
                weaker_quality,
            ]
            finite = all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value == value
                and value not in (float("inf"), float("-inf"))
                for value in reported_values
            )
            if finite:
                total_finite += 1

            gap_record["cases"] += 1
            observed_cases += 1

            if (
                not is_tie
                and selected_id == "weaker"
                and len(counterexamples) < 6
            ):
                counterexamples.append(
                    {
                        "gap": gap,
                        "selected_id": selected_id,
                        "selected_raw_match": weaker_match,
                        "unselected_raw_match": stronger_match,
                        "selected_source_trust": weaker_trust,
                        "selected_age_confidence": weaker_age,
                        "unselected_source_trust": stronger_trust,
                        "unselected_age_confidence": stronger_age,
                        "selected_fixed_quality": weaker_quality,
                        "unselected_fixed_quality": stronger_quality,
                    }
                )

        nontie_cases = gap_record["cases"] - gap_record["equal_raw_match_ties"]
        gap_record["fixed_rank_selects_lower_match_rate"] = (
            gap_record["fixed_rank_selects_lower_match"] / nontie_cases
            if nontie_cases
            else None
        )
        gap_record["raw_match_only_control_selects_lower_match_rate"] = (
            gap_record["raw_match_only_control_selects_lower_match"]
            / nontie_cases
            if nontie_cases
            else None
        )
        by_gap[str(gap)] = gap_record

    non_tie_cases = expected_cases - total_ties

    output = {
        "experiment": "evidence_sensitivity",
        "module_under_test": "experiments.algorithm_lab.ranking.rank_pack",
        "design": {
            "subjects_per_case": 1,
            "same_subject": True,
            "candidates_per_case": 2,
            "requested_size": 1,
            "eligible": True,
            "human_feedback_present": False,
            "match_gap_values": GAPS,
            "source_trust_values": FEATURE_VALUES,
            "age_confidence_values": FEATURE_VALUES,
            "stronger_base_match": 0.8,
            "weaker_base_match_rule": "0.8 - match_gap",
            "missing_feature_meaning": (
                "key omitted; swept separately from explicit 0.0. In the "
                "current quality function, omission and explicit 0.0 make "
                "the same numerical score contribution, even though their "
                "semantics and explanations may differ."
            ),
            "fixed_weights_from_module": {
                "match_score": 0.86,
                "source_trust": 0.08,
                "age_confidence": 0.06,
            },
        },
        "case_count_check": {
            "gaps": len(GAPS),
            "feature_settings_per_candidate": len(FEATURE_VALUES) ** 2,
            "two_candidate_settings": len(FEATURE_VALUES) ** 4,
            "expected_total_cases": expected_cases,
            "observed_total_cases": observed_cases,
            "matches_expected_total": observed_cases == expected_cases,
            "match_only_control_rule": "max by raw match_score, role, id",
        },
        "control": {
            "name": "match_only_raw_score_control",
            "rule": "select higher raw match_score; equal matches are ties, not lower-match mistakes",
            "total_lower_match_selections": control_lower_match_selections,
        },
        "totals": {
            "cases": observed_cases,
            "equal_raw_match_ties": total_ties,
            "non_tie_cases": non_tie_cases,
            "fixed_rank_lower_match_selections": fixed_lower_match_selections,
            "fixed_rank_lower_match_selection_rate": (
                fixed_lower_match_selections / non_tie_cases
                if non_tie_cases
                else None
            ),
            "cases_with_all_reported_metrics_finite": total_finite,
            "all_reported_metrics_finite": total_finite == observed_cases,
        },
        "by_match_gap": by_gap,
        "reproducible_counterexamples_first_up_to_6": counterexamples,
        "counterexample_count_shown": len(counterexamples),
        "synthetic_limitations": [
            "Candidates are synthetic, share one subject and role, and do not establish real-world ranking validity.",
            "Only two eligible candidates and size=1 are measured; larger packs, role diversity, exclusions, multiple subjects, and incomplete groups are outside this sweep.",
            "Feature values are limited to None, 0, 0.5, and 1; missing keys are measured separately from explicit zero but contribute equally to the current numerical quality score.",
            "The experiment tests fixed-weight sensitivity only and makes no source reputation or aesthetic quality claim.",
            "No files or network are used, and the match-only control is a direct raw-score comparison rather than a separate production model.",
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()