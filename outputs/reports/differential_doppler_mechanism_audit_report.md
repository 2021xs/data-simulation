# 差分多普勒机制可行性审计报告

## 1. 本轮目的

本轮复用既有服务区内部空间风险与单站跨服务区重复性实验的卫星组合、60 秒服务段、服务中心和验证站，重新传播固定地面点多普勒，解释非目标样本的既有误接受。未新增攻击、未改变 sequence_mode、阈值或正式判决逻辑，也未评价 full pass 或 handover。

## 2. 与旧实验的关系

输入正式数据为 `multi_service_area_single_station_dataset.csv`。几何残差统一采用 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。轨道传播、目的点生成、受控轨道构造、校准和 gate 均复用旧脚本公共实现。旧 verifier 对每段使用 `t-mean(t)` 的无权重普通最小二乘；因此 b 的参考时刻是该服务段的时间均值。

方向角沿用旧实现：0° 指北、90° 指东、顺时针增加。Jacobian 列顺序为 East/North，实际方向投影使用 `[sin(phi), cos(phi)]`。

## 3. 样本选择

自动选择 10 个“来源/分组/目标—非目标”实例，保留每个组合原有 4～5 个有效服务区。真实轨道优先 0/2.5/5/10 km，受控样本优先 0/10/50/100/200/500 km；替换记录见清单。

| pair_id                                                        | sample_source      | sample_group       |   target_id | nontarget_id                            | selection_reason                                                                                                                   |   number_of_service_areas | distance_substitution_note   |
|:---------------------------------------------------------------|:-------------------|:-------------------|------------:|:----------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------|--------------------------:|:-----------------------------|
| real_tle_candidate:65686:44714                                 | real_tle_candidate | ordinary_similar   |       65686 | 44714                                   | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；个别服务区偶发误接受；真实轨道普通相似样本                           |                         5 | 无                           |
| real_tle_candidate:65410:45230                                 | real_tle_candidate | boundary_case      |       65410 | 45230                                   | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；跨服务区持续或高比例误接受；真实轨道较难区分样本                     |                         5 | 无                           |
| legacy_synthetic:44714:synthetic_inclination_offset_0.2        | legacy_synthetic   | original_like      |       44714 | synthetic_inclination_offset_0.2        | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；普通相似受控样本 |                         4 | 无                           |
| legacy_synthetic:65409:synthetic_inclination_offset_0.05       | legacy_synthetic   | hard_case_weighted |       65409 | synthetic_inclination_offset_0.05       | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；高难度受控样本   |                         5 | 无                           |
| legacy_synthetic:65409:synthetic_same_plane_altitude_offset_-1 | legacy_synthetic   | hard_case_weighted |       65409 | synthetic_same_plane_altitude_offset_-1 | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；高难度受控样本   |                         5 | 无                           |
| legacy_synthetic:44714:synthetic_inclination_offset_-0.2       | legacy_synthetic   | original_like      |       44714 | synthetic_inclination_offset_-0.2       | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；普通相似受控样本 |                         4 | 无                           |
| real_tle_candidate:44714:65686                                 | real_tle_candidate | ordinary_similar   |       44714 | 65686                                   | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；跨服务区持续或高比例误接受；真实轨道普通相似样本                     |                         4 | 无                           |
| real_tle_candidate:65686:47749                                 | real_tle_candidate | boundary_case      |       65686 | 47749                                   | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；个别服务区偶发误接受；真实轨道较难区分样本                           |                         5 | 无                           |
| legacy_synthetic:65421:synthetic_same_plane_altitude_offset_-1 | legacy_synthetic   | hard_case_weighted |       65421 | synthetic_same_plane_altitude_offset_-1 | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；高难度受控样本   |                         5 | 无                           |
| legacy_synthetic:44714:synthetic_same_plane_altitude_offset_10 | legacy_synthetic   | original_like      |       44714 | synthetic_same_plane_altitude_offset_10 | current_bk误接受；current拒绝→wide误接受；current/wide均拒绝；同距离不同方向判决不同；跨服务区持续或高比例误接受；普通相似受控样本 |                         4 | 无                           |

## 4. 指标定义

`raw_geo_*` 是判决前纯几何残差；`unbounded_*` 是同一中心化时间定义下的无边界 b+kt 投影。`bounded_*` 是几何贡献的 box-constrained 最小二乘：no_bk 固定 b=k=0；current/wide 使用正式 gate 相对中心的参数容差（wide 为 current 的两倍）作为几何贡献预算。CSV 同时保存正式绝对 gate 上下界。由于中心化设计的常数列与时间列正交，对无边界系数逐项 clip 是精确的 box 最优解。

`score_value`、原始 b/k 与 final decision 来自旧正式观测（含经验环境项与噪声）；机制拟合只针对重算的纯几何项，二者没有混用。所有权重为 1。

## 5. 正确性审计

| check                     | passed   |      observed | tolerance                   | notes                            |
|:--------------------------|:---------|--------------:|:----------------------------|:---------------------------------|
| d=0距离误差               | True     |   0           | <=1e-6 km                   | nan                              |
| d=0原始几何残差           | True     |   1.5958e-06  | <=0.001 Hz                  | nan                              |
| no_bk恒等                 | True     |   0           | b=k=0且post=raw             | nan                              |
| 无边界拟合RMSE不增        | True     |  -9.68684e-10 | <=1e-8 Hz                   | nan                              |
| wide有界残差不高于current | True     |   0           | <=1e-8 Hz                   | nan                              |
| 有界参数满足边界          | True     |   0           | box内                       | nan                              |
| 判决重放一致率            | True     |   1           | 目标=100%                   | 不一致0条                        |
| 有限差分0.5/1/2km稳定     | True     |   0.00201147  | 最大相对变化<=15%           | 局部数值稳定性检查               |
| 经纬度/ENU/单位           | True     |   2.43006e-12 | 大圆目的点距离误差<=1e-6 km | 0°北、90°东、顺时针；传播高度0 m |
| 吸收比例数值范围          | True     |   0           | 浮点容差内[0,1]             | nan                              |
| current→wide样本存在      | True     | 257           | >0                          | nan                              |

判决重放一致率为 100.00%（4746/4746）。吸收比例浮点截断 0 次；d=0 且原始能量接近零时保持 NaN，不作强行解释。

## 6. 距离之外的几何解释

简单逻辑回归使用标准化特征和同一审计样本内 ROC-AUC，仅作可解释性筛查，不是泛化性能估计。

| model_or_bin                                        |    n |    value | notes                                                                                                                                                      |
|:----------------------------------------------------|-----:|---------:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| distance_only                                       | 1536 | 0.523302 | value=in-sample ROC-AUC; standardized coefficients: distance_km=-0.6999                                                                                    |
| distance_plus_direction_sensitivity                 | 1536 | 0.908748 | value=in-sample ROC-AUC; standardized coefficients: distance_km=-1.795;actual_direction_post_projection_sensitivity_hz_per_km=-6.748                       |
| distance_plus_absorption                            | 1536 | 0.874593 | value=in-sample ROC-AUC; standardized coefficients: distance_km=-1.179;absorption_ratio=2.483                                                              |
| distance_plus_direction_sensitivity_plus_absorption | 1536 | 0.917539 | value=in-sample ROC-AUC; standardized coefficients: distance_km=-1.547;actual_direction_post_projection_sensitivity_hz_per_km=-5.855;absorption_ratio=1.76 |

Spearman 结果：

| model_or_bin                                           |    n |      value |   secondary_value |
|:-------------------------------------------------------|-----:|-----------:|------------------:|
| distance_km                                            | 1536 | -0.0354311 |      0.165163     |
| actual_direction_post_projection_sensitivity_hz_per_km | 1536 | -0.396569  |      5.16764e-59  |
| absorption_ratio                                       | 1536 |  0.462525  |      2.89736e-82  |
| anisotropy_ratio                                       | 1536 | -0.270989  |      2.92599e-27  |
| raw_geo_rmse_hz                                        | 1536 | -0.631409  |      1.21299e-171 |

距离-only AUC=0.523；距离+方向敏感度+吸收比例 AUC=0.918。同距离分组统计已保存到 `differential_doppler_mechanism_distance_explanatory_analysis.csv`。这些量若只与拟合后 RMSE 同步而没有相对距离的增益，不视作独立解释力。

## 7. current/wide b/k 差异机制

审计中共有 257 条 current REJECT→wide ACCEPT。机制分类：

| mechanism_class   |   count |
|:------------------|--------:|
| k边界解除         |     180 |
| b边界解除         |      53 |
| b/k同时解除       |      24 |

其中 current 几何 box 触边比例为 49.42%，放宽到 wide 后解除触边比例为 37.74%；几何有界拟合后 RMSE 平均下降 19.85%，吸收比例平均增加 0.0254。正式 gate 的变化分类全部可归入 b 边界解除、k 边界解除或二者同时解除；逐条的 score/b/k/coverage/quality gate 变化保存在 `differential_doppler_mechanism_current_to_wide.csv`。

旧 verifier 的 current/wide 使用相同的无边界 b+kt 投影；新增接受来自参数 gate 容差放宽，而不是不同拟合子空间。几何 box 拟合仅用于量化在对应容差预算内可被吸收的部分。

## 8. 真实轨道与受控高难度样本差异

| group_label          |   n |   raw_geo_rmse |   actual_sensitivity |   weakest_sensitivity |   anisotropy |   absorption |   boundary_hit |   remaining_rmse |   accept_fraction |
|:---------------------|----:|---------------:|---------------------:|----------------------:|-------------:|-------------:|---------------:|-----------------:|------------------:|
| 普通相似受控样本     | 480 |       282.349  |            0.14872   |           0.00881918  |      10.2703 |     0.810121 |       0.608333 |         187.466  |          0.372917 |
| 真实轨道普通相似样本 | 216 |      1718.36   |            7.88015   |           0.0847062   |     148.216  |     0.449016 |       1        |        1455.24   |          0        |
| 真实轨道较难区分样本 | 240 |      1606.14   |            7.91724   |           0.0862742   |     143.559  |     0.455248 |       1        |        1352.04   |          0        |
| 高难度受控样本       | 600 |        52.5826 |            0.0483122 |           0.000583387 |     587.02   |     0.86366  |       0.511667 |          17.4669 |          0.341667 |

难例需区分：raw_geo_rmse 本就较小，或 raw_geo_rmse 不小但 absorption_ratio 较高。这里的 remaining_rmse 是机制解释量，不包装成新的 verifier 分数。

## 9. 跨服务区重复性解释

| pair_id                                                        | group_label          |   service_area_accept_fraction |   mean_actual_direction_sensitivity |   mean_weakest_direction_sensitivity |   mean_absorption_ratio |   absorption_ratio_std |   service_area_sensitivity_variance |   service_area_absorption_variance | persistent_accept   | recurrent_accept   |
|:---------------------------------------------------------------|:---------------------|-------------------------------:|------------------------------------:|-------------------------------------:|------------------------:|-----------------------:|------------------------------------:|-----------------------------------:|:--------------------|:-------------------|
| legacy_synthetic:44714:synthetic_inclination_offset_-0.2       | 普通相似受控样本     |                      0.536585  |                           0.0584321 |                          0.0085994   |                0.948277 |               0.151286 |                         4.41429e-05 |                        2.47039e-05 | True                | True               |
| legacy_synthetic:44714:synthetic_inclination_offset_0.2        | 普通相似受控样本     |                      0.554878  |                           0.0541261 |                          0.00880359  |                0.895966 |               0.194507 |                         3.88244e-05 |                        0.000139236 | True                | True               |
| legacy_synthetic:44714:synthetic_same_plane_altitude_offset_10 | 普通相似受控样本     |                      0.0731707 |                           0.332848  |                          0.00905456  |                0.530156 |               0.282648 |                         8.80019e-06 |                        0.000340878 | True                | True               |
| legacy_synthetic:65409:synthetic_inclination_offset_0.05       | 高难度受控样本       |                      0.478049  |                           0.0373924 |                          0.00148969  |                0.89242  |               0.174298 |                         7.99653e-05 |                        0.000133411 | False               | True               |
| legacy_synthetic:65409:synthetic_same_plane_altitude_offset_-1 | 高难度受控样本       |                      0.263415  |                           0.052421  |                          0.000125392 |                0.818491 |               0.22294  |                         3.8504e-05  |                        0.000249348 | False               | True               |
| legacy_synthetic:65421:synthetic_same_plane_altitude_offset_-1 | 高难度受控样本       |                      0.321951  |                           0.0544434 |                          0.000135082 |                0.81932  |               0.221617 |                         4.10747e-05 |                        0.000411388 | True                | True               |
| real_tle_candidate:44714:65686                                 | 真实轨道普通相似样本 |                      0.04      |                           7.84106   |                          0.0828269   |                0.445939 |               0.297598 |                         0.00817385  |                        0.000259353 | True                | True               |
| real_tle_candidate:65410:45230                                 | 真实轨道较难区分样本 |                      0.024     |                           7.88596   |                          0.0857042   |                0.44403  |               0.279184 |                         0.0112135   |                        0.00115173  | False               | True               |
| real_tle_candidate:65686:44714                                 | 真实轨道普通相似样本 |                      0.016     |                           7.86891   |                          0.0862097   |                0.421943 |               0.277245 |                         0.0102133   |                        0.000605331 | False               | False              |
| real_tle_candidate:65686:47749                                 | 真实轨道较难区分样本 |                      0.016     |                           7.86978   |                          0.0868442   |                0.432963 |               0.28128  |                         0.0102063   |                        0.000533216 | False               | False              |

`persistent_accept` 与 `recurrent_accept` 沿用旧实验的固定条件跨服务区口径。

更精确地说，本表先对每个固定“距离×方向”条件计算跨服务区接受比例，再令某组合只要存在比例=1 的条件即为 persistent、存在比例>=0.5 的条件即为 recurrent；`service_area_accept_fraction` 是这些固定条件比例的均值。组合层面（n=10）的 Spearman 结果为：重复接受比例 vs 实际方向敏感度 rho=-0.802（p=0.00521），vs 最弱方向敏感度 rho=-0.754（p=0.0118），vs 平均吸收比例 rho=0.985（p=2.29e-07）。重复接受比例与服务区间敏感度方差 rho=-0.620（p=0.0558），与吸收比例方差 rho=-0.839（p=0.00241）。在本代表样本中，持续/高重复风险总体对应更低方向敏感度和更高且跨区更稳定的吸收比例；偶发风险组合的这些条件不同时成立。n=10 很小，因此只作为机制证据，不作总体推断。

## 10. 方向是否值得扩大

本轮停止判断：**建议进入全量分析**。

判定依据：方向敏感度 Spearman rho=-0.397，吸收比例 rho=0.463，current→wide 可分类解释比例=100.00%，完整简单模型相对距离-only 的样本内 AUC 增量=0.394。只有这些指标在同距离、current/wide 和跨服务区层面共同显示额外解释力时才建议扩大。

## 11. 当前局限

- 这是 8～12 对量级的代表性可行性审计，ROC-AUC 为样本内描述量，未做外部泛化声明。
- 有限差分 Jacobian 仅解释服务中心附近；不声称精确预测 100～500 km 的非线性残差。
- 受控样本仍是受控轨道构造，不代表真实 Starlink 频偏真值。
- 本轮没有证明统一安全距离、轨道面共面或相位接近的根因，也不作绝对首次性声明。

关键图：absorption_ratio_vs_decision.png, cross_service_area_mechanism_heatmap.png, current_reject_wide_accept_boundary_comparison.png, representative_three_curves.png, risk_distance_vs_weakest_sensitivity.png, same_distance_direction_sensitivity_decision.png。
