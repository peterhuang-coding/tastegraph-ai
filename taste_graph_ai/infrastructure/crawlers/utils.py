"""Shared crawler utilities — URL filtering, normalization, validation.

Extracted from web.py and playwright_crawler.py to eliminate duplication.
Single source of truth for all image-URL heuristics.
"""

import re
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image as PILImage

# ── Constants ──────────────────────────────────────────────────

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_DIMENSION = 200  # minimum width or height in pixels

# URL patterns that indicate tiny/low-quality/non-content images.
# Expanded from the original _SKIP_URL_PATTERNS to cover more
# false-positive sources discovered from 3,431 scrape failures.
BAD_URL_PATTERNS = [
    # Original patterns
    "logo", "icon", "avatar", "pixel", "1x1", "tracking",
    "thumbnail", "thumb-", "-thumb", "_thumb", "favicon",
    "button-", "banner-", "sidebar-",
    # Newly added — derived from scrape failure analysis
    "bg_", "background", "arrow", "sponsor", "ad_", "ad-",
    "placeholder", "loading", "sprite", "dot_", "bullet",
    "separator", "divider", "header-", "footer-", "nav-",
    "menu-", "close-", "search-", "cart-", "social-",
    "share-", "print-", "email-", "rss-", "feed-",
    # Common tracking / analytics pixels
    "pixel.gif", "pixel.png", "beacon", "collect",
]

# CDN resizing patterns — strip to get original/full-size
_CDN_SIZE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\.width-\d+", re.I), ""),          # .width-30 → remove
    (re.compile(r"\.fill-\d+x\d+", re.I), ""),        # .fill-30x12 → remove
    (re.compile(r"\.fit-\d+x\d+", re.I), ""),         # .fit-100x100 → remove
    (re.compile(r"w_\d+,"), "w_1200,"),               # Cloudinary w_100 → w_1200
    (re.compile(r"h_\d+,"), ""),                      # Cloudinary h_100 → remove
    (re.compile(r"c_limit,"), "c_limit,"),            # keep
]

# Patterns for non-content page paths (used in pagination / article discovery)
SKIP_PAGE_PATTERNS = [
    "about", "contact", "login", "signup", "subscribe",
    "privacy", "terms", "policy", "faq", "cart", "search",
    "account", "wishlist", "newsletter", "cdn.", "static.",
    "assets", "cdn-", "images/", "upload", "wp-content",
    "wp-admin", "wp-json", "tag/", "author/", "page/",
    "category/", ".jpg", ".png", ".webp", ".gif", ".mp4",
    "#", "javascript:",
]


# ── URL normalization ──────────────────────────────────────────

def normalize_url(url: str, page_url: str = "") -> str:
    """Normalize a URL: strip whitespace, resolve relative paths, handle protocol-less URLs."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("data:"):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/") and page_url:
        url = urljoin(page_url, url)
    return url


def upgrade_cdn_url(url: str) -> str:
    """Strip CDN resizing params to get the largest available version."""
    for pattern, replacement in _CDN_SIZE_PATTERNS:
        url = pattern.sub(replacement, url)
    return url


# ── URL quality checks ─────────────────────────────────────────

def is_bad_url(url: str) -> bool:
    """Reject URLs that match known low-quality/image-free patterns."""
    lower = url.lower()
    for pat in BAD_URL_PATTERNS:
        if pat in lower:
            return True
    return False


def is_image_url(url: str) -> bool:
    """Check if URL points to an image file (by extension) or likely photo content."""
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True
    # Heuristic: path contains "photo" — common for CDN photo URLs
    return "photo" in path


def is_likely_content_image(url: str) -> bool:
    """Heuristic check: is this URL likely a real content image (not UI element)?

    Returns True if the URL passes basic quality filters:
    - Has an image extension or photo-like path
    - Is not in the bad-URL list
    - Has enough path segments to be a real asset
    """
    if not url:
        return False
    if not is_image_url(url):
        return False
    if is_bad_url(url):
        return False
    # Filter paths that are too short to be real content images
    path = urlparse(url).path.strip("/")
    if not path or len(path) < 4:
        return False
    return True


# ── Image filename / extension ─────────────────────────────────

def guess_ext(url: str) -> str:
    """Guess file extension from URL path."""
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ".jpg"


# ── srcset parsing ─────────────────────────────────────────────

def best_srcset_url(srcset: str, page_url: str = "") -> str | None:
    """Pick the highest-resolution URL from a srcset attribute."""
    candidates: list[tuple[int, str]] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.rsplit(" ", 1)
        url = tokens[0].strip()
        if len(tokens) == 2:
            try:
                w = int(tokens[1].rstrip("w").strip())
            except ValueError:
                w = 0
        else:
            w = 0
        url = normalize_url(url, page_url)
        if url:
            candidates.append((w, url))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ── Image dimension validation ─────────────────────────────────

def check_dimensions(filepath: Path, min_dim: int = MIN_IMAGE_DIMENSION) -> bool:
    """Returns True if the image meets minimum dimension requirements.

    Falls back to True on error (keep the image if we can't check).
    """
    try:
        with PILImage.open(filepath) as img:
            w, h = img.size
            return min(w, h) >= min_dim
    except Exception:
        return True  # Keep the image if we can't check dimensions


# ── Alt text cleaning ──────────────────────────────────────────

def clean_alt_text(alt: str) -> list[str]:
    """Filter garbage alt text (auto-generated accessibility descriptions).

    Returns cleaned list of useful keywords, or empty list if all garbage.
    """
    if not alt:
        return []
    alt_lower = alt.lower().strip()

    # Skip auto-generated patterns
    garbage_patterns = [
        "image may contain", "person standing", "person sitting",
        "indoor", "outdoor", "no description available", "untitled",
        "picture of", "photo of", "photograph of", "image of",
        "img", "image", "picture", "photo",
    ]
    if any(p in alt_lower for p in garbage_patterns):
        return []

    # Skip if too long (likely a sentence, not keywords)
    if len(alt) > 60:
        return []

    # Split on common separators
    parts = re.split(r'[,;，；、\s]+', alt.strip())
    cleaned = [p.strip() for p in parts if 2 <= len(p.strip()) <= 30]
    return cleaned[:5]


# ── Filename generation ────────────────────────────────────────

def generate_image_filename(url: str) -> str:
    """Generate a unique filename for a downloaded image."""
    img_id = uuid.uuid4().hex[:12]
    ext = guess_ext(url)
    return f"{img_id}{ext}"
