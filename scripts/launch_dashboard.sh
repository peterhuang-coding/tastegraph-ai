#!/bin/bash
# 一键打开 TasteGraph AI 总控制台
# 用法：bash scripts/launch_dashboard.sh
# 作用：1) 检查并启动 server (8787)  2) 打开 10 个 tab 到浏览器

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
)

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
