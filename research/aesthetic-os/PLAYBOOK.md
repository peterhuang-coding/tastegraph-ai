# 审美图片推荐系统 · MVP → 商业化 技术路线图
> Playbook · 审美 OS · 2026-07-26 立项版

本文是七份研究简报的统合：算法架构 / 美学系统 / Coding-LLM / 工程基建 / 数据与合规 / 商业化 v1 / 审美媒体与创作者商业闭环。
**v2 商业化已重写**（从"卖数据集/SaaS"到"卖审美裁判权 + IP"），主走 `monetization-playbook-v2.md`。本文件 §3 已按 v2 更新。
所有原始报告在 `/Volumes/SanDisk2TB/aesthetic-os/research/*.md`（旧路径 `/Users/peter_mini/research/` 已做软链兼容），每节尾部给出衔接指针。

---

## 0. 一页立项（TL;DR）

### 产品定位：Aesthetic OS（审美操作系统）
把"审美推荐 + AI Stylist + 风格数据资产"做成一个独立的操作系统层：
- **审美档案**（Personal Aesthetic Profile）：用户审美数据沉淀 = 数据护城河
- **审美推荐**（Aesthetic RecSys）：用审美特征 + 行为 + 实时上下文多路召回
- **AI Stylist**：风格克隆 / 智能配色 / 智能构图 / 情绪板一键生成
- **审美 Marketplace**：让审美达人卖 Preset / 风格包 / Prompt（抽 30%）

> 在大厂通义万相 / 即梦 / 文心一格靠"生图"切入时，**我们靠"选图 + 审美决策权"切入**——角色不同，不正面竞争。

### 七大收入支柱（v2 商业化）
- **P1 IP / 出版物**：年鉴 + 季刊 + 限量 zine，¥99–¥499/期。Apartamento / Kinfolk 模式，主护城河。
- **P2 Drop / 联名物件**：每季 1 Drop × 限量单品，¥99–¥2,999。Aimé Leon Dore 模式。
- **P3 Experience / 城市 walk / 主题住宿**：¥500–¥5,000/人。Atlas Obscura / Klook 互补。
- **P4 Subscription**：¥39 / ¥599 / ¥1,999 三档，但订阅只是"圈层入场"接入口，不是主收入。
- **P5 B2B 美学策展**：月度主编 + 品牌定制 + Guest Editor，¥30K–¥300K/年。Wallpaper\* 模式。
- **P6 Aesthetic Advisory**：主理人设计咨询，¥50K–¥500K/项目。
- **P7 API + 数据授权**（降权）：仅在数据护城河确立后启动。

→ 12 月 ARR 中性 **¥30M**（主驱动 P1 + P2），保守 **¥15M**，乐观 **¥80M**。详见 [monetization-playbook-v2.md](monetization-playbook-v2.md)。

### 技术选型一句版
- **审美评分**：双轨起步，**SigLIP 2 + DINOv2 双塔 8 维美学向量**（隐藏 SOTA 趋势）+ **AADB 12 维属性 head** + 个性化用 PIAA-TaskVector；评估走 **AesBench 4 维 + HPSv2 v2.1 + ImageReward**；通用美学 0 训练 baseline 用 **LAION-Aesthetic-Predictor v2.5**。
- **推荐架构**：MVP **SigLIP/CLIP 双塔 + 热门 + onboarding pairwise + 可解释线性重排**；10 万 DAU 进入标准漏斗（多路召回 → DIN 精排 → 约束重排）；千万级上 **MMoE 多目标 + Mamba4Rec/HSTU 长序列 + SlateQ 灰度**。
- **Coding-LLM**：**Code LLM 做"风格 DSL ↔ 向量库桥接"**（HyDE + Qwen2.5-Coder-32B）+ **RankZephyr listwise rerank** + **SFR-Embedding-Code 主 Embedding**；推荐文案仍交给 Claude Sonnet 4.5。
- **工程基建**：MVP **pgvector + TEI L4 + BGE-M3 + Redis**（<$400/月）；10 万 DAU 切 **Qdrant + vLLM L40S**（$3–5K）；千万级 **Milvus + DiskANN + Triton 4×H100**（$50–120K），核心范式 **HNSW 10% RAM 热 + DiskANN 90% SSD 冷**。
- **1M 请求/月成本**：self-host ~$1,900 / 全 API ~$9,000 / 端侧 demo ~$5。

### 12 周落地节奏（v2 改造版：5 启动动作）
- **W1–2 Premier 100 公会**（5–10% 跨圈层节点）+ 数据栈 Kafka+Flink
- **W3–4 限量 zine 第一期**（vaporwave 50 物件） + HyDE query + ItemCF 召回
- **W5–6 City Walk 第一场**（上海/成都/京都候选） + DIN 精排 + RankZephyr
- **W7–8 Profile Takeover**（Premier 100 KOL 接管 IG） + A/B 框架 + CFPED
- **W9–10 Editor's Note 仪式感 + B2B 美学主编 POC** + B2B Studio 订阅 + SSO
- **W11–12 Showroom 试运行 + Drop 第二期预备** + 全量灰度 + 12 月 ARR 复盘

---

## 1. 产品形态与"审美数据资产"哲学

### 1.1 为什么是"审美 OS"而不是又一个生图 App
- **审美决策是高价值场景**：用户每天刷图但单次决策轻 → 必须走订阅 + Marketplace 而非单次付费（Midjourney 2024 ARR $200M、Adobe Firefly Enterprise 1,200 credits/月 是支撑）。
- **审美数据具有越用越准的网络效应**：你越筛选，越能识别你 → 这层数据是大厂拿不走的护城河（即使文心 / 通义做生图，也拿不到你的审美档案）。
- **审美具有社交属性**：用户愿意晒自己的审美档案 → UGC + Marketplace 双轮。
- **生成成本不可忽略**：单次风格克隆 embedding + 重排 + 生成 = 多 token / 多 GPU 分钟 → 必须 credits 兜底，否则被羊毛党刷穿（Pika 2024 从 unlimited 改 credit-based 是行业普遍路径）。

### 1.2 数据护城河如何落
```
注册 → 5–10 个 onboarding pair（"我更喜欢 A 还是 B"）
     → 自动构建 Personal Aesthetic Profile（8 维向量 + tag 体系）
     → 每次刷新点赞 / 收藏 / 隐藏 → 模型增量学习（PIAA-TaskVector 风格）
     → 用户主动晒档案 → Marketplace / 社区引流
```

### 1.3 与大厂的差异化
| 维度 | 大厂（通义/即梦/文心一格） | 我们（审美 OS） |
|------|---------------------------|----------------|
| 核心动作 | 生图 | 选图 / 推荐 / 沉淀审美 |
| 数据资产 | 训练语料 | 用户审美档案 + Marketplace |
| 商业化 | Credits + API | 订阅 + Marketplace + B2B + API |
| 切入角色 | 供给侧 | 决策侧 |

---

## 2. 技术架构（四大块深度整合）

> 本节把六份报告的算法 / 美学 / Code-LLM / 基建选型拼成一张完整图。每段末尾附原始报告指针。

### 2.1 数据层（行为 + 内容 + 用户三表）
- **行为信号 6 维**：曝光 / 点击 / 完播 / 点赞 / 收藏 / 关注 + dwell time。
- **点表 SPL**：Kafka 实时 → Flink 实时特征 → 离线 T+1 数仓训练样本。
- **合规底线**：公开数据集优先 CC-BY / Apache-2.0；训练用图避 Getty / Shutterstock / VCG；爬虫遵守 RFC 9309 robots.txt；中国境内业务必须满足《个人信息保护法》+《生成式 AI 服务管理办法》+ 算法推荐规定双通知机制。
- **训练数据 8 周可启动**：AVA / AADB / KonIQ-10k / TAD66K / HPSv2 / LAION-Aesthetics V2.5 / MovieLens-25M / KuaiRand-27K；中文审美补充 Chameleon + 自采中文 prompt（详见 §3.4）。

> 衔接：[benchmarks-and-data.md](benchmarks-and-data.md)

### 2.2 召回层（多路并行）
```
         用户口味 + 上下文
                │
   ┌────────────┼────────────┬─────────────┐
   ▼            ▼            ▼             ▼
内容语义       协同信号       热门/新鲜     探索
(SigLIP/CLIP)  (BPR-MF/       (新图 cron   (随机池
 双塔 + ItemCF +   + 维护)      0.1–1%)
 onboarding pair)
   │            │            │             │
   └────────────┴────────────┴─────────────┘
                ▼
        ANN 检索 (pgvector → Qdrant → Milvus)
        返回 top-200 候选
```
- **冷启动救场**：用 SigLIP/CLIP 双塔在 zero-interaction 状态下也能召回，VBPR 论文证明视觉特征缓解冷启动。
- **个性化冷启动**：onboarding 5–10 个 pair → SigLIP 个性化向量 = 平均用户的偏移量。
- **MTMH（KDD 2025 Meta）** 启发：把"用户共现喜欢"和"内容真正相似"分两个 head 联合优化，本项目一开始就拆。

> 衔接：[recsys-architecture.md](recsys-architecture.md)

### 2.3 精排层（DIN → DIEN → 多目标）
- 精排头输出：`p_click`, `p_save`, `E[dwell_capped]`, `p_share`, `p_hide`, `p_report`
- 效用：`utility = w1·p_save + w2·E[dwell] + w3·p_share + w4·p_click − w5·p_hide − w6·p_report`，**权重版本化配置**，可热更新。
- 推荐效用与审美效用对齐：把"美感 prior × 美感匹配 × 效用"三段相乘，不让审美压倒实用信号。
- 北极星不只 CTR：**收藏 / 有效停留 / 7 日回访 / 列表内多样性 / 负反馈比例**，A/B 必配 CUPED 降方差 + interleaving 快速筛选。

### 2.4 审美打分与"双头"
- **公共审美 prior**：LAION-Aesthetic-Predictor v2.5 上线即用，做筛选 / 去重 / 后备打分。
- **个性化审美**：AADB 12 维属性 head（interesting_content / good_lighting / color_harmony ...） + SigLIP 2 + DINOv2 双塔 8 维美学向量；用户级 LoRA 用 PIAA-TaskVector 实现。
- **审美评估**：AesBench 4 维（感知/共情/评估/解读）作为评测标尺，每周 + 每次模型变更跑一遍。
- **LLM-as-Judge**：评估类用 GPT-4o 性价比高，解读类用 Claude 3.5 / Q-Align 类 LMM。审美"感知" LLM 一致 70–80%，"解读"仅 ~50%，需谨慎。

> 衔接：[image-aesthetic-system.md](image-aesthetic-system.md)

### 2.5 检索增强与 Code-LLM 胶水层
- **DSL Query 改写**：用户说 "vaporwave + neon pink + 80s retro" → **Qwen2.5-Coder-32B** 生成结构化 query → JSON Schema 校验 → 喂向量库 filter。
- **HyDE（零样本检索）**：用户写 "我想要 vintage grunge" → Code LLM 生成"假设审美描述"→ 用该描述 embedding 检索，比 BM25+传统 dense 高 15–25% nDCG。
- **Listwise Rerank**：BM25 + Code Embedding 召回 top-50 → **RankZephyr 7B** listwise 重排 → 输出 top-10。Cursor / Copilot 都用了类似栈。
- **Agentic 推荐**（中后期探索）：Shopify Sidekick / Amazon Rufus 范式，多轮 retrieve → filter → rerank → explain。

> 衔接：[coding-semantic-model.md](coding-semantic-model.md)

### 2.6 工程栈与三阶段成本
| 阶段 | DAU | 向量库 | Embedding 推理 | 特征 / 调度 | 月成本 |
|------|-----|--------|-----------------|------------|--------|
| **MVP** | < 1 万 | pgvector / Chroma | TEI L4 + BGE-M3 | FastAPI / 规则 | < $400 |
| **10 万 DAU** | 10 万 | Qdrant 单机 | vLLM 2× L40S + TEI | Redis + Feast | $3–5K |
| **千万级 DAU** | 千万 | Milvus 分布 + DiskANN | Triton 4×H100 + 多模态 TEI | 自研 Redis+Flink | $50–120K |

> 衔接：[recsys-infra.md](recsys-infra.md)

**冷热分层硬规则**：HNSW 仅放前 10% 高热数据走 RAM（p99 < 5ms）；后 90% 走 DiskANN + SSD（p99 < 30ms）。Bing / Shopee 已在生产验证。

### 2.7 永远 2× GPU 富余 + 新模型 Shadow 24–48h
这两个是基建层 PM 必须盯死的红灯：
- **GPU 不能打满 80%**——突发流量 + 故障恢复至少需要 2× 头寸。
- **新模型先 Shadow 24–48h**：全量流量打对一份"影子 log"，对比离线 + 线上 metrics，确认无回退再切主流量。
- **Embedding drift 监控**：每周分布对比，drift > 阈值自动告警。
- **特征穿越零容忍**：所有训练样本必须 point-in-time 拼接，键值带时间戳，不能跨时间窗泄漏。

---

## 3. 商业化架构 v2（卖审美裁判权 + IP）

### 3.1 范式转移
v1 把审美 OS 当"卖数据中间商"。**v2 把审美 OS 当策展品牌公司**，对应 Atlas Obscura / Ace Hotel / NTS Radio / Apartamento / Kinfolk 模式。订阅只是用户接入口，**真正护城河是"被 Premier 100 邀请的圈层入场权 + 可触摸的物件 + 可走进去的体验"**。

### 3.2 订阅重构（v2 三档）
| 档位 | 月价（中国） | 核心权益（v2 重构） |
|------|------------|---------------------|
| **Basic** | ¥39 | 个人审美档案 + 推荐 + 50 次/天 + 水印（接入口） |
| **Studio** | ¥599 | Basic 全部 + Drop 提前 24h 购买权 + 限量发售 + 商用授权 + 团队 3 seat |
| **Circle** | ¥1,999 | Studio 全部 + Artist Talk + 城市 walk 打折 + Showroom 优先 + advisory 1h/月 |

> 与 v1 不同：Studio 从 ¥199 → ¥599，**因为 Studio 是"进 Drop 圈"的入场券**（Apartamento 送 tote + 8 折 + 数字档案 + MUBI 合作的逻辑）。

### 3.3 七大收入支柱（P1–P7）
详见 `monetization-playbook-v2.md §2`：
- **P1 IP / 出版物**：年鉴 + 季刊 + zine，Apartamento 模式，主护城河
- **P2 Drop / 联名物件**：每季限量 Drop，Aimé Leon Dore 模式
- **P3 Experience / City Walk / 主题住宿**：Atlas Obscura 互补
- **P4 Subscription**：¥39 / ¥599 / ¥1,999 三档 → 仅接入口
- **P5 B2B 美学策展**：月度主编 + 品牌定制，Wallpaper\* 模式
- **P6 Aesthetic Advisory**：主理人 + 设计师接设计咨询
- **P7 API + 数据授权**：降权保留

### 3.4 90 天启动动作（social-magnetism §7）
**先攻 Hub（5–10% 跨圈层节点），让 Spokes 反向把 Star 拉过来——不主动去找明星。**
- **W1–2 Premier 100**：邀 100 个跨圈层节点（10 摄影师 + 10 设计师 + 10 买手店主 + 10 KOL + ...）成创始公会
- **W3–4 限量 zine 第一期**："vaporwave 的 50 个物件"，印 500 册，¥59
- **W5–6 City Walk 第一场**：上海/成都/京都候选，12 人满员，¥1,500–¥5,000/人
- **W7–8 Profile Takeover**：3 位 KOL 每周接管 IG 1 天
- **W9–10 Editor's Note + B2B POC**：每周一篇 800 字 Editorial + 1 个 B 端品牌付费 ¥30K

### 3.5 合规与法务硬约束（小红书账号封禁是前车之鉴）
- Drop + 联名合同：独占期 + 销售期 + 价格带 + 退货权写清楚
- 出版物合规：每张图署名三栏（图作者 + 摄影师 + 平台）
- 自动续费透明披露（美图 3·15 反面教材）
- EU AI Act TDM opt-out + 中国 PIPL + 算法备案
- 数据出境：海外版本每个市场独立存储
- 隐蔽宣传禁令：所有 KOL / Premier 100 名单透明披露，无暗推

> 衔接：[monetization-playbook-v2.md](monetization-playbook-v2.md)（主推 v2 详细版）
> v1 保留：[monetization-playbook.md](monetization-playbook.md)（已弃用，仅做 SaaS 路径参考）

---

## 4. 12 周落地清单（Day 1 起算）

| 周 | 工程主线 | 商业化主线 | 风险与决策点 |
|----|---------|-----------|------------|
| **W1** | 数据栈：Kafka+Flink 起，行为 6 信号埋点接入；AVA+AADB+HPSv2 落地 | Free 档基线体验 | 数据源合规审查（避 Getty/VCG） |
| **W2** | MVP 推荐：SigLIP/CLIP 双塔 + 热门 + ItemCF 召回 + 规则重排；与 pgvector 接 | 个人审美档案（onboarding）首版 | 100 用户 dogfood |
| **W3** | 美学 head：AADB 12 维属性训练 + SigLIP 2 微调 | Credits 配额系统 + Pro 付费墙 | 美学排序 vs CTR 的取舍决策 |
| **W4** | HyDE query generation + Code Embedding (SFR-Embedding-Code) 接 Qdrant | Pro ¥39/月上线，开始付费转化 | 检索质量回归不下降 |
| **W5** | DIN 精排 + RankZephyr 7B 接入 rerank | Studio 档上线 + Style Cloning Beta | 精排延迟 < 80ms 必须达成 |
| **W6** | A/B 框架 + CUPED；AesBench 4 维 + HPSv2 评测入库 | 5% 付费用户付费转化漏斗审查 | 北极星指标上线 |
| **W7** | 推荐解释模板（Code LLM 写 DSL）+ 推荐文案（Claude Sonnet 4.5） | Marketplace 创作者后台（Preset 上架） | Marketplace 模板审核机制 |
| **W8** | DSPy 编译 prompt pipeline；Langfuse 监控接入全量 | Marketplace 抽佣上线；上架 ≥ 50 个 Preset | 创作者冷启动 ≤ 10 人 |
| **W9** | Team 版协作：seat 权限 + 资源资产管理；商用授权水印分层 | B2B 团队版 ¥199/月上线；SSO | B 端 POC 名单 5–10 个 |
| **W10** | B 端审美 API：白名单限速 + 计费 + 用量看板 | 企业版询价 SDR 培训 | 合规法务过审（数据出境、AI 备案） |
| **W11** | Shadow 模型评估：候选新模型 24–48h 影子流量 | API 公开 API 计费上线 + 1 个企业私有化 POC | GPU 富余 2× 监控阈值 |
| **W12** | 全量灰度 + 监控告警；Anthropic Prompt Cache 优化 | W12 复盘 + 财报口径（订阅 / B / Marketplace） | 12 月 ARR 中性目标 ¥3M |

---

## 5. 三阶段路线（含 Gate 与成本曲线）

### Stage 1：MVP（0–3 月，< 1 万 DAU，< $400/月）
- **关键决策**：单卡 L4 GPU self-host BGE-M3 + pgvector；不上 Milvus；不上 RL；不上 MMoE
- **Gate 1**：付费转化率 ≥ 4%（PLG 健康线），D30 留存 ≥ 25%，北极星（save+dwell）正相关
- **退出条件**：MAU ≥ 3 万 + Pro 用户 ≥ 200 + 团队稳定 4 人

### Stage 2：10 万 DAU（3–9 月，$3–5K/月）
- **关键决策**：Qdrant 单机 + vLLM 2×L40S + Redis + Feast
- **技术升级**：DIN 精排 + MMoE 多目标 + Embedding drift 监控上线
- **Gate 2**：北极星稳定 ≥ Stage 1 baseline + 推荐延迟 p95 < 120ms + B 端 POC ≥ 3 个签下来
- **退出条件**：B 端 ARR ≥ ¥1M + Marketplace GMV ≥ ¥100K

### Stage 3：千万级 DAU（9–18 月，$50–120K/月）
- **关键决策**：Milvus 2.x 分布式 + DiskANN + Triton + 4×H100 + 自研 Flink
- **技术升级**：Mamba4Rec / HSTU 长序列 + SlateQ 灰度探索 + Federated 个性化美学
- **Gate 3**：MAU ≥ 100 万 + 付费用户 ≥ 50K + ARR ≥ ¥33M
- **风险红线**：GPU 富余 2× + Embedding drift 告警 + 特征穿越零容忍

### 12 月 ARR 曲线（v2 七支柱重置，中性）
v2 哲学：订阅只是接入口，**P1（出版物）+ P2（Drop）+ P5（B2B）是主引擎**。v2 数字与 v1 完全不同维度的重塑。

| 月 | Premier 100 (人数) | Studio 订阅 | Drop GMV | B2B 客户 | zine 季订 | Walk 报名 | API | 合计 ARR |
|----|---------------------|-------------|----------|----------|-----------|-----------|------|----------|
| 1 | 80 | 0.05M | – | – | 0.02M | – | – | 0.07M |
| 3 | 100 | 0.5M | 0.1M | – | 0.15M | – | – | 0.75M |
| 6 | 200（运营中） | 2M | 0.8M | 0.5M | 0.6M | 0.1M | – | 4.0M |
| 9 | 300 | 4M | 3M | 2M | 1.5M | 0.3M | 0.2M | 11M |
| 12 | 500 | 8M | 8M | 6M | 3M | 0.5M | 1.5M | **27M** |

保守 12 月 ARR **¥15M**，中性 **¥30M**，乐观 **¥80M**。P1 + P2 + P5 三项占 17M+/27M+（≈60%），订阅 P4 占 8M/27M ≈ 30%，其余 10% 来自 P3+P6+P7。

> 衔接：[monetization-playbook-v2.md](monetization-playbook-v2.md) §4 阶段 Gate 与 §5 风险

---

## 6. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| **合规风险（小红书账号封禁类）** | 中 | 高 | 训练数据两条来源；商用授权分层；法务前置 |
| **美学与"色情/猎奇"边界** | 高 | 高 | AesBench + 人工抽检双层审核；用户举报通道 |
| **Embedding drift** | 中 | 中 | 每周分布对比 + drift 阈值告警 |
| **GPU 单点 / OOM** | 高 | 高 | 永远 2× 富余 + DiskANN 冷分层 + 自动重排队 |
| **特征穿越** | 中 | 高 | point-in-time 拼接强制 + 训练平台检查 |
| **美学与 CTR 冲突** | 中 | 中 | 多目标效用权重版本化 + 北极星加权 |
| **个性化美学隐私** | 中 | 高 | 用户级 LoRA 在端侧 / 加密云侧训练 |
| **大厂入局（通义 / 即梦 / 文心）** | 高 | 中 | 选图侧差异化；审美档案数据护城河 |
| **Code LLM 幻觉输出非法 DSL** | 中 | 高 | JSON Schema + Pydantic 校验 + 工具白名单 |
| **推荐延迟超 SLA** | 中 | 中 | Speculative decoding + prompt cache + 短 prompt |
| **设计"被替代"舆论** | 中 | 中 | Marketplace 让设计师自己开店，把"替代"变"放大" |

---

## 7. 立项决策与待审批清单

### 7.1 PM 自决策
- 数据采集 6 信号范围
- MVP 推荐双塔 baseline 选型
- 审美 0 训练 baseline = LAION V2.5
- Code LLM 主力 = Qwen2.5-Coder-32B
- Code Embedding 主力 = SFR-Embedding-Code
- 商品 Embedding 兜底 = BGE-M3
- 三档订阅起步定价 ¥39 / ¥199
- Marketplace 抽佣 30%

### 7.2 需要用户拍板的
1. **首发市场优先级**：仅中国 / 仅海外 / 双并行？（涉及数据合规边界）
2. **审美风格定位**：极简 / 都市 / 复古 / 跨域混合？（决定训练数据 + KOL 合作）
3. **B2B 目标行业**：电商 / 设计工作室 / 国央企 / 出版社？（决定商务策略与 POC 模板）
4. **是否走开源社区**：Model + Embedding 开源换流量 vs 全闭源收费？（涉及融资策略）
5. **海外合规预算**：EU AI Act / GDPR 法务预算是多少？
6. **是否首批自营交易**：Marketplace 早期是只抽佣（轻）还是自营精品 SKU（重）？
7. **冷启动审美数据策略**：自采 + 小红书/微博合规爬（仍封号风险） vs 用户上传 + 合作图库授权（慢但合规）

### 7.3 v2 新增（来自 monetization-playbook-v2.md §7.1）
8. **P1 出版物节奏**：年鉴 / 季刊 / 双月刊 / 限量 zine，倾向哪一种？
9. **P2 Drop 联名首发品牌**：BEAMS / Tsuchiya Kaban / Loewe / 野兽派 / 其他？
10. **P3 City Walk 首发城市**：上海 / 成都 / 京都 / 巴塞罗那 / 纽约？
11. **P6 Advisory 主理人是否就是 PM 团队自己**：还是外部名人 IP（比如请一个独立策展人）？

### 7.4 用户 24h 内必回的事
- 立项确认（Aesthetic OS 主线认可？）
- 6 周人 / 钱 / 时间资源核（PM + 后端 + 算法 + 设计 + 标注 = 5 人起步？）
- 首发市场与审美定位决策
- v2 §7.3 四问（出版物节奏 / Drop 联名首发 / Walk 城市 / Advisory 主理人）

---

## 8. 引用来源索引

汇总六份报告的引用：

### A. 算法架构
[recsys-architecture.md](recsys-architecture.md) — 53 个原始来源，涵盖 CLIP / SigLIP / DIN / DIEN / SASRec / Mamba4Rec / HSTU / MMoE / PLE / MTMH (KDD 2025)

### B. 美学系统
[image-aesthetic-system.md](image-aesthetic-system.md) — NIMA / NIMA 分布 / PARA / LAION-Aes V2.5 / Q-Align / OneAlign / AesBench / PIAA-TaskVector / SigLIP 2 / DINOv2 / HPSv2 / ImageReward

### C. Coding-LLM
[coding-semantic-model.md](coding-semantic-model.md) — 47 来源：MTEB Code / CoIR / SFR-Embedding-Code / CodeSage / Mistral Codestral Embeddings / Voyage-code-3 / Qwen2.5-Coder / vLLM / SGLang / EAGLE-2 / Anthropic Prompt Cache

### D. 工程基建
[recsys-infra.md](recsys-infra.md) — 35 来源：Milvus / Qdrant / Weaviate / Vespa / Pinecone / pgvector / Chroma / vLLM / TensorRT-LLM / SGLang / LMDeploy / Triton / BGE-M3 / BGE-VL / SigLIP / Jina CLIP / Qwen3-Embedding

### E. 数据与合规
[benchmarks-and-data.md](benchmarks-and-data.md) — 60 来源：AVA / AADB / KonIQ-10k / TAD66K / HPSv2 / ImageReward / MovieLens-25M / Amazon-M2 / KuaiRand-27K / MicroLens / LAION V2.5 / GETTY v STABILITY 案例 / EU AI Act / RFC 9309

### F. 商业化
[monetization-playbook.md](monetization-playbook.md) — 26 来源：Midjourney ARR / Pika credit-based / Pinterest 2024 财报 / 美图 2025 H1 / 稿定定价 / 视觉中国 / Milanote pricing / ProfitWell 留存基准

### G. 审美媒体与创作者商业闭环
[aesthetic-media-creators-commerce-loop.md](aesthetic-media-creators-commerce-loop.md) — 审美媒体、审美博主、跨平台分发、一方用户承接、商品/体验导流、B2B 策展与归因闭环。
[mubu-aesthetic-media-creators-commerce.md](mubu-aesthetic-media-creators-commerce.md) — 可直接导入幕布的层级大纲。

---

## 9. 一句话给项目方

**把审美当成"数据资产 + 决策权"来卖，而不是当成"AI 生图工具"来卖。**
审美档案是别人拿不走的数据护城河；选图 + 推荐是别人不愿干的脏活累活；Marketplace 是别人带不来的生态。
**做大厂不愿做的"决策侧"，吃下审美 OS 这一层**——这是我们 12 周之后想清楚的最有 ROI 的姿态。
