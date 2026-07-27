# MAF Multi-Agent Experiment

这是一个从零实现的多智能体实验骨架，用于比较三种机制：

- `concurrent`：三个 Agent 基于同一初始状态独立回答；
- `round_robin`：按照 A、B、C 的顺序共享历史并讨论三轮；
- `dynamic`：根据分歧、等待时间和不确定性选择下一位发言者。

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

默认运行10道题和3种机制，生成30条 JSONL 记录。每条记录包含 Agent 实际可见的消息 ID、结构化回答、动态选择分数、最终答案和基础指标。

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

运行一道真实模型题：

```powershell
mas-experiment run --provider openai-compatible --mode concurrent --limit 1 --output artifacts/real-model.jsonl
```

API Key 只从环境变量读取，日志会递归清理名称包含 `api_key`、`authorization`、`token` 或 `secret` 的字段。

## 第一版指标

- 正确率；
- 共识率；
- 错误共识；
- 答案翻转率；
- 两两分歧率；
- 归一化答案熵；
- 各 Agent 发言占比。

第一版不把这些指标直接命名为温度、自由能或序参量。后续需要通过 MAST 等带标注数据验证复杂指标是否具有额外预测能力。
