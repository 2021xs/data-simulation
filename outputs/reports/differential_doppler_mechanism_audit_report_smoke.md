# 差分多普勒机制可行性审计报告

## 1. 本轮目的

本轮复用既有服务区内部空间风险与单站跨服务区重复性实验的卫星组合、60 秒服务段、服务中心和验证站，重新传播固定地面点多普勒，解释非目标样本的既有误接受。未新增攻击、未改变 sequence_mode、阈值或正式判决逻辑，也未评价 full pass 或 handover。

## 2. 与旧实验的关系

输入正式数据为 `multi_service_area_single_station_dataset.csv`。几何残差统一采用 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。轨道传播、目的点生成、受控轨道构造、校准和 gate 均复用旧脚本公共实现。旧 verifier 对每段使用 `t-mean(t)` 的无权重普通最小二乘；因此 b 的参考时刻是该服务段的时间均值。

方向角沿用旧实现：0° 指北、90° 指东、顺时针增加。Jacobian 列顺序为 East/North，实际方向投影使用 `[sin(phi), cos(phi)]`。

## 3. 样本选择

自动选择 4 个“来源/分组/目标—非目标”实例，保留每个组合原有 4～5 个有效服务区。真实轨道优先 0/2.5/5/10 km，受控样本优先 0/10/50/100/200/500 km；替换记录见清单。

| pair_id                                                  | sample_source      | sample_group       |   target_id | nontarget_id                      | selection_reason                                                                                                                   |   number_of_service_areas | distance_substitution_note   |
|:---------------------------------------------------------|:-------------------|:-------------------|------------:|:----------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------|--------------------------:|:-----------------------------|
| real_tle_candidate:65686:44714                           | real_tle_candidate | ordinary_similar   |       65686 | 44714                             | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；个别服务区偶发误接受；真实轨道普通相似样本                           |                         5 | 无                           |
| real_tle_candidate:65410:45230                           | real_tle_candidate | boundary_case      |       65410 | 45230                             | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；跨服务区持续或高比例误接受；真实轨道较难区分样本                     |                         5 | 无                           |
| legacy_synthetic:44714:synthetic_inclination_offset_0.2  | legacy_synthetic   | original_like      |       44714 | synthetic_inclination_offset_0.2  | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；普通相似受控样本 |                         4 | 无                           |
| legacy_synthetic:65409:synthetic_inclination_offset_0.05 | legacy_synthetic   | hard_case_weighted |       65409 | synthetic_inclination_offset_0.05 | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；高难度受控样本   |                         5 | 无                           |

## 4. 指标定义

`raw_geo_*` 是判决前纯几何残差；`unbounded_*` 是同一中心化时间定义下的无边界 b+kt 投影。`bounded_*` 是几何贡献的 box-constrained 最小二乘：no_bk 固定 b=k=0；current/wide 使用正式 gate 相对中心的参数容差（wide 为 current 的两倍）作为几何贡献预算。CSV 同时保存正式绝对 gate 上下界。由于中心化设计的常数列与时间列正交，对无边界系数逐项 clip 是精确的 box 最优解。

`score_value`、原始 b/k 与 final decision 来自旧正式观测（含经验环境项与噪声）；机制拟合只针对重算的纯几何项，二者没有混用。所有权重为 1。

## 5. 正确性审计

| check                     | passed   |     observed | tolerance                   | notes                            |
|:--------------------------|:---------|-------------:|:----------------------------|:---------------------------------|
| d=0距离误差               | True     |  0           | <=1e-6 km                   |                                  |
| d=0原始几何残差           | True     |  1.5958e-06  | <=0.001 Hz                  |                                  |
| no_bk恒等                 | True     |  0           | b=k=0且post=raw             |                                  |
| 无边界拟合RMSE不增        | True     | -2.06999e-09 | <=1e-8 Hz                   |                                  |
| wide有界残差不高于current | True     |  0           | <=1e-8 Hz                   |                                  |
| 有界参数满足边界          | True     |  0           | box内                       |                                  |
| 判决重放一致率            | True     |  1           | 目标=100%                   | 不一致0条                        |
| 有限差分0.5/1/2km稳定     | True     |  0.000904949 | 最大相对变化<=15%           | 局部数值稳定性检查               |
| 经纬度/ENU/单位           | True     |  2.04503e-12 | 大圆目的点距离误差<=1e-6 km | 0°北、90°东、顺时针；传播高度0 m |
| 吸收比例数值范围          | True     |  0           | 浮点容差内[0,1]             |                                  |
| current→wide样本存在      | True     | 20           | >0                          |                                  |

判决重放一致率为 100.00%（513/513）。吸收比例浮点截断 0 次；d=0 且原始能量接近零时保持 NaN，不作强行解释。

## 6. 距离之外的几何解释

简单逻辑回归使用标准化特征和同一审计样本内 ROC-AUC，仅作可解释性筛查，不是泛化性能估计。

| model_or_bin                                        |   n |    value | notes                                                                                                                                                        |
|:----------------------------------------------------|----:|---------:|:-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| distance_only                                       | 152 | 0.954545 | value=in-sample ROC-AUC; standardized coefficients: distance_km=2.93                                                                                         |
| distance_plus_direction_sensitivity                 | 152 | 0.930398 | value=in-sample ROC-AUC; standardized coefficients: distance_km=2.362;actual_direction_post_projection_sensitivity_hz_per_km=-1.081                          |
| distance_plus_absorption                            | 152 | 0.964489 | value=in-sample ROC-AUC; standardized coefficients: distance_km=2.745;absorption_ratio=0.4444                                                                |
| distance_plus_direction_sensitivity_plus_absorption | 152 | 0.96076  | value=in-sample ROC-AUC; standardized coefficients: distance_km=2.365;actual_direction_post_projection_sensitivity_hz_per_km=-0.9797;absorption_ratio=0.2217 |

Spearman 结果：

| model_or_bin                                           |   n |     value |   secondary_value |
|:-------------------------------------------------------|----:|----------:|------------------:|
| distance_km                                            | 152 |  0.898933 |       1.23779e-55 |
| actual_direction_post_projection_sensitivity_hz_per_km | 152 | -0.736154 |       3.26734e-27 |
| absorption_ratio                                       | 152 |  0.575789 |       8.47845e-15 |
| anisotropy_ratio                                       | 152 | -0.856349 |       6.71648e-45 |
| raw_geo_rmse_hz                                        | 152 | -0.721559 |       1.00343e-25 |

距离-only AUC=0.955；距离+方向敏感度+吸收比例 AUC=0.961。同距离分组统计已保存到 `differential_doppler_mechanism_distance_explanatory_analysis_smoke.csv`。这些量若只与拟合后 RMSE 同步而没有相对距离的增益，不视作独立解释力。

## 7. current/wide b/k 差异机制

审计中共有 20 条 current REJECT→wide ACCEPT。机制分类：

| mechanism_class   |   count |
|:------------------|--------:|
| b边界解除         |      13 |
| k边界解除         |       4 |
| b/k同时解除       |       3 |

旧 verifier 的 current/wide 使用相同的无边界 b+kt 投影；新增接受来自参数 gate 容差放宽，而不是不同拟合子空间。几何 box 拟合仅用于量化在对应容差预算内可被吸收的部分。

## 8. 真实轨道与受控高难度样本差异

| group_label          |   n |   raw_geo_rmse |   actual_sensitivity |   weakest_sensitivity |   anisotropy |   absorption |   boundary_hit |   remaining_rmse |   accept_fraction |
|:---------------------|----:|---------------:|---------------------:|----------------------:|-------------:|-------------:|---------------:|-----------------:|------------------:|
| 普通相似受控样本     |  32 |        6.25656 |             0.055132 |            0.00880359 |       9.7803 |     0.920806 |              0 |         0.550266 |               1   |
| 真实轨道普通相似样本 |  40 |      717.531   |             7.89954  |            0.0862097  |     143.23   |     0.641518 |              1 |       470.918    |               0   |
| 真实轨道较难区分样本 |  40 |      678.458   |             7.93406  |            0.0857042  |     144.958  |     0.660408 |              1 |       438.181    |               0   |
| 高难度受控样本       |  40 |        1.78052 |             0.037726 |            0.00148969 |      37.1675 |     0.922756 |              0 |         0.376663 |               0.8 |

难例需区分：raw_geo_rmse 本就较小，或 raw_geo_rmse 不小但 absorption_ratio 较高。这里的 remaining_rmse 是机制解释量，不包装成新的 verifier 分数。

## 9. 跨服务区重复性解释

| pair_id                                                  | group_label          |   service_area_accept_fraction |   mean_actual_direction_sensitivity |   mean_weakest_direction_sensitivity |   mean_absorption_ratio |   absorption_ratio_std |   service_area_sensitivity_variance |   service_area_absorption_variance | persistent_accept   | recurrent_accept   |
|:---------------------------------------------------------|:---------------------|-------------------------------:|------------------------------------:|-------------------------------------:|------------------------:|-----------------------:|------------------------------------:|-----------------------------------:|:--------------------|:-------------------|
| legacy_synthetic:44714:synthetic_inclination_offset_0.2  | 普通相似受控样本     |                      1         |                           0.0505495 |                           0.00880359 |                0.824988 |               0.298459 |                         3.70158e-05 |                        0.000376989 | True                | True               |
| legacy_synthetic:65409:synthetic_inclination_offset_0.05 | 高难度受控样本       |                      0.8       |                           0.0362062 |                           0.00148969 |                0.824583 |               0.286197 |                         8.34015e-05 |                        2.8601e-05  | False               | True               |
| real_tle_candidate:65410:45230                           | 真实轨道较难区分样本 |                      0.0666667 |                           7.80046   |                           0.0857042  |                0.589844 |               0.273881 |                         0.00101665  |                        0.0010007   | False               | True               |
| real_tle_candidate:65686:44714                           | 真实轨道普通相似样本 |                      0.0444444 |                           7.81446   |                           0.0862097  |                0.571846 |               0.282452 |                         0.00141838  |                        4.28265e-05 | False               | False              |

`persistent_accept` 沿用旧定义：服务区接受比例=1；`recurrent_accept`：服务区接受比例>=0.5。这里“服务区接受”指该服务区内至少一个保留的距离/方向条件被 current_bk 接受。

## 10. 方向是否值得扩大

本轮停止判断：**当前几何机制指标未形成足够独立预测价值，不建议进入全量扩展**。

判定依据：方向敏感度 Spearman rho=-0.736，吸收比例 rho=0.576，current→wide 可分类解释比例=100.00%，完整简单模型相对距离-only 的样本内 AUC 增量=0.006。只有这些指标在同距离、current/wide 和跨服务区层面共同显示额外解释力时才建议扩大。

## 11. 当前局限

- 这是 8～12 对量级的代表性可行性审计，ROC-AUC 为样本内描述量，未做外部泛化声明。
- 有限差分 Jacobian 仅解释服务中心附近；不声称精确预测 100～500 km 的非线性残差。
- 受控样本仍是受控轨道构造，不代表真实 Starlink 频偏真值。
- 本轮没有证明统一安全距离、轨道面共面或相位接近的根因，也不作绝对首次性声明。

关键图：representative_three_curves.png, current_reject_wide_accept_boundary_comparison.png, same_distance_direction_sensitivity_decision.png, absorption_ratio_vs_decision.png, risk_distance_vs_weakest_sensitivity.png, cross_service_area_mechanism_heatmap.png。
