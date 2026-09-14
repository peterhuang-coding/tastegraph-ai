import asyncio
import json
import sqlite3
from types import SimpleNamespace


def _configure_generator(tmp_path, monkeypatch):
    from scripts import generate_publish_packs as generator
    from taste_graph_ai import config
    from taste_graph_ai.graph.taste_graph import TasteGraph
    from taste_graph_ai.infrastructure.db import connection
    from taste_graph_ai.services import images

    db_path = tmp_path / "data" / "test.db"
    db_path.parent.mkdir()
    for module in (config, connection, images):
        monkeypatch.setattr(module, "DB_FILE", db_path)
    for module in (generator, images):
        monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(generator, "POSTS_DIR", tmp_path / "posts")
    monkeypatch.setattr(generator, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        generator,
        "get_container",
        lambda: SimpleNamespace(taste_graph=TasteGraph()),
    )
    asyncio.run(connection.init_db())
    return generator, db_path


def test_active_candidate_count_releases_rejected_and_submitted_packs(tmp_path):
    from taste_graph_ai.services.candidate_queue import count_active_candidate_packs

    db = sqlite3.connect(tmp_path / "queue.db")
    db.executescript("""
        CREATE TABLE daily_packs (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE pack_editorial (pack_id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE publication_observations (pack_id TEXT, publication_status TEXT);
        INSERT INTO daily_packs VALUES ('active-draft','draft');
        INSERT INTO daily_packs VALUES ('active-selected','selected');
        INSERT INTO daily_packs VALUES ('rejected','draft');
        INSERT INTO daily_packs VALUES ('submitted','selected');
        INSERT INTO daily_packs VALUES ('published','published');
        INSERT INTO pack_editorial VALUES ('rejected','rejected');
        INSERT INTO publication_observations VALUES ('submitted','under_review');
    """)
    assert count_active_candidate_packs(db) == 2
    db.close()


def test_generator_skips_without_creating_date_folder_when_queue_is_full(tmp_path, monkeypatch):
    generator, db_path = _configure_generator(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO daily_packs(id,date,status,created_at) VALUES(?,?,'draft',?)",
            [(f"pack-{i}", "2026-09-14", "2026-09-14") for i in range(5)],
        )

    folder = asyncio.run(generator.generate(
        "2026-09-14", count=5, pack_size=1, skip_queue=True, active_pack_limit=5,
    ))
    assert not folder.exists()
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM daily_packs").fetchone()[0] == 5


def test_generator_only_fills_remaining_queue_slots(tmp_path, monkeypatch):
    generator, db_path = _configure_generator(tmp_path, monkeypatch)
    files = []
    for index in range(2):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(f"candidate-{index}".encode() * 200)
        files.append(path)
    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO daily_packs(id,date,status,created_at) VALUES(?,?,'draft',?)",
            [(f"pack-{i}", "2026-09-13", "2026-09-13") for i in range(4)],
        )
        for index, path in enumerate(files):
            db.execute(
                "INSERT INTO images(id,url,page_url,local_path,status,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    f"image-{index}",
                    f"https://example.test/image-{index}.jpg",
                    f"https://example.test/works/{index}",
                    str(path),
                    "pending",
                    "2026-09-14",
                ),
            )

    folder = asyncio.run(generator.generate(
        "2026-09-14", count=5, pack_size=1, skip_queue=True, active_pack_limit=5,
    ))
    manifests = list(folder.glob("*/curation.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["queue_budget"] == {
        "active_before": 4,
        "limit": 5,
    }
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM daily_packs").fetchone()[0] == 5
