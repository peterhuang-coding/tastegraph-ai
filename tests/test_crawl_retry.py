"""Crawler retry state is persistent, bounded and status-aware."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crawl_retry", ROOT / "scripts" / "crawl_loop_6h.py")
crawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl)


def test_transient_failure_retries_with_exponential_backoff():
    state = {}
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    first = crawl.schedule_retry(state, "page", {"url": "https://example.test/a"}, "HTTP 500", now=now)
    second = crawl.schedule_retry(state, "page", {"url": "https://example.test/a"}, "HTTP 500", now=now)
    assert first["next_retry_at"] == (now + timedelta(seconds=crawl.RETRY_BASE_SECONDS)).isoformat()
    assert second["next_retry_at"] == (now + timedelta(seconds=crawl.RETRY_BASE_SECONDS * 2)).isoformat()
    assert crawl.due_retry_items(state, now=now) == []
    assert crawl.due_retry_items(state, now=now + timedelta(hours=1))[0]["url"].endswith("/a")


def test_retry_after_and_terminal_status_use_persistent_cooldown():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    state = {}
    limited = crawl.schedule_retry(state, "limited", {"url": "https://example.test/rate"},
                                   "HTTP 429", retry_after=3600, now=now)
    missing = crawl.schedule_retry(state, "missing", {"url": "https://example.test/gone"},
                                   "HTTP 404", now=now)
    blocked = crawl.schedule_retry(state, "blocked", {"url": "https://example.test/private"},
                                   "403 anti-bot", now=now)
    assert limited["next_retry_at"] == (now + timedelta(hours=1)).isoformat()
    assert missing["cooldown"] is True
    assert missing["next_retry_at"] == (now + timedelta(days=30)).isoformat()
    assert blocked["cooldown"] is True
    assert blocked["next_retry_at"] == (now + timedelta(days=1)).isoformat()


def test_retry_state_round_trips_atomically(tmp_path, monkeypatch):
    path = tmp_path / "retry.json"
    monkeypatch.setattr(crawl, "RETRY_STATE_FILE", path)
    value = {"page": {"item": {"url": "https://example.test/a"}, "attempt_count": 1,
                      "last_error": "timeout", "next_retry_at": "2026-09-14T00:05:00+00:00"}}
    crawl.save_retry_state(value)
    assert crawl.load_retry_state() == value
    assert not path.with_name(path.name + ".tmp").exists()


def test_main_persists_transient_failure_without_marking_processed(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(crawl, "SHARED_DEDUP_FILE", tmp_path / "dedup.json")
    monkeypatch.setattr(crawl, "DISCOVERY_QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(crawl, "RETRY_STATE_FILE", tmp_path / "retry.json")
    monkeypatch.setattr(crawl, "load_seeds", lambda: [{"url": "https://example.test/a", "_seed": True}])
    monkeypatch.setattr(crawl, "load_discovery_queue", lambda: [])
    monkeypatch.setattr(crawl.RateLimiter, "wait", lambda self, domain: None)
    monkeypatch.setattr(crawl, "fetch_page", lambda url: {"_error": "TimeoutError: slow", "_retryable": True})
    monkeypatch.setattr(crawl, "_shutdown", False)
    monkeypatch.setattr(sys, "argv", ["crawl", "--duration-hours", "0.00001"])
    assert crawl.main() == 0
    retry = json.loads((tmp_path / "retry.json").read_text())
    dedup = json.loads((tmp_path / "dedup.json").read_text())
    assert len(retry) == 1
    assert retry[next(iter(retry))]["attempt_count"] == 1
    assert dedup["keys"] == []
