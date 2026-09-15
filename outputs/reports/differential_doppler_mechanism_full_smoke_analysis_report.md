# 目标卫星—非目标卫星差分多普勒全量机制分析报告

## 1. 目的与冻结口径

本轮把前一轮指标定义扩展到旧正式实验的全部样本，保持 60 秒服务段、segment-local、fixed-site、single-window、原服务中心与验证站、原阈值和原判决。没有新增攻击、handover、多站或尺度扫描。纯几何残差仍为 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。

正式 verifier 指标、无边界纯几何投影、几何容忍预算三类量严格分开。current/wide 正式使用同一无边界 b+kt 拟合；容忍预算 box 只是解释量，不是重新计算的正式 score。

## 2. 样本支持与全量清单

纳入 8 个来源/分组条件实例、6 个物理 `pair_id`。同一真实物理 pair 可能同时带 ordinary/boundary 标签；grouped validation 按物理 `pair_id` 整体留出以防泄漏。

| sample_source      | sample_group       |   pair_instances |
|:-------------------|:-------------------|-----------------:|
| legacy_synthetic   | hard_case_weighted |                2 |
| legacy_synthetic   | original_like      |                2 |
| real_tle_candidate | boundary_case      |                2 |
| real_tle_candidate | ordinary_similar   |                2 |

每个实例保留旧数据实际存在的 4～5 个服务区、全部距离/方向及 no/current/wide；未插值。真实轨道局部正例稀疏，因此置信区间和分来源结果优先于点估计。

## 3. 正确性审计

| check                            | passed   | observed                                                                                                                                                         | tolerance                                                                                                                                                                              | notes                        |
|:---------------------------------|:---------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------------------|
| 全量组合及分组数量               | True     | {"legacy_synthetic|hard_case_weighted": 2, "legacy_synthetic|original_like": 2, "real_tle_candidate|boundary_case": 2, "real_tle_candidate|ordinary_similar": 2} | {('real_tle_candidate', 'ordinary_similar'): 25, ('real_tle_candidate', 'boundary_case'): 25, ('legacy_synthetic', 'original_like'): 6, ('legacy_synthetic', 'hard_case_weighted'): 6} | 62为组条件实例；物理pair另计 |
| d=0距离误差                      | True     | 0.0                                                                                                                                                              | <=1e-6 km                                                                                                                                                                              |                              |
| d=0原始几何残差                  | True     | 1.4978051490007715e-06                                                                                                                                           | <=1e-3 Hz                                                                                                                                                                              |                              |
| no_bk恒等                        | True     | 0                                                                                                                                                                | b=k=0且post=raw                                                                                                                                                                        |                              |
| 无边界拟合RMSE不增               | True     | -6.864577607568716e-10                                                                                                                                           | <=1e-8 Hz                                                                                                                                                                              |                              |
| 容忍预算参数满足box              | True     | 0                                                                                                                                                                | 0 violations                                                                                                                                                                           |                              |
| wide容忍预算残差不高于current    | True     | 0.0                                                                                                                                                              | <=1e-8 Hz                                                                                                                                                                              |                              |
| 正式判决重放一致率               | True     | 1.0                                                                                                                                                              | 100%                                                                                                                                                                                   |                              |
| current/wide正式score相同        | True     | 0.0                                                                                                                                                              | <=1e-9 Hz                                                                                                                                                                              |                              |
| current/wide正式b_hat相同        | True     | 0.0                                                                                                                                                              | <=1e-9 Hz                                                                                                                                                                              |                              |
| current/wide正式k_hat相同        | True     | 0.0                                                                                                                                                              | <=1e-12 Hz/s                                                                                                                                                                           |                              |
| wide正式b/k gate为current超集    | True     | 0                                                                                                                                                                | 0 violations                                                                                                                                                                           |                              |
| 0.5/1/2km有限差分稳定            | True     | 0.002010523359723129                                                                                                                                             | <=15%                                                                                                                                                                                  |                              |
| ENU方向角及km/m                  | True     | 2.106759211528697e-12                                                                                                                                            | 0°北/90°东/顺时针；<=1e-6km                                                                                                                                                            |                              |
| 吸收比例范围                     | True     | 0                                                                                                                                                                | [0,1]浮点容差                                                                                                                                                                          |                              |
| 主键唯一性                       | True     | 0                                                                                                                                                                | 0 duplicate                                                                                                                                                                            |                              |
| grouped validation无物理pair泄漏 | True     | 0                                                                                                                                                                | 0 overlap                                                                                                                                                                              |                              |

判决重放一致率 100.00%。只有全部审计通过时，第 12 节才给出正式停止判断。

## 4. 分组样本外验证方法

局部主分析限定 current_bk、`0<d<=10 km`，d=0 只用于数值审计。leave-one-pair-out 以物理 `pair_id` 留出，防止同一真实轨道对的不同样本标签跨训练/测试；leave-one-target-out 完整留出目标卫星。bootstrap 以物理 pair 为重采样单位，固定 seed，1000 次。合并辅助模型加入 sample_group one-hot；主要证据仍来自分来源/分组模型。

## 5. 局部区域主要 OOF 结果

| stratum        | validation           | model                                                               |     n |   positive_n |   pair_n |   target_n |     roc_auc |   roc_auc_ci_low |   roc_auc_ci_high |        pr_auc |   pr_auc_ci_low |   pr_auc_ci_high |   balanced_accuracy |   brier_score | status               |
|:---------------|:---------------------|:--------------------------------------------------------------------|------:|-------------:|---------:|-----------:|------------:|-----------------:|------------------:|--------------:|----------------:|-----------------:|--------------------:|--------------:|:---------------------|
| real_all       | leave_one_pair_out   | M0_distance                                                         |   384 |            3 |        2 |          1 |   0.695976  |        0.695976  |       0.836842    |   0.015625    |     0.015625    |      0.03125     |            0.5      |    0.00771939 | ok                   |
| real_all       | leave_one_target_out | M0_distance                                                         |   384 |            3 |        2 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| real_all       | leave_one_pair_out   | M4_distance_direction_unbounded_absorption                          |   384 |            3 |        2 |          1 |   0.735346  |        0.584211  |       0.924084    |   0.0341924   |     0.0202381   |      0.0625      |            0.5      |    0.00772677 | ok                   |
| real_all       | leave_one_target_out | M4_distance_direction_unbounded_absorption                          |   384 |            3 |        2 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| real_all       | leave_one_pair_out   | M5_distance_raw_geometry                                            |   384 |            3 |        2 |          1 |   0.85958   |        0.85958   |       0.997382    |   0.186702    |     0.186702    |      0.5         |            0.5      |    0.0076248  | ok                   |
| real_all       | leave_one_target_out | M5_distance_raw_geometry                                            |   384 |            3 |        2 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| real_all       | leave_one_pair_out   | M6_distance_raw_direction_absorption                                |   384 |            3 |        2 |          1 |   0.756343  |        0.615789  |       0.924084    |   0.0347599   |     0.021164    |      0.0625      |            0.5      |    0.00772349 | ok                   |
| real_all       | leave_one_target_out | M6_distance_raw_direction_absorption                                |   384 |            3 |        2 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| controlled_all | leave_one_pair_out   | M0_distance                                                         |   384 |          252 |        4 |          1 |   0.499038  |        0.461957  |       0.733942    |   0.660172    |     0.5965      |      0.915077    |            0.453824 |    0.259046   | ok                   |
| controlled_all | leave_one_target_out | M0_distance                                                         |   384 |          252 |        4 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| controlled_all | leave_one_pair_out   | M4_distance_direction_unbounded_absorption                          |   384 |          252 |        4 |          1 |   0.91808   |        0.800093  |       0.93545     |   0.955299    |     0.865692    |      0.984171    |            0.81241  |    0.107441   | ok                   |
| controlled_all | leave_one_target_out | M4_distance_direction_unbounded_absorption                          |   384 |          252 |        4 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| controlled_all | leave_one_pair_out   | M5_distance_raw_geometry                                            |   384 |          252 |        4 |          1 |   0.940296  |        0.862694  |       0.951445    |   0.967572    |     0.894212    |      0.988187    |            0.821068 |    0.0925096  | ok                   |
| controlled_all | leave_one_target_out | M5_distance_raw_geometry                                            |   384 |          252 |        4 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| controlled_all | leave_one_pair_out   | M6_distance_raw_direction_absorption                                |   384 |          252 |        4 |          1 |   0.909662  |        0.722927  |       0.927013    |   0.946716    |     0.895504    |      0.973511    |            0.819264 |    0.111636   | ok                   |
| controlled_all | leave_one_target_out | M6_distance_raw_direction_absorption                                |   384 |          252 |        4 |          1 | nan         |      nan         |     nan           | nan           |   nan           |    nan           |          nan        |  nan          | insufficient_targets |
| controlled_all | leave_one_pair_out   | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 24940 |        18230 |        4 |          1 |   0.546574  |        0.166641  |       0.584383    |   0.293768    |     0.129452    |      0.396132    |          nan        |  nan          | ok                   |
| controlled_all | leave_one_pair_out   | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 24940 |        18230 |        4 |          1 |  -0.0328201 |       -0.0634038 |       0.000636819 |  -0.0151312   |    -0.0408778   |      0.000208369 |          nan        |  nan          | ok                   |
| real_all       | leave_one_pair_out   | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 36294 |            3 |        2 |          1 |   0.0399135 |       -0.252632  |       0.0890028   |   0.000209497 |    -0.000121916 |      0.000531182 |          nan        |  nan          | ok                   |
| real_all       | leave_one_pair_out   | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 36294 |            3 |        2 |          1 |  -0.102845  |       -0.378947  |      -0.0732964   |  -0.0032709   |    -0.010189    |     -0.0032709   |          nan        |  nan          | ok                   |

重点增量为 M1-M0、M2-M0、M4-M0 与 M6-M5。M7/M8 接近最终判决，只作为上界型对照，不作为新机制宣传。真实轨道与受控样本敏感度量级不同，合并结果仅辅助。

## 6. 方向敏感度与吸收比例的泛化

方向是否优于距离、吸收是否对未知 pair 有效，以各来源 LOPO 的 delta 区间判断，而不是行随机拆分。详细结果见 `differential_doppler_mechanism_full_smoke_grouped_validation.csv`。组内 Spearman、同距离均值/中位数和 pair-cluster effect 区间见 `differential_doppler_mechanism_full_smoke_group_comparison.csv`。

## 7. raw geometry 之外的增量与难例类型

M6-M5 检查控制 raw_geo_rmse 后方向和无边界吸收的增量。二维图把难例分为：原始几何本来小；原始几何不小但主要落在常数/线性趋势；两者共同作用。`unbounded_geometry_post_rmse` 与 formal score 是上界对照，不包装成独立新指标。

## 8. current→wide 正式 gate 机制

共有 126 条 current REJECT→wide ACCEPT：

| formal_gate_release_type   |   count |
|:---------------------------|--------:|
| k gate解除                 |     113 |
| b gate解除                 |       8 |
| b/k同时解除                |       5 |

正式 score/b_hat/k_hat 相等率分别为 100.00%、100.00%、100.00%。正式 gate 解除与纯几何 budget 触边是不同概念；budget 吸收增量和触边变化单列在 transition CSV。

## 9. 全距离受控样本

50～500 km 只使用精确重算的 raw geometry 和吸收量做模型；局部 Jacobian 字段仅是服务区描述，不声称精确预测远距离非线性残差。结果见 grouped validation 中 `scope=full_distance_controlled`。

## 10. 排除中心后的跨服务区重复性

兼容口径保留 d=0；主口径排除 d=0，并以固定距离×方向条件跨服务区接受比例为基础，不做跨区 all-accept。真实/受控来源的组合级相关如下：

| stratum        | metric                                      |   n |   spearman_rho |   spearman_p |   effect_ci_low |   effect_ci_high |
|:---------------|:--------------------------------------------|----:|---------------:|-------------:|----------------:|-----------------:|
| real_all       | mean_actual_direction_sensitivity_local     |   4 |       -0.57735 |      0.42265 |       -1        |        -0.333333 |
| real_all       | mean_weakest_direction_sensitivity          |   4 |        0.57735 |      0.42265 |        0.333333 |         1        |
| real_all       | mean_unbounded_absorption_ratio             |   4 |       -0.57735 |      0.42265 |       -1        |        -0.333333 |
| real_all       | mean_tolerance_budget_absorption_ratio      |   4 |        0.57735 |      0.42265 |        0.333333 |         1        |
| real_all       | service_area_direction_sensitivity_variance |   4 |        0.57735 |      0.42265 |        0.333333 |         1        |
| real_all       | service_area_unbounded_absorption_variance  |   4 |        0.57735 |      0.42265 |        0.333333 |         1        |
| real_all       | service_area_tolerance_absorption_variance  |   4 |       -0.57735 |      0.42265 |       -1        |        -0.333333 |
| controlled_all | mean_actual_direction_sensitivity_local     |   4 |       -1       |      0       |       -1        |        -1        |
| controlled_all | mean_weakest_direction_sensitivity          |   4 |       -0.8     |      0.2     |       -1        |         0.7      |
| controlled_all | mean_unbounded_absorption_ratio             |   4 |       -0.8     |      0.2     |       -1        |         0.733333 |
| controlled_all | mean_tolerance_budget_absorption_ratio      |   4 |        1       |      0       |        1        |         1        |
| controlled_all | service_area_direction_sensitivity_variance |   4 |        0       |      1       |       -1        |         1        |
| controlled_all | service_area_unbounded_absorption_variance  |   4 |        1       |      0       |        1        |         1        |
| controlled_all | service_area_tolerance_absorption_variance  |   4 |       -1       |      0       |       -1        |        -1        |

局部方向敏感度只在 `0<d<=10 km` 用于主结论；远距离重复性主要看 raw geometry 与吸收指标。

## 11. 图表

生成 10 张图：direction_sensitivity_by_group.png, unbounded_absorption_by_group.png, same_distance_direction_decision.png, raw_geometry_absorption_hard_cases.png, grouped_oof_roc_pr.png, grouped_model_comparison.png, current_to_wide_gate_release.png, noncenter_cross_area_heatmap.png, repeatability_vs_absorption.png, repeatability_vs_direction.png。

## 12. 最终判断

**建议进入正式理论化阶段**。

该判断依次检查：分来源 LOPO 相对 distance-only 的组合级区间、M6-M5 或可区分难例机制、current/wide 正式拟合不变、排除中心后的组合级重复性，以及结果是否只是 post-RMSE 的重述。

## 13. 局限

- 真实轨道 ACCEPT 极少，部分单独 target 折没有正例；pooled OOF 可计算，但单折 AUC 不可定义。
- 只有 5 个真实目标卫星，leave-one-target-out 区间仍有限。
- 受控 original_like 只有 1 个目标，无法单独做有意义的 leave-one-target-out。
- 本分析不证明统一安全距离、真实 Starlink 频偏真值或局部 Jacobian 的远距离外推能力。
