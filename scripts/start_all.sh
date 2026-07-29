#!/bin/bash
# ============================================================
# TasteGraph AI — 一键启动所有自动化服务
# ============================================================
# 功能:
#   1. 启动 Chrome CDP（9222 端口）
#   2. 加载/重载 launchd 守护进程
#   3. 验证所有服务状态
#
# 用法:
#   bash scripts/start_all.sh           # 启动全部服务
#   bash scripts/start_all.sh --status  # 仅查看状态
#   bash scripts/start_all.sh --stop    # 停止全部服务
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$PROJECT_DIR/taste_graph_ai/scheduler"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/TasteGraph"
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT=9222
PROFILE_DIR="$HOME/Google/Chrome/XiaohongshuProfiles/default"

# All plists to manage
PLISTS=(
    "com.user.tastegraph.daemon"
    "com.user.tastegraph.publish-08"
    "com.user.tastegraph.publish-20"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[start_all]${NC} $*"; }
warn() { echo -e "${YELLOW}[start_all]${NC} $*"; }
err()  { echo -e "${RED}[start_all]${NC} $*"; }

# ── 检查 Chrome ──────────────────────────────────────────
check_chrome() {
    if [ -f "$CHROME_APP" ]; then
        log "Chrome found: $CHROME_APP"
        return 0
    else
        err "Chrome not found at $CHROME_APP"
        return 1
    fi
}

# ── 启动 Chrome CDP ──────────────────────────────────────
start_chrome_cdp() {
    if lsof -i ":$CDP_PORT" &>/dev/null; then
        log "Chrome CDP already running on port $CDP_PORT"
        return 0
    fi

    log "Starting Chrome with CDP on port $CDP_PORT..."
    mkdir -p "$PROFILE_DIR"

    nohup "$CHROME_APP" \
        --remote-debugging-port=$CDP_PORT \
        --user-data-dir="$PROFILE_DIR" \
        --no-first-run \
        --no-default-browser-check \
        --disable-background-timer-throttling \
        --disable-renderer-backgrounding \
        --disable-backgrounding-occluded-windows \
        &>/dev/null &

    # Wait for CDP port
    for i in $(seq 1 30); do
        if lsof -i ":$CDP_PORT" &>/dev/null; then
            log "Chrome CDP ready (took ${i}s)"
            return 0
        fi
        sleep 1
    done

    err "Chrome CDP failed to start within 30s"
    return 1
}

# ── 安装并加载所有 launchd plists ──────────────────────
setup_launchd() {
    mkdir -p "$LAUNCHD_DIR"
    mkdir -p "$LOG_DIR"

    for plist_name in "${PLISTS[@]}"; do
        local src="$PLIST_DIR/${plist_name}.plist"
        local dst="$LAUNCHD_DIR/${plist_name}.plist"

        if [ ! -f "$src" ]; then
            warn "Plist source not found: $src (skipping)"
            continue
        fi

        # Unload old, copy new, bootstrap
        launchctl bootout "gui/$(id -u)/${plist_name}" 2>/dev/null || true
        cp "$src" "$dst"
        launchctl bootstrap "gui/$(id -u)" "$dst"
        log "Loaded: ${plist_name}"
    done

    sleep 2
    log "All launchd services loaded."
}

# ── 停止所有服务 ────────────────────────────────────────
stop_all() {
    log "Stopping all services..."

    for plist_name in "${PLISTS[@]}"; do
        launchctl bootout "gui/$(id -u)/${plist_name}" 2>/dev/null && \
            log "Unloaded: ${plist_name}" || \
            warn "Was not loaded: ${plist_name}"
    done

    # Also stop old plists
    for old in com.user.tastegraph com.user.tastegraph.scrape; do
        launchctl bootout "gui/$(id -u)/${old}" 2>/dev/null || true
    done

    # Kill Chrome CDP
    if lsof -i ":$CDP_PORT" &>/dev/null; then
        PID=$(lsof -ti ":$CDP_PORT")
        kill "$PID" 2>/dev/null && log "Chrome CDP killed (PID: $PID)"
    else
        log "Chrome CDP was not running"
    fi

    log "All services stopped."
}

# ── 状态检查 ────────────────────────────────────────────
show_status() {
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  TasteGraph AI — Service Status"
    echo "═══════════════════════════════════════════════════"

    # Chrome CDP
    if lsof -i ":$CDP_PORT" &>/dev/null; then
        echo -e "  Chrome CDP (:$CDP_PORT)  ${GREEN}● running${NC}"
    else
        echo -e "  Chrome CDP (:$CDP_PORT)  ${RED}○ stopped${NC}"
    fi

    # All launchd services
    for plist_name in "${PLISTS[@]}"; do
        local line=$(launchctl list | grep "$plist_name" || true)
        if [ -n "$line" ]; then
            local pid=$(echo "$line" | awk '{print $1}')
            local code=$(echo "$line" | awk '{print $2}')
            if [ "$pid" != "-" ] && [ "$code" = "0" ]; then
                echo -e "  ${plist_name}  ${GREEN}● PID=$pid${NC}"
            else
                echo -e "  ${plist_name}  ${YELLOW}◉ loaded (pid=$pid, exit=$code)${NC}"
            fi
        else
            echo -e "  ${plist_name}  ${RED}○ not loaded${NC}"
        fi
    done

    # Also show old plists
    for old in com.user.tastegraph com.user.tastegraph.scrape; do
        if launchctl list | grep -q "$old"; then
            echo -e "  ${old}  ${YELLOW}◉ loaded (legacy)${NC}"
        fi
    done

    # Last publish in events log
    if [ -f "$PROJECT_DIR/data/events.log" ]; then
        local last_publish=$(grep "publish" "$PROJECT_DIR/data/events.log" | tail -1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ts'])" 2>/dev/null || echo "unknown")
        echo "  Last publish event: $last_publish"
    fi

    # Quick dry-run
    local dry=$(cd "$PROJECT_DIR" && /opt/anaconda3/bin/python3 -u scripts/publish_scheduler.py --dry-run 2>&1 | head -3)
    echo "  $dry"

    echo "═══════════════════════════════════════════════════"
    echo "  Logs: ~/Library/Logs/TasteGraph/"
    echo "  Events: data/events.log"
    echo "═══════════════════════════════════════════════════"
    echo ""
}

# ── Main ─────────────────────────────────────────────────
case "${1:-}" in
    --status)
        show_status
        ;;
    --stop)
        stop_all
        ;;
    *)
        log "=== TasteGraph AI — Starting All Services ==="
        check_chrome
        start_chrome_cdp
        setup_launchd
        echo ""
        show_status
        log "Done. Daemon will auto-publish at 08:00 and 20:00 daily."
        log "Run 'bash scripts/start_all.sh --status' to check."
        log "Run 'bash scripts/start_all.sh --stop' to stop."
        log "View logs: tail -f data/logs/daemon.log"
        ;;
esac
