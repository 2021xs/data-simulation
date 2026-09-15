# 图3 受控 R 扫描结果图说明

## 使用数据
- summary: `outputs\metrics\archive_controlled_R_v1_3\active_compensation_controlled_R_summary.csv`。
- 主 controlled_R summary 不可用或为空，已回退到 archive_controlled_R_v1_3。
- 使用 empirical residual_mode。
- pairwise: `outputs\metrics\archive_controlled_R_v1_3\active_compensation_controlled_R_pairwise.csv`；字段 `target_id, target_name, attacker_id, attacker_name, pass_start_utc, pass_end_utc, max_elevation_deg, residual_mode, R_km, bearing_deg, none_score_hz, controlled_R_score_hz, score_improvement_hz, score_improvement_ratio, none_attack_delta_rmse_hz, controlled_R_attack_delta_rmse_hz, attack_delta_improvement_hz, attack_delta_improvement_ratio, controlled_R_p95_accept, controlled_R_p99_accept, controlled_R_tri_state_decision, controlled_R_b_hat_hz, controlled_R_k_hat_hz_s, threshold_95_hz, target_k_min_p01, target_k_max_p99`。

## 使用字段
- `residual_mode`, `R_km`, `case_count`, `score_median_hz`, `score_p95_hz`, `tri_ACCEPT_count`, `tri_DEFER_count`, `tri_REJECT_count`, `p95_accept_rate`。

## 图中绘制范围
- 组会简化图绘制 R 列表: `0, 50, 100, 200, 500` km。
- 未放入图中的 R: `1000, 2000`。
- 1000/2000 km 没放入组会图，是因为它们对近距离边界解释帮助不大，且会拉伸横轴。

## 解释边界
- R=0 等价于 C=S，即 direct-S 上界。
- R=50 km 起当前样本全部 REJECT: `True`。
- 这不是普适的 50 km 安全边界，只是当前目标集合、攻击源集合、验证器参数和过境窗口下的观察。
- 如果远距离点不严格单调，应解释为补偿参考点偏差敏感且会快速恶化；bearing 和具体几何关系仍会影响数值。

## empirical 统计
| R_km | case_count | score_median_hz | score_p95_hz | tri_ACCEPT | tri_DEFER | tri_REJECT | ACCEPT_rate | DEFER_rate | REJECT_rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 100 | 27.873 | 32.935 | 79 | 7 | 14 | 0.790 | 0.070 | 0.140 |
| 50 | 800 | 2567.262 | 5765.293 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |
| 100 | 800 | 5185.189 | 11601.149 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |
| 200 | 800 | 10079.646 | 23334.018 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |
| 500 | 800 | 24703.899 | 61727.302 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |
| 1000 | 800 | 34772.590 | 90444.686 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |
| 2000 | 800 | 23642.608 | 63810.134 | 0 | 0 | 800 | 0.000 | 0.000 | 1.000 |