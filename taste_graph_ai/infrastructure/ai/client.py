import json
import os
from typing import Optional

import httpx

# ── Provider configs ──────────────────────────────────────────

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

CLAUDE_BASE = "https://api.anthropic.com/v1"
CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


class AIClient:
    """Unified AI client. Prefers DeepSeek if key present, falls back to Claude."""

    def __init__(self):
        self.provider: Optional[str] = None
        self.client: Optional[httpx.AsyncClient] = None
        self.model: str = ""

        if DEEPSEEK_KEY:
            self.provider = "deepseek"
            self.model = DEEPSEEK_MODEL
            self.client = httpx.AsyncClient(
                base_url=DEEPSEEK_BASE,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
        elif CLAUDE_KEY:
            self.provider = "claude"
            self.model = CLAUDE_MODEL
            self.client = httpx.AsyncClient(
                base_url=CLAUDE_BASE,
                headers={
                    "x-api-key": CLAUDE_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )

    # ── Public API ─────────────────────────────────────────────

    async def chat(self, prompt: str, max_tokens: int = 500) -> str:
        """Send a prompt, return text response."""
        if not self.client:
            return ""
        try:
            if self.provider == "deepseek":
                return await self._deepseek_chat(prompt, max_tokens)
            elif self.provider == "claude":
                return await self._claude_chat(prompt, max_tokens)
        except Exception:
            pass
        return ""

    async def chat_json(self, prompt: str, max_tokens: int = 500) -> dict:
        """Send a prompt, parse response as JSON."""
        text = await self.chat(prompt, max_tokens)
        if not text:
            return {}
        # Strip markdown code fences
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    async def evaluate_source(self, url: str, name: str, description: str = "") -> dict:
        if not self.client:
            return {"score": 0.5, "reason": "AI not configured", "risk": ""}

        prompt = f"""You are evaluating a potential content source for a taste-driven moodboard account.

The account aesthetic: quiet, editorial, low-saturation, city-walking, film-grain, brutalist, archive-feeling.
Avoid: cute, influencer, luxury-logo, neon, stock-photo, template, vibrant.

Source:
  Name: {name}
  URL: {url}
  Description: {description or 'N/A'}

Evaluate if this source's content style fits the account. Return ONLY valid JSON:
{{"score": 0.0-1.0, "reason": "1 sentence why it fits or not", "risk": "any risk keyword or empty string"}}"""
        return await self.chat_json(prompt, 200)

    async def generate_theme(self, keywords: list[str], recent_themes: list[str] = None) -> dict:
        if not self.client:
            return {"theme": "未配置 AI", "why_today": "", "title_options": [], "caption": ""}

        recent_str = ", ".join(recent_themes[:5]) if recent_themes else "暂无"
        prompt = f"""你是一个品味驱动的 moodboard 账号的内容策划师。

账号调性：冷静、克制、都市、低饱和、Hidden NY / JJJJound 风格。
近期已发布主题：{recent_str}
今日相关关键词：{', '.join(keywords[:8])}

请生成今日 moodboard 方案。返回纯 JSON（不要 markdown）：
{{
  "theme": "中文主题（10字以内）",
  "why_today": "为什么今天适合这个主题（一句话）",
  "title_options": ["标题方案1", "标题方案2", "标题方案3"],
  "caption": "小红书正文草稿（100-150字，语气冷静、不营销、像私藏笔记）"
}}"""
        return await self.chat_json(prompt, 500)

    async def extract_entities(self, page_title: str, page_description: str, alt_texts: list[str]) -> dict:
        """Extract structured taste entities from page metadata for graph enrichment."""
        if not self.client:
            return {"brands": [], "designers": [], "colors": [], "materials": [], "moods": [], "objects": [], "locations": []}

        alt_sample = "; ".join(alt_texts[:10]) if alt_texts else "N/A"
        prompt = f"""Extract taste-relevant entities from this fashion/design page metadata.
Account aesthetic: quiet, editorial, low-saturation, city-walking, archive, brutalist.

Page title: {page_title[:200]}
Page description: {page_description[:300]}
Image alt texts: {alt_sample[:300]}

Return ONLY valid JSON (no markdown):
{{"brands": ["brand name"], "designers": ["full name"], "colors": ["descriptive color"], "materials": ["fabric or texture"], "moods": ["atmosphere keyword"], "objects": ["physical object"], "locations": ["city or place"]}}
Only include items you're confident about. Empty lists for missing categories. Max 3 items per list. Keep each item short (1-4 words)."""
        return await self.chat_json(prompt, 500)

    async def evaluate_image(self, image_description: str, keywords: list[str]) -> dict:
        if not self.client:
            return {"score": 0.5, "reason": "AI not configured", "suggested_keywords": keywords}

        prompt = f"""Evaluate whether this image fits a taste-driven moodboard account.

Account aesthetic: quiet, editorial, low-saturation, city-walking, film-grain, brutalist.
Avoid: cute, influencer, luxury-logo, neon, stock-photo, vibrant.

Image description: {image_description}
Matched keywords: {', '.join(keywords)}

Return ONLY valid JSON:
{{"score": 0.0-1.0, "reason": "1 sentence", "suggested_keywords": ["kw1", "kw2"]}}"""
        return await self.chat_json(prompt, 200)

    # ── Provider-specific ─────────────────────────────────────

    async def _deepseek_chat(self, prompt: str, max_tokens: int) -> str:
        r = await self.client.post("/chat/completions", json={
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        })
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        return ""

    async def _claude_chat(self, prompt: str, max_tokens: int) -> str:
        r = await self.client.post("/messages", json={
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        })
        if r.status_code == 200:
            data = r.json()
            return data.get("content", [{}])[0].get("text", "")
        return ""

    async def close(self):
        if self.client:
            await self.client.aclose()
