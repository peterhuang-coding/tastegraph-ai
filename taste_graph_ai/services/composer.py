"""Moodboard compositor — stitches images into a Xiaohongshu-ready 3x3 grid + caption."""

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from taste_graph_ai.config import EXPORTS_DIR

# Output canvas: 1080x1350 (optimal Xiaohongshu portrait ratio)
CANVAS_W = 1080
CANVAS_H = 1350
GRID_COLS = 3
GRID_ROWS = 3
CELL_SIZE = 360  # 1080 / 3
TEXT_AREA_H = 270  # bottom caption area
FONT_TITLE_SIZE = 20
FONT_CAPTION_SIZE = 28
GRID_BORDER = 1  # subtle gap between cells

_FONT_PATHS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


def _find_cjk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in _FONT_PATHS:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


class MoodboardComposer:
    """Composes a 3x3 moodboard grid with captions, Hidden NY / JJJJound aesthetic."""

    def compose(
        self,
        image_paths: list[str],
        theme: str = "",
        caption: str = "",
        title: str = "",
    ) -> Path:
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), color=(255, 255, 255))

        self._paste_grid(canvas, image_paths)
        self._render_text(canvas, title or theme, caption)

        filename = f"moodboard_{int(time.time())}.png"
        output_path = EXPORTS_DIR / filename
        canvas.save(output_path, "PNG", optimize=True)
        return output_path

    def _paste_grid(self, canvas: Image.Image, image_paths: list[str]) -> None:
        for idx, path in enumerate(image_paths[:GRID_COLS * GRID_ROWS]):
            try:
                img = Image.open(path).convert("RGB")
            except Exception:
                continue
            cropped = self._crop_center_square(img)
            cropped = cropped.resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)

            col = idx % GRID_COLS
            row = idx // GRID_COLS
            x = col * CELL_SIZE
            y = row * CELL_SIZE

            if GRID_BORDER > 0:
                x += GRID_BORDER
                y += GRID_BORDER
                cropped = cropped.resize(
                    (CELL_SIZE - GRID_BORDER * 2, CELL_SIZE - GRID_BORDER * 2),
                    Image.LANCZOS,
                )

            canvas.paste(cropped, (x, y))

    def _render_text(self, canvas: Image.Image, title: str, caption: str) -> None:
        draw = ImageDraw.Draw(canvas)
        text_y = CANVAS_H - TEXT_AREA_H + 30

        # Title
        if title:
            font_title = _find_cjk_font(FONT_TITLE_SIZE)
            draw.text((60, text_y), title, fill=(120, 120, 120), font=font_title)
            text_y += FONT_TITLE_SIZE + 24

        # Caption (with word-wrap)
        if caption:
            font_cap = _find_cjk_font(FONT_CAPTION_SIZE)
            lines = self._wrap_text(caption, font_cap, CANVAS_W - 120)
            for line in lines:
                if text_y > CANVAS_H - 30:
                    break
                draw.text((60, text_y), line, fill=(50, 50, 50), font=font_cap)
                text_y += FONT_CAPTION_SIZE + 10

    @staticmethod
    def _crop_center_square(img: Image.Image) -> Image.Image:
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return img.crop((left, top, left + side, top + side))

    @staticmethod
    def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
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
