# moodboard. — 路线图

> 当前定位：**个人视觉采样系统 → 编辑品牌（路线 A，策展人模式）**
> Goal `20260823-015245-moodboard-editor-brand-75095`（approved 2026-08-23），对标 Hidden.NY / JJJJound / 小红书 KOC
> 核心原则：**机器只做候选，人做策展（挑选 + 观点）；单一渠道手动发布；先观众后变现**

---

## 已完成

- [x] 知识图谱 + NetworkX 打分、CLIP visual embedding、AI 页面实体提取
- [x] 多源爬取（88 源，400 req/h × 4h 每日）、link_sources.json → DB 同步
- [x] daemon 调度 + launchd 保活（daily_source_brief / trend_report / crawl / backup / source_healthcheck）
- [x] 候选流：pack_generation `--count 1 --pack-size 9`（每班一包 9 图，QUEUE.html 人工审图）
- [x] 死链清理（3 条 404）+ DB dead rows 清理（96 源）
- [x] 全源 healthcheck 周期化（每周一 11:00，基线 69/88 healthy）
- [x] 反馈精准调权（CLIP 匹配 concept + AI 解释）

---

## 主线：编辑品牌（2026-08-23 起）

**商业里程碑**（Goal 验收标准）：

- [ ] 首篇人工策展笔记本周内发布（小红书新号，正文为本人观点）
- [ ] 连续 4 周、每周 ≥3 篇人工发布
- [ ] 4 周：粉丝 ≥500 且 1 篇赞藏 ≥100
- [ ] 12 周：粉丝 ≥3,000
- [ ] 24 周：粉丝 ≥10,000（KOC B 级商单线 1000–3000/条）

**周节奏**：每天候选流自动产出 → 人挑图写观点 → 手动发；周一 trend_report（编前会纪要化）+ healthcheck 自动跑。

## 支线（非目标，明确冻结）

- ❌ 自动发布（永久，账号封禁教训）
- ❌ playwright 反爬 / 400 req/h 验证 / parser 回测（机器侧已够用）
- ❌ 推荐引擎 + 搜索（继续 DEFERRED）

## 未来项（变现验证后另立项）

- A. 发布反馈闭环（手动观察互动数据，不自动回抓）
- B. 跨源趋势检测 → **编前会纪要**（trend_report 已周跑，待人工化改造）
- C. 原创内容生成（AI remix / taste note）
- D. Taste 演化仪表板
- E. Product Seed Pipeline（`taste_ip_system.md` 产品种子，12 个月后）
- F. 多平台格式适配（先单渠道跑通）
