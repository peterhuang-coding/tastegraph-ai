"""Behavior tests for the read-only data-ops snapshot view.

These tests mount only the data-ops router on a throwaway FastAPI app;
they never import the full production application.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from taste_graph_ai.api.routes import data_ops
from taste_graph_ai.services.data_ops import build_view

SNAPSHOT_ENV = "TASTEGRAPH_DATA_OPS_SNAPSHOT"
SNAPSHOT_URL = "/api/v1/data-ops/snapshot"


def sample_snapshot():
    """Synthetic snapshot matching the approved minimal public contract."""
    return {
        "assembled_at": "2026-01-02T22:30:00+08:00",
        "db_observed_at": "2026-01-02T22:00:00+08:00",
        "database": {
            "counts": {"images": 90, "sources": 52},
            "quality": {
                "images_file_existence": {
                    "with_path": 99,
                    "existing_file": 90,
                    "missing_file": 9,
                },
                "images_source_coverage": {
                    "total": 100,
                    "missing_path": 1,
                    "missing_source_id": 20,
                    "unresolved_source_id": 2,
                },
                "images_with_provenance": 64,
            },
        },
        "source_layers": {
            "DB": {"rows": 60, "approved": 40, "pending": 15, "rejected": 5},
            "peer_research": {
                "verified_research_sources": 12,
                "ingestion_changes": 3,
            },
            "archive_reserve": {
                "new_complete_visual_sets": 4,
                "target_size_range": [20, 30],
            },
        },
        "latest_operations_observed_at": "2026-01-02T22:00:00+08:00",
        "latest_operations": {
            "lastBackup": {
                "ok": True,
                "finishedAt": "2026-01-02T04:00:00+08:00",
                "integrity": "ok",
                "countsMatch": True,
                "backupBytes": 2048,
            },
            "activeCandidatePacks": 2,
            "activePackLimit": 4,
        },
        "today_at_snapshot": {
            "scheduled_date": "2026-01-02",
            "as_of": "2026-01-02T22:00:00+08:00",
            "status": "succeeded",
            "processed_at_snapshot": 20,
            "inserted_at_snapshot": 10,
            "processed_status_counts": {
                "downloaded": 10,
                "failed": 2,
                "skipped": 8,
            },
        },
        "publication": {
            "as_of": "2026-01-02T22:00:00+08:00",
            "finite_batch_capacity": 20,
            "consumed": 4,
            "remaining": 16,
            "today_submitted_by_local_log": 1,
            "daily_cap": 4,
            "earliest_slot": 5,
            "editorial_blocked_slots": [5],
            "hold": False,
        },
        "section_freshness": {
            "database_quality_and_file_existence": {
                "as_of": "2026-01-02T20:00:00+08:00"
            },
            "source_layers_and_update_chain": {
                "as_of": "2026-01-01T20:00:00+08:00"
            },
        },
    }


def by_label(section):
    return {item["label"]: item for item in section["items"]}


class BuildViewTests(unittest.TestCase):
    def test_top_level_and_section_contract(self):
        view = build_view(sample_snapshot())
        self.assertEqual(set(view.keys()), {"assembled_at", "sections"})
        self.assertEqual(view["assembled_at"], "2026-01-02T22:30:00+08:00")
        ids = [s["id"] for s in view["sections"]]
        self.assertEqual(ids, ["inventory", "sources", "updates", "publication"])
        for section in view["sections"]:
            self.assertEqual(set(section.keys()), {"id", "title", "as_of", "items"})
            self.assertIsInstance(section["title"], str)
            for item in section["items"]:
                self.assertEqual(set(item.keys()), {"label", "value", "note"})

    def test_missing_is_null_zero_is_kept(self):
        raw = sample_snapshot()
        raw["database"]["counts"]["images"] = 0
        raw["database"]["counts"].pop("sources")
        raw["database"]["quality"]["images_file_existence"]["missing_file"] = 0
        raw["database"]["quality"]["images_source_coverage"]["missing_path"] = 0
        raw["publication"].pop("remaining")
        raw["publication"]["finite_batch_capacity"] = None
        view = build_view(raw)
        inventory = view["sections"][0]
        items = by_label(inventory)
        self.assertIs(items["图片总数"]["value"], 0)
        self.assertIsNone(items["来源总数"]["value"])
        self.assertIs(items["缺失文件图片"]["value"], 0)
        self.assertIs(items["无路径记录图片"]["value"], 0)
        publication = view["sections"][3]
        pub = by_label(publication)
        self.assertIsNone(pub["剩余槽位"]["value"])
        self.assertIsNone(pub["有限批次容量"]["value"])

    def test_wrong_types_become_unknown(self):
        raw = sample_snapshot()
        raw["database"]["counts"]["images"] = True
        raw["publication"]["hold"] = "no"
        raw["publication"]["editorial_blocked_slots"] = [5, "x"]
        view = build_view(raw)
        items = by_label(view["sections"][0])
        self.assertIsNone(items["图片总数"]["value"])
        pub = by_label(view["sections"][3])
        self.assertIsNone(pub["发布暂停"]["value"])
        self.assertIsNone(pub["编辑阻塞槽位数"]["value"])

    def test_each_section_uses_its_own_as_of(self):
        view = build_view(sample_snapshot())
        sections = {s["id"]: s for s in view["sections"]}
        self.assertEqual(
            sections["inventory"]["as_of"], "2026-01-02T20:00:00+08:00"
        )
        self.assertEqual(
            sections["sources"]["as_of"], "2026-01-01T20:00:00+08:00"
        )
        self.assertEqual(
            sections["updates"]["as_of"], "2026-01-02T22:00:00+08:00"
        )
        self.assertEqual(
            sections["publication"]["as_of"], "2026-01-02T22:00:00+08:00"
        )
        self.assertNotEqual(
            sections["inventory"]["as_of"], view["assembled_at"]
        )

    def test_missing_section_as_of_is_null(self):
        raw = sample_snapshot()
        raw["section_freshness"]["database_quality_and_file_existence"] = {}
        raw.pop("latest_operations_observed_at")
        view = build_view(raw)
        sections = {s["id"]: s for s in view["sections"]}
        self.assertIsNone(sections["inventory"]["as_of"])
        self.assertIsNone(sections["updates"]["as_of"])

    def test_dangerous_fields_are_never_projected(self):
        raw = sample_snapshot()
        raw["secret_path"] = "/srv/private/secret.json"
        raw["logs"] = ["panic at /opt/tg/run.log"]
        raw["account"] = "svc-secret-bob"
        raw["database"]["password"] = "hunter2"
        raw["database"]["quality"]["raw_log"] = "GET http://token@host/x"
        raw["latest_operations"]["url"] = "http://evil.example/"
        raw["publication"]["debug"] = "see /etc/tg/creds"
        view = build_view(raw)
        blob = json.dumps(view, ensure_ascii=False)
        for leaked in (
            "/srv/private",
            "secret",
            "logs",
            "panic",
            "svc-secret-bob",
            "password",
            "hunter2",
            "http",
            "evil",
            "/etc",
            "creds",
            "debug",
        ):
            self.assertNotIn(leaked, blob)
        # No unexpected keys anywhere in the projection.
        self.assertEqual(set(view.keys()), {"assembled_at", "sections"})
        for section in view["sections"]:
            self.assertEqual(
                set(section.keys()), {"id", "title", "as_of", "items"}
            )
            for item in section["items"]:
                self.assertEqual(set(item.keys()), {"label", "value", "note"})

    def test_previous_day_record_keeps_original_date_label(self):
        view = build_view(sample_snapshot())
        updates = view["sections"][2]
        dated = [i for i in updates["items"] if "2026-01-02" in i["label"]]
        self.assertTrue(dated)
        for item in updates["items"]:
            self.assertNotIn("今天", item["label"])

    def test_unparseable_backup_time_marked_unknown(self):
        raw = sample_snapshot()
        raw["latest_operations"]["lastBackup"]["finishedAt"] = "not-a-time"
        view = build_view(raw)
        items = by_label(view["sections"][2])
        note = items["备份完成时间"]["note"] or ""
        self.assertIn("时间未知", note)

    def test_queue_full_separate_from_archive_target(self):
        raw = sample_snapshot()
        raw["latest_operations"]["activeCandidatePacks"] = 4
        raw["latest_operations"]["activePackLimit"] = 4
        view = build_view(raw)
        updates = by_label(view["sections"][2])
        sources = by_label(view["sections"][1])
        self.assertIn("队列已满", updates["活动候选包"]["note"] or "")
        target = sources["完整视觉套目标区间"]
        self.assertEqual(target["value"], "20–30")
        self.assertIn("目标", target["note"] or "")

    def test_submission_is_not_claimed_as_published(self):
        view = build_view(sample_snapshot())
        pub = by_label(view["sections"][3])
        labels = list(pub)
        self.assertTrue(any("提交" in label for label in labels))
        for label in labels:
            self.assertNotIn("已公开", label)
        self.assertNotIn("公开数", "".join(labels))

    def test_non_dict_raw_does_not_raise(self):
        view = build_view(["not", "a", "dict"])
        self.assertEqual(set(view.keys()), {"assembled_at", "sections"})
        self.assertEqual(len(view["sections"]), 4)
        for section in view["sections"]:
            self.assertIsNone(section["as_of"])

    def test_real_file_existence_and_coverage_fields(self):
        view = build_view(sample_snapshot())
        inventory = by_label(view["sections"][0])
        self.assertIs(inventory["有文件图片"]["value"], 90)
        self.assertIs(inventory["缺失文件图片"]["value"], 9)
        self.assertIs(inventory["无路径记录图片"]["value"], 1)
        sources = by_label(view["sections"][1])
        self.assertIs(sources["追溯覆盖图片总数"]["value"], 100)
        self.assertIs(sources["缺来源ID图片"]["value"], 20)
        self.assertIs(sources["来源ID未解析图片"]["value"], 2)
        self.assertIs(sources["有溯源记录图片"]["value"], 64)

    def test_missing_coverage_groups_become_unknown(self):
        raw = sample_snapshot()
        raw["database"]["quality"].pop("images_source_coverage")
        raw["database"]["quality"].pop("images_with_provenance")
        view = build_view(raw)
        inventory = by_label(view["sections"][0])
        sources = by_label(view["sections"][1])
        self.assertIsNone(inventory["无路径记录图片"]["value"])
        self.assertIsNone(sources["追溯覆盖图片总数"]["value"])
        self.assertIsNone(sources["缺来源ID图片"]["value"])
        self.assertIsNone(sources["来源ID未解析图片"]["value"])
        self.assertIsNone(sources["有溯源记录图片"]["value"])

    def test_provenance_items_carry_quality_evidence_time(self):
        view = build_view(sample_snapshot())
        sources_section = view["sections"][1]
        # The section header keeps the source-layer evidence time ...
        self.assertEqual(
            sources_section["as_of"], "2026-01-01T20:00:00+08:00"
        )
        sources = by_label(sources_section)
        traced_labels = (
            "追溯覆盖图片总数",
            "缺来源ID图片",
            "来源ID未解析图片",
            "有溯源记录图片",
        )
        for label in traced_labels:
            note = sources[label]["note"] or ""
            # ... while each item note carries the database-quality time.
            self.assertIn("2026-01-02T20:00:00+08:00", note)
            self.assertNotIn("2026-01-01T20:00:00", note)
        provenance_note = sources["有溯源记录图片"]["note"] or ""
        self.assertIn("不等于", provenance_note)
        self.assertIn("下载", provenance_note)

    def test_provenance_note_without_quality_time_says_unknown(self):
        raw = sample_snapshot()
        raw["section_freshness"]["database_quality_and_file_existence"] = {}
        view = build_view(raw)
        sources = by_label(view["sections"][1])
        note = sources["有溯源记录图片"]["note"] or ""
        self.assertIn("证据时间：未知", note)

    def test_target_size_range_is_two_non_negative_ints(self):
        view = build_view(sample_snapshot())
        target = by_label(view["sections"][1])["完整视觉套目标区间"]
        self.assertEqual(target["value"], "20–30")
        self.assertIn("目标", target["note"] or "")

    def test_bad_target_ranges_become_unknown(self):
        bad_ranges = (
            None,
            "20-30",
            [20],
            [20, 30, 40],
            ["20", "30"],
            [20, True],
            [-1, 30],
            [20, -1],
            [20.5, 30],
            [40, 20],
        )
        for bad in bad_ranges:
            raw = sample_snapshot()
            raw["source_layers"]["archive_reserve"]["target_size_range"] = bad
            target = by_label(build_view(raw)["sections"][1])[
                "完整视觉套目标区间"
            ]
            self.assertIsNone(target["value"], bad)

    def test_counts_reject_bool_float_negative_nonfinite(self):
        raw = sample_snapshot()
        raw["database"]["counts"]["images"] = False
        raw["database"]["counts"]["sources"] = -3
        raw["publication"]["consumed"] = 4.5
        raw["latest_operations"]["activeCandidatePacks"] = float("inf")
        raw["latest_operations"]["activePackLimit"] = float("nan")
        raw["database"]["quality"]["images_source_coverage"]["total"] = 100.0
        raw["database"]["quality"]["images_with_provenance"] = -1
        view = build_view(raw)
        inventory = by_label(view["sections"][0])
        updates = by_label(view["sections"][2])
        publication = by_label(view["sections"][3])
        sources = by_label(view["sections"][1])
        self.assertIsNone(inventory["图片总数"]["value"])
        self.assertIsNone(inventory["来源总数"]["value"])
        self.assertIsNone(updates["活动候选包"]["value"])
        self.assertIsNone(updates["候选包上限"]["value"])
        self.assertIsNone(publication["已占用槽位"]["value"])
        self.assertIsNone(sources["追溯覆盖图片总数"]["value"])
        self.assertIsNone(sources["有溯源记录图片"]["value"])
        # The projection must stay serializable as strict JSON (no NaN /
        # Infinity tokens that would break Starlette JSONResponse).
        blob = json.dumps(view, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("NaN", blob)
        self.assertNotIn("Infinity", blob)

    def test_status_and_integrity_use_fixed_enums(self):
        raw = sample_snapshot()
        raw["latest_operations"]["lastBackup"]["integrity"] = "/etc/tg/creds"
        raw["today_at_snapshot"]["status"] = "http://evil.example/x"
        view = build_view(raw)
        blob = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("/etc", blob)
        self.assertNotIn("evil", blob)
        updates = by_label(view["sections"][2])
        self.assertIsNone(updates["备份完整性"]["value"])
        day_status = next(
            item for label, item in updates.items() if label.endswith("状态")
        )
        self.assertIsNone(day_status["value"])

        allowed = sample_snapshot()
        allowed["latest_operations"]["lastBackup"]["integrity"] = "failed"
        allowed["today_at_snapshot"]["status"] = "running"
        allowed_view = build_view(allowed)
        allowed_updates = by_label(allowed_view["sections"][2])
        self.assertEqual(allowed_updates["备份完整性"]["value"], "failed")
        allowed_status = next(
            item
            for label, item in allowed_updates.items()
            if label.endswith("状态")
        )
        self.assertEqual(allowed_status["value"], "running")

    def test_naive_and_broken_timestamps_become_unknown(self):
        raw = sample_snapshot()
        raw["assembled_at"] = "2026-01-02T22:30:00"  # naive: never guess tz
        raw["section_freshness"]["source_layers_and_update_chain"][
            "as_of"
        ] = "2026-01-01T20:00:00"
        raw["latest_operations_observed_at"] = "yesterday"
        raw["latest_operations"]["lastBackup"]["finishedAt"] = (
            "2026-01-02T04:00:00"
        )
        view = build_view(raw)
        self.assertIsNone(view["assembled_at"])
        sections = {s["id"]: s for s in view["sections"]}
        self.assertIsNone(sections["sources"]["as_of"])
        self.assertIsNone(sections["updates"]["as_of"])
        updates = by_label(sections["updates"])
        self.assertIsNone(updates["备份完成时间"]["value"])
        self.assertIn("时间未知", updates["备份完成时间"]["note"] or "")

    def test_scheduled_date_only_accepts_calendar_dates(self):
        for bad_date in ("2026/01/02", "2026-13-99", "not-a-date", "2026-01-02T00:00:00Z"):
            raw = sample_snapshot()
            raw["today_at_snapshot"]["scheduled_date"] = bad_date
            labels = [
                item["label"]
                for item in build_view(raw)["sections"][2]["items"]
            ]
            self.assertTrue(
                any("日期未知" in label for label in labels), bad_date
            )
            self.assertFalse(
                any(bad_date in label for label in labels), bad_date
            )


class SnapshotApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(data_ops.router)
        self.client = TestClient(app)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.path = os.path.join(self.tmp, "snapshot.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(payload)

    def test_get_twice_is_identical_and_writes_nothing(self):
        self._write(json.dumps(sample_snapshot()))
        env = {SNAPSHOT_ENV: self.path}
        before_listing = set(os.listdir(self.tmp))
        before_mtime = os.stat(self.path).st_mtime_ns
        with patch.dict(os.environ, env, clear=False):
            r1 = self.client.get(SNAPSHOT_URL)
            r2 = self.client.get(SNAPSHOT_URL)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.content, r2.content)
        self.assertEqual(r1.headers.get("cache-control"), "no-store")
        body = r1.json()
        self.assertEqual(
            [s["id"] for s in body["sections"]],
            ["inventory", "sources", "updates", "publication"],
        )
        self.assertEqual(set(os.listdir(self.tmp)), before_listing)
        self.assertEqual(os.stat(self.path).st_mtime_ns, before_mtime)

    def test_env_unset_is_503_without_path_leak(self):
        env = dict(os.environ)
        env.pop(SNAPSHOT_ENV, None)
        with patch.dict(os.environ, env, clear=True):
            r = self.client.get(SNAPSHOT_URL)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(self.tmp, r.text)

    def test_missing_file_is_503_without_path_leak(self):
        with patch.dict(os.environ, {SNAPSHOT_ENV: self.path}, clear=False):
            r = self.client.get(SNAPSHOT_URL)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(self.path, r.text)
        self.assertNotIn("snapshot.json", r.text)

    def test_bad_json_is_503(self):
        self._write("{not valid json")
        with patch.dict(os.environ, {SNAPSHOT_ENV: self.path}, clear=False):
            r = self.client.get(SNAPSHOT_URL)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(self.path, r.text)

    def test_post_is_405_and_creates_no_file(self):
        self.assertEqual(os.listdir(self.tmp), [])
        with patch.dict(os.environ, {SNAPSHOT_ENV: self.path}, clear=False):
            r = self.client.post(SNAPSHOT_URL, json={"anything": 1})
        self.assertEqual(r.status_code, 405)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_get_does_not_read_sources_outside_env_path(self):
        # Even with a database/hub-like filename present, only the env
        # configured snapshot file is read.
        decoy = os.path.join(self.tmp, "hub-db.sqlite")
        with open(decoy, "wb") as fh:
            fh.write(b"decoy")
        self._write(json.dumps(sample_snapshot()))
        with patch.dict(os.environ, {SNAPSHOT_ENV: self.path}, clear=False):
            r = self.client.get(SNAPSHOT_URL)
        self.assertEqual(r.status_code, 200)
        with open(decoy, "rb") as fh:
            self.assertEqual(fh.read(), b"decoy")

    def test_non_object_root_is_503_no_store(self):
        for payload in ("[]", '"a string"', "42", "null", "true"):
            self._write(payload)
            with patch.dict(
                os.environ, {SNAPSHOT_ENV: self.path}, clear=False
            ):
                r = self.client.get(SNAPSHOT_URL)
            self.assertEqual(r.status_code, 503, payload)
            self.assertEqual(r.headers.get("cache-control"), "no-store")
            self.assertNotIn(self.path, r.text)

    def test_error_responses_are_no_store_without_path_leak(self):
        with patch.dict(
            os.environ, {SNAPSHOT_ENV: self.path}, clear=False
        ):
            missing = self.client.get(SNAPSHOT_URL)
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(missing.headers.get("cache-control"), "no-store")
        self.assertNotIn("snapshot.json", missing.text)

        self._write("{not valid json")
        with patch.dict(
            os.environ, {SNAPSHOT_ENV: self.path}, clear=False
        ):
            bad_json = self.client.get(SNAPSHOT_URL)
        self.assertEqual(bad_json.status_code, 503)
        self.assertEqual(bad_json.headers.get("cache-control"), "no-store")
        self.assertNotIn(self.path, bad_json.text)

        env = dict(os.environ)
        env.pop(SNAPSHOT_ENV, None)
        with patch.dict(os.environ, env, clear=True):
            unset = self.client.get(SNAPSHOT_URL)
        self.assertEqual(unset.status_code, 503)
        self.assertEqual(unset.headers.get("cache-control"), "no-store")


class IngestionEvidenceTimeTests(unittest.TestCase):
    def test_day_rows_keep_their_own_old_or_unknown_evidence_time(self):
        raw = sample_snapshot()
        raw["latest_operations_observed_at"] = "2099-01-01T00:00:00+08:00"
        raw["today_at_snapshot"]["as_of"] = "2020-01-01T00:00:00+08:00"
        updates = next(s for s in build_view(raw)["sections"] if s["id"] == "updates")
        rows = [i for i in updates["items"] if i["label"].startswith("采集日")]
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertIn("2020-01-01T00:00:00+08:00", row["note"] or "")
            self.assertIn("旧快照", row["note"] or "")
        raw["today_at_snapshot"]["as_of"] = None
        updates = next(s for s in build_view(raw)["sections"] if s["id"] == "updates")
        for row in updates["items"]:
            if row["label"].startswith("采集日"):
                self.assertIn("采集记录证据时间：未知", row["note"] or "")


if __name__ == "__main__":
    unittest.main()
