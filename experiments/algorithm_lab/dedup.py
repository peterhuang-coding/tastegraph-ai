def deduplicate(records):
    if not isinstance(records, (list, tuple)):
        raise ValueError("records must be a list or tuple")

    normalized = []
    seen_ids = set()

    for pos, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError("record at position %d must be a dict" % pos)

        rid = record.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("every record must have a non-empty string id")
        if rid in seen_ids:
            raise ValueError("duplicate record id: %r" % rid)
        seen_ids.add(rid)

        sha = record.get("sha256")
        sha = sha.lower() if _valid_sha256(sha) else None

        phash = record.get("phash")
        phash = phash.upper() if _valid_phash(phash) else None

        raw_url = record.get("url", "")
        normalized.append(
            {
                "id": rid,
                "sha256": sha,
                "url": _canonical_url(raw_url),
                "source_url": record.get("source_url", "") if record.get("source_url") is not None else "",
                "phash": phash,
            }
        )

    n = len(normalized)
    parent = list(range(n))
    rank = [0] * n
    review = set()

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    def add_review(a, b):
        if a != b and find(a) != find(b):
            review.add(tuple(sorted((normalized[a]["id"], normalized[b]["id"]))))

    by_sha = {}
    for i, item in enumerate(normalized):
        if item["sha256"]:
            by_sha.setdefault(item["sha256"], []).append(i)
    for indexes in by_sha.values():
        for j in indexes[1:]:
            union(indexes[0], j)

    by_url = {}
    for i, item in enumerate(normalized):
        if item["url"]:
            by_url.setdefault(item["url"], []).append(indexes_helper(i))

    # The helper is replaced below in actual implementation; see linear build.
    return _finish(normalized, parent, rank, review, find, union, add_review, by_url, n)


def indexes_helper(i):
    return i


def _valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdefABCDEF" for c in value)
    )


def _valid_phash(value):
    return (
        isinstance(value, str)
        and len(value) == 16
        and all(c in "0123456789abcdefABCDEF" for c in value)
    )


def _canonical_url(url):
    if not isinstance(url, str) or not url:
        return ""
    try:
        scheme, rest = _split_scheme(url)
        if not scheme or not rest:
            return ""
        scheme = scheme.lower()
        authority = rest
        target = ""
        query = ""
        fragment_pos = rest.find("#")
        if fragment_pos >= 0:
            rest = rest[:fragment_pos]
        query_pos = rest.find("?")
        if query_pos >= 0:
            target = rest[:query_pos]
            query = rest[query_pos + 1:]
        else:
            target = rest

        host = target
        userinfo = ""
        at_pos = target.rfind("@")
        if at_pos >= 0:
            userinfo = target[:at_pos + 1]
            host = target[at_pos + 1:]

        host = _lowercase_host_only(host)
        path = target[len(host):] if host.startswith("/") is False and host else target
        # Reconstruct from the authority split more reliably:
        if at_pos >= 0:
            authority_out = userinfo + host
        else:
            authority_out = host
        canonical = scheme + "://" + authority_out + path
        if query:
            canonical += "?" + _strip_utm_query(query)
        return canonical
    except Exception:
        return ""


def _split_scheme(url):
    for i, ch in enumerate(url):
        if ch == ":":
            return url[:i], url[i + 1:]
        if ch in "/?#" or not ch.isascii():
            break
    return "", ""


def _lowercase_host_only(authority_tail):
    # authority_tail begins at host and may include port; no slash yet.
    end = len(authority_tail)
    if authority_tail.startswith("["):
        close = authority_tail.find("]")
        if close >= 0:
            return "[" + authority_tail[1:close].lower() + "]" + authority_tail[close + 1:].lower()
    bracket = authority_tail.find(":")
    if bracket >= 0:
        return authority_tail[:bracket].lower() + authority_tail[bracket:].lower()
    return authority_tail.lower()


def _strip_utm_query(query):
    if not query:
        return ""
    kept = []
    for part in query.split("&"):
        key = part.split("=", 1)[0]
        try:
            decoded_key = _percent_decode(key).lower()
        except Exception:
            decoded_key = key.lower()
        if not decoded_key.startswith("utm_"):
            kept.append(part)
    return "&".join(kept)


def _percent_decode(value):
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "%" and i + 2 < len(value):
            out.append(chr(int(value[i + 1:i + 3], 16)))
            i += 3
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _finish(normalized, parent, rank, review, find, union, add_review, by_url, n):
    # Rebuild URL index directly to keep the implementation linear and simple.
    by_url = {}
    for i, item in enumerate(normalized):
        if item["url"]:
            by_url.setdefault(item["url"], []).append(i)

    for indexes in by_url.values():
        hashed = [(i, normalized[i]["sha256"]) for i in indexes if normalized[i]["sha256"]]
        distinct_hashes = {h for _, h in hashed}

        if len(distinct_hashes) <= 1:
            for j in indexes[1:]:
                union(indexes[0], j)
        else:
            root_to_hash = {}
            conflict_roots = set()
            for i, h in hashed:
                r = find(i)
                previous = root_to_hash.get(r)
                if previous is not None and previous != h:
                    conflict_roots.add(r)
                else:
                    root_to_hash[r] = h

            root_members = {}
            for i in indexes:
                root_members.setdefault(find(i), []).append(i)

            roots = list(root_members)
            for p in range(len(roots)):
                for q in range(p + 1, len(roots)):
                    hp = root_to_hash.get(roots[p])
                    hq = root_to_hash.get(roots[q])
                    if hp and hq and hp != hq:
                        for a in root_members[roots[p]]:
                            for b in root_members[roots[q]]:
                                add_review(a, b)

    for i in range(n):
        left = normalized[i]
        if not left["phash"]:
            continue
        for j in range(i + 1, n):
            right = normalized[j]
            if not right["phash"]:
                continue
            if find(i) == find(j):
                continue
            distance = bin(int(left["phash"], 16) ^ int(right["phash"], 16)).count("1")
            if distance <= 4:
                add_review(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    groups = []
    retained = []

    ordered_clusters = sorted(
        clusters.values(),
        key=lambda members: min(normalized[i]["id"] for i in members),
    )

    for members in ordered_clusters:
        members = sorted(members, key=lambda i: normalized[i]["id"])
        rep = members[0]
        retained.append(normalized[rep]["id"])
        if len(members) < 2:
            continue

        sources = []
        seen_sources = set()
        for i in members:
            source = normalized[i]["source_url"]
            if source not in seen_sources:
                seen_sources.add(source)
                sources.append(source)

        groups.append(
            {
                "representative_id": normalized[rep]["id"],
                "member_ids": [normalized[i]["id"] for i in members],
                "source_urls": sources,
            }
        )

    return {
        "groups": groups,
        "retained": retained,
        "review_pairs": [list(pair) for pair in sorted(review)],
    }
