"""Old daily routes cannot bypass local review or perform platform actions."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiosqlite
from taste_graph_ai.api import schemas
from taste_graph_ai.api.routes import daily, editorial
from taste_graph_ai.infrastructure.db.connection import SCHEMA
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository
from taste_graph_ai.services.editorial import EDITORIAL_SCHEMA


class LegacyEditorialGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.path = self.base / 'test.db'
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA + EDITORIAL_SCHEMA)
        cols = [r[1] for r in await (await self.db.execute('PRAGMA table_info(daily_packs)')).fetchall()]
        if 'is_curated' not in cols:
            await self.db.execute('ALTER TABLE daily_packs ADD COLUMN is_curated INTEGER DEFAULT 0')
        await self.db.execute("INSERT INTO daily_packs(id,date,theme,created_at) VALUES('candidate','2026-09-12','Concrete','2026-09-12')")
        self.original = self.base / 'original.jpg'
        self.original.write_bytes(b'original-image-bytes-do-not-transform')
        await self.db.execute("INSERT INTO images(id,local_path,created_at) VALUES('image1',?,'2026-09-12')", (str(self.original),))
        await self.db.execute("INSERT INTO pack_images(pack_id,image_id,position) VALUES('candidate','image1',0)")
        await self.db.commit()
        self.packs = PackRepository(self.db)
        self.publishes = PublishHistoryRepository(self.db)
        self.events = []
        self.log = SimpleNamespace(append=lambda *args: self.events.append(args))

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def approve(self):
        review = {'status': 'approved', 'thesis': 'Concrete', 'sequence_reason': 'One detail',
                  'images': [{'image_id': 'image1', 'role': 'detail', 'evidence': 'texture', 'reason': 'material'}]}
        await self.db.execute('INSERT INTO pack_editorial VALUES(?,?,?,?)',
                              ('candidate', json.dumps(review), 'approved', '2026-09-12'))
        await self.db.commit()

    async def test_select_requires_editorial_approval(self):
        with self.assertRaises(daily.HTTPException) as error:
            await daily.select_pack('candidate', self.packs, self.log)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('editorial', str(error.exception.detail))
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'draft')

    async def test_export_requires_editorial_approval_without_composition(self):
        with patch.object(daily, 'MoodboardComposer', return_value=SimpleNamespace(compose=lambda **kw: self.original)):
            with self.assertRaises(daily.HTTPException) as error:
                await daily.export_pack('candidate', self.packs)
        self.assertEqual(error.exception.status_code, 409)

    async def test_approved_export_archives_original_bytes(self):
        from taste_graph_ai.services.publication_records import ensure_publication_schema
        import zipfile
        await self.approve()
        await ensure_publication_schema(self.db)
        await self.db.commit()
        with patch.object(editorial, 'DB_FILE', self.path), patch.object(editorial, 'BASE_DIR', self.base), \
             patch('taste_graph_ai.config.EXPORTS_DIR', self.base / 'exports'), \
             patch.object(daily, 'MoodboardComposer', return_value=SimpleNamespace(compose=lambda **kw: self.original)):
            result = await daily.export_pack('candidate', self.packs)
        self.assertTrue(result.filename.endswith('.zip'))
        with zipfile.ZipFile(self.base / 'exports' / result.filename) as bundle:
            self.assertEqual(bundle.read('image-01.jpg'), self.original.read_bytes())

    async def test_auto_publish_is_disabled_before_touching_repo_or_browser(self):
        class UntouchedRepo:
            async def get_by_id(self, *args):
                raise AssertionError('Disabled route must return before DB/browser work')
        with self.assertRaises(daily.HTTPException) as error:
            await daily.auto_publish_pack('candidate', UntouchedRepo(), self.publishes, self.log)
        self.assertEqual(error.exception.status_code, 405)

    async def test_manual_publish_without_explicit_date_and_status_is_rejected(self):
        with self.assertRaises(daily.HTTPException) as error:
            await daily.publish_pack('candidate', schemas.PackPublishRequest(), self.packs, self.publishes, self.log)
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'draft')

    async def test_manual_evidence_preserves_timestamp_and_is_idempotent(self):
        # SimpleNamespace permits test-first direct invocation before new schema exists.
        body = SimpleNamespace(platform='xiaohongshu', post_url='https://example.test/post',
            publication_status='published', published_at='2026-09-10T05:00:00Z', observed_at=None)
        first = await daily.publish_pack('candidate', body, self.packs, self.publishes, self.log)
        second = await daily.publish_pack('candidate', body, self.packs, self.publishes, self.log)
        rows = await (await self.db.execute('SELECT * FROM publish_history')).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['published_at'].startswith('2026-09-10'))
        self.assertEqual(first['record_id'], second['record_id'])

    async def test_under_review_evidence_does_not_mark_published(self):
        body = SimpleNamespace(platform='xiaohongshu', post_url='', publication_status='under_review',
                               published_at=None, observed_at='2026-09-12T05:00:00Z')
        await daily.publish_pack('candidate', body, self.packs, self.publishes, self.log)
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'draft')
        self.assertEqual(await (await self.db.execute('SELECT * FROM publish_history')).fetchall(), [])

    async def test_unknown_literal_is_not_explicit_publication_evidence(self):
        body = SimpleNamespace(platform='xiaohongshu', post_url='', publication_status='published',
                               published_at='unknown', observed_at=None)
        with self.assertRaises(daily.HTTPException) as error:
            await daily.publish_pack('candidate', body, self.packs, self.publishes, self.log)
        self.assertEqual(error.exception.status_code, 400)

    async def test_reviewed_candidate_can_be_selected(self):
        await self.approve()
        response = await daily.select_pack('candidate', self.packs, self.log)
        self.assertEqual(response.status, 'selected')

    async def test_reject_cannot_mutate_published_pack(self):
        await self.db.execute("UPDATE daily_packs SET status='published' WHERE id='candidate'")
        await self.db.commit()
        with self.assertRaises(daily.HTTPException) as error:
            await daily.reject_pack('candidate', self.packs, None, self.log)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'published')

    async def test_reject_cannot_mutate_submitted_pack(self):
        from taste_graph_ai.services.publication_records import record_publication_observation
        await record_publication_observation(self.db, 'candidate', {
            'publication_status': 'under_review', 'observed_at': '2026-09-12T05:00:00Z',
        }, score=0)
        with self.assertRaises(daily.HTTPException) as error:
            await daily.reject_pack('candidate', self.packs, None, self.log)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'draft')
        self.assertEqual(await (await self.db.execute('SELECT * FROM pack_editorial')).fetchall(), [])

    async def test_reject_is_pack_editorial_decision_without_image_mutation(self):
        await self.approve()
        class UntouchedImageRepo:
            async def mark_many_status(self, *args):
                raise AssertionError('Pack rejection must not mutate individual images')
        with patch('taste_graph_ai.config.DB_FILE', self.path):
            result = await daily.reject_pack('candidate', self.packs, UntouchedImageRepo(), self.log)
        self.assertEqual(result['status'], 'ok')
        review = await (await self.db.execute('SELECT * FROM pack_editorial WHERE pack_id=?', ('candidate',))).fetchone()
        self.assertEqual(review['status'], 'rejected')
        self.assertEqual(json.loads(review['review_json'])['thesis'], 'Concrete')
        self.assertEqual((await self.packs.get_by_id('candidate')).status.value, 'rejected')
        self.assertEqual(await (await self.db.execute('SELECT * FROM feedback_log')).fetchall(), [])
        images = await (await self.db.execute('SELECT status FROM images')).fetchall()
        self.assertEqual(images[0][0], 'pending')
