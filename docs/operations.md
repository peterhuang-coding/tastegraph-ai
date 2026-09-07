# moodboard. — 操作手册

> **个人视觉采样系统**。52 sources · 9 images per pack · One editor.
> 项目身份见 [`VISION.md`](../VISION.md)。

> **常驻模型（2026-09-08 Phase 3 起）**：唯一采集入口是
> `scripts/daily_ingestion.py --resume`（幂等、可恢复、状态落库）。
> launchd 服务项在 `deploy/launchd/`（**只入库，人工安装**）：
> 每日 03:00 采集、04:00 备份、工作台 KeepAlive。调度“今天是否已跑”以
> `job_runs` 表为准，重启不补跑成功任务。自动发布/登录/互动**永久封停**。

---

## 0. 常驻服务与每日采集（新）

| 项 | 入口 | 说明 |
|---|---|---|
| 每日采集 | `python3 scripts/daily_ingestion.py --resume` | preflight→crawl→persist→download→pack→summary；运行锁 + 阶段幂等 + 双去重；当天已成功则跳过（`--force` 强制） |
| 每日备份 | `python3 scripts/backup_db.py` | SQLite 在线备份 → `data/backups/`，integrity_check + 行数校验，保留 14 天/30 份 |
| 工作台 | `python3 scripts/queue_server.py` | 编辑台/发布登记/源面板，默认 `127.0.0.1:8765` |
| 图谱控制台 | `python3 -m taste_graph_ai.server` | 8787，默认环回、不 reload、CORS 白名单 |
| （可选）tape 多任务调度 | `python3 scripts/daemon_scheduler.py` | job_runs 持久化 + detached worker；launchd 直挂采集后一般不需要 |

launchd 安装/切换/卸载步骤见 [`deploy/launchd/README.md`](../deploy/launchd/README.md)。
**仓库内任何脚本都不执行 launchctl**；加载/卸载是老板的人工动作。

采集状态：
- 结构化摘要 `data/daily_ingestion_status.json`（明早验收看这个）
- 运行实例 `crawl_runs` 表、调度态 `job_runs` 表
- worker 日志 `data/logs/<job>-<ts>.log`（保留 14 天）、事件 `data/events.log`

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

### 4.4 调度与常驻
| 脚本 / 文件 | 用途 |
|---|---|
| `scripts/daily_ingestion.py` | **唯一采集入口**，`--resume` 幂等恢复（launchd 每日 03:00） |
| `scripts/backup_db.py` | SQLite 在线备份（launchd 每日 04:00） |
| `scripts/daemon_scheduler.py` | 可选 tape 多任务循环（job_runs 持久化 + detached worker + 日志轮转） |
| `config/schedule.json` | daemon_scheduler 的任务定义（launchd 直挂采集/备份时不依赖它） |
| `deploy/launchd/*.plist` | launchd 服务项（入库不自动装，安装见 README） |
| `scripts/launch_dashboard.sh` | 启动 8787 web server + 11 tab（只起控制台，不复活任何 plist） |

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

### 🟡 调度状态持久化（Phase 3）
- “今天是否已跑”以 `job_runs` 表为准（契约 §1），**不依赖进程内存**
- 重启/重复触发不补跑当天已成功任务；`running` 但 worker 进程消失自动标记
  `failed`，下次触发 `--resume` 幂等补跑；失败任务 30 分钟退避（可配 `retry_backoff_minutes`）
- 长 crawl 在 detached 子进程跑，不阻塞调度循环；运行锁（fcntl flock）是并发终极防线
- launchd 切换是**人工一次性动作**（`deploy/launchd/README.md`）；切之前旧
  `com.user.tastegraph.daemon` 仍在跑，属正常，不要同时双跑采集

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

### 6.4 采集中断 / 想手动补跑
```bash
# 看状态与日志
cat data/daily_ingestion_status.json      # 最近一次结构化摘要
ls -t data/logs/ | head                   # worker 日志（保留 14 天）
tail -f data/logs/daily_ingestion-*.log

# 幂等恢复（已完成阶段自动跳过，未完成续跑）
python3 scripts/daily_ingestion.py --resume

# 当天已成功但想强制重跑
python3 scripts/daily_ingestion.py --resume --force

# 短跑调试（只下载 50 项，不爬新页）
python3 scripts/daily_ingestion.py --stage download --max 50
```
“已有采集实例在运行，立即退出”（exit 2）= 锁被占用；若确认没有活进程，
检查 `data/ingestion.lock` 对应 pid 是否僵死（`ps -p <pid>`），僵死时锁会在
进程退出后由 OS 释放，`job_runs` 里的 running 行会被调度器 reap 为 failed。

### 6.5 备份与恢复
```bash
python3 scripts/backup_db.py              # 在线备份 → data/backups/taste_graph-<ts>.db
cat data/backups/latest_backup.json       # 最近一次校验结果
# 恢复（先停服务，再拷贝；.db 是一致快照）
cp data/backups/taste_graph-<ts>.db data/taste_graph.db
```
旧 `scripts/backup.py` 是文件拷贝（WAL 未 checkpoint 时可能丢最新写入），
已被 `backup_db.py`（SQLite Online Backup API + integrity_check + 行数比对）取代。

### 6.6 launchd 服务
```bash
# 状态（不修改任何东西）
launchctl print gui/$(id -u)/com.user.tastegraph.ingestion | head -20
launchctl print gui/$(id -u)/com.user.tastegraph.queue | head -20
tail -f ~/Library/Logs/TasteGraph/ingestion.log
# 安装/卸载：deploy/launchd/README.md（人工执行，仓库脚本不碰 launchctl）
```

### 6.7 Git push 失败 7890 proxy 死
```bash
# 全局配置 7890 已死,用 7897 override:
git -c http.proxy=http://127.0.0.1:7897 \
    -c https.proxy=http://127.0.0.1:7897 \
    push origin main
```

---

## 7. 网络暴露、CORS 与最小认证

**默认全部绑环回（127.0.0.1）**，只在本机浏览器访问：

| 服务 | 端口 | 绑定变量 | CORS 变量 |
|---|---|---|---|
| 工作台 queue_server | 8765 | `QUEUE_HOST`（默认 127.0.0.1） | `TASTEGRAPH_ALLOWED_ORIGINS` |
| 图谱 FastAPI | 8787 | `TASTEGRAPH_HOST`（默认 127.0.0.1） | `TASTEGRAPH_ALLOWED_ORIGINS` |

- **CORS 默认空白名单 = 同源 only**，两个服务都**永不返回 `Access-Control-Allow-Origin: *`**。
  跨域需求走 queue_server 的服务端代理（`/api/*` → 8787），浏览器不直接跨域。
- FastAPI 生产默认**不 reload**（开发设 `TASTEGRAPH_RELOAD=1`）。
- **没有内建账号/密码认证**。安全边界 = 网络可达性：
  - 环回：只有本机能访问。
  - Tailscale：设 `QUEUE_HOST=0.0.0.0`（或 tailscale IP）+ `TASTEGRAPH_ALLOWED_ORIGINS=http://<tailscale名>:8765`，
    暴露面 = tailnet 内设备（Tailscale 自带 mTLS + ACL）。**不要**绑公网 IP，不要做端口转发。
  - 局域网：同上但暴露面 = 同一 Wi-Fi 所有设备，仅在可信网络用。
- queue_server 仅剩文件写端点（`/save-file` 草稿落盘、`/replace-image` 换帧、
  `/publish-entries` 发布账本）与 `/pack-zip` 打包下载；远程操控 mini 的
  `/copy-image`（剪贴板）、`/open-file`、`/open-folder`（Finder/Preview）已于
  2026-09-08 工作台收口移除，预览/下载/复制文案全部在浏览器内完成。文件写端点
  在绑环回时只响应本机；一旦绑 0.0.0.0，同网段任何人都能调用 ——
  所以远程访问**只用 Tailscale，不用裸 0.0.0.0 + 公网**。

## 8. 目录结构(精简)

```
moodboard-hidden-ny-jjjjound/
├── VISION.md                # 项目身份 — 必读
├── README.md                # 系统简介 + 源 moodboard 设计参考
├── docs/
│   ├── data-contract.md     # 数据契约（表/枚举/迁移，改库先改这里）
│   ├── voice.md             # voice 系统(taste_ip_system)
│   └── operations.md        # 本文件
├── deploy/
│   └── launchd/             # launchd 服务项（入库不自动装；README 有安装步骤）
│       ├── com.user.tastegraph.ingestion.plist   # 每日 03:00 采集
│       ├── com.user.tastegraph.backup.plist      # 每日 04:00 备份
│       └── com.user.tastegraph.queue.plist       # 工作台 KeepAlive
├── scripts/
│   ├── daily_ingestion.py   # ★ 唯一安全采集入口（--resume 幂等）
│   ├── backup_db.py         # SQLite 在线备份 + 校验
│   ├── daemon_scheduler.py  # 可选 tape 调度（job_runs 持久化 + detached worker）
│   ├── migrations.py        # 幂等迁移（v1-v9）
│   ├── queue_server.py      # 工作台 HTTP（8765，默认环回）
│   ├── run_24h_crawl.sh     # 24h 长跑（手动）
│   └── launch_dashboard.sh  # 启 8787 web server
├── taste_graph_ai/
│   ├── server.py / config.py# FastAPI（默认环回、不 reload、CORS 白名单）
│   ├── api/routes/          # FastAPI 路由(graph / daily / sources ...)
│   └── static/              # Dashboard 前端(11 tab)
├── data/
│   ├── taste_graph.db       # SQLite 单库（WAL）
│   ├── daily_ingestion_status.json   # 最近采集摘要（明早验收）
│   ├── events.log           # 调度事件（5MB 轮转）
│   ├── logs/                # worker 日志（14 天清理，gitignore）
│   ├── backups/             # DB 在线备份（14 天/30 份，gitignore）
│   └── images/              # 下载图片实体（gitignore）
├── posts/                   # daily packs 输出
├── runs/                    # crawl 输出（loop_*/output.jsonl）
└── config/
    ├── schedule.json        # daemon_scheduler 任务定义
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
python3 scripts/backup_db.py           # SQLite 在线备份（校验 + 14 天保留）
python3 scripts/cleanup_stale_data.py  # 清理 30 天未用
```

---

**最后更新**:2026-09-08（Phase 3：job_runs 持久化调度、detached worker、launchd 服务项、SQLite 在线备份、CORS/绑定加固；见 §0/§6/§7 与 deploy/launchd/）