# HiddenBench MAF 十题筛选实验

论文公开参照为 65 题、多模型、多 session：Hidden Profile 讨论后平均正确率 30.1%，Full Profile 80.7%。当前结果是 10 题、单种子、MAF + DeepSeek 的筛选实验，样本、模型和重复次数不同，不能做统计等价或显著性声明。

| ID | Task | Y_pre | Y_post | Y_full | Gain | Disclosure | Cross-use |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | evacuation_west_city | 0.500 | 0.000 | 1.000 | -0.500 | 0.750 | 0.750 |
| 5 | baker_2010 | 0.000 | 0.000 | 1.000 | 0.000 | 0.750 | 0.500 |
| 7 | graetz_et_al_1998 | 0.250 | 0.000 | 0.750 | -0.250 | 1.000 | 1.000 |
| 9 | critical_hospital_transfer | 0.000 | 1.000 | 1.000 | 1.000 | 0.750 | 0.500 |
| 13 | Laboratory Theft Deduction | 0.250 | 1.000 | 0.750 | 0.750 | 1.000 | 0.750 |
| 14 | lunch_group_decision | 0.000 | 0.250 | 1.000 | 0.250 | 0.750 | 0.000 |
| 16 | Crisis Backup Decision | 0.250 | 1.000 | 1.000 | 0.750 | 0.500 | 0.500 |
| 25 | select_emergency_shelter | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 47 | Find the Missing Prototype | 0.750 | 1.000 | 1.000 | 0.250 | 1.000 | 0.750 |
| 62 | company_acquisition_decision | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.750 |

## 均值

- Y_pre_average: 0.200
- Y_post_average: 0.625
- Y_full_average: 0.950
- Integration gain: 0.425
- Full profile gap: -0.325
- Private fact disclosure rate: 0.850
- Cross-agent use rate: 0.650
- Total API requests: 721
- Total repair requests: 1

## 来源

- HiddenBench: https://arxiv.org/abs/2505.11556
- Official dataset: https://huggingface.co/datasets/YuxuanLi1225/HiddenBench
- MAST: https://arxiv.org/abs/2503.13657
