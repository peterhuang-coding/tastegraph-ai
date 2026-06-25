"""小红书 (Xiaohongshu) 自动发布器 — Playwright 浏览器自动化

独立模块，不依赖 taste_graph_ai 项目。可单独运行和调试。

首次使用：
    TASTEGRAPH_XHS_HEADFUL=1 python publisher.py — 打开浏览器扫码登录，保存 cookie

后续使用：
    python publisher.py — 直接用已保存的 cookie headless 发布
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from .config import (
    XHS_COOKIES_FILE, XHS_CREATOR_URL, XHS_HEADLESS,
    PAGE_TIMEOUT, LOGIN_TIMEOUT, POST_PUBLISH_WAIT,
)


class PublishError(Exception):
    """发布失败"""
    pass


# CSS 选择器 —— 小红书更新 UI 时需要同步更新这里
# 最后更新: 2026-06-01, 适配新版创作者平台 (creator.xiaohongshu.com/publish/publish)
SELECTORS = {
    "login_qr": ".qrcode-img, .login-qr-code, [class*=qr], canvas.qrcode, img[class*=qrcode]",
    "new_post_btn": 'a[href*="publish/publish"], div:has-text("发布笔记"), button:has-text("发布笔记"), a:has-text("发布笔记"), [class*=publish-btn]',
    "upload_input": 'input[type="file"]',
    "upload_done": '[class*=preview], [class*=thumbnail], [class*=cover], img[class*=upload]',
    "title_input": 'input[placeholder*="标题"], input.d-text[type="text"]',
    "body_editor": '.tiptap.ProseMirror, [contenteditable="true"]',
    "publish_btn": 'xhs-publish-btn[is-publish="true"], xhs-publish-btn, div.btn-wrapper:has-text("发布笔记"), button:has-text("发布"), span.btn-text:has-text("发布笔记"), [class*=submit]',
    "success_marker": '[class*=success], .publish-success, .toast-success, :has-text("发布成功")',
}

# 新版小红书创作者平台发布页 URL
XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"


class XiaohongshuPublisher:
    """小红书创作者平台自动发布器"""

    def __init__(self, cookies_path: Path | None = None):
        self.cookies_path = cookies_path or XHS_COOKIES_FILE
        self.browser = None
        self.context = None
        self.page = None
        self._pw = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        # Proxy for China access (Clash/V2Ray on 127.0.0.1:7890)
        import os
        proxy_server = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
        launch_args = ["--no-sandbox", "--disable-setuid-sandbox"]
        if proxy_server:
            launch_args.append(f"--proxy-server={proxy_server}")

        self.browser = await self._pw.chromium.launch(
            headless=XHS_HEADLESS,
            args=launch_args,
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
                print("[XHS] Cookie 加载失败，将重新登录")

        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    # ═══════════ 登录 ═══════════

    async def login(self) -> None:
        """打开浏览器扫码登录，保存 cookie 供后续使用"""
        print("[XHS] 打开浏览器，请扫码登录...")
        print(f"[XHS] 超时时间: {LOGIN_TIMEOUT // 1000} 秒")
        await self.page.goto(f"{XHS_CREATOR_URL}/login", wait_until="networkidle")
        await asyncio.sleep(2)

        start = time.time()
        while time.time() - start < LOGIN_TIMEOUT / 1000:
            url = self.page.url
            if "login" not in url and "sign" not in url.lower():
                break
            await asyncio.sleep(2)
        else:
            raise PublishError("登录超时（3分钟），请重试")

        cookies = await self.context.cookies()
        self.cookies_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        print(f"[XHS] 登录成功，Cookie 已保存到 {self.cookies_path}")

    # ═══════════ 发布 ═══════════

    async def publish(self, image_path: str, title: str, caption: str) -> str:
        """上传一张 moodboard 图片并发布，返回帖子 URL

        流程：自动上传图片 + 填写标题正文 + 自动点击「发布」按钮，
        检测发布成功后返回帖子链接。
        """
        await self._ensure_logged_in()
        page = self.page

        # ═══════════ Step 1: 进入发布页面 ═══════════
        print(f"[XHS] 正在打开发布页面: {XHS_PUBLISH_URL}")
        await page.goto(XHS_PUBLISH_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        if "publish/publish" not in page.url.lower():
            print("[XHS] 未直接进入发布页，尝试导航...")
            for sel in SELECTORS["new_post_btn"].split(", "):
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue

        # ═══════════ Step 2: 上传图片 ═══════════
        upload_ok = False
        for sel in SELECTORS["upload_input"].split(", "):
            try:
                file_input = page.locator(sel).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(image_path)
                    upload_ok = True
                    print(f"[XHS] ✅ 图片已上传")
                    break
            except Exception as e:
                continue

        if not upload_ok:
            raise PublishError("找不到上传入口，小红书 UI 可能已变更。请更新 SELECTORS")

        await asyncio.sleep(5)

        # ═══════════ Step 3: 填写标题 ═══════════
        title_filled = False
        for sel in SELECTORS["title_input"].split(", "):
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.fill("")
                    await el.fill(title)
                    title_filled = True
                    print(f"[XHS] ✅ 标题已填写: {title}")
                    break
            except Exception:
                continue

        if not title_filled:
            print("[XHS] ⚠️  未能自动填写标题，请手动填写")

        # ═══════════ Step 4: 填写正文 ═══════════
        body_filled = False
        for sel in SELECTORS["body_editor"].split(", "):
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.type(caption, delay=10)
                    body_filled = True
                    print(f"[XHS] ✅ 正文已填写")
                    break
            except Exception:
                continue

        if not body_filled:
            print("[XHS] ⚠️  未能自动填写正文，请手动填写")

        await asyncio.sleep(1)

        # ═══════════ Step 5: 自动点击发布 ═══════════
        print("[XHS] 正在自动点击发布按钮...")
        await self._click_publish_button()

        post_url = await self._wait_for_publish_result()
        return post_url

    async def _click_publish_button(self) -> None:
        """自动触发新版 <xhs-publish-btn>。

        小红书新版发布按钮会忽略 Playwright/CDP 合成点击。headful 模式下
        优先用系统级鼠标点击按钮中心；若不可用，再尝试直接调用 Vue 组件上的
        publish/submit/click 类方法。
        """
        page = self.page
        btn = page.locator(SELECTORS["publish_btn"]).first

        try:
            await btn.wait_for(state="attached", timeout=PAGE_TIMEOUT)
            await btn.scroll_into_view_if_needed(timeout=PAGE_TIMEOUT)
            await page.wait_for_function(
                """
                () => {
                    const btn = document.querySelector('xhs-publish-btn[is-publish="true"], xhs-publish-btn');
                    return btn && btn.getAttribute('submit-disabled') !== 'true';
                }
                """,
                timeout=PAGE_TIMEOUT,
            )
        except Exception as exc:
            raise PublishError(f"找不到可用的发布按钮: {exc}") from exc

        if not XHS_HEADLESS and await self._native_click_publish_button():
            print("[XHS] ✅ 已通过系统级鼠标点击发布按钮")
            return

        if await self._trigger_vue_publish_handler():
            print("[XHS] ✅ 已通过 Vue 组件方法触发发布")
            return

        raise PublishError(
            "自动点击发布按钮失败。请设置 TASTEGRAPH_XHS_HEADFUL=1 后重试，"
            "并确认当前应用拥有 macOS「辅助功能」控制权限。"
        )

    async def _trigger_vue_publish_handler(self) -> bool:
        """尽力在页面内寻找并调用 Vue 组件树里的发布方法。"""
        try:
            return bool(await self.page.evaluate(
                """
                async () => {
                    const root = document.querySelector('xhs-publish-btn[is-publish="true"], xhs-publish-btn');
                    if (!root) return false;

                    const seen = new WeakSet();
                    const nameRE = /(publish|submit|release|send|post|click)/i;
                    const skipRE = /^(constructor|render|setup|mounted|created|before|after|watch|computed|validator)$/i;
                    const roots = [
                        root,
                        root.__vueParentComponent,
                        root.__vueParentComponent?.proxy,
                        root.__vueParentComponent?.ctx,
                        root.__vueParentComponent?.setupState,
                        root.__vueParentComponent?.exposed,
                        window.__vue_app__?._instance,
                    ].filter(Boolean);

                    function collectFunctions(obj, depth = 0, out = []) {
                        if (!obj || depth > 5) return out;
                        const type = typeof obj;
                        if ((type !== 'object' && type !== 'function') || seen.has(obj)) return out;
                        seen.add(obj);

                        for (const key of Reflect.ownKeys(obj)) {
                            if (typeof key !== 'string' || skipRE.test(key)) continue;
                            let value;
                            try { value = obj[key]; } catch (_) { continue; }
                            if (typeof value === 'function' && nameRE.test(key)) {
                                out.push({ owner: obj, name: key, fn: value });
                            } else if (value && typeof value === 'object') {
                                collectFunctions(value, depth + 1, out);
                            }
                        }

                        const proto = Object.getPrototypeOf(obj);
                        if (proto && proto !== Object.prototype) {
                            collectFunctions(proto, depth + 1, out);
                        }
                        return out;
                    }

                    const candidates = [];
                    for (const item of roots) collectFunctions(item, 0, candidates);

                    for (const { owner, name, fn } of candidates) {
                        try {
                            const event = new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                composed: true,
                                view: window,
                            });
                            const result = fn.call(owner, event);
                            if (result && typeof result.then === 'function') await result;
                            console.debug('[XHS] called Vue publish candidate:', name);
                            return true;
                        } catch (err) {
                            console.debug('[XHS] Vue publish candidate failed:', name, err);
                        }
                    }

                    return false;
                }
                """,
            ))
        except Exception:
            return False

    async def _native_click_publish_button(self) -> bool:
        """用系统鼠标事件点击按钮中心，绕过浏览器合成事件限制。"""
        if sys.platform != "darwin":
            return False

        try:
            point = await self.page.evaluate(
                """
                () => {
                    const btn = document.querySelector('xhs-publish-btn[is-publish="true"], xhs-publish-btn');
                    if (!btn) return null;
                    const rect = btn.getBoundingClientRect();
                    const borderX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
                    const chromeY = Math.max(0, window.outerHeight - window.innerHeight - borderX);
                    return {
                        x: Math.round(window.screenX + borderX + rect.left + rect.width / 2),
                        y: Math.round(window.screenY + chromeY + rect.top + rect.height / 2),
                    };
                }
                """,
            )
            if not point:
                return False

            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/osascript",
                "-e",
                'try',
                "-e",
                'tell application "Chromium" to activate',
                "-e",
                'end try',
                "-e",
                "delay 0.2",
                "-e",
                f'tell application "System Events" to click at {{{point["x"]}, {point["y"]}}}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = stderr.decode("utf-8", errors="ignore").strip()
                print(f"[XHS] 系统级点击失败: {msg}")
                return False

            await asyncio.sleep(0.5)
            return True
        except Exception as exc:
            print(f"[XHS] 系统级点击异常: {exc}")
            return False

    async def _wait_for_publish_result(self, timeout: int = 120) -> str:
        """点击发布后检测发布成功

        检测策略（任一命中即认为发布成功）：
        1. URL 跳转到笔记详情页（/explore/ 或 /discovery/ 等非 publish 路径）
        2. 页面出现「发布成功」或「笔记已发布」等成功文案
        3. 发布表单被清空（图片消失 + 标题清空，说明已发布并重置）
        4. URL 跳转到笔记管理页
        """
        page = self.page
        start = time.time()
        last_url = page.url

        while time.time() - start < timeout:
            current_url = page.url

            # 检测 1: URL 跳转到非 publish 页面
            if "publish/publish" not in current_url and "publish" not in current_url:
                print(f"\n[XHS] ✅ 检测到页面跳转: {current_url}")
                return current_url

            # 检测 2: 成功文案
            try:
                body = await page.evaluate("document.body.innerText")
                for marker in ["发布成功", "笔记已发布", "笔记发布成功", "已发布"]:
                    if marker in body:
                        print(f"\n[XHS] ✅ 检测到成功标记: \"{marker}\"")
                        await asyncio.sleep(2)
                        return page.url
            except Exception:
                pass

            # 检测 3: 表单被清空（图片上传区重新出现，标题清空）
            try:
                title_val = await page.locator('input[placeholder*="标题"]').first.input_value()
                if title_val == "" and last_url == current_url:
                    # 标题被清空了，可能是发布后表单重置
                    # 再等 2 秒确认
                    await asyncio.sleep(2)
                    title_val2 = await page.locator('input[placeholder*="标题"]').first.input_value()
                    if title_val2 == "" and "publish/publish" not in page.url:
                        print(f"\n[XHS] ✅ 检测到表单已清空（发布后重置）")
                        return page.url
            except Exception:
                pass

            # 检测 4: 发布按钮消失
            try:
                btn_count = await page.locator("xhs-publish-btn").count()
                if btn_count == 0:
                    # 按钮消失，可能已跳转
                    await asyncio.sleep(1)
                    if "publish/publish" not in page.url:
                        print(f"\n[XHS] ✅ 检测到发布按钮消失，已跳转")
                        return page.url
            except Exception:
                pass

            await asyncio.sleep(1.5)

        # 超时 — 尝试从当前 URL 推断
        final_url = page.url
        if "publish/publish" not in final_url:
            return final_url

        raise PublishError(
            f"等待发布结果超时（{timeout}秒）。如果已发布成功，请从浏览器地址栏复制帖子链接"
        )

    async def _ensure_logged_in(self) -> None:
        await self.page.goto(XHS_CREATOR_URL, wait_until="networkidle")
        await asyncio.sleep(1)
        if any(kw in self.page.url.lower() for kw in ("login", "sign", "auth")):
            print("[XHS] 登录态已过期，需要重新登录")
            await self.login()


# ═══════════ 便捷函数 ═══════════

async def publish_one(image_path: str, title: str, caption: str) -> str:
    """一行代码发布到小红书"""
    async with XiaohongshuPublisher() as pub:
        return await pub.publish(image_path, title, caption)
