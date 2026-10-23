# 数据运营只读视图

只读页面 `/data-ops.html` 与只读接口 `GET /api/v1/data-ops/snapshot`，用于查看四块分时证据：

1. **inventory** 库存 / 文件缺口
2. **sources** 来源 / 追溯
3. **updates** 更新 / 失败 / 备份
4. **publication** 候选 / 发布进度

本交付不宣称线上入口已部署，需在独立工作树由父级验收后另行安排生产部署。

## 安全与行为边界

- 仅 GET；对同一路径 POST 返回 405 且不写任何文件。不启动采集、不写库、不启用源、不改队列/批准/日限额。
- 接口只读取环境变量 `TASTEGRAPH_DATA_OPS_SNAPSHOT` 指向的**已生成** JSON 文件；未配置、文件缺失、JSON 损坏、根不是 JSON 对象一律返回 `503 {"detail":"数据运营快照暂不可用"}`，错误中不回显路径。
- 不默认读取 Hub/数据库/任何固定位置；不读取该变量以外的文件。
- 200 与 503 响应一律带 `Cache-Control: no-store`。
- `services/data_ops.py::build_view(raw)` 做白名单投影：只输出固定契约字段，原始日志、配置路径、URL、账号及任何未知 key 均不会出现在响应中。
- 计数只接受**非负整数**；布尔、浮点（含 `NaN`/`Infinity`）、负数、null、类型错误 → `null`（页面显示“未知”）；真实 `0` 保留为 `0`。这也保证投影结果始终可被严格 JSON 序列化，不会因 `NaN`/`Infinity` 触发 500。
- 状态字段只走固定 enum：备份完整性 ∈ `ok` / `mismatch` / `failed`；采集日状态 ∈ `succeeded` / `running` / `partial` / `failed`。任何其他字符串（含伪装成路径/URL 的值）→ `null`，不会被原样回传。
- 时间字段（`assembled_at`、各块 `as_of`、备份 `finishedAt`）只有在是**带时区的合法 ISO-8601** 时才回传；无时区的朴素时间既不猜 UTC 也不猜浏览器本地时区，一律 `null` / “时间未知”。`scheduled_date` 只接受真实日历日期 `YYYY-MM-DD`。
- 每块 `as_of` 来自各自原始字段（见下），`assembled_at` 不被当作全库审计时间；缺失为 `null`，页面提示“时间未知”。
- 页面新鲜度始终以**当前时钟 `Date.now()`** 在每次渲染（含每次刷新）时与证据时间比较：超过 24 小时提示“旧快照”，证据时间位于未来提示“证据时间异常：位于未来”（不会当作正常）。刷新失败保留上次可信视图及其原始证据时间，并重新按当前时钟计算新鲜度标记。
- 生成器队列已满（updates）与素材成熟度目标（sources 的目标区间，输入为两个非负整数数组 `[20,30]`，展示 `20–30`）分列；目标是目标区间，不是已完成库存。
- 提交不等于公开：publication 只展示“本地日志提交数”，没有公开证据就不显示已公开数。
- 溯源记录数不等于下载图片数：sources 块的追溯/覆盖统计（`images_source_coverage` 与 `images_with_provenance`）逐条标注其证据时间为**数据库质量块**时间（`section_freshness.database_quality_and_file_existence.as_of`），与来源层自己的 `as_of` 不同，不混为同一时刻。
- 采集日记录按原 `scheduled_date` 标注，不称为“今天”；各行另标 `today_at_snapshot.as_of`，缺失为未知、超过24小时为旧快照，不借用运营块的新时间。

## 输入快照契约（合成示例）

父级在真实环境把实际 snapshot 转换为以下最小公开契约，再供本页面预览。所有值均为合成示例。

```json
{
  "assembled_at": "2026-01-02T22:30:00+08:00",
  "db_observed_at": "2026-01-02T22:00:00+08:00",
  "database": {
    "counts": { "images": 90, "sources": 52 },
    "quality": {
      "images_file_existence": {
        "with_path": 99,
        "existing_file": 90,
        "missing_file": 9
      },
      "images_source_coverage": {
        "total": 100,
        "missing_path": 1,
        "missing_source_id": 20,
        "unresolved_source_id": 2
      },
      "images_with_provenance": 64
    }
  },
  "source_layers": {
    "DB": { "rows": 60, "approved": 40, "pending": 15, "rejected": 5 },
    "peer_research": { "verified_research_sources": 12, "ingestion_changes": 3 },
    "archive_reserve": { "new_complete_visual_sets": 4, "target_size_range": [20, 30] }
  },
  "latest_operations_observed_at": "2026-01-02T22:00:00+08:00",
  "latest_operations": {
    "lastBackup": {
      "ok": true,
      "finishedAt": "2026-01-02T04:00:00+08:00",
      "integrity": "ok",
      "countsMatch": true,
      "backupBytes": 2048
    },
    "activeCandidatePacks": 2,
    "activePackLimit": 4
  },
  "today_at_snapshot": {
    "scheduled_date": "2026-01-02",
    "as_of": "2026-01-02T22:00:00+08:00",
    "status": "succeeded",
    "processed_at_snapshot": 20,
    "inserted_at_snapshot": 10,
    "processed_status_counts": { "downloaded": 10, "failed": 2, "skipped": 8 }
  },
  "publication": {
    "as_of": "2026-01-02T22:00:00+08:00",
    "finite_batch_capacity": 20,
    "consumed": 4,
    "remaining": 16,
    "today_submitted_by_local_log": 1,
    "daily_cap": 4,
    "earliest_slot": 5,
    "editorial_blocked_slots": [5],
    "hold": false
  },
  "section_freshness": {
    "database_quality_and_file_existence": { "as_of": "2026-01-02T20:00:00+08:00" },
    "source_layers_and_update_chain": { "as_of": "2026-01-01T20:00:00+08:00" }
  }
}
```

### as_of 对应关系

| 区块 | as_of 来源字段 |
| --- | --- |
| inventory | `section_freshness.database_quality_and_file_existence.as_of` |
| sources（DB/peer/archive 各项） | `section_freshness.source_layers_and_update_chain.as_of` |
| updates | `latest_operations_observed_at` |
| publication | `publication.as_of` |

注意：sources 块末尾的追溯/覆盖各项（下表）来自 `database.quality`，其真正证据时间是 `section_freshness.database_quality_and_file_existence.as_of`，与来源层头部 `as_of` 不同；这些 item 的 `note` 会显式标注各自证据时间（缺失时标“证据时间：未知”）。

### 真实字段键 → 展示项

| 区块 | 展示项 | 输入键 |
| --- | --- | --- |
| inventory | 图片总数 / 来源总数 | `database.counts.images` / `database.counts.sources` |
| inventory | 有文件图片 / 缺失文件图片 | `database.quality.images_file_existence.existing_file` / `.missing_file`（同对象另有 `with_path=99=90+9`） |
| inventory | 无路径记录图片 | `database.quality.images_source_coverage.missing_path` |
| sources | 追溯覆盖图片总数 | `database.quality.images_source_coverage.total`（=100） |
| sources | 缺来源ID图片 | `database.quality.images_source_coverage.missing_source_id`（=20） |
| sources | 来源ID未解析图片 | `database.quality.images_source_coverage.unresolved_source_id`（=2） |
| sources | 有溯源记录图片 | `database.quality.images_with_provenance`（=64；note 明示溯源记录/链接数不等于已下载图片数） |
| sources | 完整视觉套目标区间 | `source_layers.archive_reserve.target_size_range`，仅接受两个非负整数的数组（小≤大），渲染 `20–30`；缺失/坏值为 `null` |
| updates | 备份完整性 | `latest_operations.lastBackup.integrity`，enum：`ok`/`mismatch`/`failed` |
| updates | 采集日状态 | `today_at_snapshot.status`，enum：`succeeded`/`running`/`partial`/`failed` |
| updates | 采集日日期标签 | `today_at_snapshot.scheduled_date`，仅接受合法 `YYYY-MM-DD`，否则标签用“日期未知” |

以上合成值仅用于示例；页面 enum 值映射为中文展示（如 `ok`→完整、`succeeded`→成功）。

## 输出契约

```json
{
  "assembled_at": "2026-01-02T22:30:00+08:00",
  "sections": [
    {
      "id": "inventory",
      "title": "库存 / 文件缺口",
      "as_of": "2026-01-02T20:00:00+08:00",
      "items": [{ "label": "图片总数", "value": 90, "note": null }]
    }
  ]
}
```

`id` 固定为 `inventory` / `sources` / `updates` / `publication`，顺序固定；`value` 为非负整数、固定 enum 字符串、布尔或 `null`（目标区间是 `20–30` 形式的固定文本），不会出现路径、URL、日志或任意字符串。

## 接入方式（父级在真实项目中执行）

1. 路由已在 `taste_graph_ai/api/router.py` 注册（`api_router.include_router(data_ops.router)`），路径自带 `/api/v1` 前缀，无需额外 prefix。
2. 部署环境设置只读快照文件路径，例如：
   `TASTEGRAPH_DATA_OPS_SNAPSHOT=/var/lib/tastegraph/data-ops-snapshot.json`
3. 快照 JSON 由**既有**维护流程在完成采集/备份后顺手更新；本交付**不新建定时器、不新增依赖**（仅标准库与现有 FastAPI）。
4. 页面入口已加入 `static/index.html` 导航；`data-ops.html` 刻意不加载 `/js/app.js`（其 Cmd/Ctrl+R 会触发 POST），仅加载独立 `/js/data-ops.js`，后者只发固定 GET 并用 `textContent` 渲染。

## 本地验证

```bash
/opt/anaconda3/bin/python3 -m unittest discover -s tests -p test_data_ops.py -v
node --check taste_graph_ai/static/js/data-ops.js
```

测试使用独立 FastAPI app 只挂载本 router（不导入完整生产 app），共 30 项，覆盖：GET 无写入且重复响应字节一致、POST 405 不写文件、缺/坏快照/未配置变量/非对象根均 503 且带 `no-store` 不回显路径、危险字段白名单排除（含经 status/integrity 注入的路径/URL）、未知/0 语义、计数拒绝布尔/浮点/负数/`NaN`/`Infinity`（严格 JSON 可序列化）、真实 schema 键（existing_file/missing_file/images_source_coverage/images_with_provenance）与溯源项证据时间标注、目标区间数组 `[20,30]→20–30` 及各类坏值、带时区时间校验（朴素时间不猜时区）、`scheduled_date` 日历校验、各块独立 as_of 与混合日期。
