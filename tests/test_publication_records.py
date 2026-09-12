"""Filesystem identity and platform observations must never become taste votes."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiosqlite
from taste_graph_ai.api.routes import feedback_routes as routes
from taste_graph_ai.infrastructure.db.connection import SCHEMA
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository


class PublicationRecordsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.db = await aiosqlite.connect(self.base / 'test.db')
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        columns = [r[1] for r in await (await self.db.execute('PRAGMA table_info(daily_packs)')).fetchall()]
        if 'is_curated' not in columns:
            await self.db.execute('ALTER TABLE daily_packs ADD COLUMN is_curated INTEGER DEFAULT 0')
        await self.db.execute("INSERT INTO daily_packs (id,date,theme,created_at) VALUES ('p001','2026-09-10','','2026-09-10')")
        await self.db.execute("INSERT INTO images (id,created_at) VALUES ('image1','2026-09-10')")
        await self.db.execute("INSERT INTO pack_images (pack_id,image_id,position) VALUES ('p001','image1',0)")
        await self.db.commit()
        self.events = []
        self.taste_calls = []
        async def taste_record(**kwargs):
            self.taste_calls.append(kwargs)
        self.feedback = SimpleNamespace(record=taste_record)
        self.event_log = SimpleNamespace(append=lambda *args: self.events.append(args))
        self.container = SimpleNamespace(taste_graph=object(), save_graph=lambda: None)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def call(self, **kwargs):
        with patch.object(routes, 'get_container', return_value=self.container):
            return await routes.record_publish_metrics(
                routes.PublishMetricsRequest(**kwargs), PackRepository(self.db),
                PublishHistoryRepository(self.db), None, self.feedback, self.event_log,
            )

    async def rows(self, table):
        return [dict(r) for r in await (await self.db.execute(f'SELECT * FROM {table}')).fetchall()]

    def write_pack(self, explicit_id=None):
        path = self.base / 'posts/2026-09-10/01'
        path.mkdir(parents=True)
        meta = {'theme': 'Warm concrete', 'image_ids': ['image1'], 'workflow_status': 'needs_editorial_review'}
        if explicit_id:
            meta['pack_id'] = explicit_id
        (path / 'curation.json').write_text(json.dumps(meta))
        (path / 'body.txt').write_text('A considered caption.')
        return path

    async def test_under_review_zero_is_observation_not_negative_taste_or_publication(self):
        result = await self.call(pack_id='p001', likes=0, publication_status='under_review',
                                 observed_at='2026-09-12T03:00:00Z', source='manual')
        self.assertEqual(result['delta'], 0)
        self.assertEqual(result['affected_images'], 0)
        self.assertEqual(self.taste_calls, [])
        self.assertEqual(await self.rows('publish_history'), [])
        observations = await self.rows('publication_observations')
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['publication_status'], 'under_review')

    async def test_unknown_time_status_stay_unknown_and_retry_is_idempotent(self):
        first = await self.call(pack_id='p001', likes=1)
        second = await self.call(pack_id='p001', likes=1)
        self.assertEqual(first['record_id'], second['record_id'])
        self.assertEqual(await self.rows('publish_history'), [])
        rows = await self.rows('publication_observations')
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['observed_at'])
        self.assertIsNone(rows[0]['published_at'])
        self.assertEqual(rows[0]['publication_status'], 'unknown')
        self.assertEqual(self.taste_calls, [])

    async def test_filesystem_pack_import_uses_canonical_root_and_stable_id(self):
        self.write_pack()
        with patch('taste_graph_ai.config.BASE_DIR', self.base):
            first = await self.call(pack_id='posts/2026-09-10/01', likes=1)
            second = await self.call(pack_id='2026-09-10/01', likes=1)
        self.assertEqual(first['pack_id'], second['pack_id'])
        self.assertTrue(first['pack_id'].startswith('fs_'))
        self.assertEqual(len(await self.rows('publication_pack_links')), 1)
        self.assertEqual(len(await self.rows('publication_observations')), 1)
        imported = [r for r in await self.rows('daily_packs') if r['id'] == first['pack_id']][0]
        self.assertEqual(imported['theme'], 'Warm concrete')
        self.assertEqual(imported['status'], 'draft')
        self.assertEqual(imported['caption'], 'A considered caption.')
        images = [r for r in await self.rows('pack_images') if r['pack_id'] == first['pack_id']]
        self.assertEqual([r['image_id'] for r in images], ['image1'])

    async def test_explicit_manual_pack_id_preserves_content_and_status(self):
        self.write_pack('p001')
        await self.db.execute("UPDATE daily_packs SET theme='Manual title',status='published',published_at='2026-09-10' WHERE id='p001'")
        with patch('taste_graph_ai.config.BASE_DIR', self.base):
            result = await self.call(pack_id='posts/2026-09-10/01', likes=1)
        self.assertEqual(result['pack_id'], 'p001')
        packs = await self.rows('daily_packs')
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]['theme'], 'Manual title')
        self.assertEqual(packs[0]['status'], 'published')

    async def test_separate_observation_times_preserve_snapshot_history_without_taste(self):
        # A known, published date is explicit; recording at another time must not rewrite it.
        args = dict(pack_id='p001', likes=50, saves=20, publication_status='published',
                    published_at='2026-09-10T03:00:00Z', source='creator_center')
        first = await self.call(**args, observed_at='2026-09-11T03:00:00Z')
        second = await self.call(**{**args, 'likes': 70}, observed_at='2026-09-12T03:00:00Z')
        self.assertNotEqual(first['record_id'], second['record_id'])
        self.assertEqual(len(await self.rows('publication_observations')), 2)
        self.assertEqual(self.taste_calls, [])
        history = await self.rows('publish_history')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['likes'], 70)
        self.assertTrue(history[0]['published_at'].startswith('2026-09-10'))

    async def test_external_pack_path_cannot_escape_posts(self):
        outside = self.base / 'private'
        outside.mkdir()
        (outside / 'curation.json').write_text('{"image_ids": []}')
        with patch('taste_graph_ai.config.BASE_DIR', self.base):
            with self.assertRaises(routes.HTTPException) as error:
                await self.call(pack_id='../private', likes=1)
        self.assertEqual(error.exception.status_code, 400)

    async def test_older_observation_does_not_replace_newer_published_totals(self):
        common = dict(pack_id='p001', publication_status='published',
                      published_at='2026-09-10T03:00:00Z')
        await self.call(**common, likes=40, observed_at='2026-09-12T03:00:00Z')
        await self.call(**common, likes=10, observed_at='2026-09-11T03:00:00Z')
        self.assertEqual((await self.rows('publish_history'))[0]['likes'], 40)

    async def test_weekly_summary_does_not_treat_unknown_dates_as_today(self):
        async def recent(limit):
            return [{'id': 'legacy', 'published_at': '', 'likes': 10, 'saves': 0,
                     'comments': 0, 'engagement_rate': 3.0}]
        result = await routes.get_weekly_summary(SimpleNamespace(list_recent=recent))
        self.assertEqual(result['publish_count'], 0)

    async def test_missing_counts_and_images_remain_explicitly_unknown(self):
        path = self.write_pack()
        (path / 'curation.json').write_text(json.dumps({'image_ids': ['image1', 'missing-image']}))
        with patch('taste_graph_ai.config.BASE_DIR', self.base):
            result = await self.call(pack_id='posts/2026-09-10/01', likes=None,
                                     saves=None, comments=None, shares=None)
        self.assertEqual(result['label'], '未记录')
        self.assertIn('missing-image', result['warnings'][0])
        self.assertIsNone((await self.rows('publication_observations'))[0]['likes'])

    async def test_status_registration_does_not_erase_existing_metrics_or_link(self):
        common = dict(pack_id='p001', publication_status='published',
                      published_at='2026-09-10T03:00:00Z')
        await self.call(**common, likes=50, saves=20, post_url='https://example.test/post')
        await self.call(**common, likes=None, saves=None, comments=None, shares=None,
                        observation_key='registration')
        row = (await self.rows('publish_history'))[0]
        self.assertEqual(row['likes'], 50)
        self.assertEqual(row['saves'], 20)
        self.assertEqual(row['post_url'], 'https://example.test/post')

    async def test_direct_status_only_request_keeps_absent_counters_null(self):
        result = await self.call(pack_id='p001', publication_status='under_review',
                                 observed_at='2026-09-12T03:00:00Z')
        row = (await self.rows('publication_observations'))[0]
        self.assertIsNone(row['likes'])
        self.assertIsNone(row['saves'])
        self.assertIsNone(row['comments'])
        self.assertIsNone(row['shares'])
        self.assertEqual(result['label'], '未记录')


class QueuePublicationTests(unittest.TestCase):
    def setUp(self):
        from scripts import queue_server
        self.queue = queue_server
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'publish_log.json'
        self.path.write_text(json.dumps([{'id': 'p001', 'pack': 'posts/2026-09-10/01',
                                         'l24': '0', 's24': '0', 'c24': '0',
                                         'publication_status': 'under_review'}]))

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, data, upstream):
        import io
        handler = self.queue.QueueHandler.__new__(self.queue.QueueHandler)
        raw = json.dumps(data).encode()
        handler.path = '/publish-entries'
        handler.headers = {'Content-Length': str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        results = []
        handler._json = lambda value, status=200: results.append((status, value))
        with patch.object(self.queue, 'PUBLISH_LOG_PATH', self.path), patch.object(
            self.queue.urllib.request, 'urlopen', side_effect=upstream,
        ):
            handler.do_POST()
        return results[-1]

    def test_bridge_failure_surfaces_after_local_save_instead_of_false_success(self):
        from urllib.error import URLError
        calls = []
        def upstream(req, **kwargs):
            calls.append(json.loads(req.data))
            raise URLError('API unavailable')
        status, response = self.post({'id': 'p001', 'l24': '0'}, upstream)
        self.assertEqual(status, 502)
        self.assertFalse(response['ok'])
        self.assertTrue(response['saved'])
        self.assertIn('API unavailable', response['error'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['pack_id'], 'posts/2026-09-10/01')
        self.assertEqual(calls[0]['likes'], 0)
        self.assertEqual(calls[0]['publication_status'], 'under_review')
        self.assertEqual(json.loads(self.path.read_text())[0]['id'], 'p001')

    def test_merged_entry_sync_keeps_windows_separate_and_retry_identity(self):
        import io
        calls = []
        def upstream(req, **kwargs):
            calls.append(json.loads(req.data))
            return io.BytesIO(json.dumps({'pack_id': 'fs_stable', 'record_id': 'obs_1', 'warnings': []}).encode())
        status, response = self.post({'id': 'p001', 'l48': '3'}, upstream)
        self.assertEqual(status, 200)
        self.assertTrue(response['ok'])
        self.assertEqual(len(calls), 2)
        self.assertEqual([c['likes'] for c in calls], [0, 3])
        self.assertIsNone(calls[1]['saves'])
        self.assertIsNone(calls[0]['observed_at'])
        self.assertNotEqual(calls[0]['observation_key'], calls[1]['observation_key'])
        self.assertEqual(response['entries'][0]['pack_id'], 'fs_stable')
        first_keys = [c['observation_key'] for c in calls]
        calls.clear()
        self.post({'id': 'p001', 'l48': '3'}, upstream)
        self.assertEqual([c['observation_key'] for c in calls], first_keys)

    def test_status_only_edit_does_not_repeat_metric_snapshots(self):
        import io
        calls = []
        def upstream(req, **kwargs):
            calls.append(json.loads(req.data))
            return io.BytesIO(b'{"pack_id":"fs_stable","record_id":"obs_status"}')
        self.post({'id': 'p001', 'publication_status': 'published'}, upstream)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0]['likes'])
        self.assertTrue(calls[0]['observation_key'].endswith(':registration'))

    def test_retry_of_status_only_failure_does_not_send_old_counters(self):
        import io
        from urllib.error import URLError
        self.post({'id': 'p001', 'publication_status': 'published'}, lambda *a, **kw: (_ for _ in ()).throw(URLError('offline')))
        calls = []
        def upstream(req, **kwargs):
            calls.append(json.loads(req.data))
            return io.BytesIO(b'{"pack_id":"fs_stable","record_id":"obs_status"}')
        self.post({'id': 'p001', 'retry_sync': True}, upstream)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0]['likes'])

    def test_legacy_submission_time_is_not_reused_when_status_changes_to_published(self):
        import io
        legacy = {'id': 'p001', 'pack': 'posts/2026-09-10/01', 'platform_status': '审核中',
                  'published_at': '2026-09-12T22:53:00+08:00', 'l24': None, 'l48': None}
        self.path.write_text(json.dumps([legacy]))
        calls = []
        def upstream(req, **kwargs):
            calls.append(json.loads(req.data))
            return io.BytesIO(b'{"pack_id":"p001","record_id":"obs_status"}')
        self.post({'id': 'p001', 'publication_status': 'published'}, upstream)
        self.assertIsNone(calls[0]['published_at'])
        saved = json.loads(self.path.read_text())[0]
        self.assertEqual(saved['submitted_at'], legacy['published_at'])
        self.assertIsNone(saved['published_at'])
        actual = '2026-09-13T01:00:00+08:00'
        self.post({'id': 'p001', 'published_at': actual}, upstream)
        self.assertEqual(calls[-1]['published_at'], actual)

    def test_legacy_under_review_bridge_keeps_time_unknown(self):
        result = self.queue._publication_payloads({'id': 'p001', 'pack': 'posts/a',
            'platform_status': '审核中', 'published_at': '2026-09-12T22:53:00+08:00'})[0]
        self.assertEqual(result['publication_status'], 'under_review')
        self.assertIsNone(result['published_at'])


class PublicationLogUITests(unittest.TestCase):
    def test_blank_dates_stay_blank_and_review_entries_do_not_count_as_published(self):
        import subprocess
        import shutil
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for browser-script contract test')
        html = (Path(__file__).parents[1] / 'scripts/publish-log.html').read_text()
        script = html.split('<script>', 1)[1].split('</script>', 1)[0]
        harness = r"""
const vm = require('vm');
const elements = {};
const element = id => elements[id] ||= {value:'', innerHTML:'', innerText:'', textContent:'', style:{},
  querySelector: () => element('tbody')};
const context = {document: {getElementById: element},
  fetch: () => new Promise(() => {}), console, alert: () => {}, Date};
vm.createContext(context);
vm.runInContext(SCRIPT, context);
const date = element('f-time').value;
context.entries = [{id:'p001', pack:'posts/a', publication_status:'under_review',
  published_at:new Date().toISOString(), l24:0, bridge:{ok:false,error:'API unavailable'}}];
vm.runInContext('render(entries)', context);
process.stdout.write(JSON.stringify({date, summary:element('sum').innerText,
  html:element('tbody').innerHTML}));
""".replace('SCRIPT', json.dumps(script))
        result = subprocess.run([node, '-e', harness], capture_output=True, text=True, check=True)
        state = json.loads(result.stdout)
        self.assertEqual(state['date'], '')
        self.assertIn('已发布 0 篇', state['summary'])
        self.assertIn('API unavailable', state['html'])
        self.assertIn('value="0"', state['html'])
