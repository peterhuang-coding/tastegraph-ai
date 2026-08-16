# crawl_logs/ — 24h 小时级爬取沉淀

**起点**:2026-08-15 14:44 +0800(pilot 跑通)
**节奏**:每小时一次,CronCreate `3eabeb11`,HH:07 触发
**目的**:用 Playwright computer-use 真页爬取每天 5 个目标,记录 status/code/HTML/screenshot,搜渠道与防反爬反模式
**明日复盘看这里**:本文档 + `proposals.md` 的累积 bullet

## 落档结构
- `tick-YYYY-MM-DD-HH.{json,md}` — 每次 tick 的明细 + 原始 signals
- `proposals.md` — 累积的设计方案变化(每次 tick 加一条 bullet)
- `artifacts/shots/<label>.png` — 每次最后一个 tick 的截图(覆盖)
- `artifacts/html/<label>.html` — 每次最后一个 tick 的 HTML 全文(覆盖)

## 目标清单(每 tick 都会跑)
| Label | URL | 已知风险 |
|---|---|---|
| hypebeast | hypebeast.com/fashion | Akamai 202 |
| grailed | grailed.com/ | 用户说的"Grill",SPA shell + JS challenge |
| therealreal | therealreal.com/ | 403 |
| duckduckgo_ebay_search | html.duckduckgo.com/?q=site:ebay.com + ... | 403 限流 |
| wiki_marketplace | en.wikipedia.org/wiki/Online_marketplace | 真参考源,200 |

## 复盘样表(明天我看这个)
```
tick HH:07 | healthy n/N | blocked signal
2026-08-15-14:57  pilot      1/5    [hypebeast 202, grailed 200/SPA-shell, thealreal 403, ddg 403, wiki 200]
2026-08-15-15:07  
...
2026-08-16-14:07  cum: 24    x/x    
```

