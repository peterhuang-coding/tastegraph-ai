import math


def _num(value, default=0.0):
    if value is None or isinstance(value, bool):
        return default
    if not isinstance(value, (int, float)):
        return default
    value = float(value)
    if not math.isfinite(value):
        return default
    return value


def _clip01(value):
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _valid_identity(candidate):
    if not isinstance(candidate, dict):
        return False
    cid = candidate.get("id")
    subject = candidate.get("subject_key")
    role = candidate.get("role")
    return (
        isinstance(cid, str)
        and isinstance(subject, str)
        and isinstance(role, str)
        and cid.strip()
        and subject.strip()
        and role.strip()
    )


def _quality(candidate):
    # Match is the primary ordering signal. Source trust and date confidence
    # are small offline quality features and never select across subjects.
    match = _clip01(candidate.get("match_score"))
    match = 0.0 if match is None else match
    quality = 0.86 * match

    trust = _clip01(candidate.get("source_trust"))
    if trust is not None:
        quality += 0.08 * trust

    age = _clip01(candidate.get("age_confidence"))
    if age is not None:
        quality += 0.06 * age

    return quality, match


def _base_sort_key(candidate):
    quality, match = _quality(candidate)
    return quality, match, str(candidate["role"]), str(candidate["id"])


def _is_operator_negative(candidate):
    if candidate.get("preference_actor") != "operator":
        return False
    pref_raw = candidate.get("human_preference")
    if pref_raw is None or isinstance(pref_raw, bool):
        return False
    if not isinstance(pref_raw, (int, float)):
        return False
    pref = float(pref_raw)
    return math.isfinite(pref) and pref < 0.0


def _eligible(candidate, excluded_ids):
    if not _valid_identity(candidate):
        raise ValueError(
            "each candidate must have non-empty string id, subject_key, and role"
        )
    if candidate.get("eligible") is not True:
        return False
    if candidate["id"] in excluded_ids:
        return False
    if _is_operator_negative(candidate):
        return False
    return True


def _ordered_candidates(candidates):
    # Deterministic regardless of input ordering.
    return sorted(candidates, key=_base_sort_key, reverse=True)


def _top_size_quality(candidates, size):
    ordered = _ordered_candidates(candidates)
    chosen = _select_in_group(ordered, min(size, len(ordered)))
    return sum(_quality(candidate)[0] for candidate in chosen)


def _select_in_group(ordered, size):
    if size <= 0 or not ordered:
        return []

    chosen = [ordered[0]]
    if size == 1:
        return chosen

    chosen_roles = {ordered[0]["role"]}
    pool = list(ordered[1:])

    while len(chosen) < size and pool:
        best_index = 0
        best = pool[0]
        best_quality, best_match = _quality(best)
        best_new_role = best["role"] not in chosen_roles

        for index, candidate in enumerate(pool[1:], 1):
            quality, match = _quality(candidate)
            new_role = candidate["role"] not in chosen_roles

            # Role diversity can only win when match quality is effectively
            # tied. A materially stronger same-role image is never replaced.
            take_diverse_role = (
                new_role
                and not best_new_role
                and best_match - match <= 0.01
                and best_match >= match
            )
            take_same_status = new_role == best_new_role and (
                quality,
                match,
                str(candidate["role"]),
                str(candidate["id"]),
            ) > (
                best_quality,
                best_match,
                str(best["role"]),
                str(best["id"]),
            )

            if take_diverse_role or take_same_status:
                best_index = index
                best = candidate
                best_quality = quality
                best_match = match
                best_new_role = new_role

        chosen.append(best)
        chosen_roles.add(best["role"])
        pool.pop(best_index)

    return chosen


def rank_pack(candidates, size=8, excluded_ids=()):
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("size must be a non-negative integer")
    if size == 0:
        return {"selected_ids": [], "explanations": {}}

    try:
        excluded = frozenset(excluded_ids)
    except TypeError as exc:
        raise ValueError("excluded_ids must be an iterable") from exc

    usable = []
    seen_ids = set()
    for candidate in candidates:
        if not _valid_identity(candidate):
            raise ValueError(
                "each candidate must have non-empty string id, subject_key, and role"
            )
        cid = candidate["id"]
        if cid in seen_ids:
            raise ValueError("candidate ids must be unique")
        seen_ids.add(cid)
        if _eligible(candidate, excluded):
            usable.append(candidate)

    if not usable:
        return {"selected_ids": [], "explanations": {}}

    groups = {}
    for candidate in usable:
        subject = candidate["subject_key"]
        groups.setdefault(subject, []).append(candidate)

    complete_groups = []
    incomplete_groups = []
    for subject, members in groups.items():
        if len(members) >= size:
            complete_groups.append((subject, members))
        else:
            incomplete_groups.append((subject, members))

    if complete_groups:
        # A complete group wins by the quality of its best requested pack,
        # not by having arbitrarily more unused members.
        chosen_subject, chosen_pool = max(
            complete_groups,
            key=lambda item: (
                _top_size_quality(item[1], size),
                sum(_quality(candidate)[1] for candidate in item[1]),
                str(item[0]),
            ),
        )
    else:
        # No subject can fill the request. Keep the pack coherent and choose
        # the largest available group first; quality breaks cardinality ties.
        chosen_subject, chosen_pool = max(
            incomplete_groups,
            key=lambda item: (
                len(item[1]),
                _top_size_quality(item[1], len(item[1])),
                sum(_quality(candidate)[1] for candidate in item[1]),
                str(item[0]),
            ),
        )

    ordered_pool = _ordered_candidates(chosen_pool)
    selected = _select_in_group(ordered_pool, min(size, len(ordered_pool)))

    explanations = {}
    for candidate in selected:
        cid = candidate["id"]
        role = candidate["role"]
        subject = candidate["subject_key"]
        details = ["coherent subject " + subject, "role " + role]

        match = _clip01(candidate.get("match_score"))
        if match is not None:
            details.append("match_score %.3f" % match)
        if _clip01(candidate.get("source_trust")) is not None:
            details.append("source evidence considered")
        if _clip01(candidate.get("age_confidence")) is not None:
            details.append("date evidence considered")

        explanations[cid] = (
            "Selected %s from one consistent subject group; %s."
            % (cid, "; ".join(details))
        )

    return {
        "selected_ids": [candidate["id"] for candidate in selected],
        "explanations": explanations,
    }
