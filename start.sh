#!/bin/bash
# TasteGraph AI — one-click pipeline
# Usage: bash start.sh [mode]
#
# Modes:
#   (default)   Safe: serve the curation workbench only
#   full        crawl → select → generate → serve
#   publish     Skip crawl, generate publish packs from existing data
#   serve       Only start the curation workbench
#   feedback    Show weekly performance report
#
# DISABLED (老板 2026-07-29 关停全部 XHS 自动化): auto-publish / login / scheduler
#

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  TasteGraph AI"
echo "  品味知识图谱 + 小红书内容管道"
echo "========================================"
echo ""

MODE="${1:-serve}"

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
    echo "⛔ DISABLED: 自动发布已由老板于 2026-07-29 永久关停（账号封禁）。"
    echo "   发布流程改为：工作台导出 → 人工手动发布。"
    exit 1
    ;;
  login)
    echo "⛔ DISABLED: 小红书自动登录已关停。请勿在本机维护登录态。"
    exit 1
    ;;
  scheduler)
    echo "⛔ DISABLED: 定时发布调度器已关停（legacy，见 scripts/publish_scheduler.py 归档说明）。"
    echo "   安全调度请使用 scripts/daemon_scheduler.py（config/schedule.json）。"
    exit 1
    ;;
  *)
    echo "❌ 未知模式: $MODE"
    echo ""
    echo "用法: bash start.sh [模式]"
    echo ""
    echo "模式:"
    echo "  (空)          安全模式：只启动审稿工作台（默认）"
    echo "  full          全流程：爬取 → 选图 → 生成 → 启动服务"
    echo "  publish       跳过爬取，直接生成发布包"
    echo "  serve         只启动审稿工作台"
    echo "  feedback      查看发布效果周报"
    echo ""
    echo "示例:"
    echo "  bash start.sh                   # 安全模式（默认）"
    echo "  bash start.sh publish --count 9 # 生成 9 篇"
    echo "  bash start.sh serve             # 只启动审稿"
    echo "  bash start.sh feedback          # 查看周报"
    exit 1
    ;;
esac