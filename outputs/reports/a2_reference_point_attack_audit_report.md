# A2-R verifier-aware最优公共参考点审计

## 1. 范围

本轮只研究 `q(t;C')=F_A(C',t)-F_B(C',t)`、`C'∈Ω` 的A2-R攻击类。Ω沿用以原C为中心、R_cell=500 km的受控圆盘；S主分析按面积均匀分布。这不是Starlink真实用户分布，也不是所有可能q(t)的全局优化。

没有生成environment/noise realization，没有修改verifier/threshold，没有做轨道参数sweep。代表条件来自既有标签：

| geometry_condition_id             | representative_role        | selection_group                   | physical_pair_id   |   target_sat_id |   attack_sat_id | service_area_id               |
|:----------------------------------|:---------------------------|:----------------------------------|:-------------------|----------------:|----------------:|:------------------------------|
| geometry_7ac7712edd76c5ae96f1671f | high_risk_existing_label   | observed_all_accept               | 65686->65409       |           65686 |           65409 | 65686_20260310T131505Z_area_3 |
| geometry_e51710366902774f39f711f3 | boundary_existing_label    | near_boundary_zero_accept_control | 44714->65409       |           44714 |           65409 | 44714_20260310T023437Z_area_0 |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_existing_label | deep_reject_control               | 65686->65421       |           65686 |           65421 | 65686_20260310T131505Z_area_2 |

## 2. 局部理论

令S=C+Δx、C'=C+δ，且`ΔF(C+z)≈ΔF_C+Jz`。则`d(S;C')=ΔF(C')-ΔF(S)≈J(δ-Δx)`，投影能量为`(δ-Δx)^T M(δ-Δx)`，M=`J^TQJ`。区域期望为：

`E[D_proj²(δ)] = (δ-μ)^T M(δ-μ) + tr(MΣ)`，其中μ=`E[Δx]`、Σ=`Cov(Δx)`。

若区域关于C对称，μ=0；M正定时δ=0是唯一一阶projected-energy optimum，M半正定时沿其零空间可能不唯一。该结论只针对局部一阶和projected energy，不自动适用于verifier-aware P_accept。

## 3. 数值设计

- C' coarse Cartesian disk grid：125 km；
- local refinement：31.25 km，再以15.625 km确认；
- S uniform-area主积分：9段面积坐标×每段3阶Gauss×24角度；
- 空间敏感性核对：9段×每段5阶×32角度；
- 每个S,C'的概率使用上一轮32×48阶半解析environment/noise积分。

## 4. 核心结果

| selection_group                   |   target_sat_id |   attack_sat_id | optimum_type             |   offset_km |   bearing_deg |   area_mean_D_proj_squared_hz2 |   area_mean_accept_probability |   absolute_accept_gain_vs_center |   axis_error_to_v_min_deg |   axis_error_to_v_max_deg |   integration_check_location_difference_km | location_stable_within_one_fine_step   |
|:----------------------------------|----------------:|----------------:|:-------------------------|------------:|--------------:|-------------------------------:|-------------------------------:|---------------------------------:|--------------------------:|--------------------------:|-------------------------------------------:|:---------------------------------------|
| observed_all_accept               |           65686 |           65409 | current_center_C         |       0     |        0      |                    1.61996e+09 |                    2.58323e-06 |                      0           |                 nan       |                 nan       |                                    nan     | True                                   |
| observed_all_accept               |           65686 |           65409 | projected_energy_optimum |     494.106 |      251.565  |                    6.20572e+08 |                    4.19728e-06 |                      1.61404e-06 |                  77.7918  |                  12.2082  |                                      0     | True                                   |
| observed_all_accept               |           65686 |           65409 | verifier_aware_optimum   |     390.625 |      216.87   |                    6.33156e+08 |                    5.54225e-06 |                      2.95902e-06 |                  67.513   |                  22.487   |                                    281.684 | False                                  |
| near_boundary_zero_accept_control |           44714 |           65409 | current_center_C         |       0     |        0      |                    1.75351e+09 |                    1.62581e-06 |                      0           |                 nan       |                 nan       |                                    nan     | True                                   |
| near_boundary_zero_accept_control |           44714 |           65409 | projected_energy_optimum |     485.382 |      326.821  |                    6.93376e+08 |                    7.30824e-07 |                     -8.94986e-07 |                   8.20575 |                  81.7943  |                                      0     | True                                   |
| near_boundary_zero_accept_control |           44714 |           65409 | verifier_aware_optimum   |     444.146 |      230.711  |                    7.27921e+08 |                    0.000127541 |                      0.000125915 |                  87.9051  |                   2.09485 |                                      0     | True                                   |
| deep_reject_control               |           65686 |           65421 | current_center_C         |       0     |        0      |                    2.22344e+09 |                    3.14887e-07 |                      0           |                 nan       |                 nan       |                                    nan     | True                                   |
| deep_reject_control               |           65686 |           65421 | projected_energy_optimum |     346.931 |      324.162  |                    9.47926e+08 |                    3.70239e-07 |                      5.5352e-08  |                  10.1302  |                  79.8698  |                                      0     | True                                   |
| deep_reject_control               |           65686 |           65421 | verifier_aware_optimum   |     247.053 |       71.5651 |                    1.68307e+09 |                    3.35292e-06 |                      3.03803e-06 |                  62.4671  |                  27.5329  |                                     15.625 | True                                   |

`absolute_accept_gain_vs_center`是概率绝对值，即乘100后为百分点。只能称为A2-R类内的最优公共参考点。

- `deep_reject_control`：中心P=3.14887e-07；离散C_acc候选P=3.35292e-06，绝对增益=3.03803e-06（0.000303803个百分点），偏移=247.053 km，位置稳定；C_proj偏移=346.931 km。
- `near_boundary_zero_accept_control`：中心P=1.62581e-06；离散C_acc候选P=0.000127541，绝对增益=0.000125915（0.0125915个百分点），偏移=444.146 km，位置稳定；C_proj偏移=485.382 km。
- `observed_all_accept`：中心P=2.58323e-06；离散C_acc候选P=5.54225e-06，绝对增益=2.95902e-06（0.000295902个百分点），偏移=390.625 km，位置未解析/积分敏感；C_proj偏移=494.106 km。

三个projected-energy候选的位置都通过高阶空间积分复核，但均明显偏离C。这不否定局部解析结论：R_cell=500 km对本次差分Doppler并非“小区域”，一阶线性化不足以控制整个圆盘的平均能量。verifier-aware位置只在`location_stable_within_one_fine_step=true`时解释；不稳定案例不得称为已找到C_acc*。

## 5. 机制对照

| geometry_condition_id             | selection_group                   | point_type   |   candidate_offset_km |   candidate_bearing_deg |   area_mean_D_proj_squared_hz2 |   area_mean_projected_rmse_hz |   area_mean_b_geo_hat_hz |   area_mean_k_geo_hat_hz_per_s |   area_mean_score_gate_probability |   area_mean_b_gate_probability |   area_mean_k_gate_probability |   area_mean_accept_probability |
|:----------------------------------|:----------------------------------|:-------------|----------------------:|------------------------:|-------------------------------:|------------------------------:|-------------------------:|-------------------------------:|-----------------------------------:|-------------------------------:|-------------------------------:|-------------------------------:|
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | C            |                 0     |                  0      |                    1.61996e+09 |                       4180.62 |                 -22179   |                       -566.8   |                        0.000219713 |                    0.00110672  |                    0.000101494 |                    2.58323e-06 |
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | C_proj       |               494.106 |                251.565  |                    6.20572e+08 |                       2680.74 |                 -72223.5 |                       1380.35  |                        0.00020215  |                    0.00785617  |                    8.60614e-05 |                    4.19728e-06 |
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | C_acc        |               390.625 |                216.87   |                    6.33156e+08 |                       2618.73 |                -100305   |                       1552.28  |                        0.00228101  |                    0.00673594  |                    0.000127882 |                    5.54225e-06 |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | C            |                 0     |                  0      |                    1.75351e+09 |                       4285.52 |                 -25384.4 |                       -573.194 |                        0.000289362 |                    0.0013014   |                    1.90349e-06 |                    1.62581e-06 |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | C_proj       |               485.382 |                326.821  |                    6.93376e+08 |                       2801.66 |                  31506.3 |                       -109.155 |                        6.92312e-05 |                    0.0100834   |                    2.88267e-06 |                    7.30824e-07 |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | C_acc        |               444.146 |                230.711  |                    7.27921e+08 |                       2769.95 |                -148705   |                       1636.31  |                        0.00155965  |                    0.000907901 |                    0.000267303 |                    0.000127541 |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_control               | C            |                 0     |                  0      |                    2.22344e+09 |                       4761.85 |                 -31316   |                       -478.267 |                        4.54893e-05 |                    0.0007142   |                    6.90383e-07 |                    3.14887e-07 |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_control               | C_proj       |               346.931 |                324.162  |                    9.47926e+08 |                       3419.62 |                  86441.9 |                         91.99  |                        2.64305e-05 |                    0.000373053 |                    1.7198e-06  |                    3.70239e-07 |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_control               | C_acc        |               247.053 |                 71.5651 |                    1.68307e+09 |                       4759.54 |                  77338.4 |                      -1552.44  |                        1.40741e-05 |                    0.00147325  |                    0.000614273 |                    3.35292e-06 |

C_acc与C_proj是否相同、提升来自score/b/k哪一项，以同一行的区域平均gate概率直接比较；没有构造加权综合指标。

现有三个案例不支持“C_acc稳定沿最低敏感轴”：稳定的boundary C_acc更接近局部高敏感轴，deep C_acc也不沿v_min；high案例位置未解析。局部M只描述C附近的一阶结构，不能预设500 km圆盘上的全局离散最优方向。

## 6. 数值收敛

| geometry_condition_id             | selection_group                   | objective        | main_radial_angular   | check_radial_angular   |   main_optimum_east_km |   main_optimum_north_km |   check_shortlist_optimum_east_km |   check_shortlist_optimum_north_km |   optimum_location_difference_km |   main_value |   check_value |   absolute_value_difference |
|:----------------------------------|:----------------------------------|:-----------------|:----------------------|:-----------------------|-----------------------:|------------------------:|----------------------------------:|-----------------------------------:|---------------------------------:|-------------:|--------------:|----------------------------:|
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | accept           | 3x24                  | 5x32                   |               -234.375 |                -312.5   |                          -468.75  |                            -156.25 |                          281.684 |  5.54225e-06 |   4.98457e-06 |                 5.57678e-07 |
| geometry_7ac7712edd76c5ae96f1671f | observed_all_accept               | projected_energy | 3x24                  | 5x32                   |               -468.75  |                -156.25  |                          -468.75  |                            -156.25 |                            0     |  6.20572e+08 |   6.20559e+08 |             13043.8         |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | accept           | 3x24                  | 5x32                   |               -343.75  |                -281.25  |                          -343.75  |                            -281.25 |                            0     |  0.000127541 |   9.6601e-05  |                 3.09403e-05 |
| geometry_e51710366902774f39f711f3 | near_boundary_zero_accept_control | projected_energy | 3x24                  | 5x32                   |               -265.625 |                 406.25  |                          -265.625 |                             406.25 |                            0     |  6.93376e+08 |   6.93388e+08 |             12730.3         |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_control               | accept           | 3x24                  | 5x32                   |                234.375 |                  78.125 |                           234.375 |                              93.75 |                           15.625 |  3.35292e-06 |   3.494e-06   |                 1.41085e-07 |
| geometry_eb38e83b6c57deb8d05ca302 | deep_reject_control               | projected_energy | 3x24                  | 5x32                   |               -203.125 |                 281.25  |                          -203.125 |                             281.25 |                            0     |  9.47926e+08 |   9.47889e+08 |             36129           |

定位分辨率主要由15.625 km候选网格决定；高阶S积分只在主表top-five shortlist中复核，不能解释为连续全局优化证明。

## 7. 结论边界

- 本轮没有优化任意q(t)，仅优化物理可解释的参考点约束族；
- 三个条件是最小代表性验证，不支持全20-pass总体断言；
- 圆盘uniform-area是受控假设；
- C_acc偏移即使存在，也必须结合pass重复性判断，不能立即升级全量攻击模型；
- 若中心接近最优，则增强A1在对称服务区内的合理性，而不是证明现实攻击者一定选C。

## 8. 正确性审计

| check                                                 | passed   | observed                                                                                                                                                                                                                                                                                                                                                                                                              |
|:------------------------------------------------------|:---------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| three unambiguous pre-existing representative labels  | True     | ['observed_all_accept', 'near_boundary_zero_accept_control', 'deep_reject_control']                                                                                                                                                                                                                                                                                                                                   |
| controlled circular service region unchanged          | True     | R_cell=500.0 km; coverage relative to original C                                                                                                                                                                                                                                                                                                                                                                      |
| center candidate present for every case               | True     | all                                                                                                                                                                                                                                                                                                                                                                                                                   |
| coarse-refine-fine stages present                     | True     | {'coarse': {'geometry_7ac7712edd76c5ae96f1671f': 49, 'geometry_e51710366902774f39f711f3': 49, 'geometry_eb38e83b6c57deb8d05ca302': 49}, 'fine': {'geometry_7ac7712edd76c5ae96f1671f': 39, 'geometry_e51710366902774f39f711f3': 39, 'geometry_eb38e83b6c57deb8d05ca302': 50}, 'refine': {'geometry_7ac7712edd76c5ae96f1671f': 54, 'geometry_e51710366902774f39f711f3': 135, 'geometry_eb38e83b6c57deb8d05ca302': 159}} |
| all candidate reference points inside Omega           | True     | 500.0                                                                                                                                                                                                                                                                                                                                                                                                                 |
| probabilities finite and bounded                      | True     | 5.41412e-08..0.000127541                                                                                                                                                                                                                                                                                                                                                                                              |
| no environment/noise realization generated            | True     | deterministic spatial + semi-analytic probability quadrature                                                                                                                                                                                                                                                                                                                                                          |
| current thresholds reused                             | True     | fixed_geometry current_bk stored thresholds                                                                                                                                                                                                                                                                                                                                                                           |
| batch Doppler equals existing scalar propagation      | True     | 1.83285737875849e-06                                                                                                                                                                                                                                                                                                                                                                                                  |
| verifier-aware convergence status explicitly recorded | True     | stable=2/3; unstable cases retained                                                                                                                                                                                                                                                                                                                                                                                   |
