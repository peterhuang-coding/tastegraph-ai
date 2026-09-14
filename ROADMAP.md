# moodboard. — 路线图

> 更新于 2026-09-14。当前定位：**个人视觉采样系统 → 编辑品牌（策展人模式）**
> 核心原则：**机器只做候选，人做策展（挑选 + 观点）；单一渠道手动发布；先观众后变现**
> 功能投资与验收门槛见 [`docs/product-feature-gates.md`](docs/product-feature-gates.md)。

---

## 已完成

- [x] 知识图谱 + NetworkX 打分、CLIP visual embedding、AI 页面实体提取
- [x] 多源爬取（88 源，400 req/h × 4h 每日）、link_sources.json → DB 同步
- [x] daemon 调度 + launchd 保活（daily_source_brief / trend_report / crawl / backup / source_healthcheck）
- [x] 候选流：基于选题/来源页归组，每组至多 9 图，进入人工审核
- [x] 候选跨批次去重：活跃图集按 ID、URL、内容 SHA256 占位，明确拒绝后释放
- [x] 候选队列背压：活跃待审最多 5 组，定时任务只补缺口，满队列正常跳过
- [x] 死链清理（3 条 404）+ DB dead rows 清理（96 源）
- [x] 全源 healthcheck 周期化（每周一 11:00，基线 69/88 healthy）
- [x] 反馈精准调权（CLIP 匹配 concept + AI 解释）
- [x] 发布事实与运营判断分离：publication observation、image/pack editorial、event log
- [x] 健康页运行证据：今日 job/crawl、backlog、重试队列、候选积压、最近备份
- [x] 数据覆盖审计：来源、指纹、溯源、运营标注、出处核验、发布观测

---

## 主线：编辑品牌（2026-08-23 起）

**商业里程碑**（Goal 验收标准）：

- [ ] 首篇人工策展笔记本周内发布（小红书新号，正文为本人观点）
- [ ] 连续 4 周、每周 ≥3 篇人工发布
- [ ] 4 周：粉丝 ≥500 且 1 篇赞藏 ≥100
- [ ] 12 周：粉丝 ≥3,000
- [ ] 24 周：粉丝 ≥10,000（KOC B 级商单线 1000–3000/条）

**周节奏**：Mini 常驻采集并把候选队列补到最多 5 组 → 人挑图写观点 → 手动发；周一 trend_report（编前会纪要化）+ healthcheck 自动跑。

## 当前主线：MVP 证据闭环

- [ ] 连续 7 天验证 Mini always-on：无 backlog 丢失、无重复候选、备份可用
- [ ] 将候选审核、导出、发布登记收口为单一运营 Inbox
- [ ] 用 5 个真实选题完成推荐同池 A/B 人工评审
- [ ] 记录每篇找图耗时、替换张数、前 20 张可用率
- [ ] 连续 4 周、每周 ≥3 篇人工发布，并登记 24h/48h 累计表现

推荐排序的升级门槛：质量不下降，且人工选图耗时减少约 30%。达到门槛前，不修改默认权重。

## 支线（非目标，明确冻结）

- ❌ 自动发布（永久，账号封禁教训）
- ❌ playwright 反爬 / 400 req/h 验证 / parser 回测（机器侧已够用）
- ❌ 默认推荐权重的无证据调整（仅允许离线对照实验）
- ❌ 公共 Feed、多人权限、Marketplace
- ❌ Mini 自动登录、自动发布或自动互动

## Feature Gate（按证据启动）

- P1：编辑助理草稿（人工审核后生成，不自动发布）
- P1：栏目引擎（累计至少 12 篇真实发布后）
- P1：内容实验账本与客群信号卡（发布观测稳定后）
- P1：来源 ROI（来源与发布链路覆盖率达标后）
- P2：语义档案搜索、Zine / Guide、Product Seed、Taste Evolution、Guest Editor
- 延后：多平台格式适配（单一渠道闭环跑稳后）
