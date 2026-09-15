# Doppler semantic reconstruction method decision

## 1. Decision

本轮冻结 `CAUSAL_A_ALIGNED_DOPPLER_RECONSTRUCTION_V1`。旧 verifier aggregate outputs 不能从 `A_old` 严格代数转换为 `A_causal` 结果。对 A semantics mismatch units，正式结论是 `FULL_DOPPLER_RECOMPUTATION_REQUIRED`；这表示复用原 case、factor、draw、threshold 和 verifier，仅重建依赖 A 的几何与下游量，不是重新设计实验。

`LEGACY_DIRECT_RELABEL = NOT_SUFFICIENT`。

## 2. Dependency audit

| quantity                        | formula_or_source                              | dependency_class                                         | A_dependent   | B_dependent   | observation_randomness_dependent   | reconstruction_policy                  | reason                                                                                    | old_aggregate_deterministic_transform_allowed   |
|:--------------------------------|:-----------------------------------------------|:---------------------------------------------------------|:--------------|:--------------|:-----------------------------------|:---------------------------------------|:------------------------------------------------------------------------------------------|:------------------------------------------------|
| evaluation_time_and_t_rel_grid  | saved segment bounds/time grid                 | A_INDEPENDENT                                            | False         | False         | False                              | REUSE_EXACT                            | The segment/time convention is frozen and is not inferred from a new orbit.               | True                                            |
| selected_A_GP_and_state         | causal selector and propagation                | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE                              | Must select CREATION_DATE<=t and use the same A state everywhere.                         | False                                           |
| fixed_controlled_station_S      | configured station coordinates                 | A_INDEPENDENT                                            | False         | False         | False                              | REUSE_EXACT                            | A fixed station is an experiment input.                                                   | True                                            |
| A_relative_service_center_C     | A subpoint/segment-center track                | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE_WHEN_USED                    | C is generated from A in segment-local and subpoint compensation families.                | False                                           |
| A_relative_receiver_S           | destination(C,distance,direction)              | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE_WHEN_USED                    | Preserve distance/direction factors, not legacy cached coordinates.                       | False                                           |
| F_A_S_t                         | geometric Doppler of A at verifier receiver    | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE                              | This is the claimed Doppler curve.                                                        | False                                           |
| F_A_C_t                         | geometric Doppler of A at compensation center  | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE_WHEN_USED                    | Required by service-center/subpoint active compensation.                                  | False                                           |
| F_B_S_t                         | geometric Doppler of B at verifier receiver    | B_DEPENDENT                                              | False         | True          | False                              | RECOMPUTE_FROM_PRESERVED_B_SEMANTICS   | Changes for A-relative synthetic B; real B provenance is retained.                        | False                                           |
| F_B_C_t                         | geometric Doppler of B at compensation center  | A_DEPENDENT+B_DEPENDENT                                  | True          | True          | False                              | RECOMPUTE_WHEN_USED                    | C can change with A even when real B is fixed.                                            | False                                           |
| u_C_t                           | F_A(C,t)-F_B(C,t)                              | A_DEPENDENT+B_DEPENDENT                                  | True          | True          | False                              | RECOMPUTE                              | Active compensation cannot reuse the legacy curve after A changes.                        | False                                           |
| b_env                           | saved draw or deterministic seed replay        | OBSERVATION_RANDOMNESS_DEPENDENT                         | False         | False         | True                               | REUSE_DRAW                             | The effective bias draw is held fixed across semantic reconstruction.                     | True                                            |
| k_env                           | saved draw or deterministic seed replay        | OBSERVATION_RANDOMNESS_DEPENDENT                         | False         | False         | True                               | REUSE_DRAW                             | The slow-drift draw is held fixed.                                                        | True                                            |
| sigma_and_noise_vector          | saved draw/hash or deterministic seed replay   | OBSERVATION_RANDOMNESS_DEPENDENT                         | False         | False         | True                               | REUSE_DRAW                             | Do not silently sample new noise.                                                         | True                                            |
| passive_observation_y           | F_B(S,t)+b+k(t-t0)+noise                       | B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT             | False         | True          | True                               | REBUILD_IF_B_CHANGES_ELSE_REUSE_VECTOR | Real-B passive y can be reused only if its full saved vector is bound.                    | False                                           |
| active_observation_y            | F_B(S,t)+u_C(t)+b+k(t-t0)+noise                | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | RECOMPUTE                              | Both compensation and possibly B geometry change.                                         | False                                           |
| claimed_Doppler_curve           | F_A(S,t)                                       | A_DEPENDENT                                              | True          | False         | False                              | RECOMPUTE                              | The verifier reference must be causal-A aligned.                                          | False                                           |
| raw_residual                    | y(t)-F_A(S,t)                                  | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | RECOMPUTE                              | No aggregate old-to-new transform exists.                                                 | False                                           |
| OLS_b_hat                       | intercept of raw residual                      | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | REFIT_SAME_OLS                         | Must fit the unchanged OLS to the reconstructed residual.                                 | False                                           |
| OLS_k_hat                       | slope of raw residual                          | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | REFIT_SAME_OLS                         | Must fit the unchanged OLS to the reconstructed residual.                                 | False                                           |
| residual_score                  | RMSE after unchanged b+k projection            | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | RECOMPUTE                              | The score is nonlinear in the changed residual after projection.                          | False                                           |
| score_threshold                 | existing legitimate calibration threshold      | A_INDEPENDENT                                            | False         | False         | True                               | REUSE_FROZEN                           | With the same time grid and residual distribution, F_A cancels in legitimate calibration. | True                                            |
| b_k_gate_limits                 | current b/k frozen ranges or calibrated limits | A_INDEPENDENT                                            | False         | False         | True                               | REUSE_FROZEN                           | Gate limits are scientifically frozen; only fitted values change.                         | True                                            |
| coverage_and_visibility         | A/B/site geometry over segment                 | A_DEPENDENT+B_DEPENDENT                                  | True          | True          | False                              | RECOMPUTE                              | Derived C/S coordinates and both orbit states can change visibility.                      | False                                           |
| score_b_k_coverage_gate_results | threshold comparisons                          | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | RECOMPUTE                              | Inputs to every gate may change even though limits do not.                                | False                                           |
| ACCEPT_REJECT_DEFER             | unchanged verifier decision rule               | A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT | True          | True          | True                               | RECOMPUTE                              | Final decision cannot be inherited for A-mismatched units.                                | False                                           |
| orbit_D2_rho99_decision         | frozen public-RTN ellipsoid                    | A_DEPENDENT+B_DEPENDENT                                  | True          | True          | False                              | RECOMPUTE_WITH_FROZEN_PARAMETERS       | Computed once at segment center; no uncertainty refit.                                    | False                                           |

必须重新计算或按 B 语义重建的主要量为：`['selected_A_GP_and_state', 'A_relative_service_center_C', 'A_relative_receiver_S', 'F_A_S_t', 'F_A_C_t', 'F_B_S_t', 'F_B_C_t', 'u_C_t', 'passive_observation_y', 'active_observation_y', 'claimed_Doppler_curve', 'raw_residual', 'OLS_b_hat', 'OLS_k_hat', 'residual_score', 'coverage_and_visibility', 'score_b_k_coverage_gate_results', 'ACCEPT_REJECT_DEFER', 'orbit_D2_rho99_decision']`。`score threshold` 与 frozen `current b/k` limits 保持不变；变化的是 fitted values、gate outcomes 和最终 decision。

不存在从旧 `score/b_hat/k_hat/residual` aggregate 到 causal-A result 的严格 deterministic transform。被动 REAL_B 若保存了完整 observation vector，可以复用该 vector，但仍必须针对新 `F_A(S,t)` 执行同一 OLS/verifier；A-relative synthetic B 与 active compensation 还必须重建 observation curve。

## 3. B semantics

- `REAL_B`：保持原真实 B identity、原 historical/static orbit provenance 和同一 segment 的 physical state，不人工 perturb，也不要求 B 遵循 A 的 causal-publication policy。
- `SYNTHETIC_RELATIVE_TO_A`：必须执行 `B_new=Perturb(A_causal,delta)`；保留 delta、direction、orbital rule 和 randomness，不保留 `B_old` absolute state。
- `SYNTHETIC_ABSOLUTE_STATE`：只有 authoritative definition 明确与 A 无关时才保留 absolute B；当前选定 core family 没有依赖这一类别。

## 4. Family method matrix

| family                                          | scientific_purpose                                                                 | A_semantics                                                       | B_class                                  | B_policy                                                                                                                                            | randomness_reproducible                                                               | verifier_rerun_required                           | priority_for_final_mainline   | scope_decision                                                                                                   | A_reconstruction_possible           | B_semantic_reconstruction_possible   |   legacy_orbit_units |   A_semantics_compatible_units | legacy_relabel_status   |
|:------------------------------------------------|:-----------------------------------------------------------------------------------|:------------------------------------------------------------------|:-----------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------|:--------------------------------------------------|:------------------------------|:-----------------------------------------------------------------------------------------------------------------|:------------------------------------|:-------------------------------------|---------------------:|-------------------------------:|:------------------------|
| score_only_verifier_and_synthetic_orbit_attacks | Legacy full-pass score-only baseline and altitude/phase synthetic attack history   | static TLE claimed A                                              | SYNTHETIC_RELATIVE_TO_A                  | For any future reconstruction use Perturb(A_causal, frozen altitude/phase rule); do not retain B_old absolute state                                 | YES_SAVED_DRAWS_AND_SEED                                                              | YES_FOR_A_MISMATCH; NO_FOR_64_SET_MATCHED_UNITS   | KEEP_HISTORICAL_ONLY          | Use only as R1 implementation reproduction and historical baseline; superseded by current segment-local verifier | YES                                 | YES                                  |                  400 |                             20 | RELABEL_PARTIAL         |
| verifier_v2_gate_ablation                       | Derived score/b/k gate view over the initial attack observations                   | inherits initial static TLE A                                     | INHERITED_SYNTHETIC_RELATIVE_TO_A        | No independent B reconstruction; inherit the causal-A reconstructed initial-family observation                                                      | YES_INHERITED                                                                         | YES_FOR_A_MISMATCH; NO_FOR_MATCHED_READ_ONLY_VIEW | KEEP_HISTORICAL_ONLY          | Do not count as a separate experiment family or geometry unit                                                    | YES                                 | YES                                  |                  400 |                             20 | RELABEL_PARTIAL         |
| controlled_multitarget_legitimate_baseline      | Legitimate A-only calibration/baseline                                             | static TLE A-only                                                 | NOT_APPLICABLE                           | Do not manufacture candidate B                                                                                                                      | YES_BUT_PAIR_GATE_NOT_APPLICABLE                                                      | NO_FOR_JOINT_MAINLINE                             | DROP_FROM_FINAL_MAINLINE      | Retain as historical legitimate baseline only                                                                    | NOT_APPLICABLE_OR_UPSTREAM_REQUIRED | NOT_APPLICABLE                       |                    0 |                              0 | NOT_APPLICABLE          |
| active_compensation_first_pass                  | Test none/subpoint/direct active compensation against claimed identity             | static TLE A; F_A enters claimed curve, subpoint C, and u_C       | REAL_B                                   | Keep original real B identity/TLE physical state; recompute C, F_A, F_B and compensation with causal A                                              | YES_SAVED_TIMESERIES_DRAWS_AND_SEED                                                   | YES_FOR_A_MISMATCH                                | RECONSTRUCT_CORE              | Current attack-model core; use current b/k primary and minimize target/pair/compensation strata                  | YES                                 | YES                                  |                  100 |                             10 | RELABEL_PARTIAL         |
| fixed_point_active_compensation_summary         | Legacy fixed-point/window summary diagnostic                                       | legacy A with relative summaries                                  | SYNTHETIC_RELATIVE_TO_A                  | Summary rows are insufficient; any upstream reconstruction would require causal-A-relative B semantics and is redundant with retained core families | NO_FROM_SUMMARY_ALONE                                                                 | NOT_SELECTED                                      | DROP_FROM_FINAL_MAINLINE      | Stop maintaining as a formal joint-security family                                                               | NOT_APPLICABLE_OR_UPSTREAM_REQUIRED | NO_FROM_THIS_ARTIFACT_ALONE          |                    0 |                              0 | BLOCKED_B_STATE         |
| segment_local_heatmap_and_direction_sensitivity | Segment-local real-B and controlled relative-synthetic direction/geometry evidence | static TLE A defines claimed curve and A-relative C/S geometry    | MIXED_REAL_B_AND_SYNTHETIC_RELATIVE_TO_A | Keep real B physical orbit; rebuild synthetic B and A-relative C/S from causal A with frozen factors                                                | YES_WITH_BOUND_MASTER_SEED_AND_SAVED_LEGACY_DRAWS; FREEZE_EXPLICIT_DRAW_MAP_BEFORE_R2 | YES_FOR_A_MISMATCH                                | RECONSTRUCT_CORE              | Reconstruct a reduced current_bk subset; do not rerun all 89,280 legacy rows                                     | YES                                 | YES                                  |                   37 |                              0 | BLOCKED_A_SEMANTICS     |
| same_pair_multi_pass_real_TLE                   | Real-B pair x pass repeatability under the same candidate provenance               | static TLE A                                                      | REAL_B                                   | Keep original B identity/TLE state at each frozen segment; replace only A with causal A                                                             | YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES                           | YES_FOR_A_MISMATCH                                | RECONSTRUCT_CORE              | Core temporal-repeatability evidence; current_bk primary                                                         | YES                                 | YES                                  |                   40 |                              4 | RELABEL_PARTIAL         |
| historical_TLE_multi_pass_real_TLE              | Exploratory different-date real-B/TLE sensitivity for two physical pairs           | historical TLE A without publication provenance                   | REAL_B                                   | Keep historical B identity/TLE physical state; causal-select A at each segment                                                                      | YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES                           | YES_FOR_A_MISMATCH                                | RECONSTRUCT_SENSITIVITY       | Do not include in pooled core claim; retain as date/TLE sensitivity                                              | YES                                 | YES                                  |                    8 |                              0 | BLOCKED_A_SEMANTICS     |
| controlled_altitude_difference_synthetic_B      | Physical-km altitude perturbation comparison across pass/direction conditions      | static TLE A is the synthetic construction base and claimed curve | SYNTHETIC_RELATIVE_TO_A                  | Rebuild B=Perturb(A_causal, same signed delta_h and Keplerian rule); preserve factors/seeds, not B_old state                                        | YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES                           | YES_FOR_A_MISMATCH                                | RECONSTRUCT_CORE              | Use current_bk primary; no_bk/wide_bk sensitivity; delta_h=0 remains reference only                              | YES                                 | YES                                  |                  300 |                             30 | RELABEL_PARTIAL         |
| differential_doppler_mechanism_representatives  | Derived explanatory representative traces                                          | inherited legacy pair-instance A                                  | DERIVED_MIXED_PROVENANCE                 | Do not infer states from relative-time summary; regenerate diagnostics only from selected core outputs if later needed                              | NO_FROM_REPRESENTATIVE_ARTIFACT_ALONE                                                 | NOT_SELECTED                                      | DROP_FROM_FINAL_MAINLINE      | Stop maintaining as an independent formal family                                                                 | NOT_APPLICABLE_OR_UPSTREAM_REQUIRED | NO_FROM_THIS_ARTIFACT_ALONE          |                    0 |                              0 | BLOCKED_B_STATE         |

### Core reconstruction

['active_compensation_first_pass', 'segment_local_heatmap_and_direction_sensitivity', 'same_pair_multi_pass_real_TLE', 'controlled_altitude_difference_synthetic_B']

### Sensitivity only

['historical_TLE_multi_pass_real_TLE']

### Historical only / stopped mainline maintenance

历史保留：['score_only_verifier_and_synthetic_orbit_attacks', 'verifier_v2_gate_ablation']。

停止作为 final mainline family 维护：['controlled_multitarget_legitimate_baseline', 'fixed_point_active_compensation_summary', 'differential_doppler_mechanism_representatives']。

不重跑全部 158,520 rows。segment-local 只冻结 reduced `current_bk` subset；`no_bk/wide_bk` 只作 sensitivity。verifier v2 view 不重复计算 geometry units。

## 5. Minimum sufficient formal set

最小 core 由四类科学证据组成：

1. Segment-local real-B + A-relative synthetic geometry/direction subset，用于 real/synthetic 对照、方向与 rho99。
2. Controlled signed-altitude perturbation，用于保留 km 物理对照。
3. Same-pair real-B multipass，用于时间重复性。
4. Active-compensation real-B family，用于最终攻击假设。

Historical-TLE multipass 只作不同日期/TLE sensitivity。只有 R2 后 existing frozen perturbation grid 明显缺失 rho99≈1 coverage，才允许 R4 最小 boundary expansion。

## 6. R1 reproduction gate

64 个 A-semantics-compatible units 足以作为 implementation reproduction set，因为它们覆盖 initial synthetic、active compensation、same-pair multipass 和 controlled altitude 四类路径，并已有 30-case orbit bridge end-to-end audit。R1 必须验证全部 64 units 及其绑定的 6,480 条非重复 primary source realization/mode rows；200 条 verifier-v2 derived rows只作交叉检查。

冻结 correctness thresholds：

| quantity                             | threshold                                                   |
|:-------------------------------------|:------------------------------------------------------------|
| evaluation_time_and_time_grid        | exact string/value equality; t_rel absolute error <=1e-12 s |
| selected_A_GP_ID_and_TLE             | exact equality                                              |
| A_position                           | max vector norm error <=1e-6 km                             |
| A_velocity                           | max vector norm error <=1e-9 km/s                           |
| B_position                           | max vector norm error <=1e-6 km                             |
| B_velocity                           | max vector norm error <=1e-9 km/s                           |
| Doppler_geometry_curves              | max absolute error <=1e-6 Hz                                |
| active_compensation_curve            | max absolute error <=1e-6 Hz when applicable                |
| observation_and_raw_residual         | max absolute error <=1e-6 Hz                                |
| b_hat_and_score                      | absolute error <=1e-6 Hz                                    |
| k_hat                                | absolute error <=1e-9 Hz/s                                  |
| gate_booleans_and_final_decision     | exact equality; zero mismatches                             |
| saved_random_seeds_and_vector_hashes | exact equality where available                              |

所有 checks 必须通过，decision mismatch 必须为 0。无法恢复 randomness 时不得新采样，状态为 `RANDOMNESS_RECONSTRUCTION_REQUIRED`。

## 7. Segment and joint-row protocol

Orbit label 在 frozen segment center 计算一次；Doppler verifier 继续使用整个 segment timeseries。每条正式 joint row 绑定 causal A GP_ID/freshness、B semantic definition、D2/rho99/orbit decision、score/b_hat/k_hat/verifier decision。`rho99` 与 physical displacement 同时报告，rho99 不是 probability。

安全主关注为 `ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED`，不得称为 attack success rate。

## 8. Answers to the method questions

1. Aggregate old verifier outputs不能 deterministic transform；semantics-compatible cases可直接复用，mismatch cases必须执行 unchanged verifier recomputation。
2. 必须重建所有 A-dependent curves、A-relative C/S/B、active compensation、residual、OLS、score、gates 和 decision。
3. REAL_B 保持原 identity 与 physical orbit state。
4. SYNTHETIC_RELATIVE_TO_A 必须围绕 causal A 重新构造。
5. Core：segment-local、controlled altitude、same-pair real-B multipass、active compensation。
6. Historical-TLE multipass 和 no_bk/wide_bk 只作 sensitivity。
7. Fixed-point summary、differential representatives、A-only pair-inapplicable baseline停止 mainline 维护；initial/V2只保留历史与R1。
8. 64 compatible units足以作为 implementation reproduction set，但不能替代R2 scientific reconstruction。
9. R1 使用上表 floating tolerances、exact seed/hash和zero decision mismatch。
10. 不需要重跑全部158,520 rows。
11. 最小充分集合是四个 core families，不重复 derived views。
12. 下一步是 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION`。

## 9. Formal status

`DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN`

`LEGACY_DIRECT_RELABEL: NOT SUFFICIENT`

`CORE STRATEGY: CAUSAL-A-ALIGNED DOPPLER RECONSTRUCTION`

`OLD VERIFIER OUTPUT: REUSE ONLY WHEN A SEMANTICS MATCH`

`NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION`
