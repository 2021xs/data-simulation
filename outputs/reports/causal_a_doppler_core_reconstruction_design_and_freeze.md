# Causal-A Doppler core reconstruction design and freeze

## 正式状态

`CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN`

本轮只进行了 identity/provenance/configuration audit 与 protocol freeze。没有传播新的 causal-A/B state，没有计算 Doppler、score、gate、ACCEPT/REJECT、D2、rho99 或 joint-security result。

## 1. Core population

| experiment_family                               | role         | scientific_purpose                                                                                |   candidate_units |   eligible_units |   included_R3_units |   excluded_units |   planned_primary_rows |   planned_endpoint_rows |   planned_diagnostic_rows |   available_no_bk_wide_bk_sensitivity_rows_not_in_core_R3 | result_blind_selection_rule                                                                         |
|:------------------------------------------------|:-------------|:--------------------------------------------------------------------------------------------------|------------------:|-----------------:|--------------------:|-----------------:|-----------------------:|------------------------:|--------------------------:|----------------------------------------------------------:|:----------------------------------------------------------------------------------------------------|
| segment_local_heatmap_and_direction_sensitivity | PRIMARY_CORE | real/synthetic B comparison and service-direction dependence under segment-local geometry         |                37 |               37 |                  37 |                0 |                   6200 |                    6200 |                         0 |                                                     12400 | all 37 units; current_bk, M2_block, four R cells, d in {0,5,20,R}, phi=0 at d=0 otherwise all 8 phi |
| controlled_altitude_difference_synthetic_B      | PRIMARY_CORE | signed physical altitude perturbation response across frozen passes and three receiver directions |               300 |              300 |                 300 |                0 |                  18000 |                   16800 |                      1200 |                                                     36000 | all 300 units and all 15 signed delta_h levels including zero reference; current_bk                 |
| same_pair_multi_pass_real_TLE                   | PRIMARY_CORE | same real A/B pair repeatability across frozen passes                                             |                40 |               40 |                  40 |                0 |                   2400 |                    2400 |                         0 |                                                      4800 | all 40 original pair-pass units, three frozen directions, 20 realizations; current_bk               |
| active_compensation_first_pass                  | PRIMARY_CORE | none/subpoint-A/direct-S compensation comparison under the frozen active attack model             |               100 |              100 |                  30 |               70 |                    180 |                      90 |                        90 |                                                         0 | three SHA256-ordered B identities per A; all three compensation types and clean/empirical strata    |

最终 R3 primary core：**407 LEVEL-A units / 26780 planned rows**。其中 endpoint rows=25490，reference/sanity diagnostic rows=1290。相比 158,520 legacy rows，计划重建 26780 rows；不重复 historical-only derived views，也不在 core R3 执行 no_bk/wide_bk。

Active family 的 70 个 exclusion 仅由 `SHA256(R2_ACTIVE_PAIR_V1|A|B)` 每 A 取前三个 B 的 target-stratified thinning 产生。Segment-local 行级 thinning 仅使用 M2/current_bk 和原始 R/d/phi factors；所有 37 个 orbit units 均保留。没有使用 causal-A orbit score、rho99 或 verifier outcome。

## 2. B semantics

| experiment_family                               | B_class                 |   units |
|:------------------------------------------------|:------------------------|--------:|
| active_compensation_first_pass                  | REAL_B                  |      30 |
| controlled_altitude_difference_synthetic_B      | SYNTHETIC_RELATIVE_TO_A |     300 |
| same_pair_multi_pass_real_TLE                   | REAL_B                  |      40 |
| segment_local_heatmap_and_direction_sensitivity | REAL_B                  |      25 |
| segment_local_heatmap_and_direction_sensitivity | SYNTHETIC_RELATIVE_TO_A |      12 |

- REAL_B：保留真实 B identity 与原 historical TLE physical semantics；不围绕 causal A 生成 B。
- SYNTHETIC_RELATIVE_TO_A：以相同 signed altitude/phase/inclination/factor rule 围绕 `A_causal` 重建；保留科学 factor，不保留 legacy B absolute state。
- Segment-local 是 mixed-B family；controlled-altitude 全部是 A-relative synthetic；same-pair 与 active 全部是 REAL_B。

## 3. Causal A and analysis hierarchy

每个 LEVEL-A unit 冻结为 `claimed A × candidate B × segment/time`。A 使用 `CREATION_DATE<=evaluation_time` 后按 CREATION_DATE、EPOCH、GP_ID 逆序选择的同一个 GP，并统一驱动 orbit score、claimed Doppler、active compensation 和 verifier residual。Orbit decision 只在 segment center 计算一次；condition/realization 共享该 decision。

Receiver direction、service geometry 和 compensation type 是 unit 内预注册 condition strata，不伪装成 observation randomness。Observation realization 只作为 unit/condition 内 outcome。Primary endpoint 是 ORBIT_DISTINCT units 的 `controlled_observation_acceptance_fraction`，正式表述为 controlled observation model 下的 conditional verifier acceptance fraction，不是 attack success probability。

## 4. Modes and randomness

Primary mode=`current_bk`；active family 使用原 p95 score + per-target current k gate。`no_bk/wide_bk` 与 historical-TLE multipass 注册为 sensitivity，但不进入 minimal core R3。所有 planned rows 均绑定 saved draw variables/vector hashes 或 frozen seed/replay identity；new random draw forbidden。Randomness binding 共 26780 rows。

## 5. Orbit interface and downstream policy

Frozen Orbit-Uncertainty SHA=`6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1`。`rho99=sqrt(D2/c99)` 不是概率。DEFER、AMBIGUOUS、NOT_ORBIT_DISTINCT 分开报告，均不得并入 ORBIT_DISTINCT denominator。Primary security-relevant state 为 `ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED`，但不得称真实攻击成功率。

R3 后才诊断 rho99 transition coverage。若不足，进入独立的 `TARGETED_ORBIT_DISTINCT_BOUNDARY_CASE_DESIGN`，不得回头修改本 core population。

## 6. Spot-check and contamination audit

R3 spot-check 已按 stable identity hash 预先冻结：30 rows / 30 distinct units，覆盖 4 core families。Case selection 使用字段仅限 identity、family、factor、time、mode、seed/provenance。Causal-A `D2/rho99/orbit decision` 与新 Doppler results 均未生成或用于 selection；selection contamination=`FALSE`。

## 7. Formal decision

`R2: PASS`

`R3 AUTHORIZED: YES`

`NEXT STEP: CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION`
