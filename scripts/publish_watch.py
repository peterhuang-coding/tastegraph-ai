#!/usr/bin/env python3
"""发布旁观录像（Computer Use 旁观模式）— 记录老板在 Chrome 里的真实发布操作。

用法（发布前在终端跑）:
    python3 scripts/publish_watch.py --launch        # 自动重启 Chrome 开调试口并开始录像
    python3 scripts/publish_watch.py                 # Chrome 已带 --remote-debugging-port=9222 时直接录像
    Ctrl+C 结束

产出: runs/publish-replay/<时间戳>/frame-*.jpg（每 1 秒一帧）+ replay.json（帧索引、
URL、标题、时长）。之后 Claude 读取帧序列，沉淀成可重放的发布回放脚本——
每篇发布 = 老板确认 + 脚本按老板教过的样子点击。

依赖: websocket-client（pip install websocket-client）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import websocket  # type: ignore
except ImportError:
    print("缺少 websocket-client: pip install websocket-client")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEBUG_PORT = 9222


def chrome_running() -> bool:
    r = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
    return r.returncode == 0


def launch_chrome_with_debug():
    """退出 Chrome 后带调试端口重启（沿用默认 profile，保住 XHS 登录态）。"""
    subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to quit'],
                   capture_output=True, timeout=15)
    time.sleep(2)
    subprocess.Popen(
        [str(CHROME), f"--remote-debugging-port={DEBUG_PORT}",
         "--restore-last-session"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(30):
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2):
                print("✅ Chrome 已带调试端口启动，开始录像（发布完 Ctrl+C 结束）")
                return True
        except Exception:
            pass
    print("❌ Chrome 调试端口未就绪")
    return False


def get_page_target() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=3) as resp:
            pages = json.loads(resp.read().decode())
        # 选第一个 type=page 的普通页面
        for p in pages:
            if p.get("type") == "page" and not p.get("url", "").startswith("chrome://"):
                return p
    except Exception:
        pass
    return None


def cdp_ws(ws_url: str):
    ws = websocket.create_connection(ws_url, timeout=10)
    return ws


def record(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    ws = None
    target = None

    try:
        for _ in range(20):
            target = get_page_target()
            if target:
                break
            time.sleep(1)
        if not target:
            print("❌ 没找到页面 target — 请先在 Chrome 里打开小红书创作页")
            return

        ws = cdp_ws(target["webSocketDebuggerUrl"])
        idx = 0
        started = datetime.now().isoformat()
        print("📹 录像中 — 正常操作即可，Ctrl+C 结束")
        while True:
            # 截图
            ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot",
                                "params": {"format": "jpeg", "quality": 70}}))
            res = ws.recv()
            data = json.loads(res).get("result", {}).get("data", "")
            if data:
                import base64
                frame = out_dir / f"frame-{idx:05d}.jpg"
                frame.write_bytes(base64.b64decode(data))
                # 位置/标题
                ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                    "params": {"expression": "JSON.stringify({url:location.href,title:document.title})",
                                               "returnByValue": True}}))
                res2 = ws.recv()
                try:
                    meta = json.loads(json.loads(res2)["result"]["result"]["value"])
                except Exception:
                    meta = {"url": "", "title": ""}
                frames.append({"frame": frame.name, "t": datetime.now().isoformat(),
                               "url": meta.get("url", ""), "title": meta.get("title", "")})
            idx += 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        replay = {"started": started, "ended": datetime.now().isoformat(),
                  "frames": len(frames), "entries": frames}
        (out_dir / "replay.json").write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 录像完成: {out_dir} — {len(frames)} 帧")
        print(f"   回放脚本生成：把这句发给 Claude — '读 {out_dir}/replay.json 并沉淀发布回放脚本'")


def main() -> None:
    ap = argparse.ArgumentParser(description="发布旁观录像")
    ap.add_argument("--launch", action="store_true", help="自动重启 Chrome 并开调试端口")
    ap.add_argument("--port", type=int, default=DEBUG_PORT)
    args = ap.parse_args()

    if args.launch:
        if not launch_chrome_with_debug():
            sys.exit(1)
    else:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2):
                pass
        except Exception:
            print("Chrome 调试端口未开 — 加 --launch 重启 Chrome，或手动用 --remote-debugging-port=9222 启动")
            sys.exit(1)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = BASE_DIR / "runs" / "publish-replay" / stamp
    record(out_dir)


if __name__ == "__main__":
    main()
