"""
Selector Health Checker for Xiaohongshu CDP Publisher.

Verifies DOM selectors defined in cdp_publish.py against the live Xiaohongshu
creator center page.  Detects selector breakage before a publish run.

Usage:
    python3 scripts/check_selectors.py
    python3 scripts/check_selectors.py --json
    python3 scripts/check_selectors.py --save-snapshot

Exit codes:
    0  All selectors matched.
    1  One or more selectors failed to match.
    2  Could not connect to Chrome / navigate to the page.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path setup -- allow importing from the sibling xhs_publisher package
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)  # one level up from scripts/
sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import requests
import websockets.sync.client as ws_client

from xhs_publisher.chrome_launcher import (
    CDP_PORT,
    ensure_chrome,
    is_port_open,
)
from xhs_publisher.cdp_publish import SELECTORS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CREATOR_CENTER_URL = "https://creator.xiaohongshu.com"
NAVIGATION_TIMEOUT = 30  # seconds to wait for page load
DEFAULT_HEADLESS = False  # headed by default so the user can see the page

# Selectors considered "critical" -- their failure will stop the publish flow.
# (The remaining selectors are informational / used for text matching.)
CRITICAL_KEYS = {
    "image_text_tab",
    "image_text_tab_text",
    "upload_input",
    "upload_input_alt",
    "title_input",
    "title_input_alt",
    "content_editor",
    "content_editor_alt",
    "content_editor_alt2",
    "publish_button",
}


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------
def _cdp_http(host: str, port: int, endpoint: str) -> list:
    """Call a CDP HTTP endpoint and return the JSON list of targets."""
    url = f"http://{host}:{port}{endpoint}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _find_page_target(host: str, port: int) -> str | None:
    """Find a WebSocket URL for the creator.xiaohongshu.com tab.

    Returns the first matching page's webSocketDebuggerUrl, or None.
    """
    try:
        targets = _cdp_http(host, port, "/json")
    except Exception as exc:
        print(f"[check_selectors] Error listing CDP targets: {exc}",
              file=sys.stderr)
        return None

    for t in targets:
        url = t.get("url", "")
        if "creator.xiaohongshu.com" in url:
            return t.get("webSocketDebuggerUrl")

    # If no matching tab exists, create one
    return None


def _create_new_tab(host: str, port: int) -> str | None:
    """Open a new tab and navigate to the creator center.

    Returns the webSocketDebuggerUrl of the new tab, or None.
    """
    try:
        targets = _cdp_http(host, port, "/json/new")
    except Exception as exc:
        print(f"[check_selectors] Error creating new tab: {exc}",
              file=sys.stderr)
        return None

    # /json/new returns a single target object (or a list of one)
    if isinstance(targets, list):
        target = targets[0]
    else:
        target = targets

    return target.get("webSocketDebuggerUrl")


def _send_cdp(ws_url: str, method: str, params: dict | None = None) -> dict:
    """Send a CDP command over a WebSocket connection and return the result."""
    import json as _json

    msg_id = int(time.time() * 1000)
    payload: dict = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params

    with ws_client.connect(ws_url, close_timeout=5) as ws:
        ws.send(_json.dumps(payload))
        while True:
            resp = _json.loads(ws.recv(timeout=NAVIGATION_TIMEOUT))
            if resp.get("id") == msg_id:
                return resp.get("result", {})


def _navigate(ws_url: str, url: str) -> bool:
    """Navigate to *url* and wait for the page to be fully loaded.

    Returns True on success.
    """
    try:
        _send_cdp(ws_url, "Page.enable")
        _send_cdp(ws_url, "Page.navigate", {"url": url})
    except Exception as exc:
        print(f"[check_selectors] Navigation failed: {exc}", file=sys.stderr)
        return False

    # Wait for Page.loadEventFired
    deadline = time.time() + NAVIGATION_TIMEOUT
    while time.time() < deadline:
        try:
            with ws_client.connect(ws_url, close_timeout=5) as ws:
                ws.send(
                    '{"id":%d,"method":"Page.loadEventFired"}'
                    % (int(time.time() * 1000),)
                )
                resp = ws.recv(timeout=5)
                import json as _json
                if _json.loads(resp).get("method") == "Page.loadEventFired":
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _evaluate_js(ws_url: str, js: str) -> dict:
    """Evaluate JavaScript in the page context and return the result dict."""
    return _send_cdp(ws_url, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
    })


def _take_screenshot(ws_url: str, filepath: str) -> bool:
    """Capture a page screenshot and save it to *filepath*."""
    try:
        result = _send_cdp(ws_url, "Page.captureScreenshot", {"format": "png"})
        data = result.get("data", "")
        if not data:
            print("[check_selectors] Screenshot result has no data.",
                  file=sys.stderr)
            return False
        import base64
        png_bytes = base64.b64decode(data)
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(png_bytes)
        return True
    except Exception as exc:
        print(f"[check_selectors] Screenshot failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Selector checking
# ---------------------------------------------------------------------------
def _build_selector_check_js(selectors: dict) -> str:
    """Build a single JS expression that checks all selectors.

    Returns a JSON string (via JSON.stringify) mapping selector name to
    {count, text, outer_html} for diagnostic purposes.
    """
    conditions = []
    for name, sel in selectors.items():
        sel_escaped = sel.replace("\\", "\\\\").replace("'", "\\'")
        conditions.append(
            f"'{name}': (function(s){{"
            f"  try{{"
            f"    var els = document.querySelectorAll(s);"
            f"    return {{count: els.length, text: els.length>0 ? (els[0].textContent||'').trim().slice(0,80) : null}};"
            f"  }}catch(e){{"
            f"    return {{count: -1, text: 'INVALID_SELECTOR: '+e.message}};"
            f"  }}"
            f"}})('{sel_escaped}')"
        )
    return "JSON.stringify({" + ",".join(conditions) + "})"


def check_selectors(selectors: dict, ws_url: str) -> dict[str, dict]:
    """Check each selector in the live page.

    Returns a dict mapping selector name -> {"count": int, "text": str|None}.
    count == -1 means the selector string itself is invalid.
    """
    js = _build_selector_check_js(selectors)
    result = _evaluate_js(ws_url, js)
    raw = result.get("result", {}).get("value", "{}")
    try:
        import json as _json
        parsed = _json.loads(raw)
    except Exception as exc:
        print(f"[check_selectors] Failed to parse JS result: {exc}",
              file=sys.stderr)
        return {}
    # Ensure all keys are present
    for name in selectors:
        if name not in parsed:
            parsed[name] = {"count": -2, "text": "NOT_CHECKED"}
    return parsed


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(
    results: dict[str, dict],
    critical_keys: set[str],
    output_json: bool = False,
) -> dict:
    """Generate a structured report from the selector check results.

    Returns a dict with the report data.
    """
    passed = []
    failed = []
    total = len(results)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for name, info in results.items():
        count = info.get("count", -2)
        text = info.get("text", "")
        sel = SELECTORS.get(name, "?")
        if count > 0:
            passed.append({"name": name, "selector": sel, "count": count, "text": text})
        else:
            failed.append({
                "name": name,
                "selector": sel,
                "count": count,
                "reason": "invalid selector syntax" if count == -1
                           else "not found" if count == 0
                           else "not checked",
            })

    pass_count = len(passed)
    fail_count = len(failed)

    # Build suggestions for failed critical selectors
    suggestions = []
    for f in failed:
        if f["name"] in critical_keys:
            suggestions.append(f['name'])

    report = {
        "date": today,
        "total": total,
        "passed": pass_count,
        "failed": fail_count,
        "passed_selectors": passed,
        "failed_selectors": failed,
        "suggestions": suggestions,
        "all_pass": fail_count == 0,
    }

    if output_json:
        return report

    # Pretty-print
    print(f"选择器验证报告 — {today}")
    print("=" * 40)
    for name, info in sorted(results.items()):
        count = info.get("count", -2)
        sel = SELECTORS.get(name, "?")
        if count > 0:
            status = "✅"
            extra = f"匹配 ({count} elements)"
            if info.get("text"):
                extra += f"  text: {info['text'][:60]}"
        elif count == 0:
            status = "❌"
            extra = "不匹配 (0 elements)"
        elif count == -1:
            status = "⚠️"
            extra = "选择器语法错误"
        else:
            status = "❓"
            extra = "未检查"
        print(f" {status} {name}: {sel} → {extra}")

    print()
    print(f"结果: {pass_count}/{total} 通过, {fail_count} 个失效")
    if suggestions:
        print(f"建议: 更新 {' 和 '.join(suggestions)} 的选择器")
    else:
        print("所有选择器均有效。")

    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Verify DOM selectors used by the Xiaohongshu CDP publisher."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output report as JSON instead of human-readable text."
    )
    parser.add_argument(
        "--save-snapshot", action="store_true",
        help="Save a PNG screenshot of the page for manual inspection."
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Chrome CDP host (default: 127.0.0.1)."
    )
    parser.add_argument(
        "--port", type=int, default=CDP_PORT,
        help=f"Chrome CDP port (default: {CDP_PORT})."
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Launch Chrome in headless mode if not already running."
    )
    args = parser.parse_args()

    host = args.host
    port = args.port
    output_json = args.json
    save_snapshot = args.save_snapshot

    # ---- Step 1: Ensure Chrome is running ----
    if not is_port_open(port):
        print(f"[check_selectors] Chrome not running on {host}:{port}, "
              "attempting to launch...", file=sys.stderr)
        if not ensure_chrome(port=port, headless=args.headless):
            print(f"[check_selectors] FAILED: Could not start Chrome on "
                  f"{host}:{port}.", file=sys.stderr)
            # Exit code 2 = cannot connect
            if output_json:
                print(json.dumps({"error": "cannot_connect",
                                  "message": f"Could not start Chrome on {host}:{port}"}))
            sys.exit(2)
        # Wait a moment for CDP to be ready
        time.sleep(2)

    if not is_port_open(port):
        print(f"[check_selectors] FAILED: Port {host}:{port} is not open.",
              file=sys.stderr)
        if output_json:
            print(json.dumps({"error": "cannot_connect",
                              "message": f"Port {host}:{port} is not open"}))
        sys.exit(2)

    # ---- Step 2: Find or create a tab ----
    ws_url = _find_page_target(host, port)
    if ws_url is None:
        print("[check_selectors] No existing creator.xiaohongshu.com tab found. "
              "Opening a new tab...", file=sys.stderr)
        ws_url = _create_new_tab(host, port)

    if ws_url is None:
        print("[check_selectors] FAILED: Could not create a new tab.",
              file=sys.stderr)
        if output_json:
            print(json.dumps({"error": "cannot_connect",
                              "message": "Could not create a new tab"}))
        sys.exit(2)

    # ---- Step 3: Navigate to creator center (if not already there) ----
    print(f"[check_selectors] Navigating to {CREATOR_CENTER_URL}...",
          file=sys.stderr)
    if not _navigate(ws_url, CREATOR_CENTER_URL):
        print("[check_selectors] WARNING: Navigation may not have completed. "
              "Proceeding with selector check anyway.", file=sys.stderr)

    # Give the page some time to render
    time.sleep(3)

    # ---- Step 4: Optionally save a snapshot ----
    if save_snapshot:
        snapshot_dir = os.path.join(_PROJECT_ROOT, "tmp")
        os.makedirs(snapshot_dir, exist_ok=True)
        snapshot_path = os.path.join(
            snapshot_dir,
            f"selector_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        if _take_screenshot(ws_url, snapshot_path):
            print(f"[check_selectors] Snapshot saved to {snapshot_path}",
                  file=sys.stderr)
        else:
            print("[check_selectors] Snapshot failed to save.",
                  file=sys.stderr)

    # ---- Step 5: Check selectors ----
    # We only check the critical selectors defined in the task
    critical_selectors = {
        k: SELECTORS[k] for k in CRITICAL_KEYS if k in SELECTORS
    }

    results = check_selectors(critical_selectors, ws_url)

    # ---- Step 6: Generate and output report ----
    report = generate_report(results, CRITICAL_KEYS, output_json=output_json)

    if output_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    # ---- Step 7: Determine exit code ----
    if report["all_pass"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
