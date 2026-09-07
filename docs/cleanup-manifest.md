# 清理冗余清单（Cleanup Manifest）— TasteGraph 安全改造 Phase 5

> 2026-09-08 · doc-phase5 产出。**本文件只盘点，不执行任何删除/移动/修改。**
> 分类基准：worktree 分支 `task/secure-ingestion-night`（含 P0-P2 及 P3 进行中改动）**合并后的未来状态**；主 checkout `moodboard-hidden-ny-jjjjound`（main @ d0c12cc）为只读参照，其运行态差异在各项注明。
> 审查时未读取任何 cookie/.env/state 文件内容；敏感项只列路径与 Git 跟踪状态。

## 分类语义

- **KEEP** — 当前生产/运行路径依赖，或人工内容与历史资料，保留。
- **ARCHIVE** — 有历史/复盘价值但不进运行时：先移到 `archive/`（或打 tag `archive/auto-publish-2026-09`）保留，断开全部入口引用后再从主干删除。
- **DELETE** — 明确生成物 / 敏感文件 / 零引用副本：退 Git 跟踪（`git rm --cached`，必要时加 .gitignore），磁盘文件去留按各项注明。
- **UNKNOWN** — 需人工确认，**禁止删除**。

## 统计

| 分类 | 项数（条目，按组计） |
|---|---|
| KEEP | 23 |
| ARCHIVE | 21 |
| DELETE | 16 |
| UNKNOWN | 7 |

> KEEP 含生产链路、人工内容与仓库外现役运行项（D 组 4、E 组 15、F7、G1-G3）；ARCHIVE 全部为发布自动化及其试验期衍生代码/文档（B 组）；DELETE 含 3 个凭证/登录态项、12 个生成物退跟踪项、1 个仓库外 profile 项。

---

## A. 敏感 / 登录态文件（最高优先级）

| # | 路径 | 分类 | 引用证据 / 跟踪状态 | 恢复 / 回滚与动作 |
|---|---|---|---|---|
| A1 | `modules/xhs_publisher/cookies.json`、`modules/xhs_publisher/cookies.state.json` | **DELETE** | 分支已退跟踪（commit e7b4611，.gitignore:54-55 覆盖）；但 **main 与 origin/main 仍跟踪**（`git ls-tree -r main` 命中）；历史 commit `7e1a220` 含凭证。发布代码读取方：`modules/xhs_publisher/publisher.py`、`config.py:13`（均在拟归档模块内）。 | 合并门禁：确认合并后 main/origin 不再跟踪。**Git 历史仍含凭证 → 小红书账号/登录态必须轮换**（leader 已通报）。本机文件在轮换完成前由老板人工决定删除；无需恢复（轮换后重新登录产生新文件，且新方案不自动登录）。 |
| A2 | `data/xhs_cookies.json` | **DELETE** | 同 A1：分支未跟踪（.gitignore:56），main/origin 仍跟踪，历史含凭证。代码读取方仅旧发布链路（`scripts/auto_feedback.py:195` 等，均拟归档）。 | 同 A1：合并后确认退跟踪 + 账号轮换。 |
| A3 | `tmp/login_status_cache.json` | **DELETE** | **分支与 main 均仍跟踪**（`git ls-files tmp/` 命中；.gitignore 有 `tmp/` 但跟踪先于 ignore）。唯一引用：`xhs_publisher/cdp_publish.py:176`（拟归档）。内容为登录态布尔缓存（124B，未读内容）。 | `git rm --cached tmp/login_status_cache.json`（ignore 规则已存在）；本机文件可直接删，cdp_publish 归档后无任何写入方。恢复：Git 历史（无价值）。 |
| A4 | `.env`（主 checkout 根目录；worktree 中不存在） | **UNKNOWN** | **从未被 Git 跟踪**（`git ls-tree -r main` 无；.gitignore `*.env` 覆盖；无历史提交）。敏感但未泄露进仓库。 | 无需 Git 动作。请老板确认其中 API key 是否随账号轮换一并更换（未读内容）。 |

## B. 自动发布代码（ARCHIVE：断开入口后删）

> 自动发布永久不属于目标。以下代码**先 ARCHIVE 不删**；P4 断开入口引用后，可随 tag 从主干删除。所有文件均可从 Git 历史恢复（建议归档时打 tag `archive/auto-publish-2026-09`）。

| # | 路径 | 分类 | 引用证据 | 恢复 / 备注 |
|---|---|---|---|---|
| B1 | `xhs_publisher/`（整目录 8 个 .py：cdp_publish、publish_pipeline、chrome_launcher、account_manager、feed_explorer、image_downloader、run_lock、utils） | **ARCHIVE** | 被生产路径引用的只剩：`taste_graph_ai/cdp_adapter.py:16`（subprocess 调 cdp_publish.py）、`scripts/auto_publish.py:56,99,173`、`scripts/auto_feedback.py:42`、`scripts/check_selectors.py:38,43`。以上引用方全部在本清单归档/403 门控范围内。operations.md:137 已标注「整套技术栈封存」。 | 打 tag 后整目录移入 `archive/xhs-auto-publish/` 或直接删。注意：Chrome 多账号 profile 写在仓库外（`~/.../XiaohongshuProfile/`、`account_manager.py:28` CONFIG_DIR accounts.json），见 G4。 |
| B2 | `modules/xhs_publisher/publisher.py`、`main.py`、`single_composer.py` | **ARCHIVE** | publisher.py = Playwright 自动发布器（文件头自述）；main.py = 登录/发布 CLI；single_composer.py **零外部引用**（`rg single_composer` 仅命中自身）。 | 与 B1 同批归档。composer.py/config.py **不归档**（见 K1）。 |
| B3 | `modules/xhs_publisher/README.md`、`CODEX_PROMPT.md`、`FRONTEND_INTEGRATION.md`、`requirements.txt` | **ARCHIVE** | 均为发布模块文档/依赖；随 B2 走。 | Git 历史可恢复。 |
| B4 | `taste_graph_ai/infrastructure/publisher/`（`xhs.py` + `__init__.py`） | **ARCHIVE** | **零引用**：`rg "infrastructure.publisher\|publisher.xhs\|XhsPublisher"` 在 taste_graph_ai/ 全树无任何 import（__init__.py 为空）。是早期 Playwright publisher 的死代码移植。 | 零引用，归档/删除零风险；Git 恢复。 |
| B5 | `taste_graph_ai/cdp_adapter.py` | **ARCHIVE** | 引用方：`api/routes/pipeline.py:137,221`（/cdp-publish 等路由，已 403 门控：pipeline.py:207 `_publish_disabled`）、`scheduler/daily_pipeline.py:96`（仅 `--auto-publish` 显式参数触发）。 | **断开顺序**：P4 删 pipeline.py 的 cdp 路由 + daily_pipeline 的 `--auto-publish` 分支后，本文件方可归档。 |
| B6 | `scripts/auto_publish.py` | **ARCHIVE** | schedule.json:48 `live_post` enabled=false（备注仅提手动命令）；`start.sh` auto-publish 模式直接 exit 1；被 `publish_scheduler.py:89` subprocess 调用（一并归档）；launch_dashboard.sh:41 仅做进程名体检。 | Git 恢复；归档后 schedule.json 备注可删。 |
| B7 | `scripts/publish_scheduler.py` | **ARCHIVE** | schedule.json:45-48 enabled=false；`start.sh:69` 显式拒绝；唯一活引用是 `start_all.sh:182` 的 `--dry-run` 状态展示（start_all 本身归档，见 B15）。 | Git 恢复。 |
| B8 | `scripts/auto_feedback.py` | **ARCHIVE** | schedule.json:51-55 `auto_feedback` enabled=false（2026-07-29 强制关停）；无其他活引用。注意它 import 的 `publish_feedback.py` 是**手动反馈**工具，保留（K6）。 | Git 恢复。 |
| B9 | `scripts/publish_watch.py` | **ARCHIVE** | **零外部引用**（`rg publish_watch` 无命中）。用途：录像老板手动发布操作做回放，属发布自动化衍生工具；产出 `runs/publish-replay/`（本机，未跟踪）。 | Git 恢复；runs/ 下录像人工决定。 |
| B10 | `scripts/publish_playwright.py` | **ARCHIVE** | **零外部引用**。Playwright 上传方案试验稿（文件头自述 alternative to CDP）。 | Git 恢复。 |
| B11 | `scripts/check_selectors.py` | **ARCHIVE** | 仅自身 import `xhs_publisher.chrome_launcher/cdp_publish`（:38,:43），随 B1 失效；无调度/入口引用。 | Git 恢复。 |
| B12 | `scripts/taste_feedback.py` | **ARCHIVE** | **零外部引用**（反馈相关脚本，pipeline.py 周报走的是 publish_feedback.py:418，不是本文件）。 | Git 恢复。如老板认为反馈工具仍要用则升级 UNKNOWN。 |
| B13 | `scripts/hourly_crawl.py` | **ARCHIVE** | **零外部引用**；文件头自述「runs once per CronCreate invocation」的 8/15 一次性小时级探测试验，产出 crawl_logs/tick-*（C6）。已被 `daily_ingestion.py → crawl_loop_6h.py` 正式链路取代。 | Git 恢复。 |
| B14 | `scripts/launchd_daemon.sh` | **ARCHIVE** | **零外部引用**；旧 launchd wrapper（硬编码主 checkout 路径跑 daemon_scheduler.py）。现役 daemon.plist 直接调 python 不经此脚本；P3 新 plist 也不使用。 | Git 恢复。 |
| B15 | `scripts/start_all.sh` | **ARCHIVE** | **零外部引用**（无文档/脚本引用）；旧交互式总控（load plists + publish_scheduler dry-run）。现行入口为 `start.sh`（P0 改造）与 `scripts/launch_dashboard.sh`（operations.md 全文推荐）。 | Git 恢复。 |
| B16 | `scripts/run_xhs_12h_pipeline.py` | **ARCHIVE** | 仅 docs/xhs-12h-pipeline.md 引用（文档随档）；无调度、无其他脚本 import。12h 抓取/发布管道时代产物，读 taste_graph.json/manifests/link_packs 输出 JSONL。 | Git 恢复；对应文档 C8 一并归档。 |
| B17 | `scripts/link_pack_studio.py`、`run_link_pack_studio.sh`、`run_link_pack_studio.command` | **ARCHIVE** | 三者自成一体（.sh/.command 仅 exec studio.py）；无调度引用；属 link_pack 人工打包时代 GUI 工具。它调用的 `link_feedback.py`（B18）随档。 | Git 恢复。link_packs/ 数据本身 KEEP（K15）。 |
| B18 | `scripts/link_feedback.py` | **ARCHIVE** | 唯一引用方 link_pack_studio.py:813（归档）。 | Git 恢复。 |
| B19 | `scripts/link_pack_to_posts.py` | **ARCHIVE** | **零外部引用**（仅自身报错文案提到 run_daily_moodboard）；link_pack→XHS 帖文生成，发布时代产物。 | Git 恢复。 |
| B20 | `scripts/moodboard_fetch.py`、`run_daily_moodboard.py`、`arena_moodboard_fetch.py`、`run_arena_moodboard.sh` | **ARCHIVE** | 内部互相引用（run_daily→moodboard_fetch；run_arena.sh→arena_fetch），无调度/生产入口；早期抓取脚本，正式链路为 crawl_loop_6h.py。 | Git 恢复。 |
| B21 | `docs/xhs-12h-pipeline.md` | **ARCHIVE** | 文档对象（run_xhs_12h_pipeline.py 等）全部归档；留存作历史复盘。 | 随 docs 保留亦可，标记为历史文档、勿按其操作。 |

**入口断开清单（P4 执行，删 B 组代码前必须完成）**：
1. `taste_graph_ai/api/routes/pipeline.py:137,183-266` — cdp-publish 系列路由（已 403，移除代码）。
2. `taste_graph_ai/scheduler/daily_pipeline.py:93-110` — `--auto-publish` 分支。
3. `taste_graph_ai/api/routes/daily.py:232` `auto_publish_pack` 端点（保留同文件 `/export` 与 `/publish` 手动登记端点）。
4. `scripts/pipeline.py` 确认无 cdp 依赖（经查仅 import queue_server 与 clip，无 cdp）。
5. `config/schedule.json` 删 `live_post`、`auto_feedback` 两条 disabled 任务及 auto_publish 备注（P3 schedule 审计时做）。

## C. 调试产物 / 运行生成物（DELETE：退 Git + ignore，磁盘可清）

> 共同恢复方式：均为生成物，`git checkout -- <path>` 可从历史取回；功能上可由对应脚本重新生成。.gitignore 大部分规则已存在，以下多为「跟踪先于 ignore」的历史遗留，退跟踪即与既有意图对齐。

| # | 路径 | 分类 | 引用证据 | 恢复 / 备注 |
|---|---|---|---|---|
| C1 | `modules/xhs_publisher/debug_*.png`（18 张，已核实 `git ls-files` 计数） | **DELETE** | **零引用**：`rg "debug_.*png"` 全仓无代码/文档引用；为发布调试期手工截图。 | `git rm --cached`（建议加 `modules/xhs_publisher/debug_*.png` 到 .gitignore）；本机文件可直接删。Git 历史恢复。 |
| C2 | `modules/xhs_publisher/mock_data/`（9 张 jpg） | **DELETE** | 仅被该模块自身 README/main.py 文档字符串引用为 compose 测试输入；文件名是内容 hash，与 data/images 同源样本重复。 | 随发布模块归档时移除；Git 恢复。 |
| C3 | `modules/xhs_publisher/exports/`（6 张 moodboard/single PNG） | **DELETE** | composer 输出目录（`config.py:24` EXPORTS_DIR）；历史生成图，无引用。注意现网 FastAPI 挂载的是 **data/exports**（K3 注），此目录产物无人 serve。 | 退跟踪+ignore；本机可删；Git 恢复。 |
| C4 | `data/exports/moodboard_*.png`（4 张，已跟踪） | **DELETE** | 生成物；.gitignore 已含 `data/exports/`（规则在跟踪之后）。FastAPI `server.py:55` 挂载该目录，运行时由 composer 重新产出。 | `git rm --cached`；本机可删；重新导出即恢复。 |
| C5 | `data/clip_embeddings.json`（18.6MB，已跟踪） | **DELETE** | 唯一引用 `services/clip.py:21`（CLIP 向量缓存，缺失时自动重建）；调用方 web.py/feedback.py/images.py/generate_publish_packs.py 均惰性加载。.gitignore 已列。 | `git rm --cached`（**本机文件保留**，重建成本高）；仓库体积立即 -18MB。 |
| C6 | `data/probe-2026-08-15.py`、`data/probe-results-2026-08-15.json` | **DELETE** | **零引用**；脚本自述一次性探测、输出原本写 `$CLAUDE_JOB_DIR/tmp`（probe-2026-08-15.py:43），仓库内副本是误沉淀。 | 退跟踪+本机删；Git 恢复。 |
| C7 | `data/source-healthcheck-2026-08-15.json` / `.md` | **DELETE** | 8/15 一次性健康检查；周期化后由 `scripts/source_healthcheck.py` 每周生成（schedule.json 已启用）；.gitignore `data/source-healthcheck-*` 已覆盖（后续 08-23/08-24/08-31/09-07 各期均未跟踪）。 | `git rm --cached`；本机留作历史亦可；Git 恢复。 |
| C8 | `data/trend-report-2026-07-13.json` / `.md` | **DELETE** | 旧周报；`trend_report.py` 每周一生成（schedule 已启用），queue_server `/trend-report` 只取最新一份；.gitignore `data/trend-report-*` 已覆盖（07-25 起各期未跟踪）。 | `git rm --cached`；Git 恢复。 |
| C9 | `data/sources.html`（26KB，已跟踪） | **DELETE** | 生成物：`source_dashboard.py:16` OUTPUT；`queue_server.py:335` 调 source_dashboard.build 现建、:355 重定向到该文件。 | `git rm --cached` + 建议加 ignore；删除后访问工作台会自动重建。注意与 `posts/<date>/SOURCES.html`（daily_source_brief 产物，KEEP 链路）不是同一文件。 |
| C10 | `tmp/playwright_upload_1.png` | **DELETE** | 调试上传截图；零引用；.gitignore `tmp/` 已覆盖。 | `git rm --cached` + 本机删。 |
| C11 | `config/schedule.json.bak` | **DELETE** | schedule.json 的手工备份；零引用；Git 历史已完整保留 schedule.json 演变。 | `git rm --cached` + 本机删。 |
| C12 | `scripts/__pycache__/`、各 `__pycache__/`（磁盘） | **DELETE**（本机清理） | .gitignore 已覆盖，未跟踪；纯字节码缓存。 | 直接 `find . -name __pycache__ -prune -exec rm -rf {} +`，无恢复需要。 |

## D. 数据双写 / 职责重复（KEEP + 收敛说明，不是删除对象）

| # | 路径 | 分类 | 证据与关系 | 处理建议 |
|---|---|---|---|---|
| D1 | `data/taste_graph.db`（+ `-wal`/`-shm`，主 checkout 运行中） | **KEEP** | 数据契约唯一权威事实源；migrations v1-8 已落地；P3 v9 进行中。worktree 内无 db（测试用 /tmp 合成副本）。 | 不动。 |
| D2 | `data/taste_graph.json`（273KB，已跟踪；.gitignore 已列但跟踪在先） | **KEEP** | 并非 D1 的副本：它承载**品味图谱节点/边**（concepts），由 `graph/taste_graph.py:508 save()` 写出，调用方 container.py:45、api/routes/graph.py（6 处）、scheduler/daily_pipeline.py:121；读方包括 trend_report.py:30、daily_source_brief.py:21、backup.py:27、health_check.py:197。SQLite 侧无 graph 表。 | 现状双轨：实体在 DB、图谱在 JSON。**契约目标是 DB 单一权威**，图谱迁移属后续阶段；当前退跟踪会破坏 backup/health_check，故 KEEP 并跟踪现状。建议未来迁移后转为 ignored 导出。 |
| D3 | `data/publish_log.json`（主 checkout 磁盘，2 字节 `[]`；.gitignore 已列） | **KEEP**（运行时镜像） | `queue_server.py:25,395,453` 读写（人工发布登记 UI），并在 :470-485 把指标镜像 POST 到 FastAPI `/api/v1/feedback/publish-metrics` → 落 `publish_history`/`metrics_snapshots`（DB 权威）；`generate_publish_packs.py:86` 读它判已发状态。 | 契约 §3 已定性为「本地镜像（迁移中）」。P4 工作台收口到 8787 后，登记直接写 DB、前端改读 `/publish-entries` 的 DB 实现，再退役此文件。**现在删会断 QUEUE 发布日志 UI**。 |
| D4 | `scripts/queue_server.py`（:8765）vs FastAPI `taste_graph_ai/server.py`（:8787） | **KEEP**（P4 后评估退役） | 不是重复而是两层：8787=图谱/API+新静态工作台（taste_graph_ai/static/）；8765=人工策展工作台（QUEUE.html、posts/ 静态、换帧、剪贴板 osascript、DeepSeek 图注、publish-log、/api 反代 8787）。`scripts/pipeline.py:359-401` 同时起两者。 | P4 把 8765 的人工策展能力搬上 8787 后再退役 queue_server；其中 open-file/open-folder/copy-image/file:// 等远程无效动作 P4 直接移除。 |

## E. KEEP — 生产链路 / 人工内容 / 基础资料

| # | 路径 | 分类 | 证据 |
|---|---|---|---|
| K1 | `modules/xhs_publisher/composer.py`、`config.py` | **KEEP** | `taste_graph_ai/api/routes/daily.py:24` import MoodboardComposer，:180-186 `/export` 端点实际调用（PIL 3x3 拼图，纯本地图像合成，非发布）。**注意分歧**：composer 写出目录是 `modules/xhs_publisher/exports/`（config.py:24），而 FastAPI 挂载 serve 的是 `data/exports`（taste_graph_ai/config.py:29、server.py:55）——导出 URL `/exports/<file>` 可能 404，请 P4 核实并统一到 data/exports（可设 XHS_EXPORTS_DIR 或迁 composer）。 |
| K2 | `scripts/queue_server.py`、`scripts/pipeline.py`、`scripts/daemon_scheduler.py`、`scripts/daily_ingestion.py`、`scripts/migrations.py`、`scripts/download_images.py`、`scripts/generate_publish_packs.py`、`scripts/crawl_loop_6h.py` | **KEEP** | 现网服务/调度/采集主链路（pipeline.py:359-401 起双服务；daemon_scheduler 由 launchd 托管；daily_ingestion 为契约 §5 唯一采集入口；crawl_loop_6h 被 daily_ingestion.py:234 与 pipeline.py:59 调用）。 |
| K3 | `taste_graph_ai/`（除 B4/B5 外全部）、`taste_graph_ai/static/` | **KEEP** | FastAPI 应用本体；server.py 挂载 /images、/exports、/ 静态工作台。 |
| K4 | `scripts/auto_deploy.py` | **KEEP** | **现役部署机制**：仓库外 `~/Library/LaunchAgents/tastegraph-autodeploy-bootstrap.py:29-31` 每 15 分钟调它，watch `feat/curation-workbench` → ff-merge main → push origin/main。今晚合并部署依赖它，勿动。 |
| K5 | `scripts/source_dashboard.py`、`daily_source_brief.py`、`trend_report.py`、`backup.py`、`cleanup_stale_data.py`、`health_check.py`、`audit_crawl.py`、`crawl_status.sh`、`run_24h_crawl.sh`、`launch_dashboard.sh`、`start.sh` | **KEEP** | schedule.json 中 enabled 任务对应脚本 + operations.md 全文推荐的运维入口。 |
| K6 | `scripts/publish_feedback.py`、`scripts/publish-log.html` | **KEEP** | 手动反馈闭环（非自动发布）：pipeline.py:418 周报、queue_server.py:380 serve publish-log.html；数据落 DB metrics_snapshots。 |
| K7 | `config/schedule.json` | **KEEP** | daemon_scheduler 唯一调度配置；P2 已合并为单采集任务，发布任务 enabled=false（待 B 组归档时删条目）。 |
| K8 | `data/source_yield.json`、`data/voice_examples.json`、`data/trend_decisions.json` | **KEEP** | 分别被 services/images.py:44,55、services/voice.py:23、api/routes/trend.py:31 读取。 |
| K9 | `data/events.log`、`data/backups/`、`data/logs/`、`data/images/`、`data/crawl_stealth_state.db`、`runs/`（主 checkout 磁盘） | **KEEP**（运行时，已 ignore） | 事件日志/备份/日志/图片实体/stealth 状态/抓取运行目录；.gitignore 已覆盖，均未跟踪。baseline 备份在 `../backups/tastegraph-20260908-baseline`。 |
| K10 | `link_sources.json`（根）、`taste_memory.json`、`taste_ip_system.md`、`VISION.md`、`README.md`、`ROADMAP.md` | **KEEP** | seed_loader.py:20,24 加载 link_sources/taste_memory 进图谱；项目身份文档。 |
| K11 | `docs/data-contract.md`、`docs/operations.md`、`docs/voice.md`、`docs/monetize_plan.md` | **KEEP** | 现行契约/手册（operations.md 待 P3 更新）。 |
| K12 | `posts/`（163 个跟踪文件：2026-06-25/06-29/07-06/07-09/07-10 各包 QUEUE.html + 文案 + image.jpg） | **KEEP** | **人工历史发布内容与发布记录**，按规则无明确证据不得删。注意 .gitignore 含 `posts/` 但这些文件跟踪在先——它们是刻意留存的历史快照，勿退跟踪。新产生的 posts/ 走 ignore（运行导出）。 |
| K13 | `research/`（20 个跟踪文件，aesthetic-os 研究文档） | **KEEP** | 知识库；operations.md:206 列明。 |
| K14 | `link_packs/`（8 个 .txt，2026-04-17~04-26） | **KEEP** | 人工整理的每日链接（人工内容）；读取方 run_xhs_12h_pipeline/link_pack_studio 虽归档，但文件本身是人工资料。 |
| K15 | `.gitignore` | **KEEP** | P0 已加固凭证/运行产物规则；C 组退跟踪后建议补 `modules/xhs_publisher/debug_*.png`、`modules/xhs_publisher/exports/`、`modules/xhs_publisher/mock_data/`、`data/sources.html`、`config/*.bak`。 |

## F. UNKNOWN — 需人工确认（禁止删除）

| # | 路径 | 分类 | 证据与疑点 | 建议确认点 |
|---|---|---|---|---|
| F1 | `2026-04-09/`、`2026-04-11/`、`2026-04-12/`、`2026-04-13/`、`2026-04-15/`、`2026-04-16/`、`2026-04-17/`（共 37 个跟踪文件） | **UNKNOWN** | 四月起号期目录：含人工每日 .txt 笔记，以及 `2026-04-11/rejected_placeholders/` 15 张 stock 占位图（文件名自述 placeholder）。代码零引用；被 docs/xhs-12h-pipeline.md 列为历史数据源。 | .txt 人工笔记建议 KEEP/移 research；rejected_placeholders 疑似可删 stock 图——**需老板确认**后再动。 |
| F2 | `manifests/2026-04-09.json`、`2026-04-11.json` | **UNKNOWN** | AI 生成的四月主题清单；仅归档链路（run_xhs_12h_pipeline）与文档引用。 | 确认是否随 research 归档保留。 |
| F3 | `data/new_sources_check.json`（6.7KB，已跟踪） | **UNKNOWN** | **零代码引用**（无读无写）；7/29 时间戳，疑为一次性源审计产物。 | 老板确认无参考价值后按 C 组方式退跟踪。 |
| F4 | `../moodboard-tg-crawl-opt/`（仓库外 stale 完整副本，独立 worktree，分支 `feat/crawl-opt` @ 878e456，最后修改 8/16） | **UNKNOWN** | CLAUDE.md 已点名 stale 副本。**已核实 878e456 已并入 main**（`git branch --contains 878e456` 含 main；main 上有 merge commit「merge feat/crawl-opt → main」）。 | 内容无未合并提交，理论可安全 `git worktree remove` + `git branch -d feat/crawl-opt`；但删目录不可逆，**请老板/leader 人工执行确认**。 |
| F5 | prunable worktree `/Users/peter_mini/.claude/jobs/049eedb5/tmp/moodboard-worktree`（分支 feat/curation-workbench） | **UNKNOWN** | `git worktree list` 标 prunable（任务临时目录已不存在）。 | `git worktree prune` 即可清理登记项；feat/curation-workbench 分支是**现役部署跟踪分支，勿删**。 |
| F6 | `~/Library/LaunchAgents/com.user.tastegraph.daemon.plist`（仓库外，只读列出） | **UNKNOWN**（退役待人工） | 现役 loaded（pid 90294，KeepAlive），跑主 checkout 的 daemon_scheduler.py + schedule.json（发布任务 disabled，实际只跑采集/备份类）。与 P3 新单 plist 职责重复。 | P3 新 plist 就绪并验收后，由老板手动 `launchctl unload` 旧 plist 并归档文件；**本任务不 load/unload**。 |
| F7 | `~/Library/LaunchAgents/com.user.tastegraph.autodeploy.plist` + `tastegraph-autodeploy-bootstrap.{py,sh}`（仓库外） | **KEEP**（暂）→ 切后复核 | 现役 loaded，每 900s 触发 auto_deploy（见 K4）。今晚合并部署靠它。 | 合并部署完成、新调度稳定后再评估是否保留 auto-deploy 机制。 |

## G. 仓库外运行时痕迹（盘点，不在仓库内操作）

| # | 路径 | 分类 | 证据 | 动作 |
|---|---|---|---|---|
| G1 | `~/Library/Logs/TasteGraph/`（daemon.log/err、autodeploy.out/err） | KEEP（运行时） | 两个 plist 的 StandardOut/ErrorPath。 | 日志轮转由 P3 覆盖。 |
| G2 | 主 checkout `data/backups/`（含 20260908-baseline） | KEEP | backup.py 产物 + P0 基线。 | 不动。 |
| G3 | `runs/publish-replay/`、`runs/stealth_*`、`runs/crawl_*.log`（主 checkout，未跟踪） | KEEP（运行日志） | publish_watch/stealth crawl/24h crawl 产物；health_check.py:171-184 读 runs/stealth_*。 | 保留；磁盘空间紧张时按轮转策略清旧日志。 |
| G4 | Chrome 多账号 profile（`~/XiaohongshuProfile/` 或 LOCALAPPDATA 路径，account_manager.py:28）、`accounts.json`（CONFIG_DIR） | **DELETE 待轮换后**（人工） | xhs_publisher/account_manager.py 的多账号登录态存储，在仓库外。 | 账号轮换时由老板人工删除本机 Chrome profile 与 accounts.json；本清单不触碰。 |

## H. 建议执行顺序

1. **合并门禁前**：本清单 A 组（凭证退跟踪在分支已完成，核对 main/origin 合并结果）+ 老板完成账号轮换。
2. **P4 完成后**：按 B 组「入口断开清单」拆引用 → 打 tag `archive/auto-publish-2026-09` → 归档/删除 B 组代码。
3. **任意时机**（低风险，建议 P3/P4 顺手做）：C 组 `git rm --cached` 退跟踪 + 补 .gitignore；本机清 __pycache__。
4. **人工决策**：F 组逐项确认后再动；G4 随账号轮换处理。
5. **数据双写收敛**（后续阶段，非本次）：D2 图谱 JSON → DB；D3 publish_log.json → DB 登记；D4 queue_server 能力搬上 8787 后退役。

---

*证据采集方式：`rg --files` / `ls` / `rg <symbol>`（全仓，排除 __pycache__、.git）/ `git ls-files` / `git ls-tree -r main|origin/main` / `git log --oneline -- <path>` / `git worktree list` / launchd plist 只读 cat。未读取任何凭证文件内容，未枚举 data/images/。*
