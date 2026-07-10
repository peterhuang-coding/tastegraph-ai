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
#

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  TasteGraph AI"
echo "  品味知识图谱 + 小红书内容管道"
echo "========================================"
echo ""

MODE="${1:-full}"

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
  auto-pub|auto-publish)
    echo "🤖 自动发布模式：生成发布包 → 自动发到小红书"
    echo ""
    shift
    # 先生成
    python3 scripts/pipeline.py --publish-only --count "${1:-3}" "$@"
    # 再自动发第一篇
    python3 scripts/auto_publish.py
    ;;
  login)
    echo "🔐 登录模式：扫码登录小红书"
    echo ""
    python3 scripts/auto_publish.py --login
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
    echo "  auto-pub      生成 + 自动发布到小红书（需先 login）"
    echo "  login         扫码登录小红书"
    echo ""
    echo "示例:"
    echo "  bash start.sh                   # 全流程"
    echo "  bash start.sh login             # 首次登录"
    echo "  bash start.sh auto-pub          # 生成 + 自动发布"
    echo "  bash start.sh publish --count 9 # 生成 9 篇"
    echo "  bash start.sh serve             # 只启动审稿"
    echo "  bash start.sh feedback          # 查看周报"
    exit 1
    ;;
esac