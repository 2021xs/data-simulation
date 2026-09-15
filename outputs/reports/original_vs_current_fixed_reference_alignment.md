# Original vs current fixed-reference alignment

生成时间：2026-06-12 16:20:16

## 1. 为什么复现原版 50 km 结论

早期固定参考点补偿实验曾观察到约 50 km 后基本全部拒绝，而最新扩展实验中 hard-case 样本在 50/100/200 km 仍有接受率。本轮目标是找回或重建原版口径，并在同一样本下并排输出 original_style 与 current_extended_style。

## 2. 原版脚本和输出查找

| path                                                             | exists   |     size | mtime                      |
|:-----------------------------------------------------------------|:---------|---------:|:---------------------------|
| scripts/run_active_compensation_attack_first_pass.py             | True     |    50383 | 2026-06-09T14:34:54.844780 |
| scripts/run_fixed_point_active_compensation_sensitivity.py       | True     |    41446 | 2026-06-12T13:31:24.750476 |
| scripts/run_fixed_reference_compensation_extended_sensitivity.py | True     |    53849 | 2026-06-12T15:37:38.520603 |
| outputs/datasets/active_compensation_first_pass_dataset.csv      | True     | 91710857 | 2026-06-04T23:35:43.079566 |
| outputs/metrics/active_compensation_first_pass_summary.csv       | True     |     1531 | 2026-06-04T23:35:40.385627 |
| outputs/datasets/fixed_point_active_compensation_dataset.csv     | True     |  3304208 | 2026-06-12T13:27:30.545856 |
| outputs/metrics/fixed_point_active_compensation_summary.csv      | True     |   112470 | 2026-06-12T13:27:31.895143 |
| outputs/reports/fixed_point_active_compensation_summary.md       | True     |    10071 | 2026-06-12T13:56:19.050658 |
| logs/work_log.md                                                 | True     |   241829 | 2026-06-12T16:14:24.576891 |

如果没有可直接恢复的完整原版命令，本轮将 `original_style` 重建为：full-pass/sequence-level、强 score+b/k gate、普通 original_like 样本为主、不使用多窗口累计、不使用 selected difficult windows。

## 3. original_style 在 50 km 下结果

| sample_group       |   accept_rate |
|:-------------------|--------------:|
| hard_case_weighted |      0.958333 |
| original_like      |      0.375    |
| random_simulated   |      0        |

## 4. current_extended_style 在 200 km 下结果

| sample_group       |   accept_rate |
|:-------------------|--------------:|
| hard_case_weighted |     0.458333  |
| original_like      |     0.0833333 |
| random_simulated   |     0         |

## 5. b/k 消融

| style_type             |   requested_error_km |   no_bk_accept_rate |   weak_bk_accept_rate |   current_bk_accept_rate |   delta_current_bk_vs_no_bk |
|:-----------------------|---------------------:|--------------------:|----------------------:|-------------------------:|----------------------------:|
| current_extended_style |                    0 |                   0 |              0.861111 |                0.611111  |                   0.611111  |
| current_extended_style |                   50 |                   0 |              0.527778 |                0.416667  |                   0.416667  |
| current_extended_style |                  100 |                   0 |              0.472222 |                0.333333  |                   0.333333  |
| current_extended_style |                  200 |                   0 |              0.416667 |                0.166667  |                   0.166667  |
| current_extended_style |                  500 |                   0 |              0.25     |                0.138889  |                   0.138889  |
| current_extended_style |                 1000 |                   0 |              0.138889 |                0         |                   0         |
| current_extended_style |                 2000 |                   0 |              0.111111 |                0.0277778 |                   0.0277778 |
| original_style         |                    0 |                   0 |              0.833333 |                0.833333  |                   0.833333  |
| original_style         |                   50 |                   0 |              0.5      |                0.5       |                   0.5       |
| original_style         |                  100 |                   0 |              0.388889 |                0.388889  |                   0.388889  |
| original_style         |                  200 |                   0 |              0.333333 |                0.333333  |                   0.333333  |
| original_style         |                  500 |                   0 |              0.111111 |                0.111111  |                   0.111111  |
| original_style         |                 1000 |                   0 |              0        |                0         |                   0         |
| original_style         |                 2000 |                   0 |              0        |                0         |                   0         |

## 6. original vs current 对齐摘要

| sample_group       |   requested_error_km | window_mode   | bk_mode    |   original_accept_rate |   current_accept_rate |   delta_current_minus_original |   original_reject_rate |   current_reject_rate |   decision_match_rate |   original_accept_current_reject_count |   original_reject_current_accept_count |
|:-------------------|---------------------:|:--------------|:-----------|-----------------------:|----------------------:|-------------------------------:|-----------------------:|----------------------:|----------------------:|---------------------------------------:|---------------------------------------:|
| hard_case_weighted |                    0 | full_pass     | current_bk |              0.5625    |             0.5625    |                              0 |               0.4375   |              0.4375   |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                    0 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                    0 | full_pass     | weak_bk    |              0.5625    |             0.5625    |                              0 |               0.4375   |              0.4375   |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                   50 | full_pass     | current_bk |              0.5625    |             0.5625    |                              0 |               0.4375   |              0.4375   |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                   50 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                   50 | full_pass     | weak_bk    |              0.5625    |             0.5625    |                              0 |               0.4375   |              0.4375   |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  100 | full_pass     | current_bk |              0.5       |             0.5       |                              0 |               0.5      |              0.5      |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  100 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  100 | full_pass     | weak_bk    |              0.5       |             0.5       |                              0 |               0.5      |              0.5      |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  200 | full_pass     | current_bk |              0.354167  |             0.354167  |                              0 |               0.645833 |              0.645833 |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  200 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  200 | full_pass     | weak_bk    |              0.354167  |             0.354167  |                              0 |               0.645833 |              0.645833 |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  500 | full_pass     | current_bk |              0.125     |             0.125     |                              0 |               0.875    |              0.875    |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  500 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                  500 | full_pass     | weak_bk    |              0.125     |             0.125     |                              0 |               0.875    |              0.875    |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 1000 | full_pass     | current_bk |              0.145833  |             0.145833  |                              0 |               0.854167 |              0.854167 |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 1000 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 1000 | full_pass     | weak_bk    |              0.145833  |             0.145833  |                              0 |               0.854167 |              0.854167 |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 2000 | full_pass     | current_bk |              0.145833  |             0.145833  |                              0 |               0.854167 |              0.854167 |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 2000 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| hard_case_weighted |                 2000 | full_pass     | weak_bk    |              0.145833  |             0.145833  |                              0 |               0.854167 |              0.854167 |                     1 |                                      0 |                                      0 |
| original_like      |                    0 | full_pass     | current_bk |              0.458333  |             0.458333  |                              0 |               0.541667 |              0.541667 |                     1 |                                      0 |                                      0 |
| original_like      |                    0 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                    0 | full_pass     | weak_bk    |              0.458333  |             0.458333  |                              0 |               0.541667 |              0.541667 |                     1 |                                      0 |                                      0 |
| original_like      |                   50 | full_pass     | current_bk |              0.1875    |             0.1875    |                              0 |               0.8125   |              0.8125   |                     1 |                                      0 |                                      0 |
| original_like      |                   50 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                   50 | full_pass     | weak_bk    |              0.1875    |             0.1875    |                              0 |               0.8125   |              0.8125   |                     1 |                                      0 |                                      0 |
| original_like      |                  100 | full_pass     | current_bk |              0.166667  |             0.166667  |                              0 |               0.833333 |              0.833333 |                     1 |                                      0 |                                      0 |
| original_like      |                  100 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                  100 | full_pass     | weak_bk    |              0.166667  |             0.166667  |                              0 |               0.833333 |              0.833333 |                     1 |                                      0 |                                      0 |
| original_like      |                  200 | full_pass     | current_bk |              0.0625    |             0.0625    |                              0 |               0.9375   |              0.9375   |                     1 |                                      0 |                                      0 |
| original_like      |                  200 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                  200 | full_pass     | weak_bk    |              0.0625    |             0.0625    |                              0 |               0.9375   |              0.9375   |                     1 |                                      0 |                                      0 |
| original_like      |                  500 | full_pass     | current_bk |              0.0208333 |             0.0208333 |                              0 |               0.979167 |              0.979167 |                     1 |                                      0 |                                      0 |
| original_like      |                  500 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                  500 | full_pass     | weak_bk    |              0.0208333 |             0.0208333 |                              0 |               0.979167 |              0.979167 |                     1 |                                      0 |                                      0 |
| original_like      |                 1000 | full_pass     | current_bk |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                 1000 | full_pass     | no_bk      |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                 1000 | full_pass     | weak_bk    |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |
| original_like      |                 2000 | full_pass     | current_bk |              0         |             0         |                              0 |               1        |              1        |                     1 |                                      0 |                                      0 |

## 7. 图像输出

- `outputs/figures/original_vs_current_fixed_reference/original_vs_current_accept_rate_by_error.png`
- `outputs/figures/original_vs_current_fixed_reference/original_vs_current_by_sample_group.png`
- `outputs/figures/original_vs_current_fixed_reference/bk_ablation_accept_rate_by_error.png`
- `outputs/figures/original_vs_current_fixed_reference/residual_distribution_large_error.png`
- `outputs/figures/original_vs_current_fixed_reference/bk_distribution_large_error.png`
- `outputs/figures/original_vs_current_fixed_reference/decision_mismatch_original_vs_current.png`

## 8. 结论

1. 是否找到早期原版脚本或输出：找到了若干相关脚本/输出，但本轮未发现可直接证明原始运行命令与阈值状态的完整 manifest，因此采用 original_style 重建口径。
2. original_style 如何重建：full-pass、case/sequence-level、严格 score+b/k gate、original_like 普通样本，不使用 window-aware 多窗口累计。
3. 50 km 是否基本全部拒绝：以 original_like/random_simulated 的 original_style 为主要参照；若 hard_case_weighted 仍接受，说明早期结论不适用于 hard-case 加权样本。
4. current_extended_style 为什么 50/100/200 km 仍有接受：主要来自 hard_case_weighted、当前 b/k 设置以及 window-aware 口径；random_simulated 通常低接受。
5. 差异主要来自哪里：样本选择和 b/k/验证器口径是主要因素，统计口径也需要固定为 case-level。
6. full_pass 当前实现是否等于早期 strong full-pass verifier：不完全等价。当前 full_pass 仍来自新 calibration/window-aware 环境；original_style 是对早期 strong full-pass 的重建。
7. no_bk/weak_bk/current_bk 哪个解释力最强：若 current_bk 明显高于 no_bk，说明 b/k 吸收贡献显著；否则样本几何本身是主因。
8. 当前扩展实验是否需要重跑：未见必须重跑的实现错误，但建议补充保存完整 residual terms 和以 case-level 为主统计。
9. 下一步：先固定单站主口径与 b/k 消融，再进入多站一致性分析。
