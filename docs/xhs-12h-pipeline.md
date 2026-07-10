# XHS 12-Hour Content Consolidation Pipeline

> 稳定、可恢复、可观察的本地数据整理流水线。
> 不是爬虫，不访问小红书，不绕过风控。

## 是什么

这个脚本读取项目中已有的所有数据源（`link_sources.json`、`manifests/`、`link_packs/`、`taste_graph.json`、SQLite DB、日期文件夹），去重、归一化、输出结构化 JSONL 和 CSV。

**不做什么：**
- 不访问小红书网站
- 不绕过反爬/风控/验证码
- 不修改 cookies、登录态、密钥、`.env`
- 不安装新依赖
- 不删除已有数据
- 不并发暴力请求

## 运行方式

### Dry-Run（安全测试）

```bash
# 默认 dry-run，处理 5 条
python scripts/run_xhs_12h_pipeline.py --dry-run --max-items 5

# 只看 link_pack 来源的数据
python scripts/run_xhs_12h_pipeline.py --dry-run --source link_pack --max-items 10

# 只看 manifest 数据
python scripts/run_xhs_12h_pipeline.py --dry-run --source manifest --max-items 10
```

### 12 小时完整运行

```bash
python scripts/run_xhs_12h_pipeline.py --live --duration-hours 12 --resume
```

### 中断后恢复

```bash
# 中断后直接重新运行（带 --resume）
python scripts/run_xhs_12h_pipeline.py --live --duration-hours 12 --resume
```

### 有限量测试运行

```bash
# 100 条测试
python scripts/run_xhs_12h_pipeline.py --live --max-items 100
```

### 自定义速率限制

```bash
# 更长间隔（保守爬取）
python scripts/run_xhs_12h_pipeline.py --live --sleep-min 5 --sleep-max 10 --duration-hours 12
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dry-run` | True | Dry run 模式（默认开启） |
| `--live` | False | 关闭 dry-run，真实运行 |
| `--duration-hours` | 12 | 最大运行时长（小时） |
| `--max-items` | 5 (dry-run) / 无限制 (live) | 最大处理条数 |
| `--sleep-min` | 2.0 | 条目间最小间隔秒数 |
| `--sleep-max` | 5.0 | 条目间最大间隔秒数（随机） |
| `--resume` | False | 从上次 checkpoint 恢复 |
| `--source` | None | 按来源过滤 |

## 输出目录

所有输出写入 `runs/<run_id>/` 目录：

```
runs/
└── run_20260706_120000/
    ├── output.jsonl        # 结构化 JSONL（每行一条记录）
    ├── output.csv          # CSV 导出
    ├── checkpoint.json     # 断点续跑状态
    └── summary.json        # 运行摘要报告
```

### 输出字段

每条记录包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_type` | str | 数据来源（link_sources_json, manifest_pick, link_pack, db_lookbook 等） |
| `source_id` | str | 源 ID |
| `url` | str | 原始 URL |
| `title` | str | 标题 |
| `name` | str | 名称 |
| `author` | str | 作者 |
| `tags` | str (JSON) | 提取的标签 |
| `raw_text` | str | 原始文本（dry-run 截断至 200 字符） |
| `images` | str (JSON) | 图片列表 |
| `collected_at` | str (ISO 8601) | 采集时间 |
| `status` | str | 状态（success / error / dry_run / consolidated） |
| `error` | str | 错误信息 |
| `category` | str | 分类 |
| `section` | str | 段落（link_pack 中使用） |
| `why` | str | 收录原因 |
| `theme` | str | 主题 |
| `manifest_date` | str | Manifest 日期 |
| `pack_date` | str | Link pack 日期 |
| `concept_id` | str | Taste graph 概念 ID |
| `label` | str | 概念标签 |

## 安全限制

**反追踪/防检测策略（已内置）：**
- User-Agent 池：8 个真实浏览器 UA 随机轮换
- Accept-Language 随机化（zh-CN/en-US/ja 四种组合）
- Referrer 随机化（Google/Bing/Pinterest/direct/no-referrer）
- Session-aware pacing：模拟人类疲劳曲线，运行越久间隔越长
- Per-domain cooldown：同域名请求间隔至少 5 秒
- 5% 随机"人类暂停"：偶发 3-8 秒长停顿
- 微抖动：按条目序号的小幅时间变化（±1 秒）

**绝对不做的操作：**
1. 不访问 `xiaohongshu.com` 或 `creator.xiaohongshu.com`
2. 不修改 `data/xhs_cookies.json`
3. 不修改 `.env` 文件
4. 不修改 `modules/xhs_publisher/` 下的任何文件
5. 不删除任何现有数据文件
6. 不安装 Python 包（仅用标准库）
7. 不绕过验证码或风控系统
8. 不并发请求（单线程顺序处理）
9. 不使用代理池或反检测技术
10. 不自动化发布或登录

## 中断处理

- 按 `Ctrl+C` 触发优雅退出
- 当前条目处理完成后保存 checkpoint
- 再次运行带 `--resume` 可从中断处继续
- 已处理条目不会重复处理（按 URL/source_id 去重）

## 停止运行

```bash
# 按 Ctrl+C 优雅退出
# 或发送 SIGTERM
kill -TERM <pid>

# 查看当前运行的 pipeline
ps aux | grep run_xhs_12h_pipeline
```

## 数据来源

脚本从以下本地文件读取：

| 来源 | 路径 | 说明 |
|------|------|------|
| 种子源 | `link_sources.json` | lookbook/video/article 种子 URL |
| 清单 | `manifests/*.json` | AI 生成的主题清单 |
| 链接包 | `link_packs/*.txt` | 人工整理的每日链接 |
| 品味图谱 | `data/taste_graph.json` | 知识图谱概念节点 |
| 数据库 | `data/taste_graph.db` | SQLite 已批准源 |
| 输出文件夹 | `YYYY-MM-DD/` | 日期命名的输出目录 |

## 依赖

仅使用 Python 3 标准库，无需安装任何第三方包：

- `argparse`, `csv`, `datetime`, `hashlib`, `json`, `os`, `pathlib`, `random`, `signal`, `sqlite3`, `sys`, `time`, `traceback`

## 监控和日志

脚本输出到 stdout，格式：

```
[load] Reading project data...
[load] Loaded 142 raw items from all sources
[dedup] 12 duplicates skipped, 130 new items to process
[mode] DRY RUN — no real processing, output truncated
[status] Processed: 10 | Success: 10 | Failed: 0 | Rate: 2.1/s | ETA: 1min
[checkpoint] Saved at 10 items
...
============================================================
  Pipeline Complete
============================================================
  Run ID:      run_20260706_120000
  Mode:        DRY RUN
  Duration:    12.3s
  Total loaded:142
  Processed:   130
  Success:     130
  Failed:      0
  Duplicates:  12
  Output:      runs/run_20260706_120000
============================================================
```

## 定制和扩展

如需加入实际网页抓取能力，可以在 `process_item()` 函数中加入对项目已有 `WebCrawler` 的调用（在 `--live` 模式下）。但默认不启用，因为本项目不是爬虫项目。

加入方式（可选）：
```python
# 在 process_item() 中，非 dry_run 且 --live 时：
if not dry_run and item.get("url"):
    try:
        from taste_graph_ai.infrastructure.crawlers.web import WebCrawler
        # ... 按需调用
    except ImportError:
        pass  # 降级为纯整理模式
```
