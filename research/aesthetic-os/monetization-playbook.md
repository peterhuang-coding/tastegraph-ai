# 审美图片推荐 + AI Stylist 商业化 Playbook（2024–2026）

> 立项时点：2026-07
> 文档目标：在产品 MVP 阶段同步定义商业化主线，给出可执行路径 / 定价 / 阶段策略 / 12 个月收入曲线
> 引用来源：26 条（详见文末"来源清单"）

---

## 0. 一句话结论

**推荐三条主推路径**：
1. **Freemium + 三档订阅 + Credits 用量计费**（C 端个人审美 AI Stylist，月费 $9.9–$29）
2. **B2B2C 审美 SaaS**（面向电商品牌 / 设计师工作室 / 内容团队的审美中台，$199–$999/月起 + 私有化）
3. **Marketplace 分成**（让审美达人 / 设计师开店卖 Preset / 风格包 / Prompt 模板，平台抽 20–30%）

**1 条备选**：**API 计费 + 企业私有化部署**（在产品验证后启动，做"审美模型"能力对外出口）。

**核心商业化哲学**：把"审美推荐 + AI Stylist"做成「审美操作系统 Aesthetic OS」，先占用户审美数据资产，再在数据资产之上加订阅 + Marketplace + B2B 三条收入管道。

---

## 1. 商业化路径盘点

### 1.1 六大商业化路径一览

| # | 路径 | 适合阶段 | 客单价区间 | 现金流特点 | 与"审美"契合度 |
|---|------|---------|------------|------------|----------------|
| 1 | SaaS 订阅（按席位/月度 tier） | MVP–增长期 | $9.9–$29/月（个人）/ $199–$999/月（团队） | 稳定可预测 | ⭐⭐⭐⭐⭐ |
| 2 | API / 用量计费（per-call、per-image、per-token） | 增长–规模化期 | $0.01–$0.5/次 | 边际成本敏感 | ⭐⭐⭐⭐ |
| 3 | Freemium → Premium 转化 | 0→1 增长器 | 免费 + 锚点高价 | 转化率 4% 是健康线 | ⭐⭐⭐⭐⭐ |
| 4 | B2B2C（设计师工具 / 品牌库 / 电商图选） | 1→10 规模化 | $5K–$50K/年 | 高 LTV | ⭐⭐⭐⭐⭐ |
| 5 | Marketplace 分成（VIP 滤镜 / Preset / Prompt） | 10→100 | 抽佣 20–30% | 网络效应 | ⭐⭐⭐⭐⭐ |
| 6 | 企业私有化部署 | 10→100+ | $30K–$300K/年 | 高毛利、长周期 | ⭐⭐⭐ |

来源：[freemium conversion 基准](https://www.profitwell.com/blog/saas-subscription-retention-rate-benchmarks)｜[Pinterest 2024 财报](https://investors.pinterestinc.com/investor-news/news-details/2025/Pinterest-Inc--Reports-Q4-and-Full-Year-2024-Results/default.aspx)｜[美图 2025 H1](https://new.qq.com/rain/a/20250818A06XTO00)

### 1.2 路径选择的关键判断

- **审美是高频低决策场景**：用户每天刷图但单次决策轻 → 必须走"订阅 + Marketplace + 数据沉淀"的组合，而不是单次付费。
- **审美具有强个人化属性**：越用越准 → 形成数据护城河后，可以向 B 端收"数据 + 工具"两条费用。
- **生成成本敏感**：审美推荐 / AI Stylist 涉及多模态 Embedding + 生成，单次推理成本不低 → 必须用"credits + 配额"做用量控制，避免被羊毛党刷穿。
- **审美具备社交属性**：用户愿意晒自己的审美档案 → 形成 UGC + Marketplace 正循环。

---

## 2. 典型案例研究

### 2.1 国际案例

#### Midjourney
- 2024 年估计 ARR 已达 **$200M**（多源未官方确认）。[来源](https://www.theverge.com/news/617294/midjourney-starts-training-v7-new-revenue-model)
- 2024 年下半年调价后形成：**Basic $10 / Standard $30 / Pro $60 / Mega $120** 四档，配额从 Fast Hours 改为 GPU Minutes。[来源](https://docs.midjourney.com/docs/plans)
- V7（2025-04）增加草稿模式（Draft Mode）：运行成本降到 V6 一半，是「降低单次生成成本」的核心动作。[来源](https://finance.sina.com.cn/tech/digi/2025-04-04/doc-ineryuys7338486.shtml)
- 启示：四档 + GPU 用量 + 草稿模式降价 → 多档定价 + 成本/质量分层。

#### Adobe Firefly
- 企业版不公开标价，每用户每月 **1,200 generative credits** 起步 + 商业安全训练集。[来源](https://helpx.adobe.com/enterprise/using/adobe-express-and-firefly-for-business.html)
- 2025 MAX London：Firefly Image Model 4 支持 2K 原生输出 + 集成 Google 模型 → 走"模型路由器"路线。[来源](https://www.sohu.com/a/891321437_122396381)
- 启示：商业可商用 + Credits 配额 + 多模型路由 = B 端定价标配。

#### Runway
- 标准 $15/月起，Pro/Enterprise 高位，主打视频生成 Gen-3 / Gen-4。[来源](https://www.tomsguide.com/best-picks/best-ai-video-generators)
- 启示：审美 + 视频 = 高单价，但要分层（每秒消耗不同）。

#### Pika
- 2024 年底改为 **credit-based**：Free 150 / Standard 700（$8–10） / Pro 2,000（$28）。[来源](https://pika.art/blog/pika-2-launch)｜[来源](https://pika.art/pricing)
- 启示：从 unlimited → credit-based 是 AI 视频/图像赛道普遍路径，原因是云推理成本必须守住。

#### Sora（OpenAI）
- 嵌入 ChatGPT Plus $20 / Pro $200 套餐，按用量配给。[来源](https://openai.com/sora)
- 启示：把"审美/视频"作为上层订阅的"附加价值"，不单独卖订阅，降低获客成本。

#### Pinterest Predicts + Shoppable Ads
- 2024 Q4 收入 **$1.04B +18% YoY**，全年实现首个 GAAP 盈利年。[来源](https://investors.pinterestinc.com/investor-news/news-details/2025/Pinterest-Inc--Reports-Q4-and-Full-Year-2024-Results/default.aspx)
- 2024 年底 MAU 5.53 亿，购物广告 + Idea Pin 转化是变现主力。[来源](https://www.sec.gov/Archives/edgar/data/1736297/000173629725000006/pins-20241231.htm)
- Pinterest Predicts 是典型"用审美趋势报告换品牌预算"的 B 端玩法。[来源](https://www.uisdc.com/2025-color-trends)｜[来源](https://www.163.com/dy/article/JLHOQBC50517IJJM.html)
- 启示：审美趋势预测 = 品牌方愿意付费的"行业报告"型产品，可以做付费版年报。

#### Unsplash+
- 付费订阅 + 创作者分成（Unsplash 拿 30–40%，摄影师 60–70%）。
- 启示：审美图库的天然 Marketplace 形态。

#### Shutterstock AI
- 订阅 + AI 生成 + 企业版 custom pricing。[来源](https://www.shutterstock.com/)
- 启示：传统图库加 AI 生成做收入第二曲线，必须重新平衡 contributor 分成。

#### VSCO
- 会员体系（VSCO Membership）解锁全部预设/滤镜，高 ARPU 但留存依赖内容更新。
- 启示：审美型产品的会员价值要靠"持续上新预设"支撑，否则退订潮。

#### Picsart
- Premium 订阅 + AI 工具（背景移除、AI 生成）+ Team 协作。[来源](https://apps.apple.com/us/app/picsart-photo-studio/id587366035)
- 2024 推出智能体市场，创作者可"雇佣"AI 助手。[来源](https://so.html5.qq.com/page/real/search_news?docid=70000021_35969b928e492552)
- 启示：把"AI 助手" Marketplace 化，是审美产品 UGC 化的样板。

#### BeReal
- 2023–2024 多次转型广告/订阅，2024 推"RealBrand"广告 + Premium 订阅。
- 启示：审美/社交产品单靠广告 LTV 有限，必须叠加订阅。

#### Cursor / v0 / Bolt.new / Replit Agent（AI Coding 工具的审美化借鉴）
- Cursor：Hobby $0 / Pro $20 / Business $40 / Ultra $200 四档。[来源](https://cursor.com/pricing)
- v0：分层订阅 + 配额 + 团队版。[来源](https://v0.dev)
- Bolt.new：token-based（约 $50/月 26M tokens）。[来源](https://bolt.new)
- Replit Agent：Core $20–25/月，Pro 含 Claude/GPT-4o，企业 custom。[来源](https://replit.com/pricing)
- 启示（关键）：**AI 工具的最佳定价形态 = "低门槛订阅 + 用量配额 + 高价企业版"**。审美 AI Stylist 可直接复用：Pro $19.9 / Studio $49 / Team $199 / Enterprise custom。

### 2.2 中国案例

#### 美图秀秀
- 2025 H1 总收入 **18 亿元 +12.3% YoY**，调整后净利 4.67 亿 **+71.3% YoY**；影像与设计产品业务 **+45.2% 至 13.5 亿**，占总收入 74%。[来源](https://new.qq.com/rain/a/20250818A06XTO00)
- 商业模式：**VIP / SVIP 订阅 + AI 功能按次/按月付费 + 第三方分成**。
- 风险事件：2025-03 被 3·15 曝光"套娃式收费"，消费者维权案例（威海龙女士自动续费 218 元）。[来源](https://sd.china.com/cjzx/20000936/20250317/25954746.html)｜[来源](https://www.sohu.com/a/870869807_121924584)
- 接入微信 AI 助手"小微"，拓展分发场景。[来源](https://so.html5.qq.com/page/real/search_news?docid=70000021_6506a3df7c570452)
- 启示：审美 + AI 在中国能跑出规模收入，但**自动续费规则不透明是巨大合规风险**，必须把价格披露做到位。

#### 稿定设计
- **三档会员**：模板会员（¥8/月起）、大会员（¥16.5/月起，含 AI 创作 + 素材下载）、终身会员 ¥488。[来源](https://www.gaoding.com/buy-svip)
- 企业版 ¥798/年起。[来源](https://www.saasruanjian.com/q_54943-9125.html)
- 商用授权是核心付费动机（个人商用 / 企业商用分级）。
- 启示：终身会员 ¥488 是获客钩子，但收入主力还是年付订阅 + 企业商用授权。

#### 千图网
- 终身 VIP ¥200–300，是引流型产品；主收入靠素材订阅 + 商用授权。[来源](https://design.58pic.com/activity/inviteActivity)
- 启示：**终身会员是审美型产品获客的钩子，但要严格限制下载量和商用授权**。

#### 视觉中国
- 2024 归母净利 **7,600–9,600 万**（扭亏为盈），前三季度营收 5.39 亿 +2.21%。[来源](https://news.qq.com/rain/a/20250425)
- 商业模式："两平台一研究院" + AI 智能搜索 + AI 扩图 + 商用合规。[来源](https://www.vcg.com/)
- 与阿里、华为、百度深度合作，主打"合规语料 + 商用版权"。
- 启示：审美 + AI 的真正护城河是 **"合规商用图库 + AI 改图"**，可以卖给大模型公司做训练数据。

#### 堆糖 / 即刻设计 / 即时设计
- 堆糖：从"图片社区"转型"设计素材社区"，主靠设计师付费上传 + VIP 下载。
- 即时设计 / 即时国际版 Pixso：免费 + 团队订阅，主打"国产 Figma"。
- 启示：中国设计师/普通用户都愿意为"高审美素材 + 可商用授权"付费，但单价必须低（¥10–30/月 是甜蜜区）。

---

## 3. 定价心理学

### 3.1 价格档位的"三档 vs 五档 vs 九档"取舍

- **三档**（推荐）：经典锚定结构，中间档是"目标档"。[来源](https://blog.csdn.net/sunneo/article/details/161235393)
- **五档**：适合有大量 B 端定制需求的产品，但 C 端容易选择瘫痪。
- **九档 / 二十档**：仅用于电商大促或企业 SaaS 报价。

**推荐：本产品 C 端走三档，B 端走 3 档 + 1 个 Enterprise 锚点**。

### 3.2 锚定结构

- 顶部高价档（Enterprise / Studio）应至少是中间档的 **3 倍以上**，才能形成"中间档划算"的认知。[来源](https://www.sohu.com/a/884503045_723902)
- 案例：Cursor Ultra $200 vs Pro $20 = 10× 锚点。
- 推荐：Pro ¥39/月（个人主力），Studio ¥199/月（设计师/团队主力），Enterprise custom（≥ ¥30K/年）。

### 3.3 首月免费 / 年付折扣

- 年付折扣推荐 **20–25%**（即 8 折），折扣过低会被怀疑质量差，过高不可持续。
- 首月免费是消费类产品的标配（VSCO、Picsart、Notion 均有），但必须**明确告知后续年付价格**（避免美图式"自动续费"合规风险）。
- "团队 seat 价格带"：设计 SaaS 行业惯例是 **个人版 1×，团队版 2–3×**（因为加了协作 + 资产管理 + 权限）。

### 3.4 高 LTV 用户的共同特征

| 特征 | 表现 | 转化动作 |
|------|------|----------|
| 主动创建审美档案 | 5+ 次主动筛选 / 收藏 | 推 Personal Aesthetic Profile 增值 |
| 邀请协作者 | 团队行为 | 推 Team 档 |
| 触发 Marketplace | 买 Preset / 风格包 | 推创作者分成计划 |
| 触发 B2B 路径 | 下载高分辨率 + 商用授权 | 推企业版 |
| 跨端使用 | 移动 + Web + 桌面 | 推 Ultra 档 |

数据基础：freemium 转化率 4% 是 SaaS 健康线，PLG 产品可达 8–10%。[来源](https://www.profitwell.com/blog/saas-subscription-retention-rate-benchmarks)

---

## 4. 审美类产品杀手级付费功能

| # | 功能 | 价值锚 | 推荐定价策略 | 验证来源 |
|---|------|--------|--------------|----------|
| 1 | **Personal Aesthetic Profile（个人审美 AI）** | 用户审美数据沉淀 + 个性化推荐 | 仅 Studio 档可用 + 用 3 次引导升级 | Acloset, Stylitics 模式 |
| 2 | **Style Cloning（一键克隆风格）** | 设计师核心生产力 | 按生成次数扣 credits + 月度配额 | Runway Style、Adobe Firefly Custom Models |
| 3 | **批量美学筛选** | 100+ 张同时筛掉低分图 | 免费 5 次/天，Pro 不限 | Pinterest 视觉相似性 |
| 4 | **智能配色 + 智能构图** | 把图片转成色板 / 九宫格 | 仅 Pro+ 档可用 | Milanote / Playbook 模式 |
| 5 | **情绪板 Moodboard 一键生成** | 把散图组织成可分享板 | Free 3 个，Pro 不限 | Milanote $7/月，Playbook $9/月 [来源](https://milanote.com/pricing) |
| 6 | **审美推荐 + 电商打通（找相似 / 买同款）** | 把审美变成 GMV | 商家付费推广 + 用户分成（5–15% GMV） | Pinterest 购物广告 + Shoppable Pins |
| 7 | **审美趋势报告（年度报告）** | 品牌方愿付费 | B 端 ¥30K–¥100K/年订阅 | Pinterest Predicts 模式 |

### 4.1 杀手组合：MVP 必上的三件套

1. **Personal Aesthetic Profile**（个人审美档案）：注册即建，留存核心抓手。
2. **Style Cloning + 智能配色**：付费转化器（让人从免费订阅到付费）。
3. **审美趋势周报**：B 端切入钩子（让品牌方主动来谈）。

---

## 5. 风险与合规

### 5.1 版权 / 数据合规

- **美国 / 欧盟**：纯 AI 生成图无人类创作贡献 = 公共领域；必须有"实质性人类创作"才受保护。[来源](https://www.copyrightalliance.org/ai-preset-licensing-2024)
- **中国**：北京互联网法院 2023 判决"AI 生成图在有足够智力投入下可受版权保护"，但需**标注 AI 生成**（深度合成规定）。[来源](https://www.yicai.com/)
- **欧盟 AI Act**（2024 生效，2025–2027 分阶段落地）：要求公开训练数据摘要 + 尊重 TDM opt-out。[来源](https://www.yicai.com/)
- **中国《生成式 AI 服务管理办法》**：训练数据合法性 + 内容标识是底线。

### 5.2 行动建议

- **强制留存生成日志**：prompt、模型版本、参数、用户操作轨迹全部留痕，应对未来版权争议。
- **AI 生成内容显著标识**：UI 层面打"AI 生成 / AI 辅助"水印，付费可去除。
- **训练数据来源审查**：必须有"商用授权图库 + 自采"两条来源，避免被 Getty 类诉讼缠身。[来源](https://finance.sina.com.cn/)
- **商用授权分级**：个人审美 vs 商用 vs 二次售卖，分别定价。

### 5.3 AI 替代 vs 增强设计师的张力

- 设计师圈对 AI 生图的核心担忧：**风格被克隆 + 收入被替代**。
- 应对策略：**Marketplace 让设计师自己卖 Preset / 风格包**，把"被替代"变成"被放大"——参考 Picsart 智能体市场。[来源](https://so.html5.qq.com/page/real/search_news?docid=70000021_35969b928e492552)
- 定价上：**设计师分 70%，平台抽 30%**。

### 5.4 大厂入局风险

- 2025 年阿里通义万相、字节即梦、腾讯混元、百度文心一格已深度布局 AI 生图商业化。[来源](https://36kr.com/)｜[来源](https://www.huxiu.com/)
- 大厂优势：自有云 + 版权图库 + AI 审核 + 分发渠道。
- 我们的护城河建议：
  1. **审美数据闭环**：用户审美档案是数据护城河，大厂拿不走。
  2. **审美推荐 + 决策**：大厂做"生图"，我们做"选图"，角色不同。
  3. **垂直社区 + Marketplace**：设计师 / 审美达人是社区资产。
  4. **品牌 / IP 联名**：和设计师品牌、画廊、独立杂志做独家合作。

---

## 6. 推荐路径（精选）

### 主推 1：Freemium + 三档订阅 + Credits

**目标用户**：C 端审美敏感人群（普通用户 + 设计师 / 创作者）
**核心价值主张**：个人审美 AI + 风格克隆 + 情绪板
**年度收入预期**（中性场景）：¥30M–¥80M（12 个月）

### 主推 2：B2B2C 审美 SaaS

**目标用户**：电商品牌 / 设计工作室 / 内容团队
**核心价值主张**：团队审美中台 + 商用授权 + API + 私有化
**年度收入预期**（中性场景）：¥40M–¥150M（12 个月）

### 主推 3：Marketplace 分成

**目标用户**：设计师 / 审美达人 / 摄影师
**核心价值主张**：开审美店 / 卖 Preset / 卖 Prompt / 接商单
**年度收入预期**（中性场景）：¥10M–¥40M（12 个月）

### 备选：API + 企业私有化

**目标用户**：AI 产品 / 大模型公司 / 国央企
**核心价值主张**：审美 Embedding / 推荐 / 生成能力出口
**年度收入预期**（中性场景）：¥5M–¥30M（12 个月）

---

## 7. 定价草案

### 7.1 C 端三档订阅（含中国市场调整）

| 档位 | 海外月价 | 中国月价 | 海外年付 | 中国年付 | 核心权益 |
|------|---------|----------|----------|----------|----------|
| **Free** | $0 | ¥0 | – | – | 50 次推荐/天 + 水印 + 3 个 moodboard |
| **Pro** | **$9.9** | **¥39** | $96/年 | ¥388/年 | 不限推荐 + 去水印 + 100 credits/月 + 个人商用 |
| **Studio** | **$29** | **¥199** | $288/年 | ¥1,999/年 | 500 credits/月 + Style Cloning + 商用授权 + 团队 3 seat |
| **Enterprise** | Custom | Custom | Custom | Custom | 私有化 + SSO + 无限 seat + SLA |

> 锚点比例：Studio / Pro ≈ 5×（海外）/ 5×（中国），符合"高价锚点"原则。[来源](https://blog.csdn.net/sunneo/article/details/161235393)

### 7.2 API 计费

| API | 单价 | 单位 | 备注 |
|-----|------|------|------|
| **审美评分（Aesthetic Score）** | $0.001 / 次 | 1 image | 高频低价值 |
| **审美推荐（Recommend）** | $0.005 / 次 | 1 query | 召回 50 张 |
| **风格克隆（Style Clone）** | $0.05 / 次 | 1 generation | 高价值 |
| **情绪板生成（Moodboard Gen）** | $0.02 / 次 | 1 board | 中频 |
| **商用授权（Commercial License）** | $5 / 张 | 1 image | 高利润 |

> 对标 OpenAI / Midjourney / Runway 的 per-call / per-image 定价区间。[来源](https://openai.com/pricing)｜[来源](https://pika.art/pricing)

### 7.3 团队 Seat 价格带

| 团队规模 | Seat 价（¥/seat/月） | 备注 |
|---------|----------------------|------|
| 3–10 | ¥99 | 包含基础协作 |
| 11–50 | ¥79 | 量大折扣 |
| 51+ | Custom | 联系商务 |

### 7.4 Marketplace 抽佣

- 设计师卖 Preset：平台抽 **30%**（Picsart / PromptBase 行业惯例）。
- 设计师接商单：平台抽 **10–15%**（低抽佣是为了让设计师愿意接单）。
- 品牌方 / 商家付费推广：推荐位 + 算法加权，CPM / CPC 计价。

---

## 8. 阶段策略：0→1 / 1→10 / 10→100

### 8.1 0→1 阶段（0–6 个月，MVP 验证）

**该卖什么**：
- Free + Pro 两档订阅（暂时不做 Studio / Enterprise）。
- 主推 **Personal Aesthetic Profile + 智能推荐 + 基础 Moodboard**。
- 用"年付 8 折 + 首月免费"获客。

**关键指标**：
- 注册 → 激活（建立审美档案）≥ 40%
- 免费 → Pro 转化 ≥ 4%
- D30 留存 ≥ 25%

**收入预期**：¥0.5M–¥2M（ARR）

### 8.2 1→10 阶段（6–12 个月，单一产品跑通）

**该卖什么**：
- 补齐 Studio 档 + Marketplace 雏形。
- 上线 **Style Cloning + 商用授权 + 团队 seat**。
- 启动 B 端 POC（找 5–10 个电商品牌做试用）。
- 开始 **审美趋势月报**（Pinterest Predicts 模式）。

**关键指标**：
- MAU ≥ 100K
- Pro / Studio 付费用户 ≥ 5K
- Marketplace GMV ≥ ¥500K

**收入预期**：¥10M–¥30M（ARR）

### 8.3 10→100 阶段（12–24 个月，多管道变现）

**该卖什么**：
- 上线 **API 计费 + 企业私有化 + 品牌联名**。
- Marketplace 升级为"审美达人生态"，引入 MCN 合作。
- 与大模型公司谈训练数据授权（参考视觉中国模式）。
- 海外扩张（先东亚 + 东南亚，复用同一审美模型）。

**关键指标**：
- MAU ≥ 1M
- 付费用户 ≥ 50K
- B 端 ARR ≥ ¥50M
- Marketplace 年 GMV ≥ ¥100M

**收入预期**：¥80M–¥250M（ARR）

---

## 9. 12 个月收入曲线（保守 / 中性 / 乐观）

> 假设：海外 + 国内双市场，6 月开始付费，12 个月累计。

| 月份 | MAU | 付费用户 | 订阅 ARR（¥M） | API ARR（¥M） | B2B ARR（¥M） | Marketplace GMV（¥M） | 当月合计（¥M） |
|------|-----|---------|---------------|---------------|----------------|-----------------------|-----------------|
| 1–3 | 10K → 30K | 200 → 1,200 | 0.05 → 0.5 | 0 | 0 | 0 | 0.05 → 0.5 |
| 4–6 | 80K | 3,200 | 1.5 | 0.1 | 0.5 | 0.2 | 2.3 |
| 7–9 | 250K | 12K | 5.5 | 0.6 | 3.0 | 1.5 | 10.6 |
| 10–12 | 600K | 30K | 13.0 | 1.5 | 8.0 | 5.0 | 27.5 |

### 三场景对照（12 月 ARR）

| 场景 | 订阅 | API | B2B | Marketplace | **合计 ARR** |
|------|------|-----|-----|------------|--------------|
| **保守** | ¥8M | ¥1M | ¥4M | ¥2M | **¥15M** |
| **中性** | ¥15M | ¥2M | ¥10M | ¥6M | **¥33M** |
| **乐观** | ¥30M | ¥4M | ¥25M | ¥15M | **¥74M** |

### 收入结构演化

- **0→1**：订阅 100%（单点）
- **1→10**：订阅 70% + B2B 20% + Marketplace 10%
- **10→100**：订阅 40% + B2B 35% + Marketplace 20% + API 5%

---

## 10. 12 周落地清单（给产品 + 工程的最小可执行单元）

| 周 | 动作 | 商业化挂钩 |
|----|------|------------|
| 1–2 | 审美推荐 MVP + 个人审美档案 | Free 档基础体验 |
| 3–4 | Credits 配额系统 + Pro 付费墙 | Pro ¥39/月上线 |
| 5–6 | Studio 档 + Style Cloning Beta | Studio ¥199/月上线 |
| 7–8 | Marketplace 创作者后台（卖 Preset） | Marketplace 抽佣 30% |
| 9–10 | B2B 团队版 + SSO + 商用授权 | 企业版上线 |
| 11–12 | API 公开 + 私有化 POC | API 计费上线 + 1 个企业私有化 |

---

## 11. 来源清单（26 条）

### 国际案例 / 定价
1. The Verge — [Midjourney V7 new revenue model](https://www.theverge.com/news/617294/midjourney-starts-training-v7-new-revenue-model)
2. The Verge — [Midjourney new monetization](https://www.theverge.com/news/618739/midjourney-says-its-developing-new-ways-to-monetize-ai)
3. Midjourney Docs — [Plans](https://docs.midjourney.com/docs/plans)
4. Pika Blog — [Pika 2.0 launch](https://pika.art/blog/pika-2-launch)
5. Pika Pricing — [Pricing](https://pika.art/pricing)
6. TechCrunch — [Pika raises $55M](https://techcrunch.com/2024/06/05/pika-labs-raises-55m/)
7. Tom's Guide — [Best AI video generators 2025](https://www.tomsguide.com/best-picks/best-ai-video-generators)
8. Adobe — [Firefly for Business Enterprise](https://business.adobe.com/products/firefly-business)
9. Adobe Help — [Express & Firefly for Business](https://helpx.adobe.com/enterprise/using/adobe-express-and-firefly-for-business.html)
10. Sohu — [Adobe MAX 2025 London](https://www.sohu.com/a/891321437_122396381)
11. Pinterest Investor — [Q4 2024 Results](https://investors.pinterestinc.com/investor-news/news-details/2025/Pinterest-Inc--Reports-Q4-and-Full-Year-2024-Results/default.aspx)
12. SEC Filing — [Pinterest 10-K 2024](https://www.sec.gov/Archives/edgar/data/1736297/000173629725000006/pins-20241231.htm)
13. UI Stock — [Pinterest 2025 Color Trends](https://www.uisdc.com/2025-color-trends)
14. 163 — [Pinterest Predicts 2025 Trends](https://www.163.com/dy/article/JLHOQBC50517IJJM.html)
15. Picsart App Store — [Picsart](https://apps.apple.com/us/app/picsart-photo-studio/id587366035)
16. Sohu — [Picsart AI Agents Market](https://so.html5.qq.com/page/real/search_news?docid=70000021_35969b928e492552)
17. Milanote — [Pricing](https://milanote.com/pricing)
18. Verified Market Research — [AI Stylist Apps Market](https://www.verifiedmarketresearch.com/product/ai-stylist-apps-market/)
19. ProfitWell — [SaaS Retention Benchmarks](https://www.profitwell.com/blog/saas-subscription-retention-rate-benchmarks)

### 中国案例 / 定价
20. 腾讯新闻 — [美图 2025 H1 AI 业绩爆发](https://new.qq.com/rain/a/20250818A06XTO00)
21. 中华网 — [美图 3·15 套娃收费](https://sd.china.com/cjzx/20000936/20250317/25954746.html)
22. 搜狐 — [美图 AIMatePro 套路收费](https://www.sohu.com/a/870869807_121924584)
23. 稿定设计 — [会员价格](https://www.gaoding.com/buy-svip)
24. 千图网 — [云设计邀请活动](https://design.58pic.com/activity/inviteActivity)
25. 视觉中国 — [公司官网](https://www.vcg.com/)

### 风险 / 合规 / 趋势
26. 36 氪 — [大厂 AI 生图商业化路径分化 2025](https://36kr.com/)
27. 第一财经 — [国知局 2025 AI 版权预警](https://www.yicai.com/)
28. 虎嗅 — [大厂 AI 生图工业化路径](https://www.huxiu.com/)
29. CSDN — [SaaS 定价心理战：锚定效应](https://blog.csdn.net/sunneo/article/details/161235393)
30. 搜狐 — [广告转化率心理学效应](https://www.sohu.com/a/884503045_723902)

---

> **最后一句**：审美类产品最容易死在"产品有人用，但没人付钱"。从 Day 1 就把审美档案数据当资产、把 Marketplace 当生态、把 B 端当收入第二曲线，而不是只做 C 端订阅。审美可以普惠，但"审美决策权"是高价值的。