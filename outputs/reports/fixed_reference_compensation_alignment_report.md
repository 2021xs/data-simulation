# Fixed-reference compensation alignment report

生成时间：2026-06-12 15:57:23

## 1. 复核目的

早期固定参考点补偿实验曾观察到参考点偏差约 50 km 后当前样本基本全部拒绝；最新扩展实验中，在 50/100/200 km 下仍有一定 ACCEPT。表面上这两个结果冲突。本轮只做离线一致性复核，检查差异是否来自样本、窗口、验证器、阈值、b/k 拟合、方向或统计口径变化。

## 2. 早期文件可用性

| file                                                         | found   |
|:-------------------------------------------------------------|:--------|
| outputs/datasets/active_compensation_first_pass_dataset.csv  | True    |
| outputs/metrics/active_compensation_first_pass_summary.csv   | True    |
| outputs/datasets/fixed_point_active_compensation_dataset.csv | True    |
| outputs/metrics/fixed_point_active_compensation_summary.csv  | True    |
| outputs/reports/fixed_point_active_compensation_summary.md   | True    |

## 3. 200 km ACCEPT 来源：样本组

| sample_group          |   requested_error_km |   n |   accept_rate |   defer_rate |   reject_rate |   score_median |   score_p95 |   abs_b_hat_median |   abs_k_hat_median |
|:----------------------|---------------------:|----:|--------------:|-------------:|--------------:|---------------:|------------:|-------------------:|-------------------:|
| hard_case_weighted    |                  200 | 216 |      0.490741 |     0.402778 |      0.106481 |        27.5049 |      34.632 |            3460.07 |           0.662369 |
| typical_orbit_similar |                  200 | 216 |      0.138889 |     0.12963  |      0.731481 |        30.6471 |    3699.19  |            3582.39 |           1.3796   |
| random_simulated      |                  200 | 216 |      0        |     0        |      1        |       243.976  |    9812.71  |           23669.4  |         122.534    |

## 4. 50/100/200 km 窗口模式差异

|   requested_error_km | window_mode                      |   n |   accept_rate |   defer_rate |   reject_rate |   score_median |   score_p95 |   abs_b_hat_median |   abs_k_hat_median |
|---------------------:|:---------------------------------|----:|--------------:|-------------:|--------------:|---------------:|------------:|-------------------:|-------------------:|
|                   50 | full_pass                        | 216 |      0.472222 |    0.0138889 |      0.513889 |        31.1046 |   2302.44   |            3512.51 |            1.09629 |
|                   50 | selected_difficult_short_windows | 144 |      0.173611 |    0.298611  |      0.527778 |        30.8052 |     50.1964 |            3460.35 |            1.03262 |
|                   50 | single_60s_selected              | 144 |      0        |    0.541667  |      0.458333 |        27.0424 |     33.5129 |            3449.15 |            1.09116 |
|                   50 | spread_3x60s                     | 144 |      0.263889 |    0.236111  |      0.5      |        30.6975 |     85.9361 |            3568.26 |            1.22278 |
|                  100 | full_pass                        | 216 |      0.361111 |    0.0138889 |      0.625    |        38.5223 |   4509.11   |            3575.88 |            1.10066 |
|                  100 | selected_difficult_short_windows | 144 |      0.201389 |    0.215278  |      0.583333 |        32.9455 |     93.3527 |            3517.31 |            1.15423 |
|                  100 | single_60s_selected              | 144 |      0        |    0.541667  |      0.458333 |        29.5731 |     36.9114 |            3523.55 |            1.27781 |
|                  100 | spread_3x60s                     | 144 |      0.25     |    0.180556  |      0.569444 |        31.3231 |    161.494  |            3580.8  |            1.19924 |
|                  200 | full_pass                        | 216 |      0.347222 |    0.0277778 |      0.625    |        57.4956 |   9812.71   |            3645.16 |            1.29642 |
|                  200 | selected_difficult_short_windows | 144 |      0.159722 |    0.229167  |      0.611111 |        31.9575 |    166.576  |            3650.69 |            1.28567 |
|                  200 | single_60s_selected              | 144 |      0        |    0.402778  |      0.597222 |        31.9494 |     56.7978 |            3642.1  |            1.8965  |
|                  200 | spread_3x60s                     | 144 |      0.263889 |    0.125     |      0.611111 |        31.2474 |    320.407  |            3671.29 |            1.55915 |

## 5. 验证器策略差异

|   requested_error_km | strategy_type   |   n |   accept_rate |   defer_rate |   reject_rate |   score_median |   score_p95 |   abs_b_hat_median |   abs_k_hat_median |
|---------------------:|:----------------|----:|--------------:|-------------:|--------------:|---------------:|------------:|-------------------:|-------------------:|
|                   50 | candidate_v1_1  | 288 |      0.225694 |    0.274306  |      0.5      |        29.7695 |     1161.01 |            3512.3  |            1.09495 |
|                   50 | full_pass       |  72 |      0.472222 |    0.0138889 |      0.513889 |        31.1046 |     2226.74 |            3512.51 |            1.09629 |
|                   50 | proposed_v1     | 288 |      0.229167 |    0.270833  |      0.5      |        29.7695 |     1161.01 |            3512.3  |            1.09495 |
|                  100 | candidate_v1_1  | 288 |      0.201389 |    0.239583  |      0.559028 |        31.3503 |     2441.62 |            3537.23 |            1.16862 |
|                  100 | full_pass       |  72 |      0.361111 |    0.0138889 |      0.625    |        38.5223 |     4460.49 |            3575.88 |            1.10066 |
|                  100 | proposed_v1     | 288 |      0.204861 |    0.236111  |      0.559028 |        31.3503 |     2441.62 |            3537.23 |            1.16862 |
|                  200 | candidate_v1_1  | 288 |      0.1875   |    0.201389  |      0.611111 |        32.9468 |     5381.1  |            3655.04 |            1.38332 |
|                  200 | full_pass       |  72 |      0.347222 |    0.0277778 |      0.625    |        57.4956 |     8875.82 |            3645.16 |            1.29642 |
|                  200 | proposed_v1     | 288 |      0.197917 |    0.190972  |      0.611111 |        32.9468 |     5381.1  |            3655.04 |            1.38332 |

## 6. b/k 与阈值口径检查

dataset 中包含 normalized score 和 gate pass 布尔值，但不包含原始 score/b/k threshold 数值。以下表格用 gate pass rate、residual score、b/k 分布做间接检查：

|   requested_error_km | final_decision   |   n |   comp_delta_rmse_before_bk_median |   comp_delta_rmse_after_bk_median |   b_hat_median |   abs_b_hat_p95 |   k_hat_median |   abs_k_hat_p95 |   residual_score_median |   residual_score_p95 |   normalized_residual_score_median |   score_gate_pass_rate |   b_gate_pass_rate |   k_gate_pass_rate | threshold_note                                                                          |
|---------------------:|:-----------------|----:|-----------------------------------:|----------------------------------:|---------------:|----------------:|---------------:|----------------:|------------------------:|---------------------:|-----------------------------------:|-----------------------:|-------------------:|-------------------:|:----------------------------------------------------------------------------------------|
|                   50 | ACCEPT           |  86 |                            3.86858 |                           2.27969 |        3516    |         3661.3  |      -0.607507 |         1.06769 |                 26.321  |              30.5412 |                           0.808007 |               1        |          1         |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                   50 | DEFER            | 134 |                            4.03656 |                           2.29495 |        3441.19 |         3706.29 |      -0.59864  |         1.44808 |                 26.908  |              32.3178 |                           0.790691 |               0.940299 |          0.985075  |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                   50 | REJECT           | 212 |                         6022.58    |                        1092.3     |        3481.3  |        10939    |      -0.985276 |        53.9686  |                 33.4968 |            1204.78   |                          20.4057   |               0.349057 |          0.0896226 |          0.0330189 | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  100 | ACCEPT           |  75 |                            7.38983 |                           3.80129 |        3359.67 |         3621.78 |      -0.692657 |         1.05779 |                 26.3647 |              30.9743 |                           0.827532 |               1        |          1         |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  100 | DEFER            | 124 |                            7.6312  |                           4.61229 |        3343.2  |         3712.45 |      -0.714355 |         1.42496 |                 28.1165 |              33.3924 |                           0.83995  |               0.879032 |          1         |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  100 | REJECT           | 233 |                        11200.4     |                        2073.1     |        3462.51 |        18342.2  |      -0.768616 |       109.725   |                 38.574  |            2478.18   |                          28.2208   |               0.291845 |          0.16309   |          0.0772532 | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  200 | ACCEPT           |  76 |                           13.9341  |                           8.53216 |        3451.3  |         3685.99 |      -0.538239 |         1.02042 |                 25.8979 |              30.8938 |                           0.822702 |               1        |          1         |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  200 | DEFER            | 103 |                           14.9929  |                           8.97562 |        3472.04 |         3745.13 |      -0.765077 |         1.75581 |                 27.116  |              33.8208 |                           0.820685 |               0.902913 |          0.970874  |          1         | dataset stores normalized score and gate booleans; raw threshold values are not present |
|                  200 | REJECT           | 253 |                        21737.7     |                        3702.49    |        3529.75 |        33678.9  |      -0.564635 |       229.355   |                 55.3877 |            5388.54   |                          35.7173   |               0.233202 |          0.193676  |          0.0711462 | dataset stores normalized score and gate booleans; raw threshold values are not present |

## 7. row-level 与 case-level 统计

| sample_group          |   requested_error_km | strategy_type   |   row_level_accept_rate |   case_any_accept_rate |   case_all_accept_rate |   case_main_window_only_accept_rate |   n_rows |   n_cases |
|:----------------------|---------------------:|:----------------|------------------------:|-----------------------:|-----------------------:|------------------------------------:|---------:|----------:|
| hard_case_weighted    |                   50 | proposed_v1     |                0.444444 |               0.958333 |                      0 |                            0.958333 |      144 |        24 |
| hard_case_weighted    |                  100 | proposed_v1     |                0.381944 |               0.875    |                      0 |                            0.833333 |      144 |        24 |
| hard_case_weighted    |                  200 | proposed_v1     |                0.423611 |               0.833333 |                      0 |                            0.791667 |      144 |        24 |
| random_simulated      |                   50 | proposed_v1     |                0        |               0        |                      0 |                            0        |      144 |        24 |
| random_simulated      |                  100 | proposed_v1     |                0        |               0        |                      0 |                            0        |      144 |        24 |
| random_simulated      |                  200 | proposed_v1     |                0        |               0        |                      0 |                            0        |      144 |        24 |
| typical_orbit_similar |                   50 | proposed_v1     |                0.152778 |               0.458333 |                      0 |                            0.458333 |      144 |        24 |
| typical_orbit_similar |                  100 | proposed_v1     |                0.138889 |               0.333333 |                      0 |                            0.25     |      144 |        24 |
| typical_orbit_similar |                  200 | proposed_v1     |                0.104167 |               0.25     |                      0 |                            0.25     |      144 |        24 |

## 8. early-style full-pass 对齐

若找不到早期完整输出，本轮用当前 dataset 重建 early-style 口径：普通/随机样本、full_pass、full_pass/proposed_v1、e=0/50/100/200。

| sample_group          |   requested_error_km | strategy_type   |   n |   accept_rate |   defer_rate |   reject_rate |   score_median |   score_p95 |   abs_b_hat_median |   abs_k_hat_median |
|:----------------------|---------------------:|:----------------|----:|--------------:|-------------:|--------------:|---------------:|------------:|-------------------:|-------------------:|
| random_simulated      |                    0 | full_pass       |  24 |      0.958333 |    0.0416667 |      0        |        28.4004 |     32.4089 |            3453.24 |           0.538276 |
| random_simulated      |                    0 | proposed_v1     |  24 |      0.958333 |    0.0416667 |      0        |        28.4004 |     32.4089 |            3453.24 |           0.538276 |
| random_simulated      |                   50 | full_pass       |  24 |      0        |    0         |      1        |      1183.82   |   2458.99   |            5851.05 |          25.048    |
| random_simulated      |                   50 | proposed_v1     |  24 |      0        |    0         |      1        |      1183.82   |   2458.99   |            5851.05 |          25.048    |
| random_simulated      |                  100 | full_pass       |  24 |      0        |    0         |      1        |      2486.06   |   5058.84   |           11551.9  |          49.6295   |
| random_simulated      |                  100 | proposed_v1     |  24 |      0        |    0         |      1        |      2486.06   |   5058.84   |           11551.9  |          49.6295   |
| random_simulated      |                  200 | full_pass       |  24 |      0        |    0         |      1        |      5462.26   |  10842.4    |           23022.4  |          98.1659   |
| random_simulated      |                  200 | proposed_v1     |  24 |      0        |    0         |      1        |      5462.26   |  10842.4    |           23022.4  |          98.1659   |
| typical_orbit_similar |                    0 | full_pass       |  24 |      0.875    |    0         |      0.125    |        28.2839 |     32.611  |            3540.97 |           0.559871 |
| typical_orbit_similar |                    0 | proposed_v1     |  24 |      0.875    |    0         |      0.125    |        28.2839 |     32.611  |            3540.97 |           0.559871 |
| typical_orbit_similar |                   50 | full_pass       |  24 |      0.458333 |    0         |      0.541667 |        30.2548 |   1059.36   |            3332.22 |           0.964738 |
| typical_orbit_similar |                   50 | proposed_v1     |  24 |      0.458333 |    0         |      0.541667 |        30.2548 |   1059.36   |            3332.22 |           0.964738 |
| typical_orbit_similar |                  100 | full_pass       |  24 |      0.25     |    0         |      0.75     |        38.5223 |   2148.84   |            3458.08 |           0.907631 |
| typical_orbit_similar |                  100 | proposed_v1     |  24 |      0.25     |    0         |      0.75     |        38.5223 |   2148.84   |            3458.08 |           0.907631 |
| typical_orbit_similar |                  200 | full_pass       |  24 |      0.25     |    0         |      0.75     |        57.4956 |   4392.23   |            3563.74 |           1.29642  |
| typical_orbit_similar |                  200 | proposed_v1     |  24 |      0.25     |    0         |      0.75     |        57.4956 |   4392.23   |            3563.74 |           1.29642  |

## 9. 最小同条件重算

| comparison_note                                                                                           |   n |   decision_match_rate |   comp_delta_after_bk_abs_diff_median |
|:----------------------------------------------------------------------------------------------------------|----:|----------------------:|--------------------------------------:|
| clean-geometry recomputation; dataset residual_score includes empirical residual/noise not stored per row | 144 |              0.479167 |                                     0 |

注意：extended dataset 未保存每行 empirical residual/noise，因此 `residual_score` 不能逐 Hz 精确重算。几何基线 `comp_delta_rmse_after_bk` 可用 clean geometry 对齐；decision mismatch 不应单独解释为缓存错误。

## 10. 图像输出

- `outputs/figures/fixed_reference_compensation_alignment/accept_rate_by_group_at_large_error.png`
- `outputs/figures/fixed_reference_compensation_alignment/accept_rate_by_window_at_large_error.png`
- `outputs/figures/fixed_reference_compensation_alignment/row_vs_case_accept_rate.png`
- `outputs/figures/fixed_reference_compensation_alignment/accepted_vs_rejected_residual_at_200km.png`
- `outputs/figures/fixed_reference_compensation_alignment/accepted_vs_rejected_bk_at_200km.png`
- `outputs/figures/fixed_reference_compensation_alignment/early_style_vs_extended_accept_rate.png`

## 11. 最终判断

1. 早期 50 km 后基本失效与最新 200 km 仍有接受率是否真的矛盾：不必然矛盾。最新实验引入 hard-case 加权、多窗口展开和 window-aware 策略，统计口径与早期 full-pass/普通样本口径不同。
2. 差异主要来自哪里：优先看第 3、4、7 节。如果 200 km ACCEPT 主要集中在 hard-case 或特定短窗口，则主要是样本/窗口差异；如果 row-level 高于 case-level，则统计展开也有贡献。
3. 最新 200 km 接受率主要由哪些样本组贡献：见第 3 节。
4. 最新 200 km 接受率主要由哪些窗口模式贡献：见第 4 节。
5. row-level 是否放大接受率：见第 7 节。`any_accept` 通常高于 row-level，`all_accept` 通常低于 row-level；主结果应明确选择统计口径。
6. case-level 后接受率是否下降：看 `case_all_accept_rate` 或 `case_main_window_only_accept_rate` 是否低于 row-level。
7. 200 km ACCEPT 样本 residual 和 b/k 是否合理：见第 6 节。ACCEPT 样本 residual/gate pass 较好时，说明 after-b/k 确实进入接受域；若 b/k 较大但仍 gate pass，则提示 gate 边界需复核。
8. 是否存在阈值过宽或 b/k 吸收过强：dataset 缺少原始阈值，不能最终断言阈值过宽；但 b/k 吸收在扩展实验中明确存在，应在后续做 no-bk/weak-bk/strong-bk 消融。
9. 同条件重算是否复现 dataset：clean geometry 可复核几何指标；随机 residual 层无法精确复现，需要下一轮保存 injected residual terms 或 sequence-level seed。
10. 是否需要修复脚本后重跑：未发现必须修复后才能解释结果的证据；建议保留最新结果，但改写解释口径为 hard-case 加权压力测试，并补充 case-level 主统计和阈值字段。
