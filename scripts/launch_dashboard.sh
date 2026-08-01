#!/bin/bash
# 一键打开 TasteGraph AI 总控制台
# 用法：bash scripts/launch_dashboard.sh
# 作用：1) 安全检查 2) 检查并启动 server (8787) 3) 打开 11 个 tab 到浏览器
#
# 安全契约（2026-07-29）:
#   - 本脚本**只**启动 FastAPI web server（控制台）
#   - **不**启动任何 daemon_scheduler / publish_scheduler
#   - **不**检查或复活 ~/Library/LaunchAgents 下的 plist
#   - plist 一律手动管理，避免误触 XHS 自动发布导致账号封禁

set -e

REPO="/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound"
PORT=8787
TABS=(
  "sources"
  "daily"
  "graph"
  "history"
  "curation"
  "health"
  "pipeline"
  "crawler"
  "tasks"
  "weekly"
  "trend"
)

# ── 0) 安全检查 ──────────────────────────────────────────
echo "▶ 安全检查..."
if ls /Users/peter_mini/Library/LaunchAgents/com.user.tastegraph.*.plist 2>/dev/null | head -1 | grep -q plist; then
  echo "⚠️  检测到 ~/Library/LaunchAgents 下还有 tastegraph plist（建议删）:"
  ls /Users/peter_mini/Library/LaunchAgents/com.user.tastegraph.*.plist 2>/dev/null
  echo "   本脚本不会复活这些 plist，但建议手动: rm ~/Library/LaunchAgents/com.user.tastegraph.*.plist"
fi
if launchctl list 2>/dev/null | grep -qi tastegraph; then
  echo "⚠️  launchctl 里有 tastegraph 任务在跑:"
  launchctl list 2>/dev/null | grep -i tastegraph
fi
if ps -ef | grep -E "(daemon_scheduler|publish_scheduler|auto_publish)" | grep -v grep | grep -v claude | grep -q .; then
  echo "⚠️  发现后台 tastegraph 进程在跑（不致命，但建议查）:"
  ps -ef | grep -E "(daemon_scheduler|publish_scheduler|auto_publish)" | grep -v grep | grep -v claude
fi

# ── 1) 检查 server ─────────────────────────────────────────
is_listening() {
  lsof -iTCP:${PORT} -sTCP:LISTEN -P -n 2>/dev/null | grep -q ":${PORT} (LISTEN)"
}

if is_listening; then
  echo "✅ Server 已在 ${PORT} 端口运行"
else
  echo "▶ 启动 server (后台)..."
  cd "$REPO"
  nohup python3 -m taste_graph_ai.server > /tmp/tastegraph_server.log 2>&1 &
  echo "  PID: $!"
  sleep 4
  if is_listening; then
    echo "✅ Server 启动成功"
  else
    echo "❌ Server 启动失败，看 /tmp/tastegraph_server.log"
    tail -20 /tmp/tastegraph_server.log
    exit 1
  fi
fi

# ── 2) 健康探活 ─────────────────────────────────────────
echo ""
echo "▶ 健康探活..."
HEALTH=$(env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl -s -m 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/api/v1/health/detailed" 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
  echo "✅ /api/v1/health/detailed → 200"
else
  echo "⚠️  /api/v1/health/detailed → ${HEALTH}（可能 server 还在启动中）"
fi

# ── 3) 打开 10 个 tab ─────────────────────────────────────
echo ""
echo "▶ 打开 10 个 tab 到浏览器..."
i=1
for tab in "${TABS[@]}"; do
  open "http://127.0.0.1:${PORT}/#${tab}"
  if [ $i -eq 10 ]; then
    key="⌘0"
  else
    key="⌘${i}"
  fi
  echo "  ${key}  →  #${tab}"
  i=$((i + 1))
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ 总控制台已就绪"
echo "  📍 http://127.0.0.1:${PORT}/"
echo "  ⌨  快捷键: ⌘1-⌘0 切换 10 个 tab"
echo "═══════════════════════════════════════════════════════════════"
