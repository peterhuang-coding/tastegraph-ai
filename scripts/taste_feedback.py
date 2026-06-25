#!/usr/bin/env python3

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Optional


def load_memory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_memory(path: Path, memory: dict) -> None:
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    seen = {value.lower() for value in values}
    for addition in additions:
        if addition.lower() not in seen:
            values.append(addition)
            seen.add(addition.lower())
    return values


def main() -> int:
    base_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Update the taste memory with human feedback.")
    parser.add_argument("--memory", default=str(base_dir / "taste_memory.json"))
    parser.add_argument("--like", default="", help="Comma-separated keywords or qualities to prefer.")
    parser.add_argument("--avoid", default="", help="Comma-separated keywords or qualities to avoid.")
    parser.add_argument("--channel", default="", help="Comma-separated Are.na channels to prefer.")
    parser.add_argument("--note", default="", help="Freeform feedback note.")
    parser.add_argument("--image", default="", help="Optional image filename or URL this feedback refers to.")
    args = parser.parse_args()

    memory_path = Path(args.memory)
    memory = load_memory(memory_path)

    likes = parse_csv(args.like)
    avoids = parse_csv(args.avoid)
    channels = parse_csv(args.channel)

    memory["prefer"]["keywords"] = append_unique(memory["prefer"].get("keywords", []), likes)
    memory["avoid"]["keywords"] = append_unique(memory["avoid"].get("keywords", []), avoids)
    memory["prefer"]["channels"] = append_unique(memory["prefer"].get("channels", []), channels)

    if args.note or args.image or likes or avoids or channels:
        memory.setdefault("feedback", []).append(
            {
                "date": dt.date.today().isoformat(),
                "image": args.image,
                "like": likes,
                "avoid": avoids,
                "channels": channels,
                "note": args.note
            }
        )

    save_memory(memory_path, memory)
    print(f"Updated taste memory: {memory_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
