#!/usr/bin/env python3
"""
TasteGraph AI — 自动发布到小红书
===============================
从生成好的发布包自动发布到小红书。

用法:
  python3 scripts/auto_publish.py                    # 发布最新的发布包
  python3 scripts/auto_publish.py --post-dir posts/2026-07-10/post-001  # 指定某篇
  python3 scripts/auto_publish.py --all              # 发布所有未发布的帖子
  python3 scripts/auto_publish.py --login            # 首次登录（扫码）
  python3 scripts/auto_publish.py --check-login      # 检查登录状态

流程:
  1. 启动 Chrome（通过 CDP）
  2. 打开小红书创作者中心
  3. 上传图片、填写标题/正文/标签
  4. 点击发布

注意: 使用自动化发布存在被平台风控的风险。建议先用测试号。
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
XHS_DIR = BASE_DIR / "xhs_publisher"
POSTS_DIR = BASE_DIR / "posts"


def check_chrome() -> bool:
    """Check if Google Chrome is installed."""
    for path in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]:
        if os.path.exists(path):
            return True
    # Try which
    result = subprocess.run(["which", "google-chrome", "chrome", "chromium"],
                           capture_output=True, text=True)
    return bool(result.stdout.strip())


def publish_post(post_dir: Path, headless: bool = False) -> bool:
    """Publish a single post using XiaohongshuSkills."""
    title_file = post_dir / "title.txt"
    body_file = post_dir / "body.txt"
    hashtags_file = post_dir / "hashtags.txt"
    image_files = list(post_dir.glob("image.*"))

    if not title_file.exists() or not body_file.exists() or not image_files:
        print(f"  ❌ {post_dir.name}: 缺少必要文件")
        return False

    title = title_file.read_text(encoding="utf-8").strip()
    body = body_file.read_text(encoding="utf-8").strip()
    hashtags = hashtags_file.read_text(encoding="utf-8").strip() if hashtags_file.exists() else ""
    content = f"{body}\n\n{hashtags}" if hashtags else body

    print(f"  发布: {title}")

    cmd = [
        sys.executable, str(XHS_DIR / "publish_pipeline.py"),
        "--title", title,
        "--content", content,
    ]

    # Add local image files
    for img in image_files:
        cmd.extend(["--images", str(img)])

    if headless:
        cmd.append("--headless")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print(f"  ✅ {post_dir.name}: 发布成功")
            return True
        elif result.returncode == 1:
            print(f"  ❌ {post_dir.name}: 未登录（请先运行 --login）")
            return False
        else:
            print(f"  ❌ {post_dir.name}: 发布失败")
            print(f"     {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ {post_dir.name}: 超时")
        return False


def main():
    parser = argparse.ArgumentParser(description="自动发布到小红书")
    parser.add_argument("--post-dir", default=None, help="指定发布某篇帖子")
    parser.add_argument("--all", action="store_true", help="发布所有未发布的帖子")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器窗口）")
    parser.add_argument("--login", action="store_true", help="首次登录（扫码）")
    parser.add_argument("--check-login", action="store_true", help="检查登录状态")
    args = parser.parse_args()

    if not check_chrome():
        print("❌ 未找到 Google Chrome。请先安装 Chrome。")
        sys.exit(1)

    # 登录
    if args.login:
        print("🔐 打开浏览器进行扫码登录...")
        cmd = [sys.executable, str(XHS_DIR / "cdp_publish.py"), "login"]
        subprocess.run(cmd)
        return

    # 检查登录
    if args.check_login:
        cmd = [sys.executable, str(XHS_DIR / "cdp_publish.py"), "check-login"]
        subprocess.run(cmd)
        return

    # 找发布包
    if args.post_dir:
        post_dir = Path(args.post_dir)
        if not post_dir.exists():
            print(f"❌ 未找到: {post_dir}")
            sys.exit(1)
        publish_post(post_dir, headless=args.headless)
    elif args.all:
        # 找最新的日期目录
        date_dirs = sorted(POSTS_DIR.glob("20*"), reverse=True)
        if not date_dirs:
            print("❌ 没有发布包")
            sys.exit(1)
        for date_dir in date_dirs:
            post_dirs = sorted(date_dir.glob("post-*"))
            if not post_dirs:
                continue
            print(f"\n📅 {date_dir.name} ({len(post_dirs)} 篇)")
            for post_dir in post_dirs:
                publish_post(post_dir, headless=args.headless)
                time.sleep(3)  # 发布间隔，避免风控
    else:
        # 找最新的未发布帖子
        date_dirs = sorted(POSTS_DIR.glob("20*"), reverse=True)
        if not date_dirs:
            print("❌ 没有发布包。先运行: python3 scripts/pipeline.py --publish-only")
            sys.exit(1)
        latest = date_dirs[0]
        post_dirs = sorted(latest.glob("post-*"))
        if not post_dirs:
            print(f"❌ {latest.name} 下没有帖子")
            sys.exit(1)
        # 只发第一篇
        publish_post(post_dirs[0], headless=args.headless)


if __name__ == "__main__":
    main()