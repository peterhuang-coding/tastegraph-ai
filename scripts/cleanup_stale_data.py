#!/usr/bin/env python3
"""
tape — 数据清理脚本
========================
清理过期图片、知识图谱节点去重、日志轮转。

用法:
  python3 scripts/cleanup_stale_data.py            # 执行清理
  python3 scripts/cleanup_stale_data.py --dry-run  # 预览不删除
  python3 scripts/cleanup_stale_data.py --days 60  # 60天未用算过期
"""

import argparse
import difflib
import gzip
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "taste_graph.db"
EVENTS_LOG = DATA_DIR / "events.log"
BACKUPS_DIR = DATA_DIR / "backups"

DEFAULT_STALE_DAYS = 30


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def cleanup_stale_images(dry_run: bool = False, stale_days: int = DEFAULT_STALE_DAYS) -> int:
    """Delete images not used in the last N days. Returns number of deleted files."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    deleted = 0
    skipped = 0

    for img_path in sorted(IMAGES_DIR.glob("*")):
        if not img_path.is_file():
            continue
        mtime = datetime.fromtimestamp(img_path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            if dry_run:
                print(f"  [dry-run] 删除: {img_path.name} (最后使用 {mtime.strftime('%Y-%m-%d')})")
            else:
                img_path.unlink()
                print(f"  ✅ 删除: {img_path.name}")
            deleted += 1
        else:
            skipped += 1

    print(f"  图片清理: {deleted} 张删除, {skipped} 张保留")
    return deleted


def rotate_logs(dry_run: bool = False) -> int:
    """Compress and rotate events.log if over 1MB. Returns bytes saved."""
    if not EVENTS_LOG.exists():
        return 0

    size = EVENTS_LOG.stat().st_size
    if size < 1_000_000:
        return 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    gz_path = EVENTS_LOG.with_name(f"events-{date_str}.log.gz")

    if dry_run:
        print(f"  [dry-run] 压缩: {EVENTS_LOG.name} ({size/1024:.0f}KB → {gz_path.name})")
        return size

    with open(EVENTS_LOG, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    # 清空原日志（不删除文件）
    with open(EVENTS_LOG, "w") as f:
        f.write("")

    saved = size - gz_path.stat().st_size
    print(f"  ✅ 日志轮转: {EVENTS_LOG.name} → {gz_path.name} (节省 {saved/1024:.0f}KB)")
    return saved


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance (case-insensitive) using Wagner-Fischer."""
    a, b = a.lower(), b.lower()
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            tmp = dp[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = tmp
    return dp[m]


def _text_similarity(a: str, b: str) -> float:
    """Compute text similarity using SequenceMatcher."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _load_graph() -> dict:
    """Load taste graph JSON file."""
    graph_path = DATA_DIR / "taste_graph.json"
    if not graph_path.exists():
        print(f"  ❌ 图谱文件不存在: {graph_path}")
        return {"nodes": [], "edges": []}
    with open(graph_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_graph(graph: dict, dry_run: bool = False):
    """Save taste graph JSON file."""
    if dry_run:
        return
    graph_path = DATA_DIR / "taste_graph.json"
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)


def dedup_graph(dry_run: bool = False, threshold: int = 3):
    """Deduplicate nodes in the taste graph using Levenshtein distance."""
    graph = _load_graph()
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    print(f"  图谱加载: {len(nodes)} 节点, {len(edges)} 条边")

    # Build node lookup
    node_map = {n["id"]: n for n in nodes}
    removed = set()
    replacements = {}  # removed_id -> keep_id

    # Compare all pairs of same type
    by_type = {}
    for n in nodes:
        by_type.setdefault(n.get("type", "unknown"), []).append(n)

    for ntype, type_nodes in by_type.items():
        for i in range(len(type_nodes)):
            for j in range(i + 1, len(type_nodes)):
                a, b = type_nodes[i], type_nodes[j]
                dist = _edit_distance(a.get("label", ""), b.get("label", ""))
                if dist < threshold:
                    # Keep the one with higher weight
                    wa = a.get("properties", {}).get("weight", 1) or 1
                    wb = b.get("properties", {}).get("weight", 1) or 1
                    keep, drop = (a, b) if wa >= wb else (b, a)
                    if drop["id"] not in removed:
                        removed.add(drop["id"])
                        replacements[drop["id"]] = keep["id"]
                        sim = _text_similarity(a.get("label", ""), b.get("label", ""))
                        print(f"  🔗 合并: '{a['label']}' (w={wa}) + '{b['label']}' (w={wb}) "
                              f"→ 保留 '{keep['label']}' (编辑距离={dist}, 相似度={sim:.0%})")

    if not removed:
        print("  ✅ 没有发现重复节点")
        return

    # Merge edges: redirect references from removed nodes to kept nodes
    merged_count = 0
    new_edges = []
    edge_key_seen = set()
    for e in edges:
        src = replacements.get(e["source"], e["source"])
        tgt = replacements.get(e["target"], e["target"])
        if src == tgt:
            continue  # self-loop after merge, drop
        key = (src, tgt, e.get("relation", ""))
        if key in edge_key_seen:
            merged_count += 1
            continue  # duplicate edge, skip
        edge_key_seen.add(key)
        new_edge = dict(e)
        new_edge["source"] = src
        new_edge["target"] = tgt
        new_edges.append(new_edge)

    # Filter out removed nodes
    new_nodes = [n for n in nodes if n["id"] not in removed]

    graph["nodes"] = new_nodes
    graph["edges"] = new_edges

    if not dry_run:
        _save_graph(graph)
        print(f"\n  ✅ 去重完成: 移除 {len(removed)} 个节点, 合并 {merged_count} 条边")
        print(f"     结果: {len(new_nodes)} 节点, {len(new_edges)} 条边")
    else:
        print(f"\n  [dry-run] 将移除 {len(removed)} 个节点, 合并 {merged_count} 条边")
        print(f"     结果: {len(new_nodes)} 节点, {len(new_edges)} 条边 (dry-run, 未写入)")

    # Verify no dangling references
    valid_ids = {n["id"] for n in new_nodes}
    dangling = [e for e in new_edges if e["source"] not in valid_ids or e["target"] not in valid_ids]
    if dangling:
        print(f"  ⚠️ 警告: 发现 {len(dangling)} 条悬空边")


def main():
    parser = argparse.ArgumentParser(description="tape 数据清理工具")
    parser.add_argument("--dry-run", action="store_true", help="预览不删除")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_DAYS, help="过期天数 (默认: 30)")
    parser.add_argument("--skip-images", action="store_true", help="跳过图片清理")
    parser.add_argument("--skip-logs", action="store_true", help="跳过日志轮转")
    parser.add_argument("--dedup", action="store_true", help="执行知识图谱节点去重")
    parser.add_argument("--threshold", type=int, default=3, help="去重编辑距离阈值 (默认: 3)")
    args = parser.parse_args()

    mode = "预览模式" if args.dry_run else "执行模式"
    print(f"🔍 数据清理 ({mode})")

    if not args.skip_images:
        print(f"\n📸 清理过期图片 (>{args.days}天未使用)...")
        cleanup_stale_images(dry_run=args.dry_run, stale_days=args.days)

    if not args.skip_logs:
        print(f"\n📝 日志轮转...")
        rotate_logs(dry_run=args.dry_run)

    if args.dedup:
        print(f"\n🔗 知识图谱去重 (阈值={args.threshold})...")
        dedup_graph(dry_run=args.dry_run, threshold=args.threshold)

    print(f"\n✅ 清理完成")


if __name__ == "__main__":
    main()
