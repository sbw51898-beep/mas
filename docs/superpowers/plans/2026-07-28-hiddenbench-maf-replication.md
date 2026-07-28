# HiddenBench MAF Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不使用贺同学代码的前提下，用 Microsoft Agent Framework 和 DeepSeek 忠实复现 HiddenBench 的一个完整案例及十题筛选实验，完整导出信息分配、实际 prompt、60 条讨论消息、三种条件投票、指标、MAST 候选证据和审计材料。

**Architecture:** 保留现有 `Question -> MAFModelProvider -> AgentResponse` 实验链不动；新增独立的 HiddenBench 数据、prompt、原始文本 provider、协议执行、指标和报告层。协议执行器直接驱动四个 MAF Agent，按固定 A-B-C-D 顺序完成讨论前投票、15 轮共 60 次公开发言、讨论后投票和 Full Profile 独立投票。所有外部模型响应先写入强类型运行记录，再由纯函数计算指标和生成材料。

**Tech Stack:** Python 3.11、Pydantic 2、Typer、pytest/pytest-asyncio、Microsoft Agent Framework、DeepSeek OpenAI-compatible API、JSON/JSONL、Markdown、SHA-256。

## Global Constraints

- 忠实基线只运行固定轮转，不混入现有动态发言选择器。
- 四名 Agent 编号固定为 `agent-a`、`agent-b`、`agent-c`、`agent-d`。
- “15 轮”严格表示每轮四名 Agent 各发言一次，共 60 条公开消息，不因共识提前停止。
- 同一任务的 Hidden pre、Hidden post 与 Full Profile 复用同一任务、种子和答案顺序；Hidden pre/post 复用同一私有信息分配。
- Agent 只知道场景、共享信息和分配给自己的私有信息；不得提示“别人掌握不同信息”。
- 投票只接受官方 `possible_answers` 中的完整字符串，例如 `{"vote": "Station Delta", "rationale": "All constraints favor Delta."}`。
- 无效投票最多追加一次格式修复请求；讨论发言不做内容修复。
- 过程指标只生成“自动候选”，不能自动宣布出现 MAST FM-2.4/2.5/2.6。
- ID 25 通过人工闸门 A 前，不调用 DeepSeek 跑其余九题。
- 不提交 API Key、Authorization header 或含密钥的环境文件。
- 每个生产代码任务先运行新增测试并看到预期失败，再写最小实现，再运行目标测试。
- 每个任务只提交该任务列出的文件；始终排除当前未跟踪的 `reports/`。

---

## Task 1: 固化官方数据快照、来源与筛选配置

**Files:**

- Create: `data/hiddenbench/benchmark.json`
- Create: `data/hiddenbench/provenance.json`
- Create: `configs/hiddenbench-screening.json`
- Create: `tests/test_hiddenbench_data.py`
- Create: `src/mas_experiment/hiddenbench_data.py`

- [ ] **Step 1: 复制官方数据并写入不可变来源记录**

将已经下载并核验的
`C:\Users\liuli\Documents\mas\research_tmp_hiddenbench\benchmark.json`
复制为 `data/hiddenbench/benchmark.json`。`provenance.json` 写入以下固定字段：

```json
{
  "dataset": "YuxuanLi1225/HiddenBench",
  "source_url": "https://huggingface.co/datasets/YuxuanLi1225/HiddenBench",
  "source_file": "benchmark.json",
  "license": "MIT",
  "record_count": 65,
  "sha256": "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3",
  "paper_url": "https://arxiv.org/abs/2505.11556",
  "paper_version": "arXiv:2505.11556v4"
}
```

`configs/hiddenbench-screening.json` 固定为：

```json
{
  "configuration_version": "hiddenbench-maf-v1",
  "agent_ids": ["agent-a", "agent-b", "agent-c", "agent-d"],
  "discussion_rounds": 15,
  "showcase_task_id": 25,
  "screening_task_ids": [1, 5, 7, 9, 13, 14, 16, 25, 47, 62],
  "base_seed": 20260728,
  "dataset_sha256": "2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3"
}
```

- [ ] **Step 2: 写数据加载失败测试**

测试必须覆盖：

```python
def test_official_snapshot_has_expected_hash_and_65_tasks() -> None:
    tasks = load_hiddenbench_tasks(DATASET, expected_sha256=EXPECTED_SHA)
    assert len(tasks) == 65


def test_showcase_task_matches_official_record() -> None:
    task = load_hiddenbench_task(DATASET, task_id=25, expected_sha256=EXPECTED_SHA)
    assert task.name == "select_emergency_shelter"
    assert len(task.shared_information) == 4
    assert len(task.hidden_information) == 4
    assert len(task.possible_answers) == 4
    assert task.correct_answer == "Station Delta"


def test_locked_screening_ids_all_exist() -> None:
    tasks = load_hiddenbench_tasks(DATASET, expected_sha256=EXPECTED_SHA)
    assert set(LOCKED_IDS) <= {task.id for task in tasks}
```

另加两项负例：篡改字节时报 hash 错误；重复 ID 时报结构错误。

- [ ] **Step 3: 运行测试并确认按预期失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_data.py -q
```

Expected: collection/import 失败，提示 `mas_experiment.hiddenbench_data` 不存在。

- [ ] **Step 4: 实现强类型数据模型与 hash 校验**

`hiddenbench_data.py` 定义：

```python
class HiddenBenchTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    description: str
    shared_information: tuple[str, ...]
    hidden_information: tuple[str, ...]
    possible_answers: tuple[str, ...]
    correct_answer: str
    rationale: str

    @model_validator(mode="after")
    def validate_task(self) -> "HiddenBenchTask":
        if self.correct_answer not in self.possible_answers:
            raise ValueError("correct_answer must belong to possible_answers")
        if len(self.hidden_information) != 4:
            raise ValueError("replication requires exactly four hidden facts")
        return self
```

实现以下公开函数：

```python
def sha256_file(path: Path) -> str
def load_hiddenbench_tasks(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[HiddenBenchTask, ...]
def load_hiddenbench_task(
    path: Path,
    *,
    task_id: int,
    expected_sha256: str,
) -> HiddenBenchTask
```

加载函数先校验 hash，再校验 JSON 是列表、ID 唯一且共 65 条。

- [ ] **Step 5: 运行目标测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_data.py -q
git diff --check
git add data/hiddenbench/benchmark.json data/hiddenbench/provenance.json configs/hiddenbench-screening.json src/mas_experiment/hiddenbench_data.py tests/test_hiddenbench_data.py
git commit -m "feat: vendor verified HiddenBench snapshot"
```

Expected: 目标测试全部通过；提交中不包含 `reports/`。

---

## Task 2: 实现确定性私有信息分配与运行领域模型

**Files:**

- Create: `src/mas_experiment/hiddenbench_domain.py`
- Create: `tests/test_hiddenbench_domain.py`

- [ ] **Step 1: 写确定性分配和隔离测试**

固定测试：

```python
def test_assignment_is_deterministic_and_one_to_one() -> None:
    first = assign_hidden_information(SHOWCASE, seed=20260728)
    second = assign_hidden_information(SHOWCASE, seed=20260728)
    assert first == second
    assigned = tuple(first.private_information.values())
    assert len(set(assigned)) == 4
    assert set(assigned) == set(SHOWCASE.hidden_information)


def test_hidden_visible_information_never_leaks_peer_facts() -> None:
    assignment = assign_hidden_information(SHOWCASE, seed=20260728)
    visible = assignment.visible_information_for("agent-a")
    assert set(SHOWCASE.shared_information) <= set(visible)
    assert assignment.private_information["agent-a"] in visible
    assert not (
        set(assignment.private_information.values())
        - {assignment.private_information["agent-a"]}
    ) & set(visible)
```

再测试非法 Agent ID、四条以外私有信息和重复分配均被拒绝。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_domain.py -q
```

Expected: import 失败，提示领域模型尚不存在。

- [ ] **Step 3: 实现模型**

至少定义：

```python
AGENT_IDS = ("agent-a", "agent-b", "agent-c", "agent-d")


class HiddenBenchAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: int
    seed: int
    shared_information: tuple[str, ...]
    private_information: dict[str, str]

    def visible_information_for(self, agent_id: str) -> tuple[str, ...]:
        information = [
            *self.shared_information,
            self.private_information[agent_id],
        ]
        stable_shuffle(
            information,
            seed=self.seed,
            namespace=f"{self.task_id}:{agent_id}:hidden",
        )
        return tuple(information)


class PromptCompletion(BaseModel):
    text: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HiddenBenchVote(BaseModel):
    agent_id: str
    condition: Literal["hidden_pre", "hidden_post", "full_profile"]
    vote: str
    rationale: str
    raw_text: str
    system_prompt: str
    user_prompt: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HiddenBenchMessage(BaseModel):
    message_id: str
    round_index: int
    turn_index: int
    agent_id: str
    content: str
    visible_message_ids: tuple[str, ...]
    system_prompt: str
    user_prompt: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
```

另外定义 `HiddenBenchRawRun`、`HiddenBenchMetrics`、`MastCandidate` 和 `HiddenBenchRun`。`HiddenBenchRawRun` 保存 task、assignment、三组投票、60 条消息、配置指纹和代码提交号；Task 6 的纯函数把它转换为带指标和候选证据的完整 `HiddenBenchRun`。正式导出只接受后者。

`assign_hidden_information()` 使用 `random.Random(seed + task.id).shuffle()` 排列私有信息，保证同一输入稳定且不依赖全局随机状态。
`stable_shuffle()` 先对 `f"{seed}|{namespace}"` 做 SHA-256，再把摘要整数
作为 `random.Random` 的种子；不得使用 Python 进程间不稳定的 `hash()`。

- [ ] **Step 4: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_domain.py -q
git diff --check
git add src/mas_experiment/hiddenbench_domain.py tests/test_hiddenbench_domain.py
git commit -m "feat: model HiddenBench information assignments"
```

---

## Task 3: 锁定 Appendix A.4 prompt 模板

**Files:**

- Create: `src/mas_experiment/hiddenbench_prompts.py`
- Create: `tests/test_hiddenbench_prompts.py`

- [ ] **Step 1: 写 prompt 快照与防泄漏测试**

覆盖四类 prompt：

```python
def test_hidden_system_prompt_contains_only_one_private_fact() -> None:
    prompt = build_hidden_system_prompt(TASK, ASSIGNMENT, "agent-a")
    assert TASK.description in prompt
    assert all(item in prompt for item in TASK.shared_information)
    assert ASSIGNMENT.private_information["agent-a"] in prompt
    for agent_id in ("agent-b", "agent-c", "agent-d"):
        assert ASSIGNMENT.private_information[agent_id] not in prompt
    assert "order does not imply importance" in prompt
    assert "one or two sentences" in prompt


def test_discussion_prompts_match_turn_position() -> None:
    assert build_discussion_user_prompt(()) == "You are the first to speak."
    later = build_discussion_user_prompt((MESSAGE,))
    assert "It's your turn to speak." in later
    assert MESSAGE.content in later


def test_post_vote_prompt_contains_all_60_public_messages() -> None:
    prompt = build_vote_user_prompt(TASK, MESSAGES, phase="hidden_post")
    assert all(message.content in prompt for message in MESSAGES)
```

再断言 prompt 不含 `hidden information`、`different information`、`information asymmetry` 等泄题提示；Full Profile system prompt 必须含四条私有信息。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_prompts.py -q
```

- [ ] **Step 3: 实现纯 prompt 构造函数**

公开接口固定为：

```python
def build_hidden_system_prompt(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    agent_id: str,
) -> str

def build_full_profile_system_prompt(
    task: HiddenBenchTask,
    *,
    agent_id: str,
    seed: int,
) -> str

def build_discussion_user_prompt(
    visible_messages: tuple[HiddenBenchMessage, ...],
) -> str

def build_vote_user_prompt(
    task: HiddenBenchTask,
    visible_messages: tuple[HiddenBenchMessage, ...],
    *,
    phase: Literal["hidden_pre", "hidden_post", "full_profile"],
) -> str

def build_vote_repair_prompt(
    task: HiddenBenchTask,
    invalid_text: str,
) -> str
```

Hidden Profile 的五条可见信息和 Full Profile 的八条完整信息均使用
`seed + task ID + agent ID + condition` 派生的局部随机源做确定性打乱；
顺序写入实际 prompt 并留存在运行记录中。投票 prompt 明确只输出 JSON，
并逐行列出官方候选答案。模板正文在模块常量中保存，测试对关键句做精确断言。

- [ ] **Step 4: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_prompts.py -q
git diff --check
git add src/mas_experiment/hiddenbench_prompts.py tests/test_hiddenbench_prompts.py
git commit -m "feat: lock HiddenBench prompt templates"
```

---

## Task 4: 增加不改写输出的 MAF 原始文本适配器

**Files:**

- Modify: `src/mas_experiment/maf_adapter.py`
- Modify: `src/mas_experiment/providers.py`
- Modify: `tests/test_maf_adapter.py`
- Create: `tests/test_hiddenbench_provider.py`

- [ ] **Step 1: 写原始文本 provider 测试**

测试一个 fake MAF Agent，断言：

```python
@pytest.mark.asyncio
async def test_maf_prompt_provider_uses_real_agent_instructions() -> None:
    provider = MAFPromptProvider(settings, agent_factory=fake_agent_factory)
    completion = await provider.complete(
        agent_id="agent-a",
        system_prompt="system exact",
        user_prompt="user exact",
        seed=20260728,
        json_response=False,
    )
    assert fake_agent_factory.instructions == "system exact"
    assert fake_agent.received_prompt == "user exact"
    assert completion.text == "raw model text"
    assert completion.provider_metadata["api_requests"] == 1
    assert completion.provider_metadata["thinking"] == "disabled"
    assert completion.provider_metadata["temperature"] == 0
```

另测 `json_response=True` 才设置 `response_format=json_object`；讨论发言必须不强制 JSON。

- [ ] **Step 2: 写离线脚本 provider 测试**

`ScriptedPromptProvider` 按调用顺序返回固定文本，并保存每次 `agent_id/system_prompt/user_prompt/json_response`。脚本耗尽时报清楚错误，不能循环复用旧响应。

- [ ] **Step 3: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_maf_adapter.py tests/test_hiddenbench_provider.py -q
```

- [ ] **Step 4: 实现 `MAFPromptProvider`**

在 `maf_adapter.py` 添加。初始化时创建一个
`OpenAIChatCompletionClient`；每个不同的 `(agent_id, system_prompt_hash)`
创建并缓存一个 MAF `Agent`，把 `system_prompt` 作为 Agent 的真实
`instructions`，把 `user_prompt` 单独传给 `agent.run()`：

```python
class MAFPromptProvider:
    def __init__(
        self,
        settings: OpenAICompatibleSettings,
        *,
        agent_factory: Callable[[Any, str, str], Any] = create_prompt_agent,
    ) -> None:
        self._client = create_chat_client(settings)
        self._agent_factory = agent_factory
        self._agents: dict[tuple[str, str], Any] = {}

    async def complete(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        json_response: bool,
    ) -> PromptCompletion:
        del seed
        options = {
            "temperature": 0,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if json_response:
            options["response_format"] = {"type": "json_object"}
        system_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        key = (agent_id, system_hash)
        if key not in self._agents:
            self._agents[key] = self._agent_factory(
                self._client,
                agent_id,
                system_prompt,
            )
        result = await self._agents[key].run(user_prompt, options=options)
        return PromptCompletion(
            text=_extract_text(result),
            provider_metadata=build_provider_metadata(result),
        )
```

把现有 metadata 抽取逻辑提成私有 helper，供 `MAFModelProvider` 和 `MAFPromptProvider` 共用；现有 provider 的行为和测试必须保持不变。

- [ ] **Step 5: 实现 `ScriptedPromptProvider`**

在 `providers.py` 添加测试与离线演练使用的实现。返回的 metadata 固定标记：

```python
{
    "provider": "scripted-offline",
    "model": "scripted-offline",
    "api_requests": 0,
    "repair_requests": 0,
    "usage": {}
}
```

- [ ] **Step 6: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_maf_adapter.py tests/test_hiddenbench_provider.py -q
git diff --check
git add src/mas_experiment/maf_adapter.py src/mas_experiment/providers.py tests/test_maf_adapter.py tests/test_hiddenbench_provider.py
git commit -m "feat: add prompt-native MAF provider"
```

---

## Task 5: 实现忠实的三条件协议执行器

**Files:**

- Create: `src/mas_experiment/hiddenbench_protocol.py`
- Create: `tests/test_hiddenbench_protocol.py`

- [ ] **Step 1: 写投票解析和一次修复测试**

测试合法 JSON、代码围栏内 JSON、候选答案外的 vote、缺少 rationale、第一次失败第二次成功以及两次失败。成功修复必须记录两次请求的 request ID、合并 usage，并将 `repair_requests` 设为 1。

- [ ] **Step 2: 写完整协议顺序测试**

用脚本 provider 提供 72 个合法响应：

- Hidden pre：4 次投票；
- Discussion：15 × 4 = 60 次发言；
- Hidden post：4 次投票；
- Full Profile：4 次投票。

断言：

```python
assert len(run.hidden_pre_votes) == 4
assert len(run.discussion_messages) == 60
assert len(run.hidden_post_votes) == 4
assert len(run.full_profile_votes) == 4
assert [message.agent_id for message in run.discussion_messages[:8]] == [
    "agent-a", "agent-b", "agent-c", "agent-d",
    "agent-a", "agent-b", "agent-c", "agent-d",
]
assert run.discussion_messages[-1].round_index == 15
assert run.discussion_messages[-1].turn_index == 59
```

再断言第 N 条发言只看到前 N 条公开消息；四个 post prompt 都看到完整 60 条；Full Profile prompt 看到四条私有信息；整个协议不因相同投票提前结束。

- [ ] **Step 3: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_protocol.py -q
```

- [ ] **Step 4: 实现协议接口**

实现：

```python
class PromptProvider(Protocol):
    async def complete(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        json_response: bool,
    ) -> PromptCompletion: ...


async def run_hiddenbench_task(
    task: HiddenBenchTask,
    provider: PromptProvider,
    *,
    seed: int,
    discussion_rounds: int = 15,
) -> HiddenBenchRawRun
```

内部步骤固定：

1. 生成一次 assignment；
2. 顺序完成四个 Hidden pre vote；
3. 双循环 `for round_index in range(1, 16)` 和 `for agent_id in AGENT_IDS` 生成 60 条发言；
4. 顺序完成四个 Hidden post vote；
5. 顺序完成四个 Full Profile vote；
6. 汇总 provider metadata、代码提交号和配置指纹；
7. 返回 `HiddenBenchRawRun`；正式写出前必须由 Task 6 的
   `score_hiddenbench_run()` 转换为完整 `HiddenBenchRun`。

消息 ID 使用稳定输入的 SHA-256 前 16 位，不使用时间戳。运行失败时抛出包含 task ID、phase、agent ID、round/turn 的异常，不写半成品正式结果。

- [ ] **Step 5: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_protocol.py -q
git diff --check
git add src/mas_experiment/hiddenbench_protocol.py tests/test_hiddenbench_protocol.py
git commit -m "feat: run faithful HiddenBench discussion protocol"
```

---

## Task 6: 计算主指标和可人工复核的过程证据

**Files:**

- Create: `src/mas_experiment/hiddenbench_metrics.py`
- Create: `tests/test_hiddenbench_metrics.py`

- [ ] **Step 1: 写手算主指标测试**

使用固定投票：

```python
pre = ("Station Alpha", "Station Delta", "Station Alpha", "Station Bravo")
post = ("Station Delta", "Station Delta", "Station Delta", "Station Alpha")
full = ("Station Delta", "Station Delta", "Station Delta", "Station Delta")
```

期望：

```python
assert metrics.y_pre_average == 0.25
assert metrics.y_post_average == 0.75
assert metrics.y_full_average == 1.0
assert metrics.integration_gain == 0.5
assert metrics.full_profile_gap == -0.25
assert metrics.post_majority_correct is True
assert metrics.post_unanimous is False
assert metrics.consensus_round is None
```

平票时 majority 必须为 `False`，不能靠答案顺序破平。

- [ ] **Step 2: 写信息使用和 MAST 候选测试**

过程指标使用透明、保守的词法规则：

- 对每条私有事实做 Unicode casefold、去标点、英文停用词过滤；
- 至少命中该事实六个以上实义词且覆盖率不低于 0.55，才算词法提及；
- 所有者首次提及生成 disclosure；
- 非所有者在该事实已公开后提及生成 cross-agent use；
- 到讨论结束仍未由所有者提及，生成 FM-2.4 候选；
- 已公开后其他 Agent 的后续发言与 post rationale 均未提及，生成 FM-2.5 候选；
- rationale 中唯一明确出现的候选答案与 vote 不同，生成 FM-2.6 候选；
- 每个候选保存 fact、owner、message IDs、证据原文、规则版本和 `requires_manual_review=True`。

测试必须同时覆盖命中、阈值下不命中、信息公开前非所有者猜测不算 cross-use、否定句不自动定性。

- [ ] **Step 3: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_metrics.py -q
```

- [ ] **Step 4: 实现纯函数**

公开接口：

```python
def compute_hiddenbench_metrics(
    task: HiddenBenchTask,
    assignment: HiddenBenchAssignment,
    pre_votes: tuple[HiddenBenchVote, ...],
    messages: tuple[HiddenBenchMessage, ...],
    post_votes: tuple[HiddenBenchVote, ...],
    full_votes: tuple[HiddenBenchVote, ...],
) -> tuple[HiddenBenchMetrics, tuple[MastCandidate, ...]]

def score_hiddenbench_run(raw_run: HiddenBenchRawRun) -> HiddenBenchRun
```

所有规则常量保存为模块级常量，并在输出中写入 `evidence_rule_version="lexical-v1"`。`consensus_round` 在忠实基线始终为 `None`，因为公开发言不是结构化投票，不从自然语言强推共识。

- [ ] **Step 5: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_metrics.py -q
git diff --check
git add src/mas_experiment/hiddenbench_metrics.py tests/test_hiddenbench_metrics.py
git commit -m "feat: score HiddenBench outcomes and evidence"
```

---

## Task 7: 导出老师可检查的单案例档案

**Files:**

- Create: `src/mas_experiment/hiddenbench_reporting.py`
- Create: `tests/test_hiddenbench_reporting.py`

- [ ] **Step 1: 写 JSONL、Markdown 和脱敏测试**

报告测试必须断言 ID 25 档案包含：

- 论文与官方数据链接；
- 原始英文题目、共享信息和标准答案；
- Agent A-D 私有信息分配矩阵；
- 每次调用的 system prompt 和 user prompt；
- 4 个 pre vote、60 条逐轮消息、4 个 post vote、4 个 full vote；
- 三类主指标与 MAST 自动候选；
- “单题单种子不等同论文总体复现”的限制说明；
- 模型、温度、thinking、API 请求数、repair 数和 token 用量；
- 代码提交号、配置指纹、数据 hash。

脱敏测试向 metadata 注入 `api_key`、`authorization`、`bearer` 字段和形似密钥的字符串，导出函数必须拒绝写入并抛出 `SecretLeakError`。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_hiddenbench_reporting.py -q
```

- [ ] **Step 3: 实现导出接口**

```python
def write_hiddenbench_jsonl(
    runs: Sequence[HiddenBenchRun],
    destination: Path,
) -> Path

def build_showcase_report(run: HiddenBenchRun) -> str

def build_screening_report(runs: Sequence[HiddenBenchRun]) -> str

def write_hiddenbench_bundle(
    runs: Sequence[HiddenBenchRun],
    output: Path,
    *,
    report_kind: Literal["showcase", "screening"],
) -> tuple[Path, Path, Path]
```

`write_hiddenbench_bundle` 原子写入 `.jsonl` 和 `.md`，然后复用 `write_sha256_manifest` 写 `.manifest.json`。Markdown 的 60 条发言按 `Round 01` 到 `Round 15` 分组，逐条列出 speaker、可见 message IDs、实际 prompt 和输出，不截断内容。

- [ ] **Step 4: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_hiddenbench_reporting.py -q
git diff --check
git add src/mas_experiment/hiddenbench_reporting.py tests/test_hiddenbench_reporting.py
git commit -m "feat: export auditable HiddenBench dossiers"
```

---

## Task 8: 增加带闸门的 showcase 与 screening CLI

**Files:**

- Modify: `src/mas_experiment/cli.py`
- Modify: `tests/test_cli.py`
- Create: `tests/fixtures/hiddenbench_script.json`

- [ ] **Step 1: 写离线 showcase CLI 测试**

新增命令：

```text
hiddenbench-showcase
```

测试调用：

```powershell
mas-experiment hiddenbench-showcase --provider scripted --script tests/fixtures/hiddenbench_script.json --output <tmp>/showcase.jsonl
```

断言产生一条 ID 25 运行记录、60 条讨论消息、Markdown、manifest 和 gate 文件；gate 文件只能在所有结构检查通过后写入。

- [ ] **Step 2: 写 screening 闸门测试**

新增命令：

```text
hiddenbench-screening
```

没有 `--approved-showcase-manifest` 时必须失败；manifest 不存在、hash 不匹配、任务不是 25、消息不是 60 条、prompt 隔离检查失败时也必须失败。通过有效 gate 后，脚本模式运行锁定十题且不得接受任意替换 ID。

- [ ] **Step 3: 写覆盖保护和 provider 测试**

已有输出未传 `--overwrite` 时拒绝覆盖。`deepseek` provider 必须经
`DeepSeekSettings.from_env()` 创建 `MAFPromptProvider`；该 provider 按实际
system prompt 为四个逻辑身份创建和缓存 MAF Agent。`scripted` provider
不读取环境密钥。连接探针只在 DeepSeek 且未传
`--skip-connectivity` 时运行。

- [ ] **Step 4: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests/test_cli.py -q
```

- [ ] **Step 5: 实现 CLI**

命令参数固定：

```python
@app.command("hiddenbench-showcase")
def hiddenbench_showcase_command(
    output: Path = Path("artifacts/hiddenbench-showcase-20260728.jsonl"),
    provider: str = "deepseek",
    script: Path | None = None,
    seed: int = 20260728,
    skip_connectivity: bool = False,
    overwrite: bool = False,
) -> None


@app.command("hiddenbench-screening")
def hiddenbench_screening_command(
    approved_showcase_manifest: Path,
    output: Path = Path("artifacts/hiddenbench-screening-20260728.jsonl"),
    provider: str = "deepseek",
    script: Path | None = None,
    base_seed: int = 20260728,
    skip_connectivity: bool = False,
    overwrite: bool = False,
) -> None
```

showcase 只加载 ID 25；screening 只加载配置中的十个 ID。命令结束输出实际逻辑响应槽、API 请求、repair、token 和文件路径。预计无修复时单题主协议 72 次 API 调用；连接探针另计，不写入正式结果。

- [ ] **Step 6: 运行测试并提交**

Run:

```powershell
python -m pytest tests/test_cli.py -q
git diff --check
git add src/mas_experiment/cli.py tests/test_cli.py tests/fixtures/hiddenbench_script.json
git commit -m "feat: add gated HiddenBench pilot commands"
```

---

## Task 9: 补齐复现说明并做全量离线验收

**Files:**

- Create: `docs/hiddenbench-reproduction.md`
- Modify: `README.md`

- [ ] **Step 1: 写复现手册**

手册必须给出：

- HiddenBench 和 MAST 的一手来源链接；
- 数据 hash 核验命令；
- DeepSeek 三个环境变量名，但不写值；
- showcase 与 screening 的准确命令；
- 72 次/题无修复 API 预算，十题约 720 次正式调用；
- 闸门 A 的六项人工检查表；
- JSONL、Markdown、manifest 的字段与用途；
- 词法证据只是候选、单种子筛选不是论文 65×10 主实验的限制；
- 动态选择器明确排除在本轮基线之外。

- [ ] **Step 2: 更新 README 命令索引**

README 只增加复现入口和文档链接，不复制整份手册。

- [ ] **Step 3: 全量静态和离线测试**

Run:

```powershell
python -m pytest -q
python -m compileall -q src tests
git diff --check
python -m mas_experiment.cli hiddenbench-showcase --provider scripted --script tests/fixtures/hiddenbench_script.json --output artifacts/hiddenbench-offline-qa.jsonl --overwrite
```

Expected:

- 原有 84 项测试及所有新增测试通过；
- compileall 无错误；
- 离线档案包含 1 个任务、60 条讨论消息和 72 个逻辑响应槽；
- manifest 中三个文件 hash 可重新计算一致；
- `rg -ni "api[_-]?key|authorization|bearer " artifacts/hiddenbench-offline-qa*` 无命中。

- [ ] **Step 4: 提交文档**

Run:

```powershell
git add README.md docs/hiddenbench-reproduction.md
git commit -m "docs: add HiddenBench reproduction runbook"
```

不要提交 `artifacts/hiddenbench-offline-qa*`。

---

## Task 10: 执行 DeepSeek 单案例真实试跑并停在闸门 A

**Files generated, not committed:**

- `artifacts/hiddenbench-showcase-20260728.jsonl`
- `artifacts/hiddenbench-showcase-20260728.md`
- `artifacts/hiddenbench-showcase-20260728.manifest.json`
- `artifacts/hiddenbench-showcase-20260728.gate.json`

- [ ] **Step 1: 运行前检查工作区和环境**

Run:

```powershell
git status --short
python -c "from mas_experiment.providers import DeepSeekSettings; s=DeepSeekSettings.from_env(); print(s.base_url, s.model)"
python -m pytest -q
```

Expected: 只允许已知未跟踪 `reports/`；只打印 base URL 与模型名，不打印 key；测试全绿。

- [ ] **Step 2: 先做一次不计入实验的连接探针，再执行 ID 25**

Run:

```powershell
python -m mas_experiment.cli hiddenbench-showcase --provider deepseek --output artifacts/hiddenbench-showcase-20260728.jsonl
```

Expected: 命令报告一条正式 run、60 条讨论消息、72 个逻辑响应槽；API 请求数至少 72，任何 repair 另计；三个正式文件和 gate 文件均存在。

- [ ] **Step 3: 机器校验**

Run:

```powershell
python -m pytest tests/test_hiddenbench_data.py tests/test_hiddenbench_prompts.py tests/test_hiddenbench_protocol.py tests/test_hiddenbench_metrics.py tests/test_hiddenbench_reporting.py tests/test_cli.py -q
git diff --check
```

另用只读校验命令确认：

- 四条私有信息各分配一次；
- agent-a 到 agent-d 的 Hidden system prompt 各只含自己的私有事实；
- 60 条消息按 15 轮、每轮 A-B-C-D；
- 四个 post prompt 含完整历史；
- 四个 Full Profile prompt 含全部私有事实；
- 所有 12 个投票均属于官方候选项；
- JSONL 和 Markdown 不含敏感字段或密钥形态；
- manifest hash 可重算一致。

- [ ] **Step 4: 人工审阅老师材料并停止**

打开 `artifacts/hiddenbench-showcase-20260728.md`，逐项核对：

1. 题目是什么；
2. 哪四条信息是共享信息；
3. 哪四条信息被分别隐藏给谁；
4. 每个 Agent 实际看到的 prompt；
5. 讨论前怎么选；
6. 15 轮具体说了什么；
7. 讨论后怎么选；
8. Full Profile 怎么选；
9. 指标和 MAST 候选证据是否能回指原文；
10. 是否清楚声明这只是单题单种子迁移试跑。

将材料交给用户确认。未得到用户明确批准前，不执行 Task 11。

---

## Task 11: 经用户批准后执行锁定十题筛选并生成阶段报告

**Files generated, not committed:**

- `artifacts/hiddenbench-screening-20260728.jsonl`
- `artifacts/hiddenbench-screening-20260728.md`
- `artifacts/hiddenbench-screening-20260728.manifest.json`

**Files:**

- Create after successful run: `reports/HiddenBench_MAF复现实验补充报告_2026-07-28.md`

- [ ] **Step 1: 验证用户批准和闸门 manifest**

使用 Task 10 的 `.manifest.json` 作为 `--approved-showcase-manifest`。如果 manifest 或 gate 校验不通过，停止且不调用 DeepSeek。

- [ ] **Step 2: 执行锁定十题各一次**

Run:

```powershell
python -m mas_experiment.cli hiddenbench-screening --provider deepseek --approved-showcase-manifest artifacts/hiddenbench-showcase-20260728.manifest.json --output artifacts/hiddenbench-screening-20260728.jsonl --skip-connectivity
```

Expected: 正好 10 条 run；每条 60 条讨论消息和 72 个逻辑响应槽；无修复时共 720 次正式 API 调用。

- [ ] **Step 3: 汇总但不夸大比较**

报告分别列出：

- HiddenBench 论文 65 题、多模型、多 session 的公开参照；
- 当前 MAF + DeepSeek 十题单种子筛选；
- 每题 `Y_pre_average`、`Y_post_average`、`Y_full_average`；
- 十题均值、integration gain、full profile gap；
- 信息披露、跨 Agent 使用和 MAST 候选数量；
- API、repair 和 token 总量；
- “模型迁移、样本量和重复次数不同，不能声明复现论文 30.1%/80.7%”。

- [ ] **Step 4: 生成给彭老师的阶段补充报告**

报告结构固定：

1. 老师问题与本次回答；
2. 选用的公开论文/案例及其已发表结果；
3. 为什么选 HiddenBench，MAST 如何作为诊断框架；
4. Microsoft Agent Framework 复现架构；
5. 实验设置表；
6. ID 25 完整案例材料；
7. 十题筛选结果；
8. 原论文结果与当前结果可比/不可比边界；
9. 当前发现、问题和下一步建议；
10. 代码仓库、提交号、数据来源和审计文件。

- [ ] **Step 5: 最终验证**

Run:

```powershell
python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

检查报告中的每个数值都能回指 JSONL；每个引用都链接一手来源；报告不把自动候选写成已确认 MAST 标签；不提交原始运行产物或未审阅报告。

---

## Final Review Gate

实现完成后，在宣称完成前必须依次满足：

- [ ] 现有测试与新增测试全部通过；
- [ ] `python -m compileall -q src tests` 通过；
- [ ] `git diff --check` 通过；
- [ ] 官方数据 hash、65 条记录、十个锁定 ID 和 ID 25 关键字段通过测试；
- [ ] 单案例有 4+60+4+4 个逻辑响应槽；
- [ ] 所有 Hidden prompt 通过私有信息隔离检查；
- [ ] 所有 post prompt 包含完整公开历史；
- [ ] 所有 Full Profile prompt 包含全部信息；
- [ ] 输出没有密钥、Authorization 或 Bearer 内容；
- [ ] manifest 可重算；
- [ ] 单案例经过用户人工批准后才运行十题；
- [ ] 教师报告明确区分论文公开结果、当前迁移结果和不可比限制；
- [ ] 动态发言选择器没有混入忠实基线。
