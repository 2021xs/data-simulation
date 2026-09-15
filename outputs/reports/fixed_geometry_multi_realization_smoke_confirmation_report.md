# 固定几何多 observation-realization 确认报告

## 1. 目的与正式语义

固定真实目标—非目标卫星对、TLE、60秒服务段、服务中心、验证站、距离和方向，仅独立重抽经验环境项与噪声，估计 `P(ACCEPT | 固定几何条件)`。保持 `segment_local`、`fixed_site_segment_center`、`single-window` 和原 no/current/wide 正式验证器；未新增攻击、服务区、驻留时间、多站或 handover。

本轮选择是风险分层确认样本：包含全部旧 any-accept 几何和定向选择的近边界/深拒绝对照，不是随机总体样本，不能估计整个 Starlink 候选空间总体 FAR。

## 2. 条件选择与规模

- preset：smoke；每几何 realization：3；master seed：20260712。
- 选择几何：4；分组：{'observed_all_accept': 1, 'observed_mixed': 1, 'near_boundary_zero_accept_control': 1, 'deep_reject_control': 1}。
- 目标数：3；物理 pair 数：4；服务区数：4。
- realization级数据：36 行（每个 observation 同时评估 no/current/wide）。

## 3. 独立 seed 与经验残差模型

使用 SHA-256(`master_seed|geometry_condition_id|realization_index|stream_name`) 分别派生 environment/noise seed，不使用 Python `hash()`，不同几何与执行顺序互不依赖。calibration seed 沿用旧血缘表并在同一几何固定。

旧正式实现 `run_doppler_verifier_initial_experiments.py::sample_error_params`：

- b_env：Uniform[3179.0, 3728.0] Hz，effective constant frequency bias，不是 pure CFO truth；
- k_env：Uniform[-1.110156, -0.197808] Hz/s；
- sigma_hz：Uniform[23.215, 32.89] Hz；
- noise：`default_rng(noise_seed).normal(0, sigma_hz, N_full_pass)`，再取固定服务段；这是当前工程高斯近似，不代表严格白噪声。

## 4. 原 all-accept 与 mixed 条件

原 all-accept 条件：

| geometry_condition_id             | physical_pair_id   | service_area_id               |   distance_km |   direction_deg |   accept_count |   realization_count |   accept_fraction |   accept_fraction_ci_lower |   accept_fraction_ci_upper |   k_margin_mean |   k_margin_std |   k_margin_q05 | primary_reject_gate_counts   |
|:----------------------------------|:-------------------|:------------------------------|--------------:|----------------:|---------------:|--------------------:|------------------:|---------------------------:|---------------------------:|----------------:|---------------:|---------------:|:-----------------------------|
| geometry_7ac7712edd76c5ae96f1671f | 65686->65409       | 65686_20260310T131505Z_area_3 |           2.5 |             315 |              1 |                   3 |          0.333333 |                  0.0614919 |                    0.79234 |         0.19413 |       0.260554 |     -0.0104373 | {"b":1,"k":1}                |

原16个 mixed 中，本轮仍 mixed 的有 **1/1**；其中 `k_boundary_sensitive` 标签数为 **1/1**。

mixed 条件 ACCEPT/REJECT realization 的 k_env：

| final_decision   |   count |      mean |         std |    median |       min |       max |
|:-----------------|--------:|----------:|------------:|----------:|----------:|----------:|
| ACCEPT           |       1 | -1.03559  | nan         | -1.03559  | -1.03559  | -1.03559  |
| REJECT           |       2 | -0.735927 |   0.0828568 | -0.735927 | -0.794516 | -0.677338 |

k gate 的正负 margin 翻转和 k_env 对正式 k_hat 的推动是主要机制；b/score 伴随翻转见几何汇总的 fail fraction 与 margin 分位数。

## 5. 0/2 对照与深拒绝对照

- near-boundary 0/2 对照中出现新 ACCEPT：0/1；接受比例分布：{'count': 1.0, 'mean': 0.0, 'std': nan, 'min': 0.0, '25%': 0.0, '50%': 0.0, '75%': 0.0, 'max': 0.0}。
- deep-reject 对照中出现 ACCEPT：0/1；接受比例分布：{'count': 1.0, 'mean': 0.0, 'std': nan, 'min': 0.0, '25%': 0.0, '50%': 0.0, '75%': 0.0, 'max': 0.0}。

## 6. 条件接受比例与几何机制量

分析单位是一行一个 `geometry_condition_id`，没有把 realization 行当成独立几何样本。全部选择条件的 Spearman：

| stratum      | metric                                                 |   geometry_count |   spearman_rho |   spearman_p |
|:-------------|:-------------------------------------------------------|-----------------:|---------------:|-------------:|
| all_selected | raw_geo_rmse_hz                                        |                4 |       0        |     1        |
| all_selected | actual_direction_post_projection_sensitivity_hz_per_km |                4 |       0        |     1        |
| all_selected | weakest_direction_sensitivity_hz_per_km                |                4 |       0        |     1        |
| all_selected | unbounded_geometry_absorption_ratio                    |                4 |       0        |     1        |
| all_selected | geometry_tolerance_budget_absorption_ratio             |                4 |       0.447214 |     0.552786 |

分A/B/C、目标和 pair 的描述性结果保存在 group/pair/target CSV。由于样本经过风险分层选择且只有约39个几何，相关仅用于机制描述，不能解释为总体概率模型。

## 7. current 与 wide

current→wide gate解除构成：

| gate_release_reason   |   realization_count |
|:----------------------|--------------------:|
| b gate解除            |                   2 |
| k gate解除            |                   4 |

同一 realization 的 current/wide 共享相同 observation、正式 score、b_hat 与 k_hat；wide 只扩大 b/k gate。未把 wide 描述为重新拟合得到更小正式残差。

## 8. 风险分类与最终判断

- current 高接受比例（>=0.8）几何：0；其条件表见 geometry summary。
- current k-boundary-sensitive 几何：3。
- current 风险类别：{'observed_moderate_accept': 2, 'no_accept_observed': 2}。
- gate-margin类别：{'k_boundary_sensitive': 3, 'deep_reject': 1}。

**风险主要表现为 realization 敏感边界；下一步优先扩充不同日期/过境和独立物理 pair，并保留多 realization。**

## 9. 正确性审计

| check                                  | passed   | observed                                                                                                                                                                                    | expected                                                                              |
|:---------------------------------------|:---------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------|
| 选中条件均为真实轨道非中心局部条件     | True     | {'min': 2.5, 'max': 10.0}                                                                                                                                                                   | 0<d<=10 and real TLE                                                                  |
| 选中 geometry_condition_id 唯一        | True     | 0                                                                                                                                                                                           | 0 duplicates                                                                          |
| A组包含preset要求的 any-accept         | True     | 2                                                                                                                                                                                           | 2                                                                                     |
| B/C组无几何重复                        | True     | 0                                                                                                                                                                                           | 0                                                                                     |
| 每个几何每模式生成指定 realization 数  | True     | {3: 12}                                                                                                                                                                                     | 3                                                                                     |
| observation_realization_id 全局唯一    | True     | 0                                                                                                                                                                                           | 0 duplicates                                                                          |
| 同一几何 environment/noise seed 不重复 | True     | {'env': 3, 'noise': 3}                                                                                                                                                                      | 3                                                                                     |
| 调整运行顺序后 seed 可复现             | True     | 12                                                                                                                                                                                          | all sampled rows exact                                                                |
| 同一几何纯几何指标固定                 | True     | True                                                                                                                                                                                        | True                                                                                  |
| current/wide 正式 score 相同           | True     | 0.0                                                                                                                                                                                         | <=1e-10                                                                               |
| current/wide 正式 b_hat 相同           | True     | 0.0                                                                                                                                                                                         | <=1e-10                                                                               |
| current/wide 正式 k_hat 相同           | True     | 0.0                                                                                                                                                                                         | <=1e-12                                                                               |
| 无 current ACCEPT→wide REJECT          | True     | 0                                                                                                                                                                                           | 0                                                                                     |
| 同一几何 calibration 固定              | True     | 1                                                                                                                                                                                           | 1                                                                                     |
| 环境与噪声分布使用旧正式 main ranges   | True     | {'b': {'min': 3182.2465119157523, 'max': 3727.5046329447905}, 'k': {'min': -1.045294992632623, 'max': -0.3395489489268917}, 'sigma': {'min': 24.872286481544947, 'max': 32.08171204656382}} | {"b_hz":[3179.0,3728.0],"k_hz_per_s":[-1.110156,-0.197808],"sigma_hz":[23.215,32.89]} |
| no/current/wide 使用同一观测           | True     | 1                                                                                                                                                                                           | 1 hash                                                                                |
| Wilson区间计算正确                     | True     | {'0/30': (0.0, 0.11351339317396876), '30/30': (0.8864866068260312, 1.0)}                                                                                                                    | standard 95% Wilson                                                                   |
| 几何汇总可回加                         | True     | {'summary': {'current_bk': 12, 'no_bk': 12, 'wide_bk': 12}, 'data': {'current_bk': 12, 'no_bk': 12, 'wide_bk': 12}}                                                                         | equal                                                                                 |
| gate margin公式和符号正确              | True     | {'score': True, 'b': True, 'k': True}                                                                                                                                                       | all true                                                                              |
| 旧正式文件SHA-256未改变                | True     | 0                                                                                                                                                                                           | 0                                                                                     |

审计通过 20/20。任何失败时不得使用上述研究判断。

## 10. 局限

30次 realization 只给出有限精度的条件概率；2/2、30/30都不表示绝对必然，0/30也不是安全证明。环境残差来自当前经验模型，结果不等同真实 Starlink 现场攻击概率。局部方向敏感度仅用于 <=10 km，不外推远距离。样本包含全部旧正例和定向对照，存在明确选择偏差。

## 11. 输出与图

关键CSV、报告和 11 幅图均使用独立 `fixed_geometry_multi_realization` 文件名，未覆盖旧正式输出。
