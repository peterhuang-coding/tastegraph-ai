# TasteGraph 数据契约 v1

> 2026-09-08 · 契约先于代码。所有实体以 SQLite（`data/taste_graph.db`）为唯一权威事实源。
> 文件（posts/、QUEUE.html、publish_log.json）只能是导出产物或非权威缓存。
> 本契约随 `scripts/migrations.py` 幂等落地；旧数据全部保留，迁移报告见 `data/migration_report-*.json`。

## 0. 总原则

1. **单一权威库**：SQLite WAL，`data/taste_graph.db`。前端 localStorage、JSON 文件、posts 目录均为缓存/导出，不得承载权威状态。
2. **主键语义**：业务主键全局唯一、永不跨日期复用。目录名、相对路径与数据库 id 是三个不同字段，禁止混用。
3. **时间语义**：一律 ISO 8601（`YYYY-MM-DDTHH:MM:SS`，含时区或统一 +08:00）。`published_at` 是唯一发布时间字段，禁止 `time`/`date`/`published` 等别名。
4. **图片与 alt 同对象**：`images: [{url, alt}]` 为唯一传递形态；禁止两个独立数组按下标配对。
5. **快照语义**：24h/48h 是累计快照（48h 含 24h 数据）。**最新窗口优先，绝不相加**。局部更新先与服务端完整记录合并，再计算反馈；缺失字段≠0。
6. **迁移**：幂等（`CREATE TABLE IF NOT EXISTS` + 字段存在性检查），保留旧数据，输出迁移报告，禁止静默丢字段。
7. **溯源**：新入库图片必须能追溯 `source_id`、`page_url`、`image_url`。无法关联 source 时记录异常事件，不允许静默写空参与来源评分。

## 1. 实体与字段

### Source（表 `sources`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 稳定 id（md5(url)） |
| url | TEXT NOT NULL | 源地址（页面根/入口） |
| name | TEXT NOT NULL | 显示名 |
| source_type | TEXT NOT NULL | 见 §2 枚举 |
| status | TEXT NOT NULL | pending/approved/rejected/deferred |
| created_at | TEXT NOT NULL | ISO 8601 |
| reviewed_at | TEXT NULL | 审核时间 |

### CrawlRun（表 `crawl_runs`，新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | run_id，格式 `run-YYYYMMDDHHMMSS-<6hex>` |
| scheduled_for | TEXT | 计划时间 ISO 8601 |
| started_at / finished_at | TEXT NULL | 实际起止 |
| status | TEXT NOT NULL | pending/running/succeeded/partial/failed |
| pages_attempted / pages_fetched / pages_failed | INTEGER | 页级计数 |
| images_discovered / images_downloaded | INTEGER | 图级计数 |
| backlog_count | INTEGER | 结束时剩余待下载积压 |
| error_summary | TEXT | 脱敏错误摘要 |

### IngestionItem（表 `ingestion_items`，新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | `run_id + ':' + md5(image_url)` |
| run_id | TEXT FK→crawl_runs | 发现该 item 的运行 |
| source_id | TEXT FK→sources | 解析后来源（可为空，但必须记录解析失败事件） |
| page_url / image_url | TEXT | 溯源链 |
| alt_text | TEXT | 与 image_url 同对象 |
| status | TEXT | discovered/downloaded/failed/skipped |
| attempt_count | INTEGER | 失败重试计数 |
| last_error | TEXT | 最近错误 |
| created_at / updated_at | TEXT | ISO 8601 |

**Backlog 规则**：items 持久化在表中；下载器只消费 backlog 并更新状态；`--max` 只限制单次处理量，绝不丢弃剩余项；跨 crawl 批次持续有效。

### Image（表 `images`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | md5(normalized_url) 或内容 checksum |
| source_id | TEXT FK→sources | **必须解析，禁止默认写空**（解析失败→记录事件） |
| url / page_url | TEXT | 溯源 |
| local_path / thumbnail_path | TEXT | 本地文件 |
| keywords | JSON | 来自 alt_text，入库即定 |
| graph_score / visual_score / final_score | REAL | 评分 |
| status | TEXT | pending/selected/replaced/rejected |
| created_at | TEXT | ISO 8601 |

去重：至少同时考虑**规范化 URL**（去 query/hash、小写 host）与**内容 checksum**（sha256 前 16 hex）。

### Pack（表 `daily_packs`）与 PackImage（表 `pack_images`）

| Pack 字段 | 说明 |
|---|---|
| id | TEXT PK，**全局唯一**：`uuid4().hex[:16]`（新纪录），禁止 `pack-001` 类跨日期复用 |
| date | 所属日期 YYYY-MM-DD（不是主键成分） |
| theme / title_options / caption | 内容 |
| status | draft/selected/rejected/published |
| created_at / selected_at / published_at | ISO 8601（published_at 唯一发布时间） |
| dir_path | **新增**：导出目录相对路径（posts/<date>/<slug>），与 id 分离 |

| PackImage 字段 | 说明 |
|---|---|
| pack_id + image_id | 复合 PK，FK 到 daily_packs/images |
| position | 1–9 |
| user_action | approved/replaced/rejected |

**换图原子性**：换图必须同时更新 ①图片文件/引用 ②pack_images.image_id ③position ④来源 ⑤图注。禁止只改文件不改库。

### PublishRecord（表 `publish_history`）与 MetricsSnapshot（表 `metrics_snapshots`，新增）

- `publish_history.id` PK；`pack_id` FK→daily_packs（legacy 行可为文件包 slug，前缀 `slug:` 标识，见 §4）；`published_at` ISO 8601。
- **MetricsSnapshot** 承接窗口数据：

| 字段 | 说明 |
|---|---|
| id | PK |
| publish_record_id | FK→publish_history |
| window | `24h` / `48h` / `manual` |
| likes / saves / comments / shares | 该窗口累计值 |
| recorded_at | ISO 8601 |

**读取口径**：取最大可用窗口（manual > 48h > 24h）的累计值；不同窗口**不得相加**。写入时先读取完整记录做 merge，再计算。

### JobRun（表 `job_runs`，新增）— 调度器运行态

| 字段 | 说明 |
|---|---|
| id | PK |
| job_name | crawl / image_download / pack_generation … |
| scheduled_for / started_at / finished_at | ISO 8601 |
| status | pending/running/succeeded/partial/failed/skipped |
| summary_json | 结构化摘要（计数/错误，脱敏） |

调度器“今天是否已跑过”以本表为准，**禁止依赖进程内存**。

## 2. 状态枚举（大小写敏感，迁移必须合法）

- SourceStatus: pending / approved / rejected / deferred
- CrawlRunStatus: pending / running / succeeded / partial / failed
- IngestionStatus: discovered / downloaded / failed / skipped
- ImageStatus: pending / selected / replaced / rejected
- PackStatus: draft / selected / rejected / published
- JobRunStatus: pending / running / succeeded / partial / failed / skipped

## 3. 数据所有者

| 数据 | 权威所有者 | 其他副本角色 |
|---|---|---|
| 发布状态、草稿、选图顺序、反馈指标 | `daily_packs` / `pack_images` / `publish_history` / `metrics_snapshots` | localStorage=UI 缓存；posts/*.txt=导出快照 |
| 图片与溯源 | `images` + `ingestion_items` | data/images/ 文件=文件实体 |
| 抓取运行态 | `crawl_runs` + `ingestion_items` | runs/loop_*/output.jsonl=原始日志（可重建 backlog） |
| 发布登记 | `publish_history` + `metrics_snapshots` | data/publish_log.json=本地镜像（迁移中） |

## 4. 已确认风险与修复对照（2026-09-08 盘点）

| # | 风险 | 修复 |
|---|---|---|
| 1 | download_images 写 images 时 source_id 全空（DB 实测 1652/2421 为空） | 按 page_url 最长前缀匹配 sources.url 解析；失败→event_log `ingest.source_unresolved` |
| 2 | download_images `--max` + 只读最新 loop → 旧批次剩余 URL 永久失去默认处理 | ingestion_items 持久 backlog（Phase 2 daily_ingestion 统一消费） |
| 3 | image_urls/alt_texts 两个数组按下标配对 | crawl 输出改 `images:[{url,alt}]`；读侧兼容旧格式 |
| 4 | pack_id 跨日期重复（pack-001）；目录名与 DB id 混用 | daily_packs.id=uuid 全局唯一；新增 dir_path；QUEUE 文件包 slug 仅是路径 |
| 5 | published_at 混用 time/date | queue_server 归一 `time→published_at`；全链路只认 published_at |
| 6 | queue_server 反馈镜像把 24h+48h 相加 | 48h 存在则用 48h（最新窗口优先），绝不相加 |
| 7 | 换图只改文件不改库 | daily.py 新增 DB 权威换图端点（PUT /{pack_id}/images/{position}），同步 pack_images/image_id/图注 |
| 8 | generate_publish_packs localStorage 当权威发布状态 | 模板加载时先 GET /publish-entries 取服务端状态，localStorage 仅离线兜底缓存 |
| 9 | 迁移不可控 | scripts/migrations.py 幂等 + 迁移报告；preflight 必跑 |

## 5. 唯一采集入口（Phase 2 实现）

`python3 scripts/daily_ingestion.py --resume`：preflight（锁/磁盘/DB 可写/迁移）→ crawl → persist discovered → download backlog → normalize + source attach → 至多一个主 pack → 写 `data/daily_ingestion_status.json`。所有阶段状态与计数落 `crawl_runs`。
