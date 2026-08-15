# moodboard.

> **A personal visual sampler.** 52 sources. 9 images per pack. One editor.

---

## What we are

A **personal visual sampling system**. We continuously sample from 52 editorial
content sources (Vogue / 032c / Highsnobiety / Dazed / Numéro / Popbee / Are.na /
NOWRE / Hypebae / Gentle Monster ...), pass every image through quality scoring
and metadata extraction, and produce **daily 9-image sampling sets**.

The system is a tool for **one editor**, not a platform for many. Everything it
produces is for the operator's own decision-making. The unit of value is not
the post, the reach, or the growth — it is **the sample**.

---

## What we are not

- **Not a search engine.** No query, no ranking, no "results".
- **Not a feed.** No infinite scroll. No algorithmic recommendation chasing.
- **Not a content platform.** No end users. No engagement metrics. No virality.
- **Not a generator.** We do not create images. We select from what already exists.
- **Not mass-market.** `SKIP_DOMAINS` hard-excludes IKEA / Taobao / Tmall / Amazon /
  eBay / Pinterest / Instagram / TikTok / Reddit / Facebook / Twitter. Coverage of
  these is a feature, not a bug.
- **Not chasing traffic.** Coverage is not the goal. **Density** is.

---

## What we output

| Output | What it is |
|---|---|
| **Daily pack** | 9-image sampling set per day, unified voice captioning, stored in `posts/YYYY-MM-DD/` |
| **Knowledge graph** | Metadata for every sampled image: source · brand · designer · color · material · mood · object · location |
| **Trend signal** | What is rising / fading across the sampling pool (340+ keywords) |
| **Source brief** | Daily `SOURCES.html`: 8 approved sources (oldest reviewed first) + 4 newly discovered |
| **Weekly report** | Aggregate stats across sampling periods |

---

## How we sample

1. **Source filter** — `SKIP_DOMAINS` + `LOW_PRIORITY_DOMAINS` + source health monitoring
2. **Quality scoring** — CLIP embedding + zero-yield streak detection
3. **Metadata extraction** — brand / designer / color / material / mood / object / location entities into the knowledge graph
4. **Voice captioning** — unified voice routing (`taste_ip_system` / `docs/voice.md`) for all AI-written annotations
5. **Pack assembly** — theme clustering + 9-image selection per pack
6. **Operator review** — daily curation UI: ✓ 对味 / ⭐ 精 / ⏭ 弃, feedback flows back into the graph

---

## What "good" looks like

- A pack that feels **dense**, not comprehensive
- A graph where you can trace any image back to its source in two clicks
- A trend signal that says *"the pool is shifting"*, not *"you should post this"*
- A daily brief that takes **3 minutes to scan**, not 30

---

## Aesthetic reference

The original moodboard — `Hidden NY × JJJJound` — is preserved at `README.md`.
It is the design source material: the **what** we sample for. This document is
the **how** and the **why**.

---

## Versioning

This document was written **2026-08-15** after the 2026-07-29 scope change
(see `git log` for `534a89a fix(safety): 4 层防御` and the subsequent
crawler-optimization work). The system was previously framed as a Xiaohongshu
auto-publish pipeline — that framing is retired. This document supersedes it.