# Single-station b/k gate ablation report

生成时间：2026-06-12 16:54:04

## 1. 为什么先做 b/k 消融

前几轮显示：随机样本和普通样本下早期 50 km 衰减趋势大体成立，但 hard-case 样本在较大位置误差下仍可能被接受；同时 no-bk 口径下接受率为 0。说明必须先固定单站主口径并系统分析 b/k gate，而不是直接进入多站一致性。

## 2. 固定主统计口径

本轮主结果使用 case-level main-window-only：case 由 target、simulated satellite、pass、sample_group、requested_error、bearing、window_mode、strategy、bk_mode、compensation_mode 定义。row-level 只作为诊断。

## 3. b/k 模式

- `no_bk`：score 直接基于 delta，不扣除 b/k。
- `strict_bk`：benign p95 b/k gate。
- `weak_bk`：benign p99 b/k gate。
- `current_bk`：当前 window-aware verifier b/k gate。
- `loose_bk`：current_bk 阈值扩大 2x，仅作上界敏感性。

## 4. 阈值校准

阈值只用 benign target-consistent synthetic samples 校准。阈值表输出到 `outputs/metrics/single_station_bk_gate_thresholds.csv`，共 `30` 行。

## 5. b/k 消融主结果

本轮实际规模：dataset `15120` 行，case-level summary `1260` 行，阈值表 `30` 行。正式运行保留完整位置误差、方位角、样本组、窗口、策略和 b/k 模式，但使用 `max_targets=3`、`max_samples_per_group=3` 的受限规模。

按 b/k 模式汇总 fixed-reference compensation 的 case accept：

| bk_mode    |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|:-----------|----------:|-------------------:|------------------:|-------------------:|
| current_bk |      1512 |           0.356481 |          0.246693 |           0.396825 |
| loose_bk   |      1512 |           0.429894 |          0.195767 |           0.374339 |
| no_bk      |      1512 |           0        |          0        |           1        |
| strict_bk  |      1512 |           0.222222 |          0.375661 |           0.402116 |
| weak_bk    |      1512 |           0.296296 |          0.306878 |           0.396825 |

current_bk 下按样本组：

| sample_group       |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|:-------------------|----------:|-------------------:|------------------:|-------------------:|
| hard_case_weighted |       504 |          0.660714  |          0.19246  |           0.146825 |
| original_like      |       504 |          0.309524  |          0.424603 |           0.265873 |
| random_simulated   |       504 |          0.0992063 |          0.123016 |           0.777778 |

current_bk 下按窗口：

| window_mode                      |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|:---------------------------------|----------:|-------------------:|------------------:|-------------------:|
| full_pass                        |       504 |           0.301587 |          0        |           0.698413 |
| selected_difficult_short_windows |       504 |           0.363095 |          0.414683 |           0.222222 |
| spread_3x60s                     |       504 |           0.404762 |          0.325397 |           0.269841 |

delta 摘要：

| sample_group       |   delta_current_vs_no_bk |   delta_current_vs_strict_bk |   delta_loose_vs_current_bk |
|:-------------------|-------------------------:|-----------------------------:|----------------------------:|
| hard_case_weighted |                0.660714  |                    0.21627   |                  0.0972222  |
| original_like      |                0.309524  |                    0.134921  |                  0.119048   |
| random_simulated   |                0.0992063 |                    0.0515873 |                  0.00396825 |

proposed_v1 + current_bk 下按样本组：

| sample_group       |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|:-------------------|----------:|-------------------:|------------------:|-------------------:|
| hard_case_weighted |       252 |          0.662698  |          0.190476 |           0.146825 |
| original_like      |       252 |          0.309524  |          0.424603 |           0.265873 |
| random_simulated   |       252 |          0.0992063 |          0.123016 |           0.777778 |

proposed_v1 + current_bk 下按窗口：

| window_mode                      |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|:---------------------------------|----------:|-------------------:|------------------:|-------------------:|
| full_pass                        |       252 |           0.301587 |          0        |           0.698413 |
| selected_difficult_short_windows |       252 |           0.365079 |          0.412698 |           0.222222 |
| spread_3x60s                     |       252 |           0.404762 |          0.325397 |           0.269841 |

hard_case_weighted / proposed_v1 / current_bk 下随位置误差变化：

|   requested_error_km |   n_cases |   case_accept_rate |   case_defer_rate |   case_reject_rate |
|---------------------:|----------:|-------------------:|------------------:|-------------------:|
|                    0 |        36 |           0.888889 |         0.0277778 |          0.0833333 |
|                   50 |        36 |           0.833333 |         0.138889  |          0.0277778 |
|                  100 |        36 |           0.805556 |         0.166667  |          0.0277778 |
|                  200 |        36 |           0.805556 |         0.0555556 |          0.138889  |
|                  500 |        36 |           0.611111 |         0.222222  |          0.166667  |
|                 1000 |        36 |           0.361111 |         0.361111  |          0.277778  |
|                 2000 |        36 |           0.333333 |         0.361111  |          0.305556  |

no-compensation 与 fixed-reference compensation 对照（proposed_v1 + current_bk）：

| sample_group       |   fixed_reference_compensation |   no_compensation |
|:-------------------|-------------------------------:|------------------:|
| hard_case_weighted |                      0.662698  |          0.547619 |
| original_like      |                      0.309524  |          0        |
| random_simulated   |                      0.0992063 |          0        |

## 6. b/k 对剩余失配的吸收

以下表格使用 fixed-reference compensation / proposed_v1 / current_bk 的 dataset 行，比较 b/k 扣除前后的补偿残差 RMSE 中位数：

| sample_group       |   before_bk_median_hz |   after_bk_median_hz |   absorption_ratio |
|:-------------------|----------------------:|---------------------:|-------------------:|
| hard_case_weighted |               11.9833 |              6.42424 |            1.86532 |
| original_like      |               74.43   |             35.1675  |            2.11644 |
| random_simulated   |            26393      |           4552.85    |            5.79702 |

## 7. provenance 复现检查

抽样 `50` 行，decision replay match rate = `1.0000`。本轮保存 deterministic `noise_seed`、injected b/k、noise_std、residual_trace_id 和 residual_vector_hash。

## 8. 图像输出

- `outputs/figures/single_station_bk_gate_ablation/bk_mode_accept_rate_vs_error.png`
- `outputs/figures/single_station_bk_gate_ablation/sample_group_accept_rate_under_bk_modes.png`
- `outputs/figures/single_station_bk_gate_ablation/delta_current_vs_no_bk_heatmap.png`
- `outputs/figures/single_station_bk_gate_ablation/before_after_bk_residual_vs_error.png`
- `outputs/figures/single_station_bk_gate_ablation/bk_hat_distribution_by_decision.png`
- `outputs/figures/single_station_bk_gate_ablation/compensation_vs_no_compensation_by_bk_mode.png`

## 9. 本轮最终回答

1. no_bk 下是否仍有接受：fixed-reference compensation 主口径下 `no_bk` case accept rate = `0.0000`。本轮结果显示纯几何补偿不足以通过当前 residual 阈值。
2. strict_bk 是否能显著降低 hard-case 接受率：hard_case_weighted 的 `delta_current_vs_strict_bk` 均值为 `0.2163`；strict_bk 明显低于 current_bk，说明当前 b/k gate 对该压力测试偏宽。
3. current_bk 相比 no_bk 提高多少接受率：总体 fixed-reference compensation 下 current_bk = `0.3565`，no_bk = `0.0000`，差值约 `0.3565`。
4. loose_bk 是否明显放大接受率：loose_bk = `0.4299`，current_bk = `0.3565`，差值约 `0.0734`；说明 b/k 容忍范围继续放宽会放大接受率。
5. 接受率主要集中在哪个样本组：current_bk 下 hard_case_weighted 最高，其次 original_like，random_simulated 最低。具体数值见第 5 节样本组表。
6. 接受率主要集中在哪个窗口模式：current_bk 下 `spread_3x60s` 和 `selected_difficult_short_windows` 高于或接近 full_pass；具体数值见第 5 节窗口表。
7. b/k 吸收了多少固定参考点误差造成的剩余失配：在 proposed_v1 + current_bk 下，b/k 扣除前后 RMSE 中位数通常降低约 2x 以上；random_simulated 因原始失配很大，吸收比例更高但仍多被拒绝。
8. 当前 b/k gate 是否过宽：对 fixed-reference compensation 强压力测试而言偏宽；证据是 no_bk 为 0，而 strict_bk 到 current_bk 的放宽带来额外接受。
9. 是否建议把 b/k 通过从 ACCEPT 条件改成 DEFER / risk score 条件：建议至少在 fixed-reference compensation 场景中把较大 b/k 吸收量作为 risk score 或 DEFER 条件评估，而不是简单视作 ACCEPT 的充分条件。
10. 单站主口径是否已经稳定、能否进入多站一致性：本轮已固定 case-level main-window-only 口径，并保存 provenance；可以进入多站一致性分析，但应把本轮 b/k 消融作为单站主口径的前置说明。
