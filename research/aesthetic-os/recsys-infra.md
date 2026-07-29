# 向量检索 + 推荐系统工程化研究报告

> 调研时间：2026-07-26
> 调研范围：向量库 / 索引算法 / Embedding 推理 / 推荐系统工程 / 成本模型 / 可观测性
> 适用场景：审美推荐系统 MVP → 10万 DAU → 千万级 DAU 三阶段架构演进
> 引用来源：30+（末尾全量列出）

---

## TL;DR

| 维度 | MVP (<1万 DAU) | 10万 DAU | 千万级 DAU |
|------|----------------|---------|------------|
| **向量库** | pgvector / Chroma | Qdrant 单机 | Milvus 2.x 分布式 + DiskANN |
| **索引** | HNSW (m=16, ef=64) | HNSW + IVFFlat 兜底 | DiskANN (热) + HNSW (冷) |
| **Embedding 服务** | TEI 单卡 L4 | vLLM 2×H100 + TEI | Triton 推理集群 + TEI 多模态 |
| **召回栈** | 单一向量 | 向量 + BM25 双塔 | 向量 + BM25 + 行为 + 实时特征 |
| **排序** | 规则 + 余弦 | BGE Reranker | Cross-encoder + 多目标 LTR |
| **预算/月** | < $300 | $3–5K | $50–120K |

关键风险：冷启动召回率、Embedding drift、冷热分层 HNSW→DiskANN 迁移、GPU 单点故障、特征穿越。

---

## 1. 选型矩阵

### 1.1 向量库对比（7 候选）

| 数据库 | 类型 | 索引 | 混合检索 | 多模态native | 推荐场景 | 来源 |
|--------|------|------|---------|------------|---------|------|
| **Milvus** | 分布式 C++ | HNSW / IVF / **DiskANN** / SCANN / CAGRA (GPU) | ✓ (Sparse+Dense) | ✓ (Binary/Sparse) | 亿级+ 推荐 / RAG | [milvus.io/docs](https://milvus.io/docs/overview.md) |
| **Qdrant** | 单机 Rust | HNSW + Filterable HNSW | ✓ (Payload filter) | ✓ (Named vectors) | 10M–100M / 中等规模 | [qdrant.tech/benchmarks](https://qdrant.tech/benchmarks/) |
| **Weaviate** | 分布式 Go | HNSW + 自研 | ✓ (BM25 + Vector) | ✓ (CLIP / multi2vec) | RAG / 知识库 | [docs.weaviate.io](https://docs.weaviate.io/weaviate/search/hybrid) |
| **Vespa** | 分布式 C++/Java | HNSW | ✓ (BM25 native + phased ranking) | △ | 大规模搜索 + 推荐 | [docs.vespa.ai](https://docs.vespa.ai/en/vector-search.html) |
| **Pinecone** | SaaS | 自有 (Pod/Serverless) | ✓ (metadata filter) | ✓ (集成 inference) | 不想运维 / 海外项目 | [pinecone.io/pricing](https://www.pinecone.io/pricing/) |
| **pgvector** | PostgreSQL 扩展 | HNSW / IVFFlat | ✓ (SQL + Filter) | △ | < 1M 行 / 与 PG 共存 | [github.com/pgvector](https://github.com/pgvector/pgvector) |
| **Chroma** | Python-first | 内部 HNSW-like | ✓ (BM25/SPLADE + Vector) | ✓ (CLIP) | 快速原型 / 边缘 | [trychroma.com](https://www.trychroma.com/) |

**结论**：
- MVP 选 **pgvector**（与 Postgres 共运维） 或 **Chroma**（最快）
- 10万 DAU 选 **Qdrant 单机**（RPS 优于其他 4x）
- 千万 DAU 选 **Milvus 分布式 + DiskANN**（已验证 Salesforce/PayPal/Airbnb 规模）

### 1.2 索引算法对比（4 候选）

| 索引 | 算法原理 | 内存 | 召回 | QPS | 推荐规模 |
|------|---------|------|------|-----|---------|
| **HNSW** | 多层 navigable small world 图 | 高（所有向量驻内存） | ★★★★★ | 高 | < 100M in-RAM |
| **IVF-PQ** | 倒排聚类 + Product Quantization | 低（向量压缩） | ★★★ | 中 | 内存受限 / 中等精度 |
| **ScaNN** | 各向异性向量量化 | 中 | ★★★★ | 最高（多数据集 top-tier） | 平衡精度/速度 |
| **DiskANN** | Vamana 图 + SSD 出栈 | 极低（SSD-only） | ★★★★（≈ HNSW） | 中（SSD bound） | 亿+ / 单机 |

来源：[ann-benchmarks.com](https://ann-benchmarks.com/), [github.com/microsoft/DiskANN](https://github.com/microsoft/DiskANN), [github.com/google-research/scann](https://github.com/google-research/google-research/tree/master/scann)

**冷热分层模式**：HNSW（热/前 10%）+ DiskANN（冷/后 90%）。前 10% 走 RAM-HNSW（p99 < 5ms），后 90% 走 SSD-DiskANN（p99 < 30ms）。该模式已被 Bing/Shopee 在生产验证（参 [Vespa billion-scale-knn blog](https://docs.vespa.ai/en/vector-search.html)）。

### 1.3 Embedding 推理引擎（6 候选）

| 引擎 | 核心特性 | 吞吐参考 | GPU | CPU | 多模态 | 推荐场景 |
|------|---------|---------|------|-----|--------|---------|
| **vLLM** | PagedAttention, Continuous Batching | DeepSeek 2.2k tok/s/H200 | H100/H200/AMD | ONNX | ✓ | 通用 LLM + Embedding |
| **TensorRT-LLM** | NVIDIA 原生编译 | TTFT 194ms (Llama3.1-170B) | H100/B100 | × | ✓ | NVIDIA 极致优化 |
| **SGLang** | RadixAttention (5x prefix) | 25x on GB300 NVL72 | H100/B100/AMD | △ | ✓ | 高 prefix 复用 / 结构化输出 |
| **LMDeploy** | TurboMind 持久批 | 1.8x vLLM / 1.5x on H800 | H100/A100 | ✓ | ✓ | 国产硬件（昇腾 / 寒武纪） |
| **Triton** | NVIDIA serving 平台 | dynamic batching | H100/A100/L40 | ONNX/PyTorch | ✓ | 多模型路由 / 企业生产 |
| **Xinference** | 异构 + 多后端 | 同后端 | H100/A100/CPU | llama.cpp/GGML | ✓ | 多模型 API 网关 |

来源：[vllm.ai/blog](https://vllm.ai/blog), [sgl-project GitHub](https://github.com/sgl-project/sglang), [LMDeploy GitHub](https://github.com/InternLM/lmdeploy), [Triton GitHub](https://github.com/triton-inference-server/server), [Xinference GitHub](https://github.com/xorbitsai/inference)

### 1.4 Embedding 模型（5 候选）

| 模型 | 维度 | 多模态 | 多语言 | 稀疏/ColBERT | 用途 |
|------|------|--------|--------|--------------|------|
| **BGE-M3** | 1024 | × | 100+ | ✓ 三合一 | 多语种 RAG / 长文档 |
| **BGE-VL** | 1024 | ✓ | ✓ | × | 图片+文本审美 |
| **CLIP / SigLIP** | 512-768 | ✓ | △ | × | 纯视觉检索 |
| **Jina CLIP v2** | 1024 | ✓ | 89 | △ | 长文本多模态 |
| **Qwen3-Embedding** | 1024-4096 | × | 100+ | × | 通用 dense，TEI 支持好 |

Reranker 候选：
- **BGE Reranker v2-m3** (0.6B, Apache-2.0, BEIR top-tier) — 推荐主力
- **Cohere Rerank 3.5** — SaaS，$2/1k 请求 [pinecone pricing 引用]
- **Jina Rerank** — 多语种，长上下文

来源：[BGE-M3 HF](https://huggingface.co/BAAI/bge-m3), [BGE Reranker v2 HF](https://huggingface.co/BAAI/bge-reranker-v2-m3), [TEI GitHub](https://github.com/huggingface/text-embeddings-inference)

### 1.5 特征平台与在线推理（5 候选）

| 系统 | 定位 | 关键能力 | 推荐阶段 |
|------|------|---------|---------|
| **Feast** | OSS 特征库 | 17+ 在线 store，Qdrant/Milvus/Faiss 一等公民 | 10万 DAU 起 |
| **Hopsworks** | 企业级 Feature Store | 集成 KServe / 在线 transformer | 企业 |
| **自研 Redis + Flink** | 字节/美团常用 | 极低延迟 (p99 < 5ms) | 千万级 |
| **Triton + TensorRT** | 在线推理服务 | 多模型 / GPU batching / 量化 | 通用 |
| **TF Serving / TorchServe** | 框架原生 | 简单 gRPC + 版本化 | 早期 MVP |

来源：[Feast GitHub](https://github.com/feast-dev/feast), [TF Serving GitHub](https://github.com/tensorflow/serving)

---

## 2. 三阶段架构草图

### 阶段 1：MVP（< 1万 DAU，预算 < $300/月）

```
┌────────────────────────────────────────────────────────┐
│  Next.js / FastAPI 前端 + BFF                           │
└────────────────────────┬───────────────────────────────┘
                         │ POST /search?q=&user_id=
┌────────────────────────▼───────────────────────────────┐
│  推荐网关 (FastAPI / 1×CPU)                              │
│  - 简单的规则召回（热门 + 标签）                          │
│  - Embedding: TEI single L4 GPU (1 卡)                  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼───────────────────────────────┐
│  pgvector (PostgreSQL 16 + pgvector 0.7)                │
│  - 100K ~ 1M item embeddings                            │
│  - HNSW (m=16, ef_construction=64, ef_search=40)        │
│  - 与用户/标签数据共存                                   │
└─────────────────────────────────────────────────────────┘
        ↑                                   ↑
        │ 写入（item 新增）                  │ 写入（用户行为）
        │                                   │
   Postgres 主库 ──────────────── Kafka (单机) ──────────┘
```

**关键决策**：
- TEI 跑 BGE-M3 dense（1024 dim），1×L4 GPU 即够（吞吐 200 QPS）
- 用户向量存 pg，co-located with feature
- 召回后用 BGE Reranker v2 重排 Top 100 → Top 20

### 阶段 2：10万 DAU（预算 $3–5K/月）

```
┌─────────────────────────────────────────────────────────────┐
│  Cloudflare / Nginx (CDN + 边缘缓存)                          │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────▼─────────────┐
        │  BFF (Go)              │
        │  - 鉴权、限流、特征组装  │
        └──────────┬─────────────┘
                   │
   ┌───────────────┼──────────────────┐
   │               │                  │
   ▼               ▼                  ▼
┌──────┐   ┌───────────────┐   ┌─────────────┐
│召回层 │   │特征服务         │   │粗排层       │
│      │   │                │   │             │
│Qdrant│   │Redis 7         │   │LightGBM/Catboost│
│HNSW │   │(用户画像+实时)   │   │(双塔点积)    │
└──────┘   └───────────────┘   └─────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │精排: BGE Reranker│
          │(vLLM, 1×L40)     │
          └────────┬─────────┘
                   ▼
                Top-K 推送给前端
```

**关键变化**：
- 切到 **Qdrant 单机**（200K–5M item 向量），RPS 4x 于 pgvector
- **Redis 7 + Feast** 做用户实时特征（最近 30 min 浏览 / 点赞）
- **BGE Reranker v2** via TEI 替代规则排序
- Embedding 推理：vLLM 1×L40 (48GB) 或 TEI 同卡
- 行为流：Kafka → Flink → Redis 实时特征

### 阶段 3：千万级 DAU（预算 $50–120K/月）

```
┌──────────────────────────────────────────────────────────────────────┐
│  边缘层: CDN + 边缘 KV (召回 Top-K 缓存 1 min)                          │
└──────────────┬───────────────────────────────────────────────────────┘
               │
    ┌──────────▼──────────────────────────────────────────┐
    │  API Gateway (Envoy + 自定义 Lua)                     │
    │  - 分流 / A/B / Shadow                                  │
    └──────────┬──────────────────────────────────────────┘
               │
   ┌───────────┼──────────────────────────────────────────────┐
   │           │           │           │           │            │
   ▼           ▼           ▼           ▼           ▼            ▼
┌──────┐  ┌──────┐    ┌──────┐    ┌──────┐   ┌──────┐   ┌─────────┐
│向量 │  │倒排 │    │行为 │    │i2i │   │u2u │   │实时特征  │
│召回 │  │召回 │    │召回 │    │图   │   │向量 │   │(ByteHTAP) │
│Milvus│  │ES+ │    │Tair │    │(GraphDB│  │(GPU) │  │         │
│Hot/ │  │BM25│    │      │    │)    │   │      │   │         │
│Cold │  │     │    │      │    │      │   │      │   │         │
└──┬───┘  └──┬───┘    └──┬───┘    └──┬───┘   └──┬───┘   └────┬────┘
   │          │           │           │          │            │
   └──────────┴───────────┴───────────┴──────────┴────────────┘
                              │
                   ┌──────────▼──────────┐
                   │ 粗排: 多目标 DNN      │
                   │ (CTR × CVR × 多样性) │
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐
                   │ 精排: Triton Ensemble │
                   │  + Cross-encoder     │
                   │  (vLLM 4×H100)       │
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐
                   │ 重排: 业务规则 + 多样性│
                   │ (MMR / DPP)          │
                   └──────────┬──────────┘
                              │
                         用户感知
```

**关键变化**：
- **Milvus 分布式 + DiskANN** 存 100M–1B 向量，热 10% 走 HNSW 内存分片，冷 90% 走 DiskANN SSD 分片
- **多路召回**：向量 / 倒排 / 行为 CF / i2i 图 / 实时上下文
- **Embedding 推理**：Triton + vLLM 4×H100，QPS 5–10K embedding/s
- **特征平台**：自研 + Feast（Kafka → Flink → Redis + ClickHouse offline）
- **影子流量 / A/B 平台**：所有新模型走 5% 流量 24h shadow

---

## 3. 月度成本估算模板

### 3.1 容量假设

| 阶段 | User DAU | Item 数 | 单向量 size | 总向量 RAM | QPS (peak) | RPS (精排) |
|------|---------|---------|-------------|-----------|------------|-----------|
| MVP | 1K | 100K | 4KB (1024 fp32) | 0.4 GB | 5 | 1 |
| 10万 | 100K | 5M | 4KB | 20 GB | 200 | 30 |
| 千万 | 10M | 100M | 2KB (1024 fp16) | 200 GB | 5K | 800 |

注：`1024 维 × 4 bytes = 4 KB`，量化到 fp16 / int8 可减半

### 3.2 GPU 单卡价格（2025 报价）

| GPU | VRAM | Lambda/CoreWeave $/h | AWS $/h | 推荐用途 |
|-----|------|----------------------|---------|----------|
| RTX 4090 | 24GB | $0.40 | — | MVP / Embedding |
| L4 | 24GB | $0.50 | $0.70 | 推理 / 边缘 |
| L40S | 48GB | $1.20 | $1.80 | 推理主力 |
| A100 80G | 80GB | $1.80 | $3.00 | 训练 / 大 Embedding |
| H100 80G | 80GB | $2.50–3.00 | $4.00–5.00 | 大模型 / 千万级 |
| H200 | 141GB | $4.50+ | $6.50+ | MoE / 长上下文 |

来源：[CoreWeave 价格 ~$49/h 报道](https://xueqiu.com/4994696654/328552918), [H100 算力价格波动](https://www.163.com/dy/article/JFU9QCCH05561JOY.html), [Pinecone Standard pricing](https://www.pinecone.io/pricing/)

### 3.3 月度成本曲线（按 1M / 10M / 100M 用户）

| 阶段 | 向量库 | Embedding 推理 | 特征/RT | GPU 训练 | 网络/CDN | 运维 | **月合计** |
|------|--------|--------------|---------|----------|---------|------|-----------|
| **1K DAU** | pgvector $0 | TEI L4 $360 | Redis $30 | — | $10 | $0 | **~$400** |
| **100K DAU** | Qdrant 自托管 $400 (2×CPU) | vLLM L40S $1,300 | Redis+Kafka $400 | $300 | $200 | $1,000 | **~$3,600** |
| **10M DAU** | Milvus 集群 $8K (10 节点) | vLLM 4×H100 $24K | ByteHTAP/Redis $10K | $5K | $4K | $10K | **~$61K** |
| **100M DAU** | Milvus 大集群 $30K + DiskANN SSD $5K | Triton 16×H100 $96K | Kafka+Flink $30K | $20K | $20K | $40K | **~$240K** |

**优化杠杆**：
1. **向量量化**：fp32 → fp16 → int8 → binary 可降低 8–32× 存储与吞吐提升 2–5×
2. **端云协同**：用户向量本地算（iPhone Neural Engine / Android TFLite GPU），只上传 query embedding
3. **冷热分层**：10% 热数据 HNSW (RAM)，90% 冷 DiskANN (SSD)，存储省 70%
4. **Embedding Cache**：semantic cache (Redis 向量查询命中已计算) 省 30–50% 推理算力
5. **Reranker 裁剪**：Top-100 → Reranker → Top-20，可减少到 Top-50 精排省 50% GPU

---

## 4. 可观测性 & 评测自动化

### 4.1 关键 SLO / 指标

| 指标 | MVP SLO | 千万级 SLO | 监控 |
|------|---------|-----------|------|
| **Recall@100** | > 0.85 | > 0.92 | 离线 replay |
| **p50 召回时延** | < 50ms | < 30ms | Prometheus |
| **p99 召回时延** | < 300ms | < 80ms | Prometheus |
| **精排 p50** | < 200ms | < 80ms | OpenTelemetry |
| **Embedding cache hit** | > 20% | > 50% | Redis INFO |
| **GPU util** | > 40% | > 70% | nvidia-smi DCGM |
| **Embedding drift (cosine)** | < 0.05/月 | < 0.03/月 | 离线 cosine baseline |
| **冷热分层 hit rate** | — | > 90% | 自定义 metrics |

### 4.2 离线 Replay 框架

```python
# 流程：每日跑
1. 采样昨日 N=10K 用户会话
2. 用新模型跑召回 → 排序
3. 与 baseline 比对：Recall@K, NDCG, MRR
4. 监控 embedding drift: 新旧 embedding cosine 平均 > 0.95
5. 出具 PR diff report，自动触发 alert
```

### 4.3 在线 Shadow 模式

- **流量复制**：1% 真实流量 → 新模型
- **同请求双产出**：prod + shadow → 同时算分
- **不直接干预**：仅记录 diff / metric
- **24–48h 后**：自动比较 KPI（CTR、停留、转化），胜出则全量

### 4.4 监控栈推荐

- **指标**：Prometheus + Grafana（DCGM for GPU，OpenTelemetry SDK）
- **日志**：Loki / ELK
- **Trace**：Jaeger / Tempo
- **向量库内置**：Milvus / Qdrant 均暴露 Prometheus 端口

来源：[Milvus observability](https://milvus.io/docs/overview.md), [Qdrant observability](https://qdrant.tech/benchmarks/), [Prometheus + Grafana 部署模式](https://blog.csdn.net/weixin_48278764/article/details/141261923)

---

## 5. 推荐系统工程范式

### 5.1 Embedding 训练范式

| 范式 | 适用规模 | 代表系统 |
|------|---------|---------|
| **Parameter Server** | < 100B params | DistBelief, Angel |
| **AllReduce** | < 10B params (单机多卡) | PyTorch DDP, DeepSpeed |
| **EmbCache / HotKMA** | > 100B params + 高 QPS 推理 | 字节 / Meta DLRM 演化 |
| **Hybrid (PS + AllReduce)** | 工业标准 | 阿里/字节/百度 |

要点：
- 千万级 DAU 的 embedding 训练通常使用 **PS + EmbCache**（参数存 SSD，热访问驻内存）
- 用户侧 / item 侧 embedding 分别优化：user 用 AdaGrad / item 用 SGD
- **Negative Sampling**：百万级负样本 → 10K 量化候选
- **多任务学习**：CTR / CVR / 完播 多塔共享底层

### 5.2 实时特征工程

```
            ┌──────────┐
            │ 业务事件  │
            └─────┬────┘
                  ▼
        ┌─────────────────┐
        │  Kafka (分区)   │
        └─────┬───────────┘
              ▼
        ┌─────────────────┐
        │  Flink / Spark  │
        │  Streaming      │
        │  (窗口聚合 5min)│
        └─────┬───────────┘
              ▼
    ┌─────────┴─────────┐
    ▼                   ▼
┌─────────┐      ┌──────────────┐
│ Redis   │      │ ClickHouse   │
│ (在线)  │      │ (近线分析)   │
└─────────┘      └──────────────┘
```

字节 **ByteHTAP** 模式：HTAP 单库同时服务 OLTP + OLAP，省去双链路维护。
Meta **Velox**：C++ 向量化执行引擎，加速 Presto/Spark，p99 降低 50%+。

### 5.3 冷启动策略

| 阶段 | 策略 |
|------|------|
| 新用户 | 热门 + 标签 + LLM 推断兴趣（注册时让用户选 3 个 tag） |
| 新 Item | 文本/图像 embedding → 入向量库 + 主动曝光到 1% 流量 |
| Embedding 漂移 | 每月回算一遍全量 item embedding（offline batch） |
| 冷启动回退 | 规则召回（编辑精选 / 热门）兜底，10–20% 流量 |

来源：[Feast feature store](https://github.com/feast-dev/feast)

---

## 6. 已知风险清单 + 缓解策略

| # | 风险 | 影响 | 概率 | 缓解策略 | 来源 |
|---|------|------|------|---------|------|
| R1 | **Embedding 漂移** | 推荐质量下降 | 高 | 月度全量回算；线上 cosine 监控；AB 漂移超阈值告警 | [BGE-M3 评测方法论](https://huggingface.co/BAAI/bge-m3) |
| R2 | **HNSW 内存爆炸** | OOM / 单机瓶颈 | 高 (千万级) | 提前迁移到 Milvus DiskANN；冷热分层 | [Milvus DiskANN issue](https://github.com/milvus-io/milvus/issues/22127) |
| R3 | **GPU 单点故障** | 推理不可用 | 中 | 双卡主备 / 跨 AZ；TEI 自动 reload；模型权重 NFS | [TEI best practices](https://github.com/huggingface/text-embeddings-inference) |
| R4 | **特征穿越（data leakage）** | 离线指标虚高 | 高 | Feast point-in-time correct；严格时间戳管理 | [Feast point-in-time](https://github.com/feast-dev/feast) |
| R5 | **召回 + 排序不一致** | 排序模型只见热门 | 高 | 多路召回 + 曝光去重；Logits correction | 工业经验 |
| R6 | **热门偏差（popularity bias）** | 长尾无曝光 | 高 | 长尾加权；曝光校准；探索率 ε-greedy 5% | 工业经验 |
| R7 | **Pinecone / SaaS 锁定** | 数据迁移难 / 涨价 | 中 | 自托管 Qdrant/Milvus；Pinecone 仅 MVP 阶段 | [Pinecone pricing](https://www.pinecone.io/pricing/) |
| R8 | **LLM 成本失控** | 月度账单爆炸 | 高 | Semantic cache；query 合并；自托管 H100；端侧小模型 | [vLLM cache patterns](https://vllm.ai/blog) |
| R9 | **多模态 embedding 偏见** | 颜值单一审美 | 高 | 多目标（BGE-VL + 文本 + 行为融合）；人工审核 Top 1% | [SigLIP/BGE-VL](https://huggingface.co/facebook/SigLIP-base-patch16-224) |
| R10 | **法规合规**（GDPR / 个保法） | 用户向量删除困难 | 中 | 向量反演防护；用户粒度定时删除；支持 opt-out | 法律咨询 |
| R11 | **冷启动新 Item** | 永远不进 Top-K | 高 | 内容 embedding + 主动曝光池；item graph 邻居扩散 | 工业经验 |
| R12 | **Milvus OOM / IndexNode restart** | 索引重建阻塞 | 中 | 控制单分片大小；监控并自动隔离；disk warm-up | [Milvus 22127](https://github.com/milvus-io/milvus/issues/22127) |
| R13 | **GPU 供应紧张** | 训练延期 | 中 | 预留容量；多云（AWS + Lambda + CoreWeave）；国产替代（昇腾） | [H100 算力紧张](https://news.qq.com/rain/a/20241102A01OGZ00) |
| R14 | **Reranker 推理瓶颈** | 召回后尾延迟高 | 中 | Reranker 异步化；Top-100→50 截断；Reranker 模型蒸馏 | [BGE Reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| R15 | **向量库 filter 性能塌方** | 复杂筛选下 QPS 跌 10× | 高 | 预过滤；Filterable HNSW；属性列建独立索引 | [Qdrant benchmark filter](https://qdrant.tech/benchmarks/) |

---

## 7. 实施路线图（推荐 12 个月）

| 月份 | 关键交付 | 容量 / 性能目标 |
|------|---------|----------------|
| M1 | MVP 上线 (pgvector + TEI L4 + BGE-M3) | 100K item，p99 < 300ms |
| M2–3 | 切 Qdrant 单机；引入 Redis 特征；BGE Reranker | 5M item，p99 < 200ms |
| M4–6 | 引入多模态 (BGE-VL/CLIP)；多路召回；冷热分层预研 | 30M item，p99 < 100ms |
| M7–9 | 切 Milvus 分布式 + DiskANN；Kafka+Flink 实时特征；自研召回框架 | 100M item，p99 < 80ms |
| M10–12 | 多目标排序 (CTR×CVR×多样性)；Embedding drift 监控；端云协同 | 1B item，p99 < 50ms |

---

## 8. 关键来源汇总（35+ 条）

### 向量库 / 索引
1. [Milvus Overview](https://milvus.io/docs/overview.md) — Milvus 架构、索引、生产规模
2. [Qdrant Benchmarks](https://qdrant.tech/benchmarks/) — Qdrant vs Milvus vs Weaviate
3. [Vespa Vector Search](https://docs.vespa.ai/en/vector-search.html) — Vespa billion-scale ANN
4. [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid) — BM25+Vector, Relative Score Fusion
5. [pgvector GitHub](https://github.com/pgvector/pgvector) — HNSW/IVFFlat, binary quantization
6. [Chroma](https://www.trychroma.com/) — Hybrid retrieval, scale ceilings, SOC2
7. [Pinecone Pricing](https://www.pinecone.io/pricing/) — Serverless pricing model
8. [ANN-Benchmarks](https://ann-benchmarks.com/) — HNSW/IVF-PQ/ScaNN/DiskANN
9. [Microsoft DiskANN](https://github.com/microsoft/DiskANN) — DiskANN3 Rust, Vamana
10. [Google ScaNN](https://github.com/google-research/google-research/tree/master/scann) — Anisotropic Vector Quantization
11. [BillionANN benchmark](https://github.com/hkust-zhiyao/BillionANN) — Billion-scale ANN
12. [Milvus 22127 OOM issue](https://github.com/milvus-io/milvus/issues/22127) — DiskANN 索引 OOM 实测

### Embedding 推理
13. [vLLM Blog](https://vllm.ai/blog) — PagedAttention, FP8 KV-cache, MoE scaling
14. [SGLang GitHub](https://github.com/sgl-project/sglang) — RadixAttention 5x prefix caching
15. [LMDeploy GitHub](https://github.com/InternLM/lmdeploy) — TurboMind 1.8x vLLM
16. [Triton Inference Server](https://github.com/triton-inference-server/server) — Dynamic batching, multi-model
17. [Xinference](https://github.com/xorbitsai/inference) — Heterogeneous, distributed
18. [HuggingFace TEI](https://github.com/huggingface/text-embeddings-inference) — Embedding serving, BGE Reranker
19. [TensorFlow Serving](https://github.com/tensorflow/serving) — gRPC, canary/A-B

### Embedding 模型
20. [BGE-M3 HF](https://huggingface.co/BAAI/bge-m3) — Multi-functional, multi-lingual, multi-granular
21. [BGE Reranker v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) — BEIR top-tier reranker
22. [SigLIP HF](https://huggingface.co/facebook/SigLIP-base-patch16-224) — Sigmoid loss image-text

### 推荐系统工程
23. [Feast GitHub](https://github.com/feast-dev/feast) — Feature store, Qdrant/Milvus/Faiss
24. [大模型推理框架对比 知乎](https://zhuanlan.zhihu.com/p/22542987868) — vLLM/SGLang/TRT-LLM 实测
25. [开源大模型推理引擎现状 知乎](https://zhuanlan.zhihu.com/p/755874470) — 推理优化全景
26. [SGLang vs vLLM](https://zhuanlan.zhihu.com/p/18942501855) — RadixAttention 详解

### 成本与市场
27. [CoreWeave H100 价格](https://xueqiu.com/4994696654/328552918) — $49/h 2025 vs $38/h 2023
28. [H100 价格波动](https://www.163.com/dy/article/JFU9QCCH05561JOY.html) — 暴跌 75% 后再涨
29. [H100 算力紧缺](https://news.qq.com/rain/a/20241102A01OGZ00) — H100 涨价 20%
30. [H100 半年涨三成](https://so.html5.qq.com/page/real/search_news?docid=70000021_72469e0b25a91252) — Token 热加剧算力荒

### 可观测性
31. [Prometheus + Grafana 部署](https://blog.csdn.net/weixin_48278764/article/details/141261923) — 通用模式
32. [DCGM / nvidia-smi metrics](https://blog.csdn.net/pymzy666skr/article/details/145740728) — GPU 监控
33. [Grafana 统一运维视图](https://cloud.tencent.com/developer/article/2709475) — 数据可视化

### 推理框架对比
34. [vLLM 架构解析](https://blog.csdn.net/2301_80239908/article/details/153333993) — PagedAttention 详解
35. [2025 大模型推理框架](https://blog.csdn.net/2401_85390073/article/details/151184609) — vLLM/SGLang/TRT-LLM 全解析

---

## 9. 一句话建议

> **MVP 不要买 Pinecone**，用 pgvector + TEI L4 跑通；**到 100K DAU 换 Qdrant**；
> **到 10M DAU 必须上 Milvus 分布式 + DiskANN**；GPU 永远 2× 富余做主备；
> **所有新模型先 Shadow 24–48h** 再切流量；**Embedding 月度全量回算 + 实时 drift 监控** 是生死线。