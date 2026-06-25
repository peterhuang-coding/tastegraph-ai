#!/usr/bin/env python3
"""小红书自动发布 — 独立入口

用法：

    # ===== 第一步：首次登录 =====
    TASTEGRAPH_XHS_HEADFUL=1 python main.py login
    → 打开浏览器 → 扫码登录小红书 → Cookie 自动保存 → 关闭

    # ===== 第二步：导出图片 =====
    python main.py compose --images ./mock_data/ --title "今天的好东西" --caption "安静看一会儿"
    → 把 mock_data/ 下前 9 张图拼成 3x3 网格 → 保存到 exports/

    # ===== 第三步：发布 =====
    python main.py publish --image exports/moodboard_1717280000.png --title "沉默的质感" --caption "不争不抢..."
    → 用已保存的 Cookie 登录 → 上传 → 填标题/正文 → 点发布 → 打印帖子链接

    # ===== 一键合成+发布 =====
    python main.py run --images ./mock_data/ --title "今天的推荐" --caption "..."
    → compose + publish 一步完成

环境变量：
    TASTEGRAPH_XHS_HEADFUL=1   显示浏览器窗口（调试用）
    XHS_COOKIES_FILE=xxx.json  指定 Cookie 文件路径
    XHS_EXPORTS_DIR=./out      指定导出目录

依赖安装：
    pip install playwright Pillow
    playwright install chromium
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from modules.xhs_publisher.config import EXPORTS_DIR
from modules.xhs_publisher.composer import MoodboardComposer
from modules.xhs_publisher.publisher import XiaohongshuPublisher, PublishError


def cmd_login():
    """交互式登录，保存 Cookie"""
    async def _run():
        async with XiaohongshuPublisher() as pub:
            await pub.login()
            print("\n✅ 登录完成！现在可以用 python main.py publish 发布笔记了")
    asyncio.run(_run())


def cmd_compose(args):
    """把图片拼成 3x3 拼贴画"""
    image_dir = Path(args.images)
    if not image_dir.exists():
        print(f"❌ 目录不存在: {image_dir}")
        sys.exit(1)

    # 收集图片
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    image_paths = sorted(
        [p for p in image_dir.iterdir() if p.suffix.lower() in exts]
    )[:9]

    if len(image_paths) < 9:
        print(f"❌ 图片不足 9 张（找到 {len(image_paths)} 张），最少需要 9 张")
        sys.exit(1)

    print(f"📸 使用 {len(image_paths)} 张图片合成 moodboard...")
    for i, p in enumerate(image_paths):
        print(f"   {i+1}. {p.name}")

    composer = MoodboardComposer()
    output = composer.compose(
        image_paths=[str(p) for p in image_paths],
        title=args.title or "",
        caption=args.caption or "",
    )
    print(f"✅ 导出完成: {output}")
    print(f"   下一步: python main.py publish --image {output}")


def cmd_publish(args):
    """发布到小红书"""
    image_path = args.image
    if not Path(image_path).exists():
        print(f"❌ 图片不存在: {image_path}")
        sys.exit(1)

    async def _run():
        async with XiaohongshuPublisher() as pub:
            try:
                post_url = await pub.publish(
                    image_path=image_path,
                    title=args.title or "",
                    caption=args.caption or "",
                )
                print(f"\n✅ 发布成功！")
                print(f"   帖子链接: {post_url}")
            except PublishError as e:
                print(f"\n❌ 发布失败: {e}")
                print("   提示：先运行 python main.py login 登录，或检查网络")
                sys.exit(1)
    asyncio.run(_run())


def cmd_run(args):
    """先合成再发布"""
    # Step 1: compose
    print("=" * 50)
    print("  Step 1/2: 合成 Moodboard")
    print("=" * 50)
    cmd_compose(args)

    # Find the most recent export
    exports = sorted(EXPORTS_DIR.glob("moodboard_*.png"), key=lambda p: p.stat().st_mtime)
    if not exports:
        print("❌ 没有找到导出文件")
        sys.exit(1)
    image_path = str(exports[-1])

    # Step 2: publish
    print("\n" + "=" * 50)
    print("  Step 2/2: 发布到小红书")
    print("=" * 50)
    args.image = image_path
    cmd_publish(args)


def main():
    parser = argparse.ArgumentParser(
        description="小红书自动发布工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  TASTEGRAPH_XHS_HEADFUL=1 python main.py login      # 首次扫码登录
  python main.py compose --images ./mock_data/ --title "标题" --caption "文案"
  python main.py publish --image exports/moodboard.png --title "标题" --caption "文案"
  python main.py run --images ./mock_data/ --title "一键合成+发布"
        """,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # login
    sub.add_parser("login", help="扫码登录小红书，保存 Cookie")

    # compose
    p = sub.add_parser("compose", help="把 9 张图片拼成 3x3 moodboard")
    p.add_argument("--images", required=True, help="图片目录路径")
    p.add_argument("--title", default="", help="标题（显示在图片底部）")
    p.add_argument("--caption", default="", help="文案（显示在标题下方）")

    # publish
    p = sub.add_parser("publish", help="发布一张图片到小红书")
    p.add_argument("--image", required=True, help="要发布的图片路径")
    p.add_argument("--title", default="", help="小红书标题")
    p.add_argument("--caption", default="", help="小红书正文")

    # run (compose + publish)
    p = sub.add_parser("run", help="一键合成 + 发布")
    p.add_argument("--images", required=True, help="图片目录路径")
    p.add_argument("--title", default="", help="标题")
    p.add_argument("--caption", default="", help="文案")

    args = parser.parse_args()

    if args.command == "login":
        cmd_login()
    elif args.command == "compose":
        cmd_compose(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
