import pytest

from experiments.algorithm_lab.age import classify_age
from experiments.algorithm_lab.dedup import deduplicate


AGE_AS_OF = "2026-09-20"


# Shortcoming: copyright wording is not capture evidence, but the prototype accepts it.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="copyright wording incorrectly supplies a capture year")
@pytest.mark.parametrize(
    "record",
    [
        {"capture_year": 1995, "capture_evidence": "photograph copyright 1995"},
    ],
)
def test_age_photograph_copyright_1995_is_unknown(record):
    result = classify_age(record, as_of=AGE_AS_OF)
    assert result["kind"] == "unknown"
    assert result["capture_year"] is None


# Shortcoming: without a structured year, conflicting unstructured capture claims cannot be resolved.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="conflicting unstructured capture evidence is ignored")
@pytest.mark.parametrize(
    "record",
    [
        {"caption": "Photographed in 1995", "capture_evidence": "Photographed in 2010"},
    ],
)
def test_age_conflicting_caption_and_evidence_is_unknown(record):
    result = classify_age(record, as_of=AGE_AS_OF)
    assert result["kind"] == "unknown"
    assert result["capture_year"] is None


# Shortcoming: mutually exclusive capture years, one in the future, must remain unresolved.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="conflicting past and future capture claims are accepted")
@pytest.mark.parametrize(
    "record",
    [
        {"caption": "Photographed in 1995 and photographed in 2030"},
    ],
)
def test_age_conflicting_past_and_future_caption_years_is_unknown(record):
    result = classify_age(record, as_of=AGE_AS_OF)
    assert result["kind"] == "unknown"
    assert result["capture_year"] is None


# Shortcoming: a printing date is a later production event, not the capture date.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="print year is incorrectly accepted as capture year")
@pytest.mark.parametrize(
    "record",
    [
        {"caption": "Without capture date, photograph printed in 1995"},
    ],
)
def test_age_print_year_without_capture_date_is_unknown(record):
    result = classify_age(record, as_of=AGE_AS_OF)
    assert result["kind"] == "unknown"
    assert result["capture_year"] is None


# Shortcoming: UTM-only query differences should canonicalize to the bare URL even without hashes.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="hash-free UTM URL is not merged with bare URL")
@pytest.mark.parametrize(
    "records",
    [
        [
            {"id": "a", "url": "https://example.test/photo?utm_source=x"},
            {"id": "b", "url": "https://example.test/photo"},
        ],
    ],
)
def test_dedup_utm_only_url_and_bare_url_merge_without_hashes(records):
    result = deduplicate(records)
    assert len(result["groups"]) == 1
    assert set(result["retained"]) == {"a"} or set(result["retained"]) == {"b"}


# Shortcoming: host case is incidental; the same host/path should merge without hashes.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="same URL with differing host case is not merged")
@pytest.mark.parametrize(
    "records",
    [
        [
            {"id": "a", "url": "https://EXAMPLE.test/photo"},
            {"id": "b", "url": "https://example.test/photo"},
        ],
    ],
)
def test_dedup_same_host_different_case_and_path_merge_without_hashes(records):
    result = deduplicate(records)
    assert len(result["groups"]) == 1
    assert set(result["retained"]) == {"a"} or set(result["retained"]) == {"b"}


# Different substantive query values and no hashes are insufficient evidence to merge.
@pytest.mark.parametrize(
    "records",
    [
        [
            {"id": "a", "url": "https://example.test/photo?size=large"},
            {"id": "b", "url": "https://example.test/photo?size=small"},
        ],
    ],
)
def test_dedup_different_size_query_without_hashes_preserves_two(records):
    result = deduplicate(records)
    assert result["groups"] == []
    assert set(result["retained"]) == {"a", "b"}


# Exact URL equality is sufficient to merge even when content hashes are absent.
@pytest.mark.parametrize(
    "records",
    [
        [
            {"id": "a", "url": "https://example.test/photo"},
            {"id": "b", "url": "https://example.test/photo"},
        ],
    ],
)
def test_dedup_two_missing_hash_records_with_same_exact_url_merge(records):
    result = deduplicate(records)
    assert len(result["groups"]) == 1
    assert set(result["retained"]) == {"a"} or set(result["retained"]) == {"b"}
