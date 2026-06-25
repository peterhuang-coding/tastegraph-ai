#!/usr/bin/env python3

import cgi
import datetime as dt
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


def safe_date(value: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except Exception:
        return dt.date.today().isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def section_key(line: str) -> str:
    normalized = line.strip().upper()
    if normalized.startswith("LOOKBOOK / IMAGE REFERENCES"):
        return "lookbook"
    if normalized.startswith("VIDEOS / MOVING IMAGE REFERENCES"):
        return "video"
    if normalized.startswith("ARTICLES / DEEP READING"):
        return "article"
    return ""


def parse_link_pack(text: str) -> dict:
    lines = [line.rstrip("\n") for line in text.splitlines()]
    current = ""
    items: list[dict] = []

    def is_break(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith("=") and len(stripped) >= 8:
            return True
        return False

    i = 0
    while i < len(lines):
        line = lines[i]
        sk = section_key(line)
        if sk:
            current = sk
            i += 1
            continue

        if current and URL_RE.match(line.strip()):
            url = line.strip()
            title = ""
            j = i - 1
            while j >= 0:
                prev = lines[j].strip()
                if not prev:
                    j -= 1
                    continue
                if URL_RE.match(prev):
                    j -= 1
                    continue
                if section_key(prev) or is_break(prev):
                    break
                title = prev
                break

            details_lines: list[str] = []
            k = i + 1
            while k < len(lines):
                nxt = lines[k]
                if section_key(nxt) or is_break(nxt):
                    break
                if URL_RE.match(nxt.strip()):
                    break
                details_lines.append(nxt)
                k += 1

            item_id = f"{current}-{len([x for x in items if x['section'] == current]) + 1}"
            items.append(
                {
                    "id": item_id,
                    "section": current,
                    "url": url,
                    "title": title,
                    "details": "\n".join([l.rstrip() for l in details_lines]).strip(),
                }
            )
            i = k
            continue

        i += 1

    return {"items": items}


def guess_ext(filename: str, content_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return ext
    if content_type:
        guess = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guess in {".png", ".jpg", ".jpeg", ".webp"}:
            return guess
    return ".png"


def now_compact() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def create_zip_bytes(date_dir: Path, pack_path: Path, review_path: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if pack_path.exists():
            zf.writestr("link_pack.txt", load_text(pack_path))
        if review_path.exists():
            zf.writestr("review.json", review_path.read_text(encoding="utf-8"))
        screenshots_dir = date_dir / "screenshots"
        if screenshots_dir.exists():
            for path in sorted(screenshots_dir.glob("*")):
                if path.is_file():
                    zf.write(path, f"screenshots/{path.name}")
    return buf.getvalue()


HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Link Pack Studio</title>
    <style>
      :root {
        --bg: #0b0d10;
        --panel: #11161c;
        --muted: #8ea0b5;
        --text: #e9eef5;
        --line: rgba(255,255,255,0.08);
        --like: #38bdf8;
        --reject: #fb7185;
        --neutral: #a3a3a3;
        --chip: rgba(255,255,255,0.06);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        background: radial-gradient(1200px 700px at 10% 0%, rgba(56,189,248,0.08), transparent 55%),
                    radial-gradient(1200px 700px at 90% 0%, rgba(251,113,133,0.06), transparent 55%),
                    var(--bg);
        color: var(--text);
      }
      a { color: #bfe7ff; text-decoration: none; }
      a:hover { text-decoration: underline; }
      header {
        position: sticky;
        top: 0;
        z-index: 20;
        backdrop-filter: blur(10px);
        background: rgba(11,13,16,0.75);
        border-bottom: 1px solid var(--line);
      }
      .wrap { max-width: 1100px; margin: 0 auto; padding: 14px 16px; }
      .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .title { font-weight: 650; letter-spacing: 0.2px; }
      .pill { font-size: 12px; color: var(--muted); background: var(--chip); border: 1px solid var(--line); padding: 6px 10px; border-radius: 999px; }
      input, textarea, select {
        background: rgba(255,255,255,0.04);
        border: 1px solid var(--line);
        color: var(--text);
        border-radius: 10px;
        padding: 9px 10px;
        outline: none;
      }
      input:focus, textarea:focus { border-color: rgba(56,189,248,0.55); }
      button {
        background: rgba(255,255,255,0.06);
        border: 1px solid var(--line);
        color: var(--text);
        border-radius: 10px;
        padding: 9px 10px;
        cursor: pointer;
      }
      button:hover { border-color: rgba(255,255,255,0.16); }
      .btn-like { border-color: rgba(56,189,248,0.45); }
      .btn-reject { border-color: rgba(251,113,133,0.45); }
      .btn-like.active { background: rgba(56,189,248,0.14); }
      .btn-reject.active { background: rgba(251,113,133,0.14); }
      .btn-neutral.active { background: rgba(163,163,163,0.14); }
      main { padding: 18px 0 40px; }
      .section {
        border: 1px solid var(--line);
        background: rgba(17,22,28,0.6);
        border-radius: 16px;
        padding: 14px;
        margin: 14px 0;
      }
      .section h2 { margin: 0 0 10px; font-size: 15px; letter-spacing: 0.2px; }
      .cards { display: grid; gap: 12px; grid-template-columns: 1fr; }
      @media (min-width: 900px) { .cards { grid-template-columns: 1fr 1fr; } }
      .card {
        border: 1px solid var(--line);
        background: rgba(255,255,255,0.03);
        border-radius: 14px;
        padding: 12px;
      }
      .card.active { outline: 2px solid rgba(56,189,248,0.35); }
      .meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .muted { color: var(--muted); font-size: 12px; }
      .url { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; opacity: 0.95; }
      .details { white-space: pre-wrap; font-size: 12px; color: rgba(233,238,245,0.85); margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.10); padding-top: 8px; }
      .grid2 { display: grid; grid-template-columns: 1fr; gap: 10px; }
      @media (min-width: 900px) { .grid2 { grid-template-columns: 1fr 1fr; } }
      .shots { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
      .shot { font-size: 12px; border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; color: rgba(233,238,245,0.9); background: rgba(255,255,255,0.03); }
      .toast {
        position: fixed;
        bottom: 16px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(17,22,28,0.92);
        border: 1px solid var(--line);
        padding: 10px 12px;
        border-radius: 12px;
        color: var(--text);
        font-size: 12px;
        max-width: 92vw;
        display: none;
        z-index: 50;
      }
      .kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; padding: 2px 6px; border: 1px solid var(--line); border-radius: 6px; background: rgba(255,255,255,0.03); }
    </style>
  </head>
  <body>
    <header>
      <div class="wrap">
        <div class="row" style="justify-content: space-between;">
          <div class="row">
            <div class="title">Link Pack Studio</div>
            <div id="modePill" class="pill">loading…</div>
          </div>
          <div class="row">
            <label class="muted">Date</label>
            <input id="date" type="date" />
            <button id="reload">Reload</button>
            <button id="downloadZip">Download ZIP</button>
          </div>
        </div>
        <div class="row" style="margin-top: 10px; justify-content: space-between;">
          <div class="row">
            <span class="pill">点击某张卡片后按 <span class="kbd">Ctrl</span> + <span class="kbd">V</span> 粘贴截图</span>
            <span id="activePill" class="pill">Active: none</span>
          </div>
          <div class="row">
            <label class="muted">Sync taste_memory</label>
            <select id="syncTaste">
              <option value="1" selected>ON</option>
              <option value="0">OFF</option>
            </select>
            <span id="saveHint" class="muted"></span>
          </div>
        </div>
      </div>
    </header>

    <main>
      <div class="wrap">
        <div id="root"></div>
      </div>
    </main>

    <div id="toast" class="toast"></div>

    <script>
      const root = document.getElementById("root");
      const dateInput = document.getElementById("date");
      const modePill = document.getElementById("modePill");
      const activePill = document.getElementById("activePill");
      const syncTasteEl = document.getElementById("syncTaste");
      const saveHint = document.getElementById("saveHint");
      const toast = document.getElementById("toast");

      let activeId = "";
      let current = { items: [] };

      function showToast(msg) {
        toast.textContent = msg;
        toast.style.display = "block";
        clearTimeout(showToast._t);
        showToast._t = setTimeout(() => toast.style.display = "none", 2100);
      }

      function groupBySection(items) {
        const out = { lookbook: [], video: [], article: [] };
        for (const item of items) {
          if (out[item.section]) out[item.section].push(item);
        }
        return out;
      }

      function setActive(id) {
        activeId = id;
        activePill.textContent = id ? `Active: ${id}` : "Active: none";
        for (const el of document.querySelectorAll(".card")) {
          el.classList.toggle("active", el.dataset.id === id);
        }
      }

      function sectionTitle(key) {
        if (key === "lookbook") return "LOOKBOOK / IMAGE REFERENCES";
        if (key === "video") return "VIDEOS / MOVING IMAGE REFERENCES";
        if (key === "article") return "ARTICLES / DEEP READING";
        return key;
      }

      async function apiGet(path) {
        const res = await fetch(path);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Request failed");
        return data;
      }

      async function apiPost(path, body) {
        const res = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Request failed");
        return data;
      }

      function renderCard(item) {
        const card = document.createElement("div");
        card.className = "card";
        card.dataset.id = item.id;
        card.addEventListener("click", () => setActive(item.id));

        const title = document.createElement("div");
        title.textContent = item.title || item.id;
        title.style.fontWeight = "650";

        const url = document.createElement("div");
        url.className = "url";
        url.innerHTML = `<a href="${item.url}" target="_blank" rel="noreferrer">${item.url}</a>`;

        const meta = document.createElement("div");
        meta.className = "meta";
        meta.style.marginTop = "8px";

        const likeBtn = document.createElement("button");
        likeBtn.textContent = "LIKE";
        likeBtn.className = "btn-like";

        const rejectBtn = document.createElement("button");
        rejectBtn.textContent = "REJECT";
        rejectBtn.className = "btn-reject";

        const neutralBtn = document.createElement("button");
        neutralBtn.textContent = "NEUTRAL";
        neutralBtn.className = "btn-neutral";

        function setActiveRating(r) {
          likeBtn.classList.toggle("active", r === "like");
          rejectBtn.classList.toggle("active", r === "reject");
          neutralBtn.classList.toggle("active", r === "neutral");
        }
        setActiveRating(item.rating || "neutral");

        const tags = document.createElement("input");
        tags.placeholder = "tags (comma), e.g. quiet uniform, shadow";
        tags.value = (item.tags || []).join(", ");
        tags.style.width = "100%";

        const note = document.createElement("textarea");
        note.placeholder = "note (why like/reject) — optional";
        note.value = item.note || "";
        note.rows = 3;
        note.style.width = "100%";

        const upload = document.createElement("input");
        upload.type = "file";
        upload.accept = "image/*";

        const uploadBtn = document.createElement("button");
        uploadBtn.textContent = "Upload screenshot…";
        uploadBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          upload.click();
        });

        async function saveRating(rating) {
          setActive(item.id);
          setActiveRating(rating);
          saveHint.textContent = "saving…";
          try {
            const res = await apiPost("/api/rate", {
              date: dateInput.value,
              item_id: item.id,
              rating,
              tags: tags.value,
              note: note.value,
              sync_taste: syncTasteEl.value === "1",
            });
            Object.assign(item, res.item);
            setActiveRating(item.rating || "neutral");
            showToast(`Saved ${item.id}: ${item.rating}`);
          } catch (err) {
            showToast(`Save failed: ${err.message}`);
          } finally {
            saveHint.textContent = "";
          }
        }

        likeBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); saveRating("like"); });
        rejectBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); saveRating("reject"); });
        neutralBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); saveRating("neutral"); });

        upload.addEventListener("change", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!upload.files || !upload.files[0]) return;
          setActive(item.id);
          const file = upload.files[0];
          const fd = new FormData();
          fd.append("date", dateInput.value);
          fd.append("item_id", item.id);
          fd.append("file", file, file.name);
          try {
            const res = await fetch("/api/upload", { method: "POST", body: fd });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Upload failed");
            Object.assign(item, data.item);
            renderScreenshots();
            showToast(`Uploaded → ${item.id}`);
          } catch (err) {
            showToast(`Upload failed: ${err.message}`);
          } finally {
            upload.value = "";
          }
        });

        const details = document.createElement("div");
        details.className = "details";
        details.textContent = item.details || "(no details)";

        const shots = document.createElement("div");
        shots.className = "shots";
        function renderScreenshots() {
          shots.innerHTML = "";
          const list = item.screenshots || [];
          if (list.length === 0) {
            const none = document.createElement("span");
            none.className = "muted";
            none.textContent = "No screenshots yet.";
            shots.appendChild(none);
            return;
          }
          for (const s of list) {
            const chip = document.createElement("span");
            chip.className = "shot";
            chip.textContent = s;
            shots.appendChild(chip);
          }
        }
        renderScreenshots();

        const grid = document.createElement("div");
        grid.className = "grid2";
        const left = document.createElement("div");
        const right = document.createElement("div");
        left.appendChild(tags);
        left.appendChild(note);
        right.appendChild(document.createElement("div")).innerHTML = '<div class="muted">Screenshot</div>';
        right.appendChild(uploadBtn);
        right.appendChild(shots);
        grid.appendChild(left);
        grid.appendChild(right);

        meta.appendChild(likeBtn);
        meta.appendChild(rejectBtn);
        meta.appendChild(neutralBtn);
        meta.appendChild(document.createElement("span")).outerHTML = `<span class="pill">${item.section}</span>`;

        card.appendChild(title);
        card.appendChild(url);
        card.appendChild(meta);
        card.appendChild(details);
        card.appendChild(document.createElement("div")).style.height = "10px";
        card.appendChild(grid);
        return card;
      }

      function render() {
        root.innerHTML = "";
        const grouped = groupBySection(current.items || []);
        for (const key of ["lookbook", "video", "article"]) {
          const section = document.createElement("div");
          section.className = "section";
          const h2 = document.createElement("h2");
          h2.textContent = sectionTitle(key);
          section.appendChild(h2);
          const cards = document.createElement("div");
          cards.className = "cards";
          for (const item of grouped[key]) cards.appendChild(renderCard(item));
          section.appendChild(cards);
          root.appendChild(section);
        }
      }

      async function load(dateStr) {
        try {
          const data = await apiGet(`/api/pack?date=${encodeURIComponent(dateStr)}`);
          current = data;
          modePill.textContent = data.live_lookup || "loaded";
          render();
          setActive("");
        } catch (err) {
          modePill.textContent = "error";
          root.innerHTML = `<div class="section"><h2>Error</h2><div class="muted">${err.message}</div></div>`;
        }
      }

      document.getElementById("reload").addEventListener("click", () => load(dateInput.value));
      document.getElementById("downloadZip").addEventListener("click", () => {
        const url = `/api/download?date=${encodeURIComponent(dateInput.value)}`;
        window.location.href = url;
      });

      document.addEventListener("paste", async (e) => {
        if (!e.clipboardData) return;
        const items = Array.from(e.clipboardData.items || []);
        const img = items.find(it => it.type && it.type.startsWith("image/"));
        if (!img) return;
        const file = img.getAsFile();
        if (!file) return;
        const id = activeId || "";
        const fd = new FormData();
        fd.append("date", dateInput.value);
        fd.append("item_id", id);
        fd.append("file", file, file.name || "clipboard.png");
        try {
          const res = await fetch("/api/upload", { method: "POST", body: fd });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Upload failed");
          if (data.item && data.item.id) {
            const idx = current.items.findIndex(x => x.id === data.item.id);
            if (idx >= 0) current.items[idx] = data.item;
          }
          render();
          showToast(id ? `Pasted screenshot → ${id}` : "Pasted screenshot → unassigned");
        } catch (err) {
          showToast(`Paste upload failed: ${err.message}`);
        }
      });

      (async () => {
        const init = await apiGet("/api/init");
        dateInput.value = init.date;
        modePill.textContent = init.live_lookup;
        await load(init.date);
      })();
    </script>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "LinkPackStudio/1.0"

    @property
    def base_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _paths(self, date_str: str) -> dict:
        date_str = safe_date(date_str)
        link_packs_dir = self.base_dir / "link_packs"
        pack_path = link_packs_dir / f"{date_str}.txt"
        date_dir = self.base_dir / date_str
        screenshots_dir = date_dir / "screenshots"
        review_path = date_dir / "link_pack_review.json"
        return {
            "date": date_str,
            "pack_path": pack_path,
            "date_dir": date_dir,
            "screenshots_dir": screenshots_dir,
            "review_path": review_path,
        }

    def log_message(self, fmt: str, *args) -> None:
        # keep it quiet; user can see UI status
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/init":
            today = dt.date.today().isoformat()
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "date": today,
                    "live_lookup": "seed-only (no web verify in this environment)",
                    "base_dir": str(self.base_dir),
                },
            )
            return

        if parsed.path == "/api/pack":
            qs = parse_qs(parsed.query)
            date_str = safe_date((qs.get("date") or [""])[0])
            paths = self._paths(date_str)
            if not paths["pack_path"].exists():
                json_response(
                    self,
                    HTTPStatus.NOT_FOUND,
                    {"error": f"Link pack not found: {paths['pack_path']}"},
                )
                return

            pack_text = load_text(paths["pack_path"])
            parsed_pack = parse_link_pack(pack_text)
            ensure_dir(paths["date_dir"])
            ensure_dir(paths["screenshots_dir"])

            review = load_json(
                paths["review_path"],
                {
                    "date": paths["date"],
                    "pack_path": str(paths["pack_path"]),
                    "items": {},
                    "unassigned": [],
                    "updated_at": "",
                },
            )

            items_out: list[dict] = []
            for item in parsed_pack["items"]:
                saved = (review.get("items") or {}).get(item["id"], {})
                items_out.append(
                    {
                        **item,
                        "rating": saved.get("rating", "neutral"),
                        "tags": saved.get("tags", []),
                        "note": saved.get("note", ""),
                        "screenshots": saved.get("screenshots", []),
                        "updated_at": saved.get("updated_at", ""),
                    }
                )

            json_response(
                self,
                HTTPStatus.OK,
                {
                    "date": paths["date"],
                    "pack_path": str(paths["pack_path"]),
                    "date_dir": str(paths["date_dir"]),
                    "live_lookup": "seed-only (no web verify in this environment)",
                    "items": items_out,
                    "unassigned": review.get("unassigned", []),
                },
            )
            return

        if parsed.path == "/api/download":
            qs = parse_qs(parsed.query)
            date_str = safe_date((qs.get("date") or [""])[0])
            paths = self._paths(date_str)
            ensure_dir(paths["date_dir"])
            ensure_dir(paths["screenshots_dir"])
            zip_bytes = create_zip_bytes(paths["date_dir"], paths["pack_path"], paths["review_path"])
            filename = f"link_pack_{paths['date']}.zip"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/rate":
            try:
                body = read_json_body(self)
            except Exception as e:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {e}"})
                return

            date_str = safe_date(body.get("date", ""))
            item_id = str(body.get("item_id", "")).strip()
            rating = str(body.get("rating", "neutral")).strip().lower()
            tags_raw = str(body.get("tags", ""))
            note = str(body.get("note", ""))
            sync_taste = bool(body.get("sync_taste", True))

            if not item_id:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing item_id"})
                return
            if rating not in {"like", "reject", "neutral"}:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid rating"})
                return

            paths = self._paths(date_str)
            ensure_dir(paths["date_dir"])
            ensure_dir(paths["screenshots_dir"])

            pack_text = load_text(paths["pack_path"]) if paths["pack_path"].exists() else ""
            parsed_pack = parse_link_pack(pack_text) if pack_text else {"items": []}
            pack_items = {it["id"]: it for it in parsed_pack.get("items", [])}
            if item_id not in pack_items:
                json_response(self, HTTPStatus.NOT_FOUND, {"error": f"Unknown item_id: {item_id}"})
                return

            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            review = load_json(
                paths["review_path"],
                {
                    "date": paths["date"],
                    "pack_path": str(paths["pack_path"]),
                    "items": {},
                    "unassigned": [],
                    "updated_at": "",
                },
            )
            review.setdefault("items", {})
            entry = review["items"].get(item_id, {})
            entry.setdefault("screenshots", [])
            entry.update(
                {
                    "rating": rating,
                    "tags": tags,
                    "note": note,
                    "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
                }
            )
            review["items"][item_id] = entry
            review["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            save_json(paths["review_path"], review)

            # Optionally sync to taste_memory.json via existing helper script.
            sync_error = ""
            if sync_taste and rating in {"like", "reject"}:
                item = pack_items[item_id]
                link_type = item.get("section", "")
                link = item.get("url", "")
                if link_type and link:
                    args = [
                        sys.executable,
                        str(self.base_dir / "scripts" / "link_feedback.py"),
                        "--memory",
                        str(self.base_dir / "taste_memory.json"),
                        "--link",
                        link,
                        "--type",
                        link_type if link_type in {"lookbook", "video", "article"} else "",
                        "--note",
                        note,
                    ]
                    if rating == "like" and tags:
                        args += ["--like", ", ".join(tags)]
                    if rating == "reject" and tags:
                        args += ["--avoid", ", ".join(tags)]
                    try:
                        subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    except Exception as e:
                        sync_error = f"taste sync failed: {e}"

            item = pack_items[item_id]
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "item": {
                        **item,
                        "rating": entry.get("rating", "neutral"),
                        "tags": entry.get("tags", []),
                        "note": entry.get("note", ""),
                        "screenshots": entry.get("screenshots", []),
                        "updated_at": entry.get("updated_at", ""),
                    },
                    "sync_error": sync_error,
                },
            )
            return

        if parsed.path == "/api/upload":
            env = {"REQUEST_METHOD": "POST"}
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
            date_str = safe_date(form.getfirst("date", ""))
            item_id = (form.getfirst("item_id", "") or "").strip()
            file_item = form["file"] if "file" in form else None
            if not file_item or not getattr(file_item, "file", None):
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing file"})
                return

            filename = file_item.filename or "clipboard.png"
            content_type = file_item.type or ""
            ext = guess_ext(filename, content_type)
            paths = self._paths(date_str)
            ensure_dir(paths["date_dir"])
            ensure_dir(paths["screenshots_dir"])

            tag = item_id if item_id else "unassigned"
            out_name = f"{tag}__{now_compact()}{ext}"
            out_path = paths["screenshots_dir"] / out_name
            data = file_item.file.read()
            out_path.write_bytes(data)

            review = load_json(
                paths["review_path"],
                {
                    "date": paths["date"],
                    "pack_path": str(paths["pack_path"]),
                    "items": {},
                    "unassigned": [],
                    "updated_at": "",
                },
            )
            review.setdefault("items", {})
            if item_id:
                entry = review["items"].get(item_id, {})
                entry.setdefault("screenshots", [])
                entry["screenshots"].append(out_name)
                entry["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
                review["items"][item_id] = entry
            else:
                review.setdefault("unassigned", [])
                review["unassigned"].append(out_name)
            review["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            save_json(paths["review_path"], review)

            pack_text = load_text(paths["pack_path"]) if paths["pack_path"].exists() else ""
            parsed_pack = parse_link_pack(pack_text) if pack_text else {"items": []}
            pack_items = {it["id"]: it for it in parsed_pack.get("items", [])}

            if item_id and item_id in pack_items:
                item = pack_items[item_id]
                saved = review.get("items", {}).get(item_id, {})
                json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "item": {
                            **item,
                            "rating": saved.get("rating", "neutral"),
                            "tags": saved.get("tags", []),
                            "note": saved.get("note", ""),
                            "screenshots": saved.get("screenshots", []),
                            "updated_at": saved.get("updated_at", ""),
                        }
                    },
                )
                return

            json_response(
                self,
                HTTPStatus.OK,
                {
                    "item": {"id": "", "section": "", "url": "", "title": "", "details": "", "screenshots": []},
                    "unassigned": review.get("unassigned", []),
                },
            )
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})


def main() -> int:
    port = int(os.environ.get("PORT", "8787"))
    host = os.environ.get("HOST", "127.0.0.1")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Link Pack Studio running on http://{host}:{port}")
    print("Tip: click a card, then paste (Ctrl+V) to attach screenshot.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

