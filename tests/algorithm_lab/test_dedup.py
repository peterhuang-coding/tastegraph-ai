import pytest

from experiments.algorithm_lab.dedup import deduplicate


SHA1 = "a" * 64
SHA2 = "b" * 64
SHA3 = "c" * 64


def rec(rid, url="", sha256=None, source_url="", phash=None):
    data = {"id": rid, "url": url, "sha256": sha256, "source_url": source_url}
    if phash is not None:
        data["phash"] = phash
    return data


CASES = [
    ("same_sha_two_sources", [rec("a", "http://x/1", SHA1, "http://s/1"), rec("b", "http://x/2", SHA1, "http://s/2")], {"groups": [("a", ["a", "b"], ["http://s/1", "http://s/2"])], "retained": ["a"], "review": []}),
    ("distinct_singletons_retained", [rec("a", "http://x/1", SHA1), rec("b", "http://x/2", SHA2)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("identical_url_group", [rec("a", "http://x/i", SHA1), rec("b", "http://x/i", SHA1)], {"groups": [("a", ["a", "b"], [""])], "retained": ["a"], "review": []}),
    ("utm_removed", [rec("a", "http://x/i?utm_source=n", SHA1), rec("b", "http://x/i?utm_campaign=p", SHA1)], {"groups": [("a", ["a", "b"], [""])], "retained": ["a"], "review": []}),
    ("size_variant_protected", [rec("a", "http://x/i?w=100", SHA1), rec("b", "http://x/i?w=200", SHA2)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("transform_path_protected", [rec("a", "http://x/a.jpg", SHA1), rec("b", "http://x/a_webp.jpg", SHA2)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("case_sensitive_path_protected", [rec("a", "http://x/A.jpg", SHA1), rec("b", "http://x/a.jpg", SHA2)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("signature_param_protected", [rec("a", "http://x/i?sig=1", SHA1), rec("b", "http://x/i?sig=2", SHA2)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("missing_hashes_not_grouped", [rec("a", "http://x/1", None), rec("b", "http://x/2", None)], {"groups": [], "retained": ["a", "b"], "review": []}),
    ("same_url_both_missing_hash_group", [rec("a", "http://x/i", None), rec("b", "http://x/i", None)], {"groups": [("a", ["a", "b"], [""])], "retained": ["a"], "review": []}),
    ("same_url_one_missing_hash_group", [rec("a", "http://x/i", SHA1), rec("b", "http://x/i", None)], {"groups": [("a", ["a", "b"], [""])], "retained": ["a"], "review": []}),
    ("same_url_conflicting_hash_review", [rec("a", "http://x/i", SHA1), rec("b", "http://x/i", SHA2)], {"groups": [], "retained": ["a", "b"], "review": [["a", "b"]]}),
    ("near_phash_review_only", [rec("a", "http://x/1", SHA1, phash="0" * 16), rec("b", "http://x/2", SHA2, phash="0" * 15 + "1")], {"groups": [], "retained": ["a", "b"], "review": [["a", "b"]]}),
    ("same_source_different_angles", [rec("a", "http://x/angle1", SHA1, source_url="http://s"), rec("b", "http://x/angle2", SHA2, source_url="http://s")], {"groups": [], "retained": ["a", "b"], "review": []}),
]


@pytest.mark.parametrize("name,records,expected", CASES, ids=[c[0] for c in CASES])
def test_deduplicate_contract(name, records, expected):
    before = [dict(r) for r in records]
    result = deduplicate(records)
    assert set(result) == {"groups", "retained", "review_pairs"}
    assert sorted(result["retained"]) == sorted(expected["retained"])
    assert len(result["groups"]) == len(expected["groups"])
    assert all(len(g["member_ids"]) >= 2 for g in result["groups"])
    for group, (rep, members, sources) in zip(result["groups"], expected["groups"]):
        assert group["representative_id"] == rep
        assert sorted(group["member_ids"]) == sorted(members)
        assert sorted(group["source_urls"]) == sorted(sources)
    assert sorted((p[0], p[1]) for p in result["review_pairs"]) == sorted(tuple(p) for p in expected["review"])
    assert records == before


@pytest.mark.parametrize("bad", [rec("", "http://x", SHA1), {"id": None, "url": "http://x", "sha256": SHA1, "source_url": ""}, {"url": "http://x", "sha256": SHA1, "source_url": ""}])
def test_invalid_id_rejected(bad):
    with pytest.raises(ValueError):
        deduplicate([bad])


def test_duplicate_id_rejected():
    with pytest.raises(ValueError):
        deduplicate([rec("a", "http://x/1", SHA1), rec("a", "http://x/2", SHA2)])
