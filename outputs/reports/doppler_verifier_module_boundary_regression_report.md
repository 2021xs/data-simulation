# Doppler-only residual verifier initial experiment report

## 1. Motivation

closed-set residual matcher 会强制从候选库中选出一个 score 最小的 satellite，因此它不适合直接定义“攻击是否成功”。本轮把已有 b+k profile least-squares matcher 改成 single-target verifier：给定 claimed target A 和观测曲线 y(t)，系统只判断这条曲线是否足够像 A，并允许 reject。

## 2. Verifier definition

输入为 claimed target A 与观测曲线 y(t)。本轮使用 candidate library 中 A 自己的 Ku-band 几何曲线 `f_geo_A(t)`，计算 `delta_A(t) = y(t) - f_geo_A(t)`，拟合 `b_hat + k_hat(t - t0)`，再用扣除拟合项后的 residual RMSE 作为 `score_A`。若 `score_A <= threshold_A_95` 或 `score_A <= threshold_A_99`，则在对应阈值下 accept，否则 reject。

本轮阈值是 per-target threshold，不使用单一 global threshold。`threshold_A_95` 和 `threshold_A_99` 分别来自合法仿真样本 score 分布的 95% 与 99% 分位数。

## 3. Legitimate calibration

合法样本使用 controlled Starlink Ku-band full-pass reference，目标列表来自 `outputs\metrics\controlled_starlink_20target_selection_table.csv`，claimed reference 来自 `outputs\datasets\controlled_starlink_20target_partial_pass_candidate_library.csv` 中每个 target 的 true-target 几何曲线。每个 target 生成 `50` 条合法曲线：

`f_legit_A(t) = f_geo_A(t) + b + k(t - t0) + noise`

其中 `b/k/sigma` 均从 main_range 随机采样，random_seed = `20260513`。本轮合法校准总序列数为 `1000`，整体 p95 阈值下 true accept rate = `0.9400`，p99 阈值下 true accept rate = `0.9800`。

阈值表前 10 行：

| target_name | target_norad | n_legitimate_sequences | score_mean_hz | score_p95_hz | score_p99_hz | true_accept_rate_95 | true_accept_rate_99 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| STARLINK-1008 | 44714 | 50 | 28.1623 | 31.599 | 34.2915 | 0.94 | 0.98 |
| STARLINK-35137 | 65686 | 50 | 27.0216 | 32.2409 | 33.4686 | 0.94 | 0.98 |
| STARLINK-35146 | 65421 | 50 | 27.5941 | 31.7566 | 32.1915 | 0.94 | 0.98 |
| STARLINK-35022 | 65409 | 50 | 27.4624 | 32.7455 | 33.0954 | 0.94 | 0.98 |
| STARLINK-35024 | 65410 | 50 | 28.4621 | 32.7104 | 33.6998 | 0.94 | 0.98 |
| STARLINK-2163 | 47749 | 50 | 27.8428 | 33.0481 | 33.6631 | 0.94 | 0.98 |
| STARLINK-2103 | 47383 | 50 | 28.0076 | 32.8868 | 34.5473 | 0.94 | 0.98 |
| STARLINK-34983 | 65411 | 50 | 27.7766 | 32.4395 | 33.4125 | 0.94 | 0.98 |
| STARLINK-2517 | 48309 | 50 | 28.7931 | 33.5285 | 34.8595 | 0.94 | 0.98 |
| STARLINK-1227 | 45230 | 50 | 27.1743 | 32.3338 | 32.9412 | 0.94 | 0.98 |

## 4. Attack orbit construction

攻击曲线来自攻击轨道 B，而不是目标 A。攻击者 B 声称自己是 A；verifier 只使用 A 的 claimed geometry 计算 `score_A`。如果 `score_A <= threshold_A`，则记录为 false accept / attack success。

本轮实现两类初步攻击：

- `same_plane_altitude_offset`：从目标 A 的 mid-pass ECI 位置和速度估计轨道面，构造同轨道面圆轨道近似 B，并设置高度偏移 Δh = [-100, -50, -20, -10, -5, 5, 10, 20, 50, 100] km。
- `same_plane_phase_offset`：使用同一受控圆轨道近似，保持高度不变，用沿轨道相位/时间偏移 Δt = [-300, -120, -60, -30, -10, 10, 30, 60, 120, 300] s 构造 B。

这个 B 轨道生成器是受控近似：它由 mid-pass ECI 状态、轨道面法向、圆轨道半径和角速度生成 B 的位置序列，再由 B 到地面站的 range-rate 计算 Doppler。它不是把 A 的 Doppler 曲线直接加扰动来伪装攻击样本。`approximate_orbit_perturbation` 本轮未展开，列为下一步。

## 5. Results

攻击总序列数为 `2000`。整体 threshold_95 下 attack success rate = `0.0015`，threshold_99 下 attack success rate = `0.0015`。

按攻击类型汇总：

| attack_type | n_sequences | success_95 | success_99 | min_margin_95 | score_p50 |
| --- | --- | --- | --- | --- | --- |
| same_plane_altitude_offset | 1000 | 0.003 | 0.003 | -1.74934 | 528.277 |
| same_plane_phase_offset | 1000 | 0 | 0 | 1760.44 | 20328.9 |

按 variant 汇总前 20 行：

| attack_type | attack_variant | n_sequences | attack_success_rate_95 | attack_success_rate_99 | min_score_margin_95_hz | most_vulnerable_target | most_vulnerable_target_norad |
| --- | --- | --- | --- | --- | --- | --- | --- |
| same_plane_altitude_offset | delta_h_-100km | 100 | 0 | 0 | 497.621 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_-50km | 100 | 0 | 0 | 225.067 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_-20km | 100 | 0 | 0 | 69.5438 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_-10km | 100 | 0 | 0 | 20.6937 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_-5km | 100 | 0.03 | 0.03 | -1.74934 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_+5km | 100 | 0 | 0 | 7.54338 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_+10km | 100 | 0 | 0 | 30.5426 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_+20km | 100 | 0 | 0 | 78.9931 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_+50km | 100 | 0 | 0 | 230.774 | STARLINK-35060 | 65693 |
| same_plane_altitude_offset | delta_h_+100km | 100 | 0 | 0 | 476.298 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_-300s | 100 | 0 | 0 | 5996.95 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_-120s | 100 | 0 | 0 | 13169.1 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_-60s | 100 | 0 | 0 | 9606.31 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_-30s | 100 | 0 | 0 | 5246.88 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_-10s | 100 | 0 | 0 | 1760.44 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_+10s | 100 | 0 | 0 | 1769.53 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_+30s | 100 | 0 | 0 | 5151.06 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_+60s | 100 | 0 | 0 | 9209.92 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_+120s | 100 | 0 | 0 | 12268.4 | STARLINK-35060 | 65693 |
| same_plane_phase_offset | delta_t_+300s | 100 | 0 | 0 | 5866.76 | STARLINK-35060 | 65693 |

最小 p95 margin 样本为 `attack_001621`：claimed target = `STARLINK-35060 / 65693`，attack_type = `same_plane_altitude_offset`，variant = `delta_h_-5km`，score_A = `31.679707` Hz，threshold_95 = `33.429048` Hz，score_margin_95 = `-1.749342` Hz。

`b_hat/k_hat` 需要和 residual score 一起看：同轨道面相似攻击可能被 b+k 拟合项吸收掉整体频偏和平缓趋势，但如果剩余曲线形状仍不同，RMSE 会高于阈值。完整 `b_hat`、`k_hat` 分布已写入 attack results 与 summary。

threshold_95 下共有 `3` 条 false accept 样本。这些样本的 `k_hat` 范围为 `-3.317347` 到 `-3.222806` Hz/s，明显超出本轮合法误差模型 main_range 的 `k` 采样范围 [-1.110156, -0.197808] Hz/s；这说明单看 residual RMSE 会漏掉一类由 b+k 拟合项强吸收的异常样本，后续应考虑 score gate + fitted-parameter sanity gate。

threshold_95 下 false accept 样本：

| attack_sequence_id | claimed_target_name | claimed_target_norad | attack_type | attack_variant | score_A_rmse_hz | threshold_95_hz | score_margin_95_hz | b_hat_hz | k_hat_hz_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| attack_001621 | STARLINK-35060 | 65693 | same_plane_altitude_offset | delta_h_-5km | 31.6797 | 33.429 | -1.74934 | 3112.01 | -3.22281 |
| attack_001625 | STARLINK-35060 | 65693 | same_plane_altitude_offset | delta_h_-5km | 32.1678 | 33.429 | -1.26128 | 3579.73 | -3.31735 |
| attack_001921 | STARLINK-2698 | 48458 | same_plane_altitude_offset | delta_h_-5km | 31.831 | 32.015 | -0.184005 | 3373.65 | -3.30553 |

## 6. Interpretation

本轮是 controlled simulation，不是现实世界真实攻击成功率。本轮评估的是 Doppler-only residual verifier 在受控轨道相似攻击下的 false accept 风险。

如果攻击者能够完全按目标 A 主动伪造接收频率轨迹，单站 Doppler-only verifier 本身会面临天然局限；本轮没有把攻击曲线生成为 `f_geo_A(t) + b + k + noise`，因此避免了自证循环。`frequency_scaled` 或真实 Starlink Ku-band CFO 分布不是本轮结论，本轮仍使用工程级 effective residual main_range。

## 7. Next steps

- 双阈值灰区：accept / reject / defer。
- 随机子窗口挑战：避免固定窗口被 trajectory-aware attacker 预补偿。
- 多地面站联合：检查跨站 Doppler / TDOA 一致性。
- 近似轨道扰动扩展：加入 Δh、Δi、ΔΩ、Δphase 的小网格。
- 更强攻击者的受限频率补偿实验，同时明确不能把主动完全伪造 A 轨迹与自然轨道相似攻击混为一谈。
