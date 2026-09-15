# Doppler verifier initial experiment logic audit

## 1. Audit scope

本轮审查聚焦 `scripts/run_doppler_verifier_initial_experiments.py` 的 single-target Doppler-only residual verifier 初步实验逻辑，并抽查以下既有输出文件：

- `outputs/metrics/doppler_verifier_thresholds.csv`
- `outputs/metrics/doppler_verifier_legitimate_score_results.csv`
- `outputs/metrics/doppler_verifier_orbit_similarity_attack_results.csv`
- `outputs/metrics/doppler_verifier_orbit_similarity_attack_summary.csv`
- `outputs/datasets/doppler_verifier_initial_experiments_manifest.json`
- `outputs/datasets/doppler_verifier_legitimate_calibration_dataset.csv`
- `outputs/datasets/doppler_verifier_orbit_similarity_attack_dataset.csv`
- `outputs/metrics/controlled_starlink_20target_selection_table.csv`
- `outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv`

本轮没有重跑主实验，没有覆盖旧输出，也没有修改主实验脚本。

## 2. Expected experiment definition

对 claimed target A，合法校准应在 A 的同一个 pass 时间网格 `t_i` 上定义：

```text
f_legit_A(t_i) = f_geo_A(t_i) + b + k(t_i - t0_A) + noise
delta_A(t_i) = f_legit_A(t_i) - f_geo_A(t_i)
delta_A(t_i) ~= b_hat + k_hat(t_i - t0_A)
score_A = RMSE(residual_A)
threshold_A_95 / threshold_A_99 = per-target quantile(score_A)
```

攻击评估中，攻击轨道 B 声称自己是 A。B 必须在 A 的同一个 pass 时间网格上传播或近似生成：

```text
f_attack_B(t_i) = f_geo_B(t_i) + b_B + k_B(t_i - t0_A) + noise
delta_A(t_i) = f_attack_B(t_i) - f_geo_A(t_i)
score_A(B) = RMSE(delta_A - fitted b_hat - fitted k_hat)
false_accept = score_A(B) <= threshold_A
```

关键约束是：score 必须相对 claimed target A 的理论曲线计算，threshold 必须使用 claimed target A 的 per-target threshold，B 不能重新搜索自己的 pass 后用 B 自己的时间点或 B 自己的理论曲线自我验证。

## 3. Code path review

### pass selection

`load_inputs()` 读取 `outputs/metrics/controlled_starlink_20target_selection_table.csv` 前 20 个 target，并要求 selection table 包含 `pass_start_utc`、`pass_end_utc`、`step_s`。这说明每个 target A 的 pass 已在上游 selection table 中选定。主脚本没有在 verifier 阶段重新搜索 pass。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 130-142。

### time grid construction

`target_geo_from_library()` 从 candidate library 中抽取 `target_norad_id == candidate_norad_id == A` 的 true-target 几何曲线，并按 `t_rel_s` 排序。合法校准和攻击评估均从这个 `geo` 表读取 `t_abs_utc`、`t_rel_s` 和 `f_geo_candidate_hz`。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 173-180, 230-235, 422-425。

输出抽查显示，20 个 target 的 legitimate dataset 和 attack dataset 中每条 sequence 的 `t_abs_utc/t_rel_s` 均与 candidate library 中对应 A 的 true-target grid 一致；诊断结果 `time grid bad count: 0`。

### legitimate sample generation

`calibrate_legitimate()` 使用 A 的 `f_geo` 和同一组 `t_rel` 采样 `b/k/sigma`，调用 `apply_empirical_error_model()` 生成 `f_obs`，然后调用 `fit_bias_and_slope(f_obs, f_geo, t_rel)` 计算 `score_A`。因此合法样本的 `f_geo_A`、`f_obs_A`、`score_A` 使用同一组时间点。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 230-239, 198-209, 183-195。

### threshold calibration

`calibrate_thresholds()` 按 `target_name,target_norad` groupby 后分别计算 `threshold_95_hz` 和 `threshold_99_hz`。输出抽查显示 thresholds 表共有 20 行、20 个 target；legitimate score 表共有 1000 条 sequence，每个 target 50 条。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 286-319；`outputs/metrics/doppler_verifier_thresholds.csv`。

### attack orbit construction

攻击不是随机取另一颗候选卫星，而是基于 A 的 TLE 和 A pass 的 `times` 构造受控 same-plane circular-orbit approximation。`synthetic_same_plane_geo()` 在 A pass 的 `times` 上传播/近似生成 B 的位置序列，并由 B 到 station 的 range-rate 计算 `f_geo_attack_B_hz`。

`same_plane_altitude_offset` 通过 `radius_km = norm(r0) + altitude_offset_km` 改变半径，同时保留由 A mid-pass ECI 状态导出的轨道面法向 `h_hat`。`same_plane_phase_offset` 通过 `theta = angular_rate * (t_centered + phase_offset_s)` 改变沿轨相位/时间偏移。它是受控圆轨道近似，不是完整 TLE 轨道重构。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 329-362, 393-438。

### attack score computation

攻击样本先由 `apply_empirical_error_model(f_geo_attack, t_rel, ...)` 得到 `f_obs_attack_hz`，再调用 `fit_bias_and_slope(f_obs, f_geo_claimed, t_rel)`。这里第二个参数是 A 的 `f_geo_claimed`，不是 B 的 `f_geo_attack`。因此计算的是 `f_attack_B(t_i) - f_geo_A(t_i)` 的 residual RMSE。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 422-442, 487-489。

### false accept decision

`threshold_map` 由 thresholds 表按 `target_norad` 建立，攻击循环对 claimed target A 读取 `threshold_95, threshold_99 = threshold_map[target_norad]`，并以 `fit.score_rmse_hz <= threshold_95/99` 判断 accepted。输出抽查显示 attack_results 中 threshold 字段与 claimed target A 的 thresholds 表完全一致，mismatch count 为 0；accepted 公式 mismatch count 为 0。

证据：`scripts/run_doppler_verifier_initial_experiments.py` lines 385-388, 426, 445-470。

## 4. Audit checklist

| item | expected behavior | observed behavior in code | status | evidence |
|---|---|---|---|---|
| per-target threshold 是否正确 | 每个 A 单独用合法 score 分布校准 `threshold_A_95/99` | `calibrate_thresholds()` 按 `target_name,target_norad` groupby；输出 20 行/20 target，每 target 50 条合法 score | PASS | script lines 286-319; `doppler_verifier_thresholds.csv` |
| 合法样本是否基于 A 的 pass 时间窗口 | 每个 target 先取 A 的 true-target grid，再生成合法样本 | `target_geo_from_library()` 抽取 `target_norad_id == candidate_norad_id == A`；合法样本使用该 `geo` | PASS | script lines 173-180, 230-239 |
| 合法 score 是否相对 A 计算 | `score_A = RMSE(f_legit_A - f_geo_A - fitted b/k)` | `fit_bias_and_slope(f_obs, f_geo, t_rel)` 中 `f_geo` 是 A 自己的 curve | PASS | script lines 183-195, 238-239 |
| attack curve 是否来自 B | `f_attack_B = f_geo_B + b_B + k_B + noise` | `f_geo_attack = synthetic_same_plane_geo(...)`，再 `apply_empirical_error_model(f_geo_attack, ...)` | PASS | script lines 430-442 |
| attack score 是否相对 A 计算 | `score_A(B)` 使用 `f_attack_B - f_geo_A` | `fit_bias_and_slope(f_obs, f_geo_claimed, t_rel)`，`f_geo_claimed` 来自 A true-target library row | PASS | script lines 422-425, 441-442 |
| B 是否使用 A pass time grid | B 在 A 的 `t_abs_utc/t_rel_s` 上生成，不重新找 B pass | `times` 和 `t_rel` 从 A 的 `geo` 取得，并传入 `synthetic_same_plane_geo()` | PASS | script lines 422-438 |
| threshold 是否使用 claimed target A | false accept 使用 `threshold_map[target_norad]` | 输出抽查 threshold mismatch 为 0，accepted 公式 mismatch 为 0 | PASS | script lines 385-388, 426, 445-470 |
| t0 / t_rel_s 是否一致 | 合法与攻击均以当前 A pass 时间网格中心为 t0 | `apply_empirical_error_model()` 和 `fit_bias_and_slope()` 都使用 `mean(t_rel_s)`；dataset 写出 `t_centered_s` 和 `t0_s` | PASS | script lines 183-209, 486-491 |
| phase offset 是否避免自证循环 | phase variant 可以是受控近似，但不能直接写成 A 合法曲线 | `phase_offset_s` 改变 `theta`，再由 attack range-rate 得到 Doppler；攻击 score 仍相对 A | PASS | script lines 354-362, 405-438 |
| 输出是否可追溯到 pass | 每条攻击应可追溯 claimed target、attack variant、时间网格/pass | attack dataset 记录 target、variant、`t_abs_utc/t_rel_s` 和 A/B 曲线；但未直接写 `pass_start_utc/pass_end_utc/pass_id` | WARNING | `doppler_verifier_orbit_similarity_attack_dataset.csv`; selection table has pass fields |
| false accept 结论是否由 CSV 支持 | false accept = 3/2000，均来自 `delta_h_-5km`，`k_hat` 约 -3.22 到 -3.32 Hz/s | CSV 抽查为 3/2000；accepted variants `{'delta_h_-5km': 3}`；`k_hat` range `[-3.317347, -3.222806]` | PASS | `doppler_verifier_orbit_similarity_attack_results.csv` |

## 5. Findings

Current implementation is consistent with the intended single-pass claimed-identity verifier experiment.

没有发现以下会使当前结果失效的逻辑错误：

- 未发现 B 重新搜索自己的 pass 后与 A 比较。
- 未发现 `score_A(B)` 错误地使用 `f_attack_B - f_geo_B` 自我验证。
- 未发现使用全局 threshold 或使用 B 的 threshold 判断 false accept。
- 未发现攻击曲线被直接写成 `f_geo_A(t) + b + k + noise` 的自证循环。

一个可追溯性 warning：当前 legitimate/attack dataset 没有直接写入 `pass_id`、`pass_start_utc`、`pass_end_utc`、`time_grid_hash`。现有输出仍可通过 `claimed_target_norad/target_norad`、`t_abs_utc/t_rel_s` 和 `controlled_starlink_20target_selection_table.csv` 回连 pass，但组会或论文级复核时建议补充这些 diagnostic 字段。这个 warning 不要求重跑当前实验；若要把 pass metadata 写进逐行 dataset，则需要新增输出版本或显式重跑，不能覆盖旧结果。

CSV 原始结果支持当前报告中的关键结论：

- attack sequences: `2000`
- threshold_95 false accept: `3/2000 = 0.0015`
- threshold_99 false accept: `3/2000 = 0.0015`
- false accept 全部来自 `same_plane_altitude_offset / delta_h_-5km`
- false accept 的 `k_hat_hz_s` 范围为 `-3.317347` 到 `-3.222806` Hz/s
- 对应 claimed targets 为 `STARLINK-35060 / 65693` 两条、`STARLINK-2698 / 48458` 一条

因此当前结果可以作为初步组会汇报材料使用，但应明确它是 controlled single-pass verifier baseline，不是真实世界攻击成功率。

## 6. Limitations

即使代码逻辑与本轮定义一致，当前实验仍有以下边界：

- 当前是 single-pass full-window 初步实验。
- 每个 target 只使用一个代表性 pass，不是 multi-pass validation。
- 当前 false accept rate 不是现实世界射频攻击成功率。
- 攻击轨道 B 是基于 A mid-pass ECI 状态的 same-plane circular-orbit controlled approximation，不是完整动力学轨道设计。
- `same_plane_phase_offset` 是沿受控圆轨道的相位/时间偏移近似，汇报时需要说明不是直接的真实 TLE 相位重构。
- 当前 verifier 只看 residual RMSE；false accept 样本的 `k_hat` 明显偏离合法 main_range，说明后续需要 score gate + fitted-parameter sanity gate。

## 7. Recommended next checks

- 做 multi-pass validation：每个 target 至少多个 pass，检查 threshold 和 false accept 是否稳定。
- 增加 score + fitted-parameter sanity gate：例如对 `b_hat/k_hat/residual_std` 设置 target-specific 或 range-aware 辅助门限。
- 在后续新增输出中记录每条 legitimate/attack sequence 的 `pass_id`、`pass_start_utc`、`pass_end_utc`、`time_grid_hash`。
- 输出 false accept 样本的 A/B 曲线对比图，尤其是 `attack_001621`、`attack_001625`、`attack_001921`。
- 对 `delta_h_-5km` 附近做更细高度 sweep，并检查 `k_hat` gate 后 false accept 是否消失。
