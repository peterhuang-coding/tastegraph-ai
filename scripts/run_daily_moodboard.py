#!/usr/bin/env python3

import argparse
import datetime as dt
import sys
from pathlib import Path

from moodboard_fetch import run as fetch_run


def find_manifest(manifest_dir: Path, date_str: str, allow_latest: bool) -> Path:
    dated = manifest_dir / f"{date_str}.json"
    if dated.exists():
        return dated

    if not allow_latest:
        raise FileNotFoundError(f"No manifest found for {date_str}: {dated}")

    manifests = sorted(manifest_dir.glob("*.json"))
    if not manifests:
        raise FileNotFoundError(f"No manifest files found in {manifest_dir}")
    return manifests[-1]


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Run the daily Xiaohongshu moodboard fetch job."
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Target date folder, format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--manifest-dir",
        default=str(base_dir / "manifests"),
        help="Directory containing dated manifest JSON files.",
    )
    parser.add_argument(
        "--output-root",
        default=str(base_dir),
        help="Root output directory for dated moodboard folders.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Number of images to download.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry count per image.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Pause seconds between retries.",
    )
    parser.add_argument(
        "--strict-date",
        action="store_true",
        help="Require a manifest for the exact date instead of falling back to the latest one.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_dir = Path(args.manifest_dir)
    output_root = Path(args.output_root)

    manifest_path = find_manifest(
        manifest_dir=manifest_dir,
        date_str=args.date,
        allow_latest=not args.strict_date,
    )

    print(f"Using manifest: {manifest_path}")
    print(f"Output root: {output_root}")
    print(f"Target date: {args.date}")

    return fetch_run(
        manifest_path=manifest_path,
        output_root=output_root,
        date_str=args.date,
        limit=args.limit,
        retries=args.retries,
        pause_s=args.pause,
    )


if __name__ == "__main__":
    sys.exit(main())
