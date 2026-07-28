# HiddenBench on Microsoft Agent Framework 复现实验设计

## 1. 目标

本阶段不再以自拟题作为主要证据，而是复现 Li、Naito 与 Shirado 的 HiddenBench 公开实验，再把现有动态发言机制作为后续扩展。

复现需要回答四个问题：

1. 使用 Microsoft Agent Framework（MAF）能否执行 HiddenBench 的公开隐藏信息任务；
2. DeepSeek 智能体在讨论前、讨论后和全信息条件下分别表现如何；
3. 智能体究竟看到了哪些共享信息与私有信息，又如何在讨论中披露、忽略或使用这些信息；
4. 固定轮转基线跑通以后，现有内容感知动态发言机制是否值得在相同案例、相同发言预算下继续比较。

这是一项“框架复现 + 模型迁移”的资源受限试验。由于原论文评估的是15个前沿模型，而本项目使用 DeepSeek，因此不能把数值差异全部归因于 MAF，也不能宣称严格复现论文总体正确率。

## 2. 公开依据

### 2.1 HiddenBench

- 论文：Yuxuan Li, Aoi Naito, Hirokazu Shirado, *Systematic Failures in Collective Reasoning under Distributed Information in Multi-Agent LLMs*, arXiv:2505.11556v4，ICML 2026。
- 论文地址：https://arxiv.org/abs/2505.11556
- 官方数据：https://huggingface.co/datasets/YuxuanLi1225/HiddenBench
- 数据许可：MIT。
- 官方数据规模：65个任务。
- 本次下载的 `benchmark.json` SHA-256：
  `2815AFFFCA4E470D1DFBC81E625160447DF1109CE371968181C9E1E6B90443A3`

论文报告的总体参照结果为：

- Hidden Profile 讨论后平均正确率：30.1%；
- Full Profile 单智能体正确率：80.7%；
- 主要问题：智能体不能可靠识别潜在信息不对称，容易围绕共享证据过早收敛，关键私有信息没有被主动探索。

这些数值只作为论文背景，不与本项目的10题单次筛选结果直接做显著性或等价性比较。

### 2.2 MAST

- 论文：Mert Cemri et al., *Why Do Multi-Agent LLM Systems Fail?*, arXiv:2503.13657，NeurIPS 2025 Datasets and Benchmarks。
- 论文地址：https://arxiv.org/abs/2503.13657
- 代码与数据：https://github.com/multi-agent-systems-failure-taxonomy/MAST

本项目仅将下列 MAST 标签用作人工诊断框架：

- FM-2.4 Information Withholding：掌握关键材料却没有披露；
- FM-2.5 Ignored Other Agent's Input：已经看到其他智能体输入却没有使用；
- FM-2.6 Reasoning-Action Mismatch：推理内容与最终选择不一致。

自动关键词指标只能产生候选记录，不自动宣告出现某个 MAST 失败模式。

## 3. 复现范围

### 3.1 完整展示案例

使用 HiddenBench 官方任务 ID 25：

- 名称：`select_emergency_shelter`
- 场景：化工厂事故后的四个避难所选择；
- 智能体数量：4；
- 候选方案：Station Alpha、Bravo、Charlie、Delta；
- 标准答案：Station Delta；
- 共享信息：所有智能体共同看到的避难所基础条件；
- 私有信息：4条，每名智能体固定获得1条；
- 选择理由：任务文本清晰，4条私有信息与4名智能体一一对应，适合向老师逐项展示“隐藏了什么、每个人看到了什么、如何讨论”。

该案例必须生成完整实验档案：

1. 原始英文题目及中文解释；
2. 共享信息清单；
3. Agent A-D 的私有信息分配矩阵；
4. 原论文模板对应的实际 system prompt 与 user prompt；
5. 讨论前4名智能体的选择和理由；
6. 15轮公开讨论的完整逐轮记录；
7. 讨论后4名智能体的选择和理由；
8. Full Profile 条件下的独立选择；
9. 正确率、信息披露率、跨智能体引用率、共识轮次和 MAST 候选标记；
10. 原始 JSONL、可读 Markdown 与文件哈希。

### 3.2 十题筛选集

使用固定、不按结果更换的10个官方任务：

| ID | 名称 | 领域 |
|---:|---|---|
| 1 | `evacuation_west_city` | 灾害疏散 |
| 5 | `baker_2010` | 大学校长招聘，改编自既有人类研究 |
| 7 | `graetz_et_al_1998` | 采购方案选择，改编自既有人类研究 |
| 9 | `critical_hospital_transfer` | 医院转运 |
| 13 | `Laboratory Theft Deduction` | 实验室失窃 |
| 14 | `lunch_group_decision` | 约束条件决策 |
| 16 | `Crisis Backup Decision` | 数据中心备份 |
| 25 | `select_emergency_shelter` | 化工事故避难 |
| 47 | `Find the Missing Prototype` | 原型失窃 |
| 62 | `company_acquisition_decision` | 企业收购 |

选择规则为：

- 必须来自官方 `benchmark.json`；
- 优先保留4条私有信息，可与4名智能体一一对应；
- 覆盖至少5种决策领域；
- 包含至少2个由既有人类研究改编的任务；
- 任务ID在运行前写入配置并锁定，不能依据试跑结果替换。

每个任务先执行1个固定种子，用于验证流程与生成老师可审阅的材料。该10题结果只能称为筛选结果，不与论文的“65题 × 每题10次”主实验作统计等价比较。

## 4. 实验条件

每个任务运行三个忠实复现条件。

### 4.1 Hidden Profile / Pre-discussion

- 4名智能体；
- 每名智能体看到：场景描述 + 全部共享信息 + 自己的1条私有信息；
- 私有信息分配由固定种子随机排列，但同一任务的不同条件复用同一分配；
- 智能体互相不可见；
- 输出严格 JSON：`vote` 与 `rationale`。

### 4.2 Hidden Profile / Post-discussion

- 从同一组讨论前状态开始；
- 固定轮转 A→B→C→D；
- 15轮，每轮4次公开发言，共60个讨论消息位置；
- 不因共识提前结束；
- 每次发言只允许1—2句，尽量保持原论文模板；
- 每名智能体看到自己的初始信息和此前全部公开消息；
- 15轮后4名智能体分别进行一次最终投票。

“15轮”严格定义为4名智能体各发言一次构成一轮，避免把15次单人发言误写为15轮。

### 4.3 Full Profile / Pre-discussion

- 4个相互独立的模型响应；
- 每个响应看到：场景描述 + 全部共享信息 + 全部私有信息；
- 不允许讨论；
- 输出格式与 Hidden Profile 投票相同。

该条件用于判断任务是否在信息完整时可由模型独立解决。

## 5. Prompt 忠实性

### 5.1 System prompt

以论文附录 A.4 为来源，保留以下要求：

- 插入任务描述；
- 插入该智能体可见的信息；
- 明确信息顺序已随机打乱，顺序不表示重要性或关系；
- 讨论消息保持1—2句。

### 5.2 投票 prompt

讨论前和讨论后均要求：

```json
{
  "vote": "<必须是possible_answers中的一个字符串>",
  "rationale": "<简洁理由>"
}
```

讨论后的 user prompt 必须包含完整公开讨论记录。

### 5.3 允许的适配

只允许以下 MAF/DeepSeek 适配：

- 将论文模板拆分为 MAF 的 system message 和 user message；
- 增加“只输出JSON”以保证机器解析；
- 对无效 JSON 进行一次格式修复请求；
- 记录模型名、温度、thinking 设置、请求ID和 token 用量。

不得加入“你掌握的是隐藏信息”“其他人可能拥有不同信息”“请主动寻找信息不对称”等提示，因为原论文刻意不告知智能体其信息与他人不同。

## 6. MAF 架构

复用当前项目中的：

- DeepSeek provider；
- `AgentRole`、`AgentResponse` 与消息记录模型；
- MAF 对话适配器；
- 运行审计、配置指纹和 SHA-256 manifest；
- 信息披露、跨智能体输入使用和 Brier/正确率指标。

新增边界清晰的组件：

1. HiddenBench 数据加载器：校验官方数据结构、ID和哈希；
2. 信息分配器：把共享信息复制给全体，把私有信息固定分配给4名智能体；
3. 忠实协议执行器：运行 pre-discussion、15轮固定轮转、post-discussion 和 full-profile；
4. 对话材料导出器：输出每个智能体实际看到的 prompt 与逐轮消息；
5. 论文对照报告器：区分论文总体参照值、当前10题筛选值和单案例细节；
6. MAST 人工复核清单：生成 FM-2.4/2.5/2.6 候选证据，不自动定性。

原有动态选择器不进入忠实复现主结果。只有固定轮转基线完成并冻结后，才可作为扩展条件加入。

## 7. 指标

### 7.1 HiddenBench 主指标

- `Y_pre_average`：讨论前4名智能体中选择正确答案的比例；
- `Y_post_average`：讨论后4名智能体中选择正确答案的比例；
- `Y_full_average`：全信息条件下4个独立响应中选择正确答案的比例；
- `integration_gain = Y_post_average - Y_pre_average`；
- `full_profile_gap = Y_post_average - Y_full_average`；
- majority accuracy：超过半数智能体是否选择正确答案；
- unanimity：4名智能体是否一致；
- consensus round：若讨论中可以从结构化发言识别投票，记录首次全体一致轮次；否则留空，不从自然语言强行推断。

### 7.2 过程指标

- 私有信息披露率：4条私有信息中有多少由其所有者公开；
- 跨智能体输入使用率：发言是否引用其他所有者披露的信息；
- 未披露关键信息候选；
- 已见但未使用输入候选；
- 推理与最终投票不一致候选；
- 每名智能体发言数、响应修复数、API调用数和 token 用量。

关键词匹配结果必须保留原始证据片段，并在教师报告中明确标为自动候选。

## 8. 输出材料

### 8.1 机器可审计输出

- 官方数据快照及 provenance 文件；
- 每次运行的 JSONL；
- 配置文件与固定任务ID；
- SHA-256 manifest；
- 代码提交号；
- 无密钥日志。

### 8.2 教师可读输出

生成一份新的阶段补充报告，重点不是重新解释全部代码，而是回答老师的两个问题：

1. 论文已经做过什么，公开结果是什么，我们为什么选它；
2. 一个具体案例中，题目是什么、隐藏了什么、每个人看到了什么、讨论过程是什么。

报告主体包括：

- HiddenBench 与 MAST 的文献对照；
- 复现实验设置表；
- ID 25 的完整信息分配矩阵；
- 实际 prompt；
- 逐轮对话；
- 三条件结果；
- 10题筛选汇总；
- 原论文结果与 MAF + DeepSeek 结果的可比与不可比之处；
- 下一步是否加入动态选择器。

## 9. 预算与执行闸门

执行分两步：

### 闸门 A：单案例

先只运行 ID 25。只有在以下条件全部满足后才运行其余9题：

- 4名智能体的可见信息互相隔离正确；
- 一条私有信息只分配给一个所有者；
- 讨论记录确实包含15轮 × 4发言；
- pre、post、full 三类投票可解析；
- 报告能够还原每次模型调用的可见历史；
- 无 API Key 或 Authorization 泄露；
- 用户确认单案例材料符合老师要求。

### 闸门 B：十题筛选

通过闸门 A 后运行锁定的10题各1次。任何新增重跑必须使用新的运行批次标识，不覆盖原结果。

## 10. 测试与验收

实现必须先写失败测试，再写生产代码。验收至少覆盖：

- 官方数据哈希和65条记录；
- 固定10题ID全部存在；
- ID 25 有4条共享信息、4条私有信息、4个候选项和正确答案 Station Delta；
- 每名智能体只看到自己的私有信息；
- full-profile 能看到全部私有信息；
- 固定轮转正好产生15轮 × 4消息；
- 无提前终止；
- 讨论后 prompt 包含完整公共对话；
- 投票值必须属于候选答案；
- 指标公式与手工样例一致；
- 导出材料包含题目、分配、prompt、对话与三条件结果；
- manifest 校验通过且不含密钥。

全套现有测试和新增测试必须通过，源码编译检查与 `git diff --check` 必须通过。

## 11. 明确不做

本轮不做以下事情：

- 不完整运行65题 × 10次；
- 不声称复现论文30.1%总体正确率；
- 不修改 HiddenBench 的标准答案；
- 不根据 DeepSeek 结果挑换10题；
- 不把自动关键词命中直接当作 MAST 人工标签；
- 不在忠实复现主结果中混入动态发言选择器；
- 不把现有3道自拟任务并入 HiddenBench 复现统计。

## 12. 后续扩展

忠实基线冻结后，在相同任务和相同60个公共消息预算下新增：

- 内容感知动态发言；
- HiddenBench 论文的 Exchange-then-Decide 结构化沟通；
- 固定轮转。

三者比较时使用同一初始状态、同一模型、同一任务和同一请求预算。扩展实验另写设计，不能回写或覆盖本轮忠实复现结果。
