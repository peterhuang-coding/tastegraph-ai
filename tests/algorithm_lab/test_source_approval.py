import asyncio
import json
from types import SimpleNamespace

import pytest

from taste_graph_ai.domain.enums import SourceStatus
from taste_graph_ai.services import source_sync


class FakeEventLog:
    def __init__(self):
        self.events = []

    def append(self, event_type, payload):
        self.events.append((event_type, payload))


class FakeSourceRepo:
    def __init__(self, existing=None):
        self.by_url = {}
        self.saved = []
        for source in existing or []:
            self.by_url[source.url] = source

    async def find_by_url(self, url):
        return self.by_url.get(url)

    async def save(self, source):
        self.saved.append(source)
        self.by_url[source.url] = source


SEED_URL = "https://example.com/lookbook"
SEED = {
    "lookbook_images": [
        {
            "url": SEED_URL,
            "name": "Example Lookbook",
            "why": "Test seed source",
        }
    ]
}


def seed_base_dir(tmp_path, monkeypatch):
    (tmp_path / "link_sources.json").write_text(
        json.dumps(SEED), encoding="utf-8"
    )
    monkeypatch.setattr(source_sync, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        source_sync,
        "Source",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )


def existing_source(status):
    return SimpleNamespace(
        id="existing123",
        url=SEED_URL,
        name="Example Lookbook",
        status=status,
        reviewed_at=None,
    )


def run_sync(repo, events):
    return asyncio.run(source_sync.sync_seed_sources(repo, events))


def test_new_source_remains_pending_on_first_sync(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    repo = FakeSourceRepo()
    events = FakeEventLog()

    count = run_sync(repo, events)

    assert count == 1
    saved = repo.saved[0]
    assert saved.url == SEED_URL
    assert saved.status == SourceStatus.PENDING
    assert saved.reviewed_at is None
    assert [event[0] for event in events.events] == ["source.synced"]


@pytest.mark.xfail(
    strict=True,
    reason="Repeating seed sync must not approve a source still awaiting manual review.",
)
def test_new_source_remains_pending_on_second_sync(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    first_repo = FakeSourceRepo()
    first_events = FakeEventLog()

    first_count = run_sync(first_repo, first_events)
    created = first_repo.saved[0]

    second_repo = FakeSourceRepo(existing=[created])
    second_events = FakeEventLog()
    second_count = run_sync(second_repo, second_events)

    assert first_count == 1
    try:
        assert second_count == 0
        assert created.status == SourceStatus.PENDING
        assert created.reviewed_at is None
        assert second_repo.saved == []
        assert second_events.events == []
    except AssertionError:
        raise
    else:
        pytest.fail("Expected current pending-on-repeat violation did not occur")


@pytest.mark.xfail(
    strict=True,
    reason="A pending seed source must retain manual-review state; sync must not approve it.",
)
def test_existing_pending_seed_source_is_not_auto_approved(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    source = existing_source(SourceStatus.PENDING)
    repo = FakeSourceRepo(existing=[source])
    events = FakeEventLog()

    count = run_sync(repo, events)

    try:
        assert count == 0
        assert source.status == SourceStatus.PENDING
        assert source.reviewed_at is None
        assert repo.saved == []
        assert events.events == []
    except AssertionError:
        raise
    else:
        pytest.fail("Expected current pending auto-approval violation did not occur")


@pytest.mark.xfail(
    strict=True,
    reason="A rejected source is an explicit denial; seed sync must not reverse it.",
)
def test_existing_rejected_seed_source_is_not_auto_approved(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    source = existing_source(SourceStatus.REJECTED)
    repo = FakeSourceRepo(existing=[source])
    events = FakeEventLog()

    count = run_sync(repo, events)

    try:
        assert count == 0
        assert source.status == SourceStatus.REJECTED
        assert source.reviewed_at is None
        assert repo.saved == []
        assert events.events == []
    except AssertionError:
        raise
    else:
        pytest.fail("Expected current rejected auto-approval violation did not occur")


@pytest.mark.xfail(
    strict=True,
    reason="A deferred source must remain deferred until separately reviewed and approved.",
)
def test_existing_deferred_seed_source_is_not_auto_approved(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    source = existing_source(SourceStatus.DEFERRED)
    repo = FakeSourceRepo(existing=[source])
    events = FakeEventLog()

    count = run_sync(repo, events)

    try:
        assert count == 0
        assert source.status == SourceStatus.DEFERRED
        assert source.reviewed_at is None
        assert repo.saved == []
        assert events.events == []
    except AssertionError:
        raise
    else:
        pytest.fail("Expected current deferred auto-approval violation did not occur")


@pytest.mark.xfail(
    strict=True,
    reason="An auto-approval event for a rejected source must not falsely report previous_status as approved.",
)
def test_rejected_auto_approval_event_cannot_falsely_say_approved(
    tmp_path, monkeypatch
):
    seed_base_dir(tmp_path, monkeypatch)
    source = existing_source(SourceStatus.REJECTED)
    repo = FakeSourceRepo(existing=[source])
    events = FakeEventLog()

    run_sync(repo, events)

    auto_events = [
        payload
        for event_type, payload in events.events
        if event_type == "source.auto_approved"
    ]
    try:
        assert auto_events
        assert auto_events[0]["previous_status"] == SourceStatus.REJECTED.value
    except AssertionError:
        raise
    else:
        pytest.fail("Expected current incorrect previous_status violation did not occur")


def test_approved_seed_source_is_idempotent(tmp_path, monkeypatch):
    seed_base_dir(tmp_path, monkeypatch)
    source = existing_source(SourceStatus.APPROVED)
    source.reviewed_at = "2026-01-01T00:00:00+00:00"
    repo = FakeSourceRepo(existing=[source])
    events = FakeEventLog()

    first_count = run_sync(repo, events)
    second_count = run_sync(repo, events)

    assert first_count == 0
    assert second_count == 0
    assert source.status == SourceStatus.APPROVED
    assert source.reviewed_at == "2026-01-01T00:00:00+00:00"
    assert repo.saved == []
    assert events.events == []
