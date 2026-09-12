#!/usr/bin/env python3
"""Import documented local editorial evidence; default is a read-only rehearsal.

Requires explicit input paths. --apply mutates only the supplied --db. No API,
network, image generation, preference feedback, or platform publishing is used.
"""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from taste_graph_ai.services.editorial import (
    connect, save_annotation, save_pack_review, validate_annotation,
)
from taste_graph_ai.services.publication_records import (
    canonical_pack_path, resolve_publication_pack, record_publication_observation,
)

TABLES = ('images', 'image_editorial', 'pack_editorial', 'editorial_events',
          'daily_packs', 'pack_images', 'publication_pack_links',
          'publication_observations', 'publish_history', 'feedback_log')
STATUS = {'审核中': 'under_review', 'submitted_under_review': 'under_review',
          'under_review': 'under_review', 'published': 'published', '已发布': 'published',
          'rejected': 'rejected', 'removed': 'removed', 'unknown': 'unknown'}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def counts(path):
    with _readonly(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                if table in tables else 0 for table in TABLES}


def _annotation(row):
    observation = row.get('observation', {})
    proposal = row.get('editorial_proposal', {})
    official = 'official_project_page' in row.get('attribution', {}).get('evidence', [])
    dates = {key: None for key in ('photo_created', 'object_original_design', 'project_release', 'page_published')}
    project = row.get('dates', {}).get('project_release')
    # This batch documents the documentary year only. Filenames, ingestion dates,
    # monochrome appearance and unverified keywords cannot date a photograph.
    if (official and isinstance(project, dict) and project.get('year') == 2018
            and project.get('evidence_url', '').rstrip('/') == 'https://www.hustwit.com/rams'):
        dates['project_release'] = {'value': '2018', 'evidence_url': project['evidence_url'],
                                    'note': project.get('scope', '纪录片年份，不是逐图拍摄日期')}
    action = proposal.get('action', '')
    availability = 'excluded' if action == '不进入常规图片候选' else (
        'candidate' if proposal.get('topic') else 'needs_context')
    return {'image_form': observation.get('image_form', ''), 'scene': observation.get('scene', ''),
            'topic_hint': proposal.get('topic', ''),
            'reason': '\n'.join(x for x in (action, proposal.get('reason', '')) if x),
            'availability': availability, 'source_verified': official,
            'source_evidence': row.get('source_page', ''), 'dates': dates}


def _preflight(db_path, base_dir, examples_path, feedback_path, log_path):
    examples, feedback, log = _read(examples_path), _read(feedback_path), _read(log_path)
    rows = examples.get('rows', [])
    if not rows or len({row['image_id'] for row in rows}) != len(rows):
        raise ValueError('Annotation samples must have distinct image IDs')
    for row in rows:
        validate_annotation(_annotation(row), actor='assistant')
    registry = feedback['registry']
    entry_id = registry['entry_id']
    entries = [entry for entry in log if entry.get('id') == entry_id]
    if len(entries) != 1:
        raise ValueError('Expected exactly one matching registry entry')
    folder, relative = canonical_pack_path(registry['pack'], base_dir)
    if canonical_pack_path(entries[0]['pack'], base_dir)[1] != relative:
        raise ValueError('Registry and canonical feedback disagree about pack path')
    manifest = _read(folder / 'curation.json')
    assets = sorted(feedback['assets'], key=lambda row: row['order'])
    ids = [row['id'] for row in assets]
    if not ids or manifest.get('image_ids') != ids:
        raise ValueError('Canonical asset order differs from curation.json; do not modify submitted content')
    with _readonly(db_path) as db:
        missing = [image_id for image_id in {row['image_id'] for row in rows} | set(ids)
                   if not db.execute('SELECT 1 FROM images WHERE id=?', (image_id,)).fetchone()]
        if missing:
            raise ValueError('Missing existing image IDs: ' + ', '.join(sorted(missing)))
        existing = db.execute('SELECT id FROM daily_packs WHERE id=?', (entry_id,)).fetchone()
        if existing:
            stored = [r[0] for r in db.execute('SELECT image_id FROM pack_images WHERE pack_id=? ORDER BY position', (entry_id,))]
            if stored != ids:
                raise ValueError('Registry ID already belongs to a different pack; manual data was preserved')
    if (feedback.get('status') != 'submitted_under_review'
            or feedback.get('publication', {}).get('published_at') not in (None, '')):
        raise ValueError('This bounded migration expects the documented submitted-under-review Rams record')
    # Window labels in publish_log are not observations. Import only the explicit
    # canonical observation list, never fill missing 24h/48h values.
    for observation in feedback.get('metric_observations', []):
        if STATUS.get(observation.get('platform_status')) != 'under_review':
            raise ValueError('This bounded migration only imports documented under-review observations')
        if not observation.get('observed_at') or observation.get('platform_status') not in STATUS:
            raise ValueError('Canonical observations need an explicit time and known status')
        for key in ('likes', 'saves', 'comments', 'shares', 'views'):
            value = observation.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Canonical counters must be nonnegative integers or null')
    return rows, feedback, entries[0], assets


async def _import_publication(db_path, base_dir, feedback, entry):
    import aiosqlite
    db = await aiosqlite.connect(str(db_path), timeout=10)
    db.row_factory = aiosqlite.Row
    await db.execute('PRAGMA foreign_keys=ON')
    try:
        identity = await resolve_publication_pack(db, entry['id'], feedback['registry']['pack'], base_dir)
        publication = feedback.get('publication', {})
        inserted = 0
        for observation in feedback.get('metric_observations', []):
            payload = {key: observation.get(key) for key in ('likes', 'saves', 'comments', 'shares', 'views')}
            payload.update({
                'platform': publication.get('platform', 'xiaohongshu'),
                'source': observation.get('source') or 'documented_local_record',
                'observation_key': observation.get('observation_id'),
                'observed_at': observation['observed_at'],
                'publication_status': STATUS[observation['platform_status']],
                # published_at in the old log actually denotes submission. Only
                # the canonical record can supply a verified publication date.
                'published_at': publication.get('published_at'),
                'post_url': publication.get('post_url') or '',
            })
            result = await record_publication_observation(db, identity['pack_id'], payload, score=0)
            inserted += int(result['inserted'])
        return identity['pack_id'], inserted
    finally:
        await db.close()


def migrate(db_path, base_dir, examples_path, feedback_path, log_path):
    """Apply to an explicitly supplied DB; callers should rehearse a backup first."""
    db_path = Path(db_path)
    rows, feedback, entry, assets = _preflight(db_path, base_dir, examples_path, feedback_path, log_path)
    before = counts(db_path)
    db = connect(db_path)
    try:
        existing = {r[0] for r in db.execute('SELECT image_id FROM image_editorial')}
    finally:
        db.close()
    imported, preserved = 0, []
    for row in rows:
        image_id = row['image_id']
        if image_id in existing:
            preserved.append(image_id)
            continue  # Manual or previously imported annotations are never overwritten.
        save_annotation(db_path, image_id, _annotation(row), actor='assistant')
        imported += 1
    pack_id, observations = asyncio.run(_import_publication(db_path, base_dir, feedback, entry))
    db = connect(db_path)
    try:
        review_exists = bool(db.execute('SELECT 1 FROM pack_editorial WHERE pack_id=?', (pack_id,)).fetchone())
    finally:
        db.close()
    prior_approval = feedback.get('user_content_approval', {}).get('scope') == 'four_image_set_and_caption'
    import_review = not review_exists and prior_approval
    if import_review:
        save_pack_review(db_path, pack_id, {
            'status': 'approved',
            'thesis': feedback.get('group_thesis', ''),
            'sequence_reason': ' → '.join(asset.get('role', '') for asset in assets),
            'images': [{'image_id': asset['id'], 'role': asset.get('role', ''),
                        'evidence': asset.get('visual_evidence', ''),
                        'reason': asset.get('sequence_reason', '')} for asset in assets],
        }, actor='assistant')
    after = counts(db_path)
    if after['feedback_log'] != before['feedback_log'] or after['publish_history'] != before['publish_history']:
        raise RuntimeError('Historical migration unexpectedly changed taste feedback or published history')
    return {'before': before, 'after': after, 'pack_id': pack_id,
            'annotations_imported': imported, 'annotations_preserved': preserved,
            'observations_imported': observations, 'pack_review_imported': import_review,
            'source_sha256': {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                              for path in (examples_path, feedback_path, log_path)}}


def rehearse(db_path, base_dir, examples_path, feedback_path, log_path):
    """SQLite's backup API includes WAL safely; production connection is read-only."""
    with tempfile.TemporaryDirectory(prefix='editorial-migration-') as temporary:
        copy_path = Path(temporary) / 'rehearsal.db'
        with _readonly(db_path) as source, sqlite3.connect(copy_path) as target:
            source.backup(target)
        first = migrate(copy_path, base_dir, examples_path, feedback_path, log_path)
        second = migrate(copy_path, base_dir, examples_path, feedback_path, log_path)
        return {'mode': 'rehearsal_copy', 'source_db': str(Path(db_path).resolve()),
                'first': first, 'second': second, 'idempotent': first['after'] == second['after']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--base-dir', type=Path, required=True)
    parser.add_argument('--examples', type=Path, required=True)
    parser.add_argument('--feedback-record', type=Path, required=True)
    parser.add_argument('--publish-log', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Apply to the explicit --db; default rehearses a temporary backup twice')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    inputs = (args.db, args.base_dir, args.examples, args.feedback_record, args.publish_log)
    result = {'mode': 'applied', **migrate(*inputs)} if args.apply else rehearse(*inputs)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
