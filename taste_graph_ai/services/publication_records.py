"""Bridge filesystem curation packs to DB identities and retain platform evidence.

These observations are not user taste votes. Missing timestamps and publication
states stay unknown; only explicit published evidence enters publish_history.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


async def ensure_publication_schema(db):
    # Additive tables only: existing hand-entered packs and history are untouched.
    await db.execute('''CREATE TABLE IF NOT EXISTS publication_pack_links (
        pack_path TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL REFERENCES daily_packs(id),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        imported_at TEXT NOT NULL
    )''')
    await db.execute('''CREATE TABLE IF NOT EXISTS publication_observations (
        id TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL REFERENCES daily_packs(id),
        platform TEXT NOT NULL,
        source TEXT NOT NULL,
        observation_key TEXT,
        observed_at TEXT,
        recorded_at TEXT NOT NULL,
        publication_status TEXT NOT NULL DEFAULT 'unknown',
        published_at TEXT,
        post_url TEXT NOT NULL DEFAULT '',
        likes INTEGER, saves INTEGER, comments INTEGER, shares INTEGER, views INTEGER,
        engagement_score REAL NOT NULL DEFAULT 0,
        raw_json TEXT NOT NULL
    )''')
    await db.execute('''CREATE INDEX IF NOT EXISTS publication_observations_pack
                      ON publication_observations(pack_id, observed_at)''')


def canonical_pack_path(value, base_dir):
    """Accept old posts-relative and new base-relative paths, inside posts only."""
    base = Path(base_dir).resolve()
    posts = (base / 'posts').resolve()
    path = Path(value)
    if not path.is_absolute():
        path = base / path if path.parts and path.parts[0] == 'posts' else posts / path
    path = path.resolve()
    if path == posts or not path.is_relative_to(posts):
        raise ValueError('pack_path must identify a directory inside the configured posts folder')
    return path, path.relative_to(base).as_posix()


async def resolve_publication_pack(db, pack_id, pack_path=None, base_dir=None):
    """Return pack_id/pack_path/missing_image_ids, importing curation additively.

    Explicit IDs (including historical manual p001) take priority over generated
    IDs. Paths use the configured content root, never the code checkout root.
    """
    from taste_graph_ai.config import BASE_DIR
    await ensure_publication_schema(db)
    existing = await (await db.execute('SELECT id FROM daily_packs WHERE id=?', (pack_id,))).fetchone()
    if existing and not pack_path:
        return {'pack_id': pack_id, 'pack_path': None, 'missing_image_ids': []}
    if not pack_path and '/' not in pack_id and '\\' not in pack_id:
        raise FileNotFoundError(f'Pack {pack_id} does not exist; provide pack_path for a filesystem pack')
    directory, relative = canonical_pack_path(pack_path or pack_id, base_dir or BASE_DIR)
    metadata_file = directory / 'curation.json'
    if not metadata_file.is_file():
        raise FileNotFoundError(f'No curation.json for {relative}')
    try:
        metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise ValueError(f'Cannot read curation.json for {relative}: {exc}') from exc
    if not isinstance(metadata, dict) or not isinstance(metadata.get('image_ids', []), list):
        raise ValueError('curation.json must contain an image_ids list')
    explicit_id = metadata.get('pack_id')
    link = await (await db.execute('SELECT pack_id FROM publication_pack_links WHERE pack_path=?', (relative,))).fetchone()
    requested_id = pack_id if pack_path and '/' not in pack_id else None
    candidates = [value for value in (link[0] if link else None, explicit_id, requested_id) if value]
    if len(set(candidates)) > 1:
        raise ValueError(f'Conflicting pack IDs for {relative}')
    resolved_id = candidates[0] if candidates else 'fs_' + hashlib.sha256(relative.encode()).hexdigest()[:20]
    now = datetime.now(timezone.utc).isoformat()
    def read_text(filename):
        path = directory / filename
        return path.read_text(encoding='utf-8').strip() if path.is_file() else ''
    theme = read_text('title.txt') or str(metadata.get('theme') or '')
    # A folder date is a pack date, never evidence of when it was published.
    date = directory.parent.name if len(directory.parent.name) == 10 else ''
    await db.execute('''INSERT OR IGNORE INTO daily_packs
        (id,date,theme,caption,status,created_at,title_options_json)
        VALUES (?,?,?,?,?,?,?)''',
        (resolved_id, date, theme, read_text('body.txt'), 'draft', now,
         json.dumps([theme] if theme else [], ensure_ascii=False)))
    missing = []
    for position, image_id in enumerate(dict.fromkeys(metadata.get('image_ids', []))):
        if not isinstance(image_id, str):
            raise ValueError('curation.image_ids entries must be strings')
        known = await (await db.execute('SELECT id FROM images WHERE id=?', (image_id,))).fetchone()
        if known:
            await db.execute('''INSERT OR IGNORE INTO pack_images
                (pack_id,image_id,position,user_action) VALUES (?,?,?,'unreviewed')''',
                (resolved_id, image_id, position))
        else:
            missing.append(image_id)
    await db.execute('''INSERT INTO publication_pack_links
        (pack_path,pack_id,metadata_json,imported_at) VALUES (?,?,?,?)
        ON CONFLICT(pack_path) DO UPDATE SET metadata_json=excluded.metadata_json''',
        (relative, resolved_id, json.dumps(metadata, ensure_ascii=False, sort_keys=True), now))
    await db.commit()
    return {'pack_id': resolved_id, 'pack_path': relative, 'missing_image_ids': missing}


def _timestamp(value):
    if value in (None, '', 'unknown'):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('Observation and publication times must be ISO timestamps or unknown') from exc
    # Preserve missing timezone; never interpret a legacy local date as UTC now.
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


async def record_publication_observation(db, pack_id, data, score):
    await ensure_publication_schema(db)
    status = data.get('publication_status') or 'unknown'
    status = {'submitted_under_review': 'under_review', '审核中': 'under_review'}.get(status, status)
    if status not in {'unknown', 'draft', 'under_review', 'published', 'rejected', 'removed'}:
        raise ValueError(f'Unknown publication_status: {status}')
    snapshot = {
        'pack_id': pack_id, 'platform': data.get('platform') or 'xiaohongshu',
        'source': data.get('source') or 'manual',
        'observation_key': data.get('observation_key'),
        'observed_at': _timestamp(data.get('observed_at')),
        'publication_status': status, 'published_at': _timestamp(data.get('published_at')),
        'post_url': data.get('post_url') or '',
        **{key: data.get(key) for key in ('likes', 'saves', 'comments', 'shares', 'views')},
    }
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    record_id = 'obs_' + hashlib.sha256(raw.encode()).hexdigest()[:24]
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute('''INSERT OR IGNORE INTO publication_observations
        (id,pack_id,platform,source,observation_key,observed_at,recorded_at,
         publication_status,published_at,post_url,likes,saves,comments,shares,views,engagement_score,raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (record_id, pack_id, snapshot['platform'], snapshot['source'], snapshot['observation_key'],
         snapshot['observed_at'], now, status, snapshot['published_at'], snapshot['post_url'],
         snapshot['likes'], snapshot['saves'], snapshot['comments'], snapshot['shares'], snapshot['views'], score, raw))
    inserted = cursor.rowcount > 0
    if inserted and status == 'published' and snapshot['published_at']:
        # Compatibility projection: one published record per pack/platform. Do
        # not sum cumulative windows or overwrite newer evidence with old data.
        latest = await (await db.execute('''SELECT * FROM publication_observations
            WHERE pack_id=? AND platform=? AND publication_status='published' AND published_at IS NOT NULL
            ORDER BY observed_at DESC, recorded_at DESC, id DESC LIMIT 1''',
            (pack_id, snapshot['platform']))).fetchone()
        history = await (await db.execute('''SELECT * FROM publish_history
            WHERE pack_id=? AND platform=? ORDER BY published_at DESC LIMIT 1''',
            (pack_id, snapshot['platform']))).fetchone()
        history_id = history[0] if history else 'pub_' + hashlib.sha256(
            (pack_id + ':' + snapshot['platform']).encode()).hexdigest()[:20]
        row = dict(latest)
        previous = dict(history) if history else {}
        # A status-only observation supplies no new counters or URL. Keep the
        # compatibility display's last known values while retaining raw nulls.
        for key in ('likes', 'saves', 'comments'):
            if row[key] is None:
                row[key] = previous.get(key, 0)
        if not row['post_url']:
            row['post_url'] = previous.get('post_url', '')
        if all(latest[key] is None for key in ('likes', 'saves', 'comments', 'shares')):
            row['engagement_score'] = previous.get('engagement_rate', 0)
        await db.execute('''INSERT INTO publish_history
            (id,pack_id,published_at,platform,post_url,likes,saves,comments,engagement_rate)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            published_at=excluded.published_at,post_url=excluded.post_url,likes=excluded.likes,
            saves=excluded.saves,comments=excluded.comments,engagement_rate=excluded.engagement_rate''',
            (history_id, pack_id, row['published_at'], row['platform'], row['post_url'],
             row['likes'] or 0, row['saves'] or 0, row['comments'] or 0, row['engagement_score']))
        await db.execute("UPDATE daily_packs SET status='published',published_at=COALESCE(published_at,?) WHERE id=?",
                         (row['published_at'], pack_id))
    await db.commit()
    return {'record_id': record_id, 'inserted': inserted, 'publication_status': status,
            'observed_at': snapshot['observed_at']}
