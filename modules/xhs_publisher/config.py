"""小红书发布模块 - 独立配置

所有配置项都有合理默认值，可通过环境变量覆盖。
另一个 AI 只需改这里的值就能适配不同环境。
"""

import os
from pathlib import Path

# 工作目录 - 模块所在目录
ROOT = Path(__file__).resolve().parent

# Cookie 文件（登录一次后自动保存，后续免登录）
XHS_COOKIES_FILE = Path(os.environ.get("XHS_COOKIES_FILE", ROOT / "cookies.json"))

# 小红书创作者平台地址
XHS_CREATOR_URL = os.environ.get("XHS_CREATOR_URL", "https://creator.xiaohongshu.com")

# Headless 模式：默认 True（无界面运行）
# 首次登录需要设置 TASTEGRAPH_XHS_HEADFUL=1 打开浏览器扫码
XHS_HEADLESS = not bool(os.environ.get("TASTEGRAPH_XHS_HEADFUL"))

# 导出目录
EXPORTS_DIR = Path(os.environ.get("XHS_EXPORTS_DIR", ROOT / "exports"))
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 页面超时（毫秒）
PAGE_TIMEOUT = 30_000
LOGIN_TIMEOUT = 180_000  # 扫码等待 3 分钟
POST_PUBLISH_WAIT = 5_000

# 画布尺寸（小红书竖版最优比例）
CANVAS_W = 1080
CANVAS_H = 1350
GRID_COLS = 3
GRID_ROWS = 3
CELL_SIZE = 360
TEXT_AREA_H = 270
FONT_TITLE_SIZE = 20
FONT_CAPTION_SIZE = 28
GRID_BORDER = 1

# 中文字体搜索路径（按优先级）
_FONT_PATHS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/SimHei.ttf",      # Linux
    "C:\\Windows\\Fonts\\msyh.ttc",           # Windows
]


def get_font_paths() -> list[str]:
    """返回实际存在的中文字体路径列表"""
    return [fp for fp in _FONT_PATHS if Path(fp).exists()]
