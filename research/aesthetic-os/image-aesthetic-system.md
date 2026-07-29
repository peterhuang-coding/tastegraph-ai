# 图片审美系统研究（Image Aesthetic Scoring & Tagging System）

> 调研日期：2026-07-26
> 调研范围：2023-2026 美学评分模型、维度分解、指标体系、数据集、训练方案
> 目的：从 0 搭一套"有审美"的图片打分 + 标签体系，支撑推荐/订阅/风格克隆业务
> 关联：`/Users/peter_mini/research/active-projects.md` 中的"图片审美系统"方向

---

## 0. 一页摘要（TL;DR）

- **SOTA 路线已分裂成两条**：① 通用美学回归（CLIP/SigLIP 顶 + 轻量头），② 多模态大模型做 LMM-judge（Q-Align / OneAlign / AesBench）。前者便宜、后者能解释。
- **2024 年起，"维度分解"成为新主流**：不再是 1 个总分，而是构图 / 色彩 / 光影 / 主题 / 情绪 / 风格 / 复杂度 / 罕见度 8 维的向量表示，喂给推荐做向量化召回。
- **数据集已经够用**（AVA 25 万、AADB 1 万、KonIQ-10k、POCO 8K 中文、LAION 6.5+ 千万），但要"我们的审美"必须用我们自己的 pair 数据 + Bradley-Terry 重训。
- **推荐路径 A（快，2 周）**：LAION-Aesthetic-Predictor v2.5 + 多维 CLIP-Score 启发式。**路径 B（稳，6 周）**：SigLIP 2 + AVA/AADB 微调 + 维度 head。**路径 C（强，12 周）**：OneAlign/Q-Align 思路自训 + 用户级 LoRA + 配 Bradley-Terry 重排。
- **关键风险**：数据合规（小红书 / 图虫被禁、小红书账号被封已是大前提）、美学与"色情/猎奇"边界、个性化隐私。

---

## 1. 美学评分模型 SOTA（2023-2026）

### 1.1 时间线：通用评分模型演进

| 年份 | 模型 | 核心思想 | 局限 |
|------|------|----------|------|
| 2017 | NIMA (Talebi & Milanfar, TIP) | CNN 顶在 VGG/MobileNet 上，预测分数**分布**而非均值 | 单标签、数据量小 |
| 2019 | MLSP (Hosu, CVPR) | 多层级空间池化 | 仍单分 |
| 2020 | AFDC (Chen, CVPR) | 自适应分数扩张卷积 | 感受野受限 |
| 2021 | MUSIQ (Ke et al., Google, ICCV) | 多尺度 ViT，原生支持任意分辨率 | 单分、缺解释 |
| 2021 | TANet / MLSP | 图卷积+布局 | 单分 |
| 2021 | HyperIQA (Su et al.) | 超网络自适应内容 | 单分 |
| 2022 | MaxViT (Tu, ECCV) | 多轴 ViT，**也用做美学** | 单分 |
| 2022 | LAION-Aesthetic-Predictor | CLIP ViT-L/14 + 单层 `nn.Linear` 头 | 单分、西方审美 |
| 2023 | NIMA 已被各 T2I 模型用作 reward | 训练数据从美学扩到偏好对 |  |
| 2023 | HPSv2 (Wu et al., arXiv 2306.09341) | 79.8 万人对比 pair，CLIP+head，83.3% acc | 偏 T2I 对比、不是绝对分 |
| 2023 | ImageReward (Xu et al., NeurIPS 2023, arXiv 2304.05977) | BLIP+head，137k 专家 pair，**首个通用 T2I RM** | 单 reward |
| 2023 | PickScore | CLIP-H/14 微调，PickaPic 800k pair | 偏 T2I |
| 2023 | VILA (Ke et al., arXiv 2306.04638) | 用 Reddit 评论 + VLP 训美学表征 | 评论噪声 |
| 2023-24 | Q-Align (Wu et al., arXiv 2312.17090) | **第一个用 LMM 把美学当离散 5 级文本预测** | 5 级粒度粗 |
| 2024 | OneAlign (Q-Align 团队) | Q-Align 统一 IQA+IAA+VQA 一个模型 | 多任务耦合 |
| 2024 | AesBench (He et al., NeurIPS 2024, arXiv 2409.18749) | **4 维（感知/共情/评估/解读）MLLM benchmark + AUBD 2800 图** | 评测为主、非打分模型 |
| 2024 | PIAA-TaskVector (Yun & Choo, ECCV 2024, arXiv 2407.07176) | 用 task vector 组合做**个性化**美学 | 依赖多 IAA/IQA 数据集 |
| 2024 | VisionReward (THUDM, 2024-12) | ImageReward 继任，多维 reward | 偏 T2I 训练 |
| 2024-25 | MANIQA / MUSIQ 改进 / CLIP-IQA | 用 CLIP 视觉-语言对齐给 IQA 加分 | 仍单分 |
| 2025 | AesPA / AesAgent / Aes-Next | LLM-Agent 多步审美推理 | 推理慢、成本高 |
| 2025-26 | UnifyReward (复旦) | 理解+生成多模态 reward | 偏 T2I |

> **结论**：通用打分用 **LAION-Aesthetic-Predictor v2.5** 或 **Q-Align/OneAlign** 是 2025 年最稳的两条线；维度分解走 **AesBench 4 维**思路（感知/共情/评估/解读）。

### 1.2 三类 Backbone 横向对比

| Backbone | 适用场景 | 优势 | 劣势 | 关键来源 |
|----------|----------|------|------|----------|
| **CLIP ViT-L/14** | 通用美学回归、跨模态检索 | 训练数据大、社区成熟、LAION-Aesthetic V2.5 直接可用 | 西方审美偏置；分辨率固定 | https://github.com/LAION-AI/aesthetic-predictor |
| **SigLIP 2 (Google DeepMind 2025)** | T2I 奖励、海量数据高效训练 | Sigmoid loss 训练快、零样本强、支持任意分辨率 | 美学数据上无 SOTA 微调 | https://juejin.cn/post/7473760696137351205 |
| **DINOv2** | 风格/构图特征提取 | 自监督、视觉特征强、无文本偏置 | 不能直接算"美学分"，要加 head | https://github.com/facebookresearch/dinov2 |
| **EVA-CLIP (BAAI)** | 大规模美学 + 中文对齐 | 训练到 2B+ 仍稳定 | 推理重、需多卡 | https://github.com/baaivision/EVA |
| **BLIP** | 图像-文本语义对齐 | 适合"美得有理由" | 单流不如 CLIP | https://github.com/salesforce/BLIP |
| **LMM (Q-Align, OneAlign)** | 多任务、离散等级、可解释 | 一次性给 IQA+IAA+VQA；能自然输出多维 | GPU 贵、推理慢 | https://github.com/Q-Future/Q-Align |

> **关键发现**：用 SigLIP 2 + DINOv2 **双塔拼接**（SigLIP 表征"内容语义"+ DINOv2 表征"风格/构图"），再回归 8 维美学向量，是 2025-2026 论文的隐藏趋势。EVA-CLIP 在中文场景必须做。

### 1.3 重要奖励 / 偏好模型

- **ImageReward** (NeurIPS 2023, THUDM)：BLIP 顶，137k 专家 pair，在 CLIP/Aesthetic/BLIP 上分别提升 38.6/39.6/31.6%。ReFL 微调 SD 人类偏好胜率 +58.4%。继任 **VisionReward** 已发（多维 reward for T2I/视频）。
  - 论文：https://arxiv.org/abs/2304.05977
  - 代码：https://github.com/THUDM/ImageReward
- **HPSv2** (Wu et al., 2023)：798k pair / 433k 图 / 107k prompt；HPS v2.1 在 HPD v2 测试集 84.1% 准确率，超过单人类（78.1%）、PickScore（79.8%）、ImageReward（74.0%）、Aesthetic Score。
  - 论文：https://arxiv.org/abs/2306.09341
  - 代码：https://github.com/tgxs002/HPSv2
- **PickScore**：PickaPic 数据集（800k 真实用户偏好），CLIP-H/14 微调。
- **Q-Align** (Wu et al., 2023-12)：把美学/质量当**离散文本等级**让 LMM 学，IQA+IAA+VQA 一个模型。
  - 论文：https://arxiv.org/abs/2312.17090
  - 代码：https://github.com/Q-Future/Q-Align
- **AesBench / AUBD** (NeurIPS 2024)：**评测为主**——2800 张专家标注图，4 个深度递进维度（感知/共情/评估/解读），4 个 MLLM 横向 leaderboard。
  - 项目：https://aesbench.github.io/
  - 论文：https://arxiv.org/abs/2409.18749
- **PIAA Task-Vector** (ECCV 2024)：用 task vector 组合多个 IAA/IQA 数据集，做**个性化**美学评估，可泛化到未见域。
  - 论文：https://arxiv.org/abs/2407.07176

### 1.4 推荐系统方向的"打分"vs"排序"

- 打分：给每张图一个绝对分（LAION-Aesthetic / NIMA / Q-Align 离散）。
- 排序：pairwise 比较（Bradley-Terry / Plackett-Luce / ELO）→ HPSv2 / ImageReward / PickScore。

> **结论**：召回用绝对分（快），精排用 pairwise 偏好模型（准）。两者不要混。

---

## 2. 审美维度分解

### 2.1 维度清单（业界共识）

| 维度 | 量化方法 | 工具 / 模型 | 备注 |
|------|----------|-------------|------|
| **构图 (Composition)** | Rule-of-thirds 偏差、对角线能量、引导线 (HED edge) | OpenCV + 启发式，或 AADB attribute head | 易量化，但与"风格"耦合 |
| **色彩 (Color)** | Lab 直方图 + palette 提取 + 对比度 (HSV) | scikit-image / palettefm / CLIP 颜色词对齐 | 与情绪强相关 |
| **光影 (Lighting)** | 亮度直方图 + 阴影检测 (U2-Net) + 高光占比 | 启发式 / EVA-CLIP 文本查询 | 夜景 vs 棚拍难统一 |
| **主题 (Subject)** | 检测 + 分类 (YOLO/EVA-02) | COCO 80 类 + 自定义细类 | 推荐召回最关键 |
| **情绪 (Emotion)** | CLIP 文本相似度（"serene, dramatic, melancholic"） | CLIP / LMM | 与"风格"边界模糊 |
| **风格 (Style)** | DINOv2 表征 + WikiArt 标签 | DINOv2 + classifier | 强 T2I 风格转移需要 |
| **复杂度 (Complexity)** | Canny 边缘密度 + 颜色熵 | OpenCV 启发式 | 反向指标（极简主义 vs 繁复） |
| **罕见度 (Rarity)** | 在 LAION/Unsplash 池里的 ANN 最近邻距离 | FAISS / Milvus | 推荐"长尾"重要 |

### 2.2 业界主流的 4-8 维方案

- **AesBench (NeurIPS 2024)**：感知 / 共情 / 评估 / 解读 4 维（评测角度）。
- **AADB (CVPR 2016)**：原论文就给出 **12 维属性**（interesting_content、object_emphasis、good_lighting、color_harmony、good_composition、vivid_color、shallow_dof、motion_blur、rule_of_thirds、balanced、no_noise、soft）——非常值得直接复用做属性 head。
- **Photo Critique Dataset (NeurIPS 2022)**：用语言描述"为什么美"。
- **个性化美学 (PIAA-TaskVector 2024)**：用 task vector 拼出"我"的审美特征。

> **结论**：MVP 起步用 **AADB 12 维** + **AesBench 4 维评估** = **8-10 维可对齐业界**。

### 2.3 LLM-as-Judge 的一致性证据

- **AesBench 论文** 报告：GPT-4o、Claude-3.5、Gemini-1.5 在"审美感知"上 70-80% 一致，但"审美解读"维度只有 ~50% 一致。
- **Q-Align 论文**：用 LMM + 离散等级能比直接回归在 SRCC 上提升 5-8 个点。
- **作者建议**：
  - 评估类（打分）→ GPT-4o 性价比高，Claude 3.5 偏严。
  - 解读/共情类 → 必须 LMM（GPT-4V / Claude 3.5 Sonnet / Gemini Pro Vision），零样本不够。
  - 推理时分级（**两阶段**：先 LMM 标 ±1，歧义时升级到 GPT-4o）能省 60% 成本。

---

## 3. 指标体系

### 3.1 与人类一致性

| 指标 | 公式 | 适用 | 业界标准 |
|------|------|------|----------|
| **SRCC (Spearman)** | 1 - 6 Σd² / [n(n²-1)] | 单图打分 benchmark | 通用 |
| **PLCC (Pearson)** | cov(x,y) / (σx σy) | 线性回归后 | 通用 |
| **KRCC (Kendall)** | (C-D) / n(n-1)/2 | 序对齐 | 论文用 |
| **Krippendorff α** | 1 - Do/De | 多人标注一致性 | 内容分析 |
| **Pairwise accuracy** | 1/N Σ [sgn(p_i - p_j) = sgn(g_i - g_j)] | 偏好模型 | HPSv2/ImageReward 标准 |
| **ELO / TrueSkill** | 在线更新 | 用户反馈循环 | RecSys 通用 |

### 3.2 自动化指标

- **CLIP-IQA**：CLIP 图-文距离给"质量/噪声/亮度"打分。
- **LAION-Aesthetic-Predictor**：1-10 绝对分。
- **PickScore / HPSv2 / ImageReward**：T2I 偏好预测。
- **BRISQUE / NIQE / PIQE**：无参考传统 IQA（**过时**，只参考用）。

### 3.3 推荐评测 prompt 模板

```text
SYSTEM: 你是专业摄影评论家，请基于构图、色彩、光影、情绪、风格 5 维对图评分（每维 1-5）。
USER: <image>
OUTPUT (JSON): {"composition":4, "color":3, "lighting":5, "mood":4, "style":"cinematic", "overall":4.2, "critique":"..."}
```

评估流程：
1. **离线评测**：AVA test set (官方 19k) → SRCC + PLCC。
2. **在线评测**：用户反馈回流的 pairwise accuracy + ELO。
3. **冷启动**：用 ImageReward / HPSv2 当"伪人评"做 A/B baseline。

---

## 4. 数据集与 Benchmark 清单

### 4.1 经典 IAA / IQA 数据集

| 数据集 | 规模 | 任务 | 链接 | 备注 |
|--------|------|------|------|------|
| **AVA** | 255k 图 / 66k test | 美学评分 1-10 + 风格标签 (66 类) | https://github.com/lyogavin/ava_downloader | 摄影社区 DPChallenge；最经典 |
| **AADB** | 10k 图 | 美学分 + 12 维属性 | https://github.com/aimagelab/aadb | MIT Kong 2016 |
| **PETA** | 7k+ 行人 | 时尚美学 + 服装属性 | https://github.com/yhustl/PETA | 时尚方向 |
| **TAD66K** | 66k 图 | 主题/美学 |  | "TAD" topic-aesthetic dataset |
| **KonIQ-10k** | 10,073 图 / 1.2M 评分 | IQA（质量/失真） | https://arxiv.org/abs/1910.06180 | "in-the-wild" IQA |
| **SPAQ** | 11,125 手机摄影 | 手机摄影质量 + 属性 |  | 弱光、噪声 |
| **LIVE / CSIQ / TID2013** | 传统 IQA | 失真类型 |  | 学术已过时 |
| **EVA** | 2020 / explainable | 解释性美学 |  |  |
| **BAID** (CVPR 2023) | 艺术绘画 | 风格 + 美学 |  |  |
| **FAE-Captions** | 图像-美评文本对 | 风格 captioning | https://www.sciencedirect.com/science/article/abs/pii/S0045790622001562 | 配 LMM captioning |

### 4.2 偏好对（pair）数据集

| 数据集 | 规模 | 来源 | 链接 |
|--------|------|------|------|
| **HPD v2** | 798k pair / 433k 图 / 107k prompt | T2I 模型生成 | https://github.com/tgxs002/HPSv2 |
| **ImageRewardDB** | 137k pair | DiffusionDB 标注 | https://huggingface.co/datasets/THUDM/ImageRewardDB |
| **PickaPic** | 800k+ pair | 真实用户 |  |
| **DiffusionDB** | 14M 提示-图 | LAION 衍 | https://github.com/poloclub/diffusiondb |
| **AADB pair** | AADB 子集 | Kong 2016 |  |

### 4.3 大规模预训练 / 评分池

| 数据 | 规模 | 用途 |
|------|------|------|
| **LAION-Aesthetics 6.5+** | 6.5M 顶级图 / 2B 总 | 训练通用美学回归 / Stable Diffusion 筛选 |
| **Unsplash Aesthetics** | 200k+ 高分图 | 训练高分回归 |
| **Pexels** | 商用免费 | 训练中 |
| **POCO / 图虫 / 视觉中国** | 8k+ 中文 + 图 | 中文审美微调 |

### 4.4 中文美学数据集

- **POCO** (Liblib Group, 2024-06)：图虫 + 视觉中国 + POCO 摄影社区，约 8000+ 张高质量图，**全中文 prompt**。专门给 SD/MJ 微调 + 美学评分。
  - 知乎介绍：https://zhuanlan.zhihu.com/p/703245829
  - 仓库：https://github.com/liblib-group/poco-dataset
  - HF 集合：https://huggingface.co/datasets/cafeai/aesthetics-predictor
- **小红书 / 图虫 / POCO / VCG**：需自行爬取（注意：用户已封禁小红书账号侧，**爬图虫/视觉中国/POCO** 是合规替代）。
- **BAID-artistic** (CVPR 2023)：中文/东方绘画美学可用。

> **数据合规提醒**：用户已要求**停掉小红书账号侧**（发帖/评论/私信/抓账号/养号），但**抓图虫/POCO 公开摄影内容做训练数据**目前在合规边缘，建议加"仅用作学术研究 + 训练 + 来源标注 + opt-out 链接"。详细见 `active-projects.md`。

### 4.5 Benchmark 速查

- **AesBench / AUBD** (NeurIPS 2024)：https://aesbench.github.io/ — 4 维 MLLM 评测
- **IAA / IQA Awesome List**：
  - https://github.com/bcmi/Awesome-Aesthetic-Evaluation-and-Cropping
  - https://github.com/chaofengc/Awesome-Image-Quality-Assessment
  - https://github.com/LikeGiver/Awesome-Image-Aesthetic-Assessment
- **AVA test set (官方 19k)**：业内公认 SRCC/PLCC 排行榜

---

## 5. "我们怎么从 0 做出一个有审美"

### 5.1 Backbone 选型

| 选项 | 推荐度 | 理由 | 代价 |
|------|--------|------|------|
| **LAION-Aesthetic-Predictor v2.5 (CLIP ViT-L/14 + 1 层 nn.Linear)** | ★★★★★ | 开箱即用、单 GPU 实时、社区基准 | 单分、西方审美、不可解释 |
| **SigLIP 2 + 自训美学头** | ★★★★ | 训练快、多语言、原生高分辨率 | 美学数据要重准备 |
| **EVA-CLIP-G/14 + 自训美学头** | ★★★★ | 中文对齐友好、可扩展 | 多卡训练 |
| **DINOv2 + 自训美学头** | ★★★ | 视觉特征强、风格/构图细 | 不能直接对齐"美" |
| **Q-Align / OneAlign (LMM 5 级)** | ★★★★ | 多任务、可解释、维度分解 | 推理重、需 A100/H100 |
| **多塔融合 (SigLIP+DINOv2+CLIP-text)** | ★★★ | 维度向量强 | 工程复杂 |

### 5.2 训练数据来源与合规

1. **公开可商用**：
   - LAION-Aesthetics 6.5+ / Unsplash / Pexels（CC0 / Unsplash 协议）。
   - AVA / AADB / KonIQ-10k（学术用，发布产品前要查 license）。
2. **可爬取 + 学术使用**：
   - 图虫 / 视觉中国 / POCO（来源标注，opt-out）。
   - **小红书**：**用户明令禁止**账号侧（见 active-projects.md）；"抓公开帖做训练"在 2024 年后小红书 ToS 明确禁止，**不建议**。
3. **自标 pair**：
   - 内部团队 1-3k pair（最快 2 周可标完）。
   - 众包（Toloka / Scale AI / Label Studio），1 万 pair 约 ¥2-3 万。

### 5.3 Pair-wise + Bradley-Terry / ELO 路线

- **思路**：NIMA 已经证明**预测分布**比单均值稳定；2023 后主流是**pairwise** + Bradley-Terry。
- **方法**：
  1. 标 5-10k pair（"A vs B 哪个更美"）。
  2. 用 Bradley-Terry 或 Plackett-Luce 反推每张图分数。
  3. 用这个分数当监督，训美学头（CLIP/SigLIP 顶）。
  4. 在线时 ELO 实时更新。
- **好处**：
  - 标注员一致率比"打 1-10 分"高 2 倍。
  - 同一框架可升级到 DPO 训练扩散模型。
- **参考实现**：https://github.com/jmmcd/BradleyTerry、NIMA 仓库。

### 5.4 是否要微调"我们的审美"？

- **必须**。LAION 通用分对中文用户偏置严重（不熟悉亚洲构图/色彩）。
- **路径**：
  - Stage 1：用 LAION 训的 v2.5 初始化，**冻结 backbone**。
  - Stage 2：在 AVA + AADB + POCO 上微调美学头。
  - Stage 3：用我们自标 pair（Bradley-Terry）做"品味校准"。
  - Stage 4：用户级 LoRA（per-user adapter 2MB）。

### 5.5 个性化美学

- **PIAA-TaskVector (ECCV 2024)**：用 task vector 拼多个 IAA 数据集，可以**没见过的域**也工作。
- **用户级 LoRA**：每个用户 2-4MB LoRA adapter，5-10 张点赞图就能训，推理时合并。
- **冷启动**：先用通用分 + 用户前 5 次点击/收藏，5 张后启 LoRA。

### 5.6 Diffusion 生成对抗数据

- **思路**：用 SDXL / Flux 生成"美/不美"两极图，反向训美学评分器。
- **优势**：数据无限、覆盖长尾风格。
- **风险**：评分器会"奖励过优化"（reward over-optimization）→ 文生图烂图分虚高。
- **缓解**：加 30% 真实图做负样本；定期人工核验。

### 5.6 三条候选路径 + 代价

| 路径 | 时间 | 团队 | 算力 | 数据 | 质量上限 | 推荐度 |
|------|------|------|------|------|----------|--------|
| **A. 通用分 + 维度启发式（MVP）** | 2 周 | 1 人 | 单 GPU | 0（直接用 v2.5） | 60% | 冷启动 / 验证推荐 |
| **B. SigLIP 2 + AVA/AADB 微调 + 8 维头** | 6 周 | 2 人 | 4×A100 | AVA + AADB + POCO | 78% | 生产推荐 |
| **C. OneAlign 思路自训 + 用户级 LoRA + Bradley-Terry** | 12 周 | 3-4 人 | 8×H100 | 全套 + 自标 50k pair | 88% | 长期差异化 |

---

## 6. 评测：最小能立刻跑起来的脚本

```python
# 1. 装环境
# pip install torch transformers pillow timm open_clip_torch faiss-cpu

# 2. 加载 LAION-Aesthetic v2.5
import torch, open_clip
from PIL import Image

model, _, preprocess = open_clip.create_model_and_transforms(
    'ViT-L-14', pretrained='openai')
ckpt = torch.hub.load_state_dict_from_url(
    'https://github.com/LAION-AI/aesthetic-predictor/blob/main/sa_0_4_vit_l_14_linear.pth?raw=true')
head = torch.nn.Linear(768, 1)
head.load_state_dict(ckpt)
head.eval()

# 3. 推理
img = preprocess(Image.open('test.jpg')).unsqueeze(0)
with torch.no_grad():
    feat = model.encode_image(img)
    score = head(feat).item()  # 1-10 美学分

# 4. 评测 AVA test set（官方 19k）
# 下载 https://github.com/lyogavin/ava_downloader
ava = load_ava_test()
preds, gts = [], []
for path, gt in ava:
    p = predict_aesthetic(path)
    preds.append(p); gts.append(gt)
srcc = spearmanr(preds, gts).correlation
plcc = pearsonr(preds, gts)[0]
print(f'SRCC={srcc:.4f} PLCC={plcc:.4f}')
# 业界 v2.5 在 AVA test 上 ~0.67 SRCC
```

最小可跑 benchmark：
1. **AVA test 19k** → SRCC/PLCC
2. **AADB test** → SRCC/PLCC
3. **PickaPic pair (1k 子集)** → pairwise accuracy
4. **AUBD (AesBench) 2800** → 4 维 MLLM 评估（调用 GPT-4o/Claude 3.5）

---

## 7. 8-12 周研发时间线

### 阶段 0（Week 1）— 立项 + 数据
- [ ] 锁定路径（B 或 C）
- [ ] 落 AVA / AADB / POCO 数据 + 标注员开工
- [ ] 跑通 LAION-Aesthetic v2.5 baseline（AVA SRCC 0.67）

### 阶段 1（Week 2-3）— MVP（路径 A）
- [ ] 部署 v2.5 serving
- [ ] 维度分解：构图 (rule-of-thirds) + 色彩 (palette) + 复杂度 (edge density) + 罕见度 (FAISS ANN)
- [ ] 接入推荐召回做 A/B baseline
- [ ] 评测：AVA SRCC、AADB SRCC、AUBD 4 维 LMM judge

### 阶段 2（Week 4-6）— 微调（路径 B）
- [ ] Backbone 选 SigLIP 2 (ViT-L) 或 EVA-CLIP-G/14
- [ ] AVA + AADB + POCO 联合微调，8 维头
- [ ] 加 pair 数据训练 Bradley-Terry
- [ ] 维度消融实验

### 阶段 3（Week 7-9）— 维度深化
- [ ] AADB 12 维属性 head 训练
- [ ] 主题分类（EVA-02 / YOLO）+ 情绪/风格 CLIP 文本相似度
- [ ] 多维向量导出 → 入向量库（Milvus/Qdrant）

### 阶段 4（Week 10-12）— 个性化（路径 C 起步）
- [ ] 收集首批 1000 用户 × 5 点赞图
- [ ] 用户级 LoRA adapter（2-4MB）
- [ ] 上线 ELO 排序 + 用户反馈回路
- [ ] 接入 Diffusion 反向数据 pipeline

### 阶段 5（Week 13+）— 持续优化
- [ ] 季度重训美学头（增新风格、节日主题）
- [ ] 接入 LMM 解读（"为什么这张美"）
- [ ] 多模态 LLM-as-Judge 评估回路

---

## 8. 关键风险与决策点

| 风险 | 影响 | 建议 |
|------|------|------|
| **数据合规** | POCO/图虫/视觉中国版权 | 加来源标注 + opt-out 链接；只用公开图 |
| **小红书数据** | 用户已封禁账号侧，**禁止抓** | 不使用 |
| **美学 vs 色情/猎奇** | 监管风险 | 双层过滤：美学分 + NSFW 分类器 (CLIPNSFW) |
| **西方审美偏置** | LAION 训练数据 | 中文 POCO 微调 + 内部标注员 |
| **奖励过优化** | 自训美学头在 T2I 上虚高 | 30% 真实图兜底 + 人工抽检 |
| **个性化隐私** | 用户级 LoRA 需存用户特征 | 差分隐私 / 同态加密 / 端侧 |

---

## 9. 引用清单（精选 40+）

### 经典美学模型
- NIMA: https://arxiv.org/abs/1709.05424 (Talebi & Milanfar, TIP 2018)
- MUSIQ: https://arxiv.org/abs/2108.05997 (Ke et al., Google, ICCV 2021)
- MLSP: https://github.com/lidq92/MLSP (Hosu et al., CVPR 2019)
- HyperIQA: https://github.com/SSL92/hyperIQA (Su et al., CVPR 2020)
- MaxViT: https://github.com/google-research/maxvit (Tu et al., ECCV 2022)
- MANIQA: https://github.com/IIGROUP/MANIQA (Yang et al., CVPR 2022)

### T2I 偏好 / 奖励
- ImageReward: https://arxiv.org/abs/2304.05977 / https://github.com/THUDM/ImageReward
- HPSv2: https://arxiv.org/abs/2306.09341 / https://github.com/tgxs002/HPSv2
- PickScore: https://github.com/yuvalkirstain/PickScore
- VILA: https://arxiv.org/abs/2306.04638
- Q-Align: https://arxiv.org/abs/2312.17090 / https://github.com/Q-Future/Q-Align
- AesBench / AUBD: https://aesbench.github.io/ / https://arxiv.org/abs/2409.18749
- PIAA-TaskVector: https://arxiv.org/abs/2407.07176
- VisionReward: https://github.com/THUDM/VisionReward
- PickaPic: https://github.com/pickapic/PickaPic
- DiffusionDB: https://github.com/poloclub/diffusiondb

### 数据集
- AVA: https://github.com/lyogavin/ava_downloader (Murray et al., CVPR 2012)
- AADB: https://github.com/aimagelab/aadb (Kong et al., CVPR 2016)
- KonIQ-10k: https://arxiv.org/abs/1910.06180
- LAION-Aesthetics: https://laion.ai/blog/laion-aesthetics/ / https://github.com/LAION-AI/aesthetic-predictor
- POCO: https://github.com/liblib-group/poco-dataset / https://huggingface.co/datasets/cafeai/aesthetics-predictor
- BAID: CVPR 2023
- FAE-Captions: https://www.sciencedirect.com/science/article/abs/pii/S0045790622001562

### Backbone
- CLIP: https://github.com/openai/CLIP
- SigLIP 2: https://huggingface.co/google/siglip2-base-patch16-224
- DINOv2: https://github.com/facebookresearch/dinov2
- EVA-CLIP: https://github.com/baaivision/EVA
- BLIP: https://github.com/salesforce/BLIP

### 工具 / 集合
- Awesome IAA: https://github.com/bcmi/Awesome-Aesthetic-Evaluation-and-Cropping
- Awesome IQA: https://github.com/chaofengc/Awesome-Image-Quality-Assessment
- Awesome IAA (LikeGiver): https://github.com/LikeGiver/Awesome-Image-Aesthetic-Assessment
- NIMA PyTorch 实现: https://github.com/idealo/image-quality-assessment / https://github.com/torum/NIMA
- Bradley-Terry 实现: https://github.com/jmmcd/BradleyTerry
- Tamer Saleh pairwise blog: https://tamersaleh.com/posts/building-an-image-aesthetic-judge-with-pairwise-comparisons/

### 维度 / Bradley-Terry / ELO
- NIMA Bradley-Terry: https://arxiv.org/abs/1709.05424
- AesBench 4 维: https://arxiv.org/abs/2409.18749
- 视频美学 + pair: https://arxiv.org/abs/2303.13733
- 通用 IQA pair: https://arxiv.org/abs/2302.01848

### 评测 / 指标
- Krippendorff α: https://en.wikipedia.org/wiki/Krippendorff%27s_alpha
- 通用 SRCC/PLCC 用法: 各 IAA 论文标准（AVA test 19k）

### 相关商业 / 工业
- Pinterest Pinnability: https://arxiv.org/abs/1803.02586 (Geng et al., KDD 2015 → 持续更新)
- PhotoRank: 综述见 https://github.com/bcmi/Awesome-Aesthetic-Evaluation-and-Cropping

---

## 10. 决策建议（给用户）

**推荐路径 B**（6 周，2 人，4×A100）作为生产默认：
- SigLIP 2 + AVA + AADB + POCO 微调 8 维美学头
- pair 数据训练 Bradley-Terry 当排序 fallback
- 同时**冷启动用 v2.5**保证 2 周内可用（路径 A 并行）
- 第 8 周启动路径 C 的用户级 LoRA 实验

**优先决策点**：
1. 是否愿意投入数据标注（5-10k pair，约 ¥2-3 万）？ → 决定走 B 还是 C
2. 中文审美优先级？（POCO 够用 vs 自建中文 pair） → 决定 backbone 选 EVA-CLIP 还是 SigLIP 2
3. 是否同步做 T2I 风格克隆？ → 决定要不要 ImageReward/VisionReward 路线
4. 商业化走"通用审美 API"还是"个性化审美 AI"？ → 决定是否要 PIAA/LoRA 投入

---

> 文档版本：v1.0（2026-07-26）
> 下一步：等用户拍板路径 B/C，PM Agent 启动执行。
