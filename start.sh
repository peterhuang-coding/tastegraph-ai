#!/bin/bash
# TasteGraph AI — one-click pipeline
# Usage: bash start.sh [mode]
#
# Modes:
#   (default)   Full pipeline: crawl → select → generate → serve
#   publish     Skip crawl, generate publish packs from existing data
#   serve       Only start the QUEUE review server
#   feedback    Show weekly performance report
#   auto-pub    Generate + auto-publish to Xiaohongshu (login first)
#   login       Login to Xiaohongshu via QR code (first time only)
#   scheduler   Start the scheduled publish daemon
#

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  TasteGraph AI"
echo "  品味知识图谱 + 小红书内容管道"
echo "========================================"
echo ""

MODE="${1:-auto-publish}"

case "$MODE" in
  full)
    echo "🌐 全流程模式：爬取 → 选图 → 生成 → 启动服务"
    echo ""
    shift
    python3 scripts/pipeline.py "$@"
    ;;
  publish)
    echo "📝 发布模式：跳过爬取，直接生成发布包"
    echo ""
    shift
    python3 scripts/pipeline.py --publish-only "$@"
    ;;
  serve)
    echo "🔧 服务模式：只启动审稿工作台"
    echo ""
    shift
    python3 scripts/pipeline.py --serve-only "$@"
    ;;
  feedback)
    echo "📊 反馈模式：查看发布效果周报"
    echo ""
    shift
    python3 scripts/pipeline.py --feedback "$@"
    ;;
  crawl)
    echo "🕷️ 爬取模式：只运行内容发现"
    echo ""
    shift
    python3 scripts/pipeline.py --crawl-only "$@"
    ;;
  auto-publish|auto|auto-pub)
    echo "🤖 全自动模式：生成发布包 → 自动发布到小红书（无需审稿）"
    echo ""
    shift
    count="${1:-6}"
    # 先生成发布包（跳过 QUEUE.html 节省时间）
    python3 scripts/pipeline.py --publish-only --count "$count"
    # 确认生成成功后有帖子目录
    latest_dir=$(ls -d posts/20* 2>/dev/null | sort | tail -1)
    if [ -n "$latest_dir" ] && [ "$(ls -d "$latest_dir"/post-* 2>/dev/null | wc -l)" -gt 0 ]; then
      echo "📤 全部自动发布中（headless 模式）..."
      python3 scripts/auto_publish.py --all --headless
    else
      echo "❌ 没有生成发布包"
    fi
    ;;
  login)
    echo "🔐 登录模式：扫码登录小红书"
    echo ""
    python3 scripts/auto_publish.py --login
    ;;
  scheduler)
    echo "⏰ 调度模式：启动定时发布调度器"
    echo ""
    shift
    python3 scripts/publish_scheduler.py "$@"
    ;;
  *)
    echo "❌ 未知模式: $MODE"
    echo ""
    echo "用法: bash start.sh [模式]"
    echo ""
    echo "模式:"
    echo "  (空)          全流程：爬取 → 选图 → 生成 → 启动服务"
    echo "  publish       跳过爬取，直接生成发布包"
    echo "  serve         只启动 QUEUE 审稿服务"
    echo "  feedback      查看发布效果周报"
    echo "  auto-publish  全自动：生成 + 自动发布（无需审稿），默认模式"
    echo "  login         扫码登录小红书"
    echo "  scheduler     启动定时发布调度器"
    echo ""
    echo "示例:"
    echo "  bash start.sh                   # 全流程"
    echo "  bash start.sh login             # 首次登录"
    echo "  bash start.sh scheduler         # 启动定时调度"
    echo "  bash start.sh scheduler --run-now # 立即执行一次"
    echo "  bash start.sh auto-publish       # 全自动：生成 + 自动发布（无需审稿），默认模式"
    echo "  bash start.sh publish --count 9 # 生成 9 篇"
    echo "  bash start.sh serve             # 只启动审稿"
    echo "  bash start.sh feedback          # 查看周报"
    exit 1
    ;;
esac