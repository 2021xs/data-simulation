# Fixed-reference compensation sanity report

生成时间：2026-06-12 15:25:55

## 1. 为什么做核查

上一轮固定参考点补偿位置误差敏感性实验给出了较高 ACCEPT 率。由于上一轮运行过程中多次被安全检查中断，本轮只做离线、合成、学术仿真的 mathematical simulation sanity check，核查公式方向、`S_hat` 位置偏移、no-compensation 对照、补偿误差随 e 的变化，以及上一轮 dataset 一致性。

## 2. 正确公式

固定参考点补偿的定义是让模拟卫星 B 在参考点 `S_hat` 上看起来像目标卫星 A：

`u_Shat(t) = f_geo(A, S_hat, t) - f_geo(B, S_hat, t)`

真实站 S 接收的补偿后曲线为：

`f_comp(t) = f_geo(B, S, t) + f_geo(A, S_hat, t) - f_geo(B, S_hat, t)`

验证器比较 `f_comp(t) - f_geo(A, S, t)`。

## 3. 最小 sanity case

- target：`44714 / STARLINK-1008`
- attack type：`same_plane_altitude_offset`
- attack param：`delta_h_km = -1.0`

east bearing 下的核心统计：

|   e_km |   actual_distance_km |   raw_delta_rmse_hz |   comp_delta_rmse_before_bk_hz |   comp_delta_rmse_after_bk_hz |     b_hat_hz |   k_hat_hz_per_s |   residual_score_hz |   improvement_ratio |
|-------:|---------------------:|--------------------:|-------------------------------:|------------------------------:|-------------:|-----------------:|--------------------:|--------------------:|
|      0 |                    0 |             88.0103 |                    8.40165e-07 |                   8.38999e-07 |  4.27018e-08 |      1.49825e-10 |         8.38999e-07 |         1.04754e+08 |
|      1 |                    1 |             88.0103 |                    0.0385357   |                   0.0141241   | -0.00458189  |      0.000459643 |         0.0141241   |      2283.87        |
|      5 |                    5 |             88.0103 |                    0.193       |                   0.0705628   | -0.023167    |      0.00230259  |         0.0705628   |       456.012       |
|     10 |                   10 |             88.0103 |                    0.386801    |                   0.140981    | -0.0469803   |      0.00461604  |         0.140981    |       227.534       |

## 4. e = 0 km sanity check

`e=0` 时 `S_hat=S`，因此正确方向的 `f_comp` 应退化为 `f_geo(A,S)`。本轮最大 `comp_delta_rmse_before_bk_hz` 为 `8.40165e-07` Hz；反向公式在 `e=0` 的最小 RMSE 为 `176.021` Hz。

结论：补偿公式方向正确，e=0 退化符合预期。

## 5. S_hat 位置偏移核查

本轮测试 bearings：`0.0, 90.0, 180.0, 270.0`，e values：`0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0`。设置距离与实际 haversine 距离的最大偏差为 `8.45546e-13` km。

结论：S_hat 随 e 和 bearing 正确改变。

## 6. no-compensation baseline

`raw_delta_rmse_hz` 是未补偿 B 相对 A 的差异；`comp_delta_rmse_before_bk_hz` 是补偿后未做 b/k 拟合前的差异。`e=0` 时 improvement ratio 应非常大，表示补偿确实生效。随 e 增大，补偿误差出现可观测变化；同时 `comp_delta_rmse_after_bk_hz` 明显小于 before-bk，说明 b/k 拟合会吸收一部分位置失配。

## 7. 补偿误差随 e 的变化

east bearing 下 `e=0` 到 `e=100 km` 的 residual score 变化为 `1.38397` Hz。本轮不要求严格单调，因为过境几何和方向会影响曲线形状；但如果只看 0-10 km，小范围内变化可能被 b/k 拟合和 hard-case 选择掩盖。因此上一轮 0-10 km ACCEPT 率不明显下降，可能是模型现象，也可能与 hard-case 加权和阈值/拟合吸收有关，并非直接说明位置误差完全无影响。

## 8. 曲线图

- `outputs/figures/fixed_reference_compensation_sanity/sanity_curves_e0km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_residuals_e0km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_curves_e10km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_residuals_e10km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_curves_e50km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_residuals_e50km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_curves_e100km.png`
- `outputs/figures/fixed_reference_compensation_sanity/sanity_residuals_e100km.png`

## 9. 上一轮 dataset 一致性检查

| check_name                             | status   | severity   | detail                                                                                                                                                                                                                                                                                                                                                                                  |
|:---------------------------------------|:---------|:-----------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| rows_per_e_consistent                  | PASS     | info       | [{'e_km': 0.0, 'n': 1444}, {'e_km': 0.5, 'n': 1444}, {'e_km': 1.0, 'n': 1444}, {'e_km': 2.0, 'n': 1444}, {'e_km': 5.0, 'n': 1444}, {'e_km': 10.0, 'n': 1444}]                                                                                                                                                                                                                           |
| S_hat_coordinates_recorded             | WARN     | warning    | previous dataset does not record S_hat coordinates; cannot directly check coordinate variation                                                                                                                                                                                                                                                                                          |
| identical_score_across_e               | PASS     | info       | groups=205, identical_mean_score_groups=0, ratio=0.0000                                                                                                                                                                                                                                                                                                                                 |
| proposed_v1_accept_by_e                | PASS     | info       | [{'e_km': 0.0, 'proposed_v1_accept_rate': 0.4276315789473684}, {'e_km': 0.5, 'proposed_v1_accept_rate': 0.4342105263157895}, {'e_km': 1.0, 'proposed_v1_accept_rate': 0.4144736842105263}, {'e_km': 2.0, 'proposed_v1_accept_rate': 0.43859649122807015}, {'e_km': 5.0, 'proposed_v1_accept_rate': 0.4780701754385965}, {'e_km': 10.0, 'proposed_v1_accept_rate': 0.44298245614035087}] |
| full_pass_high_across_all_e            | PASS     | info       | [{'e_km': 0.0, 'full_pass_accept_rate': 0.8552631578947368}, {'e_km': 0.5, 'full_pass_accept_rate': 0.9342105263157895}, {'e_km': 1.0, 'full_pass_accept_rate': 0.881578947368421}, {'e_km': 2.0, 'full_pass_accept_rate': 0.9342105263157895}, {'e_km': 5.0, 'full_pass_accept_rate': 0.9078947368421053}, {'e_km': 10.0, 'full_pass_accept_rate': 0.9210526315789473}]                |
| attack_type_coverage                   | PASS     | info       | {'same_plane_altitude_offset': 5928, 'inclination_offset': 2736}                                                                                                                                                                                                                                                                                                                        |
| ordinary_sample_contrast               | WARN     | warning    | dataset appears hard-case weighted and lacks ordinary sample contrast                                                                                                                                                                                                                                                                                                                   |
| summary_matches_dataset_subset         | PASS     | info       | matched_groups=798, max_n_diff=0, max_accept_count_diff=0                                                                                                                                                                                                                                                                                                                               |
| previous_script_formula_direction      | PASS     | info       | uses f_B(S)+f_A(S_hat)-f_B(S_hat)                                                                                                                                                                                                                                                                                                                                                       |
| previous_script_duplicate_write_report | WARN     | warning    | definitions=2                                                                                                                                                                                                                                                                                                                                                                           |
| previous_script_duplicate_append_log   | WARN     | warning    | definitions=2                                                                                                                                                                                                                                                                                                                                                                           |
| previous_script_sha256                 | PASS     | info       | d99c6ed4a37960f51c9eb0ce14adabb89064d9ae0a7f39c14f700585b7265b49                                                                                                                                                                                                                                                                                                                        |

## 10. 最终回答

1. 上一轮补偿公式方向是否正确：若以上源码检查与 `e=0` 退化均成立，则方向正确；本轮核查结果为 `正确`。
2. `e=0 km` 时补偿后曲线是否接近目标曲线：`comp_delta_rmse_before_bk_hz` 最大 `8.40165e-07` Hz，接近数值零。
3. `S_hat` 是否真的按 e 改变：最大距离误差 `8.45546e-13` km，有效。
4. 不同 e 是否重新计算补偿量：sanity metrics 中 `u_shat`、RMSE 与位置坐标随 e/bearing 变化；dataset 中未发现大比例完全相同 score 的 e 复用迹象时可认为重新计算有效。
5. 0-10 km 下接受率不下降是否可能因为位置误差范围太小：可能。最小复现显示 0-100 km 才更容易观察到失配趋势，0-10 km 可能被 b/k 拟合和窗口选择削弱。
6. b/k 拟合是否吸收了大部分位置误差：是，`comp_delta_rmse_after_bk_hz` 通常显著低于 before-bk，应在主动补偿评估中单独报告 before/after b/k。
7. 上一轮结果是否可信：`通过`。它可作为 hard-case pressure test 初步结果，但不应作为最终安全边界。
8. 如果可信，下一轮是否扩大到 20/50/100/200 km 并加入普通样本对照：建议扩大，并加入普通样本、不同 bearing、不同窗口组合和 before/after b/k 指标。
9. 如果不可信，需要修复哪部分并重跑：若公式或 S_hat 检查失败，应修复公式方向或位置生成；若 dataset consistency 出现缓存复用，应修复 e 循环内曲线重算与输出字段。

## 11. 分情况结论

- 情况 A：若公式、e=0、S_hat、dataset consistency 均通过，则上一轮可作为强压力测试初步结果。
- 情况 B：若公式方向错误，则上一轮结果不能直接作为结论，需要修正后重跑。
- 情况 C：若 e 未生效或缓存复用，则上一轮位置误差敏感性结果不可信，需要修复 S_hat 生成或缓存逻辑后重跑。
