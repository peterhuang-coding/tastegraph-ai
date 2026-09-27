import json, shutil, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from .collections import CollectionError

TERMINAL = {"awaiting_review", "failed", "cancelled"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _questions(doc):
    q = doc.get("research_questions") or doc.get("questions") or []
    if isinstance(q, str):
        q = [q]
    out, seen = [], set()
    for x in q if isinstance(q, list) else []:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s); out.append(s)
    if not out:
        raise CollectionError("at least one owner-reviewed question is required", 400)
    if len(out) > 3:
        raise CollectionError("at most three questions are allowed", 400)
    return out


def _photos(doc, ids):
    if not isinstance(ids, list) or not ids:
        raise CollectionError("select one to four photos", 400)
    photos = {str(p.get("id")): p for p in doc.get("photos", []) if isinstance(p, dict)}
    chosen = []
    for x in ids:
        pid = str(x or "").strip()
        if pid not in photos:
            raise CollectionError("unknown photo id: " + pid, 400)
        if pid in chosen:
            raise CollectionError("photo ids must be unique", 400)
        chosen.append(pid)
    if len(chosen) > 4:
        raise CollectionError("at most four photos are allowed", 400)
    return chosen


def default_ocr(path, timeout):
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract is not installed")
    timeout = max(0.1, min(float(timeout), 20.0))
    deadline = time.monotonic() + timeout
    langs = "eng"
    try:
        p = subprocess.run([exe, "--list-langs"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, shell=False)
        available = (p.stdout or "") + (p.stderr or "")
        if "chi_sim" in available and "eng" in available:
            langs = "eng+chi_sim"
    except Exception:
        pass
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise RuntimeError("OCR deadline exceeded")
    p = subprocess.run([exe, str(path), "stdout", "-l", langs], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, shell=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "ocr failed")[:300])
    return (p.stdout or "")[:20000]


def default_http_get(url, params, timeout):
    headers = {"User-Agent": "CollectionResearch/1.0 (private local collection; owner-operated background lookup)"}
    with httpx.stream("GET", url, params=params, timeout=min(float(timeout), 10.0), headers=headers, follow_redirects=False) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > 2_000_000:
                raise RuntimeError("response body exceeded size limit")
        return json.loads(raw)



class CollectionResearch:
    def __init__(self, store, http_get=None, ocr=None):
        self.store = store
        self.http_get = http_get or default_http_get
        self.ocr = ocr or default_ocr
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="collection-research")
        self.lock = threading.RLock()
        self.active = {}
        self._events = {}
        self.closed = False
        self.recovered = False

    def capabilities(self):
        reason = None
        if shutil.which("tesseract") is None:
            reason = "Tesseract is not installed; local OCR unavailable"
        return {"identify": {"available": reason is None, "reason": reason},
                "research": {"available": True, "scope": "公开百科背景检索", "max_questions": 3, "max_pages": 3},
                "budget": {"seconds": 90, "max_photos": 4}}

    def recover_interrupted(self):
        with self.lock:
            if self.recovered:
                return []
            self.recovered = True
            out = []
            for summary in self.store.list_items():
                doc = self.store.get(summary["id"])
                run = doc.get("research") if isinstance(doc.get("research"), dict) else {}
                if run.get("state") == "running":
                    out.append(self.store.recover_interrupted(doc["id"], "interrupted by runtime restart"))
            return out

    def start(self, item_id, payload):
        payload = payload or {}
        mode = payload.get("mode")
        if mode not in ("identify", "research"):
            raise CollectionError("mode must be identify or research", 400)
        rev = payload.get("expected_revision")
        if not isinstance(rev, int) or isinstance(rev, bool):
            raise CollectionError("expected_revision must be an integer", 400)
        doc = self.store.get(item_id)
        if doc.get("revision") != rev:
            raise CollectionError("stale item revision", 409)
        snapshot = {"mode": mode}
        if mode == "identify":
            snapshot["photo_ids"] = _photos(doc, payload.get("photo_ids"))
        else:
            if payload.get("allow_external") is not True:
                raise CollectionError("explicit allow_external consent is required", 400)
            lang = payload.get("language", "en")
            if lang not in ("en", "zh"):
                raise CollectionError("language must be en or zh", 400)
            target = doc.get("target") if isinstance(doc.get("target"), dict) else {}
            label = str(target.get("label") or "").strip()
            if not label or target.get("confirmed") is not True:
                raise CollectionError("a confirmed target label is required", 400)
            snapshot.update({"target_label": label, "questions": _questions(doc), "language": lang, "allow_external": True})
        with self.lock:
            if self.closed:
                raise CollectionError("research runtime is closed", 503)
            if len(self.active) >= 2:
                raise CollectionError("research capacity is full", 503)
            if item_id in self.active:
                raise CollectionError("research already running for this object", 409)
            run_id = self.store.begin_research(item_id, mode, expected_revision=rev)
            stop = threading.Event()
            self.active[item_id] = run_id
            self._events[run_id] = stop
            try:
                fut = self.pool.submit(self._run, item_id, run_id, mode, snapshot, stop)
            except Exception:
                self.active.pop(item_id, None)
                self._events.pop(run_id, None)
                error = {"mode": mode, "inputs": snapshot, "observations": [], "sources": [], "gaps": [], "errors": [{"stage": "dispatch", "error": "could not start worker"}], "limitations": "no research was performed"}
                self.store.finish_research(item_id, run_id, error, "dispatch failed")
                raise CollectionError("could not dispatch research", 503)
            fut.add_done_callback(lambda f, i=item_id, r=run_id, s=stop: self._after(i, r, s, f))
        return self.store.get(item_id)

    def cancel(self, item_id, payload=None):
        payload = dict(payload or {})
        payload["action"] = "cancel_research"
        doc = self.store.action(item_id, payload)
        run = doc.get("research") if isinstance(doc.get("research"), dict) else {}
        rid = run.get("id")
        event = None
        with self.lock:
            stop = self.active.get(item_id)
            if stop == rid and isinstance(stop, str):
                event = self._events.get(rid)
        if isinstance(event, threading.Event):
            event.set()
        return doc

    def close(self):
        with self.lock:
            self.closed = True
            for event in self._events.values():
                event.set()
            for item_id in list(self.active):
                self.store.recover_interrupted(item_id, "服务已停止；已有成果保留，可手动重试")
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _after(self, item_id, run_id, stop, fut):
        with self.lock:
            self._events.pop(run_id, None)
        if fut.cancelled():
            stop.set()
            with self.lock:
                self.active.pop(item_id, None) if self.active.get(item_id) == run_id else None
            return
        exc = fut.exception()
        if exc:
            result = {"mode": "unknown", "inputs": {}, "observations": [], "sources": [], "gaps": [], "errors": [{"stage": "worker", "error": str(exc)[:500]}]}
            with self.lock:
                self.active.pop(item_id, None) if self.active.get(item_id) == run_id else None
            try:
                self.store.finish_research(item_id, run_id, result, "research worker failed")
            except Exception:
                pass
        else:
            with self.lock:
                self.active.pop(item_id, None) if self.active.get(item_id) == run_id else None

    def _cancelled(self, event):
        return event.is_set()

    def _phase(self, item_id, rid, phase, event):
        if event.is_set():
            raise RuntimeError("cancelled")
        self.store.research_phase(item_id, rid, phase)

    def _finish(self, item_id, rid, result, error, event):
        result = self._bound(result)
        if event.is_set():
            try:
                self.store.finish_research(item_id, rid, result, "cancelled")
            except Exception:
                pass
            return
        try:
            self.store.finish_research(item_id, rid, result, error)
        except CollectionError as exc:
            if exc.status_code != 409:
                raise

    def _bound(self, result):
        result["sources"] = result.get("sources", [])[:3]
        result["errors"] = result.get("errors", [])[:10]
        result["observations"] = result.get("observations", [])[:4]
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > 262144:
            result["gaps"] = (result.get("gaps", []) + ["result exceeded size limit and was bounded"])[:20]
            for s in result["sources"]:
                if "excerpt" in s:
                    s["excerpt"] = str(s["excerpt"])[:500]
        return result

    def _run(self, item_id, run_id, mode, snapshot, event):
        result = {"mode": mode, "inputs": snapshot, "observations": [], "sources": [], "gaps": [], "errors": []}
        deadline = time.monotonic() + 90
        try:
            if mode == "identify":
                self._identify(item_id, run_id, snapshot, result, event, deadline)
            else:
                self._research(item_id, run_id, snapshot, result, event, deadline)
            self._finish(item_id, run_id, result, None, event)
        except Exception as e:
            msg = str(e)[:500]
            if not any(x.get("error") == msg for x in result["errors"] if isinstance(x, dict)):
                result["errors"].append({"stage": mode, "error": msg})
            self._finish(item_id, run_id, result, msg if not event.is_set() else "cancelled", event)

    def _identify(self, item_id, rid, snap, result, event, deadline):
        for pid in snap["photo_ids"]:
            if event.is_set() or time.monotonic() >= deadline:
                raise RuntimeError("cancelled" if event.is_set() else "research deadline exceeded")
            self._phase(item_id, rid, "ocr:" + pid, event)
            remaining = min(20.0, max(1.0, deadline - time.monotonic()))
            try:
                path = self.store.photo_path(item_id, pid)
                text = self.ocr(path, timeout=remaining) or ""
                result["observations"].append({"photo_id": pid, "recognized_text": str(text)[:10000], "candidate_manufacturers": [], "confidence": "tentative", "limitations": "OCR text may be wrong; not model, version, or authenticity evidence"})
                self.store.research_phase(item_id, rid, "ocr:" + pid, result=result)
                if not str(text).strip():
                    result["gaps"].append({"photo_id": pid, "question": "Please reshoot bottom markings and packaging in sharp, even lighting."})
            except Exception as e:
                result["errors"].append({"stage": "ocr", "photo_id": pid, "error": str(e)[:500]})
                raise
        result["limitations"] = "Local OCR only; selected private photos were not sent externally. Empty OCR is evidence of no readable marking, not proof of origin."

    def _research(self, item_id, rid, snap, result, event, deadline):
        host = "en.wikipedia.org" if snap["language"] == "en" else "zh.wikipedia.org"
        base = "https://" + host + "/w/api.php"
        titles, seen, requests = [], set(), 0
        if event.is_set() or time.monotonic() >= deadline:
            raise RuntimeError("cancelled")
        self._phase(item_id, rid, "search", event)
        params = {"action": "query", "list": "search", "srsearch": snap["target_label"], "srlimit": "3", "format": "json", "formatversion": "2"}
        try:
            data = self.http_get(base, params, timeout=min(10.0, deadline - time.monotonic()))
            requests += 1
            pages = ((data or {}).get("query") or {}).get("search") or []
        except Exception as e:
            result["errors"].append({"stage": "search", "url": base, "error": str(e)[:500]})
            raise
        for p in pages:
            title = str((p or {}).get("title", "")).strip()
            if title and title not in seen:
                seen.add(title); titles.append(title)
        for title in titles[:3]:
            if event.is_set() or time.monotonic() >= deadline:
                raise RuntimeError("cancelled" if event.is_set() else "research deadline exceeded")
            if requests >= 6:
                break
            self._phase(item_id, rid, "extract:" + title, event)
            params = {"action": "query", "prop": "extracts", "explaintext": "1", "exchars": "10000", "titles": title, "format": "json", "formatversion": "2"}
            try:
                data = self.http_get(base, params, timeout=min(10.0, deadline - time.monotonic())) or {}
                requests += 1
                pages2 = ((data.get("query") or {}).get("pages") or [])
                text = (pages2[0] or {}).get("extract", "") if pages2 else ""
                if not str(text).strip():
                    result["errors"].append({"stage": "extract", "title": title, "error": "empty readable text"})
                    continue
                excerpt = str(text).replace("\n", " ")[:500]
                result["sources"].append({"title": title, "url": "https://" + host + "/wiki/" + quote(title.replace(" ", "_")), "accessed_at": _now(), "excerpt": excerpt, "excerpt_note": "exact truncated quote from retrieved page text", "scope": "background only", "limitations": "not evidence for this specimen version/production/authenticity", "publication_year": None, "photography_year": None, "object_year": None})
                self.store.research_phase(item_id, rid, "extract:" + title, result=result)
            except Exception as e:
                result["errors"].append({"stage": "extract", "title": title, "url": base, "error": str(e)[:500]})
                raise
        for q in snap["questions"]:
            result["gaps"].append({"question": q, "status": "unanswered", "reason": "encyclopedia background is not an answer about this specimen"})
        if not result["sources"]:
            result["gaps"].append("No readable public encyclopedia background page found; add brand catalog or museum evidence manually in the claim editor.")
        result["limitations"] = "公开百科背景检索 only; only the confirmed target label was sent; reviewed questions remain unanswered local scope notes. No photos, captions, known_info, story, private notes, or draft were sent."
