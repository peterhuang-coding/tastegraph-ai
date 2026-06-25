# 小红书自动发布模块

独立模块，不依赖项目其他部分。只需要图片 + 文案 → 自动发布到小红书。

---

## 快速开始

### 1. 安装依赖

```bash
pip install playwright Pillow
playwright install chromium
```

### 2. 首次登录（只需一次）

```bash
TASTEGRAPH_XHS_HEADFUL=1 python main.py login
```

会打开 Chromium 浏览器 → 扫码登录小红书创作者平台 → Cookie 自动保存到 `cookies.json`。

### 3. 合成 Moodboard（图片拼贴）

```bash
python main.py compose --images ./mock_data/ --title "沉默的质感" --caption "不争不抢，只记录..."
```

输入：`mock_data/` 下的前 9 张图片  
输出：`exports/moodboard_<timestamp>.png`（1080×1350，小红书竖版比例）

### 4. 发布到小红书

```bash
TASTEGRAPH_XHS_HEADFUL=1 python main.py publish \
  --image exports/moodboard_1717280000.png \
  --title "今日推荐" \
  --caption "写一段文案..."
```

⚠️ **需要 `TASTEGRAPH_XHS_HEADFUL=1`** 打开浏览器窗口。  
脚本会自动完成图片上传、标题填写、正文填写，并自动点击「发布」按钮。  
发布后脚本会自动检测成功并返回帖子链接。

> 原因：小红书新版创作者平台的发布按钮是 `<xhs-publish-btn>` Vue 自定义元素，Playwright/CDP 合成点击无法触发其事件。当前方案会优先用 macOS 系统级鼠标点击按钮中心，必要时再尝试调用 Vue 组件方法。

### 5. 一键合成+发布

```bash
python main.py run --images ./mock_data/ --title "一键发布" --caption "..."
```

---

## 文件说明

```
modules/xhs_publisher/
  main.py          入口 — 所有 CLI 命令
  publisher.py     浏览器自动化（Playwright），登录 + 上传 + 发布
  composer.py      图片合成（Pillow），3×3 网格 + 中文标题
  config.py        所有配置项，默认值 + 环境变量覆盖
  README.md        本文档
  requirements.txt Python 依赖
  mock_data/       放 9 张测试图片
  exports/         合成后的 moodboard 输出
  cookies.json     登录后自动生成（不要提交到 git）
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TASTEGRAPH_XHS_HEADFUL=1` | off | 显示浏览器窗口（调试/首次登录） |
| `XHS_COOKIES_FILE` | `./cookies.json` | Cookie 保存路径 |
| `XHS_EXPORTS_DIR` | `./exports` | 导出目录 |
| `XHS_CREATOR_URL` | `https://creator.xiaohongshu.com` | 创作者平台地址 |

---

## 常见问题

**Q: 登录失败 / 超时？**  
A: 小红书可能更新了登录页。打开 `publisher.py`，更新 `SELECTORS` 字典里的 CSS 选择器。

**Q: 发布按钮点不动？**  
A: 小红书新版创作者平台 (2026) 使用 `<xhs-publish-btn>` Vue 自定义元素，Playwright 无法触发其点击事件。当前方案会在 headful 模式下使用系统级鼠标点击；如果 macOS 拒绝控制，请在「系统设置 → 隐私与安全性 → 辅助功能」里允许当前终端/Codex 控制电脑。如 UI 再次更新，调试步骤见下文。

**Q: 小红书又更新了 UI 怎么调试？**  
A: 用 headful 模式运行，在浏览器开发者工具中检查元素：
- 上传入口：找 `input[type="file"]`
- 标题输入框：找 `input[placeholder*="标题"]`
- 正文编辑器：找 `.tiptap.ProseMirror`（ProseMirror 富文本编辑器）
- 发布按钮：`<xhs-publish-btn>` Vue 组件（位于页面底部 sticky 位置，z-index=101）
- 更新 `publisher.py` 顶部的 `SELECTORS` 字典和 `XHS_PUBLISH_URL`

**Q: Cookie 过期了？**  
A: 重新跑 `TASTEGRAPH_XHS_HEADFUL=1 python main.py login`

**Q: Linux 服务器字体乱码？**  
A: 在 `config.py` 的 `_FONT_PATHS` 里加上你的中文字体路径，比如 `/usr/share/fonts/SimHei.ttf`

**Q: 怎么传 9 张图但来源不是同一个目录？**  
A: 可以直接调 Python API：
```python
from modules.xhs_publisher.composer import MoodboardComposer
from modules.xhs_publisher.publisher import publish_one
import asyncio

composer = MoodboardComposer()
output = composer.compose(
    image_paths=["/path/to/img1.jpg", "/path/to/img2.jpg", ...],
    title="标题",
    caption="文案",
)
asyncio.run(publish_one(str(output), "标题", "文案"))
```

---

## 与主项目的集成方式（后面接回来时改这里）

当前模块是**完全独立的**。集成回主项目时，主项目调用方需要：

1. 把 `taste_graph_ai/infrastructure/publisher/xhs.py` 的 import 改为 `from modules.xhs_publisher.publisher import XiaohongshuPublisher`
2. 把 `taste_graph_ai/services/composer.py` 的 import 改为 `from modules.xhs_publisher.composer import MoodboardComposer`
3. 传入主项目的 config 路径（cookie 文件、导出目录）

也就是改两行 import，其余不变。
