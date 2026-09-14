"""All manual and compatibility entries delegate to canonical ingestion."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from taste_graph_ai.api.routes import pipeline


def test_start_ingestion_uses_daily_entrypoint(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"
    calls = []
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LOGS_DIR", log_dir)
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(pid=42))
    events = SimpleNamespace(append=lambda *args: None)

    result = pipeline._start_ingestion("ingest", events)

    assert result.success is True
    assert calls[0][0][2].endswith("scripts/daily_ingestion.py")
    assert calls[0][0][-2:] == ["--stage", "ingest"]
    assert "--resume" not in calls[0][0]
    assert calls[0][1]["start_new_session"] is True


def test_start_ingestion_reports_spawn_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))
    captured = []
    result = pipeline._start_ingestion("all", SimpleNamespace(append=lambda *args: captured.append(args)))
    assert result.success is False
    assert "boom" in result.message
    assert captured[0][0] == "pipeline.ingestion_start_error"


def test_legacy_cli_crawl_uses_daily_ingestion(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("legacy_pipeline", root / "scripts" / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0))
    assert module.step_crawl(duration_hours=0.5, max_items=12) == 0
    assert calls[0][0][2].endswith("scripts/daily_ingestion.py")
    assert calls[0][0][-10:] == ["--stage", "ingest", "--duration-hours", "0.5",
                                 "--rate-limit", "200", "--max-discovered", "50", "--max", "12"]


def test_legacy_cli_full_uses_daily_ingestion(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("legacy_full_pipeline", root / "scripts" / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0))
    import asyncio
    asyncio.run(module.full_pipeline(crawl_hours=0.5, image_count=6, start_serve=False))
    assert calls[0][0][2].endswith("scripts/daily_ingestion.py")
    assert "--resume" in calls[0][0]


def test_publish_only_preserves_count_and_date(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("legacy_publish_pipeline", root / "scripts" / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0))
    import asyncio
    asyncio.run(module.full_pipeline(image_count=4, skip_crawl=True,
                                     date_str="2026-09-14", start_serve=False))
    assert calls[0][0][2].endswith("scripts/generate_publish_packs.py")
    assert calls[0][0][-6:] == ["--count", "4", "--pack-size", "9", "--date", "2026-09-14"]


def test_legacy_schedulers_use_daily_ingestion(monkeypatch):
    from taste_graph_ai.scheduler import daily_pipeline, scrape_cron
    calls = []
    fake = lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0)
    monkeypatch.setattr(daily_pipeline.subprocess, "run", fake)
    monkeypatch.setattr(scrape_cron.subprocess, "run", fake)
    assert daily_pipeline.run() == 0
    assert scrape_cron.run() == 0
    assert calls[0][0][2].endswith("scripts/daily_ingestion.py")
    assert calls[0][0][-1] == "--resume"
    assert calls[1][0][-2:] == ["--stage", "ingest"]
