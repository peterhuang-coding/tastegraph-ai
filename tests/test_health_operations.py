import json
import sqlite3
from datetime import date


def _create_health_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE sources (id TEXT PRIMARY KEY);
        CREATE TABLE images (
            id TEXT PRIMARY KEY, source_id TEXT, content_hash TEXT
        );
        CREATE TABLE daily_packs (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE pack_editorial (pack_id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE publication_observations (pack_id TEXT, publication_status TEXT);
        CREATE TABLE ingestion_items (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE image_provenance (image_id TEXT);
        CREATE TABLE image_editorial (image_id TEXT, annotation_json TEXT);
        CREATE TABLE job_runs (
            id TEXT PRIMARY KEY, job_name TEXT, scheduled_for TEXT,
            scheduled_date TEXT, started_at TEXT, finished_at TEXT,
            status TEXT, summary_json TEXT, error_summary TEXT, log_path TEXT
        );
        CREATE TABLE crawl_runs (
            id TEXT PRIMARY KEY, scheduled_for TEXT, started_at TEXT,
            finished_at TEXT, status TEXT, pages_attempted INTEGER,
            pages_fetched INTEGER, pages_failed INTEGER,
            images_discovered INTEGER, images_downloaded INTEGER,
            backlog_count INTEGER, error_summary TEXT
        );
        INSERT INTO sources VALUES ('source-1');
        INSERT INTO images VALUES ('image-1','source-1','abc');
        INSERT INTO images VALUES ('image-2',NULL,'');
        INSERT INTO image_provenance VALUES ('image-1');
        INSERT INTO image_editorial VALUES (
            'image-1','{"source_verified": true}'
        );
        INSERT INTO daily_packs VALUES ('active','draft');
        INSERT INTO daily_packs VALUES ('submitted','selected');
        INSERT INTO publication_observations VALUES ('submitted','under_review');
        INSERT INTO ingestion_items VALUES ('pending','discovered');
        INSERT INTO ingestion_items VALUES ('failed','failed');
    """)
    today = date.today().isoformat()
    db.execute(
        "INSERT INTO job_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "job-1", "daily_ingestion", f"{today}T03:00:00+08:00", today,
            f"{today}T03:00:01+08:00", f"{today}T03:05:00+08:00",
            "succeeded", '{"images_downloaded": 7}', "", "/private/logs/job.log",
        ),
    )
    db.execute(
        "INSERT INTO crawl_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "crawl-1", f"{today}T03:00:00+08:00", f"{today}T03:00:01+08:00",
            f"{today}T03:05:00+08:00", "succeeded", 10, 9, 1, 8, 7, 2, "",
        ),
    )
    db.commit()
    db.close()


def test_health_collects_operational_evidence_and_coverage(tmp_path, monkeypatch):
    from taste_graph_ai.api.routes import health

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "taste_graph.db"
    _create_health_db(db_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "crawl_retry_state.json").write_text(json.dumps({"a": {}, "b": {}}))
    backups = data_dir / "backups"
    backups.mkdir()
    (backups / "latest_backup.json").write_text(json.dumps({
        "ok": True,
        "backup": "/private/backups/taste_graph-1.db",
        "backup_bytes": 123,
        "integrity": "ok",
        "counts_match": True,
        "finished_at": "2026-09-14T04:00:00+08:00",
    }))
    monkeypatch.setattr(health, "BASE_DIR", tmp_path)
    monkeypatch.setattr(health, "DATA_DIR", data_dir)
    monkeypatch.setattr(health, "DB_FILE", db_path)

    errors = []
    operations = health._collect_operations(errors)
    coverage = health._collect_coverage(errors)

    assert errors == []
    assert operations["todayStatus"]["status"] == "succeeded"
    assert operations["latestCrawlRun"]["images_downloaded"] == 7
    assert operations["backlogCount"] == 2
    assert operations["activeCandidatePacks"] == 1
    assert operations["retryQueueCount"] == 2
    assert operations["lastBackup"]["backupFile"] == "taste_graph-1.db"
    assert "/private" not in json.dumps(operations)
    assert coverage["totalImages"] == 2
    assert coverage["sourceResolved"]["percent"] == 50.0
    assert coverage["contentHashed"]["percent"] == 50.0
    assert coverage["provenanceCovered"]["percent"] == 50.0
    assert coverage["editorialAnnotated"]["percent"] == 50.0
    assert coverage["sourceVerified"]["percent"] == 50.0
    assert coverage["activePacks"] == 1
    assert coverage["publicationObserved"] == 1


def test_health_missing_database_is_read_only(tmp_path, monkeypatch):
    from taste_graph_ai.api.routes import health

    data_dir = tmp_path / "data"
    db_path = data_dir / "missing.db"
    monkeypatch.setattr(health, "BASE_DIR", tmp_path)
    monkeypatch.setattr(health, "DATA_DIR", data_dir)
    monkeypatch.setattr(health, "DB_FILE", db_path)

    errors = []
    database = health._collect_database(errors)
    operations = health._collect_operations(errors)
    coverage = health._collect_coverage(errors)

    assert not db_path.exists()
    assert database["path"] == "data/missing.db"
    assert operations["todayStatus"]["status"] == "not_run"
    assert coverage["totalImages"] == 0
