#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "image"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def fetch_url(url: str, timeout: int = 20) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def is_direct_image(url: str) -> bool:
    parsed = urlparse(url)
    return any(parsed.path.lower().endswith(ext) for ext in IMAGE_EXTENSIONS) or "images.unsplash.com" in parsed.netloc


def extract_image_from_html(html: str, page_url: str) -> Optional[str]:
    patterns = [
        r'<meta property="og:image" content="([^"]+)"',
        r'<meta name="twitter:image" content="([^"]+)"',
        r'"image":"(https:[^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1).replace("\\u0026", "&").replace("\\/", "/")
    if "unsplash.com" in page_url:
        match = re.search(r'https://images\.unsplash\.com[^"\']+', html)
        if match:
            return match.group(0).replace("\\u0026", "&")
    return None


def resolve_image_url(item: dict) -> str:
    direct = item.get("direct_image")
    if direct:
        return direct

    source_page = item.get("source_page")
    if not source_page:
        raise ValueError(f"Missing source_page for {item.get('title', 'untitled item')}")

    html = fetch_url(source_page).decode("utf-8", errors="ignore")
    image_url = extract_image_from_html(html, source_page)
    if not image_url:
        raise ValueError(f"Could not extract image URL from {source_page}")

    if "images.unsplash.com" in image_url and "w=" not in image_url:
        query = urlencode({"q": 80, "w": 1600, "auto": "format"})
        separator = "&" if "?" in image_url else "?"
        image_url = f"{image_url}{separator}{query}"
    return image_url


def extension_for_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ".jpg"


def download_image(url: str, output_path: Path) -> None:
    output_path.write_bytes(fetch_url(url))


def write_txt(output_dir: Path, date_str: str, manifest: dict, download_results: list[dict]) -> Path:
    lines: list[str] = []
    lines.append(f"Date: {date_str}")
    lines.append(f"Theme: {manifest['theme']}")
    lines.append("")
    lines.append("Why this fits today:")
    lines.append(manifest["why_today"].strip())
    lines.append("")

    trend_sources = manifest.get("trend_sources", [])
    if trend_sources:
        lines.append("Trend sources:")
        for idx, source in enumerate(trend_sources, start=1):
            lines.append(f"{idx}. {source['name']}")
            lines.append(source["url"])
            lines.append(f"Why it matters: {source['why']}")
            lines.append("")

    lines.append("Shared visual pattern:")
    for point in manifest.get("shared_visual_pattern", []):
        lines.append(f"- {point}")
    lines.append("")

    lines.append("Xiaohongshu title ideas:")
    for idx, title in enumerate(manifest.get("title_ideas", []), start=1):
        lines.append(f"{idx}. {title}")
    lines.append("")

    lines.append("Caption draft:")
    lines.append(manifest.get("caption_draft", "").strip())
    lines.append("")

    lines.append("Picks:")
    lines.append("")
    for idx, result in enumerate(download_results, start=1):
        item = result["item"]
        lines.append(f"{idx:02d}. {item['title']}")
        lines.append("Source page:")
        lines.append(item["source_page"])
        if result.get("image_url"):
            lines.append("Direct image:")
            lines.append(result["image_url"])
        lines.append("Reason:")
        lines.append(item["reason"])
        if result.get("file_name"):
            lines.append("Saved file:")
            lines.append(result["file_name"])
        if result.get("error"):
            lines.append("Download error:")
            lines.append(result["error"])
        lines.append("")

    recommended = manifest.get("recommended_9", [])
    if recommended:
        lines.append("Recommended 9 to post first:")
        lines.append(", ".join(f"{value:02d}" for value in recommended))
        lines.append("")

    posting_order = manifest.get("posting_order", [])
    if posting_order:
        lines.append("Posting order suggestion:")
        for entry in posting_order:
            lines.append(entry)
        lines.append("")

    success_count = sum(1 for row in download_results if row.get("file_name"))
    lines.append("Download status:")
    lines.append(f"Downloaded {success_count} / {len(download_results)} images into the dated folder.")

    txt_path = output_dir / f"{date_str}.txt"
    txt_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return txt_path


def run(manifest_path: Path, output_root: Path, date_str: str, limit: int, retries: int, pause_s: float) -> int:
    manifest = read_json(manifest_path)
    output_dir = output_root / date_str
    ensure_dir(output_dir)

    results: list[dict] = []
    successes = 0

    for item in manifest.get("picks", []):
        if successes >= limit:
            break

        result = {"item": item}
        try:
            image_url = resolve_image_url(item)
            result["image_url"] = image_url

            file_slug = slugify(item["title"])
            ext = extension_for_url(image_url)
            file_name = f"{successes + 1:02d}_{file_slug}{ext}"
            output_path = output_dir / file_name

            last_error = None
            for attempt in range(1, retries + 1):
                try:
                    download_image(image_url, output_path)
                    result["file_name"] = file_name
                    successes += 1
                    break
                except (HTTPError, URLError, TimeoutError, OSError) as exc:
                    last_error = f"attempt {attempt}/{retries}: {exc}"
                    time.sleep(pause_s)
            if "file_name" not in result and last_error:
                result["error"] = last_error

        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)

        results.append(result)

    txt_path = write_txt(output_dir, date_str, manifest, results)
    print(f"Output folder: {output_dir}")
    print(f"TXT file: {txt_path}")
    print(f"Downloaded: {successes}/{min(limit, len(manifest.get('picks', [])))}")
    return 0 if successes >= limit else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a dated Xiaohongshu moodboard pack.")
    parser.add_argument("--manifest", required=True, help="Path to the JSON manifest file.")
    parser.add_argument("--output-root", default=".", help="Root folder for dated moodboard output.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Date folder name, format YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=15, help="How many images to download.")
    parser.add_argument("--retries", type=int, default=2, help="Retry count per image.")
    parser.add_argument("--pause", type=float, default=1.0, help="Pause seconds between retries.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(
        manifest_path=Path(args.manifest),
        output_root=Path(args.output_root),
        date_str=args.date,
        limit=args.limit,
        retries=args.retries,
        pause_s=args.pause,
    )


if __name__ == "__main__":
    sys.exit(main())
