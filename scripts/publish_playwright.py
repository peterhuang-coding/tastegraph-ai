#!/usr/bin/env python3
"""
Xiaohongshu publish via Playwright (alternative to CDP DOM.setFileInputFiles).

Problem:
  CDP's DOM.setFileInputFiles silently sets the file on <input type="file">
  but the Xiaohongshu frontend does not detect the file selection event,
  so the image preview never appears and the editor stays in "upload" mode.

Solution:
  Playwright's locator.setInputFiles() simulates a full browser interaction
  including the change event, which reliably triggers the frontend's upload
  flow.

Usage:
  python3 scripts/publish_playwright.py \
      --title "标题" --content "正文" --images img1.jpg img2.jpg

  python3 scripts/publish_playwright.py \
      --title "标题" --content "正文" --image-dir /path/to/images

  # With timing jitter (default 0.25)
  python3 scripts/publish_playwright.py \
      --title "标题" --content "正文" --images img1.jpg --timing-jitter 0.35

Requirements:
  playwright==1.60.0
  python3 -m playwright install chromium
"""

import argparse
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

# ── Xiaohongshu URLs ────────────────────────────────────────────
XHS_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"

# ── Selectors (same as cdp_publish.py) ──────────────────────────
SELECTORS = {
    "image_text_tab": "div.creator-tab",
    "image_text_tab_text": "上传图文",
    "upload_input": ".upload-input",
    "upload_input_alt": 'input[type="file"]',
    "title_input": "div.d-input input",
    "title_input_alt": 'input[placeholder*="填写标题"], input[placeholder*="标题"], input.d-text',
    "content_editor": "div.tiptap.ProseMirror",
    "content_editor_alt": 'div.ProseMirror[contenteditable="true"]',
    "content_editor_alt2": "div.ql-editor",
    "content_placeholder_text": "输入正文描述",
    "publish_button": ".publish-page-publish-btn button.bg-red",
    "publish_button_text": "发布",
    "image_preview_items": ".img-preview-area .pr",
}

# ── Timing ──────────────────────────────────────────────────────
UPLOAD_WAIT = 8       # seconds to wait after image upload for editor to appear
PAGE_LOAD_WAIT = 5    # seconds to wait after navigation
TAB_CLICK_WAIT = 2.5  # seconds to wait after clicking tab
MAX_TIMING_JITTER = 0.7


def _normalize_timing_jitter(value: float) -> float:
    return max(0.0, min(MAX_TIMING_JITTER, value))


def _jitter_seconds(base: float, jitter_ratio: float, minimum: float = 0.05) -> float:
    if jitter_ratio <= 0:
        return base
    delta = base * jitter_ratio
    low = max(minimum, base - delta)
    high = max(low, base + delta)
    return random.uniform(low, high)


def _jitter_ms(base_ms: int, jitter_ratio: float, minimum_ms: int = 0) -> int:
    base = max(minimum_ms, base_ms)
    if jitter_ratio <= 0:
        return base
    delta = int(round(base * jitter_ratio))
    low = max(minimum_ms, base - delta)
    high = max(low, base + delta)
    return random.randint(low, high)


def _extract_topic_tags(content: str) -> tuple[str, list[str]]:
    """Extract #tags from the last non-empty line of content."""
    lines = content.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return content, []
    last_line = lines[-1].strip()
    parts = [p for p in last_line.split() if p]
    if not parts or not all(re.fullmatch(r"#[^\s#]+", p) for p in parts):
        return content, []
    body = "\n".join(lines[:-1]).strip()
    return body, parts


# ═══════════════════════════════════════════════════════════════
#  Main: Playwright upload + fill + publish
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Xiaohongshu publish via Playwright (alternative to CDP DOM.setFileInputFiles)"
    )
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument("--content", required=True, help="Article body text (may include #tags on last line)")
    parser.add_argument("--images", nargs="*", default=None, help="Local image file paths")
    parser.add_argument("--image-dir", default=None, help="Directory containing image.* files")
    parser.add_argument("--preview", action="store_true", default=False, help="Preview mode: fill form only, don't click publish")
    parser.add_argument("--timing-jitter", type=float, default=0.25, help="Timing jitter ratio (default: 0.25)")
    parser.add_argument("--headless", action="store_true", default=False, help="Run in headless mode")
    parser.add_argument("--cdp-host", default="127.0.0.1", help="CDP host (default: 127.0.0.1)")
    parser.add_argument("--cdp-port", type=int, default=9222, help="CDP remote debugging port (default: 9222)")
    args = parser.parse_args()

    timing_jitter = _normalize_timing_jitter(args.timing_jitter)
    content, topic_tags = _extract_topic_tags(args.content)
    if topic_tags:
        print(f"[playwright] Detected topic tags: {' '.join(topic_tags)}")

    # ── Resolve image files ──────────────────────────────────
    image_paths = []
    if args.image_dir:
        img_dir = Path(args.image_dir)
        image_paths = sorted(str(p) for p in img_dir.glob("image.*"))
    elif args.images:
        image_paths = [os.path.abspath(p) for p in args.images]
    else:
        print("Error: --images or --image-dir required.", file=sys.stderr)
        sys.exit(2)

    # Verify files exist
    valid_paths = []
    for p in image_paths:
        if not os.path.isfile(p):
            print(f"Warning: image file not found: {p}", file=sys.stderr)
        else:
            valid_paths.append(p)
    if not valid_paths:
        print("Error: no valid image files.", file=sys.stderr)
        sys.exit(2)
    image_paths = valid_paths
    print(f"[playwright] Using {len(image_paths)} image(s):")
    for p in image_paths:
        print(f"  {p}")

    # ── Import Playwright (with graceful fallback) ───────────
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Error: Playwright is not installed.\n"
            "  Run: pip3 install playwright\n"
            "  Then: python3 -m playwright install chromium",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Ensure Chromium browser is installed ─────────────────
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            check=False,
        )
    except Exception:
        pass

    # ── Connect to existing Chrome via CDP ───────────────────
    cdp_url = f"http://{args.cdp_host}:{args.cdp_port}"
    print(f"[playwright] Connecting to Chrome at {cdp_url}...")

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(cdp_url)
            except Exception as e:
                print(
                    f"Error: Could not connect to Chrome at {cdp_url}.\n"
                    f"  {e}\n\n"
                    "  Make sure Chrome is running with remote debugging enabled:\n"
                    '    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\\n'
                    '      --remote-debugging-port=9222 \\\n'
                    '      --user-data-dir=/tmp/chrome-debug\n',
                    file=sys.stderr,
                )
                sys.exit(2)

            # ── Find or create a Xiaohongshu tab ───────────────
            target_page = None
            for page in browser.contexts[0].pages if browser.contexts else []:
                url = page.url
                if "creator.xiaohongshu.com" in url or "xiaohongshu.com" in url:
                    target_page = page
                    print(f"[playwright] Reusing existing tab: {url[:80]}")
                    break

            if not target_page:
                context = browser.contexts[0] if browser.contexts else None
                if context:
                    target_page = context.new_page()
                    print("[playwright] Created new tab")
                else:
                    print("Error: No browser context available.", file=sys.stderr)
                    sys.exit(2)

            # ── Navigate to creator publish page ───────────────
            print(f"[playwright] Navigating to {XHS_CREATOR_URL}...")
            target_page.goto(XHS_CREATOR_URL, wait_until="networkidle", timeout=30000)
            time.sleep(_jitter_seconds(PAGE_LOAD_WAIT, timing_jitter, 2.0))

            # Check if we're on the login page
            if "/login" in target_page.url:
                print("[playwright] Not logged in. Please login first.")
                sys.exit(1)

            # ── Click "上传图文" tab ───────────────────────────
            print("[playwright] Clicking '上传图文' tab...")
            try:
                tab_button = target_page.locator(SELECTORS["image_text_tab"]).filter(
                    has_text=SELECTORS["image_text_tab_text"]
                ).first
                tab_button.wait_for(state="visible", timeout=10000)
                tab_button.click()
                time.sleep(_jitter_seconds(TAB_CLICK_WAIT, timing_jitter, 1.0))
            except Exception as e:
                print(f"[playwright] Warning: Could not click '上传图文' tab: {e}")
                print("[playwright] Maybe already on the right tab.")

            # ── Upload images via Playwright's setInputFiles ──
            print(f"[playwright] Uploading {len(image_paths)} image(s) via setInputFiles...")

            # Find the file input element
            file_input = None
            for selector in [SELECTORS["upload_input"], SELECTORS["upload_input_alt"]]:
                try:
                    file_input = target_page.locator(selector).first
                    if file_input.count() > 0:
                        print(f"[playwright] Found file input via selector: '{selector}'")
                        break
                except Exception:
                    continue

            if file_input is None or file_input.count() == 0:
                print(
                    "Error: Could not find file input element.\n"
                    "  Tried selectors: .upload-input, input[type='file']",
                    file=sys.stderr,
                )
                # Debug: dump input elements on page
                input_count = target_page.locator('input[type="file"]').count()
                upload_input_count = target_page.locator(".upload-input").count()
                print(f"[playwright] Debug: input[type='file'] count = {input_count}")
                print(f"[playwright] Debug: .upload-input count = {upload_input_count}")
                sys.exit(2)

            # Upload each image one by one (like the original flow)
            for idx, img_path in enumerate(image_paths):
                print(f"[playwright] Uploading image {idx+1}/{len(image_paths)}: {img_path}")
                try:
                    file_input.setInputFiles(img_path)
                    print(f"[playwright]   setInputFiles succeeded for image {idx+1}")
                except Exception as e:
                    print(f"[playwright]   setInputFiles failed for image {idx+1}: {e}", file=sys.stderr)
                    # Try with absolute path
                    abs_path = os.path.abspath(img_path)
                    if abs_path != img_path:
                        try:
                            file_input.setInputFiles(abs_path)
                            print(f"[playwright]   Retry with abs path succeeded: {abs_path}")
                        except Exception as e2:
                            print(f"[playwright]   Retry also failed: {e2}", file=sys.stderr)
                            sys.exit(2)

                # Wait for preview to appear
                print(f"[playwright]   Waiting for preview ({UPLOAD_WAIT}s timeout)...")
                preview_found = _wait_for_image_preview(target_page, idx + 1, timeout=UPLOAD_WAIT)
                if preview_found:
                    print(f"[playwright]   Preview {idx+1}/{len(image_paths)} appeared!")
                else:
                    print(f"[playwright]   Warning: Preview {idx+1} did not appear within timeout.")
                    print(f"[playwright]   Current page URL: {target_page.url}")
                    # Try to screenshot for debugging
                    try:
                        screenshot_path = os.path.join(
                            PROJECT_DIR, "tmp", f"playwright_upload_{idx+1}.png"
                        )
                        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                        target_page.screenshot(path=screenshot_path, full_page=True)
                        print(f"[playwright]   Screenshot saved to: {screenshot_path}")
                    except Exception:
                        pass

                time.sleep(_jitter_seconds(0.5, timing_jitter, 0.2))

            # ── Wait for editor to fully appear ────────────────
            print("[playwright] Waiting for editor to appear after upload...")
            time.sleep(_jitter_seconds(UPLOAD_WAIT, timing_jitter, 2.0))

            # ── Fill title ─────────────────────────────────────
            print("[playwright] Filling title...")
            title_input = None
            for selector in [SELECTORS["title_input"], SELECTORS["title_input_alt"]]:
                try:
                    el = target_page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        title_input = el
                        break
                except Exception:
                    continue

            if title_input:
                time.sleep(_jitter_seconds(0.5, timing_jitter, 0.2))
                title_input.click()
                time.sleep(_jitter_seconds(0.3, timing_jitter, 0.1))
                title_input.fill(args.title)
                print(f"[playwright] Title filled: {args.title[:50]}...")
            else:
                print("[playwright] Warning: Could not find title input.")

            # ── Fill content ────────────────────────────────────
            print("[playwright] Filling content...")
            content_editor = None
            for selector in [
                SELECTORS["content_editor"],
                SELECTORS["content_editor_alt"],
                SELECTORS["content_editor_alt2"],
                "[role='textbox']",
            ]:
                try:
                    el = target_page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        content_editor = el
                        break
                except Exception:
                    continue

            if content_editor:
                time.sleep(_jitter_seconds(0.5, timing_jitter, 0.2))
                content_editor.click()
                time.sleep(_jitter_seconds(0.3, timing_jitter, 0.1))
                content_editor.fill(content)
                print(f"[playwright] Content filled ({len(content)} chars)")
            else:
                print("[playwright] Warning: Could not find content editor.")

            # ── Handle topic tags ───────────────────────────────
            if topic_tags:
                print(f"[playwright] Adding {len(topic_tags)} topic tag(s)...")
                _add_topic_tags(target_page, topic_tags, timing_jitter)

            # ── Publish (unless preview mode) ───────────────────
            if not args.preview:
                print("[playwright] Clicking publish button...")
                try:
                    publish_btn = target_page.locator(SELECTORS["publish_button"]).first
                    publish_btn.wait_for(state="visible", timeout=15000)
                    time.sleep(_jitter_seconds(1.0, timing_jitter, 0.5))
                    publish_btn.click()
                    print("[playwright] Publish button clicked!")
                except Exception as e:
                    print(f"[playwright] Warning: Could not click publish: {e}")
            else:
                print("[playwright] Preview mode: form filled, not publishing.")

            print("[playwright] Done.")
            sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


def _wait_for_image_preview(page, expected_count: int, timeout: float = 8.0) -> bool:
    """Wait until image preview count reaches expected_count.

    Uses the same selectors as cdp_publish.py's _count_uploaded_images().
    """
    import time as _time
    deadline = _time.time() + timeout
    selectors = [
        SELECTORS["image_preview_items"],
        ".img-preview-area [class*='preview']",
        ".draggable-item",
        "[class*='img-preview'] .pr",
    ]

    while _time.time() < deadline:
        max_count = 0
        for sel in selectors:
            try:
                count = page.locator(sel).count()
                max_count = max(max_count, count)
            except Exception:
                pass

        if max_count > 0:
            print(f"[playwright]   Preview count: {max_count}/{expected_count}")
        if max_count >= expected_count:
            return True

        _time.sleep(0.5)

    # Final check
    max_count = 0
    for sel in selectors:
        try:
            count = page.locator(sel).count()
            max_count = max(max_count, count)
        except Exception:
            pass
    if max_count >= expected_count:
        return True

    return False


def _add_topic_tags(page, tags: list[str], timing_jitter: float):
    """Add topic tags by typing into the content editor."""
    import time as _time

    for idx, tag in enumerate(tags):
        normalized = tag.lstrip("#").strip()
        if not normalized:
            continue

        hash_pause = _jitter_ms(180, timing_jitter, 90)
        char_delay_min = _jitter_ms(45, timing_jitter, 25)
        char_delay_max = _jitter_ms(95, timing_jitter, char_delay_min)
        suggest_wait = _jitter_ms(3000, timing_jitter, 1600)

        # Focus editor
        for selector in [
            SELECTORS["content_editor"],
            SELECTORS["content_editor_alt"],
            SELECTORS["content_editor_alt2"],
            "[role='textbox']",
        ]:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    el.click()
                    break
            except Exception:
                continue

        _time.sleep(0.1)

        # Type newline (if not first tag) + # + tag name
        if idx > 0:
            page.keyboard.press("Enter")
        _time.sleep(hash_pause / 1000)
        page.keyboard.type("#")
        _time.sleep(hash_pause / 1000)

        for ch in normalized:
            page.keyboard.type(ch, delay=random.randint(char_delay_min, char_delay_max))

        _time.sleep(suggest_wait / 1000)
        page.keyboard.press("Enter")
        _time.sleep(_jitter_seconds(0.3, timing_jitter, 0.1))
        page.keyboard.type(" ")
        print(f"[playwright]   Tag added: #{normalized}")


if __name__ == "__main__":
    main()
