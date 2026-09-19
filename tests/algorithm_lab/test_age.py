from datetime import date

import pytest

from experiments.algorithm_lab.age import classify_age


AS_OF = "2026-09-20"


def rec(**kw):
    base = {
        "capture_year": None,
        "capture_evidence": "",
        "object_year": None,
        "page_published_at": None,
        "collected_at": None,
        "image_url": "",
        "caption": "",
    }
    base.update(kw)
    return base


CASES = [
    ("explicit documented old photo high", rec(capture_year=1995, capture_evidence="Photographer documented capture in 1995."), {"kind": "historical_photo", "capture_year": 1995, "confidence": "high"}),
    ("boundary exactly twenty years", rec(capture_year=2006, capture_evidence="photographer documented capture in 2006"), {"kind": "historical_photo", "capture_year": 2006, "confidence": "high"}),
    ("nineteen years contemporary", rec(capture_year=2007, capture_evidence="photographer documented capture in 2007"), {"kind": "contemporary_photo", "capture_year": 2007, "confidence": "high"}),
    ("caption photographed medium old", rec(caption="Photographed in 1995"), {"kind": "historical_photo", "capture_year": 1995, "confidence": "medium"}),
    ("webpage 2026 but caption 1995", rec(page_published_at="2026-01-10", caption="Photographed in 1995"), {"kind": "historical_photo", "capture_year": 1995, "confidence": "medium"}),
    ("2001 chair photographed 2026", rec(object_year=2001, capture_year=2026, capture_evidence="photographer documented capture in 2026"), {"kind": "historical_object_contemporary_photo", "capture_year": 2026, "confidence": "high"}),
    ("object design year alone unknown", rec(object_year=1975, caption="chair"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("upload path 1975 misleading unknown", rec(image_url="https://example.test/uploads/1975/photo.jpg", collected_at="2026-02-01"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("copyright 1975 misleading unknown", rec(caption="Copyright 1975. Interior view."), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("print date is not capture high", rec(capture_year=1980, capture_evidence="Print date 1985; photographer documented capture in 1980."), {"kind": "historical_photo", "capture_year": 1980, "confidence": "high"}),
    ("print date alone unknown", rec(capture_evidence="Print date 1985"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("archive word without year unknown", rec(caption="From the archive"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("no information unknown", rec(), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("conflicting years unknown", rec(capture_year=1995, capture_evidence="photographer documented capture in 1995", caption="Photographed in 2010"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("future capture unknown", rec(capture_year=2030, capture_evidence="photographer documented capture in 2030"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
    ("illegal numeric string unknown", rec(capture_year="1995", capture_evidence="photographer documented capture in 1995"), {"kind": "unknown", "capture_year": None, "confidence": "unknown"}),
]


@pytest.mark.parametrize("name,record,expected", CASES, ids=[c[0] for c in CASES])
def test_classify_age_synthetic_cases(name, record, expected):
    result = classify_age(record, as_of=AS_OF)
    assert isinstance(result, dict)
    assert set(result) == {"kind", "capture_year", "confidence", "evidence"}
    assert result["kind"] == expected["kind"]
    assert result["capture_year"] == expected["capture_year"]
    assert result["confidence"] == expected["confidence"]
    assert isinstance(result["evidence"], list)
    assert all(isinstance(item, str) for item in result["evidence"])
