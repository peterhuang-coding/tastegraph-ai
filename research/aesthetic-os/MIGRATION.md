# Aesthetic-OS Research — 迁移说明

**迁移日期**: 2026-07-29
**来源**: `/Volumes/SanDisk2TB/aesthetic-os/research/`（19 份 .md，472K）
**目标**: 本目录 `research/aesthetic-os/`
**决定**: 老板 2026-07-29 总控冷启动，把 aesthetic-os 项目关停并整合到 tastegraph-ai

## 包含文件

19 份原始研究文档全部完整保留：

- `PLAYBOOK.md` — 总研究索引
- `aesthetic-media-creators-commerce-loop.md` — 审美媒体商业闭环（691 行）
- `mubu-aesthetic-media-creators-commerce.md` — 可导入幕布的层级大纲（273 行）
- `recsys-architecture.md` + `recsys-infra.md` — 推荐系统架构（**直接服务新方向"推荐引擎+搜索"**）
- `benchmarks-and-data.md` — 评测与数据
- `coding-semantic-model.md` — 语义编码
- `image-aesthetic-system.md` — 图像审美系统
- `social-magnetism-mechanics.md` — 社交磁吸机制
- `china-curation-landscape.md` / `curation-brand-landscape.md` / `city-curation-brands.md` — 中国策展版图
- `design-magazines.md` / `music-culture-media.md` / `hotel-curation.md` / `hidden-new-york-case.md` — 媒体案例
- `experience-commerce-playbook.md` / `monetization-playbook-v2.md` / `monetization-playbook.md` — 变现手册

## 后续处理

- 原 `/Volumes/SanDisk2TB/aesthetic-os/` 目录保留为 backup，本轮不删除
- 本次迁移为"内容到位"，未 commit / 未 push
- 与「Git 备份」Assignment 一起 commit + push 到 origin
- 「推荐引擎+搜索」主线 Assignment 启动后，优先消费 `recsys-architecture.md` + `recsys-infra.md` + `benchmarks-and-data.md`
