"""Historical editorial evidence import is additive and idempotent on local DBs."""
import importlib.util
import json
import sqlite3
from pathlib import Path

from taste_graph_ai.infrastructure.db.connection import SCHEMA
from taste_graph_ai.services.editorial import EDITORIAL_SCHEMA, save_annotation


def migration_module():
    spec = importlib.util.find_spec('scripts.migrate_editorial_workflow')
    assert spec is not None, 'An explicit rehearsal-first editorial migration CLI is required'
    from scripts import migrate_editorial_workflow
    return migrate_editorial_workflow


def fixture(tmp_path):
    db_path = tmp_path / 'copy.db'
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA + EDITORIAL_SCHEMA)
    cols = {r[1] for r in db.execute('PRAGMA table_info(daily_packs)')}
    if 'is_curated' not in cols:
        db.execute('ALTER TABLE daily_packs ADD COLUMN is_curated INTEGER DEFAULT 0')
    ids = ['one', 'two']
    for image_id in ids:
        db.execute('INSERT INTO images(id,created_at) VALUES(?,?)', (image_id, '2026-09-12'))
    db.commit(); db.close()
    base = tmp_path / 'files'
    pack = base / 'posts/2026-09-12/manual-rams-example'
    pack.mkdir(parents=True)
    (pack / 'curation.json').write_text(json.dumps({'image_ids': ids, 'status': 'submitted_under_review'}))
    (pack / 'title.txt').write_text('Objects in daily life')
    examples = {'rows': [{'image_id': image_id, 'source_page': 'https://www.hustwit.com/rams',
        'observation': {'image_form': '使用动作', 'scene': '日常'},
        'dates': {'photo_created': None, 'object_original_design': None, 'page_published': None,
            'project_release': {'year': 2018, 'evidence_url': 'https://www.hustwit.com/rams', 'scope': '纪录片年份，不是拍摄日期'}},
        'editorial_proposal': {'topic': '物件进入日常', 'action': '解释组图', 'reason': '手在使用物件'},
        'attribution': {'annotator': 'assistant_visual_review', 'evidence': ['official_project_page']},
    } for image_id in ids]}
    feedback = {'draft_id': 'draft-example', 'status': 'submitted_under_review',
        'title': 'Objects in daily life', 'group_thesis': '物件进入日常',
        'assets': [{'id': image_id, 'order': i, 'role': '使用动作', 'visual_evidence': '可见手', 'sequence_reason': '由远及近'} for i, image_id in enumerate(ids, 1)],
        'publication': {'platform': 'xiaohongshu', 'published_at': None, 'submitted_at': '2026-09-12T22:53:00+08:00', 'platform_status': '审核中'},
        'metric_observations': [{'observation_id': 'initial', 'observed_at': '2026-09-12T14:56:47Z',
            'platform_status': '审核中', 'views': 0, 'likes': 0, 'saves': 0, 'comments': 0, 'shares': 0,
            'source': 'creator note-manager', 'eligible_for_preference_update': False}],
        'registry': {'entry_id': 'p001', 'pack': 'posts/2026-09-12/manual-rams-example'},
    }
    log = [{'id': 'p001', 'pack': feedback['registry']['pack'], 'platform_status': '审核中',
            'published_at': '2026-09-12T22:53:00+08:00', 'l24': None, 'l48': None}]
    paths = {}
    for name, value in [('examples', examples), ('feedback', feedback), ('publish_log', log)]:
        path = tmp_path / (name + '.json'); path.write_text(json.dumps(value)); paths[name] = path
    return db_path, base, paths


def run_migration(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    result = module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    return module, db_path, base, paths, result


def test_migration_preserves_null_dates_and_imports_only_documented_observation(tmp_path):
    module, db_path, base, paths, result = run_migration(tmp_path)
    db = sqlite3.connect(db_path); db.row_factory = sqlite3.Row
    assert result['after']['image_editorial'] == 2
    notes = [json.loads(r[0]) for r in db.execute('SELECT annotation_json FROM image_editorial')]
    assert all(n['actor'] == 'assistant' and n['dates']['photo_created'] is None for n in notes)
    assert all(n['dates']['project_release']['value'] == '2018' for n in notes)
    rows = db.execute('SELECT * FROM publication_observations').fetchall()
    assert len(rows) == 1 and rows[0]['likes'] == 0
    assert rows[0]['published_at'] is None and rows[0]['publication_status'] == 'under_review'
    assert db.execute('SELECT COUNT(*) FROM publish_history').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM feedback_log').fetchone()[0] == 0
    assert db.execute("SELECT status FROM daily_packs WHERE id='p001'").fetchone()[0] != 'published'
    db.close()


def test_repeated_import_does_not_duplicate_annotations_events_or_observations(tmp_path):
    module, db_path, base, paths, first = run_migration(tmp_path)
    second = module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    assert second['before'] == first['after'] == second['after']
    assert second['annotations_imported'] == 0
    assert second['observations_imported'] == 0


def test_existing_manual_annotation_is_preserved(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    manual = save_annotation(db_path, 'one', {'image_form': '我的分类', 'dates': {}}, actor='operator')
    result = module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    db = sqlite3.connect(db_path)
    kept = json.loads(db.execute("SELECT annotation_json FROM image_editorial WHERE image_id='one'").fetchone()[0])
    assert kept == manual
    assert result['annotations_imported'] == 1
    assert result['annotations_preserved'] == ['one']
    db.close()


def test_dry_run_does_not_modify_source_database(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    original = db_path.read_bytes()
    result = module.rehearse(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    assert result['idempotent'] is True
    assert result['first']['after']['publication_observations'] == 1
    assert db_path.read_bytes() == original


def test_only_documented_group_approval_is_imported_with_assistant_actor(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    feedback = json.loads(paths['feedback'].read_text())
    feedback['user_content_approval'] = {'scope': 'four_image_set_and_caption'}
    paths['feedback'].write_text(json.dumps(feedback))
    result = module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    db = sqlite3.connect(db_path)
    review = json.loads(db.execute('SELECT review_json FROM pack_editorial').fetchone()[0])
    assert result['pack_review_imported'] is True
    assert review['actor'] == 'assistant' and review['status'] == 'approved'
    assert db.execute("SELECT status FROM daily_packs WHERE id='p001'").fetchone()[0] == 'draft'
    db.close()


def test_unverified_year_and_photograph_dates_are_not_promoted_to_facts(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    examples = json.loads(paths['examples'].read_text())
    row = examples['rows'][0]
    row['attribution']['evidence'] = ['stored_page_url']
    row['dates']['photo_created'] = {'year': 2018, 'evidence_url': 'https://example.test'}
    paths['examples'].write_text(json.dumps(examples))
    module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    db = sqlite3.connect(db_path)
    note = json.loads(db.execute("SELECT annotation_json FROM image_editorial WHERE image_id='one'").fetchone()[0])
    assert all(value is None for value in note['dates'].values())
    assert note['source_verified'] is False
    db.close()


def test_changed_publication_evidence_stops_before_any_import(tmp_path):
    module = migration_module()
    db_path, base, paths = fixture(tmp_path)
    before = module.counts(db_path)
    feedback = json.loads(paths['feedback'].read_text())
    feedback['metric_observations'][0]['platform_status'] = 'published'
    feedback['publication']['published_at'] = '2026-09-13T01:00:00Z'
    paths['feedback'].write_text(json.dumps(feedback))
    import pytest
    with pytest.raises(ValueError, match='under.review'):
        module.migrate(db_path, base, paths['examples'], paths['feedback'], paths['publish_log'])
    assert module.counts(db_path) == before
