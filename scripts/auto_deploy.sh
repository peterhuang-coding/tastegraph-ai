#!/bin/bash
# TasteGraph 自动部署（launchd: com.user.tastegraph.autodeploy，每 15 分钟）
# 1. 监听部署分支新提交 → 快进合并进本地 main
# 2. queue_server 代码变了 → 重启工作台服务
# 3. 模板版本变了 → 重生成今日 6 套方案（有人近期编辑或正在生成则跳过）
# 安全：工作区不干净、无法快进、无网络时一律不动，只记日志。
set -u

REPO="/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound"
BRANCH="${TASTEGRAPH_DEPLOY_BRANCH:-feat/curation-workbench}"
PROXY="-c http.proxy=socks5://127.0.0.1:7897 -c https.proxy=socks5://127.0.0.1:7897"
LOG="$HOME/Library/Logs/TasteGraph/autodeploy.log"
mkdir -p "$HOME/Library/Logs/TasteGraph"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

cd "$REPO" 2>/dev/null || { log "repo 不可达，跳过"; exit 1; }

# ── 1. 工作区必须干净（保护人工编辑） ──
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  log "skip: 工作区有未提交改动"
  exit 0
fi

# ── 2. fetch 对比 ──
git $PROXY fetch origin "$BRANCH" >> "$LOG" 2>&1 || { log "fetch 失败（网络/代理）"; exit 1; }
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null)
[ -n "$LOCAL" ] && [ -n "$REMOTE" ] || { log "rev-parse 失败"; exit 1; }
if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0  # 无新提交
fi

log "发现新提交: ${LOCAL:0:7} → ${REMOTE:0:7}"
CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")

# ── 3. 快进合并 ──
git $PROXY merge --ff-only "origin/$BRANCH" >> "$LOG" 2>&1 || { log "merge 失败（非快进，跳过）"; exit 1; }
log "已合并: $(echo "$CHANGED" | tr '\n' ' ')"

# ── 4. 服务端代码变了 → 重启工作台 ──
if echo "$CHANGED" | grep -q "scripts/queue_server.py"; then
  pkill -f "scripts/queue_server.py" 2>/dev/null
  sleep 1
  nohup python3 -u scripts/queue_server.py > /tmp/queue_server.log 2>&1 &
  log "queue_server 已重启"
fi

# ── 5. 模板代码变了 → 重生成今日包 ──
if echo "$CHANGED" | grep -q "scripts/generate_publish_packs.py"; then
  if pgrep -f "generate_publish_packs.py" > /dev/null; then
    log "skip regen: 生成任务正在运行（daemon 班次会带出新模板）"
    exit 0
  fi
  CODE_VER=$(python3 -c "import re; m=re.search(r'TEMPLATE_VERSION = \"([^\"]+)\"', open('scripts/generate_publish_packs.py').read()); print(m.group(1) if m else 'unknown')" 2>/dev/null)
  TODAY=$(date +%F)
  Q="posts/$TODAY/QUEUE.html"
  STAMPED=$(grep -oE 'queue-template-v: [^ ]+' "$Q" 2>/dev/null | awk '{print $2}')
  if [ "$STAMPED" = "$CODE_VER" ]; then
    log "模板版本一致 ($STAMPED)，无需重生成"
    exit 0
  fi
  if [ -n "$(find "posts/$TODAY" -name '*.txt' -mmin -120 2>/dev/null | head -1)" ]; then
    log "skip regen: 今日包近 2 小时有人编辑过"
    exit 0
  fi
  python3 scripts/generate_publish_packs.py --count 6 --pack-size 9 >> "$LOG" 2>&1 \
    && log "已重生成今日包 (模板 $STAMPED → $CODE_VER)" \
    || log "重生成失败（见上方日志）"
fi
