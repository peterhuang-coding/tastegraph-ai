import aiosqlite

from taste_graph_ai.config import DB_FILE


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_FILE))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        await db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'mixed',
    discovered_from TEXT,
    preview_thumbnails TEXT DEFAULT '[]',
    ai_score REAL DEFAULT 0.0,
    ai_reason TEXT DEFAULT '',
    ai_risk TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    url TEXT DEFAULT '',
    page_url TEXT DEFAULT '',
    local_path TEXT DEFAULT '',
    thumbnail_path TEXT DEFAULT '',
    keywords_json TEXT DEFAULT '[]',
    graph_score REAL DEFAULT 0.0,
    visual_score REAL DEFAULT 0.0,
    final_score REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS daily_packs (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    theme TEXT DEFAULT '',
    why_today TEXT DEFAULT '',
    title_options_json TEXT DEFAULT '[]',
    caption TEXT DEFAULT '',
    taste_score REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    selected_at TEXT,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS pack_images (
    pack_id TEXT NOT NULL,
    image_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    user_action TEXT NOT NULL DEFAULT 'approved',
    PRIMARY KEY (pack_id, image_id),
    FOREIGN KEY (pack_id) REFERENCES daily_packs(id),
    FOREIGN KEY (image_id) REFERENCES images(id)
);

CREATE TABLE IF NOT EXISTS feedback_log (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    label TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'medium',
    action_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS publish_history (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    platform TEXT DEFAULT 'xiaohongshu',
    post_url TEXT DEFAULT '',
    likes INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    engagement_rate REAL DEFAULT 0.0,
    FOREIGN KEY (pack_id) REFERENCES daily_packs(id)
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
"""
