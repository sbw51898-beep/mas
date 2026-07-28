# HiddenBench 在 Microsoft Agent Framework 上的复现手册

## 1. 这次复现回答什么问题

本实验不再只使用自行设计的题目，而是迁移公开的 HiddenBench：

- 论文：Yuxuan Li, Aoi Naito, Hirokazu Shirado, [Systematic Failures in Collective Reasoning under Distributed Information in Multi-Agent LLMs](https://arxiv.org/abs/2505.11556)
- 官方数据：[YuxuanLi1225/HiddenBench](https://huggingface.co/datasets/YuxuanLi1225/HiddenBench)
- 失败诊断对照：Cemri et al., [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657)
- MAST 代码与标签说明：[multi-agent-systems-failure-taxonomy/MAST](https://github.com/multi-agent-systems-failure-taxonomy/MAST)

目标是检查：用 Microsoft Agent Framework 驱动的四个 DeepSeek Agent，
在各自只掌握部分信息时，能否通过公开讨论整合信息并选出正确答案。

这是“框架复现 + 模型迁移”。原论文使用 65 题、15 个前沿模型和每题
多次 session；本阶段先做 ID 25 单案例，再做锁定十题各一个固定种子。
因此当前结果不能被称为对论文 30.1% 和 80.7% 总体数值的统计复现。

## 2. 官方数据快照

项目保存：

- `data/hiddenbench/benchmark.json`
- `data/hiddenbench/provenance.json`
- `configs/hiddenbench-screening.json`

官方快照应包含 65 条记录，SHA-256 固定为：

```text
2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3
```

在 PowerShell 中验证：

```powershell
Get-FileHash data\hiddenbench\benchmark.json -Algorithm SHA256
python -m pytest tests\test_hiddenbench_data.py -q
```

锁定十题 ID 为：

```text
1, 5, 7, 9, 13, 14, 16, 25, 47, 62
```

这些 ID 在看到 DeepSeek 结果之前已经写入配置，不能按试跑结果替换。

## 3. 三个实验条件

每个任务都执行三种条件。

### Hidden Profile / Pre-discussion

四名 Agent 分别看到：

1. 场景描述；
2. 全部共享信息；
3. 只分配给自己的一条私有信息。

四名 Agent 互相看不到投票，分别输出 `vote` 和 `rationale`。

### Hidden Profile / Post-discussion

沿用同一份私有信息分配，固定按
`agent-a -> agent-b -> agent-c -> agent-d` 发言。每名 Agent 每轮
发言一次，共 15 轮、60 条公开消息，不因共识提前停止。讨论结束后
四名 Agent 再分别投票。

这是顺序异步语义：后发言者能看到同轮此前消息，并且每次调用都读取
截至当时的完整公开历史；不是四名 Agent 同时生成后再统一广播。四名
Agent 来自 HiddenBench 每题四组私有信息的一对一结构，不是调参结果。
本阶段固定该数量，不做合并或拆分私有信息的 Agent 数量消融。

### Full Profile

四名 Agent 分别看到场景、全部共享信息和全部私有信息，各自独立投票，
不进行讨论。该条件用于判断模型在信息完整时是否能够解决任务。

Hidden system prompt 不会告诉 Agent“别人可能掌握不同信息”，也不会
提示其主动寻找信息不对称。Full Profile 才包含全部私有信息。

## 4. DeepSeek 配置

程序只从当前 PowerShell 进程读取以下环境变量：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_CHAT_COMPLETION_MODEL
```

本实验要求：

```text
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_CHAT_COMPLETION_MODEL=deepseek-v4-flash
```

API Key 不写入代码、配置、报告或 Git。不要把 Key 粘贴到聊天中。

运行时固定：

- `temperature=0`
- `thinking=disabled`
- 投票请求使用 JSON response format
- 讨论发言保留自然语言原始文本
- 非法投票最多追加一次格式修复请求

## 5. 先做零成本离线验收

```powershell
mas-experiment hiddenbench-showcase `
  --provider scripted `
  --script tests\fixtures\hiddenbench_script.json `
  --skip-connectivity `
  --output artifacts\hiddenbench-offline-qa.jsonl `
  --overwrite
```

预期产生：

- `hiddenbench-offline-qa.jsonl`
- `hiddenbench-offline-qa.md`
- `hiddenbench-offline-qa.manifest.json`
- `hiddenbench-offline-qa.gate.json`

离线结果只验证程序流程、信息隔离和材料导出，不是模型效果。

## 6. ID 25 真实单案例

```powershell
mas-experiment hiddenbench-showcase `
  --provider deepseek `
  --output artifacts\hiddenbench-showcase-20260728.jsonl
```

默认先做一次不计入正式结果的连接探针。无格式修复时，正式单题有：

```text
4 次讨论前投票
+ 60 次公开发言
+ 4 次讨论后投票
+ 4 次 Full Profile 投票
= 72 次正式 API 调用
```

每次格式修复会增加一次 API 调用，并在报告中单独计数。

### 闸门 A：人工确认清单

在运行其余九题前，必须人工确认：

1. 四条私有信息各分配给一名 Agent，没有重复；
2. 每名 Agent 的 Hidden prompt 只包含自己的私有信息；
3. 讨论正好是 15 轮、每轮 A-B-C-D，共 60 条消息；
4. 四个 post vote prompt 包含完整公开历史；
5. 四个 Full Profile prompt 包含全部信息，所有投票均可解析；
6. JSONL、Markdown、manifest 和 gate 均不包含 Key 或 Authorization。

命令会生成结构检查 gate，但结构通过不代替人工审阅。只有用户明确确认
ID 25 材料满足老师要求后，才允许执行十题筛选。

## 7. 十题筛选

人工批准 ID 25 后运行：

```powershell
mas-experiment hiddenbench-screening `
  --provider deepseek `
  --approved-showcase-manifest artifacts\hiddenbench-showcase-20260728.manifest.json `
  --skip-connectivity `
  --output artifacts\hiddenbench-screening-20260728.jsonl
```

命令会重新验证 showcase manifest、gate、JSONL hash、任务 ID、私有信息
隔离、60 条消息和完整历史。任一检查失败都会在调用 DeepSeek 之前停止。

十题无修复时约 720 次正式 API 调用。该结果只能称为“十题单种子筛选”，
不能与论文 65 题 × 每题十次直接做显著性比较。

## 8. 输出字段

JSONL 的每条运行记录包含：

- 官方任务原文、候选答案和标准答案；
- 固定种子与 Agent A-D 私有信息分配；
- 每次模型调用的 system prompt、user prompt 和原始输出；
- pre、60 条 discussion、post 和 full-profile 记录；
- `Y_pre_average`、`Y_post_average`、`Y_full_average`；
- integration gain、full profile gap、多数正确和一致性；
- 私有信息披露率、跨 Agent 使用率；
- FM-2.4、FM-2.5、FM-2.6 自动候选及原始证据；
- 模型、温度、thinking、request ID、API/repair/token 计数；
- 代码提交、配置指纹和 run ID。

Markdown 是面向老师的可读档案；manifest 保存 JSONL 和 Markdown 的
字节数及 SHA-256；gate 保存 ID 25 的结构检查结果和 manifest hash。

## 9. 指标解释与限制

- `Y_pre_average`：讨论前四票中正确票比例；
- `Y_post_average`：讨论后四票中正确票比例；
- `Y_full_average`：Full Profile 四票中正确票比例；
- `integration_gain = Y_post_average - Y_pre_average`；
- `full_profile_gap = Y_post_average - Y_full_average`；
- 私有信息披露率：四条私有事实中，有多少被其所有者公开；
- 跨 Agent 使用率：被公开后，有多少事实被其他 Agent 在后续文本使用。

过程指标使用 `lexical-semantic-v2`。它先保留原有的严格词法闸门
（至少六个实义词且覆盖事实词汇的 55%），再补充：

- 轻量词形归一，例如 `exposed/exposure`、`expires/expiring`；
- 把长列表拆成原子事实，允许 Agent 只披露其中一条有效私有信息；
- 对 Station、Hospital、Restaurant、Lab、Option 和 Data Center
  使用实体锚点；
- 识别断电、污染、道路阻断、人员流失等有限的透明语义概念；
- 对“安全/危险”“有污染/无污染”“断电/有电”等反向陈述设置极性
  冲突保护；
- 对 `(a) N` 一类结构化准则，要求实体、准则编号和通过/失败方向一致。

该规则修复了压缩和释义表达造成的主要漏检，但仍不是通用自然语言
蕴含模型。因此 FM-2.4、FM-2.5、FM-2.6 输出继续标记为“自动候选，
必须人工复核”，不能直接作为论文标签。

讨论发言不是结构化投票，所以基线不从自然语言强行推断
`consensus_round`。

## 10. 本轮明确不做

- 不把原有三道自拟题并入 HiddenBench 统计；
- 不根据结果更换锁定十题；
- 不宣称十题单种子复现论文总体正确率；
- 不把关键词命中直接写成已经确认的 MAST 失败；
- 不在忠实基线中加入动态发言选择器；
- 不覆盖既有运行，除非明确传入 `--overwrite`。

内容感知动态发言只在固定轮转基线完成并冻结以后另做扩展设计。
