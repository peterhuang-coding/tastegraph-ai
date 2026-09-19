"""Offline seeded benchmark for experiments.algorithm_lab.ranking.rank_pack."""
import json
import random
import statistics
import time
from experiments.algorithm_lab.ranking import rank_pack

ROLES = ["lead", "support", "wide", "detail", "context", "edge"]


def make_candidate(rng, sid, subject=None, role=None, eligible=True, negative=False):
    if subject is None:
        subject = "noise%02d" % rng.randrange(6)
    if role is None:
        role = rng.choice(ROLES)
    return {
        "id": "c%06d" % sid,
        "subject_key": subject,
        "role": role,
        "match_score": rng.uniform(0.0, 1.0),
        "source_trust": rng.uniform(0.0, 1.0),
        "age_confidence": rng.uniform(0.0, 1.0),
        "eligible": eligible,
        "preference_actor": "operator" if negative else "system",
        "human_preference": -1.0 if negative else 1.0,
    }


def fixture(rng, groups, roles, size):
    out, sid = [], 0
    for g in range(groups):
        subject = "subj%02d" % g
        for r in range(roles):
            for _ in range(size):
                sid += 1
                out.append(make_candidate(rng, sid, subject, ROLES[r]))
    # Explicitly exercise every rejection path in addition to excluded IDs.
    for _ in range(6):
        sid += 1
        out.append(make_candidate(rng, sid, eligible=False))
    for _ in range(6):
        sid += 1
        out.append(make_candidate(rng, sid, negative=True))
    for _ in range(8):
        sid += 1
        out.append(make_candidate(rng, sid))
    rng.shuffle(out)
    return out


def rejected_by_filters(c, excluded):
    if not isinstance(c, dict):
        return True
    if c.get("eligible") is not True:
        return True
    if c.get("id") in excluded:
        return True
    return (
        c.get("preference_actor") == "operator"
        and isinstance(c.get("human_preference"), (int, float))
        and not isinstance(c.get("human_preference"), bool)
        and float(c["human_preference"]) < 0.0
    )


def independent_top_match(cands, size, excluded=()):
    # Illustrative naive baseline only: same filters, independently sorted.
    usable = [c for c in cands if not rejected_by_filters(c, excluded)]
    usable.sort(key=lambda c: (float(c.get("match_score", 0.0)), str(c.get("id"))), reverse=True)
    return [c["id"] for c in usable[:size]]


def evaluate(cands, ids, size, excluded):
    by_id = {c["id"]: c for c in cands}
    unknown = [i for i in ids if i not in by_id]
    sel = [by_id[i] for i in ids if i in by_id]
    subjects = {c["subject_key"] for c in sel}
    roles_present = {c["role"] for c in sel}
    scores = [float(c.get("match_score", 0.0)) for c in sel]
    return {
        "coherent_one_subject": len(subjects) <= 1,
        "ineligible_selected": sum(1 for c in sel if c.get("eligible") is not True),
        "excluded_id_selected": sum(1 for i in ids if i in excluded),
        "operator_negative_selected": sum(1 for c in sel if rejected_by_filters(c, set())),
        "duplicate_output_ids": len(ids) - len(set(ids)),
        "unknown_output_ids": len(unknown),
        "permutation_stable": False,
        "role_coverage": len(roles_present) / max(1, min(size, len(ROLES))),
        "mean_match_score": statistics.mean(scores) if scores else 0.0,
        "selected_count": len(ids),
    }


def run_trials():
    rng = random.Random(20260214)
    rows = {"prototype": [], "naive_independent_top_match_baseline_illustrative_not_production": []}
    sweeps = []
    for trial in range(200):
        groups = (trial % 4) + 1
        roles = (trial % 4) * 1 + 2
        size = min(8, roles + 1)
        cands = fixture(rng, groups, roles, size)
        excluded = {c["id"] for c in rng.sample(cands, 5)}
        pids = rank_pack(cands, size=size, excluded_ids=excluded)["selected_ids"]
        bids = independent_top_match(cands, size, excluded)
        shuffled = list(cands)
        rng.shuffle(shuffled)
        p_again = rank_pack(shuffled, size=size, excluded_ids=excluded)["selected_ids"]
        b_again = independent_top_match(shuffled, size, excluded)
        pm, bm = evaluate(cands, pids, size, excluded), evaluate(cands, bids, size, excluded)
        pm["permutation_stable"] = pids == p_again
        bm["permutation_stable"] = bids == b_again
        rows["prototype"].append(pm)
        rows[list(rows)[1]].append(bm)
        sweeps.append({"trial": trial + 1, "groups": groups, "roles": roles, "pack_size": size,
                       "fixture_eligible_false": 6, "fixture_operator_negative": 6,
                       "excluded_ids": len(excluded), "candidate_count": len(cands)})
    return rows, sweeps


def summarize(rows):
    keys = ["coherent_one_subject", "ineligible_selected", "excluded_id_selected",
            "operator_negative_selected", "duplicate_output_ids", "unknown_output_ids",
            "permutation_stable", "role_coverage", "mean_match_score", "selected_count"]
    out = {}
    for method, vals in rows.items():
        out[method] = {"trials": len(vals)}
        for k in keys:
            seq = [v[k] for v in vals]
            out[method][k] = sum(1 for x in seq if x) / len(seq) if isinstance(seq[0], bool) else statistics.mean(seq)
    return out


def timing_fixture(rng, n):
    cands, sid = [], 0
    groups, roles = 4, 5
    while len(cands) < n:
        sid += 1
        g = (sid - 1) // 50
        if g < groups:
            subject, role = "subj%02d" % g, ROLES[(sid - 1) % roles]
        else:
            subject, role = "noise%02d" % rng.randrange(4), rng.choice(ROLES)
        c = make_candidate(rng, sid, subject, role)
        if len(cands) % 17 == 0:
            c["eligible"] = False
        if len(cands) % 23 == 0:
            c["preference_actor"], c["human_preference"] = "operator", -1.0
        cands.append(c)
    rng.shuffle(cands)
    assert len(cands) == n
    return cands


def time_sizes():
    result = {}
    for n in (100, 1000):
        rng = random.Random(99173 + n)
        cands = timing_fixture(rng, n)
        timings = []
        for _ in range(5):
            t0 = time.perf_counter()
            rank_pack(cands, size=8)
            timings.append(time.perf_counter() - t0)
        result[str(n)] = {"repeats": 5, "actual_candidate_count": len(cands),
                          "median_seconds": statistics.median(timings)}
    return result


def main():
    rows, sweeps = run_trials()
    payload = {
        "context": {
            "seeded_offline": True,
            "random_seed_note": "Python random.Random 20260214 trials; timing RNG 99273/100173",
            "trials": len(rows["prototype"]),
            "synthetic_fixtures": "randomized subject/role groups plus eligible=False, operator-negative, and excluded-ID cases",
            "baseline_label": "naive independent top-match baseline (illustrative; not existing production)",
            "shared_filters": "eligible flag, excluded ids, operator-negative human preference",
            "sweep": {"fixture_group_counts": sorted(set(s["groups"] for s in sweeps)),
                      "role_counts": sorted(set(s["roles"] for s in sweeps)),
                      "pack_sizes": sorted(set(s["pack_size"] for s in sweeps))},
            "weights_note": "observational offline synthetic benchmark; exact internal weights are not assumed; no real-world/production effect claimed",
        },
        "observed_metrics": summarize(rows),
        "timing_perf_counter_5_repeat_median": time_sizes(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
