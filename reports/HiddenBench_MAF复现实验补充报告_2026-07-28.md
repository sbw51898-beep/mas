# HiddenBench 在 Microsoft Agent Framework 上的阶段复现实验报告

## 一、这次工作针对老师提出的两个问题

老师上次主要提出了两点：

1. 需要找一项已经发表、已有案例和结果的多智能体研究，再使用
   Microsoft 的 Agent Framework 复现相同问题；
2. 需要把案例和实验设置说明清楚，包括题目是什么、哪些信息是共享的、
   哪些信息被分别隐藏、每个智能体实际看到了什么，以及讨论过程具体
   说了什么。

本次选择 HiddenBench 作为主要复现对象，并使用 MAST 作为失败诊断
对照。代码没有使用贺同学的实现，而是在现有项目中独立完成。

## 二、选用的公开研究

### 1. HiddenBench

论文：

Yuxuan Li, Aoi Naito, Hirokazu Shirado,
*Systematic Failures in Collective Reasoning under Distributed Information
in Multi-Agent LLMs*，ICML 2026，arXiv:2505.11556。

- 论文：https://arxiv.org/abs/2505.11556
- 官方数据：https://huggingface.co/datasets/YuxuanLi1225/HiddenBench
- 数据许可：MIT
- 官方数据规模：65 个任务

这项研究讨论的是“分布式信息”问题：每名参与者只知道一部分信息，
单独看都无法完整判断，必须在讨论中把各自的信息说出来并正确整合。

论文报告的总体参照结果是：

- Hidden Profile 讨论后平均正确率：30.1%；
- Full Profile 平均正确率：80.7%。

也就是说，模型在一次性看到全部信息时通常可以解题，但信息分散到多个
智能体后，即使允许讨论，也经常无法正确整合。

### 2. MAST

论文：

Bert Cemri et al.,
*Why Do Multi-Agent LLM Systems Fail?*，NeurIPS 2025，
arXiv:2503.13657。

- 论文：https://arxiv.org/abs/2503.13657
- 代码：https://github.com/multi-agent-systems-failure-taxonomy/MAST

本项目重点参考三类标签：

- FM-2.4：掌握重要信息但没有披露；
- FM-2.5：看到了其他智能体的信息但没有使用；
- FM-2.6：推理内容与最终选择不一致。

MAST 标签在本项目中只用于人工诊断。程序生成的关键词候选不能直接
视为已经确认的失败标签。

## 三、复现方法

### 1. 技术环境

- 多智能体框架：Microsoft Agent Framework；
- 模型：DeepSeek V4 Flash；
- API：DeepSeek OpenAI-compatible endpoint；
- temperature：0；
- thinking：disabled；
- Agent 数量：4；
- 固定身份：agent-a、agent-b、agent-c、agent-d；
- 发言方式：固定 A-B-C-D 轮转；
- 讨论轮数：15 轮；
- 公开发言数：每轮 4 条，共 60 条；
- 不因形成共识而提前结束；
- 投票格式：`vote` 与 `rationale` 两个 JSON 字段；
- 非法投票最多追加一次格式修复请求。

### 2. 三个实验条件

每道题都运行三种条件。

#### Hidden Profile / Pre-discussion

每名智能体看到：

- 场景描述；
- 全部共享信息；
- 只分配给自己的一条私有信息。

四名智能体先独立投票，互相看不到其他人的投票。

#### Hidden Profile / Post-discussion

沿用相同的信息分配，按 A-B-C-D 顺序进行 15 轮讨论。每次发言时，
智能体可以看到此前全部公开消息，但仍只能在 system prompt 中看到
自己的那条私有信息。60 条消息结束后，四名智能体再次独立投票。

#### Full Profile

四名智能体分别看到全部共享信息和全部四条私有信息，不讨论，直接
独立投票。这个条件用于判断模型在信息完整时能否解题。

### 3. Prompt 忠实性

Prompt 依据 HiddenBench 论文附录 A.4。系统提示包含：

```text
You have received the following information, notice the order of this
information is randomly shuffled, the order of facts does not indicate
importance or relationship, please reason carefully:
```

首次发言：

```text
You are the first to speak.
```

后续发言：

```text
Previous messages from other people:
[此前的全部公开消息]
It’s your turn to speak.
```

投票要求只返回：

```json
{
  "vote": "官方候选答案中的一个完整字符串",
  "rationale": "简洁理由"
}
```

没有加入“其他智能体可能掌握不同信息”“请主动寻找信息不对称”等额外
提示，避免改变原论文任务。

## 四、完整展示案例：HiddenBench ID 25

任务名：`select_emergency_shelter`

场景是化工厂事故后，四人应急小组需要在 Alpha、Bravo、Charlie 和
Delta 四个避难所中选择一个。官方正确答案是 Station Delta。

### 1. 私有信息分配

| Agent | 只分配给该 Agent 的信息 |
|---|---|
| agent-a | Station Charlie 的太阳能板损坏，备用电池耗尽，没有电力 |
| agent-b | Station Alpha 的通风系统暴露于室外空气，室内毒素超标 |
| agent-c | Station Delta 的水、备用灯和主要系统正常，没有污染 |
| agent-d | Station Bravo 附近空气传感器读数异常，可能受到化学污染 |

四名智能体共同看到避难所容量、距离、补给、道路等基础信息，但上表中的
四条信息各自只出现在一名智能体的 Hidden system prompt 中。

### 2. 讨论前

四名智能体全部选择 Station Alpha，因此：

```text
Y_pre_average = 0.000
```

### 3. 第一轮关键信息披露

第一轮四名智能体依次说：

- agent-a：说明 Charlie 没有电，但仍先建议 Alpha；
- agent-b：明确指出 Alpha 存在毒素，必须排除；
- agent-c：指出 Delta 的系统已确认安全，建议 Delta；
- agent-d：指出 Bravo 可能受到污染，但当时仍建议 Charlie。

第二轮开始，agent-a 综合 Alpha 污染、Charlie 无电和 Delta 道路开放
等信息，改为支持 Delta。其余智能体也逐步支持 Delta。之后的讨论出现
大量重复确认，说明关键信息在前两轮已经基本完成整合，后续 13 轮主要
是在重复已经形成的结论。

### 4. 讨论后与 Full Profile

讨论后四票全部选择 Station Delta：

```text
Y_post_average = 1.000
```

Full Profile 四票也全部选择 Station Delta：

```text
Y_full_average = 1.000
integration_gain = 1.000
full_profile_gap = 0.000
```

这个案例说明，在信息分散时，四名智能体最初都判断错误；公开讨论披露
关键信息后，系统从全错转为全对。

### 5. 自动披露指标修正

程序最初使用 `lexical-v1` 保守规则：一条发言必须至少命中私有事实的
6 个实义词，并覆盖该事实词汇的 55%，才记为信息披露。该规则能避免
把一般性讨论误记为披露，但会漏掉压缩和释义表达。例如，Agent 把完整
的 Alpha 通风检测报告概括为 “Station Alpha is unsafe due to elevated
toxin levels”，含义已经披露，词汇覆盖率却不足 55%。

本次在不修改任何原始模型回答、不增加 DeepSeek 调用的前提下，将过程
指标升级为 `lexical-semantic-v2`。新规则包括：

1. 保留原来的 6 词、55% 严格词法闸门；
2. 对 `exposed/exposure`、`expires/expiring` 等表达做轻量词形归一；
3. 将长列表拆成原子事实，允许 Agent 披露其中一条决策相关私有信息；
4. 使用 Station、Hospital、Restaurant、Lab、Option 和 Data Center
   等实体锚点；
5. 识别断电、污染、道路阻断、人员流失等有限、可检查的语义概念；
6. 设置极性冲突保护，避免把“有电”当成“断电”、把“有污染”当成
   “无污染”；
7. 对 `(a) N` 一类结构化准则，同时核对实体、准则编号和通过/失败方向。

修正后，ID 25 的四条私有信息全部被自动识别为已披露：

```text
private_fact_disclosure_rate = 1.000
cross_agent_use_rate = 0.750
FM-2.4 candidates = 0
```

`cross_agent_use_rate = 0.750` 表示四条私有事实中有三条在披露后被至少
一名其他 Agent 明确复用。原来的四个 FM-2.4 候选已经消失。自动候选
仍须人工复核，因为该规则是透明的任务级语义启发式，不是通用自然语言
蕴含模型。

## 五、锁定十题筛选结果

十题 ID 在运行前已经固定为：

```text
1, 5, 7, 9, 13, 14, 16, 25, 47, 62
```

每题只运行一个固定种子。

| ID | 任务 | Y_pre | Y_post | Y_full | 讨论增益 |
|---:|---|---:|---:|---:|---:|
| 1 | evacuation_west_city | 0.500 | 0.000 | 1.000 | -0.500 |
| 5 | baker_2010 | 0.000 | 0.000 | 1.000 | 0.000 |
| 7 | graetz_et_al_1998 | 0.250 | 0.000 | 0.750 | -0.250 |
| 9 | critical_hospital_transfer | 0.000 | 1.000 | 1.000 | 1.000 |
| 13 | Laboratory Theft Deduction | 0.250 | 1.000 | 0.750 | 0.750 |
| 14 | lunch_group_decision | 0.000 | 0.250 | 1.000 | 0.250 |
| 16 | Crisis Backup Decision | 0.250 | 1.000 | 1.000 | 0.750 |
| 25 | select_emergency_shelter | 0.000 | 1.000 | 1.000 | 1.000 |
| 47 | Find the Missing Prototype | 0.750 | 1.000 | 1.000 | 0.250 |
| 62 | company_acquisition_decision | 0.000 | 1.000 | 1.000 | 1.000 |
| **平均** |  | **0.200** | **0.625** | **0.950** | **0.425** |

主要现象：

1. Full Profile 平均正确率达到 0.950，说明这些题在信息完整时对当前
   模型基本可解；
2. Hidden Profile 讨论前平均正确率只有 0.200，说明私有信息分散造成
   明显困难；
3. 讨论后提高到 0.625，平均增益为 0.425，说明讨论总体上有帮助；
4. ID 9、13、16、25、47、62 在讨论后达到四票全对；
5. ID 1、5、7 在讨论后形成四票一致，但一致答案是错误的；
6. ID 14 讨论后只有一名智能体正确，另外三名选择同一错误答案。

因此，这十题并不支持“共识等于正确”。讨论既可能整合信息，也可能
让智能体围绕错误答案快速收敛。

### 自动信息流指标

使用同一批原始 JSONL 重新评分，没有重新调用模型，正确率和投票结果
均未改变。

| ID | 任务 | 私有信息披露率 | 跨 Agent 使用率 | FM-2.4 候选数 |
|---:|---|---:|---:|---:|
| 1 | evacuation_west_city | 0.750 | 0.750 | 1 |
| 5 | baker_2010 | 0.750 | 0.500 | 1 |
| 7 | graetz_et_al_1998 | 1.000 | 1.000 | 0 |
| 9 | critical_hospital_transfer | 0.750 | 0.500 | 1 |
| 13 | Laboratory Theft Deduction | 1.000 | 0.750 | 0 |
| 14 | lunch_group_decision | 0.750 | 0.000 | 1 |
| 16 | Crisis Backup Decision | 0.500 | 0.500 | 2 |
| 25 | select_emergency_shelter | 1.000 | 1.000 | 0 |
| 47 | Find the Missing Prototype | 1.000 | 0.750 | 0 |
| 62 | company_acquisition_decision | 1.000 | 0.750 | 0 |
| **平均/合计** |  | **0.850** | **0.650** | **6** |

原 `lexical-v1` 在十题上的平均披露率为 0.025、跨 Agent 使用率为
0.000。v2 修正为 0.850 和 0.650，说明旧结果主要反映词法漏检，不能
解释为 Agent 普遍没有披露信息。

仍保留的 6 个 FM-2.4 自动候选是：

- ID 1 / agent-c：未公开“步道因倒树关闭”；
- ID 5 / agent-a：未公开其候选人资料包中的决策相关私有点；
- ID 9 / agent-a：未公开“Hospital A 山路已清理并确认安全”；
- ID 14 / agent-b：未公开“Restaurant C 次餐厅仍对公众开放”；
- ID 16 / agent-a：未公开“Charlie 电缆已修复并通过额外安全审计”；
- ID 16 / agent-d：未公开“Bravo 临时负责人不熟悉应急流程”。

人工复核这些所有者的 15 次发言后，没有发现能够推翻上述 6 个候选的
明确表达，因此它们不是本轮已知的词法漏检；但最终是否构成 MAST
FM-2.4，仍需结合任务重要性和完整上下文人工定性。

## 六、运行与审计

- 单案例：72 次正式 API 调用，0 次格式修复；
- 十题筛选：720 个逻辑响应槽；
- 十题实际 API 请求：721 次；
- 格式修复：1 次；
- 修复发生在任务 62 的 hidden post / agent-a；
- 原始输出把答案写成 `Option C`，不符合官方完整候选字符串；
- 修复后得到 `Option C: Logistics software company`；
- v2 信息披露重评分：0 次新增模型/API 请求，原始回答和投票未改动；
- ID 25 自动披露率：由 0.000 修正为 1.000；
- 十题平均自动披露率：由 0.025 修正为 0.850；
- 十题平均跨 Agent 使用率：由 0.000 修正为 0.650；
- 总输入 token：1,205,166；
- 其中缓存读取 token：904,064；
- 总输出 token：30,662；
- 总 token：1,235,828；
- 全套测试：149 项通过；
- 所有任务均为 60 条讨论消息；
- manifest SHA-256 重新计算一致；
- API Key、Authorization、Bearer 扫描：0 命中。

代码提交：

```text
b31e8fe
```

GitHub：

https://github.com/sbw51898-beep/mas

## 七、与原论文结果如何比较

可以比较：

- 使用的是同一套 HiddenBench 官方任务；
- Hidden/Full Profile 的信息结构相同；
- 讨论前、讨论后和 Full Profile 指标定义一致；
- 15 轮讨论和附录 Prompt 的核心结构一致。

不能直接比较：

- 原论文是 65 题，本次只有锁定十题；
- 原论文每题有多次 session，本次每题只有一个固定种子；
- 原论文比较 15 个模型，本次只使用 DeepSeek V4 Flash；
- 本次使用 Microsoft Agent Framework 做工程迁移；
- 因模型、样本和重复次数不同，不能做显著性检验，也不能声称严格复现
  论文的 30.1% 和 80.7%。

本阶段结果应该表述为：

> 在 Microsoft Agent Framework + DeepSeek V4 Flash 上，完成了
> HiddenBench 十题单种子筛选复现。完整信息条件平均正确率为 0.950，
> 分散信息讨论前为 0.200，讨论后为 0.625。讨论总体有帮助，但同时
> 出现了三个全体一致却错误的案例。

## 八、当前结论和下一步

目前已经完成老师要求的第一阶段：

- 找到已有论文、公开数据、公开案例和公开结果；
- 使用 Microsoft Agent Framework 独立复现；
- 固定并公开实验设置；
- 保存每名 Agent 的实际可见信息；
- 保存全部 system prompt、user prompt、原始回答和 60 条讨论；
- 生成 JSONL、Markdown、manifest 和代码提交号；
- 修复了自动信息披露指标的释义漏检，并增加反向陈述保护；
- 发现讨论增益与错误共识同时存在。

下一步不宜马上加入更多自定义参数。建议先做两件事：

1. 对 ID 1、5、7 三个错误共识案例进行逐轮人工编码，判断是信息未披露、
   信息被忽略，还是正确证据被错误解释；
2. 冻结当前固定轮转基线后，再用相同任务、相同模型和相同 60 次发言
   预算比较内容感知动态发言机制，避免把预算差异误认为治理效果。

## 九、附件

- `artifacts/hiddenbench-showcase-20260728-v2.jsonl`：ID 25 v2 重评分记录；
- `artifacts/hiddenbench-showcase-20260728-v2.md`：ID 25 完整可读档案；
- `artifacts/hiddenbench-showcase-20260728-v2.manifest.json`：单案例 hash；
- `artifacts/hiddenbench-showcase-20260728-v2.gate.json`：闸门 A 校验；
- `artifacts/hiddenbench-screening-20260728-v2.jsonl`：十题 v2 重评分记录；
- `artifacts/hiddenbench-screening-20260728-v2.md`：十题指标汇总；
- `artifacts/hiddenbench-screening-20260728-v2.manifest.json`：十题 hash；
- `docs/hiddenbench-reproduction.md`：完整复现手册。
