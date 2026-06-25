# TasteGraph AI — 路线图 & 待办

> 当前定位：自动化爬取 + 知识图谱推荐 Moodboard 引擎  
> 下一步：从「内容搬运工」→「个人品味编辑系统」

---

## 已完成

- [x] 知识图谱 + NetworkX 打分
- [x] 多源爬取（Are.na, Unsplash, Web scraper, 27 sources）
- [x] 并发抓取（5 并发, 50 张/源）
- [x] link_sources.json → DB 自动同步
- [x] CLIP visual embedding 接入打分
- [x] AI 页面实体提取 → 自动建图
- [x] 新源 exploration bonus
- [x] Pipeline 自动 save graph
- [x] 反馈精准调权（CLIP 匹配 concept + AI 解释）

---

## A. 发布反馈闭环 ← **下一个做**

> 最小成本最大收益。把小红书互动数据喂回 taste graph 自动调权重。

**具体任务：**
- [ ] 发布后 24h/48h 自动回抓帖子数据（赞/藏/评/分享）
- [ ] 高互动图片 → auto boost 对应 concept/source 权重
- [ ] 低互动图片 → 降权
- [ ] 每周生成「什么管用」报告（top concepts, top sources, top visual patterns）

---

## B. 跨源趋势检测 ← **和 A 一起做**

> 加一个 AI prompt 就能从搬运工变成编辑。

**具体任务：**
- [ ] 每周一次：所有源的 title/description → AI 分析共同主题
- [ ] 输出：什么在上升、什么在消退、什么值得单独写一篇
- [ ] 产出「编辑判断」而非 moodboard pack — 像杂志编前会纪要

---

## C. 原创内容生成

**具体任务：**
- [ ] AI remix：CLIP 找跨源视觉相似图 → AI 写原创 taste note → 排版卡片
- [ ] Taste object 产品草稿：高频物件 → AI 生成概念图 + 文案
- [ ] 「如果我来做 XX」系列：基于 graph 数据生成产品假设

---

## D. Taste 演化仪表板

> 可视化你的品味变化轨迹。

**具体任务：**
- [ ] 记录 concept/source/mood 每月权重变化
- [ ] 前端加一个「品味日历」或趋势线
- [ ] AI 每周自然语言总结：「你这个月对 X 兴趣在降，对 Y 在升」

---

## E. Product Seed Pipeline

> taste_ip_system.md 的产品路线图，代码实现。

**具体任务：**
- [ ] 自动识别高频物件 → 标记「有产品潜力」
- [ ] 生成一页纸产品 brief（材质/颜色/参考/定位/定价建议）
- [ ] 找相似产品参考（MUJI 的 XX 系列、某设计师的 YY 作品）

---

## F. 多平台格式适配

**具体任务：**
- [ ] 小红书：9 图 + caption（已有）
- [ ] Instagram：1 图 + 英文一句
- [ ] 公众号/Substack：长文 + 排版
- [ ] Zine/PDF：印刷排版自动导出

---

## 边缘想法（待评估）

- 自动关注/发现小红书同品味账号
- 定时自动发布（定好内容 → 每天固定时间发）
- 品味匹配社交（找 taste compatible 的人/品牌合作）
- 竞品监控（同赛道的号最近在发什么）
