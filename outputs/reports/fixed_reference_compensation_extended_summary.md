# Fixed-reference compensation extended sensitivity summary

生成时间：2026-06-12 15:47:15

## 1. 实验目的

本轮在 sanity check 通过后，扩展固定参考点补偿模型的位置误差范围，并加入普通相似样本和随机对照样本。所有结果仅来自离线、合成、可复现数学仿真，不接入真实链路，不发射信号，也不代表真实系统结论。

## 2. 上一轮 sanity check 结论

上一轮已确认补偿方向为 `f_geo(B,S) + f_geo(A,S_hat) - f_geo(B,S_hat)`，`e=0 km` 时补偿后曲线接近 `f_geo(A,S)`，`S_hat` 会按 e 和方向正确偏移，且未发现明显 e 曲线复用问题。

## 3. 模型与位置误差范围

- e values：`0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0`
- bearings：`0.0, 90.0, 180.0, 270.0`
- window modes：`full_pass, single_30s_selected, single_60s_selected, spread_3x60s, spread_6x30s, selected_difficult_short_windows`
- strategies：`single_window_baseline, proposed_v1, candidate_v1_1, full_pass`
- compensation modes：`no_compensation`, `fixed_reference_compensation`

## 4. 样本规模

- dataset rows：`24624`
- summary rows：`4104`
- target 数：`4`

样本组规格数：

| sample_group          |   sample_specs |
|:----------------------|---------------:|
| hard_case_weighted    |              6 |
| random_simulated      |              6 |
| typical_orbit_similar |              6 |

## 5. 不同样本组的接受率

proposed v1 + fixed-reference compensation 按 sample group 平均：

| sample_group          |   accept_rate |
|:----------------------|--------------:|
| hard_case_weighted    |     0.396605  |
| random_simulated      |     0.0578704 |
| typical_orbit_similar |     0.27392   |

## 6. 位置误差影响

proposed v1 + fixed-reference compensation 按 e 平均：

|   requested_error_km |   accept_rate |
|---------------------:|--------------:|
|                    0 |      0.439815 |
|                    1 |      0.247685 |
|                    2 |      0.231481 |
|                    5 |      0.273148 |
|                   10 |      0.219907 |
|                   20 |      0.224537 |
|                   50 |      0.199074 |
|                  100 |      0.173611 |
|                  200 |      0.175926 |

## 7. 验证策略对比

fixed-reference compensation 下按 strategy 平均：

| strategy_type          |   accept_rate |
|:-----------------------|--------------:|
| candidate_v1_1         |      0.230453 |
| full_pass              |      0.50463  |
| proposed_v1            |      0.242798 |
| single_window_baseline |      0.578189 |

## 8. no-compensation 对照

proposed v1 下 compensation mode 对比：

| mode                         |   accept_rate |
|:-----------------------------|--------------:|
| fixed_reference_compensation |     0.242798  |
| no_compensation              |     0.0262346 |

## 9. b/k 拟合吸收作用

按 e 的 before/after b/k 中位数：

|   requested_error_km |   before_bk_rmse_median |   after_bk_rmse_median |   bk_absorption_ratio |
|---------------------:|------------------------:|-----------------------:|----------------------:|
|                    0 |             8.40165e-07 |            8.38999e-07 |               1.00139 |
|                    1 |             0.510687    |            0.24632     |               2.07323 |
|                    2 |             1.02139     |            0.492641    |               2.07323 |
|                    5 |             2.55359     |            1.23163     |               2.07322 |
|                   10 |             5.1076      |            2.4634      |               2.07324 |
|                   20 |            10.2171      |            4.92786     |               2.0734  |
|                   50 |            25.5619      |           12.3372      |               2.07485 |
|                  100 |            51.2184      |           24.7973      |               2.08044 |
|                  200 |           103.052       |           50.5655      |               2.15545 |

## 10. 图像输出

- `outputs/figures/fixed_reference_compensation_extended/accept_rate_vs_location_error_by_group.png`
- `outputs/figures/fixed_reference_compensation_extended/accept_rate_vs_location_error_by_strategy.png`
- `outputs/figures/fixed_reference_compensation_extended/before_after_bk_rmse_vs_location_error.png`
- `outputs/figures/fixed_reference_compensation_extended/accept_rate_heatmap_group_by_error_strategy.png`
- `outputs/figures/fixed_reference_compensation_extended/compensation_vs_no_compensation_accept_rate.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_hard_case_weighted_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_hard_case_weighted_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_hard_case_weighted_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_hard_case_weighted_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_hard_case_weighted_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_hard_case_weighted_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_hard_case_weighted_e200km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_hard_case_weighted_e200km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_typical_orbit_similar_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_typical_orbit_similar_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_typical_orbit_similar_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_typical_orbit_similar_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_typical_orbit_similar_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_typical_orbit_similar_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_typical_orbit_similar_e200km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_typical_orbit_similar_e200km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_random_simulated_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_random_simulated_e0km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_random_simulated_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_random_simulated_e20km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_random_simulated_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_random_simulated_e100km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_curves_random_simulated_e200km.png`
- `outputs/figures/fixed_reference_compensation_extended/example_residuals_random_simulated_e200km.png`

## 11. 阶段性结论

本轮只能说明当前离线仿真和固定参考点补偿模型下，非目标模拟卫星曲线对单站 Doppler residual 验证器的压力变化。不能外推为真实系统行为。

如果普通样本组接受率明显低于最难区分样本，则上一轮更接近边界压力测试；如果普通样本也较高，则说明该模型在当前仿真设置下对更广样本也有明显压力。若 50/100/200 km 后接受率下降，说明参考点精度是重要限制；若仍不明显下降，需要继续检查 b/k 拟合、窗口长度、样本选择和频率尺度，并进入多站一致性或更严格窗口一致性分析。

## 12. 本轮问题回答

1. 固定参考点补偿效果是否随位置误差扩大下降：见第 6 节和图表，需按样本组解释。
2. 0-10 km 不下降是否主要因为误差范围过小：本轮扩展到 200 km 用于判断；若趋势只在 50 km 后出现，则 0-10 km 范围确实偏小。
3. 20/50/100/200 km 是否出现边界：见 `fixed_reference_compensation_extended_summary.csv`。
4. 现象是否集中在最难区分样本：见第 5 节。
5. no-compensation 与 fixed-reference compensation 差异：见第 8 节。
6. b/k 拟合吸收多少剩余位置失配：见第 9 节和 `fixed_reference_compensation_bk_absorption.csv`。
7. proposed v1 与 candidate v1.1 哪个更稳：见第 7 节，较低 ACCEPT 且较高 DEFER 的策略更保守。
8. full-pass 是否仍高接受：见 strategy 对比中的 `full_pass`。
9. 是否足以进入下一步：若 sanity 与本轮扩展均稳定，建议进入多站一致性或更严格窗口一致性分析。
10. 不能外推的结论：本轮不是真实链路验证，不证明真实系统一定接受或拒绝，只是离线模型压力测试。
