import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_coverage_counts_only_images_in_the_library(tmp_path, monkeypatch):
    from taste_graph_ai.api.routes import health
    db_path = tmp_path / 'fixture.db'
    with sqlite3.connect(db_path) as con:
        con.executescript("CREATE TABLE images (id TEXT); CREATE TABLE image_provenance (image_id TEXT); INSERT INTO images VALUES ('downloaded'); INSERT INTO image_provenance VALUES ('downloaded'), ('not-yet-downloaded');")
    monkeypatch.setattr(health, 'DB_FILE', db_path)
    coverage = health._collect_coverage([])
    assert coverage['provenanceCovered']['percent'] == 100.0


def test_exhausted_retry_keeps_server_retry_after():
    spec = importlib.util.spec_from_file_location('review_crawl', Path(__file__).resolve().parents[1] / 'scripts/crawl_loop_6h.py')
    crawl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawl)
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    state = {'k': {'attempt_count': 3}}
    record = crawl.schedule_retry(state, 'k', {'url': 'https://example.test/image'}, 'HTTP 429', retry_after=172800, now=now)
    assert datetime.fromisoformat(record['next_retry_at']) >= now + timedelta(seconds=172800)
