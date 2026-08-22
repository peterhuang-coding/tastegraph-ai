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
import subprocess
import sys
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
POSTS_DIR = BASE_DIR / "posts"
PUBLISH_LOG_PATH = BASE_DIR / "data" / "publish_log.json"
PORT = 8765


class QueueHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from BASE_DIR, plus clipboard and Finder actions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

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
    print(f"   Open: http://localhost:{bound_port}/posts/{latest.name}/QUEUE.html")
    print(f"   发布登记: http://localhost:{bound_port}/publish-log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
