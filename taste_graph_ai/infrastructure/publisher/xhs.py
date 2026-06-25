"""Xiaohongshu (小红书) publisher via Playwright browser automation.

First run opens a browser for QR-code login and saves cookies.
Subsequent runs reuse cookies in headless mode.
"""

import asyncio
import json
import time
from pathlib import Path

from taste_graph_ai.config import XHS_COOKIES_FILE, XHS_CREATOR_URL, XHS_HEADLESS


class PublishError(Exception):
    """Raised when automatic publishing fails."""
    pass


# CSS selectors for Xiaohongshu Creator Studio UI.
# These WILL change when Xiaohongshu updates their UI — update here.
SELECTORS = {
    # Login page
    "login_qr": ".qrcode-img, .login-qr-code, [class*=qr], canvas.qrcode",
    # After login — "new post" buttons
    "new_post_btn": 'a[href*="creator/publish"], button:has-text("发布笔记"), a:has-text("发布笔记"), [class*=publish-btn], .publishBtn',
    # Upload area
    "upload_input": 'input[type="file"], input[accept*="image"], [class*=upload] input[type=file]',
    "upload_done": '[class*=uploaded], [class*=preview], .img-preview, [class*=thumbnail]',
    # Title
    "title_input": '[placeholder*="标题"], input.title, [class*=title] input, .note-title input, #title',
    # Body / caption (contenteditable div)
    "body_editor": '[placeholder*="正文"], [contenteditable="true"], .note-content, .ql-editor, #content',
    # Publish button
    "publish_btn": 'button:has-text("发布"), [class*=publish]:not([class*=publish-btn]):not(a), .submit-btn, button:has-text("确定")',
    # Success indicator
    "success_marker": '[class*=success], .publish-success, .toast-success, :has-text("发布成功")',
}

PAGE_TIMEOUT = 30_000  # 30 seconds per wait
LOGIN_TIMEOUT = 180_000  # 3 minutes for QR scan
POST_PUBLISH_WAIT = 5_000  # wait for success redirect


class XiaohongshuPublisher:
    """Automated Xiaohongshu Creator Studio publisher using Playwright."""

    def __init__(self, cookies_path: Path | None = None):
        self.cookies_path = cookies_path or XHS_COOKIES_FILE
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=XHS_HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        if self.cookies_path.exists():
            try:
                cookies = json.loads(self.cookies_path.read_text())
                await self.context.add_cookies(cookies)
            except Exception:
                pass
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Login ─────────────────────────────────────────────────

    async def login(self) -> None:
        """Open browser for QR-code login. Blocks until user completes."""
        if self.browser and not XHS_HEADLESS:
            # Re-create in headful mode
            pass

        print("[XHS] Opening browser for login. Scan the QR code...")
        await self.page.goto(f"{XHS_CREATOR_URL}/login", wait_until="networkidle")
        await asyncio.sleep(2)

        # Wait for user to complete login
        start = time.time()
        while time.time() - start < LOGIN_TIMEOUT / 1000:
            url = self.page.url
            if "login" not in url and "sign" not in url.lower():
                break
            await asyncio.sleep(2)
        else:
            raise PublishError("登录超时（3分钟），请重试")

        # Save cookies
        cookies = await self.context.cookies()
        self.cookies_path.write_text(json.dumps(cookies, ensure_ascii=False))
        print(f"[XHS] Login successful, cookies saved to {self.cookies_path}")

    async def _ensure_logged_in(self) -> None:
        """Check login state. If not logged in, run interactive login."""
        await self.page.goto(XHS_CREATOR_URL, wait_until="networkidle")
        await asyncio.sleep(1)

        # Check if we're on a login page
        if any(kw in self.page.url.lower() for kw in ("login", "sign", "auth")):
            print("[XHS] Session expired, need to re-login.")
            await self.login()

    # ── Publish ───────────────────────────────────────────────

    async def publish(self, image_path: str, title: str, caption: str) -> str:
        """Upload a moodboard image and publish it. Returns the post URL."""
        await self._ensure_logged_in()

        page = self.page

        # Navigate to publish page
        await page.goto(f"{XHS_CREATOR_URL}/creator/publish", wait_until="networkidle")
        await asyncio.sleep(1)

        # If publish page didn't load, try clicking the "new post" button
        if "publish" not in page.url.lower():
            for sel in SELECTORS["new_post_btn"].split(", "):
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        break
                except Exception:
                    continue

        # Upload image
        upload_triggered = False
        for sel in SELECTORS["upload_input"].split(", "):
            try:
                file_input = page.locator(sel).first
                await file_input.set_input_files(image_path)
                upload_triggered = True
                break
            except Exception:
                continue

        if not upload_triggered:
            raise PublishError("找不到上传入口，小红书 UI 可能已变更")

        # Wait for upload to finish
        await asyncio.sleep(3)
        try:
            for sel in SELECTORS["upload_done"].split(", "):
                await page.wait_for_selector(sel, timeout=PAGE_TIMEOUT)
                break
        except Exception:
            pass  # Proceed anyway

        # Fill title
        await asyncio.sleep(1)
        for sel in SELECTORS["title_input"].split(", "):
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await el.fill(title)
                    break
            except Exception:
                continue

        # Fill body
        for sel in SELECTORS["body_editor"].split(", "):
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await el.fill(caption)
                    break
            except Exception:
                continue

        await asyncio.sleep(1)

        # Click publish
        published = False
        for sel in SELECTORS["publish_btn"].split(", "):
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    published = True
                    break
            except Exception:
                continue

        if not published:
            raise PublishError("找不到发布按钮，小红书 UI 可能已变更")

        # Wait for success
        await asyncio.sleep(POST_PUBLISH_WAIT / 1000)

        # Try to capture the post URL
        post_url = page.url
        await asyncio.sleep(2)

        return post_url or ""
