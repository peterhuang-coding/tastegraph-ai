#!/opt/anaconda3/bin/python3
"""TasteGraph 自动部署（launchd: com.user.tastegraph.autodeploy，每 15 分钟）。

1. 监听部署分支新提交 → 快进合并进本地 main
2. queue_server 代码变了 → 重启工作台服务
3. 模板版本戳变了且近 2h 无人编辑 → 重生成今日 6 套方案
安全：工作区不干净、无法快进、无网络时一律不动，只记日志。

注意：必须用 python 实现——launchd 上下文中 bash 访问 SanDisk 卷被 TCC 拒绝，
python3 正常（与 daemon_scheduler 同款）。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound")
BRANCH = os.environ.get("TASTEGRAPH_DEPLOY_BRANCH", "feat/curation-workbench")
PROXY = ["-c", "http.proxy=socks5://127.0.0.1:7897", "-c", "https.proxy=socks5://127.0.0.1:7897"]
LOG = Path.home() / "Library/Logs/TasteGraph/autodeploy.log"
PYTHON = "/opt/anaconda3/bin/python3"
HOME = str(Path.home())

LOG.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def run(cmd: list[str], cwd: str = HOME, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def main() -> None:
    # ── 1. 工作区必须干净（保护人工编辑） ──
    r = run(["git", "-C", str(REPO), "status", "--porcelain"])
    if r.returncode != 0:
        log("git status 失败，跳过")
        return
    if r.stdout.strip():
        log("skip: 工作区有未提交改动")
        return

    # ── 2. fetch 对比 ──
    r = run(["git", "-C", str(REPO), *PROXY, "fetch", "origin", BRANCH])
    if r.returncode != 0:
        log("fetch 失败（网络/代理）")
        return
    r = run(["git", "-C", str(REPO), "rev-parse", "HEAD"])
    local = r.stdout.strip()
    r = run(["git", "-C", str(REPO), "rev-parse", f"origin/{BRANCH}"])
    remote = r.stdout.strip()
    if not local or not remote:
        return

    changed = []
    if local != remote:
        log(f"发现新提交: {local[:7]} → {remote[:7]}")
        r = run(["git", "-C", str(REPO), "diff", "--name-only", local, remote])
        changed = r.stdout.split()

        # ── 3. 快进合并 ──
        r = run(["git", *PROXY, "-C", str(REPO), "merge", "--ff-only", f"origin/{BRANCH}"])
        if r.returncode != 0:
            log(f"merge 失败（非快进，跳过）: {r.stderr.strip()[:200]}")
            return
        log(f"已合并: {' '.join(changed)}")

        # ── 4. 服务端代码变了 → 重启工作台 ──
        if any("scripts/queue_server.py" in c for c in changed):
            subprocess.run(["pkill", "-f", "scripts/queue_server.py"], cwd=HOME)
            subprocess.run(["sleep", "1"], cwd=HOME)
            logf = open("/tmp/queue_server.log", "ab")
            subprocess.Popen(
                [PYTHON, "-u", str(REPO / "scripts" / "queue_server.py")],
                cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log("queue_server 已重启")

    # ── 5. 每次循环都查模板版本戳：任何来源覆盖了旧版 QUEUE 都会被纠正 ──
    # （daemon 旧进程用旧参数重生成也会被这里的版本比对抓住）
    r = run(["pgrep", "-f", "generate_publish_packs.py"])
    if r.returncode == 0:
        log("skip regen: 生成任务正在运行（daemon 班次会带出新模板）")
        return

    gen_src = (REPO / "scripts" / "generate_publish_packs.py").read_text(encoding="utf-8")
    m = re.search(r'TEMPLATE_VERSION = "([^"]+)"', gen_src)
    code_ver = m.group(1) if m else "unknown"
    today = datetime.now().strftime("%Y-%m-%d")
    q_path = REPO / "posts" / today / "QUEUE.html"
    stamped = ""
    if q_path.exists():
        sm = re.search(r"queue-template-v: ([^\s]+)", q_path.read_text(encoding="utf-8", errors="ignore"))
        stamped = sm.group(1) if sm else ""
    if stamped == code_ver:
        log(f"模板版本一致 ({stamped})，无需重生成")
        return

    # 近 2 小时有人编辑今日包 → 跳过
    pack_dir = REPO / "posts" / today
    recently_edited = False
    if pack_dir.exists():
        cutoff = datetime.now().timestamp() - 7200
        for p in pack_dir.rglob("*.txt"):
            try:
                if p.stat().st_mtime > cutoff:
                    recently_edited = True
                    break
            except OSError:
                pass
    if recently_edited and not os.environ.get("TASTEGRAPH_FORCE_REGEN"):
        log("skip regen: 今日包近 2 小时有人编辑过")
        return

    r = run([PYTHON, "-u", str(REPO / "scripts" / "generate_publish_packs.py"),
             "--count", "6", "--pack-size", "9"], cwd=str(REPO), timeout=1800)
    if r.returncode == 0:
        log(f"已重生成今日包 (模板 {stamped or '无戳'} → {code_ver})")
    else:
        log(f"重生成失败: {r.stderr.strip()[-200:]}")


if __name__ == "__main__":
    main()
