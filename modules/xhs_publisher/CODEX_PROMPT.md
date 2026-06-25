# 任务：修复小红书发布按钮点击

## 背景

小红书创作者平台新版 UI 的发布按钮是 `<xhs-publish-btn>` Vue 自定义元素，Playwright 的所有常规点击方式（locator.click、mouse.click、dispatchEvent、keyboard、CDP Input.dispatchMouseEvent）都无法触发它的发布事件。

手动在浏览器里点击这个按钮是有效的。

## 你需要做的

让 `publisher.py` 的 `publish()` 方法能够**完全自动化**点击发布按钮，不需要人工介入。

## 关键文件

- `publisher.py` — `XiaohongshuPublisher.publish()` 方法（第 106 行起）
- `publisher.py` — `_wait_for_manual_publish()` 是当前的过渡方案，可以删除
- `publisher.py` — 顶部 `SELECTORS` 字典和 `XHS_PUBLISH_URL`

## 已知信息

- 发布页 URL: `https://creator.xiaohongshu.com/publish/publish?from=menu&target=image`
- 发布按钮: `<xhs-publish-btn>` 自定义元素，位于页面内容区底部 (y≈810)
  - 属性: `is-publish="true"` `submit-text="发布"` `submit-disabled="false"` `save-text="暂存离开"`
  - 尺寸: 680×90px，position: sticky，z-index: 101
  - innerHTML 为空（Vue Virtual DOM 渲染，无真实子元素）
  - shadowRoot 为 null（不是 Shadow DOM）
  - cursor: auto（不是 pointer）
- 上传入口: `input[type="file"]`（页面第一个）
- 标题输入框: `input[placeholder*="标题"]`
- 正文编辑器: `.tiptap.ProseMirror`（ProseMirror 富文本）
- Cookie 文件: `cookies.json`（登录已就绪）
- 测试图片: `exports/moodboard_1780325963.png`（1080×1350 PNG）

## 测试命令

```bash
cd /Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound/modules/xhs_publisher
TASTEGRAPH_XHS_HEADFUL=1 python main.py publish \
  --image exports/moodboard_1780325963.png \
  --title "测试标题" \
  --caption "测试正文"
```

## 成功标准

运行 publish 命令后完全不需要人工操作，发布成功并打印帖子链接。

## 思路参考（可以任选或组合）

1. 从 `__vue_app__` 根节点遍历 Vue 组件树，找到包含 `publish`/`submit`/`handleClick` 方法的组件实例，直接调用
2. 找到 Vue app 的 Pinia store，直接 dispatch publish action
3. 用 Playwright 录制真实点击的 event 序列并精确回放
4. 直接调用小红书发布 API（抓包拿到 endpoint 和参数）
5. 用 `page.evaluate` 在 xhs-publish-btn 上 attach 一个原生 click handler，触发其 Vue 事件处理器
6. 任何其他能 work 的方案

## 注意

- 只改 `modules/xhs_publisher/` 下的文件
- 不要引入 taste_graph_ai 项目的 import
- 模块是完全独立的
