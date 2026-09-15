# Window reliability calibration summary

生成时间：2026-06-11 21:07:40

## 1. 实验目的

本轮实验标定当前单站 Doppler residual claimed-identity verifier 在不完整观测窗口下的可靠性。它只评估 controlled station、真实 Starlink TLE、受控 Ku-band 载频、经验 effective residual 误差模型和规则化轨道相似攻击集合下的经验现象，不评价主动频率补偿攻击，也不把短窗口直接设计成最终 ACCEPT 策略。

## 2. 为什么加入 inclination_offset

已有高度偏移和相位偏移主要改变同轨道面内的径向/沿轨几何。`inclination_offset` 属于 orbit-plane offset，用于检查 cross-track / 轨道面相似性是否会在短窗口中形成新的高风险样本。本轮只改变 inclination，不同时加入 RAAN offset，避免变量耦合。

## 3. 实验矩阵

- target 数量：`20`
- benign_A 序列数：`1000`
- attack 序列数：`2000`
- attack 类型：`same_plane_altitude_offset`、`same_plane_phase_offset`、`inclination_offset`
- window：`full_pass`、`180/120/60/30s_middle`，以及 `180/120/60/30s_best_attack`
- threshold：window-specific `p95` / `p99`
- verifier：`shape_only`、`weak_prior`、`strong_prior`

best_attack 选择标准：对每个 target / attack 参数，在完整过境内按 1 s 步长滑动，使用无噪声 `f_geo_B(t) - f_geo_A(t)` 几何差异选择 `normalized_score = score / window_specific_p95_threshold` 最低的窗口；随后在该窗口位置用 benign_A 样本重新校准 window-specific threshold。该设置是 diagnostic 风险上界，不表示攻击源能利用随机噪声或主动调频。

## 4. verifier 三版本定义

- `shape_only`：只使用 residual RMSE score gate。
- `weak_prior`：score gate + per-window benign b/k quantile gate 放宽 `3` 倍，并裁剪到全局 main_range；质量门限仅要求 `n_points >= 10`。
- `strong_prior`：score gate + per-window benign b/k quantile gate 与全局 b/k main_range 的交集，并要求 `n_points >= 20` 与 mean elevation 下限 `0` deg。

这里的 `b_hat/k_hat` 是 claimed target A 条件下拟合出的 effective residual 线性参数，不是 true CFO，也不是攻击源精确可控变量。

## 5. 主要结果表

以下为 `p95 + strong_prior` 的聚合结果节选：

| window_type | window_length_s | window_position | attack_type | attack_accept_rate | benign_accept_rate | normalized_score_median |
| --- | --- | --- | --- | --- | --- | --- |
| 120s_best_attack | 120.0000 | best_attack | inclination_offset | 0.1333 |  | 0.8409 |
| 120s_best_attack | 120.0000 | best_attack | same_plane_altitude_offset | 0.0362 |  | 0.9161 |
| 120s_best_attack | 120.0000 | best_attack | same_plane_phase_offset | 0.0000 |  | 31.4110 |
| 120s_middle | 120.0000 | middle | benign_A |  | 0.7250 | 0.8427 |
| 120s_middle | 120.0000 | middle | inclination_offset | 0.0000 |  | 1.0011 |
| 120s_middle | 120.0000 | middle | same_plane_altitude_offset | 0.0487 |  | 1.0241 |
| 120s_middle | 120.0000 | middle | same_plane_phase_offset | 0.0000 |  | 151.7099 |
| 180s_best_attack | 180.0000 | best_attack | inclination_offset | 0.1083 |  | 0.8949 |
| 180s_best_attack | 180.0000 | best_attack | same_plane_altitude_offset | 0.0325 |  | 1.4960 |
| 180s_best_attack | 180.0000 | best_attack | same_plane_phase_offset | 0.0000 |  | 96.9167 |
| 180s_middle | 180.0000 | middle | benign_A |  | 0.7300 | 0.8528 |
| 180s_middle | 180.0000 | middle | inclination_offset | 0.0000 |  | 1.2724 |
| 180s_middle | 180.0000 | middle | same_plane_altitude_offset | 0.0475 |  | 1.5744 |
| 180s_middle | 180.0000 | middle | same_plane_phase_offset | 0.0000 |  | 317.3269 |
| 30s_best_attack | 30.0000 | best_attack | inclination_offset | 0.1367 |  | 0.7845 |
| 30s_best_attack | 30.0000 | best_attack | same_plane_altitude_offset | 0.0825 |  | 0.7827 |
| 30s_best_attack | 30.0000 | best_attack | same_plane_phase_offset | 0.0000 |  | 1.0273 |
| 30s_middle | 30.0000 | middle | benign_A |  | 0.4600 | 0.7847 |
| 30s_middle | 30.0000 | middle | inclination_offset | 0.0283 |  | 0.7753 |
| 30s_middle | 30.0000 | middle | same_plane_altitude_offset | 0.0488 |  | 0.7807 |
| 30s_middle | 30.0000 | middle | same_plane_phase_offset | 0.0000 |  | 9.8095 |
| 60s_best_attack | 60.0000 | best_attack | inclination_offset | 0.1717 |  | 0.8254 |
| 60s_best_attack | 60.0000 | best_attack | same_plane_altitude_offset | 0.0650 |  | 0.8204 |
| 60s_best_attack | 60.0000 | best_attack | same_plane_phase_offset | 0.0000 |  | 4.5369 |
| 60s_middle | 60.0000 | middle | benign_A |  | 0.6790 | 0.8228 |
| 60s_middle | 60.0000 | middle | inclination_offset | 0.0033 |  | 0.8489 |
| 60s_middle | 60.0000 | middle | same_plane_altitude_offset | 0.0462 |  | 0.8522 |
| 60s_middle | 60.0000 | middle | same_plane_phase_offset | 0.0000 |  | 39.9061 |
| full_pass | 248.0000 | full_pass | benign_A |  | 0.7200 | 0.8473 |
| full_pass | 248.0000 | full_pass | inclination_offset | 0.0000 |  | 1.4857 |

## 6. 三类轨道相似攻击对比

| attack_type | attack_accept_rate |
| --- | --- |
| same_plane_altitude_offset | 0.0272 |
| inclination_offset | 0.0262 |
| same_plane_phase_offset | 0.0000 |

当前设置下平均 attack accept rate 最高的是：`same_plane_altitude_offset`。如果 inclination_offset 排在前列，应作为下一轮轨道相似攻击扩展重点；如果不是，也说明本轮 cross-track 小扰动在当前 station/pass 组合下未比高度或相位偏移更危险。

## 7. b/k gate 对不同窗口的贡献

`bk_gate_delta = shape_only_attack_accept_rate - strong_prior_attack_accept_rate`：

| window_length_s | bk_gate_delta |
| --- | --- |
| 30.0000 | 0.6755 |
| 60.0000 | 0.5797 |
| 120.0000 | 0.4405 |
| 180.0000 | 0.2530 |
| 248.0000 | 0.1300 |
| 251.0000 | 0.1700 |
| 264.0000 | 0.1100 |
| 267.0000 | 0.0600 |
| 330.0000 | 0.0300 |
| 343.0000 | 0.0200 |
| 346.0000 | 0.0100 |
| 360.0000 | 0.0100 |
| 369.0000 | 0.0300 |
| 371.0000 | 0.0000 |
| 372.0000 | 0.0200 |
| 375.0000 | 0.0100 |
| 376.0000 | 0.0000 |
| 386.0000 | 0.0200 |
| 404.0000 | 0.0000 |
| 408.0000 | 0.0000 |

该表用于拆分完整曲线形状与 fitted-parameter sanity gate 的贡献。短窗口中如果 `bk_gate_delta` 明显上升，说明短窗口更依赖 b/k gate 来拒绝可由线性项吸收的轨道几何差异。

## 8. middle 与 best_attack 差异

- `p95 + strong_prior` middle 平均 attack accept rate：`0.0215`
- `p95 + strong_prior` best_attack 平均 attack accept rate：`0.0629`

best_attack 是 diagnostic 上界搜索，不代表攻击源主动调频或在线挑选窗口；它用于标定同一 full-pass 内局部片段最危险的位置。

## 9. 阶段性回答

1. full-pass 相比短窗口是否显著降低误接受率：当前 full-pass 平均 attack accept rate 为 `0.0083`，30s/60s 平均为 `0.0498`。若后者更高，说明短窗口形状证据更弱，应作为弱证据累计或 DEFER。
2. 30s / 60s 是否更依赖 b/k gate：见第 7 节 `bk_gate_delta`。短窗口 delta 越大，依赖越强。
3. middle 与 best_attack 差异：见第 8 节。best_attack 高于 middle 表示认证窗口位置会显著影响风险。
4. 三类攻击中哪类最危险：本轮均值最高为 `same_plane_altitude_offset`。
5. strong evidence / weak evidence：full-pass 和较长窗口可作为 strong evidence 的候选；30s/60s 若出现较高 attack accept rate 或强依赖 b/k gate，应只作为 weak evidence 或输出 DEFER。
6. 下一轮是否进入 location-aware active compensation under partial observation：建议先基于本轮结果设计 window-aware evidence accumulation verifier；只有在短窗口风险被清楚标定后，再进入 location-aware active compensation under partial observation。

## 10. 生成文件

- `outputs/datasets/window_reliability_calibration_dataset.csv`
- `outputs/metrics/window_reliability_calibration_summary.csv`
- `outputs/metrics/window_reliability_bk_gate_contribution.csv`
- `outputs/reports/window_reliability_calibration_summary.md`
- `outputs/figures/attack_accept_rate_vs_window_length.png`
- `outputs/figures/benign_accept_rate_vs_window_length.png`
- `outputs/figures/bk_gate_contribution_by_window.png`
- `outputs/figures/middle_vs_best_attack_accept_rate.png`
- `outputs/figures/attack_type_comparison_by_window.png`
- `outputs/figures/normalized_score_distribution_by_window.png`

## 11. 局限和下一步

本轮仍是 controlled orbit-based diagnostic。它没有复现真实 SatNOGS Starlink observation，没有评价真实 Ku-band residual 分布，也没有实现主动频率补偿。下一步应把窗口结果转成 window-aware evidence accumulation verifier，并把短窗口通过策略改为累计证据或 DEFER，而不是单窗口直接 ACCEPT。
