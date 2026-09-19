# source_sync 审批绕过问题提案（仅隔离测试，不含补丁）

## 结论
现有 `sync_seed_sources()` 会把种子文件中已存在但状态非 `approved` 的来源强制改为 `approved`。因此：人工的 `pending/rejected/deferred` 决定会在下一次同步被覆盖；新建来源虽首次为 `pending`，但第二次同步即自动批准。事件中的 `previous_status` 也在状态修改后读取，错误记录为 `approved`。

## 触发与前后状态
| 场景 | 触发条件 | 当前前状态 | 当前后状态 | 期望后状态 |
|---|---|---|---|---|
| 已存在 pending | URL 命中且再次同步 | pending | approved | pending |
| 已存在 rejected | URL 命中且再次同步 | rejected | approved | rejected |
| 已存在 deferred | URL 命中且再次同步 | deferred | approved | deferred |
| 新来源首次同步 | URL 不存在 | 无 | pending | pending |
| 新来源第二次同步 | 同一 URL 再次出现 | pending | approved | pending |
| 自动审批事件 | 非 approved 被覆盖 | 原状态 | 事件误报 previous_status=approved | 应保留真实 before 状态 |

直接代码原因：`existing.status != APPROVED` 分支无条件批准；且先赋值再记录 `existing.status.value`。

## 推荐最小修改
1. 同步已存在记录时仅做 URL 存在性确认，不修改 `status/reviewed_at`。
2. 删除或禁用“非 approved 自动 approved”分支；保留必要元数据更新也应限制为非审批字段。
3. 新来源继续创建为 `pending`。
4. 如仍需记录审批/覆盖事件，先缓存 `before_status = existing.status`，再执行任何变更；但事件审计不能替代审批流修复。
5. 研究候选来源应维护独立 catalog/候选表，直到人工明确审批后才进入正式 source seed；“新来源 pending”不能阻止下一次 seed 同步自动 approved。

## 迁移与兼容风险
- 修复后，种子文件中的历史 rejected/deferred/pending 不会自动进入抓取队列，可能改变当前“实际会抓”的行为。
- 不建议为此重扫生产数据库；如后续确需处置，应另行做只读审计、备份和人工确认。
- 可能存在依赖“启动即全部 approved”的任务，需要显式审批/发布流程替代。
- 旧事件已错误的 `previous_status` 不应静默改写。

## 验收清单
- 新来源首次、第二次同步均保持 pending。
- pending/rejected/deferred 连续同步不被改状态、不改 reviewed_at。
- approved 保持 approved。
- 若产生事件，事件包含真实 before 状态，且不得把 rejected 事件描述成从 approved 变化。
- 独立研究候选在明确审批前不会进入自动批准 seed。

## 测试范围说明
隔离结果共 11 个失败：其中 5 个属于本 source_sync 审批问题；其余 6 个是年龄判定/URL 去重的独立预期失败，不能归因于生产 source_sync。所谓“原型 6”应仅指实验原型中的独立问题，不应表述为生产来源 5 之外的生产事故。本报告仅提案，未生成补丁，也未声明修复或部署。