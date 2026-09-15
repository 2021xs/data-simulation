# 图2 星下点补偿失败证据图说明

## 输入检查
- sequence_eval: `outputs\metrics\active_compensation_first_pass_sequence_eval.csv`，行数 `600`。
- sequence_eval 字段: `sequence_id, residual_mode, reference_mode, target_id, target_name, attacker_id, attacker_name, pass_start_utc, pass_end_utc, max_elevation_deg, compensation_type, R_km, bearing_deg, C_lat_deg, C_lon_deg, C_alt_m, C_S_distance_km, sanity_check_role, score_only_sanity_pass, tri_state_applicable, score_A_rmse_hz, b_hat_hz, k_hat_hz_s, threshold_95_hz, threshold_99_hz, accepted_p95, accepted_p99, target_k_min_p01, target_k_max_p99, accepted_per_target_k_p01_p99, tri_state_decision, b_injected_hz, k_injected_hz_s, noise_sigma_hz, u_comp_mean_hz, u_comp_std_hz, u_comp_p95_abs_hz, attack_delta_rmse_hz, attack_delta_mean_hz, attack_delta_std_hz, observed_delta_rmse_hz, observed_delta_mean_hz, observed_delta_std_hz, C_lat_min_deg, C_lat_max_deg, C_lon_min_deg, C_lon_max_deg, C_S_distance_min_km, C_S_distance_mean_km, C_S_distance_max_km, C_S_distance_at_mid_km, num_points, center_freq_hz, random_seed, moving_reference_diff_step_s`。
- dataset: `outputs\datasets\active_compensation_first_pass_dataset.csv`。
- dataset 字段: `sequence_id, residual_mode, reference_mode, target_id, target_name, attacker_id, attacker_name, compensation_type, R_km, bearing_deg, t_rel_s, time_utc, f_geo_A_S_hz, f_geo_B_S_hz, f_geo_A_C_hz, f_geo_B_C_hz, u_comp_hz, f_attack_base_hz, b_injected_hz, k_injected_hz_s, noise_sigma_hz, noise_injected_hz, f_attack_hz, delta_to_claimed_hz, delta_base_to_claimed_hz, C_lat_deg, C_lon_deg, C_alt_m, C_S_distance_km, range_rate_A_C_mps, range_rate_B_C_mps`。
- 使用 pairwise 文件 `outputs\metrics\active_compensation_first_pass_pairwise_compare.csv`；residual_mode=empirical。

## 使用字段
- pairwise: `residual_mode`, `none_score_hz`, `subpoint_score_hz`, `score_improvement_ratio`, `none_attack_delta_rmse_hz`, `subpoint_attack_delta_rmse_hz`, `attack_delta_improvement_ratio`, `subpoint_p95_accept`, `subpoint_tri_state_decision`。
- sequence_eval: `sequence_id`, `target_id`, `target_name`, `attacker_id`, `attacker_name`, `score_A_rmse_hz`, `attack_delta_rmse_hz`, `b_hat_hz`, `k_hat_hz_s`, `tri_state_decision`。
- dataset: `t_rel_s`, `delta_to_claimed_hz`, `C_S_distance_km`。

## 统计结果
- 原始几何差距改善比例: `86.00%`。
- 验证器分数改善比例: `55.00%`。
- 原始改善但分数未改善比例: `33.00%`。
- ACCEPT 数: `0`。
- DEFER 数: `0`。

## 代表性样本
- sequence_id: `active_comp_000064`。
- target: `STARLINK-35137` / `65686`。
- attacker: `STARLINK-35024` / `65410`。
- score: `30596.281621` Hz。
- attack_delta_rmse: `189514.302635` Hz。
- tri_state: `REJECT`。
- d_min: `951.145` km。
- 选择原因: 优先选择 subpoint_A 相比 none 原始几何差距有改善、验证器分数没有改善或更差、tri-state 不是 ACCEPT 的样本；该样本 selection_score 最高。