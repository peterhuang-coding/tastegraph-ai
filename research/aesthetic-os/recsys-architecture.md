# 审美图片推荐系统：算法架构与千万级 DAU 演进路线

> 调研日期：2026-07-26  
> 证据窗口：优先检索 2024–2026 论文与官方工程资料；对奠基算法保留原始论文  
> 场景：审美图片推荐，从千级物品/单机 MVP 演进到 10 万 DAU，再到千万级 DAU  
> 引用：53 个高信息密度原始论文、官方代码库或工程博客；结论均在所在段落或表格附链接

---

## TL;DR：推荐的主路线

1. **MVP 不做“大而全推荐平台”**：以 `SigLIP/CLIP 内容召回 + 热门/新图召回 + onboarding pairwise 偏好 + 可解释线性重排` 起步；千级物品可以精确向量搜索，不需要分布式 ANN。视觉内容特征可以在无交互时提供可用信号，VBPR 也明确将视觉特征用于缓解冷启动；CLIP/SigLIP 提供视觉—语言共享空间。[VBPR](https://arxiv.org/abs/1510.01784) · [CLIP](https://arxiv.org/abs/2103.00020) · [SigLIP](https://arxiv.org/abs/2303.15343)
2. **10 万 DAU 才进入标准工业漏斗**：多路召回 → 轻量粗排 → DIN/DIEN 类精排 → 约束重排；此时建设 Kafka/Flink 实时特征、point-in-time 样本拼接、模型注册与 A/B 平台。YouTube 的候选生成/排序两阶段、Pinterest 的批量长期表示 + 实时短期序列组合、Uber 的在线/离线一致特征存储分别给出了直接证据。[YouTube DNN](https://research.google/pubs/pub45530) · [PinnerFormer](https://arxiv.org/abs/2205.04507) · [TransAct](https://arxiv.org/abs/2306.00248) · [Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/)
3. **千万 DAU 再引入长序列、多目标和受约束探索**：召回服务分片，增加粗排，精排用 Mamba/HSTU 类长序列编码器或受延迟约束的 Transformer，MMoE/PLE 处理点击、收藏、停留、隐藏等目标，SlateQ/TwCF/Policy Gradient 只在日志策略、反事实评估和安全护栏成熟后灰度。HSTU 展示了超长序列和大规模生成式推荐的上限，但它是重基础设施方案，不是 MVP 默认项。[Mamba4Rec](https://arxiv.org/abs/2403.03900) · [HSTU](https://arxiv.org/abs/2402.17152) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) · [SlateQ](https://arxiv.org/abs/1905.12767)
4. **审美推荐必须把“公共审美”与“个人偏好残差”拆开**：公共头预测美感分布/技术质量，个性化头学习用户对风格、主题、构图和图像对的相对偏好；不能把 LAION/AVA 的平均分直接当作某个用户的喜好。NIMA 预测人类评分分布，PARA 专门把通用审美与个性化审美及丰富属性分开建模。[NIMA](https://arxiv.org/abs/1709.05424) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)
5. **核心北极星不应只有 CTR**：至少并列监控收藏/保存、有效停留、负反馈、次日回访和列表内多样性；上线决策采用 A/B，CUPED 降低方差，interleaving 只用于快速筛选排序器而不能替代长期 A/B。[CUPED](https://dl.acm.org/doi/10.1145/2433396.2433413) · [Netflix Interleaving](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55) · [Beyond-accuracy survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)

---

## 1. 目标架构：先定义系统边界

### 1.1 推荐链路

```text
客户端曝光/点击/停留/收藏/隐藏/分享
                 │
                 ▼
          事件采集与归因
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
离线湖仓/训练样本       Kafka → Flink → 在线特征
     │                       │
     ├── Item 多模态编码      ├── 最近会话/实时统计
     ├── User/Item Embedding  └── point-in-time 特征回灌
     └── 模型训练与注册
                 │
                 ▼
请求 → 多路召回 → 粗排 → 精排 → 重排/多样性/规则 → 曝光
       │          │      │            │
       │          │      │            ├── 去重/安全/创作者约束
       │          │      │            └── MMR/配额/探索
       │          │      └── pClick/pSave/pDwell/pHide 多目标
       │          └── 高吞吐轻模型，保留精排高价值候选
       └── 内容/协同/序列/热门/新图/探索候选
```

工业推荐普遍使用候选生成后再排序的漏斗：YouTube 原始系统将百万级语料缩到数百候选再用丰富特征排序；Pinterest Pixie 在 30 亿节点、170 亿边图上执行实时候选生成；美团公开了粗排承担“在效果接近精排的同时满足严格延迟”的工程矛盾。[YouTube DNN](https://research.google/pubs/pub45530) · [Pixie](https://arxiv.org/abs/1711.07601) · [美团粗排实践](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html)

### 1.2 为什么审美图片不是普通电商 CTR

| 特殊性 | 架构后果 | 证据 |
|---|---|---|
| 同一图像可同时由主题、色彩、风格、构图驱动偏好 | 物品必须保留多组 embedding/attribute，而不是压成一个不可解释分数 | [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |
| 公共审美与个人审美可能相反 | 用“公共美感 prior + personalized residual”，分别校准 | [NIMA](https://arxiv.org/abs/1709.05424) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |
| 隐式反馈歧义大：停留可能是喜欢，也可能是困惑 | 多目标建模；负反馈与显式 pair 需要独立标签，不只优化点击 | [MMoE](https://dl.acm.org/doi/10.1145/3219819.3220117) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) |
| 新图占比高且没有行为 | 内容 embedding 在上传时生成，先内容召回，再逐步切到协同信号 | [VBPR](https://arxiv.org/abs/1510.01784) · [CLIP](https://arxiv.org/abs/2103.00020) |
| 用户很难用星级准确表达审美 | onboarding 用二选一/多选一；线上训练用 pairwise ranking，比绝对分更贴近选择 | [BPR](https://arxiv.org/abs/1205.2618) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |

---

## 2. 经典 → SOTA：算法演进与选择边界

### 2.1 协同过滤：ItemCF / UserCF / MF / BPR

| 方法 | 核心机制 | 仍然值得用的场景 | 明确边界 | 原始来源 |
|---|---|---|---|---|
| UserCF | 根据相似用户的历史偏好投票 | 小社区、可解释“与你相似的人喜欢” | 用户数增大时邻居计算与兴趣漂移成本高；新用户无邻居 | [GroupLens/CF evaluation](https://dl.acm.org/doi/10.1145/963770.963772) |
| ItemCF | 预计算物品共现/相似度，再由用户已喜欢物品扩展 | MVP 强基线、related images、多路召回 | 新物品无共现；热门物品偏置 | [Sarwar et al., 2001](https://doi.org/10.1145/371920.372071) |
| Matrix Factorization | 将用户—物品矩阵分解为共享潜因子，点积预测偏好 | 交互量开始积累后的低成本协同召回/基线 | 很难直接消费图像内容；冷启动弱；静态因子难跟踪短期意图 | [Koren, Bell, Volinsky, 2009](https://doi.org/10.1109/MC.2009.263) |
| BPR-MF | 从隐式反馈构造 `(u, positive, negative)`，优化 pairwise ranking | 收藏/喜欢/二选一等隐式审美反馈 | 负样本若其实未曝光会带偏；不能单独解决曝光选择偏差 | [BPR](https://arxiv.org/abs/1205.2618) |

**阶段判断**：ItemCF 和 BPR-MF 不应被深度模型“一次性替换”。它们训练快、故障面小，适合作为召回路、冷备与回归基线；只有当内容、序列和多目标模型在时间切分离线评估及线上实验均稳定胜出后再降低流量。[Sarwar et al.](https://doi.org/10.1145/371920.372071) · [Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772)

### 2.2 双塔 / DSSM / YouTube DNN：将全库检索变成向量检索

- DSSM 把 query 与 document 映射到同一低维语义空间并用 cosine 匹配；推荐系统将两侧换成 user tower 与 item tower，即工业常说的双塔。[DSSM original paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/cikm2013_DSSM_fullversion.pdf)
- YouTube DNN 将系统拆成 candidate generation 和 ranking；候选模型使用用户历史/context 产生用户表示，排序模型再消费更丰富特征，并以 watch time 而非单纯 click 作为重要目标。[Google Research](https://research.google/pubs/pub45530)
- 双塔的优势是 item embedding 可离线计算并放入 ANN，在线仅编码用户；代价是 user-item 只在最终点积相遇，跨特征表达能力弱。因此它适合**召回**，不应直接承担最终精排。[YouTube DNN](https://research.google/pubs/pub45530) · [ScaNN](https://arxiv.org/abs/1908.10396)
- Meta 在 KDD 2025 的 MTMH 把 item-to-item 召回拆成 engagement head 与 relevance head，并用多任务损失联合优化共现召回和内容语义；论文在服务数十亿用户的平台数据上报告 Recall@500 最高提升 14.4%、语义相关性最高提升 56.6%，线上同时改善消费与长期体验指标。这一结果支持审美图片召回把“用户共现喜欢”与“内容真正相似”设为两个可观测目标，而不是只追 co-engagement。[MTMH, KDD 2025](https://doi.org/10.1145/3711896.3737255)

**审美系统落地**：item tower 输入 `SigLIP image embedding + caption/tag + aesthetic/style/composition attributes`；user tower 输入长期收藏画像、最近行为和 onboarding pair。输出 128–256 维向量，用 in-batch negatives + hard negatives 训练。SigLIP 的 pairwise sigmoid loss 不要求 CLIP 式全局 softmax 归一化，且论文表明 32K batch 后收益递减，为中期训练提供了更灵活的 batch 选择。[SigLIP](https://arxiv.org/abs/2303.15343)

### 2.3 DIN → DIEN → DSIN：候选感知注意力与兴趣演化

| 模型 | 解决的问题 | 机制 | 对本项目的用途 | 来源 |
|---|---|---|---|---|
| DIN | 固定用户向量无法针对当前候选激活相关兴趣 | local activation unit 对历史行为做 candidate-conditioned attention | 10 万 DAU 阶段精排首选；实现与延迟可控 | [DIN](https://arxiv.org/abs/1706.06978) |
| DIEN | 历史兴趣随时间变化，单次 attention 不够 | interest extractor + 辅助损失；interest evolving layer 建模与候选相关的演化 | 有稳定序列和足够正/负反馈后替代 DIN | [DIEN](https://arxiv.org/abs/1809.03672) |
| DSIN | 一段长历史包含多个语义不同 session | session 内 self-attention，session 间 Bi-LSTM，再对目标 item 激活 | 用户跨场景明显且 session 定义可靠时使用 | [DSIN](https://arxiv.org/abs/1905.06482) |

DIN 在阿里超过 20 亿样本的生产数据上验证，DIEN 报告淘宝线上 CTR 提升，DSIN 在广告与生产推荐数据上优于当时基线；这些结果证明机制可工业化，但不能直接外推本项目收益，仍需自己的时间切分和 A/B。[DIN](https://arxiv.org/abs/1706.06978) · [DIEN](https://arxiv.org/abs/1809.03672) · [DSIN](https://arxiv.org/abs/1905.06482)

### 2.4 长序列：GRU4Rec / SASRec / BST / MIMN / Mamba4Rec / HSTU

| 模型 | 时间/空间特性 | 优势 | 风险与使用时机 | 来源 |
|---|---|---|---|---|
| GRU4Rec | RNN 顺序扫描 | session-only 场景强基线；无长期用户 ID 也能工作 | 难并行；超长序列梯度与吞吐受限 | [GRU4Rec](https://arxiv.org/abs/1511.06939) |
| SASRec | self-attention，标准注意力随序列长度二次增长 | 论文中比 CNN/RNN 同类方法高效约一个数量级，并可观察相关历史 | 长序列显存/延迟上升；位置与时间间隔需另建模 | [SASRec](https://arxiv.org/abs/1808.09781) |
| BST | Transformer 直接编码行为序列用于电商排序 | 能建模行为顺序及跨行为关系，已在淘宝部署 | 在线精排延迟需严格约束；适合截断后的 recent sequence | [BST](https://arxiv.org/abs/1905.06874) |
| MIMN | 把超长历史压缩到固定大小外部 memory | 在线成本与原始序列长度解耦，支持上千行为 | memory 更新、版本一致性和 KV 成本复杂 | [MIMN](https://arxiv.org/abs/1905.09248) |
| Mamba4Rec | selective state-space model，线性序列建模 | 避免 attention 二次复杂度；2024 论文报告效果/效率同时优于 RNN 与注意力基线 | 生态、kernel、可解释性和线上成熟度低于 Transformer | [Mamba4Rec](https://arxiv.org/abs/2403.03900) |
| HSTU | 面向高基数、非平稳流数据的生成式 sequential transducer | 论文报告 8K 序列上快于 FlashAttention2 Transformer，并展示万亿参数部署 | 极高训练/服务门槛；只适合千万 DAU 后的专项平台投入 | [HSTU](https://arxiv.org/abs/2402.17152) |

**选择顺序**：先 `最近 N 次行为 + DIN`，再用 `SASRec/BST` 验证序列收益；只有 p95/p99 延迟、GPU 成本或上下文截断成为已量化瓶颈，才评估 `Mamba4Rec/MIMN`。HSTU 是规模上限参照，不是三阶段中的必选依赖。[DIN](https://arxiv.org/abs/1706.06978) · [Mamba4Rec](https://arxiv.org/abs/2403.03900) · [HSTU](https://arxiv.org/abs/2402.17152)

### 2.5 多任务：ESMM / MMoE / PLE

| 方法 | 核心结构 | 最适合解决 | 何时不用 | 来源 |
|---|---|---|---|---|
| ESMM | 在全部曝光空间联合建模 CTR 与 CTCVR，用概率关系导出 CVR；共享表示 | 点击后收藏/下载等稀疏下游行为，缓解 clicked-only sample selection bias 与稀疏性 | 目标不是严格漏斗关系时不能硬套乘法分解 | [ESMM](https://arxiv.org/abs/1804.07931) |
| MMoE | 多个共享 experts，每个任务有独立 gate | 点击、收藏、停留等相关但不完全一致的目标 | 数据少时 gate/expert 容易不稳定；冲突严重时共享污染 | [MMoE](https://dl.acm.org/doi/10.1145/3219819.3220117) |
| PLE | task-specific experts + shared experts 分层抽取，逐层减少负迁移 | 明显冲突目标，如 click 与 hide/report、短停留与长收藏 | 模型和调参成本高，不应在 MVP 使用 | [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) |

推荐的精排输出头：`p_click`、`p_save`、`E[dwell_capped]`、`p_share`、`p_hide`、`p_report`。最终效用不是固定写死的“加权 CTR”，而是版本化配置：

```text
utility = w1·p_save + w2·E[dwell_capped] + w3·p_share
          + w4·p_click - w5·p_hide - w6·p_report
```

权重必须由 A/B 与 guardrail 决定；MMoE/PLE 只能学习任务表示，不能替代产品层对负反馈、安全和多样性的硬约束。[MMoE](https://dl.acm.org/doi/10.1145/3219819.3220117) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236)

### 2.6 强化学习：DQN / Policy Gradient / TwCF / SlateQ

| 路线 | 能解决什么 | 生产前置条件 | 主要风险 | 来源 |
|---|---|---|---|---|
| DQN | 用 Q-learning 优化跨时刻长期回报 | 小且可控的离散动作空间或高质量 simulator | 百万物品动作空间不可直接枚举；离线外推误差 | [DQN](https://www.nature.com/articles/nature14236) |
| Policy Gradient / REINFORCE | 直接优化随机推荐策略，可处理采样动作 | 完整 propensity/logging policy 与 off-policy correction | 高方差、探索伤害、奖励投机 | [YouTube top-K off-policy REINFORCE](https://arxiv.org/abs/1812.02353) |
| TwCF | bandit exploration + counterfactual reasoning，用于 Twitter 时间线反馈闭环 | 能记录候选集、展示概率、延迟奖励并做反事实评估 | 社交时间线结论不可直接外推审美图片；探索需风险预算 | [Twitter RecSys workshop PDF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) |
| SlateQ | 在用户选择假设下，将 slate 长期价值分解成 item-wise LTV 的可处理函数 | 列表级 choice model、长期奖励、稳定实验平台 | 分解依赖用户选择假设；列表内相互作用建模仍可能偏 | [SlateQ](https://arxiv.org/abs/1905.12767) |

**决策**：阶段 1 不做 RL；阶段 2 只做受限 contextual bandit（例如新图候选池 1–5% 探索流量）；阶段 3 才在 logged propensity、IPS/DR 离线评估、shadow 与逐级 ramp 完备后尝试 SlateQ/Policy Gradient。YouTube 的 top-K off-policy correction 和 TwCF 均说明，生产 RL 的关键不只是网络结构，而是日志策略与反事实校正。[YouTube REINFORCE](https://arxiv.org/abs/1812.02353) · [TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf)

### 2.7 多模态推荐：VBPR → MMGCN → MMSSL → LGMRec

| 模型 | 多模态如何进入推荐 | 价值 | 局限/选型 | 来源 |
|---|---|---|---|---|
| VBPR | 预训练视觉特征经可学习层映射后，与 BPR 潜因子联合排序 | 简单、可扩展，明确缓解视觉物品冷启动 | 只建模视觉与线性偏好交互；不建模用户—物品高阶图 | [VBPR](https://arxiv.org/abs/1510.01784) |
| MMGCN | 在 user-item 图上按视觉/文本/音频等模态传播，再融合 | 利用高阶协同关系和模态偏好 | 图训练/更新成本高；新图仍需内容侧旁路 | [MMGCN official repo](https://github.com/Xun-Yang/MMGCN) · [ACM MM paper](https://dl.acm.org/doi/10.1145/3343031.3351034) |
| MMSSL | 对抗增强 + 模态感知图结构学习 + 跨模态对比学习 | 在稀疏标签下对齐协同视图与多模态语义 | 训练复杂；增益需与简单 two-tower/LightGCN 强基线比较 | [MMSSL](https://arxiv.org/abs/2302.10632) |
| LGMRec | 同时建模局部模态关系与全局模态语义 | 2024 的更强多模态图推荐候选 | 论文基准收益不等于线上收益；动态图更新与 serving 仍需自建 | [LGMRec, SIGIR 2024](https://dl.acm.org/doi/10.1145/3626772.3657833) |

**推荐顺序**：`预训练视觉/文本 embedding + BPR/two-tower` → `协同图召回` → `MMSSL/LGMRec 离线挑战者`。直接从 MMSSL/LGMRec 起步，会把“数据质量不够”和“模型结构不够”混在一起，且失去 VBPR/two-tower 可解释基线。[VBPR](https://arxiv.org/abs/1510.01784) · [MMSSL](https://arxiv.org/abs/2302.10632)

---

## 3. 工业架构证据与可复用模式

### 3.1 Pinterest：图召回 + 长短期用户表示

| 系统 | 公开规模/机制 | 可复用模式 | 来源 |
|---|---|---|---|
| Pixie | 30 亿节点、170 亿边图上的实时随机游走；论文报告单机 1,200 RPS、60 ms latency | related-image/兴趣图候选可用图随机游走，不一定先上 GNN | [Pixie](https://arxiv.org/abs/1711.07601) |
| PinSage | 30 亿节点、180 亿边，随机游走邻居采样 + graph convolution；训练 75 亿样本 | 大图训练必须采样；item embedding 可批量离线生成 | [PinSage](https://arxiv.org/abs/1806.01973) |
| PinnerFormer | 预测长期未来交互，批量生成长期用户 embedding，避免维护在线可变隐状态 | 长期兴趣适合日级 batch，降低实时 serving 成本 | [PinnerFormer](https://arxiv.org/abs/2205.04507) |
| TransAct | Transformer 编码实时短期动作，与 batch 长期 embedding 组成 hybrid ranking | 长期与短期分路，只有短序列进入在线重模型 | [TransAct](https://arxiv.org/abs/2306.00248) |

对本项目最值得复用的不是 Pinterest 的绝对规模，而是“**长期 batch 表示 + 短期实时序列 + 多路候选**”边界。这样能让上传新图、用户刚发生的审美转向和长期风格偏好各自以合适频率更新。[PinnerFormer](https://arxiv.org/abs/2205.04507) · [TransAct](https://arxiv.org/abs/2306.00248)

### 3.2 字节：Monolith 的实时训练边界

Monolith 为动态稀疏推荐特征设计 collisionless embedding table，并提供 expirable embedding 与 frequency filtering 控制内存；它打破“批训练—在线服务完全隔离”，在可靠性与实时学习之间做显式权衡。[Monolith](https://arxiv.org/abs/2209.07663) · [official repo](https://github.com/bytedance/monolith)

可复用结论：千万 DAU 前先追求**分钟级实时特征 + 小时/日级重训**；只有审美趋势变化速度确实让批训练失效，才引入参数级在线更新。实时更新必须具备去重、迟到事件、checkpoint、回放和模型回滚，否则“更实时”会变成更快地放大脏数据。[Monolith](https://arxiv.org/abs/2209.07663) · [Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/)

### 3.3 阿里：从候选感知到超长序列和树召回

- DIN/DIEN/DSIN 建立了 candidate-aware attention、兴趣演化和 session 分层建模的连续路线。[DIN](https://arxiv.org/abs/1706.06978) · [DIEN](https://arxiv.org/abs/1809.03672) · [DSIN](https://arxiv.org/abs/1905.06482)
- MIMN 将长历史压缩为固定 memory，并把用户兴趣 memory 放到外部存储增量维护，使在线成本不再随原始行为长度线性增长。[MIMN](https://arxiv.org/abs/1905.09248)
- TDM 将全库候选组织为可学习树，自顶向下检索，复杂度随 corpus 规模对数增长，并在淘宝展示广告线上验证。[TDM](https://arxiv.org/abs/1801.02294)

对本项目的优先级是 DIN → 长短期分路 → Mamba/MIMN；TDM 只有在内积 ANN 的表达上限被离线与线上同时证实时才值得投入，因为树构建、联合训练和在线路由都会增加系统复杂度。[DIN](https://arxiv.org/abs/1706.06978) · [TDM](https://arxiv.org/abs/1801.02294)

### 3.4 美团：粗排是独立的“效果—性能”层

美团公开实践显示，粗排从线性/LR 演进到双塔，并关注样本选择偏差、与精排联动、蒸馏和严格性能约束。粗排不是“缩小版精排的复制品”，它的优化目标是在高吞吐预算下尽量保持精排认为有价值的候选。[美团搜索粗排优化](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html)

本项目到 10 万 DAU 后的粗排建议：输入召回分、少量静态特征、最近行为摘要和内容质量特征；用小型 MLP/DCN 或蒸馏双塔，把数千候选缩到 200–500。粗排评估除 NDCG 外要加“精排 top-K 保留率”，否则粗排可能独立指标好却提前杀掉精排需要的候选。[美团搜索粗排优化](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html)

### 3.5 Meta：embedding 系统约束、双目标召回与生成式推荐上限

- DLRM 将 sparse categorical features 走 embedding tables、dense features 走 MLP，再用 pairwise dot-product interaction；其专用并行方式是 embedding 模型并行 + MLP 数据并行，直接揭示推荐训练的“内存带宽 + 计算”双重瓶颈。[DLRM](https://arxiv.org/abs/1906.00091)
- MTMH 用 engagement/relevance 双 head 和多任务损失处理 item-to-item 召回的 co-engagement—语义相关性冲突；2025 论文报告离线 Recall@500 和语义相关性提升，并通过生产 A/B 验证消费、兴趣发现、多样性与 freshness 指标。[MTMH](https://doi.org/10.1145/3711896.3737255)
- HSTU 将推荐重写为 sequential transduction；论文报告处理每日数百亿行为、部署 1.5T 参数模型，在 8,192 长度序列上相对 FlashAttention2 Transformer 有明显速度优势，并展示线上提升。[HSTU](https://arxiv.org/abs/2402.17152)

HSTU 给出的不是“现在就做 1.5T 模型”的建议，而是阶段 3 的架构方向：当数据、算力和多场景足以支撑统一基础推荐模型时，序列生成式训练可能替代多个割裂的召回/排序模型；此前仍应保持模块化漏斗和可回滚基线。[HSTU](https://arxiv.org/abs/2402.17152)

---

## 4. Embedding 训练、ANN 与在线 Serving

### 4.1 Item 表征契约

每张图像生成版本化对象：

```text
item_features = {
  semantic_embedding,      # CLIP/SigLIP: 主题、对象、文本语义
  aesthetic_distribution, # NIMA: 1..10 人类评分分布，而非只存均值
  style_attributes,        # 风格/色彩/媒介
  composition_attributes,  # 构图、景别、主体布局等可解释维度
  safety_quality_flags,
  creator_id, created_at, language, region,
  encoder_version, feature_timestamp
}
```

CLIP 用 4 亿图文对做对比预训练并支持自然语言零样本迁移；SigLIP 将 softmax 对比损失换成独立 pairwise sigmoid；NIMA 输出人类评分**分布**而非单个均值；PARA 提供个性化审美与 rich attributes 的任务定义。因此四类特征不可互相替代。[CLIP](https://arxiv.org/abs/2103.00020) · [SigLIP](https://arxiv.org/abs/2303.15343) · [NIMA](https://arxiv.org/abs/1709.05424) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)

### 4.2 Embedding 训练流水线

```text
原图/元数据
  → 安全与重复检测
  → CLIP/SigLIP 批量编码
  → aesthetic/style/composition heads
  → 版本化 Feature Registry
  → item tower 微调（曝光/点击/收藏/pair）
  → offline validation
  → 全量/增量 item embedding build
  → ANN shadow index
  → recall/latency validation
  → atomic index switch
```

训练负样本分三层：随机未互动、同主题 hard negative、已曝光但未选/明确隐藏。仅将“未见过”当负样本会把曝光机制偏差写入模型；BPR 的 pairwise 目标和 ANCE/ANN hard-negative 思路都说明负样本质量会改变排序边界。[BPR](https://arxiv.org/abs/1205.2618) · [ScaNN](https://arxiv.org/abs/1908.10396)

### 4.3 ANN 选型边界

| 规模 | 检索 | 原因 | 证据 |
|---|---|---|---|
| 千级物品 | exact cosine/dot product | 精确扫描简单，ANN 误差和运维没有收益 | [FAISS](https://arxiv.org/abs/1702.08734) |
| 10 万 DAU / 百万级物品 | HNSW 或 ScaNN/FAISS IVF，按真实向量 benchmark | 需要在 recall、p99、内存和更新速度间实测 | [ScaNN](https://arxiv.org/abs/1908.10396) · [FAISS](https://arxiv.org/abs/1702.08734) |
| 千万 DAU / 亿级物品 | 分片 ANN + 副本 + 热/冷层 + index versioning | 单索引故障域和全量重建时间不可接受 | [FAISS billion-scale](https://arxiv.org/abs/1702.08734) · [Pixie](https://arxiv.org/abs/1711.07601) |

ANN 必须同时验收 `Recall@K against exact`、p50/p95/p99、QPS、增量写入、删除可见性、全量 rebuild 时间和切换回滚；只看 ANN benchmark 的单一 QPS 不能代表推荐链路。[FAISS](https://arxiv.org/abs/1702.08734) · [ScaNN](https://arxiv.org/abs/1908.10396)

---

## 5. Kafka + Flink 实时特征、样本拼接与回灌

### 5.1 事件契约

每条曝光日志必须包含：

```text
request_id, user_id/device_id, event_time, ingest_time,
model_version, feature_version, candidate_set_hash,
item_id, position, retrieval_sources, retrieval_scores,
rank_score, exploration_probability/propensity,
client_context, experiment_buckets
```

后续动作日志必须用 `request_id + item_id` 关联，并保留事件时间与到达时间。TwCF、YouTube off-policy REINFORCE 和 SlateQ 都依赖知道当时策略及候选/展示行为；如果今天不记录 propensity 与候选上下文，未来无法可信地做反事实评估。[TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) · [YouTube REINFORCE](https://arxiv.org/abs/1812.02353) · [SlateQ](https://arxiv.org/abs/1905.12767)

### 5.2 双路数据流

```text
                         ┌→ Flink session/window aggregation
Client → Gateway → Kafka ┤      └→ Online Store (Redis/Cassandra)
                         │
                         └→ Object Store/Lakehouse
                                ├→ point-in-time training join
                                ├→ delayed-label attribution
                                └→ offline feature backfill
```

Uber Feature Store 将离线特征放在 Hive、在线特征放在 Cassandra，并通过流处理维护在线值，目标是同一时间点的线上/离线一致性；Uber 的 exactly-once 工程文章进一步说明实时事件处理和在线推理需要幂等与一致语义。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) · [Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/)

### 5.3 样本拼接的硬规则

1. **按 event time 做 point-in-time join**：样本只能读取曝光时已经存在的特征，禁止用未来累计值。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/)
2. **延迟标签分窗**：点击、收藏、分享、次日回访有不同成熟窗口；未成熟样本不能直接标 0。ESMM 的全空间建模展示了点击后转化稀疏和选择偏差的结构性问题。[ESMM](https://arxiv.org/abs/1804.07931)
3. **曝光去重与机器人过滤**：同一请求重试、客户端重复上报要幂等；exactly-once 或端到端幂等是实时回灌前置条件。[Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/)
4. **训练—服务同一特征定义**：DSL/UDF 只定义一次，分别生成 batch 与 stream 计算；Feature Store 记录 owner、TTL、schema、freshness 和 lineage。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/)
5. **回灌可重放**：原始 Kafka/lake 日志不可只保留聚合结果；模型故障与特征 bug 需要按版本回放。[Monolith](https://arxiv.org/abs/2209.07663)

---

## 6. 排序、重排、多样性与规则层

### 6.1 每层输入/输出

| 层 | 输入规模（建议量级） | 模型 | 输出/约束 | 依据 |
|---|---:|---|---|---|
| 多路召回 | 全库 → 每路 100–1,000 | content two-tower、ItemCF、graph、popular、fresh、follow、explore | 合并、source quota、去重 | [YouTube DNN](https://research.google/pubs/pub45530) · [Pixie](https://arxiv.org/abs/1711.07601) |
| 粗排 | 1,000–5,000 → 200–500 | distilled two-tower / small MLP | 高吞吐，最大化精排 top-K 保留 | [美团粗排](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html) |
| 精排 | 200–500 → 50–100 | DIN/DIEN/SASRec + MMoE/PLE | 多任务分数与校准概率 | [DIN](https://arxiv.org/abs/1706.06978) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) |
| 重排 | 50–100 → 20–50 | greedy constrained optimization / MMR / slate model | 多样性、创作者/主题配额、探索、安全 | [Novelty & Diversity](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) · [SlateQ](https://arxiv.org/abs/1905.12767) |
| 规则层 | 最终列表 | hard filters + policy | 审核、屏蔽、年龄/地区、频控、去重 | [Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full) |

### 6.2 可执行的多样性重排

```text
score(i | selected) = relevance(i)
                      - λ · max_similarity(i, selected)
                      + μ · novelty(i)
                      + ν · creator_coverage_gain(i)
```

其中 similarity 应优先用 style/theme embedding，而不是只用 item ID；这样能避免连续出现几乎相同构图或同一主题。λ/μ/ν 由实验决定，安全、拉黑、版权与创作者曝光上限作为硬约束，不允许被相关性分数抵消。[Novelty and Diversity in Recommender Systems](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) · [Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)

---

## 7. 评估体系

### 7.1 离线指标：定义与使用边界

设用户真实相关集合为 `G_u`，前 K 推荐为 `R_u@K`，`rel_j∈{0,1}` 或分级相关度。

| 指标 | 定义 | 适合回答 | 不足 | 来源 |
|---|---|---|---|---|
| Precision@K | `|R∩G| / K` | 前 K 有多少比例相关 | 当每用户正样本很少时抖动大 | [Microsoft Recommenders metrics](https://github.com/recommenders-team/recommenders/blob/main/recommenders/evaluation/python_evaluation.py) |
| Recall@K | `|R∩G| / |G|` | 候选召回是否漏掉用户会喜欢的图 | 不关心相关图在第 1 还是第 K 位 | [Microsoft Recommenders metrics](https://github.com/recommenders-team/recommenders/blob/main/recommenders/evaluation/python_evaluation.py) |
| Hit Rate@K | `1[R∩G≠∅]` 的用户均值 | leave-one-out 下是否命中至少一个 | 命中 1 个与多个相同；信息量低 | [Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772) |
| DCG/NDCG@K | `DCG=Σ(2^rel_j−1)/log2(j+1)`；除以理想 DCG | 位置与分级相关性是否正确 | 依赖 relevance 标签定义 | [Microsoft Recommenders metrics](https://github.com/recommenders-team/recommenders/blob/main/recommenders/evaluation/python_evaluation.py) |
| AP/MAP@K | 每次命中位置的 Precision 求均值，再跨用户平均 | 多个相关 item 的整体排序 | 正样本极少时与 Hit/Rank 指标趋同 | [Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772) |
| AUC | 随机正样本排在随机负样本前的概率 | pointwise/pairwise ranker 的全局区分 | 对最终 top-K 不够敏感；受负采样影响 | [Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772) |

**推荐验收组合**：召回层用 `Recall@100/500 + exact-ANN recall + coverage`；粗排用 `精排 top-K 保留率 + NDCG`；精排用 `NDCG@20 + MAP@20 + AUC + calibration`；重排另看 diversity/coverage/novelty。评价框架必须分层，否则一个端到端 NDCG 无法定位是哪层退化。[Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772)

### 7.2 离线切分与防“漂亮假指标”

- 使用按时间的 train/validation/test，用户历史只能看测试时点之前；随机切分会泄漏未来偏好。[Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772)
- 同时报告 warm user、new user、warm item、new item、head/tail、地区/语言切片；平均值会掩盖冷启动失败。[VBPR](https://arxiv.org/abs/1510.01784) · [Near cold-start](https://arxiv.org/abs/2307.14225)
- 如果评估只在 100 个 sampled negatives 中排名，必须固定采样协议并补全库评估；AUC/NDCG 会随负样本难度变化。[BPR](https://arxiv.org/abs/1205.2618)
- 图片 encoder 更新时分别报告“冻结旧索引”“全量重建新索引”“混合版本”结果，防止 embedding space 不兼容。[CLIP](https://arxiv.org/abs/2103.00020) · [FAISS](https://arxiv.org/abs/1702.08734)

### 7.3 在线 A/B、interleaving、CUPED

**A/B 主流程**：AA 校验 → 1% canary → 5% → 25% → 50%，每级检查数据完整性、延迟/错误率、安全投诉与核心业务 guardrail，再扩大。最终看预先注册的主指标，不能在大量指标中事后挑显著项。[CUPED paper](https://dl.acm.org/doi/10.1145/2433396.2433413)

**CUPED**：使用实验前与实验指标相关、且不受 treatment 影响的协变量 `X`，构造 `Y_cv = Y - θ(X-E[X])` 降低方差；协变量相关性越强，方差降低越明显。适合审美系统中用实验前 7/14 天收藏、停留或活跃度做协变量。[Deng et al., 2013](https://dl.acm.org/doi/10.1145/2433396.2433413)

**Interleaving**：把 A/B 两个排序器结果交错到同一列表，用用户选择判定偏好，通常比完整 A/B 更快筛出排序器差异；但它只适合比较同一候选空间内的排序质量，无法代替留存、生态、安全和长期效应 A/B。[Netflix Engineering](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55)

### 7.4 多样性、覆盖率、Novelty、Serendipity

| 指标 | 建议定义 | 注意点 | 来源 |
|---|---|---|---|
| Intra-list Diversity | `1 - avg_pairwise_similarity(items in list)` | similarity 用风格/主题 embedding 分开报告 | [Novelty & Diversity chapter](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) |
| Catalog Coverage | 评估期被推荐过的 distinct items / 可推荐 items | 需同时看曝光分布/Gini，避免“每项只露一次”虚高 | [Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full) |
| User Coverage | 收到至少 K 个合格推荐的用户占比 | 冷用户应单独切片 | [Herlocker et al.](https://dl.acm.org/doi/10.1145/963770.963772) |
| Novelty | 常用 `-log2(popularity(i)/total)` 的列表均值 | 过度 novelty 会伤害相关性，应与 relevance 联合看 | [Novelty & Diversity chapter](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) |
| Serendipity | 与用户历史/强基线不同、同时被用户判为相关的比例 | 没有“相关”就只是惊讶；需要显式反馈或反事实基线 | [Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full) |

---

## 8. 冷启动与长尾

### 8.1 新物品：多模态 embedding 先救场

上传时同步/准实时生成 `SigLIP/CLIP semantic embedding + aesthetic distribution + attributes`，进入 content ANN 与新图候选池；积累到足够曝光/收藏后，再逐步提高 collaborative score 权重。VBPR 的结论直接支持视觉特征缓解新物品冷启动；CLIP/SigLIP 则提供无需本域大量标签的初始语义空间。[VBPR](https://arxiv.org/abs/1510.01784) · [CLIP](https://arxiv.org/abs/2103.00020) · [SigLIP](https://arxiv.org/abs/2303.15343)

建议的置信度融合：

```text
final_item_score = confidence(n_interactions) · collaborative_score
                 + (1-confidence) · content_score
```

`confidence` 随有效曝光/显式反馈增长，而不是按“上线天数”增长；否则低曝光长尾永远无法获得可靠协同估计。多模态内容与协同图联合建模可参考 MMGCN/MMSSL，但早期采用显式置信度融合更易解释与回滚。[MMGCN](https://github.com/Xun-Yang/MMGCN) · [MMSSL](https://arxiv.org/abs/2302.10632)

### 8.2 新用户：引导式 onboarding + 原型 + CLUB

1. 首屏展示 8–20 组跨主题/风格/构图的二选一图片，优先挑信息增益高且安全的 pair；BPR 给出了从 pairwise 隐式偏好学习排序的标准目标。[BPR](https://arxiv.org/abs/1205.2618)
2. 将所选图片的多维 embedding 聚合成初始 user vector，同时保留明确“不喜欢”的负方向；不能只平均正样本。[CLIP](https://arxiv.org/abs/2103.00020)
3. 将新用户软分配到审美原型/cluster，借用群体 prior；CLUB 在线发现相似用户群并共享探索信息，论文给出 regret 分析与可扩展性证据。[CLUB](https://arxiv.org/abs/1401.8257)
4. 允许自然语言表达“喜欢低饱和胶片、不要人像”等偏好，编码后作为冷启动旁路。RecSys 2023 研究显示，在 near cold-start 条件下，LLM 基于语言偏好可与 item-based CF 竞争，但该证据不支持让 LLM 直接替代成熟协同推荐。[Near cold-start LLM](https://arxiv.org/abs/2307.14225)
5. 前 20–50 次有效动作快速更新短期向量；长期画像低学习率更新，避免一次偶然点击重写全部审美偏好。Pinterest 的 batch 长期表示 + realtime short sequence 是可复用模式。[PinnerFormer](https://arxiv.org/abs/2205.04507) · [TransAct](https://arxiv.org/abs/2306.00248)

### 8.3 长尾：曝光预算而非简单加分

- 为 fresh/tail 建独立召回通道与最小配额，在重排时控制总探索预算，而不是给所有长尾统一加分。[Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)
- 记录每个被探索候选的展示概率，才能用 IPS/DR 方法区分“没被看到”与“不被喜欢”；TwCF 和 YouTube off-policy work 都把 logging policy 作为核心。[TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) · [YouTube REINFORCE](https://arxiv.org/abs/1812.02353)
- 创作者覆盖和目录覆盖要作为生态 guardrail，但不能牺牲安全/明确负反馈；重排层做硬约束比在精排 loss 中隐式学习更可控。[Novelty & Diversity](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26)

---

## 9. 审美图片推荐的专用模型设计

### 9.1 视觉—语义对齐：CLIP / SigLIP / LLaVA 分工

| 模型 | 用途 | 不建议用途 | 证据 |
|---|---|---|---|
| CLIP | 图像/文本统一 embedding、zero-shot 标签、内容检索 | 直接当个人美感分数；CLIP 学的是图文对应而非个人审美 | [CLIP](https://arxiv.org/abs/2103.00020) |
| SigLIP | 默认 item semantic encoder；pairwise sigmoid 更易扩展和小 batch 训练 | 在无本域评估时仅因模型更新就替换 CLIP | [SigLIP](https://arxiv.org/abs/2303.15343) |
| LLaVA | 离线生成结构化 caption/候选解释/数据审查辅助 | 在线主排序 inner loop；生成解释不可作为事实，无校验会幻觉 | [LLaVA](https://arxiv.org/abs/2304.08485) |

**落地流程**：用 SigLIP 做稳定、可缓存的 dense embedding；用 LLaVA 离线产生 `subject/style/mood/composition` 候选标签，再由规则/小分类器校验并保存 provenance。召回与排序只消费已版本化特征，不在线调用 LLaVA 生成分数。[SigLIP](https://arxiv.org/abs/2303.15343) · [LLaVA](https://arxiv.org/abs/2304.08485)

### 9.2 四个可解释审美维度

| 维度 | 表征/监督 | 给用户的解释示例 | 来源 |
|---|---|---|---|
| 美感/质量 | NIMA 评分分布、均值、方差；技术质量单独头 | “符合你常收藏的高质感作品” | [NIMA](https://arxiv.org/abs/1709.05424) |
| 风格 | photographic/art style multi-label，颜色/媒介/时代属性 | “低饱和胶片风格” | [AVA](https://ieeexplore.ieee.org/document/6247954) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |
| 主题/语义 | SigLIP image-text embedding + taxonomy | “与你喜欢的建筑夜景相似” | [CLIP](https://arxiv.org/abs/2103.00020) · [SigLIP](https://arxiv.org/abs/2303.15343) |
| 构图 | composition attributes/subject layout/crop/negative space | “相似的居中留白构图” | [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |

解释必须来自实际参与打分的特征贡献，例如“style similarity +0.17、theme similarity +0.08”，再映射成模板；不能让 LLaVA 看图后自由编造推荐原因。[LLaVA](https://arxiv.org/abs/2304.08485) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)

### 9.3 “审美一致性 + 个性化 pair”的推荐头

建议把分数拆成：

```text
s(u,i) = α(u)·global_aesthetic(i)
       + β(u)·semantic_similarity(u,i)
       + γ(u)·style_similarity(u,i)
       + δ(u)·composition_similarity(u,i)
       + collaborative_residual(u,i)
       + freshness/quality terms
```

- `global_aesthetic(i)` 由 NIMA/AVA 类公共评分监督，只作为 prior；NIMA 预测评分分布，方差可用于不确定性而不只取均值。[NIMA](https://arxiv.org/abs/1709.05424)
- `α/β/γ/δ` 是用户级 gate，由 onboarding 与后续 pair 更新；PARA 的 personalized aesthetic + rich attributes 任务为这种拆分提供直接依据。[PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)
- `collaborative_residual` 用 BPR/双塔从真实选择学习“内容特征解释不了的偏好”。[BPR](https://arxiv.org/abs/1205.2618) · [VBPR](https://arxiv.org/abs/1510.01784)
- 对新用户只更新小 user embedding/gate，不微调整个视觉 backbone；有足够数据后再联合训练，降低 few-shot 过拟合风险。[PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)

pair 样本优先级：显式二选一 > 同请求点击/未点且有充分停留机会 > 收藏/隐藏构造 pair > 随机未曝光负样本。后者偏差最大，只应低权重使用；BPR 的 pairwise 学习与 off-policy 推荐论文都说明样本来自何种行为策略至关重要。[BPR](https://arxiv.org/abs/1205.2618) · [YouTube REINFORCE](https://arxiv.org/abs/1812.02353)

### 9.4 文化与群体偏差

AVA、LAION-Aesthetics 或通用视觉—语言预训练数据反映的是其采集平台与标注者分布，不等于所有地区、年龄与文化群体的审美。LAION 的官方 aesthetic predictor 只是 CLIP 特征上的线性估计器，因此尤其不能把其分数当作“客观美”。[LAION aesthetic predictor](https://github.com/LAION-AI/aesthetic-predictor) · [AVA](https://ieeexplore.ieee.org/document/6247954)

上线时分地区/语言/活跃度报告 calibration、positive rate、coverage、negative feedback；公共 aesthetic prior 的权重对新用户最高风险，应允许通过 onboarding 很快覆盖。[PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)

---

## 10. 模块清单 + 推荐技术选型

| 模块 | MVP：千级物品/单机 | 10 万 DAU | 千万 DAU | 技术依据 |
|---|---|---|---|---|
| 事件采集 | append-only DB/对象存储；完整 exposure/action schema | Kafka + schema registry | 多 region Kafka/Pulsar、分层保留与 replay | [TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) |
| 流处理 | 不需要；分钟级 job | Flink session/window + Redis | Flink 集群、exactly-once/幂等、跨 region | [Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/) |
| 离线存储 | PostgreSQL + Parquet | S3/OSS + Iceberg/Delta | 分区湖仓 + catalog + data quality | [Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) |
| Feature Store | PostgreSQL/Redis，手工版本 | Feast/自研 registry + online Redis | 多租户 feature platform、point-in-time join | [Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) |
| Item encoder | 预训练 SigLIP/CLIP 冻结；离线批量 | 本域 adapter/fine-tune + NIMA/attributes | 多版本 encoder、蒸馏、增量 build | [SigLIP](https://arxiv.org/abs/2303.15343) · [NIMA](https://arxiv.org/abs/1709.05424) |
| 内容召回 | exact vector scan/pgvector | HNSW/ScaNN；two-tower | 分片 ANN + 热冷层 + 原子索引切换 | [FAISS](https://arxiv.org/abs/1702.08734) · [ScaNN](https://arxiv.org/abs/1908.10396) |
| 协同召回 | ItemCF/BPR-MF | two-tower + ItemCF + graph 邻居 | 多路检索服务、图/序列/探索路 | [ItemCF](https://doi.org/10.1145/371920.372071) · [YouTube DNN](https://research.google/pubs/pub45530) |
| 粗排 | 无，直接精排全候选 | small MLP/distilled tower | CPU/GPU elastic pre-rank，按 source 校准 | [美团粗排](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html) |
| 精排 | 可解释线性/LightGBM/BPR | DIN/DIEN + ESMM/MMoE | PLE + SASRec/Mamba/MIMN，必要时 HSTU 专项 | [DIN](https://arxiv.org/abs/1706.06978) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) |
| 重排 | 去重 + style/theme MMR | 多约束 greedy + fresh/tail quota | slate optimizer + constrained bandit | [SlateQ](https://arxiv.org/abs/1905.12767) · [Novelty & Diversity](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) |
| 模型训练 | 单机 Python/PyTorch | GPU job + registry + scheduled retrain | 分布式训练、embedding PS、在线/近线更新 | [DLRM](https://arxiv.org/abs/1906.00091) · [Monolith](https://arxiv.org/abs/2209.07663) |
| Serving | 单 FastAPI 服务 + cache | 独立 recall/rank services，gRPC | multi-region cell、autoscaling、degradation | [Pixie](https://arxiv.org/abs/1711.07601) |
| 实验 | feature flag + user hash | A/B、CUPED、interleaving | 统一实验平台、sequential monitoring、长期 holdout | [CUPED](https://dl.acm.org/doi/10.1145/2433396.2433413) · [Netflix Interleaving](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55) |
| 监控 | 请求/分数/覆盖人工 dashboard | data/model/service SLO | 分 region/slice、drift、自动 rollback | [Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) |

---

## 11. 三阶段路线图

## 阶段 A：MVP——千级物品、单机（0 → PMF）

### 目标与边界

- 目标：验证“用户愿意通过 pair/收藏表达审美，系统能在 1–3 个 session 内明显个性化”。语言偏好在 near cold-start 有潜力，pairwise BPR 是成熟的隐式排序目标。[Near cold-start](https://arxiv.org/abs/2307.14225) · [BPR](https://arxiv.org/abs/1205.2618)
- 物品规模：1K–100K；单机 exact scan 或 pgvector 足够，避免 ANN 和流平台过早复杂化。[FAISS](https://arxiv.org/abs/1702.08734)
- 非目标：不做 RL、MMoE/PLE、实时参数训练、分布式图推荐和跨 region。

### 建议架构

```text
Upload → offline SigLIP/NIMA/attribute extraction → Postgres/pgvector
                                                    │
User onboarding pairs → initial user vector         │
                                                    ▼
Request → [content exact + popular + fresh + ItemCF] → score
        → style/theme diversity + safety filters → response
        → append-only exposure/action logs
```

### 关键技术决策

1. **默认 encoder 用 SigLIP，保留 CLIP benchmark**；二者都先冻结，避免少量域内数据破坏通用空间。[CLIP](https://arxiv.org/abs/2103.00020) · [SigLIP](https://arxiv.org/abs/2303.15343)
2. **公共美感只作 prior**；排序由用户 pair 的 style/theme/composition gate 主导。[NIMA](https://arxiv.org/abs/1709.05424) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)
3. **召回保持 4 路**：content、popular、fresh、ItemCF；每路分数先分别归一化，记录 source。[ItemCF](https://doi.org/10.1145/371920.372071)
4. **日志一次做对**：必须记录 exposure、position、候选来源、模型/feature 版本和后续动作；这是未来反事实与样本拼接的不可补录资产。[TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf)

### 验收门槛

- 离线：时间切分 `Recall@20、NDCG@20、pair accuracy`；new-user/new-item 单独报告。[Herlocker](https://dl.acm.org/doi/10.1145/963770.963772)
- 产品：onboarding 完成率、前 20 次曝光至少一次收藏/喜欢、有效负反馈率、D1 回访；不能只看 CTR。[Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)
- 多样性：style/theme intra-list diversity 与 catalog coverage 同时报。[Novelty & Diversity](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26)

### 主要风险

| 风险 | 处理 | 依据 |
|---|---|---|
| 通用 aesthetic score 压过个人偏好 | 低权重 prior；pair 后快速衰减 prior 权重 | [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) |
| 误把未曝光 item 当负样本 | 显式 pair 与已曝光负样本高权重；随机负样本低权重 | [BPR](https://arxiv.org/abs/1205.2618) |
| 列表连续同质图 | style/theme 两个 embedding 分别做 MMR | [Novelty & Diversity](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26) |
| encoder 版本混用 | embedding 与索引带 version；全量原子切换 | [FAISS](https://arxiv.org/abs/1702.08734) |

### 所需工程能力

Python/PyTorch 推理、基础数据建模、可复现实验、图片安全/版权流水线、推荐日志与简单产品实验；不需要专职分布式系统团队。

---

## 阶段 B：10 万 DAU——标准漏斗与实时特征

### 进入条件

只有当 MVP 已有稳定 exposure/action 日志、日新增内容、单机延迟或训练周期出现量化瓶颈，才进入本阶段。YouTube/Pinterest 的系统证据都显示，漏斗和长短期分路是在语料与请求规模需要时形成，而不是算法清单驱动。[YouTube DNN](https://research.google/pubs/pub45530) · [PinnerFormer](https://arxiv.org/abs/2205.04507)

### 建议架构

```text
Clients → Kafka → Lakehouse ───────────→ batch training / embeddings
            └→ Flink → Online Features ───────────────┐
                                                      ▼
Gateway → multi-recall ANN/ItemCF/fresh/graph → small pre-rank
        → DIN/DIEN + ESMM/MMoE fine-rank → constrained rerank
        → response/logging → A/B platform
```

### 关键技术决策

1. **召回模型升级 two-tower**，item embeddings 离线计算，在线 user tower + ANN；保留 ItemCF/content/fresh 作为独立来源和降级路径。[YouTube DNN](https://research.google/pubs/pub45530)
2. **增加独立粗排**，目标包含精排 top-K 保留率；用小 MLP 或从精排蒸馏，不把复杂序列模型放入数千候选 loop。[美团粗排](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html)
3. **精排从 DIN 起**；有明确“点击→收藏/下载”漏斗时加 ESMM；多个平行目标先 MMoE，确认负迁移后才 PLE。[DIN](https://arxiv.org/abs/1706.06978) · [ESMM](https://arxiv.org/abs/1804.07931) · [MMoE](https://dl.acm.org/doi/10.1145/3219819.3220117)
4. **Kafka + Flink 做分钟/秒级行为特征，不立刻做参数在线学习**；训练仍小时/日级，先保证 point-in-time correctness。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) · [Monolith](https://arxiv.org/abs/2209.07663)
5. **长期画像 batch、短期 session realtime**，复用 PinnerFormer + TransAct 模式，避免所有历史进入在线 Transformer。[PinnerFormer](https://arxiv.org/abs/2205.04507) · [TransAct](https://arxiv.org/abs/2306.00248)
6. **建立 A/B + CUPED**，interleaving 用于同候选排序器快速筛选，最终决策仍看 A/B 长期指标。[CUPED](https://dl.acm.org/doi/10.1145/2433396.2433413) · [Netflix Interleaving](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55)

### SLO 与验收

- 推荐服务：明确 p50/p95/p99、超时、空结果、降级率；候选/粗排/精排分别有 latency budget。Pixie 的生产案例证明实时候选系统需用吞吐与尾延迟共同验收。[Pixie](https://arxiv.org/abs/1711.07601)
- 数据：event completeness、迟到率、重复率、feature freshness、training-serving skew。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/)
- 模型：分层 Recall/NDCG、calibration、new-user/new-item、head/tail 与 embedding drift。[Herlocker](https://dl.acm.org/doi/10.1145/963770.963772) · [VBPR](https://arxiv.org/abs/1510.01784)
- 在线：收藏/有效停留/负反馈/D1 或 D7 guardrail；创作者覆盖与列表多样性不下降。[Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)

### 主要风险

| 风险 | 处理 | 依据 |
|---|---|---|
| online/offline feature skew | 一份 feature 定义，point-in-time join，线上/离线值抽样对账 | [Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) |
| 实时流重复/乱序 | event-time watermark、幂等 key、checkpoint/replay | [Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/) |
| 多任务负迁移 | 先 shared-bottom/MMoE，按任务梯度/指标诊断后再 PLE | [MMoE](https://dl.acm.org/doi/10.1145/3219819.3220117) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) |
| ANN 更新期间召回错乱 | shadow build、exact subset 对比、atomic switch、旧索引回滚 | [FAISS](https://arxiv.org/abs/1702.08734) |
| 新图被热门闭环压制 | fresh 独立召回配额 + propensity logging | [TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) |

### 所需工程能力

数据平台（Kafka/Flink/湖仓）、ML platform（feature/model registry、训练编排）、ANN/embedding serving、推荐后端与缓存、实验统计、SRE 与 on-call、数据治理和图片安全审核。

---

## 阶段 C：千万级 DAU——分布式多阶段、多目标与受约束长期优化

### 建议架构

```text
Multi-region ingress
  → regional candidate cells
      ├ content ANN shards
      ├ collaborative/two-tower shards
      ├ graph/sequence retrieval
      ├ follow/popular/fresh/explore
      └ cache/degraded candidates
  → CPU/GPU elastic pre-rank
  → sequence + PLE fine-rank
  → constrained slate rerank
  → policy/safety/frequency layer
  → exposure log with propensity

Global control plane:
feature registry · model/index registry · training · experiments · observability · rollback
```

### 关键技术决策

1. **Cell 化隔离故障域**：ANN、特征与 rank serving 按 region/cell 部署；每 cell 有热门/内容降级候选。Pixie 和 FAISS 的规模证据说明大规模检索必须把吞吐、内存和索引故障域纳入设计。[Pixie](https://arxiv.org/abs/1711.07601) · [FAISS](https://arxiv.org/abs/1702.08734)
2. **长序列按瓶颈选择**：如果 attention p99/显存先到上限，评估 Mamba4Rec；如果超长历史存取是瓶颈，评估 MIMN；如果多个 surface、数据和算力足以支撑统一生成式模型，再立项 HSTU 类架构。[Mamba4Rec](https://arxiv.org/abs/2403.03900) · [MIMN](https://arxiv.org/abs/1905.09248) · [HSTU](https://arxiv.org/abs/2402.17152)
3. **多目标升级 PLE**：shared/task-specific experts 减少 click、save、dwell、hide 等目标的负迁移；模型输出先校准，再进入产品效用和硬约束层。[PLE](https://dl.acm.org/doi/10.1145/3383313.3412236)
4. **实时性分层**：秒级特征、分钟级 user embedding、小时级轻量模型、日级大模型；仅对高价值动态 sparse embeddings 试在线更新。Monolith 明确展示实时学习与可靠性的权衡。[Monolith](https://arxiv.org/abs/2209.07663)
5. **RL 只做受约束增量**：先新图/长尾 contextual bandit，再 slate LTV；必须记录 propensity，做 off-policy evaluation，shadow 后小流量 ramp。[TwCF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf) · [SlateQ](https://arxiv.org/abs/1905.12767)
6. **多模态图模型作为 challenger**：MMSSL/LGMRec 只有在相同 encoder、负样本和训练预算下稳定胜过 two-tower/graph baseline，才进入生产召回。[MMSSL](https://arxiv.org/abs/2302.10632) · [LGMRec](https://dl.acm.org/doi/10.1145/3626772.3657833)

### 主要风险

| 风险 | 处理 | 依据 |
|---|---|---|
| 万亿 embedding 内存/通信 | embedding 模型并行、频率过滤、TTL、hot/cold tier | [DLRM](https://arxiv.org/abs/1906.00091) · [Monolith](https://arxiv.org/abs/2209.07663) |
| 推荐闭环让审美单一化 | 长期 holdout、多样性/coverage guardrails、独立探索池 | [Multi-objective survey](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full) |
| RL reward hacking | capped rewards、负反馈硬惩罚、安全约束、离线 OPE、逐级 ramp | [YouTube REINFORCE](https://arxiv.org/abs/1812.02353) · [SlateQ](https://arxiv.org/abs/1905.12767) |
| 跨 region 数据/模型不一致 | event/model/index version、幂等回放、cell 级 rollback | [Uber Exactly-Once](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/) |
| 文化偏差被规模放大 | 按地区/语言切片校准；公共审美 prior 可覆盖；用户控制 | [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html) · [LAION predictor](https://github.com/LAION-AI/aesthetic-predictor) |
| 大模型收益追不上成本 | 每次升级报告 quality/latency/cost Pareto；保留 DIN/two-tower baseline | [HSTU](https://arxiv.org/abs/2402.17152) · [DIN](https://arxiv.org/abs/1706.06978) |

### 所需工程能力

分布式训练与 embedding parameter server、GPU/CPU serving 性能工程、跨 region 流与数据治理、feature/model/index control plane、实验因果推断、bandit/RL/OPE、可靠性工程、隐私合规、创作者生态与 Trust & Safety。

---

## 12. 阶段 Gate：什么时候允许升级

| 升级 | 必须先看到的证据 | 不满足时保持 |
|---|---|---|
| exact → ANN | exact scan p99/QPS 或成本已超预算；ANN 对 exact 的 Recall@K 达标 | exact/pgvector |
| 单路内容 → two-tower | 协同交互足够，时间切分对 new/warm slices 均有增益 | content + ItemCF |
| 无粗排 → 粗排 | 召回候选数让精排延迟/成本超预算 | 直接精排 |
| DIN → SASRec/Mamba | 长序列在离线与线上同时带来收益，且延迟/显存可控 | DIN + recent sequence |
| MMoE → PLE | 已观察并量化任务负迁移 | MMoE |
| batch → online learning | 模型陈旧性而非特征陈旧性已被证明是主要损失 | realtime features + batch retrain |
| supervised → RL | propensity logging、OPE、reward/guardrail、rollback 全部就绪 | constrained bandit/重排规则 |
| two-tower/graph → HSTU | 多场景统一模型的收益覆盖训练、服务、组织成本 | 模块化漏斗 |

上述 gate 分别来自 ANN 的 recall/latency 权衡、DIN/Mamba/HSTU 的序列复杂度、MMoE/PLE 的任务关系、Monolith 的实时可靠性权衡和 off-policy RL 的日志要求。[FAISS](https://arxiv.org/abs/1702.08734) · [Mamba4Rec](https://arxiv.org/abs/2403.03900) · [PLE](https://dl.acm.org/doi/10.1145/3383313.3412236) · [Monolith](https://arxiv.org/abs/2209.07663) · [YouTube REINFORCE](https://arxiv.org/abs/1812.02353)

---

## 13. 推荐的首年实施顺序

1. **第 0–2 月**：事件字典、曝光日志、图片安全与 encoder version；SigLIP/CLIP/NIMA 批量特征；onboarding pair；exact/content + popular/fresh/ItemCF。[SigLIP](https://arxiv.org/abs/2303.15343) · [BPR](https://arxiv.org/abs/1205.2618)
2. **第 2–4 月**：时间切分评估、new user/item slices、style/theme MMR、基础 A/B；把公共美感和个性 residual 分离。[NIMA](https://arxiv.org/abs/1709.05424) · [PARA](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)
3. **第 4–6 月**：two-tower + ANN shadow；hard negatives；recall source calibration；模型/索引 registry。[YouTube DNN](https://research.google/pubs/pub45530) · [ScaNN](https://arxiv.org/abs/1908.10396)
4. **第 6–9 月**：Kafka/Flink、point-in-time samples、online feature store；小粗排 + DIN；CUPED。[Uber Feature Store](https://www.uber.com/en-US/blog/scaling-ml-feature-store/) · [DIN](https://arxiv.org/abs/1706.06978) · [CUPED](https://dl.acm.org/doi/10.1145/2433396.2433413)
5. **第 9–12 月**：ESMM/MMoE 多目标、长期 batch + 短期 realtime user representation、fresh/tail constrained exploration；只在指标证明需要时评估 PLE/Mamba。[ESMM](https://arxiv.org/abs/1804.07931) · [PinnerFormer](https://arxiv.org/abs/2205.04507) · [Mamba4Rec](https://arxiv.org/abs/2403.03900)

---

## 14. 来源索引（53 项）

### 经典、召回、序列与多任务

1. Sarwar et al., *Item-Based Collaborative Filtering Recommendation Algorithms*, WWW 2001 — [ACM](https://doi.org/10.1145/371920.372071)
2. Koren, Bell, Volinsky, *Matrix Factorization Techniques for Recommender Systems*, 2009 — [PDF](https://doi.org/10.1109/MC.2009.263)
3. Rendle et al., *Bayesian Personalized Ranking from Implicit Feedback* — [arXiv](https://arxiv.org/abs/1205.2618)
4. Huang et al., *Learning Deep Structured Semantic Models for Web Search using Clickthrough Data* — [Microsoft Research PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/cikm2013_DSSM_fullversion.pdf)
5. Covington et al., *Deep Neural Networks for YouTube Recommendations*, 2016 — [Google Research](https://research.google/pubs/pub45530)
6. Zhou et al., *Deep Interest Network*, 2017/2018 — [arXiv](https://arxiv.org/abs/1706.06978)
7. Zhou et al., *Deep Interest Evolution Network*, 2018/2019 — [arXiv](https://arxiv.org/abs/1809.03672)
8. Feng et al., *Deep Session Interest Network*, 2019 — [arXiv](https://arxiv.org/abs/1905.06482)
9. Hidasi et al., *Session-based Recommendations with Recurrent Neural Networks*, 2015/2016 — [arXiv](https://arxiv.org/abs/1511.06939)
10. Kang & McAuley, *Self-Attentive Sequential Recommendation*, 2018 — [arXiv](https://arxiv.org/abs/1808.09781)
11. Chen et al., *Behavior Sequence Transformer for E-commerce Recommendation in Alibaba*, 2019 — [arXiv](https://arxiv.org/abs/1905.06874)
12. Liu et al., *Mamba4Rec*, 2024 — [arXiv](https://arxiv.org/abs/2403.03900)
13. Pi et al., *Practice on Long Sequential User Behavior Modeling for CTR Prediction (MIMN)*, 2019 — [arXiv](https://arxiv.org/abs/1905.09248)
14. Ma et al., *MMoE*, 2018 — [ACM](https://dl.acm.org/doi/10.1145/3219819.3220117)
15. Tang et al., *Progressive Layered Extraction*, 2020 — [ACM](https://dl.acm.org/doi/10.1145/3383313.3412236)
16. Ma et al., *Entire Space Multi-Task Model*, 2018 — [arXiv](https://arxiv.org/abs/1804.07931)

### 强化学习与反事实

17. Mnih et al., *Human-level control through deep reinforcement learning*, 2015 — [Nature](https://www.nature.com/articles/nature14236)
18. Chen et al., *Top-K Off-Policy Correction for a REINFORCE Recommender System*, 2018 — [arXiv](https://arxiv.org/abs/1812.02353)
19. Ie et al., *Reinforcement Learning for Slate-based Recommender Systems (SlateQ)*, 2019 — [arXiv](https://arxiv.org/abs/1905.12767)
20. Twitter, *Reinforcement Learning Deployed in Twitter's Timeline Feed (TwCF)*, 2020 — [RecSys workshop PDF](https://recsys.acm.org/2020/wp-content/uploads/2020/08/RL-Deployed-in-Twitter-Feed-_-Joint-Workshop-RecSys-2020.pdf)
21. Gentile et al., *Online Clustering of Bandits (CLUB)*, 2014 — [arXiv](https://arxiv.org/abs/1401.8257)

### 多模态推荐与视觉审美

22. He & McAuley, *VBPR*, 2016 — [arXiv](https://arxiv.org/abs/1510.01784)
23. Yang et al., *MMGCN*, 2019 — [official repo](https://github.com/Xun-Yang/MMGCN) · [ACM](https://dl.acm.org/doi/10.1145/3343031.3351034)
24. Wei et al., *MMSSL*, WWW 2023 — [arXiv](https://arxiv.org/abs/2302.10632)
25. Guo et al., *LGMRec*, SIGIR 2024 — [ACM](https://dl.acm.org/doi/10.1145/3626772.3657833)
26. Radford et al., *CLIP*, 2021 — [arXiv](https://arxiv.org/abs/2103.00020)
27. Zhai et al., *SigLIP*, 2023 — [arXiv](https://arxiv.org/abs/2303.15343)
28. Liu et al., *Visual Instruction Tuning (LLaVA)*, 2023 — [arXiv](https://arxiv.org/abs/2304.08485)
29. Murray et al., *AVA: A Large-Scale Database for Aesthetic Visual Analysis*, 2012 — [IEEE](https://ieeexplore.ieee.org/document/6247954)
30. Talebi & Milanfar, *NIMA*, 2017 — [arXiv](https://arxiv.org/abs/1709.05424)
31. LAION-AI, *Aesthetic Predictor* — [official GitHub](https://github.com/LAION-AI/aesthetic-predictor)
32. Yang et al., *Personalized Image Aesthetics Assessment with Rich Attributes*, CVPR 2022 — [CVF](https://openaccess.thecvf.com/content/CVPR2022/html/Yang_Personalized_Image_Aesthetics_Assessment_With_Rich_Attributes_CVPR_2022_paper.html)
33. Sanner et al., *Large Language Models are Competitive Near Cold-start Recommenders*, RecSys 2023 — [arXiv](https://arxiv.org/abs/2307.14225)

### 工业架构与检索

34. Eksombatchai et al., *Pixie*, 2017/2018 — [arXiv](https://arxiv.org/abs/1711.07601)
35. Ying et al., *Graph Convolutional Neural Networks for Web-Scale Recommender Systems (PinSage)*, 2018 — [arXiv](https://arxiv.org/abs/1806.01973)
36. Pancha et al., *PinnerFormer*, 2022 — [arXiv](https://arxiv.org/abs/2205.04507)
37. Xia et al., *TransAct*, KDD 2023 — [arXiv](https://arxiv.org/abs/2306.00248)
38. Liu et al., *Monolith*, 2022 — [arXiv](https://arxiv.org/abs/2209.07663) · [official GitHub](https://github.com/bytedance/monolith)
39. Zhu et al., *Learning Tree-based Deep Model for Recommender Systems*, KDD 2018 — [arXiv](https://arxiv.org/abs/1801.02294)
40. Naumov et al., *DLRM*, 2019 — [arXiv](https://arxiv.org/abs/1906.00091)
41. Zhai et al., *Actions Speak Louder than Words: HSTU*, ICML 2024 — [arXiv](https://arxiv.org/abs/2402.17152)
42. 美团技术团队，*搜索粗排优化探索实践*, 2022 — [官方博客](https://tech.meituan.com/2022/08/11/Coarse-Ranking-Exploration-Practice.html)
43. Uber, *Scaling Machine Learning at Uber with Michelangelo's Feature Store* — [official blog](https://www.uber.com/en-US/blog/scaling-ml-feature-store/)
44. Uber, *Real-time Exactly-Once Event Processing & Real-time Model Inference* — [official blog](https://www.uber.com/blog/real-time-exactly-once-event-processing-real-time-model-inference/)
45. Johnson et al., *Billion-scale similarity search with GPUs (FAISS)*, 2017 — [arXiv](https://arxiv.org/abs/1702.08734)
46. Guo et al., *Accelerating Large-Scale Inference with Anisotropic Vector Quantization (ScaNN)*, 2020 — [arXiv](https://arxiv.org/abs/1908.10396)
47. Zhang et al., *Optimizing Recall or Relevance? A Multi-Task Multi-Head Approach for Item-to-Item Retrieval in Recommendation (MTMH)*, KDD 2025 — [ACM](https://doi.org/10.1145/3711896.3737255)

### 评估、实验与 beyond-accuracy

48. Herlocker et al., *Evaluating Collaborative Filtering Recommender Systems*, 2004 — [ACM](https://dl.acm.org/doi/10.1145/963770.963772)
49. Microsoft Recommenders, ranking/diversity evaluation implementation — [official GitHub](https://github.com/recommenders-team/recommenders/blob/main/recommenders/evaluation/python_evaluation.py)
50. Deng et al., *Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data (CUPED)*, 2013 — [ACM](https://dl.acm.org/doi/10.1145/2433396.2433413)
51. Netflix Engineering, *Interleaving in Online Experiments at Netflix* — [official blog](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55)
52. Jannach et al./Frontiers, *A Survey on Multi-objective Recommender Systems*, 2023 — [Frontiers](https://www.frontiersin.org/articles/10.3389/fdata.2023.1157899/full)
53. Castells et al., *Novelty and Diversity in Recommender Systems* — [Springer](https://link.springer.com/chapter/10.1007/978-1-4899-7637-6_26)

---

## 最终决策摘要

- **现在做**：正确日志、pair onboarding、多维内容 embedding、公共审美/个性残差解耦、4 路轻召回、可解释多样性重排、时间切分评估。
- **到 10 万 DAU 做**：two-tower + ANN、独立粗排、DIN/ESMM/MMoE、Kafka/Flink/Feature Store、CUPED A/B、长期 batch + 短期 realtime。
- **到千万 DAU 做**：cell 化检索、长序列 Mamba/MIMN/HSTU 按瓶颈选、PLE、多模态图 challenger、受约束 bandit/SlateQ、跨 region control plane。
- **始终不做**：把通用美感分当个人喜好；只优化 CTR；未记录 exposure/propensity 就做 RL；没有 exact baseline 就上 ANN；没有量化负迁移就上 PLE；没有成本—收益证据就追逐万亿参数。
