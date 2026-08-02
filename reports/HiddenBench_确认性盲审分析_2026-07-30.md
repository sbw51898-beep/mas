# HiddenBench 披露判断确认性盲审（模型辅助预审）

## 审计范围

- 总体：320 项 Agent 级信息包判断。
- 全量复核：84 项 AI—透明规则分歧。
- 分层抽样：其余 236 项一致判断中，按 AI 已披露/未披露、任务和机制分层各抽 30 项，共 60 项。
- 盲审总数：144 项；抽样种子：20260730。

## 加权结果

- 独立复核与 AI 一致率：93.5%
- AI 精确率：88.3%
- AI 召回率：94.8%
- 修订后的总体披露率：36.4%

以上指标对84项分歧赋权1；对一致样本按其所在AI标签×任务×机制层的总体数/样本数加权，估计范围回到320项。

## 诚信说明

本轮逐项标签由独立盲化的 DeepSeek V4 Flash 复核生成，没有向复核提示展示原 AI 标签或透明规则标签。它属于模型辅助预审，不是真人人工金标准，因此不能在对外材料中写成“人工一致率”。已同时生成不含既有标签的人工签核表；真人完成或修改该表后，应使用相同加权公式重算最终人工指标。

## 复核入口

- 盲化人工签核表：`artifacts\hiddenbench-stability-20260729.blind-review.queue.csv`
- 模型辅助逐项判断：`artifacts\hiddenbench-stability-20260729.blind-review.judgments.jsonl`
- 加权摘要：`artifacts\hiddenbench-stability-20260729.blind-review.summary.json`
