import json
from typing import Optional

import httpx

from taste_graph_ai.config import CLAUDE_API_KEY, CLAUDE_MODEL


class ClaudeClient:
    """Minimal Claude API client for content evaluation and generation.

    Uses direct httpx calls to avoid anthropic SDK dependency for v1.
    The SDK can be swapped in later.
    """

    BASE = "https://api.anthropic.com/v1"

    def __init__(self, api_key: str = CLAUDE_API_KEY, model: str = CLAUDE_MODEL):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=60,
        ) if api_key else None

    async def evaluate_source(self, url: str, name: str, description: str = "") -> dict:
        """Quick evaluation of a new content source against taste profile.

        Returns {"score": 0-1, "reason": "...", "risk": "..."}
        """
        if not self.client:
            return {"score": 0.5, "reason": "Claude not configured", "risk": ""}

        prompt = f"""You are evaluating a potential content source for a taste-driven moodboard account.

The account aesthetic: quiet, editorial, low-saturation, city-walking, film-grain, brutalist, archive-feeling.
Avoid: cute, influencer, luxury-logo, neon, stock-photo, template, vibrant.

Source:
  Name: {name}
  URL: {url}
  Description: {description or 'N/A'}

Evaluate if this source's content style fits the account. Return ONLY valid JSON:
{{"score": 0.0-1.0, "reason": "1 sentence why it fits or not", "risk": "any risk keyword or empty string"}}"""

        try:
            r = await self.client.post("/messages", json={
                "model": self.model,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            })
            if r.status_code == 200:
                data = r.json()
                text = data.get("content", [{}])[0].get("text", "{}")
                return json.loads(text)
        except Exception:
            pass

        return {"score": 0.5, "reason": "Evaluation failed", "risk": ""}

    async def generate_theme(self, keywords: list[str], recent_themes: list[str] = None) -> dict:
        """Generate a daily moodboard theme.

        Returns {"theme": "...", "why_today": "...", "title_options": [...], "caption": "..."}
        """
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

        try:
            r = await self.client.post("/messages", json={
                "model": self.model,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            })
            if r.status_code == 200:
                data = r.json()
                text = data.get("content", [{}])[0].get("text", "{}")
                return json.loads(text)
        except Exception:
            pass

        return {"theme": keywords[0] if keywords else "今日灵感", "why_today": "", "title_options": [], "caption": ""}

    async def evaluate_image(self, image_description: str, keywords: list[str]) -> dict:
        """Evaluate whether an image fits the taste profile.

        Returns {"score": 0-1, "reason": "...", "suggested_keywords": [...]}
        """
        if not self.client:
            return {"score": 0.5, "reason": "Claude not configured", "suggested_keywords": keywords}

        prompt = f"""Evaluate whether this image fits a taste-driven moodboard account.

Account aesthetic: quiet, editorial, low-saturation, city-walking, film-grain, brutalist.
Avoid: cute, influencer, luxury-logo, neon, stock-photo, vibrant.

Image description: {image_description}
Matched keywords: {', '.join(keywords)}

Return ONLY valid JSON:
{{"score": 0.0-1.0, "reason": "1 sentence", "suggested_keywords": ["kw1", "kw2"]}}"""

        try:
            r = await self.client.post("/messages", json={
                "model": self.model,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            })
            if r.status_code == 200:
                data = r.json()
                text = data.get("content", [{}])[0].get("text", "{}")
                return json.loads(text)
        except Exception:
            pass

        return {"score": 0.5, "reason": "Evaluation failed", "suggested_keywords": keywords}

    async def close(self):
        if self.client:
            await self.client.aclose()
