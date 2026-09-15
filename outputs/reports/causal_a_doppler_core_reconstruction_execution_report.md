# Causal-A Doppler core reconstruction execution

## 正式状态

`CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_COMPLETE`

本轮严格执行 R2 冻结的 407 个 LEVEL-A units 与 26,780 observation rows。没有修改 population、randomness、verifier、b/k、score threshold 或 Orbit-Uncertainty 参数，也没有增加 post-result cases。

## 1. Execution completeness

| experiment_family                               |   planned_units |   executed_units |   planned_rows |   executed_rows |   orbit_scored_units |   DEFER_units |   verifier_completed_rows |   failed_rows |   new_randomness_rows |   provenance_failures |   rho99_min |   rho99_max |
|:------------------------------------------------|----------------:|-----------------:|---------------:|----------------:|---------------------:|--------------:|--------------------------:|--------------:|----------------------:|----------------------:|------------:|------------:|
| segment_local_heatmap_and_direction_sensitivity |              37 |               37 |           6200 |            6200 |                   37 |             0 |                      6200 |             0 |                     0 |                     0 |   0.0169284 |   2677.57   |
| controlled_altitude_difference_synthetic_B      |             300 |              300 |          18000 |           18000 |                  300 |             0 |                     18000 |             0 |                     0 |                     0 |   0.0153223 |     21.4601 |
| same_pair_multi_pass_real_TLE                   |              40 |               40 |           2400 |            2400 |                   40 |             0 |                      2400 |             0 |                     0 |                     0 |  36.8854    |   2968.47   |
| active_compensation_first_pass                  |              30 |               30 |            180 |             180 |                   30 |             0 |                       180 |             0 |                     0 |                     0 |   1.97208   |   2852.05   |

全部 407 units 与 26,780 rows 已执行；endpoint rows=25,490，diagnostic/reference rows=1,290。26,780 rows 是 unit 内受控 observation outcomes，不是独立轨道案例。

## 2. Orbit scoring

- NOT_ORBIT_DISTINCT: 23 units
- AMBIGUOUS: 119 units
- ORBIT_DISTINCT: 265 units
- DEFER: 0 units
- overall rho99 range: 0.0153222502 to 2968.46592

每个 LEVEL-A unit 在 segment center 只计算一次 orbit decision。`z_B=RTN_public(A-B)`，`rho99=sqrt(D2/c99)` 仅为归一化椭球距离，不是 probability。

## 3. Boundary diagnostic

- rho99 < 0.8: 108
- 0.8 <= rho99 <= 1.2: 40
- rho99 > 1.2: 259
- rho99 <= 1: 142
- rho99 > 1: 265
- status: `BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE`

R2 没有冻结 transition-band 最小样本量，因此这里只报告预先允许的 descriptive band presence，不新增 threshold。

## 4. Verifier outcome binding

ORBIT_DISTINCT units=265；其中具有 primary endpoint realizations 的 units=265，`controlled_observation_acceptance_fraction > 0` 的 units=198。这里只报告 existence/count，不作 risk 或现实概率解释。

## 5. Correctness

- future publication violations: 0
- new random draws: 0
- SupGP operational use: 0
- verifier execution failures: 0
- A semantic split: 0
- frozen spot-check: 30/30 PASS
- categorical correctness mismatches: 0
- frozen threshold/model/source modifications: 0

## 6. Decision

`R3: PASS`

`NEXT STEP: ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS`

本轮在完成 frozen execution、summary 与 correctness audit 后停止，没有自动执行下一阶段。
