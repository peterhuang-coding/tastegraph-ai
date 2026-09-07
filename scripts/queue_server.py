#!/usr/bin/env python3
"""运营工作台 server — 人工策展 QUEUE 的本地 HTTP 入口。

Run:  python scripts/queue_server.py
Then: open http://localhost:8765

设计原则（2026-09-08 安全收口）：
  - 全部能力在浏览器内完成：页内预览、单张下载 <a download>、九图 ZIP 打包、
    复制文案 navigator.clipboard；不再有任何 osascript / pbcopy / open 等
    「远程操控 mini」的端点（剪贴板/Finder/Preview 在远程访问时本就无效）。
  - 草稿编辑通过 /save-file 服务端落盘（权威），状态记 data/workbench_state.json。
  - 自动发布永久禁用：本服务不含任何发布/登录/互动能力。
"""

import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 脚本直起（launchd / python3 scripts/queue_server.py）时 sys.path[0] 是 scripts/，
# 项目根不在路径上，/sources 的 `from scripts.source_dashboard import build` 会崩；
# 统一补上根目录（经 pipeline.py 模块方式启动时幂等无害）。
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
POSTS_DIR = BASE_DIR / "posts"
PUBLISH_LOG_PATH = BASE_DIR / "data" / "publish_log.json"
INGEST_STATUS_PATH = BASE_DIR / "data" / "daily_ingestion_status.json"
WORKBENCH_STATE_PATH = BASE_DIR / "data" / "workbench_state.json"
PORT = int(os.environ.get("QUEUE_PORT", "8765"))
# 绑定地址：默认环回（仅本机）。Tailscale/局域网访问设 QUEUE_HOST=0.0.0.0 或
# tailscale IP，并配 TASTEGRAPH_ALLOWED_ORIGINS 白名单（见 docs/operations.md §7）。
HOST = os.environ.get("QUEUE_HOST", os.environ.get("TASTEGRAPH_HOST", "127.0.0.1"))
# CORS 白名单：逗号分隔，如 "http://mini.tailnet:8765,http://192.168.1.10:8765"。
# 默认空 = 不发 Access-Control-Allow-Origin（同源 only），永不返回 "*"。
ALLOWED_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.environ.get("TASTEGRAPH_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
UPSTREAM_API = os.environ.get("TASTEGRAPH_UPSTREAM_API", "http://127.0.0.1:8787")  # 图谱/周报/候选池 API


def _cors_origin_for(origin: str | None) -> str | None:
    """请求 Origin 命中白名单才回该 origin；默认白名单为空 → 跨域一律不带 CORS 头。"""
    if origin and origin.rstrip("/") in ALLOWED_ORIGINS:
        return origin
    return None


# ── 工作台策展状态（服务端权威）：记录每个 pack 的最后保存/下载时间，
#    供首页「今天唯一下一步」状态卡与「最后保存于 HH:MM」展示。 ──

def _load_workbench_state() -> dict:
    try:
        return json.loads(WORKBENCH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_workbench_state(state: dict) -> None:
    try:
        WORKBENCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        WORKBENCH_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # 状态记录失败不阻塞策展操作


def _mark_pack_state(pack_path: Path, key: str) -> None:
    """key: 'saved_at' | 'zip_at'。pack_path 用相对 posts/ 的键存储。"""
    try:
        rel = str(pack_path.resolve().relative_to(POSTS_DIR.resolve()))
    except Exception:
        return
    state = _load_workbench_state()
    entry = state.get(rel, {})
    entry[key] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    state[rel] = entry
    _save_workbench_state(state)


def _today_next_step() -> dict:
    """首页「今天唯一下一步」：
    开始挑图 / 继续编辑 / 下载发布包 / 回填反馈 / 系统异常 / 今日无新候选。"""
    today = datetime.now().strftime("%Y-%m-%d")
    posts_today = POSTS_DIR / today
    packs = sorted(p for p in posts_today.glob("*") if p.is_dir()) if posts_today.is_dir() else []

    ingest = None
    try:
        ingest = json.loads(INGEST_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    if not packs:
        if not ingest:
            return {
                "state": "error",
                "title": "系统异常",
                "text": "今天还没有采集记录（daily_ingestion 未跑或状态文件缺失）。",
                "href": "", "cta": "",
            }
        if ingest.get("status") not in ("succeeded", "partial"):
            return {
                "state": "error",
                "title": "系统异常",
                "text": f"采集状态异常：{ingest.get('status', '?')}。{ingest.get('error_summary', '')}",
                "href": "", "cta": "",
            }
        return {
            "state": "empty",
            "title": "今日无新候选",
            "text": "采集正常结束但候选池为空，可从编辑台继续翻看历史包。",
            "href": "", "cta": "",
        }

    queue_href = f"/posts/{today}/QUEUE.html"
    try:
        entries = json.loads(PUBLISH_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        entries = []
    today_entries = [e for e in entries if today in str((e or {}).get("pack", ""))]

    def _has_metrics(e: dict) -> bool:
        return any(str(e.get(k, "")) not in ("", "0", "None") for k in ("l24", "l48", "s24", "s48", "c24", "c48"))

    if today_entries:
        if all(_has_metrics(e) for e in today_entries):
            return {
                "state": "done",
                "title": "今天已完成",
                "text": "发布与反馈回填都已登记，明天见。",
                "href": "/publish-log", "cta": "查看发布账本",
            }
        return {
            "state": "feedback",
            "title": "回填反馈",
            "text": "今天已登记发布 — 发布后 24h/48h 记得回填点赞/收藏/评论。",
            "href": "/publish-log", "cta": "去回填",
        }

    wb_state = _load_workbench_state()
    pack_keys = [str(p.resolve().relative_to(POSTS_DIR.resolve())) for p in packs]
    zipped = any(wb_state.get(k, {}).get("zip_at") for k in pack_keys)
    edited = any(wb_state.get(k, {}).get("saved_at") for k in pack_keys)

    if zipped:
        return {
            "state": "publish",
            "title": "下载发布包",
            "text": "发布包已下载 — 在小红书人工发布后，回到这里登记（30 秒）。",
            "href": "/publish-log", "cta": "去登记发布",
        }
    if edited:
        return {
            "state": "edit",
            "title": "继续编辑",
            "text": "今天的方案已有草稿保存 — 换图、改写观点，定稿后下载九图发布包。",
            "href": queue_href, "cta": "回编辑台",
        }
    return {
        "state": "pick",
        "title": "开始挑图",
        "text": f"今天有 {len(packs)} 套候选方案 — 挑一套，换图，把观点改成你的话。",
        "href": queue_href, "cta": "打开编辑台",
    }

_TREND_CSS = """
:root { --bg:#f5f5f7; --card:#fff; --ink:#1d1d1f; --mut:#6e6e73; --line:#e5e5ea; --green:#1a6b4f; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--ink); font-family:-apple-system,"PingFang SC",sans-serif; -webkit-font-smoothing:antialiased; }
.bar { height:3px; background:var(--green); }
.wrap { max-width:720px; margin:0 auto; padding:36px 20px 80px; }
h1 { font-size:26px; font-weight:700; margin:18px 0 6px; }
h2 { font-size:18px; font-weight:700; margin:26px 0 10px; color:var(--green); }
h3 { font-size:15px; font-weight:600; margin:16px 0 6px; }
p, li { font-size:14px; line-height:1.9; color:var(--ink); }
ul { padding-left:20px; }
blockquote { border-left:3px solid var(--green); padding:8px 14px; margin:12px 0; background:var(--card); border-radius:0 10px 10px 0; }
.back { display:inline-block; margin-top:28px; font-size:13px; color:var(--mut); text-decoration:none; }
.back:hover { color:var(--ink); }
"""


def _md_to_html(md: str) -> str:
    """极简 markdown → HTML（够趋势简报用：标题/列表/引用/加粗）。"""
    import html as _h
    import re as _re
    out = []
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("# "):
            out.append(f"<h1>{_h.escape(s[2:])}</h1>")
        elif s.startswith("## "):
            out.append(f"<h2>{_h.escape(s[3:])}</h2>")
        elif s.startswith("### "):
            out.append(f"<h3>{_h.escape(s[4:])}</h3>")
        elif s.startswith("> "):
            out.append(f"<blockquote>{_h.escape(s[2:])}</blockquote>")
        elif _re.match(r"^\d+\.\s", s):
            out.append(f"<li>{_h.escape(_re.sub(r'^\\d+\\.\\s', '', s))}</li>")
        elif s.startswith("- "):
            out.append(f"<li>{_h.escape(s[2:])}</li>")
        elif not s.strip():
            continue
        else:
            t = _h.escape(s)
            t = t.replace("**", "<b>", 1).replace("**", "</b>", 1)
            out.append(f"<p>{t}</p>")
    return "\\n".join(out)

# 换图同步图注需要 DEEPSEEK_API_KEY（与 generate_publish_packs 同源 .env）
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>moodboard. 工作台</title>
<style>
  :root {{
    --bg:#f5f5f7; --card:#ffffff; --ink:#1d1d1f; --mut:#6e6e73; --faint:#aeaeb2;
    --line:#e5e5ea; --green:#1a6b4f; --green-soft:#eef5f1; --red:#c0392b; --red-soft:#fbecea;
    --sans:-apple-system,"PingFang SC",sans-serif;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--ink); font-family:var(--sans); -webkit-font-smoothing:antialiased; }}
  .bar {{ height:3px; background:var(--green); }}
  .wrap {{ max-width:880px; margin:0 auto; padding:0 20px 70px; }}

  .top {{ display:flex; justify-content:space-between; align-items:center; padding:26px 0 16px; }}
  .top .brand {{ font-size:24px; font-weight:700; letter-spacing:-.02em; }}
  .top .brand .dot {{ color:var(--green); }}
  .top .meta {{ font-size:13px; color:var(--mut); }}

  /* ── 今天唯一下一步状态卡 ── */
  .next {{ background:var(--card); border:1px solid var(--line); border-radius:18px;
           padding:26px 28px; margin:10px 0 26px; border-left:5px solid var(--green); }}
  .next.error {{ border-left-color:var(--red); }}
  .next .k {{ font-size:11px; font-weight:700; letter-spacing:.08em; color:var(--green); margin-bottom:8px; }}
  .next.error .k {{ color:var(--red); }}
  .next h1 {{ font-size:26px; font-weight:700; letter-spacing:-.02em; margin-bottom:6px; }}
  .next p {{ font-size:14px; color:var(--mut); line-height:1.7; margin-bottom:16px; }}
  .next .cta {{ display:inline-block; background:var(--green); color:#fff; font-size:14px; font-weight:600;
                padding:10px 22px; border-radius:12px; text-decoration:none; }}
  .next .meta-line {{ font-size:12px; color:var(--faint); margin-top:14px; }}

  .steps {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:24px; }}
  @media (max-width:760px) {{ .steps {{ grid-template-columns:repeat(2,1fr); }} }}
  .step {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }}
  .step .n {{ font-size:11px; font-weight:700; color:var(--green); margin-bottom:5px; }}
  .step b {{ display:block; font-size:13px; margin-bottom:2px; }}
  .step span {{ font-size:12px; color:var(--mut); line-height:1.5; }}

  .links {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .links a {{
    display:block; background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:18px; text-decoration:none; color:var(--ink); transition:border-color .15s;
  }}
  .links a:hover {{ border-color:var(--green); }}
  .links .k {{ font-size:11px; font-weight:700; color:var(--green); display:block; margin-bottom:6px; }}
  .links b {{ display:block; font-size:15px; margin-bottom:4px; }}
  .links span {{ font-size:12px; color:var(--mut); }}
  .foot {{ margin-top:26px; font-size:12px; color:var(--faint); }}
  @media (max-width:600px) {{ .links {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="bar"></div>
<div class="wrap">
  <div class="top">
    <div class="brand">moodboard<span class="dot">.</span></div>
    <div class="meta">个人视觉采样系统 · 机器出方案，人做判断</div>
  </div>

  <div class="next {card_cls}">
    <div class="k">今天唯一下一步 · {today}</div>
    <h1>{next_title}</h1>
    <p>{next_text}</p>
    {cta_block}
    <div class="meta-line">{meta_line}</div>
  </div>

  <div class="steps">
    <div class="step"><span class="n">1</span><b>挑一套</b><span>综合 + 5 个栏目</span></div>
    <div class="step"><span class="n">2</span><b>换图</b><span>悬停帧上 ⇄，图注自动同步</span></div>
    <div class="step"><span class="n">3</span><b>改写观点</b><span>终稿必须是你的话</span></div>
    <div class="step"><span class="n">4</span><b>发布</b><span>下载九图 ZIP，手动发</span></div>
    <div class="step"><span class="n">5</span><b>登记</b><span>30 秒，24/48h 回填</span></div>
  </div>

  <nav class="links">
    <a href="{queue_href}"><span class="k">01 · CURATE</span><b>✏️ 编辑台</b><span>候选方案 · 挑图 · 改写 · 下载发布包</span></a>
    <a href="/publish-log"><span class="k">02 · LOG</span><b>📓 发布登记</b><span>登记 + 24h/48h 回填 + 周汇总</span></a>
    <a href="/sources"><span class="k">03 · SOURCES</span><b>📡 信息源</b><span>源面板与健康度</span></a>
  </nav>

  <div class="foot">全部操作在浏览器内完成；数据本地保存，不碰小红书。自动发布永久禁用。</div>
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

        # ── / → 每日工作台首页（今天唯一下一步状态卡） ──
        if parsed.path == "/":
            import html as _h

            step = _today_next_step()
            date_dirs = sorted(POSTS_DIR.glob("20*"), reverse=True)
            queue_href = (
                step.get("href")
                if step.get("state") in ("pick", "edit") and step.get("href")
                else (f"/posts/{date_dirs[0].name}/QUEUE.html" if date_dirs else "#")
            )
            cta_block = (
                f'<a class="cta" href="{_h.escape(step["href"])}">{_h.escape(step["cta"])}</a>'
                if step.get("href") and step.get("cta")
                else ""
            )
            meta_line = self._ingest_meta_line()

            body = _INDEX_HTML
            repl = {
                "{card_cls}": "error" if step["state"] == "error" else "",
                "{today}": datetime.now().strftime("%Y-%m-%d"),
                "{next_title}": _h.escape(step["title"]),
                "{next_text}": _h.escape(step["text"]),
                "{cta_block}": cta_block,
                "{meta_line}": _h.escape(meta_line),
                "{queue_href}": _h.escape(queue_href),
            }
            for k, v in repl.items():
                body = body.replace(k, v)
            body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── /trend-report → 最新编前会纪要（周一 10:00 自动生成） ──
        if parsed.path == "/trend-report":
            reports = sorted((BASE_DIR / "data").glob("trend-report-*.md"), reverse=True)
            if not reports:
                self._json({"ok": False, "error": "暂无编前会纪要 — 周一 10:00 自动生成"}, status=404)
                return
            md = reports[0].read_text(encoding="utf-8")
            html = (
                "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>编前会 — {reports[0].stem}</title><style>{_TREND_CSS}</style></head><body>"
                "<div class=\"bar\"></div><div class=\"wrap\">"
                + _md_to_html(md)
                + "<a class=\"back\" href=\"/posts/\">&larr; 回工作台</a></div></body></html>"
            )
            body = html.encode("utf-8")
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
                self._send_cors()
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
                        "keywords": im.get("keywords", []),
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
            kw = params.get("kw", [""])[0]
            srcname = params.get("srcname", [""])[0]
            try:
                if src_path.suffix.lower() == ".png":
                    subprocess.run(
                        ["sips", "-s", "format", "jpeg", str(src_path), "--out", str(target)],
                        capture_output=True, timeout=30, check=True,
                    )
                else:
                    shutil.copyfile(src_path, target)

                # 图注同步：生成一句话图注并回写 body.txt 第 0N 行
                caption = self._caption_for_frame(pack_dir, kw, srcname)
                body_path = pack_dir / "body.txt"
                if body_path.exists():
                    lines = body_path.read_text(encoding="utf-8").splitlines()
                    new_line = f"{pos_n:02d} {caption}"
                    replaced = False
                    for li, line in enumerate(lines):
                        if line.startswith(f"{pos_n:02d} "):
                            lines[li] = new_line
                            replaced = True
                            break
                    if not replaced:
                        lines.append(new_line)
                    body_path.write_text("\n".join(lines), encoding="utf-8")

                self._json({"ok": True, "rel": str(target.relative_to(BASE_DIR)), "caption": caption})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)
            return

        # ── /save-file?path=...&content=... → 草稿服务端落盘（策展权威存储） ──
        if parsed.path == "/save-file":
            params = urllib.parse.parse_qs(parsed.query)
            path = params.get("path", [None])[0]
            content = params.get("content", [""])[0]
            if path and Path(path).parent.exists():
                try:
                    target = Path(path)
                    target.write_text(content, encoding="utf-8")
                    # 记录 pack 级保存时间（posts/ 下的文案文件）供状态卡/「最后保存于」
                    if target.suffix == ".txt":
                        _mark_pack_state(target.parent, "saved_at")
                    self._json({"ok": True, "path": path})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)}, status=500)
            else:
                self._json({"ok": False, "error": "path not found or parent missing"}, status=404)
            return

        # ── /sources → live source dashboard ──
        if parsed.path == "/sources":
            try:
                from scripts.source_dashboard import build
                build()
                self.send_response(302)
                self.send_header("Location", "/data/sources.html")
                self.end_headers()
            except Exception as e:
                # DB 未就绪/迁移未跑时返回 JSON 500，不断连接
                self._json({"ok": False, "error": f"源面板构建失败: {e}"}, status=500)
            return

        # ── /pack-zip?pack=<abs pack dir> → 打包该包 9 帧为 ZIP 下载 ──
        # （浏览器内能力，替代旧的 Finder/Preview/剪贴板远程动作）
        if parsed.path == "/pack-zip":
            params = urllib.parse.parse_qs(parsed.query)
            pack = params.get("pack", [None])[0]
            if not pack:
                self._json({"ok": False, "error": "missing pack"}, status=400)
                return
            pack_dir = Path(pack)
            try:
                pack_res = pack_dir.resolve()
                posts_res = POSTS_DIR.resolve()
                if pack_res != posts_res and posts_res not in pack_res.parents:
                    self._json({"ok": False, "error": "pack must be under posts/"}, status=403)
                    return
            except Exception:
                self._json({"ok": False, "error": "bad pack path"}, status=400)
                return
            imgs = sorted([p for p in pack_dir.glob("image*") if p.is_file()])
            if not imgs:
                self._json({"ok": False, "error": "no images in pack"}, status=404)
                return
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for img in imgs:
                    zf.write(img, arcname=img.name)
            buf.seek(0)
            data = buf.read()
            zip_name = f"{pack_res.parent.name}-{pack_res.name}.zip"
            _mark_pack_state(pack_res, "zip_at")
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
                self._send_cors()
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
        # 契约 §0.3：发布时间唯一字段 published_at（兼容旧前端发的 time）
        if "time" in payload and "published_at" not in payload:
            payload["published_at"] = payload["time"]
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

        # ── 数据单源化：publish-log 为唯一入口，有真实数据时镜像到图谱做调权 ──
        def _num(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0

        if not payload.get("delete"):
            # 契约 §0.5：24h/48h 是累计快照（48h 含 24h），最新窗口优先，绝不相加。
            likes = _num(payload.get("l48")) if payload.get("l48") not in (None, "") else _num(payload.get("l24"))
            saves = _num(payload.get("s48")) if payload.get("s48") not in (None, "") else _num(payload.get("s24"))
            comments = _num(payload.get("c48")) if payload.get("c48") not in (None, "") else _num(payload.get("c24"))
            if likes or saves or comments:
                try:
                    metrics = {
                        "pack_id": payload.get("pack", ""),
                        "likes": likes,
                        "saves": saves,
                        "comments": comments,
                        "shares": 0,
                        "post_url": payload.get("link", ""),
                    }
                    req = urllib.request.Request(
                        UPSTREAM_API + "/api/v1/feedback/publish-metrics",
                        data=json.dumps(metrics).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=10).read()
                except Exception:
                    pass  # 图谱不在线不阻塞登记

    def _ingest_meta_line(self) -> str:
        """首页状态卡小字：今日采集摘要（读 daily_ingestion_status.json）。"""
        try:
            st = json.loads(INGEST_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return "采集状态不可用（data/daily_ingestion_status.json 缺失）。"
        finished = str(st.get("finished_at") or "")[:16].replace("T", " ")
        parts = [
            f"采集 {finished or '时间未知'}",
            f"下载 {st.get('images_downloaded', 0)} 张",
            f"出包 {'是' if st.get('pack_generated') else '否'}",
        ]
        if st.get("status") == "partial" and st.get("error_summary"):
            parts.append(f"部分失败：{st['error_summary'][:80]}")
        return " · ".join(parts)

    def _caption_for_frame(self, pack_dir: Path, kw: str, srcname: str) -> str:
        """为换入的第 N 帧生成一句话图注（DeepSeek，失败则模板）。含来源后缀。"""
        ctx = ""
        for name in ("title.txt", "opinion_draft.txt"):
            p = pack_dir / name
            if p.exists():
                ctx += p.read_text(encoding="utf-8").strip()[:200] + " "
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key and (kw or ctx):
            try:
                prompt = (
                    "小红书 moodboard 笔记，一包 9 帧图，每帧一句话图注。\n"
                    f"本包标题与观点：{ctx.strip() or '（无）'}\n"
                    f"新图关键词：{kw or '（无）'}\n"
                    f"来源：{srcname or 'archive'}\n"
                    "写一句话图注（≤18 字），与全包语气一致，quiet editorial，不要营销腔，不要引号。只输出图注本身。"
                )
                req = urllib.request.Request(
                    "https://api.deepseek.com/v1/chat/completions",
                    data=json.dumps({
                        "model": "deepseek-chat",
                        "max_tokens": 60,
                        "messages": [{"role": "user", "content": prompt}],
                    }).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=20)
                out = json.loads(resp.read().decode("utf-8"))
                text = out["choices"][0]["message"]["content"].strip().strip('"')
                if text:
                    return f"{text} — {srcname}" if srcname else text
            except Exception:
                pass
        base = srcname or "archive"
        return f"{kw.split()[0]} · {base}" if kw else f"来自 {base} 的新帧"

    def _send_cors(self):
        """命中白名单的 Origin 才回 CORS 头；默认无白名单 = 同源 only。"""
        origin = _cors_origin_for(self.headers.get("Origin"))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        origin = _cors_origin_for(self.headers.get("Origin"))
        if origin:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._json({"ok": False, "error": "origin not allowed"}, status=403)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging: suppress routine 200s for static/asset requests
        if "/pack-zip" in str(args) or "/save-file" in str(args) or "/replace-image" in str(args):
            print(f"  {args[0]}")
        elif "200" in fmt:
            pass
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
    print(f"   编辑台：页内预览 · 单张/九图 ZIP 下载 · 复制文案（全部浏览器内完成）")
    print(f"   自动发布永久禁用；无 osascript/pbcopy/open 远程动作端点")
    print(f"   Press Ctrl+C to stop")

    if ALLOWED_ORIGINS:
        print(f"   CORS 白名单: {ALLOWED_ORIGINS}")
    else:
        print("   CORS: 同源 only（TASTEGRAPH_ALLOWED_ORIGINS 未配置）")
    server = None
    bound_port = None
    for try_port in (PORT, 8766, 8767):
        try:
            server = http.server.ThreadingHTTPServer((HOST, try_port), QueueHandler)
            bound_port = try_port
            break
        except OSError:
            print(f"   port {try_port} busy → trying next")
    if server is None:
        print("No free port (8765-8767). Stop another service first.")
        sys.exit(1)
    print(f"   绑定: {HOST}:{bound_port}（环回=仅本机；Tailscale 见 operations.md §7）")
    print(f"   工作台: http://localhost:{bound_port}/")
    print(f"   编辑队列: http://localhost:{bound_port}/posts/{latest.name}/QUEUE.html")
    print(f"   发布登记: http://localhost:{bound_port}/publish-log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
