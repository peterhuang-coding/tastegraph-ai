import base64, io, threading, time, uuid
from pathlib import Path

import pytest
from PIL import Image

from taste_graph_ai.services.collection_research import CollectionResearch
from taste_graph_ai.services.collections import CollectionError, CollectionStore

WAIT = 4.0


def fresh_store(tmp_path):
    return CollectionStore(tmp_path / "store.db", tmp_path / "media")


def make_doc(s, title="Toy", questions=("Brand history?",), target=True):
    d = s.create({"create_token": str(uuid.uuid4()), "title": title, "questions": list(questions), "known_info": "SECRET", "private_notes": "PRIVATE"})
    b = io.BytesIO(); Image.new("RGB", (20, 20), "red").save(b, "PNG")
    d = s.add_photo(d["id"], {"expected_revision": d["revision"], "name": "toy.png", "data_base64": base64.b64encode(b.getvalue()).decode()})
    if target:
        d = s.action(d["id"], {"expected_revision": d["revision"], "action": "confirm_target", "label": "LEGO", "confirmed": True})
    return d


def wait_terminal(s, item_id):
    end = time.monotonic() + WAIT
    while time.monotonic() < end:
        d = s.get(item_id)
        if d["research"]["state"] in {"awaiting_review", "failed", "cancelled"}:
            return d
        time.sleep(0.02)
    raise AssertionError("research did not finish")


def page(title, text="LEGO is a Danish toy brand."):
    return {"query": {"pages": [{"title": title, "extract": text}]}}


def search(titles):
    return {"query": {"search": [{"title": t, "snippet": "SNIPPET"} for t in titles]}}


def test_research_minimization_and_extract_source(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s); seen = []
    def http(url, params, timeout):
        seen.append(dict(params))
        return search(["LEGO"]) if params.get("list") == "search" else page("LEGO")
    r = CollectionResearch(s, http_get=http, ocr=lambda path, timeout: "")
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True, "language": "en"})
    out = wait_terminal(s, d["id"]); res = out["research"]["result"]
    assert out["research"]["state"] == "awaiting_review"
    assert all("SECRET" not in str(x) and "PRIVATE" not in str(x) for x in seen)
    assert res["inputs"].keys() == {"mode", "target_label", "questions", "language", "allow_external"}
    assert res["sources"][0]["excerpt"] == "LEGO is a Danish toy brand."
    assert "SNIPPET" not in str(res["sources"])


def test_requires_consent_language_revision_and_confirmed_target(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s)
    r = CollectionResearch(s, http_get=lambda *a, **kw: {}, ocr=lambda *a, **kw: "")
    with pytest.raises(CollectionError):
        r.start(d["id"], {"expected_revision": d["revision"], "mode": "research"})
    with pytest.raises(CollectionError):
        r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True, "language": "de"})
    with pytest.raises(CollectionError):
        r.start(d["id"], {"mode": "research", "allow_external": True})
    d2 = make_doc(s, "No target", target=False)
    with pytest.raises(CollectionError):
        r.start(d2["id"], {"expected_revision": d2["revision"], "mode": "research", "allow_external": True})


def test_duplicate_and_global_capacity_are_limited(tmp_path):
    s = fresh_store(tmp_path); docs = [make_doc(s, f"T{i}") for i in range(3)]
    entered, release = threading.Event(), threading.Event()
    def http(url, params, timeout):
        entered.set(); release.wait(WAIT)
        return search([])
    r = CollectionResearch(s, http_get=http)
    r.start(docs[0]["id"], {"expected_revision": docs[0]["revision"], "mode": "research", "allow_external": True})
    assert entered.wait(WAIT)
    with pytest.raises(CollectionError):
        r.start(docs[0]["id"], {"expected_revision": docs[0]["revision"], "mode": "research", "allow_external": True})
    r.start(docs[1]["id"], {"expected_revision": docs[1]["revision"], "mode": "research", "allow_external": True})
    time.sleep(0.1)
    with pytest.raises(CollectionError):
        r.start(docs[2]["id"], {"expected_revision": docs[2]["revision"], "mode": "research", "allow_external": True})
    release.set()
    for d in docs[:2]: wait_terminal(s, d["id"])


def test_cancelled_run_makes_no_second_request(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s); started, stop_search = threading.Event(), threading.Event(); calls = []
    def http(url, params, timeout):
        calls.append(params)
        if params.get("list") == "search":
            started.set(); stop_search.wait(WAIT); return search(["LEGO"])
        raise AssertionError("extract should not run")
    r = CollectionResearch(s, http_get=http)
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True})
    assert started.wait(WAIT)
    cur = s.get(d["id"])
    out = r.cancel(d["id"], {"expected_revision": cur["revision"]})
    stop_search.set()
    end = time.monotonic() + WAIT
    while time.monotonic() < end and s.get(d["id"])["research"]["state"] != "cancelled": time.sleep(0.02)
    assert s.get(d["id"])["research"]["state"] == "cancelled"
    assert len(calls) == 1


def test_restart_interrupts_running_and_recovery_gets_docs(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s); hold = threading.Event()
    old = CollectionResearch(s, http_get=lambda *a, **kw: hold.wait(WAIT) and {})
    old.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True})
    time.sleep(0.1)
    new = CollectionResearch(s, http_get=lambda *a, **kw: {})
    recovered = new.recover_interrupted()
    assert recovered[0]["research"]["state"] == "failed"
    assert "restart" in recovered[0]["research"]["error"]
    hold.set()


def test_identify_does_not_require_target_and_empty_ocr_succeeds(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s, target=False); pid = d["photos"][0]["id"]
    r = CollectionResearch(s, http_get=lambda *a, **kw: {}, ocr=lambda path, timeout: "   ")
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "identify", "photo_ids": [pid]})
    out = wait_terminal(s, d["id"]); res = out["research"]["result"]
    assert out["research"]["state"] == "awaiting_review"
    assert res["observations"][0]["photo_id"] == pid
    assert res["gaps"][0]["photo_id"] == pid
    assert "target_label" not in res["inputs"]


def test_search_error_terminates_and_preserves_partial_sources(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s)
    docs = iter([page("LEGO")])
    def http(url, params, timeout):
        if params.get("list") == "search": raise RuntimeError("403 forbidden")
        return next(docs)
    r = CollectionResearch(s, http_get=http)
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True})
    out = wait_terminal(s, d["id"])
    assert out["research"]["state"] == "failed"
    assert out["research"]["error"] == "403 forbidden"
    assert out["research"]["result"]["errors"][0]["stage"] == "search"


def test_zero_search_results_are_successful_gaps(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s)
    r = CollectionResearch(s, http_get=lambda *a, **kw: search([]))
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True})
    out = wait_terminal(s, d["id"]); res = out["research"]["result"]
    assert out["research"]["state"] == "awaiting_review"
    assert any("No readable" in str(x) for x in res["gaps"])


def test_ocr_error_fails_but_keeps_partial_observations(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s, target=False); pids = [p["id"] for p in d["photos"]]
    b = io.BytesIO(); Image.new("RGB", (8, 8), "blue").save(b, "PNG")
    d = s.add_photo(d["id"], {"expected_revision": d["revision"], "name": "two.png", "data_base64": base64.b64encode(b.getvalue()).decode()})
    pids = [p["id"] for p in d["photos"]]
    def ocr(path, timeout):
        if str(path).endswith(pids[0] + ".png"): return "BRAND"
        raise RuntimeError("ocr boom")
    r = CollectionResearch(s, ocr=ocr)
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "identify", "photo_ids": pids})
    out = wait_terminal(s, d["id"]); res = out["research"]["result"]
    assert out["research"]["state"] == "failed"
    assert len(res["observations"]) == 1
    assert res["errors"][-1]["error"] == "ocr boom"


def test_no_auto_claim_draft_publication_edits(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s)
    r = CollectionResearch(s, http_get=lambda *a, **kw: page("LEGO", "Public history."))
    r.start(d["id"], {"expected_revision": d["revision"], "mode": "research", "allow_external": True})
    out = wait_terminal(s, d["id"])
    assert out.get("claims", []) == []
    assert out["draft"] == d["draft"]
    assert out.get("status") != "published"
    assert {"id", "title", "research_state"} <= s.list_items()[0].keys()


def test_cancel_keeps_completed_sources_and_stops_followup(tmp_path):
    s = fresh_store(tmp_path); d = make_doc(s); blocked = threading.Event(); release = threading.Event(); calls=[]
    def http(url, params, timeout):
        calls.append(dict(params))
        if params.get('list') == 'search': return search(['First','Second','Third'])
        if params['titles']=='First': return page('First','First readable evidence')
        blocked.set(); release.wait(WAIT); return page('Second','Late result')
    r=CollectionResearch(s,http_get=http)
    r.start(d['id'],{'expected_revision':d['revision'],'mode':'research','allow_external':True})
    assert blocked.wait(WAIT)
    cur=s.get(d['id']); assert len(cur['research']['result']['sources'])==1
    for operation in [lambda:s.action(d['id'],{'expected_revision':cur['revision'],'action':'confirm_target','label':'Different','confirmed':True}),lambda:s.update(d['id'],{'expected_revision':cur['revision'],'questions':['Changed?']})]:
        with pytest.raises(CollectionError) as e: operation()
        assert e.value.status_code==409
    r.cancel(d['id'],{'expected_revision':cur['revision']});release.set()
    r.pool.shutdown(wait=True)
    out=s.get(d['id'])
    assert out['research']['state']=='cancelled'
    assert [x['title'] for x in out['research']['result']['sources']]==['First']
    assert len(calls)==3


def test_runtime_shutdown_leaves_recoverable_failure(tmp_path):
    s=fresh_store(tmp_path);d=make_doc(s);entered=threading.Event();release=threading.Event()
    def http(url,params,timeout):entered.set();release.wait(WAIT);return search([])
    r=CollectionResearch(s,http_get=http);r.start(d['id'],{'expected_revision':d['revision'],'mode':'research','allow_external':True})
    assert entered.wait(WAIT);r.close();release.set();r.pool.shutdown(wait=True)
    assert s.get(d['id'])['research']['state']=='failed'
