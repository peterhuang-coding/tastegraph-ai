#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_CHANNELS = [
    "brian-curran/jjjjound-full-archive",
    "lily-clempson-tfz8voo8tzo/editorial-fashion",
    "jeremy-turner/photography-editorial-lifestyle-fashion",
]

MIN_BYTES = 180_000
MIN_WIDTH = 900
MIN_HEIGHT = 900
MAX_ASPECT_RATIO = 2.4


def load_taste_memory(path: Optional[Path]) -> dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:80] or "arena_image"


def fetch_json(url: str, timeout: int = 30) -> dict:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def image_url_from_block(block: dict) -> Optional[str]:
    image = block.get("image") or {}
    for size in ("original", "large", "display", "square"):
        value = image.get(size)
        if isinstance(value, dict) and value.get("url"):
            return value["url"]
        if isinstance(value, str):
            return value
    return None


def block_source_url(block: dict) -> str:
    source = block.get("source") or {}
    if isinstance(source, dict) and source.get("url"):
        return source["url"]
    return f"https://www.are.na/block/{block.get('id')}"


def channel_url(channel_path: str) -> str:
    return f"https://www.are.na/{channel_path}"


def api_url_for_channel(channel_path: str, page: int, per: int) -> str:
    encoded = quote(channel_path, safe="/")
    return f"https://api.are.na/v2/channels/{encoded}?page={page}&per={per}&sort=position"


def iter_channel_blocks(channel_path: str, pages: int, per: int) -> list[dict]:
    blocks: list[dict] = []
    for page in range(1, pages + 1):
        data = fetch_json(api_url_for_channel(channel_path, page=page, per=per))
        contents = data.get("contents") or []
        if not contents:
            break
        for block in contents:
            if block.get("class") == "Image" or image_url_from_block(block):
                blocks.append(block | {"_channel_path": channel_path})
        if len(contents) < per:
            break
    return blocks


def jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if not data.startswith(b"\xff\xd8"):
        return None
    idx = 2
    while idx < len(data):
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9}:
            continue
        if idx + 2 > len(data):
            return None
        length = int.from_bytes(data[idx : idx + 2], "big")
        if marker in range(0xC0, 0xC4) or marker in range(0xC5, 0xC8) or marker in range(0xC9, 0xCC) or marker in range(0xCD, 0xD0):
            if idx + 7 > len(data):
                return None
            height = int.from_bytes(data[idx + 3 : idx + 5], "big")
            width = int.from_bytes(data[idx + 5 : idx + 7], "big")
            return width, height
        idx += length
    return None


def png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    return jpeg_dimensions(data) or png_dimensions(data)


def is_quality_image(data: bytes) -> tuple[bool, str]:
    if len(data) < MIN_BYTES:
        return False, f"too small: {len(data)} bytes"
    dims = dimensions(data)
    if not dims:
        return False, "unsupported image type or missing dimensions"
    width, height = dims
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return False, f"resolution too low: {width}x{height}"
    aspect = max(width / height, height / width)
    if aspect > MAX_ASPECT_RATIO:
        return False, f"aspect ratio too extreme: {width}x{height}"
    return True, f"{width}x{height}, {len(data)} bytes"


def extension_for_data(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    return ".jpg"


def collect_candidates(channels: list[str], pages: int, per: int) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()
    for channel in channels:
        blocks = iter_channel_blocks(channel, pages=pages, per=per)
        for block in blocks:
            image_url = image_url_from_block(block)
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            title = block.get("title") or "Are.na moodboard reference"
            candidates.append(
                {
                    "title": title,
                    "image_url": image_url,
                    "source_page": f"https://www.are.na/block/{block.get('id')}",
                    "original_source": block_source_url(block),
                    "channel": channel,
                    "channel_url": channel_url(channel),
                }
            )
    return candidates


def candidate_text(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(key, ""))
        for key in ("title", "source_page", "original_source", "channel", "channel_url")
    ).lower()


def score_candidate(candidate: dict, memory: dict) -> tuple[int, list[str]]:
    if not memory:
        return 0, []

    weights = memory.get("score_weights", {})
    prefer = memory.get("prefer", {})
    avoid = memory.get("avoid", {})
    text = candidate_text(candidate)
    score = 0
    reasons: list[str] = []

    preferred_keyword_weight = int(weights.get("preferred_keyword", 3))
    avoided_keyword_weight = int(weights.get("avoided_keyword", -6))
    preferred_channel_weight = int(weights.get("preferred_channel", 8))
    source_bonus = int(weights.get("source_bonus", 2))

    for keyword in prefer.get("keywords", []):
        if keyword.lower() in text:
            score += preferred_keyword_weight
            reasons.append(f"+{keyword}")

    for keyword in avoid.get("keywords", []):
        if keyword.lower() in text:
            score += avoided_keyword_weight
            reasons.append(f"-{keyword}")

    if candidate.get("channel") in prefer.get("channels", []):
        score += preferred_channel_weight
        reasons.append("+preferred-channel")

    if candidate.get("original_source") and candidate.get("original_source") != candidate.get("source_page"):
        score += source_bonus
        reasons.append("+external-source")

    return score, reasons


def rank_candidates(candidates: list[dict], memory: dict, shuffle: bool) -> list[dict]:
    ranked = []
    for candidate in candidates:
        score, reasons = score_candidate(candidate, memory)
        ranked.append(candidate | {"taste_score": score, "taste_reasons": reasons})
    if shuffle:
        random.shuffle(ranked)
    return sorted(ranked, key=lambda row: row.get("taste_score", 0), reverse=True)


def write_txt(output_dir: Path, date_str: str, theme: str, results: list[dict], rejected: list[dict]) -> None:
    lines: list[str] = []
    lines.append(f"Date: {date_str}")
    lines.append(f"Theme: {theme}")
    lines.append("")
    lines.append("Source strategy:")
    lines.append("Pulled from public Are.na moodboard/channel contents, not from local videos and not generated placeholders.")
    lines.append("")
    lines.append("Taste strategy:")
    lines.append("Candidates are ranked using taste_memory.json before downloading. Human feedback should update that memory over time.")
    lines.append("")
    lines.append("Quality gate:")
    lines.append(f"- min file size: {MIN_BYTES} bytes")
    lines.append(f"- min resolution: {MIN_WIDTH}x{MIN_HEIGHT}")
    lines.append(f"- max aspect ratio: {MAX_ASPECT_RATIO}")
    lines.append("- no local source files")
    lines.append("- no placeholder generation")
    lines.append("")
    lines.append("Downloaded picks:")
    lines.append("")
    for idx, row in enumerate(results, start=1):
        lines.append(f"{idx:02d}. {row['title']}")
        lines.append(f"Saved file: {row['file_name']}")
        lines.append(f"Are.na block: {row['source_page']}")
        lines.append(f"Original source: {row['original_source']}")
        lines.append(f"Curated channel: {row['channel_url']}")
        lines.append(f"Image URL: {row['image_url']}")
        lines.append(f"Quality: {row['quality']}")
        lines.append(f"Taste score: {row.get('taste_score', 0)}")
        if row.get("taste_reasons"):
            lines.append(f"Taste reasons: {', '.join(row['taste_reasons'])}")
        lines.append("")
    lines.append("Rejected candidates:")
    for row in rejected[:40]:
        lines.append(f"- {row.get('title', 'untitled')} | {row.get('reason', 'unknown')}")
    lines.append("")
    if len(results) >= 9:
        lines.append("Recommended use:")
        lines.append("Pick 9 from the downloaded set after visual review. Do not repost copyrighted/editorial imagery without checking usage rights or adding proper credit; safest use is as a private reference board or inspiration for your own shoots.")
    else:
        lines.append("Run status:")
        lines.append("Not enough usable images were downloaded. Do not post this folder as a Xiaohongshu moodboard.")
    (output_dir / f"{date_str}.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    date_str = args.date
    output_dir = Path(args.output_root) / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    channels = args.channel or DEFAULT_CHANNELS
    taste_memory = load_taste_memory(Path(args.taste_memory) if args.taste_memory else None)
    if taste_memory and not args.channel:
        channels = taste_memory.get("prefer", {}).get("channels", channels) or channels
    try:
        candidates = collect_candidates(channels, pages=args.pages, per=args.per)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        failure_txt = output_dir / f"{date_str}.txt"
        failure_txt.write_text(
            "\n".join(
                [
                    f"Date: {date_str}",
                    f"Theme: {args.theme}",
                    "",
                    "Run status:",
                    "Failed before downloading because the current environment could not reach the curated moodboard source.",
                    "",
                    "Important:",
                    "No placeholder images were generated.",
                    "No local video frames were used.",
                    "This folder should not be posted until the script successfully downloads 15 real images.",
                    "",
                    "Error:",
                    str(exc),
                    "",
                    "Suggested fix:",
                    "Run the same command from a network environment that can resolve api.are.na and image hosts.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Output folder: {output_dir}")
        print(f"TXT file: {failure_txt}")
        print("Downloaded real images: 0/15")
        print(f"Network failure: {exc}", file=sys.stderr)
        return 1
    candidates = rank_candidates(candidates, taste_memory, shuffle=args.shuffle)

    results: list[dict] = []
    rejected: list[dict] = []
    for candidate in candidates:
        if len(results) >= args.limit:
            break
        try:
            data = fetch_bytes(candidate["image_url"], timeout=args.timeout)
            ok, reason = is_quality_image(data)
            if not ok:
                rejected.append(candidate | {"reason": reason})
                continue
            file_name = f"{len(results) + 1:02d}_{slugify(candidate['title'])}{extension_for_data(data)}"
            (output_dir / file_name).write_bytes(data)
            results.append(candidate | {"file_name": file_name, "quality": reason})
            time.sleep(args.pause)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            rejected.append(candidate | {"reason": str(exc)})

    write_txt(output_dir, date_str, args.theme, results, rejected)
    print(f"Output folder: {output_dir}")
    print(f"Downloaded real images: {len(results)}/{args.limit}")
    if len(results) < args.limit:
        print("Failed quality gate: not enough real moodboard images downloaded.", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Fetch real curated moodboard images from public Are.na channels.")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--output-root", default=str(base_dir))
    parser.add_argument("--theme", default="curated Are.na moodboard / quiet cool references")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--per", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--pause", type=float, default=0.2)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--channel", action="append", help="Are.na channel path, e.g. user/slug. Can be repeated.")
    parser.add_argument("--taste-memory", default=str(base_dir / "taste_memory.json"))
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(run(parse_args()))
