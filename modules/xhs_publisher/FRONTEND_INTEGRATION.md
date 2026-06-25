# 前端集成任务：对接小红书自动发布模块

## 背景

`modules/xhs_publisher/` 是一个**已跑通**的小红书自动发布模块：
- `composer.py` — 把 9 张图拼成 1080×1350 moodboard PNG
- `publisher.py` — Playwright 浏览器自动化，自动上传+填标题+填正文+点击发布，返回帖子链接
- CLI 已验证：`TASTEGRAPH_XHS_HEADFUL=1 python main.py publish --image xxx.png --title "标题" --caption "文案"` 可以成功发布

## 当前项目架构

```
taste_graph_ai/
  server.py              ← FastAPI 服务 (port 8787)
  api/routes/daily.py    ← /api/v1/daily/{pack_id}/auto-publish 已经存在
  api/routes/curation.py ← /api/v1/packs/curated 创建策展包
  services/composer.py   ← 旧版 MoodboardComposer（和 modules 里的是重复代码）
  infrastructure/publisher/xhs.py ← 旧版 XiaohongshuPublisher（已失效，UI 变更后不可用）
  config.py              ← EXPORTS_DIR = data/exports, XHS_COOKIES_FILE = data/xhs_cookies.json
  static/
    index.html           ← 5 个 tab: 发现源审核 | 今日推荐 | 品味图谱 | 发布历史 | 手动选图
    js/curation.js       ← 手动选图 tab：选 9 张 → 创建策展包 → 预览 → "导出并发布"
    js/daily.js          ← 今日推荐 tab：已有 "一键发布" 按钮 → 调用 auto-publish API → showPublishModal
```

## 现有流程

### 手动选图 (curation.js)
1. 用户选 9 张图 → 填主题/标题/文案 → 点「创建策展包」
2. POST /api/v1/packs/curated → 创建 DailyPack
3. 弹预览框 → 「导出并发布」按钮
4. POST /api/v1/daily/{packId}/export → 生成 moodboard PNG → showPublishModal（手动填链接）

### 今日推荐 (daily.js)
1. 已有 "一键发布" 按钮（`.btn-auto-publish`，第 172 行）
2. 调用 `POST /api/v1/daily/{id}/select` + `POST /api/v1/daily/{id}/auto-publish`
3. 旧版 publisher 已失效

## 你需要改的

### 1. 后端：修复 auto-publish 端点 ✅ 关键

**文件：`taste_graph_ai/api/routes/daily.py`**

第 232 行，把旧 import：
```python
from taste_graph_ai.infrastructure.publisher.xhs import XiaohongshuPublisher
```
替换为：
```python
from modules.xhs_publisher.publisher import XiaohongshuPublisher
```

同时传入正确的 cookie 路径（模块默认读 `modules/xhs_publisher/cookies.json`，但项目 cookie 在 `data/xhs_cookies.json`）：
```python
from taste_graph_ai.config import XHS_COOKIES_FILE

async with XiaohongshuPublisher(cookies_path=XHS_COOKIES_FILE) as publisher:
    post_url = await publisher.publish(...)
```

### 2. 前端 curation.js：加「一键发布到小红书」按钮

在 `showPreview()` 的预览弹窗里（第 225-229 行），现有的「导出并发布」旁边加一个「一键发布到小红书」按钮：

```javascript
<button class="btn btn-accent" style="flex:1" onclick="CurationTab.autoPublish('${pack.id}')">
  🚀 一键发布到小红书
</button>
```

新增 `autoPublish` 方法：
```javascript
async autoPublish(packId) {
  const btn = event.target;
  btn.textContent = '... 发布中';
  btn.disabled = true;
  try {
    const result = await API.post(`/api/v1/daily/${packId}/auto-publish`);
    if (result.success) {
      App.toast(`发布成功！${result.post_url}`, 'success');
      this.closePreview();
    } else {
      App.toast(result.error, 'error');
    }
  } catch(e) {
    App.toast(`发布失败: ${e.message}`, 'error');
  }
  btn.textContent = '🚀 一键发布到小红书';
  btn.disabled = false;
}
```

### 3. 前端 daily.js：修复 showPublishModal

`showPublishModal`（第 203 行）目前展示的是"手动发完贴后填写链接"的 UI。如果 auto-publish 成功，应该直接显示成功信息而不是手动填写框。改一下逻辑：auto-publish 成功后直接 `App.toast`，不弹 modal。

### 4. 可选：统一 composer

`taste_graph_ai/services/composer.py` 和 `modules/xhs_publisher/composer.py` 是重复代码。可以把 `daily.py` 里的 `MoodboardComposer` import 也统一改成：
```python
from modules.xhs_publisher.composer import MoodboardComposer
```
但这不影响功能，优先级低。

## 测试步骤

1. 启动服务器: `bash start.sh`
2. 打开 http://localhost:8787
3. 进入「手动选图」tab → 选 9 张图 → 填主题/标题/文案 → 创建策展包
4. 在预览弹窗点「一键发布到小红书」→ 自动发布 → 看到成功 toast
5. 进入「今日推荐」tab → 点「一键发布」→ 自动发布成功

## 注意事项

- 发布需要 `TASTEGRAPH_XHS_HEADFUL=1` 环境变量（打开浏览器窗口）
- Cookie 文件路径是 `data/xhs_cookies.json`（通过 XHS_COOKIES_FILE 传入）
- 首次使用需要先登录：`TASTEGRAPH_XHS_HEADFUL=1 python modules/xhs_publisher/main.py login`
- 如果发布失败，检查浏览器窗口是否被关闭、Cookie 是否过期
- 只改 taste_graph_ai/ 下的文件，不要改 modules/xhs_publisher/（那个模块已经跑通了）
