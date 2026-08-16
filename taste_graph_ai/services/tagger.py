"""AI 自动风格标签服务 — L1。

给抽检图片批量打风格标签 + 推荐度评分。
- 用 AIClient 调 Vision LLM 生成 tags / style_label / why
- 用 CLIPService 做 embedding 余弦相似度作为 ranking 信号
- 返回 list[dict] 与前端 chip/badge 风格对齐

参考:
  - services/feedback.py:196-224 的 prompt 风格
  - services/clip.py:CLIPService.embed_image / embed_text
  - domain/enums.py:FeedbackLabel (用 .value 当中文标签候选)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from taste_graph_ai.domain.enums import FeedbackLabel


# ── 视觉词表 (L3 同源) ───────────────────────────────────────────
# 给 LLM 当锚点用,确保 it hits at least one concrete visual word.
VISUAL_VOCAB = {
    "color":    ["灰", "白", "黑", "米", "冷调", "暖调", "低饱和", "莫兰迪"],
    "material": ["水泥", "羊毛", "棉", "亚麻", "金属", "玻璃", "木", "哑光"],
    "layout":   ["留白", "居中", "三分", "对称", "边缘切割"],
    "light":    ["阴天", "室内自然光", "侧光", "逆光", "暗调"],
    "ratio":    ["瘦长", "方正", "微小", "夸张"],
    "type":     ["无衬线", "西文", "标点节制", "对齐"],
}

# LLM 可以自由组合的 style_label 取值(2-6 字)
STYLE_LABEL_POOL = [
    "隐藏 NY", "极简街头", "复古运动", "建筑感", "工业废墟",
    "街头档案", "包豪斯", "北欧冷感", "水泥都市", "日杂风",
    "mood 电影", "lowkey", "editorial", "urban archive",
]


def _feedback_label_values() -> list[str]:
    """FeedbackLabel enum 的中文 values,给 LLM 当候选标签池。"""
    return [lbl.value for lbl in FeedbackLabel]


class ImageTaggerService:
    """给一组图片批量打风格标签。

    设计要点:
      - 单图 Vision LLM 调用:tags / style_label / why
      - CLIP 余弦相似度作为 score 的视觉侧锚定
      - 失败安全:任何一步崩了都返回 fallback,不让前端拿到 500
    """

    def __init__(self, ai_client=None, clip_service=None):
        # 延迟导入避免循环依赖 / 启动期拉模型
        self._ai = ai_client
        self._clip = clip_service

    async def tag_spotcheck(
        self,
        image_paths: list[str],
        theme_hint: str = "",
    ) -> list[dict]:
        """对每张图打风格标签 + 推荐度。

        Args:
          image_paths: 绝对路径或 /images/xxx 相对路径都行(会自动归一化)
          theme_hint:  主题上下文(如 "Hidden NY 都市感")用于 LLM prompt

        Returns:
          list[dict],顺序与输入一致,每项:
            {
              "image_path": str,
              "tags":       [str],       # 3-5 个,含 FeedbackLabel + 自由风格
              "style_label":str,         # 2-6 字,例 "隐藏 NY" / "极简街头"
              "score":      float,       # 0-1,推荐度(CLIP 锚定 + AI 加权)
              "why":        str,         # ≤30 字中文,必中具体视觉词
            }
        """
        if not image_paths:
            return []

        # 并发处理每张图(各自独立 Vision 调用)
        results = await asyncio.gather(
            *[self._tag_one(p, theme_hint) for p in image_paths],
            return_exceptions=True,
        )

        out = []
        for p, r in zip(image_paths, results):
            if isinstance(r, Exception):
                out.append(self._fallback(p))
            else:
                out.append(r)
        return out

    # ── 单图处理 ────────────────────────────────────────────────

    async def _tag_one(self, image_path: str, theme_hint: str) -> dict:
        path_obj = Path(image_path)
        if not path_obj.exists():
            # 路径不对也要回个 fallback,前端 grid 才不会空
            return self._fallback(image_path)

        # 1. CLIP 相似度锚定(给一个 0-1 的 baseline)
        clip_score = await asyncio.to_thread(self._clip_score, path_obj, theme_hint)

        # 2. Vision LLM 生成 tags / style_label / why
        llm_payload = await self._llm_tag(path_obj, theme_hint)

        # 3. 融合 score(CLIP 70% + AI 30%)— LLM 没给 score 就退回 CLIP
        ai_score = llm_payload.get("score")
        if isinstance(ai_score, (int, float)):
            score = round(max(0.0, min(1.0, clip_score * 0.7 + float(ai_score) * 0.3)), 3)
        else:
            score = round(clip_score, 3)

        # 4. 清洗 tags:去重 + 限长
        tags = self._clean_tags(llm_payload.get("tags") or [])

        return {
            "image_path": str(path_obj),
            "tags": tags,
            "style_label": (llm_payload.get("style_label") or "未分类")[:8],
            "score": score,
            "why": self._clean_why(llm_payload.get("why") or ""),
        }

    def _clip_score(self, path_obj: Path, theme_hint: str) -> float:
        """CLIP 余弦相似度:图 vs 主题文本(无主题就 vs 一个中性 anchor)。"""
        try:
            clip = self._get_clip()
            anchor = theme_hint.strip() or "quiet editorial moodboard, low saturation, urban archive"
            return float(clip.compute_similarity(path_obj, anchor))
        except Exception:
            return 0.5  # CLIP 不可用时的中性 fallback

    async def _llm_tag(self, path_obj: Path, theme_hint: str) -> dict:
        """调 Vision LLM 出 tags / style_label / why / score。"""
        try:
            ai = self._get_ai()
            prompt = self._build_prompt(theme_hint)
            # Vision:把图片 base64 进 prompt(MVP:用 text-only prompt + 文件名/尺寸提示)
            # 真正的 Vision upload 留给后面 MCP 联调再做,先把 text 通道跑通
            hint = (
                f"Image file: {path_obj.name}\n"
                f"Size: {self._file_size_kb(path_obj)} KB\n"
                f"Theme hint: {theme_hint or 'auto-detect'}"
            )
            full = f"{prompt}\n\n{hint}"
            result = await ai.chat_json(full, max_tokens=350)
            await ai.close()
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    # ── Prompt 构建 ─────────────────────────────────────────────

    def _build_prompt(self, theme_hint: str) -> str:
        labels = "、".join(_feedback_label_values())
        style_pool = "、".join(STYLE_LABEL_POOL)
        vocab_lines = []
        for cat, words in VISUAL_VOCAB.items():
            vocab_lines.append(f"  {cat}: {'/'.join(words)}")
        vocab_block = "\n".join(vocab_lines)

        return f"""你是 moodboard. 账号的视觉策展人,给一张图打风格标签。

账号调性:quiet, editorial, low-saturation, Hidden NY / JJJJound 风格。
主题上下文:{theme_hint or 'auto-detect'}

候选 FeedbackLabel 标签池(从中挑 3-5 个最相关的):
{labels}

允许的 style_label(2-6 字,也可以从下面自由组合):
{style_pool}

允许的视觉词表(why 必命中至少 1 个,不能只说"feels right"):
{vocab_block}

Hard rules:
- 不准说 "feels right"、"很对味"、"不错"、"good"
- why 一句话,中文 ≤30 字,必中至少 1 个具体视觉词(颜色/材质/构图/光线/比例/排版)
- tags 3-5 个,优先从 FeedbackLabel 池挑,允许少量自由词
- style_label 2-6 字
- style_label 保持 Hidden NY / JJJJound 调性,不要"可爱/萌/酷炫/网红/绝美/高级感"类词
- score 0-1(0.85+ 是绝对对味,< 0.4 是弃)
- 只返回 JSON,不要 markdown:
{{"tags":["标签1","标签2"],"style_label":"隐藏 NY","score":0.82,"why":"灰色水泥质感配侧光,留白比例克制"}}
"""

    # ── 清洗 ────────────────────────────────────────────────────

    @staticmethod
    def _clean_tags(raw) -> list[str]:
        if not isinstance(raw, list):
            return []
        seen = []
        for t in raw:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.append(t)
            if len(seen) >= 5:
                break
        return seen

    @staticmethod
    def _clean_why(text: str) -> str:
        if not isinstance(text, str):
            return ""
        text = text.strip()
        # L3 同源:hard 拦截"feels right"类空话
        empty_phrases = ["feels right", "很对味", "不错", "good", "ok", "可以"]
        for ph in empty_phrases:
            if text.lower() == ph or text.lower().startswith(ph + "，") or text.lower().startswith(ph + ","):
                return ""
        return text[:40]

    @staticmethod
    def _file_size_kb(p: Path) -> int:
        try:
            return round(p.stat().st_size / 1024)
        except Exception:
            return 0

    # ── Fallback ─────────────────────────────────────────────────

    def _fallback(self, image_path: str) -> dict:
        return {
            "image_path": image_path,
            "tags": [],
            "style_label": "未分类",
            "score": 0.5,
            "why": "",
        }

    # ── 依赖注入(单例,延迟)─────────────────────────────────────

    def _get_ai(self):
        if self._ai is None:
            from taste_graph_ai.infrastructure.ai.client import AIClient
            self._ai = AIClient()
        return self._ai

    def _get_clip(self):
        if self._clip is None:
            from taste_graph_ai.services.clip import get_clip
            self._clip = get_clip()
        return self._clip
