"""Moodboard 单图导出器 — 每张图独立排版，各自带标题/正文

独立模块。输入: 图片路径 + 标题 + 文案
输出: 小红书比例的单图（1080×1350），图在上方，文字在底部
"""

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import (
    CANVAS_W, CANVAS_H, EXPORTS_DIR,
)


def _find_cjk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from .config import _FONT_PATHS as font_paths
    for fp in font_paths:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


class SingleComposer:
    """单图排版 — 一张图 + 底部标题 + 正文"""

    # Layout: image is CROPPED to fill top area, text goes below
    IMAGE_AREA_H = 1080       # square image area (matching canvas width)
    TEXT_AREA_H = 270         # bottom text area
    PADDING = 60              # left/right padding for text

    def compose(
        self,
        image_path: str,
        title: str = "",
        caption: str = "",
    ) -> Path:
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), color=(255, 255, 255))

        # Paste and crop the image to fill top area
        try:
            img = Image.open(image_path).convert("RGB")
            # Smart crop: fit into IMAGE_AREA_H while preserving aspect ratio
            w, h = img.size
            target_ratio = CANVAS_W / self.IMAGE_AREA_H
            img_ratio = w / h

            if img_ratio > target_ratio:
                # Image is wider — crop sides
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            else:
                # Image is taller — crop top/bottom
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))

            img = img.resize((CANVAS_W, self.IMAGE_AREA_H), Image.LANCZOS)
            canvas.paste(img, (0, 0))
        except Exception:
            pass  # Image failed to load — leave area blank

        # Render text below image
        self._render_text(canvas, title, caption)

        filename = f"single_{int(time.time())}.png"
        output_path = EXPORTS_DIR / filename
        canvas.save(output_path, "PNG", optimize=True)
        return output_path

    def _render_text(self, canvas: Image.Image, title: str, caption: str) -> None:
        draw = ImageDraw.Draw(canvas)
        y = self.IMAGE_AREA_H + 30

        if title:
            font_title = _find_cjk_font(22)
            draw.text((self.PADDING, y), title, fill=(80, 80, 80), font=font_title)
            y += 32

        if caption:
            font_cap = _find_cjk_font(26)
            lines = self._wrap_text(caption, font_cap, CANVAS_W - self.PADDING * 2)
            for line in lines:
                if y > CANVAS_H - 30:
                    break
                draw.text((self.PADDING, y), line, fill=(40, 40, 40), font=font_cap)
                y += 34

    @staticmethod
    def _wrap_text(text: str, font, max_width: int) -> list[str]:
        lines = []
        line_chars = []
        for ch in text:
            line_chars.append(ch)
            bbox = font.getbbox("".join(line_chars))
            if bbox[2] > max_width:
                if len(line_chars) > 1:
                    line_chars.pop()
                lines.append("".join(line_chars))
                line_chars = [ch]
        if line_chars:
            lines.append("".join(line_chars))
        return lines

    @staticmethod
    def batch_export(
        image_paths: list[str],
        title_template: str = "",
        captions: list[str] = None,
    ) -> list[Path]:
        """Export multiple images as individual cards. Returns list of output paths."""
        composer = SingleComposer()
        outputs = []
        for i, path in enumerate(image_paths):
            cap = captions[i] if captions and i < len(captions) else ""
            title = title_template if title_template else ""
            out = composer.compose(path, title=title, caption=cap)
            outputs.append(out)
        return outputs
