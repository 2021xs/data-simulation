# 单站 Doppler Residual Identity Verification Baseline 收口报告

生成时间：2026-05-27 21:39:39

本报告只整理当前仓库中已经存在的单站 Doppler-only claimed-identity verification 代码和输出；没有重新生成 attack observation，没有改 verifier 逻辑，也没有做主动调频或多站实验。

## 1. 单站 baseline 当前链路

当前单站链路的核心实现位于 `scripts/run_doppler_verifier_initial_experiments.py`：

- `ObservationSequence`（约第 57 行）保存一条观测曲线 `y_obs_hz`、时间网格、source geometry 和经验误差参数。
- `fit_bias_and_slope(...)`（约第 236 行）计算 `delta_A(t)=y(t)-f_geo_A(t)`，用最小二乘拟合 `b_hat + k_hat(t-t0)`，并输出拟合后 residual RMSE。
- `apply_empirical_error_model(...)`（约第 251 行）生成 `f_obs(t)=f_geo(t)+b+k(t-t0)+noise`。
- `build_legitimate_observation(...)`（约第 272 行）用目标 A 的几何曲线生成合法观测。
- `build_attack_observation(...)`（约第 312 行）用攻击源 B 的几何曲线生成观测，但只把它作为观测来源，不作为 claimed reference。
- `verify_claimed_identity(...)`（约第 366 行）只接收观测曲线和 claimed target A 的 `f_geo_A(t)`，不使用 B 的轨道参数做判决。
- `calibrate_thresholds(...)`（约第 480 行）按每个 target 的合法 residual RMSE 分布计算 p95 / p99 阈值。
- `synthetic_same_plane_geo(...)`（约第 523 行）用于构造第一阶段规则化 same-plane 高度/相位扰动攻击轨道。

后续增强逻辑是只读后处理或扩展实验：

- `scripts/evaluate_verifier_v2_gates.py`：保留 score-only 决策，额外统计 global k、global b/k、per-target k、per-target b/k gate。
- `scripts/run_full_pass_quality_coverage_expansion.py`：为困难样本补充中高仰角完整过境，并按每个 pass 重新校准 score threshold 与 k_hat 范围。
- `scripts/evaluate_full_pass_quality_expanded_tri_state.py`：实现 `ACCEPT / REJECT / DEFER`，其中低于仰角阈值但 score+k 通过的样本给 `DEFER`。
- `scripts/evaluate_full_pass_quality_expanded_multipass_aggregation.py`：把多次完整过境聚合成 case-level 决策。
- `scripts/run_pass_quality_aware_attacker_search.py`：在攻击者知道 pass-quality 规则的情况下，只评估 `max_elevation_deg >= 20` 的高质量候选过境。

链路可以整理为：

`TLE / SGP4 / station / carrier frequency` -> `f_geo_A(t)` -> `f_obs(t)` -> `delta_A(t)` -> `b/k least-squares fitting` -> `residual RMSE score` -> `p95/p99 threshold` -> `k_hat / b_hat sanity check` -> `pass quality` -> `ACCEPT / REJECT / DEFER`。

## 2. 固定实验设置表

| 项目 | 当前仓库事实 |
| --- | --- |
| mode | `controlled_starlink`，`observation_id=null`，来源：`outputs/datasets/doppler_verifier_initial_experiments_manifest.json` |
| 地面站 | `controlled_example_station`，lat `52.21`，lon `5.16`，alt `14` m |
| 载波频率 | `11325000000.0` Hz |
| 目标卫星数量 | 初始 score-only/v2：`20`；full-pass quality expanded 当前覆盖困难目标/过境集合见 `outputs/metrics/full_pass_quality_expanded_sequence_eval.csv` |
| 初始合法样本 | `1000` sequences，`359900` rows |
| 初始攻击样本 | `2000` sequences，`719800` rows |
| 初始攻击类型 | `same_plane_altitude_offset, same_plane_phase_offset` |
| 初始攻击参数 | 高度偏移 `[-100, -50, -20, -10, -5, 5, 10, 20, 50, 100]` km；相位偏移 `[-300, -120, -60, -30, -10, 10, 30, 60, 120, 300]` s |
| 时间窗口 | `configs/orbit_simulation_cases.yaml` 中 `auto_pass_search`，search_start=`2026-03-10T00:00:00Z`，min_elevation=`10` deg，step=`1` s |
| residual model | `f_obs(t)=f_geo(t)+b+k(t-t0)+noise` |
| b 范围 | `[3179.0, 3728.0]` Hz，来源：`configs/simulation_parameter_config.yaml` / manifest |
| k 范围 | `[-1.110156, -0.197808]` Hz/s，来源：`configs/simulation_parameter_config.yaml` / manifest |
| noise sigma 范围 | `[23.215, 32.89]` Hz，来源：`configs/simulation_parameter_config.yaml` / manifest |
| 阈值计算 | per-target 或 per-pass 合法样本 residual RMSE 的 p95 / p99 分位数 |
| 参数检查 | v2 使用 global k、global b/k、per-target quantile；full-pass quality 使用 per-pass `k_hat` p01-p99 |
| pass quality | 当前收口使用 `max_elevation_deg >= 20°` 作为强接受候选完整过境阈值；低仰角通过样本进入 `DEFER` |
| 主要输出 | `outputs/metrics/verifier_v2_gate_ablation.csv`、`outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv`、`outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv`、`outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv` |

## 3. 最终 baseline 结果表

### 3.1 单次完整过境 tri-state 序列级结果

数据来源：`outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv`，`elevation_min_deg=20`。

| threshold_type | legitimate_total | legitimate_accept | legitimate_reject | legitimate_defer | attack_total | attack_accept | attack_reject | attack_defer | false_accept_count | false_reject_count | false_accept_rate | false_reject_rate | threshold_rule | parameter_gate | quality_rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p95 | 1320 | 1108 | 142 | 70 | 840 | 0 | 790 | 50 | 0 | 142 | 0 | 0.107576 | p95 per-pass legitimate residual RMSE quantile | per-pass k_hat p01-p99 | max_elevation_deg >= 20 => ACCEPT if score+k pass; low elevation score+k pass => DEFER |
| p99 | 1320 | 1147 | 103 | 70 | 840 | 0 | 781 | 59 | 0 | 103 | 0 | 0.07803 | p99 per-pass legitimate residual RMSE quantile | per-pass k_hat p01-p99 | max_elevation_deg >= 20 => ACCEPT if score+k pass; low elevation score+k pass => DEFER |

### 3.2 case-level 多过境聚合结果

推荐作为当前单站 baseline 收口口径：`any_high_quality_accept`。含义是：至少一个高质量完整过境通过 score+k 才最终 ACCEPT；若只有低质量过境通过，则 DEFER。

数据来源：`outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv`，`elevation_min_deg=20`。

| threshold_type | legitimate_total | legitimate_accept | legitimate_reject | legitimate_defer | attack_total | attack_accept | attack_reject | attack_defer | false_accept_count | false_reject_count | false_accept_rate | false_reject_rate | threshold_rule | parameter_gate | quality_rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p95 | 200 | 200 | 0 | 0 | 160 | 0 | 110 | 50 | 0 | 0 | 0 | 0 | p95 per-pass legitimate residual RMSE quantile | per-pass k_hat p01-p99 | accept if any high-quality pass accepts; otherwise DEFER if only low-quality pass accepts |
| p99 | 200 | 200 | 0 | 0 | 160 | 0 | 101 | 59 | 0 | 0 | 0 | 0 | p99 per-pass legitimate residual RMSE quantile | per-pass k_hat p01-p99 | accept if any high-quality pass accepts; otherwise DEFER if only low-quality pass accepts |

补充验证：pass-quality-aware attacker search 在 `max_elevation_deg >= 20°` 的约束搜索中，p95/p99 的 score-only、score+k、v3 single-pass 接受数均为 0。

| threshold_type | total_sequences | accepted_score_only | accepted_per_pass_k_p01_p99 | accepted_v3_single_pass |
| --- | --- | --- | --- | --- |
| p95 | 12600 | 0 | 0 | 0 |
| p99 | 12600 | 0 | 0 | 0 |

## 4. 最小 ablation 表

数据来源：`outputs/metrics/full_pass_quality_expanded_sequence_eval.csv` 与 `outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv`。

说明：最终 full-pass quality 主线使用的是 per-pass `k_hat` p01-p99 检查；`b_hat` gate 在 v2 离线消融中已经评估，但当前 pass-quality tri-state 输出没有单独的 per-pass b_hat gate 字段，因此 ablation 的 Version 2/3 不把 b_hat 作为最终主线条件。

| threshold_type | method_version | method | legitimate_total | legitimate_accept_rate | attack_total | attack_reject_rate | false_accept_count | false_reject_count | defer_count | explanation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p95 | Version 1 | 仅 residual RMSE 阈值 | 1320 | 0.942424 | 840 | 0.9 | 84 | 76 | 0 | 没有使用 k_hat/b_hat 或过境质量判断。 |
| p95 | Version 2 | residual RMSE 阈值 + k_hat 参数合理性检查 | 1320 | 0.892424 | 840 | 0.940476 | 50 | 142 | 0 | 使用每个 pass 的合法样本 k_hat p01-p99 范围。 |
| p95 | Version 3 | residual RMSE 阈值 + k_hat 参数检查 + 20°过境质量判断 | 1320 | 0.839394 | 840 | 0.940476 | 0 | 142 | 120 | 低仰角通过样本不强行 ACCEPT，而是 DEFER；高质量 pass 才允许强接受。 |
| p99 | Version 1 | 仅 residual RMSE 阈值 | 1320 | 0.972727 | 840 | 0.877381 | 103 | 36 | 0 | 没有使用 k_hat/b_hat 或过境质量判断。 |
| p99 | Version 2 | residual RMSE 阈值 + k_hat 参数合理性检查 | 1320 | 0.92197 | 840 | 0.929762 | 59 | 103 | 0 | 使用每个 pass 的合法样本 k_hat p01-p99 范围。 |
| p99 | Version 3 | residual RMSE 阈值 + k_hat 参数检查 + 20°过境质量判断 | 1320 | 0.868939 | 840 | 0.929762 | 0 | 103 | 129 | 低仰角通过样本不强行 ACCEPT，而是 DEFER；高质量 pass 才允许强接受。 |

v2 初始 20-target score-only 对比也支持同一结论：score-only 在 2000 条攻击中有 3 条 false accept；global k / global b+k gate 后 false accept 变为 0。

| threshold_type | gate_name | sample_group | total_sequences | accepted_sequences | false_accepts_for_attack | false_accept_rate_for_attack | legit_accept_rate | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p95 | score_only | legit | 1000 | 940 | 0 |  | 0.94 | score <= per-target threshold |
| p95 | score_only | attack | 2000 | 3 | 3 | 0.0015 |  | score <= per-target threshold |
| p95 | score_plus_global_k_gate | legit | 1000 | 929 | 0 |  | 0.929 | global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p95 | score_plus_global_k_gate | attack | 2000 | 0 | 0 | 0 |  | global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p95 | score_plus_global_bk_gate | legit | 1000 | 926 | 0 |  | 0.926 | global_b_range=[3179.0, 3728.0], global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p95 | score_plus_global_bk_gate | attack | 2000 | 0 | 0 | 0 |  | global_b_range=[3179.0, 3728.0], global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p99 | score_only | legit | 1000 | 980 | 0 |  | 0.98 | score <= per-target threshold |
| p99 | score_only | attack | 2000 | 3 | 3 | 0.0015 |  | score <= per-target threshold |
| p99 | score_plus_global_k_gate | legit | 1000 | 968 | 0 |  | 0.968 | global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p99 | score_plus_global_k_gate | attack | 2000 | 0 | 0 | 0 |  | global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p99 | score_plus_global_bk_gate | legit | 1000 | 965 | 0 |  | 0.965 | global_b_range=[3179.0, 3728.0], global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |
| p99 | score_plus_global_bk_gate | attack | 2000 | 0 | 0 | 0 |  | global_b_range=[3179.0, 3728.0], global_k_range=[-1.110156, -0.197808]; range_source=configs\simulation_parameter_config.yaml |

## 5. false accept / false reject / DEFER 个例分析

| case_type | sequence_id | target | source_or_attacker | attack_type | score_rmse_hz | threshold_hz | b_hat_hz | k_hat_hz_per_s | decision | why_boundary | limitation | source_path |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| score-only false accept filtered by k gate | attack_001621 | STARLINK-35060 / 65693 | same_plane_altitude_offset/delta_h_-5km | same_plane_altitude_offset | 31.679707 | 33.429048 | 3112.011 | -3.222806 | score-only ACCEPT; global/per-target k gate REJECT | RMSE 低于阈值，但 k_hat 约 -3.22 Hz/s，明显超出 main_range 与 per-target 合法范围。 | 单看残差 RMSE 会让拟合自由度吸收几何差异，必须联合 fitted-parameter sanity gate。 | outputs/metrics/verifier_v2_false_accepts_detail.csv |
| legitimate false reject under score+k | 65693 / 65693_exp_01_medium / row_index=6272 | STARLINK-35060 / 65693 | legitimate observation |  | 21.861057 | 32.708305 | 3436.765 | -1.107158 | REJECT | 高质量过境 max_elevation_deg=28.44°，但 score 或 k_hat 检查未通过。 | 参数 gate 会牺牲一部分合法接受率；这是安全性与合法误拒之间的主要折中。 | outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv |
| legitimate low-elevation DEFER | 47767 / 47767_pass_01 / row_index=5289 | STARLINK-2185 / 47767 | legitimate observation |  | 21.77726 | 31.220423 | 3417.492 | -0.494392 | DEFER | score+k 通过，但 max_elevation_deg=15.26 < 20°。 | 低仰角合法样本可能看起来像目标，但不适合强 ACCEPT；需要等待高质量完整过境。 | outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv |

补充边界参考：`outputs/metrics/verifier_v2_fine_sweep_hard_cases.csv` 中存在细粒度高度偏移样本可以通过 per-target k p01-p99 gate，例如 `alt_fine_001147`，这说明几何极近样本仍是单站 Doppler-only baseline 的边界，但它不是当前 pass-quality 主线的最终验收口径。

## 6. 单站阶段性结论

1. 当前单站链路已经可以作为 baseline：输入为 claimed target A 与观测曲线，只用 A 的 `f_geo_A(t)` 做残差拟合与判决，不在 verifier 中使用攻击源 B 的轨道参数。
2. residual RMSE 能区分合法样本和多数规则化轨道相似攻击；初始 2000 条攻击中 score-only false accept 为 3 条。
3. `k_hat` / `b_hat` 参数合理性检查是必要的：3 条 score-only false accept 的 `k_hat` 明显越界，加入 gate 后被拒绝。
4. pass quality 判断解决了低质量完整过境的强判决问题：低仰角样本即使通过 score+k，也进入 `DEFER`，而不是直接 ACCEPT。
5. 当前推荐收口口径为：per-pass residual RMSE threshold + per-pass k_hat p01-p99 gate + `20°` high-quality pass 判断 + case-level `any_high_quality_accept` 聚合。
6. 剩余边界主要来自几何极近、细粒度高度偏移、短/低质量窗口，以及后续更强的主动频率补偿攻击。
7. 因此下一阶段不应继续无限扩展单站规则化攻击集合，而应在这个 baseline 上研究主动调频攻击下的多接收端空间一致性与残差差异。

## 7. 下次组会可用的一页摘要

### 单站 Doppler residual identity verification baseline 收口

- 当前单站验证器已经形成可复现 baseline：给定声称目标 A，只用 A 的理论多普勒曲线和观测曲线做残差拟合与判决。
- 初始 score-only 结果显示，残差 RMSE 能拒绝绝大多数规则化轨道相似攻击，但 2000 条攻击中仍有 3 条误接受。
- 这 3 条误接受的 `k_hat` 明显越界，说明只看 RMSE 不够；加入拟合参数合理性检查后，误接受降为 0。
- 在完整过境质量实验中，20°以上高质量过境的攻击误接受率为 0；低仰角通过样本不强行接受，而是延后判断。
- case-level 多过境聚合下，`any_high_quality_accept` 规则在当前困难样本集合中保持合法样本 200/200 接受，攻击样本 0/160 接受。
- 当前单站 baseline 的边界是几何极近、低质量过境和潜在主动调频攻击。
- 下一阶段应基于该 baseline 研究主动调频攻击下，多接收端看到的补偿残差是否一致。

## 附：本报告生成的结果表

- `outputs/metrics/single_station_baseline_final_results.csv`
- `outputs/metrics/single_station_baseline_ablation.csv`
- `outputs/metrics/single_station_baseline_case_studies.csv`
