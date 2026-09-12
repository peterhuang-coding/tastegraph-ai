"""Explicit source evidence shared by crawler, ingestion and editorial review.

Provenance can precede download: image_id initially uses the ingestion URL hash;
content dedup must relink it to the retained images.id. Observation/publication
timestamps are never treated as a date of the photograph or depicted object.
"""
import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse


PROVENANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_provenance (
    id TEXT PRIMARY KEY,
    image_id TEXT NOT NULL,
    ingestion_item_id TEXT NOT NULL DEFAULT '',
    source_id TEXT,
    discovery_url TEXT NOT NULL DEFAULT '',
    page_url TEXT NOT NULL DEFAULT '',
    canonical_url TEXT NOT NULL DEFAULT '',
    page_kind TEXT NOT NULL DEFAULT 'unknown' CHECK(page_kind IN ('entry','detail','unknown')),
    page_title TEXT NOT NULL DEFAULT '',
    page_author TEXT NOT NULL DEFAULT '',
    alt_text TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    image_author TEXT NOT NULL DEFAULT '',
    surrounding_text TEXT NOT NULL DEFAULT '',
    page_published_at TEXT NOT NULL DEFAULT '',
    original_date_text TEXT NOT NULL DEFAULT '',
    date_evidence TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS idx_image_provenance_image ON image_provenance(image_id);
"""


def ensure_provenance_schema(con):
    """Add the evidence table idempotently, without rewriting any existing data."""
    # execute() avoids executescript() implicitly committing the caller's work.
    for statement in PROVENANCE_SCHEMA.split(';'):
        if statement.strip():
            con.execute(statement)


def is_site_asset(url: str, alt: str = '') -> bool:
    """Conservative website chrome filter; products and design work remain valid."""
    path = unquote(urlparse(url).path).lower()
    name = PurePosixPath(path).stem
    if PurePosixPath(path).suffix in {'.svg', '.ico', '.gif'}:
        return True  # Existing crawler format exclusions.
    if any(part in path for part in ('/static/chrome/', '/assets/icons/', '/tracking/')):
        return True
    if re.search(r'(^|[-_.])(site[-_]?logo|custom[-_]?logo|header[-_]?logo|footer[-_]?logo|favicon|sprite|loader|loading|tracking[-_]?pixel)([-_.]|$)', name):
        return True
    if '/assets/' in path and re.fullmatch(r'logo[-_]\d+x\d+', name):
        return True
    if name in {'logo', 'icon', 'avatar', 'pixel', 'blank', 'spacer', 'placeholder'}:
        return True
    return alt.strip().lower() in {'site logo', 'website logo', 'loading spinner', 'tracking pixel'}


def classify_page(url: str) -> str:
    """URL-only hint for scheduling; fetched structured metadata may refine it."""
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return 'unknown'
    parts = [part.lower() for part in parsed.path.strip('/').split('/') if part]
    collections = {'index.html', 'index.php', 'home', 'archive', 'archives', 'works',
                   'work', 'projects', 'articles', 'stories', 'news', 'journal', 'blog',
                   'shop', 'products', 'collections', 'gallery', 'galleries', 'portfolio'}
    exact_entries = {'fashion','fashion-shows','artanddesign','sneakers','video','en-us/editorial',
                     'the-hs-style-guide','l/hs-style-guide','style','fashion-shows/designer'}
    path = '/'.join(parts)
    if (path in exact_entries or path.startswith('preference/edition/')
            or path.startswith('fashion-shows/designer/') or path.startswith('brands/')
            or 'change-language' in parts or any(part.startswith('category:') for part in parts)):
        return 'entry'
    if not parts or (len(parts) == 1 and parts[0] in collections):
        return 'entry'
    if any(part in {'category', 'categories', 'tag', 'tags', 'page', 'search', 'author'} for part in parts):
        return 'entry'
    return 'detail' if len(parts) > 1 else 'unknown'


def save_image_provenance(con, image_id, item_id, source_id, record, image, observed_at):
    """Keep one observation per image URL and fetched page, preserving richer evidence."""
    page_url = record.get('page_url') or record.get('url') or ''
    image_url = image.get('url') or image.get('src') or ''
    identity = hashlib.sha256(f'{image_url}\n{page_url}'.encode()).hexdigest()
    page_kind = record.get('page_kind') or classify_page(page_url)
    if page_kind not in {'entry', 'detail', 'unknown'}:
        page_kind = 'unknown'
    date_evidence = image.get('date_evidence') or ''
    values = {
        'id': identity, 'image_id': image_id, 'ingestion_item_id': item_id,
        'source_id': source_id,
        'discovery_url': record.get('discovery_url') or record.get('parent_url') or record.get('url') or '',
        'page_url': page_url, 'canonical_url': record.get('canonical_url') or page_url,
        'page_kind': page_kind, 'page_title': record.get('page_title') or record.get('title') or '',
        'page_author': record.get('page_author') or '', 'alt_text': image.get('alt') or '',
        'caption': image.get('caption') or '', 'image_author': image.get('image_author') or '',
        'surrounding_text': image.get('surrounding_text') or '',
        'page_published_at': record.get('page_published_at') or '',
        'original_date_text': (image.get('original_date_text') or '') if date_evidence else '',
        'date_evidence': date_evidence, 'observed_at': record.get('collected_at') or observed_at,
    }
    # Repeat collection can add missing captions, but must not erase prior evidence.
    updates = ', '.join(
        f"{key}=COALESCE(NULLIF(excluded.{key}, ''), image_provenance.{key})"
        for key in values if key not in {'id', 'image_id'}
    )
    con.execute(f"INSERT INTO image_provenance ({', '.join(values)}) "
                f"VALUES ({', '.join('?' for _ in values)}) ON CONFLICT(id) DO UPDATE SET {updates}",
                tuple(values.values()))


def link_downloaded_image(con, pending_image_id, actual_image_id):
    """Bind all pages for a URL to the retained image, including checksum duplicates."""
    con.execute('UPDATE image_provenance SET image_id=? WHERE image_id=?',
                (actual_image_id, pending_image_id))
