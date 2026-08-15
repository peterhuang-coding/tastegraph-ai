# moodboard. — 操作手册

> **个人视觉采样系统**。52 sources · 9 images per pack · One editor.
> 项目身份见 [`VISION.md`](../VISION.md)。

---

## 1. 快速开始

### 1.1 启动 dashboard

```bash
bash scripts/launch_dashboard.sh
# 浏览器打开 http://localhost:8787
```

> ⚠️ 此脚本**只**启动 web server。**不**启动 daemon,**不**复活任何 plist,XHS 自动发布永久封停。

### 1.2 启动一次 24h crawl

```bash
bash scripts/run_24h_crawl.sh [rate]    # 默认 200 req/h × 24h
```

后台跑,日志写 `runs/crawl_24h_<ts>.log`,PID 写 `runs/crawl_24h.pid`。

### 1.3 监控运行中

```bash
bash scripts/crawl_status.sh            # 单屏状态
tail -f runs/crawl_24h_<ts>.log         # 实时日志
python3 scripts/audit_crawl.py          # 质量审计
```

---

## 2. 日常操作(3 分钟/天)

打开 **Home tab**,做这 3 件事:

### 2.1 抽样 6 张图(1 分钟)— **最重要**
Home 上「📸 抽样 · N 张待取舍」 → 每张点一下:
- **✓ 对味** — 进图谱权重 ↑
- **⭐ 精** — 进精选池,优先 pack
- **⏭ 弃** — 减权重,以后不推荐

> 这 6 次点击是 moodboard. 的**唯一人工信号**,决定采样池漂移方向。

### 2.2 采样池(1 分钟)
Home 上「📡 采样池 · N 个待你浏览」 → 点开 `SOURCES.html`:
- **8 个 approved 源** — 按 reviewed_at 排序,最久没看的优先
- **4 个 newly discovered** — 决定加 / 弃

如果 `SOURCES.html` 没更新,手动跑:
```bash
python3 scripts/daily_source_brief.py
```

### 2.3 今日采样 pack(1 分钟)
Home 下方「📦 今日采样 · N 组精筛」:
- 扫 3 个 9 图 pack 是否对味
- 不对味:点 curation tab 手动换图
- 对味:留在 `daily_packs` 备用

---

## 3. 周期操作(按需,不是每天)

### 3.1 24h 长跑启动
```bash
# 起 (后台 nohup)
bash scripts/run_24h_crawl.sh 200

# 停
kill $(cat runs/crawl_24h.pid)

# 看
bash scripts/crawl_status.sh
python3 scripts/audit_crawl.py
```

**触发时机**:
- 老板手动决定:每 3-7 天一次
- 或 schedule.json 标记 03:00 BJT(实际**不自动跑**,因为 daemon 8/1 已删)

### 3.2 每周一:feedback 周报
```bash
# 自动? 不会 — daemon 已删
# 手动跑:
python3 scripts/weekly.py    # 或对应脚本
```

看 Home 上「📊 本周采样」卡片 + weekly tab。

### 3.3 trend 信号(随时)
按 **⌘+Shift+T** 打开潮流 tab。340+ 关键词的 rising / fading。

### 3.4 品味图谱 drill-down
点导航栏「⚙️ 系统」→ 「品味图谱」。Cytoscape 可视化,节点 1223 / 边 2017。

---

## 4. 所有脚本一览

### 4.1 采样(主动)
| 脚本 | 用途 |
|---|---|
| `scripts/run_24h_crawl.sh` | 24h 不间断后台爬 |
| `scripts/crawl_loop_6h.py` | 单次循环爬取(被前者调用) |
| `scripts/audit_crawl.py` | 爬取质量审计(IKEA 类污染检测) |
| `scripts/crawl_status.sh` | 单屏状态快照 |

### 4.2 采样池(被动,定时)
| 脚本 | 用途 |
|---|---|
| `scripts/daily_source_brief.py` | 生成 `SOURCES.html`(8 approved + 4 new) |

### 4.3 取舍(人工)
| 脚本 | 用途 |
|---|---|
| Home tab 抽样 | ✓对味 / ⭐精 / ⏭弃 |
| Home tab 今日采样 | 浏览 AI 精筛 pack |
| curation tab | 手动换图 / 调 pack |

### 4.4 调度
| 脚本 | 用途 |
|---|---|
| `config/schedule.json` | 任务定义(**daemon 已删,实际不自动跑**) |
| `scripts/launch_dashboard.sh` | 启动 web server + 11 tab |

### 4.5 历史/已封存(不要用)
| 脚本 | 状态 |
|---|---|
| `scripts/auto_publish.py` | 🚫 XHS 自动发布已封停(`I-UNDERSTAND-RISK` header 才解) |
| `scripts/publish_scheduler.py` | 🚫 schedule.json `live_post` 永久 disabled |
| `scripts/auto_feedback.py` | 🚫 `auto_feedback` 永久 disabled |
| `xhs_publisher/*` | 🚫 XHS 整套技术栈封存 |

---

## 5. 关键约束(必读)

### 🔴 XHS 自动发布永久封停
- 7/29 老板账号又被封,根因是后台自动化点击 / 上传
- `config/schedule.json` 顶层 `_publish_disabled: true`
- 所有 XHS-touching 任务(发布 / 回抓)enabled=false
- 后端 `/cdp-publish` 默认 403,需要 `I-UNDERSTAND-RISK` header 才能手动 override
- UI 双确认(精确输入"确认发布"才能触发)

### 🟡 调度脱钩
- 8/1 起无 launchd daemon
- `schedule.json` 写 6 个 enabled 任务,但**实际不会自动跑**
- 所有任务必须手动触发(或重新起 daemon,见 §6.4)

### 🟢 SKIP_DOMAINS(源质量控制)
- 硬跳过 IKEA / Taobao / Tmall / Amazon / eBay / AliExpress / Pinterest / Instagram / TikTok / Reddit / Facebook / Twitter
- 反 IKEA 53% 污染(8/8 任务 #24 修复)

---

## 6. 故障排除

### 6.1 Dashboard 打不开
```bash
lsof -iTCP:8787 -sTCP:LISTEN -P -n    # 检查 server
bash scripts/launch_dashboard.sh      # 启动
```

### 6.2 24h crawl 没启动 / 立刻挂
```bash
cat runs/crawl_24h_<ts>.log           # 看错误
python3 scripts/audit_crawl.py        # 看上一轮质量
# 常见: 7890 proxy 死,7897 活
NO_PROXY=localhost,127.0.0.1 curl ... # 本地调用要加 NO_PROXY
```

### 6.3 图谱 tab 看不到
点导航栏最右边「⚙️ 系统」按钮展开 admin tab(图谱 / 趋势 / 爬虫等都在内)。

### 6.4 想恢复自动调度
```bash
# 写一个新 launchd plist,只挂非 XHS 任务(纯爬虫 / 备份 / trend_report)
# 见 config/schedule.json 的 enabled=true 任务清单
# 注意:crawl / daily_source_brief / pack_generation / backup / cleanup / trend_report
```

### 6.5 Git push 失败 7890 proxy 死
```bash
# 全局配置 7890 已死,用 7897 override:
git -c http.proxy=http://127.0.0.1:7897 \
    -c https.proxy=http://127.0.0.1:7897 \
    push origin main
```

---

## 7. 目录结构(精简)

```
moodboard-hidden-ny-jjjjound/
├── VISION.md                # 项目身份 — 必读
├── README.md                # 系统简介 + 源 moodboard 设计参考
├── docs/
│   ├── voice.md             # voice 系统(taste_ip_system)
│   └── operations.md        # 本文件
├── research/aesthetic-os/   # 19 份 research(MIGRATION.md 有说明)
├── scripts/
│   ├── run_24h_crawl.sh     # 24h 长跑
│   ├── audit_crawl.py       # 质量审计
│   ├── crawl_status.sh      # 状态快照
│   ├── daily_source_brief.py
│   ├── crawl_loop_6h.py     # 单次爬取循环
│   └── launch_dashboard.sh  # 启 web server
├── taste_graph_ai/
│   ├── api/routes/          # FastAPI 路由(graph / daily / sources ...)
│   └── static/              # Dashboard 前端(11 tab)
├── data/                    # 运行时数据(图谱 / DB / events.log)
├── posts/                   # daily packs 输出
├── runs/                    # crawl 输出 + 24h pid/log
└── config/
    ├── schedule.json        # 任务定义
    └── link_sources.json    # 52 源
```

---

## 附录:常用命令速查

```bash
# 启动
bash scripts/launch_dashboard.sh       # web 控制台
bash scripts/run_24h_crawl.sh 200      # 24h 后台爬

# 监控
bash scripts/crawl_status.sh           # 单屏状态
python3 scripts/audit_crawl.py         # 质量审计
tail -f runs/crawl_24h_<ts>.log        # 实时日志

# 每日(Home tab 内 3 分钟)
# - 抽样 6 张图 → ✓对味/⭐精/⏭弃
# - 浏览 SOURCES.html
# - 扫一眼今日采样 pack

# 周期
python3 scripts/daily_source_brief.py  # 生成 SOURCES.html(需手动)
python3 scripts/backup.py              # 备份
python3 scripts/cleanup_stale_data.py  # 清理 30 天未用
```

---

**最后更新**:2026-08-15(moodboard. 身份重塑,与 VISION.md 同步)