# HiddenBench 官方 GPT-4.1 四题结果与本实验对照

## 口径

- 官方逐题数值不是从论文总表反推，而是从 HiddenBench 官方公开结果包逐 session 重新计分。
- 官方计分严格复用仓库 `src/hiddenbench/metrics.py` 的定义：平均正确率是每轮四名 Agent 正确票比例；多数正确率要求正确票严格超过一半。
- 本实验的 DeepSeek 数值只与同一题、同一隐藏信息结构做描述性对照。模型、编排实现和实验日期均不同，不能把差值单独归因于 Microsoft Agent Framework。

## 逐题结果

| ID | 场景 | 官方 GPT-4.1 Hidden 前/后平均正确率 | 官方 Hidden 前/后多数正确率 | 官方 Full 前平均/多数正确率 | 本实验固定/动态后多数正确率 |
|---:|---|---:|---:|---:|---:|
| 1 | `evacuation_west_city` | 0.0% / 50.0% | 0.0% / 50.0% | 70.0% / 60.0% | 100.0% / 60.0% |
| 5 | `baker_2010` | 7.5% / 2.5% | 0.0% / 0.0% | 100.0% / 100.0% | 0.0% / 0.0% |
| 7 | `graetz_et_al_1998` | 40.0% / 50.0% | 10.0% / 50.0% | 100.0% / 100.0% | 20.0% / 0.0% |
| 25 | `select_emergency_shelter` | 0.0% / 50.0% | 0.0% / 50.0% | 100.0% / 100.0% | 80.0% / 80.0% |

每题官方 Hidden 和 Full Profile 均为 10 个 session。官方 Hidden 为 15 轮讨论；公开 Full Profile 文件中这四题均记录 1 轮。

## 来源冻结

- HiddenBench 官方代码提交：`3be6ca16973e4fb751ffc0dfb7eb11f2d28335d1`。
- 官方结果数据集：`YuxuanLi1225/HiddenBench-results`。
- `paper/hidden_manual_adapted/hidden_manual_adapted_gpt-4.1.json`：SHA-256 `1c425d73ff384a182ecc3a5109546eaaf62618e076300c8d3ccf384ae031d9cf`。
- `paper/hidden_generated/hidden_generated_gpt-4.1.json`：SHA-256 `e0ea7e3d1f2ba96f636c0eafd8fd485e73b2785e7ee9911e3000d253cd613a84`。
- `paper/full_profile/full_profile_gpt-4.1.json`：SHA-256 `262ce811e96f1d28a0ef1bdb69e42487acbd8da0c56d67c327351cd6c2bb1e55`。
- 本地对照：`artifacts/hiddenbench-stability-20260729.summary.csv`。
