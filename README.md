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
- 私有信息关键词覆盖率；
- 跨智能体输入使用率；
- FM-2.5输入忽视候选率（必须人工复核）。

探索性输出使用 `T_proxy`、`H_proxy` 和 `F_proxy` 命名，不把它们直接表述为真实温度、熵或 Helmholtz 自由能。后续需要通过扩样和 MAST 人工标注验证它们是否具有额外预测能力。
