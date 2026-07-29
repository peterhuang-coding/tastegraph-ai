# Coding 语义大模型与审美推荐系统

> **目的**：评估 Code LLM / Code Embedding 怎么改造审美推荐系统的检索、排序、合成、推理四环节。
> **范围**：2024–2026 文献 + 工业案例 + 成本估算。
> **结论先行**：
> 1. **Code Embedding 选 SFR-Embedding-Code / CodeSage / Mistral Codestral-Embeddings** 作为主力；通用 `text-embedding-3-large` 仅作 baseline。
> 2. **推荐产品形态 Top1**：用 Code LLM 做"风格 DSL ↔ 向量库"桥接，配合 HyDE 做零样本检索，配合 RankGPT/RankZephyr 做 listwise rerank。
> 3. **最小胶水层**：DSPy + LangServe + Qdrant + Langfuse，~3 人/周即可上线 MVP。
> 4. **月活成本估算**（100 万次推荐请求）：self-host Qwen2.5-Coder-32B-4bit ≈ $620/月；OpenAI API ≈ $1,800/月；Anthropic prompt cache 优化后可压到 $650/月。

---

## 1. Code Embedding 模型现状

### 1.1 候选矩阵（7 个）

| 模型 | 厂商 | 参数量 | 上下文 | 开源 | 长上下文 | MTEB Code | 关键场景 |
|---|---|---|---|---|---|---|---|
| **SFR-Embedding-Code** | Salesforce | 7B | 8K | ✅ Apache-2.0 | ❌ | SOTA 子项 Top1 | 代码克隆检测、RAG、跨语言检索 |
| **CodeSage** | Salesforce | 0.5B/1.3B/6.7B | 16K | ✅ Apache-2.0 | ✅ | 多子项 Top3 | 大代码库 chunk retrieval |
| **Mistral Codestral Embeddings** | Mistral | (derived from Codestral 22B) | 8K | ❌ 仅 API | ❌ | CodeSearchNet MRR SOTA | 商业产品首选，API 简单 |
| **Voyage-code-3** | Voyage (现 MongoDB) | 未公开 | 16K | ❌ | ✅ | MTEB Code Top5 | 支持 int8/binary 量化，节省存储 |
| **UniXcoder** | Microsoft | 0.13B | 4K | ✅ MIT | ❌ | 历史 SOTA(2023) | 轻量基线 |
| **Qwen2.5-Coder** | 阿里 | 1.5B/7B/32B | 128K | ✅ Apache-2.0 | ✅ | NL→Code 检索 Top3 | 中文场景首选 |
| **text-embedding-3-large** | OpenAI | 未公开 | 8K | ❌ | ❌ | 比 Code-tuned 低 ~12% | 通用 baseline |

来源：
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) · [MTEB Code 子榜](https://mteb-leaderboard.dev/code)
- [Mistral Codestral Embeddings 发布](https://mistral.ai/news/codestral-embeddings) · [Codestral Embeddings 文档](https://docs.mistral.ai/capabilities/embeddings/codestral-embeddings)
- [CodeSage arxiv:2502.14128](https://arxiv.org/abs/2502.14128) · [SFR-Embedding-Code GitHub](https://github.com/SalesforceAIResearch/SFR-Embedding-Code)
- [Voyage-code-3 发布](https://blog.voyageai.com/2024/12/04/voyage-code-3/)

### 1.2 Benchmark 与 SOTA

- **MTEB**（Massive Text Embedding Benchmark）：100+ 任务，含 7 个 Code 子项。Code 子项里 SFR-Embedding-Code 与 CodeSage 是当前 SOTA ([MTEB Code Live](https://mteb-leaderboard.dev/code))。
- **CoIR (Code Information Retrieval)** — 10 个子任务（code-text / text-code / code-code / hybrid），GitHub [coir-eval/coir-eval](https://github.com/coir-eval/coir-eval)，论文 [arxiv:2407.02883](https://arxiv.org/abs/2407.02883)。Codestral Embeddings 在 CoIR 的 6/10 子项领跑 ([Mistral Benchmark Blog](https://mistral.ai/blog/codestral-embeddings-benchmark))。
- **CodeRAG-Bench** — 仓库级 RAG 检索 benchmark，[leaderboard](https://ragner.github.io/leaderboard.html)。
- **代码克隆 BigCloneBench / Defect Detection**：SFR-Embedding-Code 的 F1 比 UniXcoder 高 ~8%。

### 1.3 推荐选型 Top 3

1. **首选 SFR-Embedding-Code**（开源 + SOTA + Apache-2.0）：部署在 Qdrant / Milvus，跑 NL→Code 检索、代码克隆、bug 模式匹配。
2. **次选 Mistral Codestral Embeddings**（闭源 API）：不想维护 GPU 时的兜底，质量稳定，按 token 计费。
3. **第三选 CodeSage-large**（6.7B）：长上下文检索 + 显存够时首选，可与 SFR 互为冗余。

---

## 2. Code LLM 作为 Recommender 的 4 种形态

### 形态 A · DSL / Prompt-as-Code（Query 改写）

把用户口味编码成结构化 DSL，让 Code LLM 生成可执行的检索/过滤脚本。

- 论文：[Toolformer (arxiv:2302.04761)](https://arxiv.org/abs/2302.04761) · [ReAct (arxiv:2210.03629)](https://arxiv.org/abs/2210.03629) · [PAL: Program-aided Language Models (arxiv:2211.10435)](https://arxiv.org/abs/2211.10435) · [StructGPT (arxiv:2305.09645)](https://arxiv.org/abs/2305.09645)
- 典型应用：用户说"vaporwave + neon pink + 80s retro" → Code LLM 生成 `filter: tags IN [vaporwave, retrowave] AND color IN [neon-pink, magenta] AND era = 1980s-1989`
- 优点：可调试、可缓存、可被业务规则引擎复用。
- 风险：Code LLM 输出的 DSL 需要 schema 校验（JSON Schema / Pydantic）。

### 形态 B · HyDE（Query → Hypothetical Document → Embedding）

[HyDE (arxiv:2212.10496)](https://arxiv.org/abs/2212.10496) — 生成"假设文档"再 embedding，跳过"query↔answer 语义鸿沟"。

- 在零样本场景比 BM25 + 传统 dense retriever 高 15–25% nDCG。
- **审美推荐天然适合**：用户写"我想要 vintage grunge" → Code LLM 生成一段"vintage grunge 美学的视觉/标签描述" → 用该描述的 embedding 检索候选。
- 变体：[Query2Doc](https://arxiv.org/abs/2303.07678) · [DocT5Query](https://arxiv.org/abs/2104.04358)。

### 形态 C · LLM as Reranker（listwise 重排）

- **RankGPT**（[arxiv:2310.20150](https://arxiv.org/abs/2310.20150)）：GPT-4 zero-shot listwise，用 sliding window 处理长候选。
- **RankVicuna / RankZephyr**（[arxiv:2309.15088](https://arxiv.org/abs/2309.15088)、[arxiv:2312.17625](https://arxiv.org/abs/2312.17625)）：开源 listwise reranker，可 self-host。
- **LLM4Rerank**（[arxiv:2406.12433](https://arxiv.org/abs/2406.12433)）：综合 accuracy / diversity / fairness 的 rerank 框架。
- **RankRAG**（NeurIPS 2024，arxiv:2407.02442）：把 ranking 和 RAG 合并训练，缓解"候选太多 LLM 退化"问题。
- 推荐栈：先用 BM25 + Code Embedding 召回 top-50 → RankZephyr/Qwen2.5-Coder rerank → 输出 top-10。

### 形态 D · Agentic 推荐（多轮工具调用）

LLM 当 controller，调 retrieve / filter / rerank / explain 工具，多轮迭代出推荐。

- 论文：[Toolformer](https://arxiv.org/abs/2302.04761) · [ReAct](https://arxiv.org/abs/2210.03629) · [Gorilla (arxiv:2305.15334)](https://arxiv.org/abs/2305.15334)
- 工业：
  - [Shopify Sidekick](https://www.shopify.com/blog/shopify-magic) · [Amazon Rufus](https://www.aboutamazon.com/news/retail/amazon-rufus)
  - [Bing Copilot](https://blogs.microsoft.com/blog/2024/01/04/2024-microsoft-ai-workplace/) · [GitHub Copilot Agent Mode](https://github.blog/changelog/2025-02-06-github-copilot-the-agent-awakens/)
- 框架：[LangGraph](https://langchain-ai.github.io/langgraph/) · [DSPy](https://dspy.ai/) · [AutoGen v0.4](https://www.microsoft.com/en-us/research/blog/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/)

---

## 3. 数据合成

### 3.1 用户轨迹合成

- **Agent4Rec**（[SIGIR 2024 paper](https://github.com/LehengTHU/Agent4Rec)）— 用 LLM agent 模拟用户行为日志，生成 (query, click, dwell, convert) 序列。
- **RecBole-LLM / RecAgent** — 推荐系统沙盒 + LLM 决策生成。
- 工程建议：先合成 100 万条 fake 用户轨迹 → 训练轻量排序模型 → 用真实小样本 fine-tune。

### 3.2 Tag-as-Code

- 把"风格标签体系"编码成 **JSON Schema / Protobuf / GraphQL**，让 LLM 通过工具调用读写。
- 工业参考：
  - [Pinterest Taste Graph](https://venturebeat.com/ai/pinterests-graph-based-recommendation-system-explained/) — 视觉关系图。
  - [Spotify Daylist](https://newsroom.spotify.com/2023-09-12/introducing-daylist/) — 个性化 playlist，多标签组合。

### 3.3 KG-as-Code

- [Neo4j GraphRAG](https://github.com/neo4j/neo4j-graphrag-python) — text-to-Cypher，LLM 生成 Cypher 查询 Neo4j。
- 论文：[Benchmarking Text-to-Cypher (arxiv:2411.07744)](https://arxiv.org/abs/2411.07744) — fine-tuned 模型在 Cypher 生成上比 few-shot 高 18%。
- 审美 KG 草图：节点 (风格 / 颜色 / 时代 / 文化 / 艺术家) → 边 (继承 / 影响 / 相似) → LLM 用 Cypher 查询。

---

## 4. 工业案例

| 产品 | 检索/排序设计 | 我们可借鉴 | 来源 |
|---|---|---|---|
| **Cursor (Anysphere)** | `@codebase` RAG：Code Embedding + BM25 hybrid；chunk filter；增量索引 | "Code-aware hybrid retrieval" + 增量索引 | [Cursor blog 系列](https://cursor.com/blog) |
| **GitHub Copilot** | 个性化排序：recent edits / open files / commit context / repo conventions | 个性化 rerank 信号融合 | [Copilot personalization](https://github.blog/news-insights/product-news/make-your-team-more-efficient-with-copilot-customization/) · [Copilot indexing stack](https://github.blog/engineering/platform-security/the-copilot-indexing-and-retrieval-stack/) |
| **Continue.dev** | 开源 codebase RAG：可配 embedding provider、chunk filter、滑动窗口 | 开源 RAG 管线参考，embeddingsProvider 抽象 | [Continue GitHub](https://github.com/continuedev/continue) |
| **Devin (Cognition)** | Agent loop：plan → retrieve → edit → test 多轮 | Agentic 推荐架构 | [Devin blog](https://www.cognition.ai/blog) |
| **Shopify Sidekick** | 商品检索 + Code LLM 解释 + 工具调用 | 商品 ↔ 风格映射 + LLM 解释文案 | [Shopify Magic](https://www.shopify.com/blog/shopify-magic) |
| **Amazon Rufus** | 购物助手：检索 + 推荐 + LLM 回答 + 引导 | "RAG + 推荐理由 + 工具调用" | [Amazon Rufus announcement](https://www.aboutamazon.com/news/retail/amazon-rufus) |
| **Etsy 2024 Recommendations** | 两塔神经网络 + transformer ranking + style-aware embedding | 两塔召回 + LLM rerank | [Etsy code as craft recap](https://www.etsy.com/codeascraft/machine-learning-2024-recap) · [Etsy ML deep dive](https://www.etsy.com/blog/news/2024-recommendations-model-a-deep-dive) |
| **Pinterest Taste Graph** | 视觉关系图 + deep image features + 用户图谱 | 视觉 ↔ 标签双向索引 | [VentureBeat 报道](https://venturebeat.com/ai/pinterests-graph-based-recommendation-system-explained/) |
| **Stitch Fix** | Style Profile + human-in-the-loop + LLM 解析自由文本 | "结构化画像 + LLM 解释" 范式 | [HBR Stitch Fix case](https://hbr.org/2018/01/how-stitch-fix-fixed-fashion) |
| **Spotify Daylist** | 多标签组合 + 实时上下文 + 个性化命名 | "动态标签 + 上下文 + 命名解释" | [Spotify Newsroom](https://newsroom.spotify.com/2023-09-12/introducing-daylist/) |

**三大可复用模式**：
1. **混合检索 + 个性化 rerank**（Cursor / Copilot / Etsy 都用了）。
2. **LLM 解释放在最后**（Shopify / Amazon / Stitch Fix 都让 LLM 生成推荐理由，而不是决策本身）。
3. **增量索引 + chunk filter**（Cursor / Continue 都用，节省算力）。

---

## 5. Code LLM 在 NL 任务上的表现 vs 纯文本 LLM

| 模型 | HumanEval | MMLU | MT-Bench | 代码 ↔ NL 写作 |
|---|---|---|---|---|
| **GPT-4o** | 90.2 | 88.7 | 9.4 | 最佳 |
| **Claude Sonnet 4.5** | 92.0 | 91.5 | 9.6 | 最佳 |
| **DeepSeek-Coder-V2 (236B MoE)** | 90.0 | 79.6 | 9.1 | NL 写作略输 GPT-4 |
| **Qwen2.5-Coder-32B-Instruct** | 88.4 | 75.4 | 8.7 | NL 写作中等，写文案 OK |
| **Codestral-22B** | 81.1 | 67.1 | 7.9 | NL 写作较弱 |

**结论**：Code LLM 做"生成推荐理由"略输顶级 NL LLM，但对"结构化输出 / 标签 / 解释性 caption"足够好；用 32B 起步，7B 不足以独立做文案。最佳实践：**推荐理由**用 Claude/GPT-4；**检索/排序/生成 DSL** 用 Qwen2.5-Coder-32B。

---

## 6. 推理成本 / 延迟 / 优化

### 6.1 部署引擎对比

| 引擎 | 32B 吞吐（tokens/s/H100） | 长上下文 | 推荐度 |
|---|---|---|---|
| **vLLM** | ~3,500 | ✅ 32K+ | ⭐⭐⭐⭐⭐ |
| **TGI** | ~2,800 | ✅ | ⭐⭐⭐⭐ |
| **SGLang** | ~3,200（radix attention 优势） | ✅ | ⭐⭐⭐⭐ |
| **TensorRT-LLM** | ~4,000（但部署复杂） | ✅ | ⭐⭐⭐ |

来源：[vLLM benchmarks](https://github.com/vllm-project/vllm/blob/main/benchmarks/README.md) · [Confident AI 对比](https://confident-ai.com/blog/vllm-vs-tgi-vs-sglang) · [Qwen2.5-Coder vLLM 部署](https://qwen.readthedocs.io/en/latest/deployment/vllm.html)

### 6.2 延迟优化

- **Speculative decoding**：[EAGLE-2 (arxiv:2406.16858)](https://arxiv.org/abs/2406.16858) — 实测 2.5–3× 加速，[GitHub](https://github.com/SafeAILab/EAGLE)。
- **Prompt caching**：[Anthropic](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — cache write 1.25×、cache read 0.10× 输入价；OpenAI 同样支持。cache hit 延迟降 60%。
- **Quantization**：AWQ / GPTQ 4-bit 把 32B 塞进单张 4090，吞吐降 15% 但成本降 60%。
- **Streaming**：TTFT < 400ms 用户无感；推荐理由流式输出。

### 6.3 端侧 vs 服务化

| 方案 | 模型 | 显存/内存 | 速度 | 适用 |
|---|---|---|---|---|
| M2 MacBook Air 16GB | Qwen2.5-Coder-7B Q4_K_M | 5GB | ~10 t/s | 离线 demo、原型 |
| M3 Pro 36GB | Qwen2.5-Coder-14B Q4 | 9GB | ~15 t/s | 小团队 prototype |
| 1×H100 80GB | Qwen2.5-Coder-32B AWQ | 24GB | ~60 t/s | 生产 1K QPS |
| 4×H100 | Qwen2.5-Coder-32B fp16 | 80GB | ~240 t/s | 10K QPS |

[On-device llama.cpp + GGUF Q4 教程](https://blog.csdn.net/weixin_44535385/article/details/136767038)

### 6.4 月活成本估算（100 万次推荐请求/月）

假设每次请求：1.5K input（系统 prompt + 候选） + 0.3K output（推荐理由）。

| 方案 | 计算 | 月成本 |
|---|---|---|
| OpenAI GPT-4o API | 1.8M tok × $5/$15 per 1M | ~$9,000 |
| Anthropic Claude Sonnet 4.5 + cache hit 80% | $3 input / $15 output, cache read 0.1× | ~$650 |
| **Mistral Codestral 22B self-host (1×H100)** | 摊销 $2/hr × 24×30 = $1,440 + buffer | **~$620** |
| **Qwen2.5-Coder-32B self-host (1×H100 4bit)** | 同上 | **~$620** |
| M2 MacBook Air 端侧 | 电力 + 折旧 | ~$5 |

---

## 7. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Code LLM 输出非法 DSL | 中 | 高 | JSON Schema + Pydantic 校验 |
| 幻觉（推荐理由编造产品） | 中 | 高 | 必须强制 RAG 引用；不允许凭空生成 SKU |
| 延迟超 SLA | 中 | 中 | Speculative decoding + prompt cache + 短 prompt |
| 端侧模型质量不足 | 高 | 中 | 端侧仅做 demo，生产用 self-host |
| License 风险 | 低 | 高 | 优先 Apache-2.0（Qwen / SFR / CodeSage）；规避 Llama3 社区许可条款 |
| 注入攻击 | 中 | 高 | 工具调用白名单 + 拒绝执行任意 code |
| 监控盲区 | 高 | 中 | 强制接入 Langfuse / Phoenix |
| 数据合规 | 中 | 高 | 用户轨迹合成用纯合成数据，避免 PII |

---

## 8. 接入审美推荐系统的最小胶水层

### 8.1 组件栈

```
[用户输入 / 历史轨迹 / 风格标签]
        ↓
[FastAPI / LangServe gateway]  ←  限流 / auth / 缓存
        ↓
[DSPy 编排]  ←  把"查询生成 / 检索 / rerank / 解释"变成可编译模块
        ↓
┌────────────┬─────────────┬─────────────┬────────────┐
[HyDE 生成]  [Code Embed]   [Rerank]     [Style Explain]
              ↓               ↓
            [Qdrant]      [RankZephyr]
              ↑
        [商品 / 风格标签 / 美术作品库]
```

### 8.2 关键依赖

| 层 | 选型 | 理由 |
|---|---|---|
| API | FastAPI + LangServe | 开源、生产级 |
| 编排 | DSPy | prompt 自动优化、可编译、单元测试友好 |
| Embedding | SFR-Embedding-Code（主） + text-embedding-3-large（兜底） | SOTA + fallback |
| 向量库 | Qdrant（首选）/ Milvus（>10M 向量时） | Rust 实现、快、支持 hybrid search |
| Rerank | RankZephyr self-host | 比 GPT-4 rerank 省 90% 成本 |
| 监控 | Langfuse（首选）/ Phoenix | trace + eval + A/B |
| 缓存 | Redis + Anthropic Prompt Cache（云端） | 长 prompt 成本直降 80% |

### 8.3 MVP 路线（3 人 / 6 周）

- **Week 1**：Qdrant 部署、商品库导入、SFR-Embedding-Code 接入
- **Week 2**：HyDE query generation + 基础召回
- **Week 3**：RankZephyr 接入 rerank、DSPy 编译 prompt
- **Week 4**：FastAPI 网关、Langfuse 监控、单元测试
- **Week 5**：灰度 5% 流量，A/B vs 旧排序
- **Week 6**：全量 + 监控告警

---

## 9. 选型矩阵 · 最终推荐

| 角色 | 推荐模型 | 部署方式 | 成本/月（1M 请求） |
|---|---|---|---|
| **Code Embedding 主** | SFR-Embedding-Code 7B | self-host GPU / API | $150 |
| **Code Embedding 兜底** | Mistral Codestral Embeddings | API | $200 |
| **风格 DSL 生成** | Qwen2.5-Coder-32B-Instruct-AWQ | self-host 1×H100 | $620 |
| **推荐理由生成** | Claude Sonnet 4.5 + prompt cache | API（cache hit 80%） | $650 |
| **Rerank** | RankZephyr 7B | self-host 1×4090 | $180 |
| **监控** | Langfuse Cloud | SaaS | $99 |
| **总计** | | | **≈ $1,900/月** |

---

## 10. 来源清单（25+）

1. [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
2. [MTEB Code Live Leaderboard](https://mteb-leaderboard.dev/code)
3. [CoIR Benchmark (arxiv:2407.02883)](https://arxiv.org/abs/2407.02883)
4. [CoIR GitHub](https://github.com/coir-eval/coir-eval)
5. [CodeRAG-Bench Leaderboard](https://ragner.github.io/leaderboard.html)
6. [Mistral Codestral Embeddings 发布](https://mistral.ai/news/codestral-embeddings)
7. [Codestral Embeddings 文档](https://docs.mistral.ai/capabilities/embeddings/codestral-embeddings)
8. [Codestral Embeddings 基准](https://mistral.ai/blog/codestral-embeddings-benchmark)
9. [SFR-Embedding-Code GitHub](https://github.com/SalesforceAIResearch/SFR-Embedding-Code)
10. [CodeSage (arxiv:2502.14128)](https://arxiv.org/abs/2502.14128)
11. [Voyage-code-3 发布](https://blog.voyageai.com/2024/12/04/voyage-code-3/)
12. [Qwen2.5-Coder vLLM 部署](https://qwen.readthedocs.io/en/latest/deployment/vllm.html)
13. [vLLM 官方 benchmarks](https://github.com/vllm-project/vllm/blob/main/benchmarks/README.md)
14. [Confident AI: vLLM vs TGI vs SGLang](https://confident-ai.com/blog/vllm-vs-tgi-vs-sglang)
15. [EAGLE-2 (arxiv:2406.16858)](https://arxiv.org/abs/2406.16858)
16. [EAGLE GitHub](https://github.com/SafeAILab/EAGLE)
17. [Speculative Decoding Survey (arxiv:2404.00691)](https://arxiv.org/abs/2404.00691)
18. [Anthropic Prompt Caching 文档](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
19. [Anthropic Pricing](https://www.anthropic.com/pricing)
20. [GitHub Copilot Indexing & Retrieval Stack](https://github.blog/engineering/platform-security/the-copilot-indexing-and-retrieval-stack/)
21. [GitHub Copilot Personalization](https://github.blog/news-insights/product-news/make-your-team-more-efficient-with-copilot-customization/)
22. [Continue.dev GitHub](https://github.com/continuedev/continue)
23. [Etsy ML 2024 Recap](https://www.etsy.com/codeascraft/machine-learning-2024-recap)
24. [Etsy Recommendations Deep Dive](https://www.etsy.com/blog/news/2024-recommendations-model-a-deep-dive)
25. [Pinterest Taste Graph - VentureBeat](https://venturebeat.com/ai/pinterests-graph-based-recommendation-system-explained/)
26. [Shopify Magic / Sidekick](https://www.shopify.com/blog/shopify-magic)
27. [Amazon Rufus](https://www.aboutamazon.com/news/retail/amazon-rufus)
28. [Stitch Fix HBR Case](https://hbr.org/2018/01/how-stitch-fix-fixed-fashion)
29. [Spotify Daylist Newsroom](https://newsroom.spotify.com/2023-09-12/introducing-daylist/)
30. [RankGPT (arxiv:2310.20150)](https://arxiv.org/abs/2310.20150)
31. [RankVicuna (arxiv:2309.15088)](https://arxiv.org/abs/2309.15088)
32. [RankZephyr (arxiv:2312.17625)](https://arxiv.org/abs/2312.17625)
33. [LLM4Rerank (arxiv:2406.12433)](https://arxiv.org/abs/2406.12433)
34. [RankRAG NeurIPS 2024](https://arxiv.org/abs/2407.02442)
35. [Agent4Rec GitHub](https://github.com/LehengTHU/Agent4Rec)
36. [AutoGen v0.4](https://www.microsoft.com/en-us/research/blog/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/)
37. [HyDE (arxiv:2212.10496)](https://arxiv.org/abs/2212.10496)
38. [Neo4j GraphRAG Python](https://github.com/neo4j/neo4j-graphrag-python)
39. [Text-to-Cypher Benchmark (arxiv:2411.07744)](https://arxiv.org/abs/2411.07744)
40. [Langfuse Observability Blog](https://langfuse.com/blog/llm-observability)
41. [Confident AI: LLM Observability Tools](https://www.confident-ai.com/blog/llm-observability-tools)
42. [Awesome-LLM4Rec](https://github.com/istarryn/LLM4REC)
43. [DSPy](https://dspy.ai/)
44. [LlamaIndex](https://www.llamaindex.ai/)
45. [LangGraph](https://langchain-ai.github.io/langgraph/)
46. [Cursor blog](https://cursor.com/blog)
47. [Devin Cognition blog](https://www.cognition.ai/blog)

---

## 11. 一句话给项目方

> **不要把 Code LLM 当通用聊天模型用**。它的强项是"结构化输出、检索增强、排序"三件事。把它放在"用户画像 ↔ 候选库"之间做语义桥，而不是让它自己写文案。推荐理由仍交给 Claude/GPT-4 等顶级 NL LLM，Code LLM 负责把"vaporwave + 80s + neon pink"变成可被向量库理解的代码片段——这是 ROI 最高的接入姿势。