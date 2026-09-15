# 固定几何多 observation-realization 确认报告

## 1. 目的与正式语义

固定真实目标—非目标卫星对、TLE、60秒服务段、服务中心、验证站、距离和方向，仅独立重抽经验环境项与噪声，估计 `P(ACCEPT | 固定几何条件)`。保持 `segment_local`、`fixed_site_segment_center`、`single-window` 和原 no/current/wide 正式验证器；未新增攻击、服务区、驻留时间、多站或 handover。

本轮选择是风险分层确认样本：包含全部旧 any-accept 几何和定向选择的近边界/深拒绝对照，不是随机总体样本，不能估计整个 Starlink 候选空间总体 FAR。

## 2. 条件选择与规模

- preset：confirmation；每几何 realization：30；master seed：20260712。
- 选择几何：39；分组：{'observed_mixed': 16, 'near_boundary_zero_accept_control': 10, 'deep_reject_control': 10, 'observed_all_accept': 3}。
- 目标数：5；物理 pair 数：20；服务区数：9。
- realization级数据：3510 行（每个 observation 同时评估 no/current/wide）。

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
| geometry_7ac7712edd76c5ae96f1671f | 65686->65409       | 65686_20260310T131505Z_area_3 |           2.5 |             315 |             10 |                  30 |          0.333333 |                   0.192305 |                   0.512199 |        0.170412 |       0.315952 |      -0.37087  | {"b":8,"k":8,"multiple":4}   |
| geometry_d6e17ffe3591ba8b5da76925 | 44714->65409       | 44714_20260310T023437Z_area_0 |           2.5 |             315 |             10 |                  30 |          0.333333 |                   0.192305 |                   0.512199 |       -0.130005 |       0.374277 |      -0.726586 | {"b":1,"k":17,"multiple":2}  |
| geometry_fc657fb36de801f7a353b1b5 | 44714->47749       | 44714_20260310T023437Z_area_0 |           2.5 |             135 |              9 |                  30 |          0.3      |                   0.166647 |                   0.478758 |       -0.208379 |       0.329277 |      -0.656259 | {"k":20,"multiple":1}        |

原16个 mixed 中，本轮仍 mixed 的有 **16/16**；其中 `k_boundary_sensitive` 标签数为 **16/16**。

mixed 条件 ACCEPT/REJECT realization 的 k_env：

| final_decision   |   count |      mean |      std |    median |      min |       max |
|:-----------------|--------:|----------:|---------:|----------:|---------:|----------:|
| ACCEPT           |     144 | -0.705605 | 0.283005 | -0.749275 | -1.10853 | -0.204443 |
| REJECT           |     336 | -0.661114 | 0.243919 | -0.657629 | -1.10576 | -0.199548 |

k gate 的正负 margin 翻转和 k_env 对正式 k_hat 的推动是主要机制。原 mixed 几何的 margin sign-flip 条件数为 {'score': 13, 'b': 15, 'k': 16}；b/score margin 也经常跨零，但 realization 级 primary gate 计数为 {'k': 245, 'none': 144, 'multiple': 67, 'b': 14, 'score': 10}，单独由 k 拒绝明显多于单独由 b 或 score 拒绝。因此“主要由 k gate”指判决主导路径，不表示 b/score margin 从不变化。

在每个 geometry 内去均值后，`k_env` 与正式 `k_hat` 的 Pearson 相关为 **0.799**。这比混合不同几何后的总体相关更直接地说明：固定几何时，环境线性漂移是推动正式 k_hat 跨 gate 的主要 realization 变量；噪声造成剩余离散。

## 5. 0/2 对照与深拒绝对照

- near-boundary 0/2 对照中出现新 ACCEPT：10/10；接受比例分布：{'count': 10.0, 'mean': 0.24, 'std': 0.15055453054181622, 'min': 0.03333333333333333, '25%': 0.13333333333333333, '50%': 0.23333333333333334, '75%': 0.35, 'max': 0.4666666666666667}。
- deep-reject 对照中出现 ACCEPT：0/10；接受比例分布：{'count': 10.0, 'mean': 0.0, 'std': 0.0, 'min': 0.0, '25%': 0.0, '50%': 0.0, '75%': 0.0, 'max': 0.0}。

## 6. 条件接受比例与几何机制量

分析单位是一行一个 `geometry_condition_id`，没有把 realization 行当成独立几何样本。全部选择条件的 Spearman：

| stratum      | metric                                                 |   geometry_count |   spearman_rho |   spearman_p |
|:-------------|:-------------------------------------------------------|-----------------:|---------------:|-------------:|
| all_selected | raw_geo_rmse_hz                                        |               39 |     -0.518006  |  0.000731022 |
| all_selected | actual_direction_post_projection_sensitivity_hz_per_km |               39 |     -0.656816  |  5.59286e-06 |
| all_selected | weakest_direction_sensitivity_hz_per_km                |               39 |     -0.0839984 |  0.611171    |
| all_selected | unbounded_geometry_absorption_ratio                    |               39 |     -0.214711  |  0.189314    |
| all_selected | geometry_tolerance_budget_absorption_ratio             |               39 |      0.725965  |  1.6943e-07  |

分A/B/C、目标和 pair 的描述性结果保存在 group/pair/target CSV。由于样本经过风险分层选择且只有约39个几何，相关仅用于机制描述，不能解释为总体概率模型。

## 7. current 与 wide

current→wide gate解除构成：

| gate_release_reason   |   realization_count |
|:----------------------|--------------------:|
| b gate解除            |                  28 |
| b/k同时解除           |                  72 |
| k gate解除            |                 389 |

同一 realization 的 current/wide 共享相同 observation、正式 score、b_hat 与 k_hat；wide 只扩大 b/k gate。未把 wide 描述为重新拟合得到更小正式残差。

wide 接受比例增幅最大的几何：

| geometry_condition_id             | selection_group                   | physical_pair_id   | service_area_id               |   distance_km |   direction_deg |   accept_fraction |   wide_accept_fraction |   accept_fraction_gain |
|:----------------------------------|:----------------------------------|:-------------------|:------------------------------|--------------:|----------------:|------------------:|-----------------------:|-----------------------:|
| geometry_f12f7a5a966e10915c7cb779 | near_boundary_zero_accept_control | 65409->47749       | 65409_20260310T064053Z_area_0 |           2.5 |             315 |         0.0666667 |               0.866667 |               0.8      |
| geometry_1f05d9e0fc78d13e6ad92c68 | observed_mixed                    | 44714->65421       | 44714_20260310T023437Z_area_0 |           2.5 |             135 |         0.266667  |               0.966667 |               0.7      |
| geometry_ee0188ed034f2ffa02fc8127 | near_boundary_zero_accept_control | 44714->65686       | 44714_20260310T023437Z_area_0 |           2.5 |             135 |         0.233333  |               0.9      |               0.666667 |
| geometry_fff92acd53d683488904b6be | near_boundary_zero_accept_control | 65686->44714       | 65686_20260310T131505Z_area_0 |           2.5 |             315 |         0.133333  |               0.8      |               0.666667 |
| geometry_e6cd4799426b83a8dfd2431b | observed_mixed                    | 65686->47749       | 65686_20260310T131505Z_area_0 |           2.5 |             315 |         0.166667  |               0.8      |               0.633333 |
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | 65686->65409       | 65686_20260310T131505Z_area_3 |           2.5 |             315 |         0.333333  |               0.966667 |               0.633333 |
| geometry_b1e5519233baad5d39ba95aa | observed_mixed                    | 65421->65686       | 65421_20260310T064222Z_area_0 |           2.5 |             315 |         0.366667  |               1        |               0.633333 |
| geometry_fc657fb36de801f7a353b1b5 | observed_all_accept               | 44714->47749       | 44714_20260310T023437Z_area_0 |           2.5 |             135 |         0.3       |               0.933333 |               0.633333 |
| geometry_49ccd9dcdd867115aad32a4a | near_boundary_zero_accept_control | 65409->48309       | 65409_20260310T064053Z_area_0 |           2.5 |             315 |         0.0333333 |               0.666667 |               0.633333 |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | 44714->65409       | 44714_20260310T023437Z_area_0 |           2.5 |             135 |         0.366667  |               0.966667 |               0.6      |

## 8. 风险分类与最终判断

- current 高接受比例（>=0.8）几何：0；其条件表见 geometry summary。
- current k-boundary-sensitive 几何：29。
- current 风险类别：{'observed_moderate_accept': 22, 'no_accept_observed': 10, 'observed_rare_accept': 7}。
- gate-margin类别：{'k_boundary_sensitive': 29, 'deep_reject': 10}。

**风险主要表现为 realization 敏感边界；下一步优先扩充不同日期/过境和独立物理 pair，并保留多 realization。**

## 9. 正确性审计

| check                                  | passed   | observed                                                                                                                                                                                   | expected                                                                              |
|:---------------------------------------|:---------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------|
| 选中条件均为真实轨道非中心局部条件     | True     | {'min': 2.5, 'max': 10.0}                                                                                                                                                                  | 0<d<=10 and real TLE                                                                  |
| 选中 geometry_condition_id 唯一        | True     | 0                                                                                                                                                                                          | 0 duplicates                                                                          |
| A组包含preset要求的 any-accept         | True     | 19                                                                                                                                                                                         | 19                                                                                    |
| B/C组无几何重复                        | True     | 0                                                                                                                                                                                          | 0                                                                                     |
| 每个几何每模式生成指定 realization 数  | True     | {30: 117}                                                                                                                                                                                  | 30                                                                                    |
| observation_realization_id 全局唯一    | True     | 0                                                                                                                                                                                          | 0 duplicates                                                                          |
| 同一几何 environment/noise seed 不重复 | True     | {'env': 30, 'noise': 30}                                                                                                                                                                   | 30                                                                                    |
| 调整运行顺序后 seed 可复现             | True     | 20                                                                                                                                                                                         | all sampled rows exact                                                                |
| 同一几何纯几何指标固定                 | True     | True                                                                                                                                                                                       | True                                                                                  |
| current/wide 正式 score 相同           | True     | 0.0                                                                                                                                                                                        | <=1e-10                                                                               |
| current/wide 正式 b_hat 相同           | True     | 0.0                                                                                                                                                                                        | <=1e-10                                                                               |
| current/wide 正式 k_hat 相同           | True     | 0.0                                                                                                                                                                                        | <=1e-12                                                                               |
| 无 current ACCEPT→wide REJECT          | True     | 0                                                                                                                                                                                          | 0                                                                                     |
| 同一几何 calibration seed与阈值固定    | True     | {'seed_fixed': True, 'thresholds_fixed': True}                                                                                                                                             | both true                                                                             |
| 环境与噪声分布使用旧正式 main ranges   | True     | {'b': {'min': 3179.625305204261, 'max': 3727.8380080937623}, 'k': {'min': -1.1100123194917124, 'max': -0.1981102430208065}, 'sigma': {'min': 23.22248352959119, 'max': 32.87542392003152}} | {"b_hz":[3179.0,3728.0],"k_hz_per_s":[-1.110156,-0.197808],"sigma_hz":[23.215,32.89]} |
| no/current/wide 使用同一观测           | True     | 1                                                                                                                                                                                          | 1 hash                                                                                |
| Wilson区间计算正确                     | True     | {'0/30': (0.0, 0.11351339317396876), '30/30': (0.8864866068260312, 1.0)}                                                                                                                   | standard 95% Wilson                                                                   |
| 几何汇总可回加                         | True     | {'summary': {'current_bk': 1170, 'no_bk': 1170, 'wide_bk': 1170}, 'data': {'current_bk': 1170, 'no_bk': 1170, 'wide_bk': 1170}}                                                            | equal                                                                                 |
| gate margin公式和符号正确              | True     | {'score': True, 'b': True, 'k': True}                                                                                                                                                      | all true                                                                              |
| 旧正式文件SHA-256未改变                | True     | 0                                                                                                                                                                                          | 0                                                                                     |

审计通过 20/20。任何失败时不得使用上述研究判断。

## 10. 局限

30次 realization 只给出有限精度的条件概率；2/2、30/30都不表示绝对必然，0/30也不是安全证明。环境残差来自当前经验模型，结果不等同真实 Starlink 现场攻击概率。局部方向敏感度仅用于 <=10 km，不外推远距离。样本包含全部旧正例和定向对照，存在明确选择偏差。

## 11. 输出与图

关键CSV、报告和 11 幅图均使用独立 `fixed_geometry_multi_realization` 文件名，未覆盖旧正式输出。
