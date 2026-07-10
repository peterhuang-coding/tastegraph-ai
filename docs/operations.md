# TasteGraph AI — 操作手册

> 品味知识图谱 + 小红书内容管道。从爬取、选图、生成文案到自动发布，全流程覆盖。

---

## 目录

1. [快速开始](#1-快速开始)
2. [日常操作](#2-日常操作)
3. [数据维护](#3-数据维护)
4. [所有脚本一览](#4-所有脚本一览)
5. [故障排除](#5-故障排除)
6. [目录结构](#6-目录结构)

---

## 1. 快速开始

### 1.1 前提条件

- **Google Chrome**（macOS 已安装，Windows/Linux 需自行安装）
- **Python 3.12+**
- **pip 依赖**（首次运行需安装）：

```bash
pip3 install httpx beautifulsoup4 aiosqlite uvicorn
pip3 install playwright
python3 -m playwright install chromium
```

### 1.2 首次登录

自动发布需要先登录小红书创作者中心，通过扫码保存登录态。

```bash
bash start.sh login
```

### 1.3 第一篇发布

```bash
# 全流程一键运行
bash start.sh                       # 爬取1小时 + 选图 + 生成 + 启动审稿服务

# 或分步运行
bash start.sh publish --count 3     # 只生成发布包
bash start.sh serve                 # 启动审稿工作台
bash start.sh auto-pub              # 自动发布
```

---

## 2. 日常操作

### 2.1 登录/检查登录

```bash
bash start.sh login                          # 扫码登录
python3 scripts/auto_publish.py --check-login  # 检查登录状态
```

### 2.2 手动发布一篇

```bash
bash start.sh publish --count 1              # 生成 1 篇
bash start.sh serve                          # 审稿
python3 scripts/auto_publish.py --post-dir posts/2026-07-11/post-001  # 发布
```

### 2.3 生成发布包但不发布

```bash
bash start.sh publish --count 6
python3 scripts/pipeline.py --publish-only --count 5 --date 2026-07-10
```

### 2.4 启动定时发布

```bash
bash start.sh scheduler                      # 守护进程（08:00/20:00）
bash start.sh scheduler --run-now            # 立即执行一次
bash start.sh scheduler --dry-run            # 预览
bash start.sh scheduler --once               # 只执行下一次
```

### 2.5 启动审稿工作台

```bash
bash start.sh serve
# 或 python3 scripts/queue_server.py
# 浏览器访问 http://localhost:8765
```

### 2.6 查看发布效果周报

```bash
bash start.sh feedback
python3 scripts/publish_feedback.py report
```

---

## 3. 数据维护

### 3.1 回抓互动数据

```bash
python3 scripts/auto_feedback.py             # 回抓超过 24h 的
python3 scripts/auto_feedback.py --dry-run   # 预览不录入
python3 scripts/auto_feedback.py --all       # 回抓所有未回抓的
python3 scripts/auto_feedback.py --days 48   # 回抓 48h 前的
```

### 3.2 数据备份

```bash
python3 scripts/backup.py                    # 备份（保留最近 7 个版本）
python3 scripts/backup.py --dry-run          # 预览
python3 scripts/backup.py --keep 14          # 保留 14 个版本
```

### 3.3 数据清理

```bash
python3 scripts/cleanup_stale_data.py                # 清理 30 天未用图片
python3 scripts/cleanup_stale_data.py --dry-run      # 预览
python3 scripts/cleanup_stale_data.py --days 60      # 60 天阈值
python3 scripts/cleanup_stale_data.py --skip-logs    # 跳过日志轮转
```

### 3.4 统一调度器

```bash
python3 scripts/daemon_scheduler.py                  # 启动守护进程
python3 scripts/daemon_scheduler.py --run-all        # 立即执行所有任务
python3 scripts/daemon_scheduler.py --run backup     # 立即执行指定任务
```

---

## 4. 所有脚本一览

### 4.1 核心管道

| 脚本 | 一句话说明 |
|------|-----------|
| `scripts/pipeline.py` | 全流程管道：爬取 → 选图 → 生成 → 启动服务 |
| `scripts/generate_publish_packs.py` | 从已爬取图片中选 Top-N 并生成发布包 |
| `scripts/queue_server.py` | 启动本地 QUEUE 审稿服务（端口 8765） |
| `scripts/auto_publish.py` | 自动发布到小红书（需先登录） |
| `scripts/publish_scheduler.py` | 定时发布守护进程 |
| `scripts/publish_playwright.py` | Playwright 方案发布（CDP 备用方案） |

### 4.2 爬虫

| 脚本 | 一句话说明 |
|------|-----------|
| `scripts/crawl_loop_6h.py` | 多源爬虫循环 |
| `scripts/run_xhs_12h_pipeline.py` | 12 小时内容整合管道 |
| `scripts/moodboard_fetch.py` | 从 Are.na 抓取 moodboard 图片 |

### 4.3 反馈/调权

| 脚本 | 一句话说明 |
|------|-----------|
| `scripts/publish_feedback.py` | 发布效果周报 + 互动数据录入 |
| `scripts/auto_feedback.py` | 自动回抓小红书帖子互动数据 |
| `scripts/taste_feedback.py` | 更新 taste memory 偏好/规避关键词 |

### 4.4 数据维护

| 脚本 | 一句话说明 |
|------|-----------|
| `scripts/backup.py` | 备份核心数据文件 |
| `scripts/cleanup_stale_data.py` | 清理过期图片 + 日志轮转 |
| `scripts/daemon_scheduler.py` | 统一调度器管理所有定时任务 |
| `scripts/source_dashboard.py` | 生成信息源看板 HTML |

### 4.5 start.sh 模式一览

```bash
bash start.sh                          # 全流程
bash start.sh publish --count 6        # 只生成发布包
bash start.sh serve                    # 只启动审稿服务
bash start.sh feedback                 # 查看周报
bash start.sh crawl                    # 只运行爬取
bash start.sh auto-pub                 # 生成 + 自动发布
bash start.sh login                    # 扫码登录
bash start.sh scheduler                # 启动定时调度
```

---

## 5. 故障排除

### 5.1 CDP 连接失败

**现象**：`Could not connect to Chrome at http://127.0.0.1:9222`

**解决**：
```bash
# 以调试模式启动 Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug &
# 验证连接
curl http://127.0.0.1:9222/json/version
```

### 5.2 Chrome 端口占用

**解决**：
```bash
lsof -i :9222
kill -9 $(lsof -ti :9222)
```

### 5.3 登录过期

**解决**：`bash start.sh login` 重新扫码

### 5.4 发布失败

| 原因 | 解决 |
|------|------|
| 未登录 | `bash start.sh login` |
| 选择器失效 | `python3 scripts/check_selectors.py` 检查 |
| 风控限制 | 增加 `--min-interval` 和 `--timing-jitter` |

### 5.5 爬虫没有新内容

**解决**：检查 `link_sources.json` 配置，增加爬取时长 `bash start.sh crawl --crawl-hours 2`

---

## 6. 目录结构

```
.
├── start.sh                       # 一键启动入口
├── scripts/                       # 可执行脚本（20+）
├── taste_graph_ai/                # 核心库（Python 包）
├── xhs_publisher/                 # 小红书发布模块
├── data/                          # 数据文件（图谱、DB、图片）
├── posts/                         # 生成的发布包
├── config/                        # 配置文件
├── docs/                          # 文档
├── link_sources.json              # 信息源配置（27 个源）
└── taste_memory.json              # 品味偏好记忆
```

---

## 附录：常用命令速查

```bash
# 首次
pip3 install httpx beautifulsoup4 aiosqlite uvicorn playwright
python3 -m playwright install chromium
bash start.sh login

# 每日
bash start.sh publish --count 3
bash start.sh serve
python3 scripts/auto_publish.py --all

# 全天候
bash start.sh scheduler

# 复盘
bash start.sh feedback

# 维护
python3 scripts/backup.py
python3 scripts/cleanup_stale_data.py --dry-run
```
