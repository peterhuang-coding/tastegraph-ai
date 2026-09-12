"""Offline crawler fixtures and isolated SQLite regressions (no network/model calls)."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crawl = load_script("crawl_loop_6h")
ingest = load_script("daily_ingestion")
migrations = load_script("migrations")

HTML = """<html><head><title>A chair study</title>
<link rel="canonical" href="/works/chair-study">
<meta name="author" content="Page editor"><meta property="og:type" content="article">
<meta property="article:published_time" content="2026-09-10">
</head><body><header><img src="/static/site-logo.png" alt="Site logo" width="200"></header>
<article><img src="/media/unlabelled.jpg" alt="" width="800">
<figure><img src="/media/chair.jpg" alt="Oak chair in the studio" width="800" data-credit="Photographer A">
<figcaption>Chair study, photographed by Photographer A.</figcaption></figure>
<img src="relative-study.jpg" alt="An independent study" width="800">
<img src="/media/catalog/product-hero.jpg" alt="A product study" width="800">
<img src="/media/logo-design.jpg" alt="Identity design work" width="800">
<a href="/works/next-study">Next study</a></article></body></html>"""


def fixture_fetch(monkeypatch, html=HTML):
    client = SimpleNamespace(get=lambda url: SimpleNamespace(
        status_code=200, text=html, url="https://design.example/works/chair-study?ref=home"))
    monkeypatch.setattr(crawl, "_get_http", lambda: client)
    monkeypatch.setattr(crawl, "_rotate_ua", lambda: None)
    return crawl.fetch_page("https://design.example/redirect")


def run_one_cycle(monkeypatch, tmp_path, seeds, queue, metadata):
    monkeypatch.setattr(crawl, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(crawl, "SHARED_DEDUP_FILE", tmp_path / "dedup.json")
    monkeypatch.setattr(crawl, "DISCOVERY_QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(crawl, "load_seeds", lambda: seeds)
    monkeypatch.setattr(crawl, "load_discovery_queue", lambda: queue)
    monkeypatch.setattr(crawl.RateLimiter, "wait", lambda self, domain: None)
    monkeypatch.setattr(crawl, "_shutdown", False)
    fetched = []

    def fetch(url):
        fetched.append(url)
        crawl._shutdown = True
        return metadata

    monkeypatch.setattr(crawl, "fetch_page", fetch)
    monkeypatch.setattr(sys, "argv", ["crawl", "--duration-hours", "0.01"])
    assert crawl.main() == 0
    records = [json.loads(line) for p in tmp_path.glob("loop_*/output.jsonl")
               for line in p.read_text().splitlines()]
    return fetched, records, json.loads((tmp_path / "queue.json").read_text())


def test_fixture_keeps_explicit_image_context_and_canonical_page(monkeypatch):
    meta = fixture_fetch(monkeypatch)
    chair = next(im for im in meta["images"] if im["src"].endswith("chair.jpg"))
    assert chair.get("caption") == "Chair study, photographed by Photographer A."
    assert chair.get("image_author") == "Photographer A"
    assert meta.get("page_url") == "https://design.example/works/chair-study?ref=home"
    assert meta.get("canonical_url") == "https://design.example/works/chair-study"
    assert meta.get("page_kind") == "detail"
    assert meta.get("page_published_at") == "2026-09-10"
    assert not chair.get("original_date_text")  # Publication is not a photo/object date.


def test_fixture_excludes_chrome_without_excluding_editorial_products(monkeypatch):
    meta = fixture_fetch(monkeypatch)
    urls = [im["src"] for im in meta["images"]]
    assert not any("site-logo" in url for url in urls)
    assert "https://design.example/works/relative-study.jpg" in urls
    assert any("product-hero" in url for url in urls)
    assert any("logo-design" in url for url in urls)


def test_main_retains_each_images_own_alt_beyond_first_five(monkeypatch, tmp_path):
    images = [{"src": f"https://media.example/{i}.jpg", "alt": "" if i == 0 else f"Image {i}"}
              for i in range(8)]
    metadata = {"images": images, "alt_texts": ["wrong filtered alt"], "child_links": [],
                "canonical_url": "https://design.example/works/one", "page_kind": "detail"}
    _, records, _ = run_one_cycle(monkeypatch, tmp_path,
        [{"url": "https://design.example/works/one", "_seed": True}], [], metadata)
    assert [im["alt"] for im in records[0]["images"]] == [im["alt"] for im in images]
    assert records[0].get("canonical_url") == metadata["canonical_url"]


def test_queued_details_precede_homepage_refresh_and_unprocessed_queue_survives(monkeypatch, tmp_path):
    home = {"url": "https://design.example/", "_seed": True}
    queued = [{"url": f"https://design.example/works/{slug}", "parent_url": home["url"]}
              for slug in ("one", "two")]
    fetched, _, remaining = run_one_cycle(monkeypatch, tmp_path, [home], queued,
                                         {"images": [], "child_links": []})
    assert fetched == [queued[0]["url"]]
    assert queued[1]["url"] in [item["url"] for item in remaining]


@pytest.fixture
def con(tmp_path):
    db = sqlite3.connect(tmp_path / "fixture.db")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""CREATE TABLE sources (id TEXT PRIMARY KEY, url TEXT);
    CREATE TABLE images (id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id),
      url TEXT, page_url TEXT, local_path TEXT, thumbnail_path TEXT, keywords_json TEXT,
      graph_score REAL, visual_score REAL, final_score REAL, status TEXT, created_at TEXT,
      content_hash TEXT);
    CREATE TABLE daily_packs (id TEXT PRIMARY KEY);""")
    assert not [m for m in migrations.apply_migrations(db) if m["status"] == "failed"]
    db.execute("INSERT INTO sources VALUES ('source-design', 'https://www.design.example/archive')")
    db.commit()
    yield db
    db.close()


def persist_record(con, tmp_path, monkeypatch, record):
    loop = tmp_path / "loop-fixture"
    loop.mkdir(exist_ok=True)
    (loop / "output.jsonl").write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(ingest, "RUNS_DIR", tmp_path)
    return ingest.stage_persist(con, con.execute("SELECT id,url FROM sources").fetchall(),
                                {"id": "run-fixture"}, [str(loop)], {})


def test_source_resolution_uses_domain_without_url_prefix_spoofing():
    sources = [("generic", "https://www.design.example/archive"),
               ("work", "https://design.example/works")]
    assert ingest.resolve_source("https://design.example/works/chair", sources) == "work"
    assert ingest.resolve_source("http://design.example/article/chair", sources) is None
    assert ingest.resolve_source("https://design.example/article/chair", sources[:1]) == "generic"
    assert ingest.resolve_source("https://www.design.example.evil.test/archive", sources) is None
    assert ingest.resolve_source("https://unknown.example/chair", sources) is None


def test_persist_provenance_before_download_is_additive_and_never_invents_dates(con, tmp_path, monkeypatch):
    record = {"status": "fetched", "url": "https://design.example/works/chair?ref=home",
        "parent_url": "https://design.example/", "canonical_url": "https://design.example/works/chair",
        "page_kind": "detail", "page_title": "Chair study", "page_author": "Page editor",
        "page_published_at": "2026-09-10", "collected_at": "2026-09-12T12:00:00Z",
        "images": [{"url": "https://media.example/1995/product.jpg", "alt": "Chair study",
                    "caption": "Studio view", "image_author": "Photographer A"}]}
    assert persist_record(con, tmp_path, monkeypatch, record)["discovered"] == 1
    assert persist_record(con, tmp_path, monkeypatch, record)["discovered"] == 0
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "image_provenance" in tables
    cur = con.execute("SELECT * FROM image_provenance")
    rows = [dict(zip([c[0] for c in cur.description], row)) for row in cur]
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"] == "source-design"
    assert row["discovery_url"] == "https://design.example/"
    assert row["canonical_url"] == record["canonical_url"]
    assert row["alt_text"] == "Chair study" and row["caption"] == "Studio view"
    assert row["page_published_at"] == "2026-09-10"
    assert row["original_date_text"] == row["date_evidence"] == ""
    assert con.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0


def test_legacy_unpaired_alts_are_not_reassigned_and_product_media_survives(con, tmp_path, monkeypatch):
    record = {"status": "fetched", "url": "https://design.example/works/chair",
        "image_urls": ["https://media.example/site-logo.png", "https://media.example/product-hero.jpg",
                       "https://media.example/logo-design.jpg"], "alt_texts": ["Someone else's alt"]}
    out = persist_record(con, tmp_path, monkeypatch, record)
    assert out["discovered"] == 2
    assert con.execute("SELECT DISTINCT alt_text FROM ingestion_items").fetchall() == [("",)]


def test_stage_download_finishes_job_but_does_not_mark_full_daily_job_succeeded(con, tmp_path, monkeypatch):
    db_path = Path(con.execute("PRAGMA database_list").fetchone()[2])
    monkeypatch.setattr(ingest, "DB_PATH", db_path)
    monkeypatch.setattr(ingest, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ingest, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(ingest, "LOCK_PATH", tmp_path / "ingestion.lock")
    monkeypatch.setattr(ingest, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(ingest, "MIN_FREE_BYTES", 0)
    monkeypatch.setitem(sys.modules, "migrations", migrations)
    monkeypatch.setattr(sys, "argv", ["daily_ingestion", "--stage", "download", "--max", "0"])
    assert ingest.main() == 0
    job = con.execute("SELECT status,finished_at,summary_json,job_name FROM job_runs").fetchone()
    assert job[0] in ("succeeded", "partial") and job[1]
    assert json.loads(job[2])["requested_stage"] == "download"
    assert not ingest.job_succeeded_today(con, ingest.datetime.now().strftime("%Y-%m-%d"))


def test_403_does_not_retry_or_rotate_after_refusal(monkeypatch):
    calls = []
    client = SimpleNamespace(get=lambda url: (calls.append(url) or SimpleNamespace(status_code=403)))
    monkeypatch.setattr(crawl, "_get_http", lambda: client)
    monkeypatch.setattr(crawl.random, "random", lambda: 1)
    assert crawl.fetch_page("https://design.example/work")["_error"] == "403 anti-bot"
    assert len(calls) == 1


def test_download_links_new_and_content_duplicate_provenance_without_orphan_sources(con, tmp_path, monkeypatch):
    image_dir = tmp_path / "cached-images"
    image_dir.mkdir()
    monkeypatch.setattr(ingest, "IMAGES_DIR", image_dir)
    monkeypatch.setattr(ingest.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ingest.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Network forbidden"))
    record = {"status": "fetched", "url": "https://design.example/works/chair",
              "images": [{"url": "https://media.example/chair.jpg", "alt": "Chair"}]}
    persist_record(con, tmp_path, monkeypatch, record)
    uid = ingest._md5(ingest._norm_url(record["images"][0]["url"]))
    cached = b"fixture-image-content" * 200
    (image_dir / f"{uid}.jpg").write_bytes(cached)
    con.execute("UPDATE ingestion_items SET source_id='historical-orphan'")
    con.commit()
    assert ingest.stage_download(con, {"id": "run-fixture"}, 10)["inserted"] == 1
    assert con.execute("SELECT source_id FROM images WHERE id=?", (uid,)).fetchone()[0] == "source-design"
    assert con.execute("SELECT p.image_id FROM image_provenance p JOIN images i ON i.id=p.image_id").fetchall() == [(uid,)]

    record["url"] = "https://design.example/works/another-view"
    record["images"][0]["url"] = "https://media.example/duplicate-content.jpg"
    persist_record(con, tmp_path, monkeypatch, record)
    duplicate_uid = ingest._md5(ingest._norm_url(record["images"][0]["url"]))
    (image_dir / f"{duplicate_uid}.jpg").write_bytes(cached)
    assert ingest.stage_download(con, {"id": "run-fixture"}, 10)["inserted"] == 0
    assert con.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 1
    assert con.execute("SELECT image_id FROM image_provenance").fetchall() == [(uid,), (uid,)]
    persist_record(con, tmp_path, monkeypatch, record)
    assert con.execute("SELECT DISTINCT image_id FROM image_provenance").fetchall() == [(uid,)]


def test_only_explicit_figure_creation_date_is_preserved(monkeypatch):
    html = HTML.replace('<figcaption>', '<time itemprop="dateCreated" datetime="1998">1998</time><figcaption>')
    meta = fixture_fetch(monkeypatch, html)
    chair = next(im for im in meta["images"] if im["src"].endswith("chair.jpg"))
    unlabelled = next(im for im in meta["images"] if im["src"].endswith("unlabelled.jpg"))
    assert chair["original_date_text"] == "1998" and chair["date_evidence"]
    assert unlabelled["original_date_text"] == unlabelled["date_evidence"] == ""


def test_page_hints_and_asset_filter_keep_content_images():
    from taste_graph_ai.services.provenance import classify_page, is_site_asset
    assert classify_page("https://design.example/") == "entry"
    assert classify_page("https://design.example/projects") == "entry"
    assert classify_page("https://design.example/category/furniture") == "entry"
    assert classify_page("https://design.example/works/chair") == "detail"
    assert classify_page("") == "unknown"
    assert is_site_asset("https://design.example/static/chrome/menu.png")
    assert is_site_asset("https://design.example/site-logo.png?width=400")
    for image in ("product-hero.jpg", "media/ogp-photo.jpg", "logo-design.jpg", "iconic-chair.jpg"):
        assert not is_site_asset("https://design.example/" + image)


def test_download_preserves_original_webp_bytes(con, tmp_path, monkeypatch):
    image_dir=tmp_path/'originals'; image_dir.mkdir()
    monkeypatch.setattr(ingest,'IMAGES_DIR',image_dir)
    monkeypatch.setattr(ingest.time,'sleep',lambda _:None)
    monkeypatch.setattr(ingest.urllib.request,'urlopen',lambda *a,**k:pytest.fail('Network forbidden'))
    monkeypatch.setattr(ingest.subprocess,'run',lambda *a,**k:pytest.fail('Original must not be transcoded'))
    record={'status':'fetched','url':'https://design.example/works/chair','images':[{'url':'https://media.example/chair.webp','alt':'Chair'}]}
    persist_record(con,tmp_path,monkeypatch,record)
    uid=ingest._md5(ingest._norm_url(record['images'][0]['url']))
    content=b'original-webp-fixture'*200
    path=image_dir/f'{uid}.webp'; path.write_bytes(content)
    assert ingest.stage_download(con,{'id':'run-fixture'},1)['inserted']==1
    assert path.read_bytes()==content
    assert con.execute('SELECT local_path FROM images WHERE id=?',(uid,)).fetchone()[0]==str(path)
