# experiments/algorithm_lab 评审说明

## 当前结论（务必先读）

- 本目录是**有界离线算法实验**，**不是生产就绪方案**。
- 四条实现路线**未全部通过验收**；仅 `ranking` 作为实验原型保留。
- 测试结果：合成测试 **125 通过、11 个严格 xfail、11 个真实断言失败已独立复现**；这 11 项由 **5 个既有 source-sync 断言失败**和 **6 个未采用年代/去重原型的断言失败**组成。
- 原始回归基线：`origin/main`（`354e23f`，已通过 `git fetch` 确认未变）**51 通过**。最终合并运行相关回归与实验测试为 **176 通过、11 xfail**。
- 报告前共 36 次尝试、19 个任务；加本报告共 37 次尝试、20 个逻辑任务，峰值并发 4。提供方仅限 `volcengine-plan`。
- 原始结果放在 `results/`。未运行的 oracle/来源集中度测量没有结果，不以静态回包冒充实验。

## 已接受与已拒绝

**接受（仅限实验）：**

- `ranking` 原型。
- archive schema 与 30 条机器参考标签。
- source risk 建议。
- 合成 benchmark、ablation、holdout、feedback isolation、sensitivity。

**拒绝且不再重试：**

- age 与 dedup：完成一次实现修正后仍拒绝。
- backlog test packet：只修正一次，无实现。
- exhaustive oracle：一次修正后返回的是替代 selector，而非要求的穷举测量。
- source concentration diagnostic：一次修正后返回静态 JSON，而非要求的测量。

本地小修包括 phash fixture 单 bit、benchmark 变量名、holdout 括号和矛盾用例、拒绝重复 ID 的非法成功用例（保留 35 个合格用例）、修正 sensitivity 中错误的常量元数据预期；1536 个输出均有本地 ID/基数保护。

## 可复现命令

```bash
python -m pytest tests/algorithm_lab -q
python -m experiments.algorithm_lab.benchmark_ranking
python -m experiments.algorithm_lab.ablation_ranking
python -m experiments.algorithm_lab.evidence_sensitivity
```

均为离线、固定随机种子；各模块使用完整模块路径作为 CLI 前缀。

## Benchmark：200 个合成 trial

共同过滤：eligible、excluded ids、operator-negative 人类偏好。原型在合成数据上保持单主体一致、无重复/未知/排除/不合格/负反馈选中、置换稳定。

- 原型：coherent 1.0，role coverage 0.67067，mean match 0.82117。
- 独立 top-match naive（**示意，不是生产基线**）：coherent 0.025，role coverage 0.69975，mean match 0.91262。
- 1000 候选、5 次中位耗时：原型 0.004829 秒；计时与机器相关，不是负载测试。

## 同输入 Ablation

200 个冻结输入复用于三个方法；只比较同一 cohort 内结果，不能与 benchmark 横向因果比较。

- 当前原型：coverage 0.65608，mean match 0.83234，ideal gap 0.001372。
- match-only：coverage 0.65200，mean match 0.83550，gap 0.0000222。
- no-diversity：coverage 0.65133，mean match 0.83235，gap 0.001366。

三者均无重复、未知、排除、不合格或 operator-negative 选中。1000 候选中位耗时分别为 0.004833、0.002608、0.001421 秒。结果只说明合成 harness 内的取舍，不证明审美、互动或业务收益。

## Evidence sensitivity：1536 计数

固定权重：match 0.86、source trust 0.08、age confidence 0.06。共 **1536 case**：每个 gap 256 个，6 个 gap；其中 256 个 raw match 平局，非平局 1280 个。

- 平局的“选低分率”为 `null`（非平局分母为 0），不得算作错误。
- 非平局中固定排序有 **291 次选择 raw match 更低者，总率 0.22734375**。
- raw-score 控制组低分选择为 0。
- gap 0.005 与 0.01 各 110/256；0.05 为 55/256；0.1 为 16/256；0.2 为 0。
- 缺失 key 与显式 `0.0` 语义可不同，但当前数值贡献相同。

## Archive 30 条样本

- 30 条 parser 全部 abstain；dated 14、unknown 16。
- known-date recall 为 0/14。
- precision 为 `null`，分母为 0；不能把 null 解释成 0 或高精度。
- 标签是机器提议并核对引文/年份，**不是用户或运营决定**。
- 范围仅公开元数据；照片、对象、出版、印刷、上传年份不可混同。

## 限制与下一步

无真实候选、用户、标签、流量、发布 API 或指标摄取验证；未改权重、部署、爬虫预算或发布队列。feedback 测试只验证 scorer 元数据隔离；旧 helper 的 `operator_negative_selected` 还混入不合格计数，虽然其他计数器确认本次均为 0。

**下一步需要用户评审后，才能开始新实现或生产部署。优先保持 source approval，整理清楚标注的 archive 数据，并在获得许可的本地私有数据上对照真实已批准 pack 判断。**