from datetime import date
import re


_YEAR_RE = r"(?<!\d)(1\d{3}|20\d{2}|21\d{2})(?!\d)"
_CAPTURE_TERMS = (
    "photographed",
    "photograph",
    "photographs",
    "captured",
    "capture",
    "shot",
    "taken",
)
_NON_CAPTURE_TERMS = (
    "copyright",
    "uploaded",
    "upload",
    "published",
    "print",
    "printed",
    "scan",
    "scanned",
    "url",
    "page",
)
_NEGATIONS = ("not", "no", "never", "without")


def classify_age(record, as_of="2026-09-20"):
    unknown = {"kind": "unknown", "capture_year": None, "confidence": "unknown", "evidence": []}

    def fail():
        return dict(unknown)

    if not isinstance(record, dict):
        return fail()

    try:
        as_of_date = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return fail()

    capture_year = record.get("capture_year")
    capture_evidence = record.get("capture_evidence", "")
    object_year = record.get("object_year")
    caption = record.get("caption", "")

    if capture_evidence is None:
        capture_evidence = ""
    if caption is None:
        caption = ""
    if not isinstance(capture_evidence, str) or not isinstance(caption, str):
        return fail()

    structured_year = None
    if capture_year is not None:
        if isinstance(capture_year, bool) or not isinstance(capture_year, int):
            return fail()
        if not _valid_past_year(capture_year, as_of_date):
            return fail()
        structured_year = capture_year

    structured_claims = _capture_claims(capture_evidence, as_of_date)
    caption_claims = _capture_claims(caption, as_of_date)

    if structured_year is not None:
        if not structured_claims or any(y != structured_year for y in structured_claims):
            return fail()
        if caption_claims and any(y != structured_year for y in caption_claims):
            return fail()
        year = structured_year
        confidence = "high"
        evidence = [capture_evidence]
    elif caption_claims:
        if len(set(caption_claims)) != 1:
            return fail()
        year = caption_claims[0]
        confidence = "medium"
        evidence = [caption]
    else:
        return fail()

    if isinstance(object_year, bool) or not isinstance(object_year, int):
        if object_year is not None:
            return fail()
        old_object = False
    else:
        if not _valid_past_year(object_year, as_of_date):
            return fail()
        old_object = as_of_date.year - object_year >= 20

    age = as_of_date.year - year
    if age >= 20:
        kind = "historical_photo"
    elif old_object:
        kind = "historical_object_contemporary_photo"
    else:
        kind = "contemporary_photo"

    return {
        "kind": kind,
        "capture_year": year,
        "confidence": confidence,
        "evidence": evidence,
    }


def _valid_past_year(year, as_of_date):
    return (
        not isinstance(year, bool)
        and isinstance(year, int)
        and 1000 <= year <= 9999
        and year <= as_of_date.year
    )


def _capture_claims(text, as_of_date):
    claims = []
    for fragment in re.split(r"[.;:!?]|(?:\band\b)|(?:\bbut\b)", text):
        lowered = fragment.lower()
        if not _affirmative_capture(lowered):
            continue

        for match in re.finditer(_YEAR_RE, fragment):
            year = int(match.group(1))
            prefix = lowered[max(0, match.start() - 12):match.start()]
            if not any(word in prefix.split() for word in _NEGATIONS) and _valid_past_year(year, as_of_date):
                claims.append(year)
    return claims


def _affirmative_capture(lowered):
    if re.search(r"\b(?:not|no|never)\b[^.;:!?]{0,40}\b(?:" + "|".join(_CAPTURE_TERMS) + r")\b", lowered):
        return False
    if re.search(r"\b(?:" + "|".join(_CAPTURE_TERMS) + r")\b[^.;:!?]{0,40}\b(?:not|no|never)\b", lowered):
        return False
    if not re.search(r"\b(?:" + "|".join(_CAPTURE_TERMS) + r")\b", lowered):
        return False

    # "Photographed/captured in <year>" is a date statement.  Generic "photo"
    # only counts when a nearby non-capture source word is absent.
    if re.search(r"\b(?:photographed|photograph|photographs|captured|capture|shot|taken)\b", lowered):
        return True
    return not re.search(r"\b(?:" + "|".join(_NON_CAPTURE_TERMS) + r")\b", lowered)
