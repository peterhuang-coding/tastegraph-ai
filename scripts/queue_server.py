#!/usr/bin/env python3
"""Local server for the publish QUEUE — enables cross-domain image copy to clipboard.

Run:  python scripts/queue_server.py
Then: open http://localhost:8765

Features:
  - Serves QUEUE.html + images from a local HTTP origin
  - /copy-image?path=...  → copies image file to macOS clipboard (Cmd+V into XHS)
  - /open-folder?path=... → reveals in Finder
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
POSTS_DIR = BASE_DIR / "posts"
PUBLISH_LOG_PATH = BASE_DIR / "data" / "publish_log.json"
PORT = int(os.environ.get("QUEUE_PORT", "8765"))
UPSTREAM_API = "http://127.0.0.1:8787"  # 图谱/周报/候选池 API (taste_graph_ai server)

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>moodboard. 工作台</title>
<style>
  :root {{ --bg:#f6f4f1; --card:#fff; --ink:#2b2a28; --mut:#99948c; --line:#e5e0d8; --accent:#c9b8a3; }}
  body {{ margin:0; font-family:-apple-system,"PingFang SC",sans-serif; background:var(--bg); color:var(--ink); }}
  .wrap {{ max-width:760px; margin:0 auto; padding:40px 20px 60px; }}
  h1 {{ font-size:26px; font-weight:600; margin:0 0 4px; }}
  .sub {{ color:var(--mut); font-size:13px; margin-bottom:28px; }}
  .day {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px 20px; margin-bottom:20px; }}
  .day h2 {{ font-size:13px; letter-spacing:.08em; color:var(--accent); margin:0 0 10px; text-transform:uppercase; }}
  .day ol {{ margin:0; padding-left:20px; font-size:14px; line-height:2; color:var(--ink); }}
  .day a {{ color:inherit; }}
  .links {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
  .links a {{ display:block; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; text-decoration:none; color:var(--ink); transition:border-color .15s; }}
  .links a:hover {{ border-color:var(--accent); }}
  .links b {{ display:block; font-size:15px; margin-bottom:4px; }}
  .links span {{ font-size:12px; color:var(--mut); }}
  .foot {{ margin-top:24px; font-size:12px; color:var(--mut); }}
  @media (max-width:600px) {{ .links {{ grid-template-columns:1fr; }} }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#1c1b19; --card:#26241f; --ink:#e8e4dc; --mut:#8a857c; --line:#3a362f; --accent:#8a7a68; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>moodboard.</h1>
  <div class="sub">个人视觉采样系统 · 每日人工策展工作台（路线 A：机器出候选，人做判断）</div>
  <div class="day">
    <h2>今天要做</h2>
    <ol>
      <li>打开 <a href="{queue_href}">编辑工作台</a>，看今日 9 图候选包</li>
      <li>挑图：9 宫格悬停点 🔁 换图；改写观点草稿（💾 保存会落盘）</li>
      <li>复制文案 → 小红书新号手动发布</li>
      <li>发完到 <a href="/publish-log">发布登记</a> 记录（30 秒）</li>
      <li>24h / 48h 后回填赞藏评 → 周报自动汇总</li>
    </ol>
  </div>
  <nav class="links">
    <a href="{queue_href}"><b>✏️ 编辑工作台</b><span>今日候选包 · 挑图 · 改写 · 复制</span></a>
    <a href="/publish-log"><b>📓 发布登记</b><span>登记 + 24h/48h 回填 + 周汇总</span></a>
    <a href="/sources"><b>📡 信息源</b><span>源面板与健康度</span></a>
    <a href="http://127.0.0.1:8787"><b>⚙️ 系统台</b><span>图谱 / 爬虫 / Pipeline（技术控制台）</span></a>
  </nav>
  <div class="foot">周报入口：编辑工作台右上角「📊 周报」。数据全部本地，不碰小红书。</div>
</div>
</body>
</html>
"""


class QueueHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from BASE_DIR, plus clipboard and Finder actions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # ── / → 每日工作台首页 ──
        if parsed.path == "/":
            date_dirs = sorted(POSTS_DIR.glob("20*"), reverse=True)
            latest = date_dirs[0]
            queue_href = f"/posts/{latest.name}/QUEUE.html"
            body = _INDEX_HTML.replace("{queue_href}", queue_href).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── /api/* → 代理到 8787 图谱 API（周报/反馈/候选池） ──
        if parsed.path.startswith("/api/"):
            url = UPSTREAM_API + parsed.path + ("?" + parsed.query if parsed.query else "")
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"ok": False, "error": f"上游 API 未连接 (8787): {e}"}, status=502)
            return

        # ── /queue-candidates → 换图候选池（优先 8787 评分池，回退本地最近图） ──
        if parsed.path == "/queue-candidates":
            images = []
            try:
                req = urllib.request.Request(UPSTREAM_API + "/api/v1/images/pending?limit=60")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for im in data.get("images", [])[:60]:
                    src = im.get("local_path") or ""
                    if not src or not Path(src).exists():
                        continue
                    image_url = im.get("image_url") or f"/images/{im.get('image_id')}.jpg"
                    images.append({
                        "id": im.get("image_id"),
                        "src": UPSTREAM_API + image_url,
                        "local_path": src,
                        "final_score": im.get("final_score", 0),
                        "source_name": im.get("source_name", ""),
                    })
            except Exception:
                pass
            if not images:
                imgs = sorted(
                    (BASE_DIR / "data" / "images").glob("*.jpg"),
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )[:60]
                images = [
                    {"id": p.stem, "src": f"/data/images/{p.name}", "local_path": str(p),
                     "final_score": 0, "source_name": ""}
                    for p in imgs
                ]
            self._json({"ok": True, "images": images})
            return

        # ── /replace-image?pack=...&pos=N&src=... → 用候选池图片替换 pack 内第 N 张 ──
        if parsed.path == "/replace-image":
            params = urllib.parse.parse_qs(parsed.query)
            pack = params.get("pack", [None])[0]
            pos = params.get("pos", [None])[0]
            src = params.get("src", [None])[0]
            try:
                pos_n = int(pos)
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "pos must be a number"}, status=400)
                return
            if not (pack and src) or not (1 <= pos_n <= 9):
                self._json({"ok": False, "error": "missing pack/src or pos out of 1-9"}, status=400)
                return
            pack_dir = Path(pack)
            src_path = Path(src)
            if not str(pack_dir.resolve()).startswith(str(POSTS_DIR.resolve())):
                self._json({"ok": False, "error": "pack must be under posts/"}, status=403)
                return
            # 只允许替换 data/images 下的爬取图（resolve 后比较，兼容 symlink 布局）
            images_root = (BASE_DIR / "data" / "images").resolve()
            if str(src_path.resolve()) != str(images_root) and not str(src_path.resolve()).startswith(str(images_root) + "/"):
                self._json({"ok": False, "error": "src must be a crawled image under data/images"}, status=403)
                return
            if not src_path.exists():
                self._json({"ok": False, "error": "src not found"}, status=404)
                return
            target = pack_dir / f"image-{pos_n:02d}.jpg"
            try:
                if src_path.suffix.lower() == ".png":
                    subprocess.run(
                        ["sips", "-s", "format", "jpeg", str(src_path), "--out", str(target)],
                        capture_output=True, timeout=30, check=True,
                    )
                else:
                    shutil.copyfile(src_path, target)
                self._json({"ok": True, "rel": str(target.relative_to(BASE_DIR))})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)
            return

        # ── /save-file?path=...&content=... → save edited content to file ──
        if parsed.path == "/save-file":
            params = urllib.parse.parse_qs(parsed.query)
            path = params.get("path", [None])[0]
            content = params.get("content", [""])[0]
            if path and Path(path).parent.exists():
                try:
                    Path(path).write_text(content, encoding="utf-8")
                    self._json({"ok": True, "path": path})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)}, status=500)
            else:
                self._json({"ok": False, "error": "path not found or parent missing"}, status=404)
            return

        # ── /sources → live source dashboard ──
        if parsed.path == "/sources":
            from scripts.source_dashboard import build
            build()
            self.send_response(302)
            self.send_header("Location", "/data/sources.html")
            self.end_headers()
            return

        # ── /copy-image?path=... → copy image to clipboard (Cmd+V into XHS) ──
        if parsed.path == "/copy-image":
            params = urllib.parse.parse_qs(parsed.query)
            path = params.get("path", [None])[0]
            if path and Path(path).exists():
                try:
                    self._copy_file_to_clipboard(path)
                    self._json({"ok": True, "path": path})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)}, status=500)
            else:
                self._json({"ok": False, "error": "file not found"}, status=404)
            return

        # ── /open-file?path=... → open image in Preview ──
        if parsed.path == "/open-file":
            params = urllib.parse.parse_qs(parsed.query)
            path = params.get("path", [None])[0]
            if path and Path(path).exists():
                subprocess.run(["open", "-a", "Preview", path])
                self._json({"ok": True, "path": path})
            else:
                self._json({"ok": False, "error": "file not found"}, status=404)
            return

        # ── /open-folder?path=... → reveal in Finder ──
        if parsed.path == "/open-folder":
            params = urllib.parse.parse_qs(parsed.query)
            path = params.get("path", [None])[0]
            if path and Path(path).exists():
                subprocess.run(["open", "-R", path])
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "not found"}, status=404)
            return

        # ── /publish-log → 发布登记页（本地数据，不碰 XHS） ──
        if parsed.path == "/publish-log":
            page = BASE_DIR / "scripts" / "publish-log.html"
            if page.exists():
                body = page.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"ok": False, "error": "publish-log.html not found"}, status=404)
            return

        # ── /publish-entries → GET 列表 ──
        if parsed.path == "/publish-entries":
            try:
                entries = json.loads(PUBLISH_LOG_PATH.read_text(encoding="utf-8"))
            except Exception:
                entries = []
            self._json({"ok": True, "entries": entries})
            return

        # ── Default: serve static files ──
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        # ── /api/* POST → 代理到 8787（如 publish-metrics 反馈录入） ──
        if parsed.path.startswith("/api/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = self.rfile.read(length)
                url = UPSTREAM_API + parsed.path + ("?" + parsed.query if parsed.query else "")
                req = urllib.request.Request(url, data=payload, method="POST")
                req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"ok": False, "error": f"上游 API 未连接 (8787): {e}"}, status=502)
            return

        if parsed.path != "/publish-entries":
            self._json({"ok": False, "error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, status=400)
            return
        try:
            entries = json.loads(PUBLISH_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            entries = []
        if payload.get("delete"):
            entries = [e for e in entries if e.get("id") != payload["delete"]]
        elif payload.get("id"):
            for e in entries:
                if e.get("id") == payload["id"]:
                    e.update({k: v for k, v in payload.items() if k != "id"})
        else:
            payload["id"] = f"p{len(entries) + 1:03d}"
            entries.append(payload)
        PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        PUBLISH_LOG_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        self._json({"ok": True, "entries": entries})

    def _copy_file_to_clipboard(self, path: str):
        """Copy image file to macOS clipboard using osascript + Applescript.
        After this, Cmd+V in XHS upload area will paste the image."""
        abs_path = str(Path(path).resolve())
        script = f'''
        set theFile to POSIX file "{abs_path}" as alias
        set the clipboard to theFile
        '''
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging
        if "/copy-image" in str(args) or "/open-folder" in str(args):
            print(f"  {args[0]}")
        elif "200" in fmt:
            pass  # suppress 200 OK for static files
        else:
            super().log_message(fmt, *args)


def main():
    # Find latest QUEUE.html
    date_dirs = sorted(POSTS_DIR.glob("20*"), reverse=True)
    if not date_dirs:
        print("No publish packs found. Run generate_publish_packs.py first.")
        sys.exit(1)

    latest = date_dirs[0]
    queue_html = latest / "QUEUE.html"
    if not queue_html.exists():
        print(f"No QUEUE.html in {latest}")
        sys.exit(1)

    print(f"📋 Serving: {latest.name}")
    print(f"   Click 📋 on any card → copies image to clipboard → Cmd+V into XHS")
    print(f"   Press Ctrl+C to stop")

    server = None
    bound_port = None
    for try_port in (PORT, 8766, 8767):
        try:
            server = http.server.HTTPServer(("127.0.0.1", try_port), QueueHandler)
            bound_port = try_port
            break
        except OSError:
            print(f"   port {try_port} busy → trying next")
    if server is None:
        print("No free port (8765-8767). Stop another service first.")
        sys.exit(1)
    print(f"   工作台: http://localhost:{bound_port}/")
    print(f"   编辑队列: http://localhost:{bound_port}/posts/{latest.name}/QUEUE.html")
    print(f"   发布登记: http://localhost:{bound_port}/publish-log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
