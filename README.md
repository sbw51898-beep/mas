# MAF Multi-Agent Experiment

这是一个从零实现的多智能体实验骨架，用于比较四种等调用预算机制：

- `independent`：三个 Agent 各自回答并独立自省，始终看不到同伴消息；
- `round_robin`：三人独立初始化后，按照 A、B、C 顺序公开讨论两轮；
- `random_order`：每人仍发言两次，但六个公开发言槽位按随机种子打乱；
- `dynamic`：根据分歧、未曝光信息、依赖触发、不确定性和等待时间
  五个因素选择剩余6次发言者。

每种机制每题均使用9次有效讨论调用，避免把调用次数差异误当成讨论机制效果。

离线提供程序只用于验证程序机制和可重复性，不能作为模型效果或认知治理有效性的科学证据。

## 安装

```powershell
python -m pip install -e ".[dev,maf]"
```

项目只安装 MAF Core、Orchestrations 和 OpenAI 三个必要组件，不安装包含全部云服务的 MAF 元包。

## 测试

```powershell
python -m pytest -v
```

## 运行离线实验

```powershell
mas-experiment run --provider offline --output artifacts/results.jsonl
mas-experiment summarize artifacts/results.jsonl
```

默认运行10道题和4种机制，生成40条 JSONL 记录。每条记录包含 Agent 实际可见的消息 ID、结构化回答、动态选择分数、最终答案和基础指标。

## 使用真实 OpenAI-compatible 模型

在当前 PowerShell 会话中设置：

```powershell
$env:OPENAI_API_KEY="<your-key>"
$env:OPENAI_BASE_URL="https://your-provider.example/v1"
$env:OPENAI_CHAT_COMPLETION_MODEL="your-model"
```

然后先构造 MAF 工作流，验证环境和接口：

```powershell
mas-experiment maf-smoke --mode concurrent
mas-experiment maf-smoke --mode group-chat
```

运行一道普通真实模型题：

```powershell
mas-experiment run --provider openai-compatible --mode independent --limit 1 --output artifacts/real-model.jsonl
```

API Key 只从环境变量读取，日志会递归清理名称包含 `api_key`、`authorization`、`token` 或 `secret` 的字段。

## DeepSeek正式单题试跑

正式试跑使用批准的隐藏信息供应商任务和 DeepSeek V4 Flash 非思考模式。三种机制共享同一批三智能体初始回答，然后分别执行6次后续调用；每种机制仍记录9个逻辑响应位置。

请只在本机 PowerShell 会话中设置密钥，不要将密钥粘贴到聊天、代码或GitHub：

```powershell
$env:OPENAI_API_KEY="<set locally; do not paste into chat>"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_CHAT_COMPLETION_MODEL="deepseek-v4-flash"
mas-experiment formal-pilot --output artifacts/deepseek-formal-pilot-shared-initial.jsonl
```

命令先执行一次不计入讨论预算的连通性请求，然后执行3次共享初始化请求和18次模式后续请求，共21次真实讨论请求。三种模式分别序列化共享初始回答，因此输出仍有27个逻辑响应位置。若模型返回非法结构，最多追加一次格式修复请求，并在日志和报告中单独计数。输出包括 JSONL 完整轨迹和同名 Markdown 审计报告。

无需API Key即可先验证完全相同的离线流程：

```powershell
mas-experiment formal-pilot --provider offline --skip-connectivity --output artifacts/formal-pilot-shared-initial-offline.jsonl
```

离线结果只验证工程机制，真实单题结果也不能用于认定某种机制更优。

## 三任务内容感知筛选实验

筛选实验使用三道独立设计的隐藏信息题，分别代表容易、中等和困难
任务。每道题运行两次共享初始状态，并比较 `independent`、
`round_robin`、`random_order` 和 `dynamic` 四种机制。所有机制都只有
6次后续调用，不启用自动终止，也不会自动修改未发言 Agent 的信念。
共享初始回答只作为各模式共同的私有起点，不会自动公开；只有后续发言
才进入公共讨论频道。

先执行零成本离线审计：

```powershell
mas-experiment screening-pilot `
  --provider offline `
  --skip-connectivity `
  --output artifacts/screening-offline.jsonl `
  --overwrite
```

运行真实 DeepSeek 筛选实验：

```powershell
mas-experiment screening-pilot `
  --provider deepseek `
  --output artifacts/deepseek-screening-20260727.jsonl
```

默认预算为三道题 × 两次重复，共6个共享初始状态、24条模式记录和
162次讨论API请求；连通性探测单独计数。命令会生成JSONL轨迹、Markdown
报告和包含两者SHA-256摘要的`.manifest.json`清单。两次重复只用于筛选
机制差异，不能作为确认性统计结论。

## 正式指标

- 正确率；
- 多数集中度 `majority_share`；
- 全体一致与错误共识；
- 答案翻转率；
- 两两分歧率；
- 概率 Jensen-Shannon 分歧；
- Brier 分数；
- 归一化答案熵；
- 各 Agent 发言占比；
- 私有信息披露率（`lexical-semantic-v2`：严格词法、原子事实、
  实体锚点、有限语义概念与极性冲突保护）；
- 跨智能体输入使用率；
- FM-2.5输入忽视候选率（必须人工复核）。

探索性输出使用 `T_proxy`、`H_proxy` 和 `F_proxy` 命名，不把它们直接表述为真实温度、熵或 Helmholtz 自由能。后续需要通过扩样和 MAST 人工标注验证它们是否具有额外预测能力。

## HiddenBench 公开案例复现

项目已经增加独立的 HiddenBench 忠实复现链：四名 Agent、固定
A-B-C-D 轮转、15轮共60条公开消息，并比较 Hidden pre、Hidden post
和 Full Profile。该链不会混入上面的动态发言机制。

先运行离线结构验收：

```powershell
mas-experiment hiddenbench-showcase `
  --provider scripted `
  --script tests\fixtures\hiddenbench_script.json `
  --skip-connectivity `
  --output artifacts\hiddenbench-offline-qa.jsonl
```

真实 DeepSeek 单案例及十题人工闸门步骤见
[HiddenBench MAF 复现手册](docs/hiddenbench-reproduction.md)。

老师审阅入口：

- [最终实验报告](reports/HiddenBench_MAF复现实验补充报告_2026-07-28.md)
- [ID 25 完整可读对话](artifacts/hiddenbench-showcase-20260728-v2.md)
- [ID 25 机器可读原始记录](artifacts/hiddenbench-showcase-20260728-v2.jsonl)
- [十题完整机器可读记录](artifacts/hiddenbench-screening-20260728-v2.jsonl)
- [十题指标汇总](artifacts/hiddenbench-screening-20260728-v2.md)

这些指定的 v2 附件虽然位于通常被忽略的 `artifacts/` 目录，但已作为
本次正式复现材料明确纳入版本控制。附件包含原始 Prompt、可见消息、
60 条讨论、三种条件投票、指标和 SHA-256 manifest；不包含 API Key。

## HiddenBench 预算匹配动态发言试验

固定轮转基线冻结后，可先在错误共识案例 ID 1、5、7 上运行内容感知
动态顺序：

```powershell
mas-experiment hiddenbench-dynamic-pilot `
  --provider deepseek `
  --skip-connectivity `
  --output artifacts/hiddenbench-dynamic-pilot-20260729.jsonl
```

两种条件均为每个 Agent 15 次、每题总计 60 次公开发言。动态选择器只
计算闭式分数，不调用 LLM，也不读取标准答案。输出额外包含逐次选择分数
trace、协议 gate、配对报告和 SHA-256 manifest。三题仅用于机制与协议
审计，不能据此作显著性或优越性结论。

## HiddenBench AI披露与稳定性正式实验

老师要求的重复实验锁定 ID 1、5、7、25，并分别比较固定轮转和动态
发言。每个“题目×机制”重复10次，共80次运行；每次仍为60次公开发言、
每名 Agent 15次。两种机制在同一题同一次重复中使用相同种子、相同私有
信息分配、相同模型参数和相同发言预算。选择器不调用 LLM；Token 用量只
单独报告，并不宣称已经做到 Token 等额。

先运行一组零成本流程验收：

```powershell
mas-experiment hiddenbench-stability `
  --offline `
  --smoke `
  --output artifacts/hiddenbench-stability-offline-smoke.jsonl
```

真实 DeepSeek 正式运行：

```powershell
mas-experiment hiddenbench-stability `
  --output artifacts/hiddenbench-stability-20260729.jsonl `
  --experiment-workers 8 `
  --judge-workers 16
```

中断后使用相同命令即可续跑；默认启用 `--resume`，只跳过已经完整写入的
固定/动态配对和已经完成的 AI 审计。`--skip-ai-judge` 只生成对话记录，
不会生成可称为正式结果的 gate 和报告。

AI审计对每条私有事实分别判断是否由其所有者公开，并必须返回消息ID和
原文片段。最终披露百分比由程序按“披露事实数÷4”计算，不直接采用模型
自报的百分比。原有 `lexical-semantic-v2` 结果继续保留，二者不一致的
事实进入人工复核CSV。输出还包括80次运行、公开对话/选择器trace、
AI审计、稳定性summary、Markdown报告、gate和SHA-256 manifest。

正式结果和老师审阅材料：

- [四题十次重复分析](reports/HiddenBench_四题十次重复分析_2026-07-30.md)
- [官方 GPT-4.1 四题逐题对照](reports/HiddenBench_官方GPT4.1四题对照_2026-07-30.md)
- [2026-07-30 修订版 Word 报告](reports/给彭老师的HiddenBench_MAF复现实验最终报告_2026-07-30_修订版.docx)
- `artifacts/hiddenbench-stability-20260729.*`：80 个 run、4,800 条
  发言、AI 披露审计、分歧清单、汇总、闸门和 SHA-256 manifest。
