# R1 historical reproduction numerical tolerance protocol erratum

## 正式决定

`R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED`

本 erratum 仅修正 historical serialized artifact reproduction comparison。Scientific/production thresholds、verifier、b/k gates、coverage、ACCEPT/REJECT 和 population 均不变。R1 尚未重新执行，R2 仍不授权。

## 1. Independent numerical floor

全部 direct R1 GHz geometry 的 float64 spacing：min=1.9073486328125e-06 Hz，median=1.9073486328125e-06 Hz，max=1.9073486328125e-06 Hz。historical CSV 使用 pandas shortest round-trip decimal，reload dtype=float64。历史值与重建值各经历一个 float64 表示边界，因此比较界限采用两端各一 ULP 的保守 floor `3.814697265625e-06 Hz`，不是由 observed R1 maximum 构造。

## 2. Bound propagation

- Geometry bound `3.814697265625e-06` Hz；固定 reproduction tolerance `3.9e-06` Hz。
- Compensation bound `7.629510946571827e-06` Hz，来自两个 geometry bound 与 subtraction rounding；tolerance `8e-06` Hz。
- Observation/residual bound `1.525902189314365e-05` Hz；tolerance `1.6e-05` Hz。
- b_hat bound `1.600000000000001e-05` Hz；tolerance `1.7e-05` Hz。
- k_hat bound `1.927710843373494e-07` Hz/s；tolerance `2e-07` Hz/s。
- Score bound `1.6e-05` Hz；tolerance `1.6e-05` Hz。

Observed R1 maxima 仅用于验证 proposed bounds 能覆盖已观察值，未参与任何公式。完整推导见 `outputs/metrics/causal_a_doppler_r1_numerical_tolerance_bound_derivation.csv`。

## 3. Fixed vs ULP-aware

A fixed absolute bound 最适合本 population：所有 geometry 值位于同一 GHz exponent bin，spacing 完全相同。Dynamic ULP rule 同样可行，但增加实现复杂度；hybrid 对当前 population 没有额外收益。因此采用可直接审计的 fixed per-quantity tolerances，不采用统一 tolerance。

## 4. Quantity decisions

| quantity                             |   old_tolerance |   proposed_reproduction_tolerance | decision         | derivation_summary                                       | scientific_effect   | scope                        | bound_construction_uses_observed_R1_max   |
|:-------------------------------------|----------------:|----------------------------------:|:-----------------|:---------------------------------------------------------|:--------------------|:-----------------------------|:------------------------------------------|
| evaluation_time_and_time_grid        |           1e-12 |                           1e-12   | KEEP             | exact time grid policy unchanged                         | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| A_position                           |           1e-06 |                           1e-06   | KEEP             | state reconstruction already exact                       | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| A_velocity                           |           1e-09 |                           1e-09   | KEEP             | state reconstruction already exact                       | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| B_position                           |           1e-06 |                           1e-06   | KEEP             | state reconstruction already exact                       | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| B_velocity                           |           1e-09 |                           1e-09   | KEEP             | state reconstruction already exact                       | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| Doppler_geometry                     |           1e-06 |                           3.9e-06 | ERRATUM_REQUIRED | one GHz-scale float64 ULP exceeds old absolute tolerance | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| active_compensation_curve            |           1e-06 |                           8e-06   | ERRATUM_REQUIRED | two geometry terms plus subtraction rounding             | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| observation_and_raw_residual         |           1e-06 |                           1.6e-05 | ERRATUM_REQUIRED | geometry and compensation propagation                    | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| b_hat                                |           1e-06 |                           1.7e-05 | ERRATUM_REQUIRED | centered-OLS intercept operator bound                    | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| k_hat                                |           1e-09 |                           2e-07   | ERRATUM_REQUIRED | centered-OLS slope operator bound                        | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| score                                |           1e-06 |                           1.6e-05 | ERRATUM_REQUIRED | RMSE Lipschitz bound                                     | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |
| categorical_gates_and_final_decision |           0     |                           0       | KEEP             | exact zero-mismatch requirement                          | NONE                | HISTORICAL_REPRODUCTION_ONLY | False                                     |

State/time tolerances 保持原值。Geometry、compensation、observation/residual、b_hat、k_hat 和 score 只在 historical reproduction equivalence 中采用 derived bounds。Categorical gate/decision 继续要求 exact zero mismatch。

## 5. Evidence boundary

High-precision evidence 仍只覆盖 30 个 direct-family failing samples，没有补造 10 个 passing samples。Tolerance decision 的主要依据是 serialization/ULP 与 deterministic operator-norm proof，而非 sample representativeness。

## 6. Formal status

`R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED`

SCIENTIFIC METHOD CHANGED: `NO`

VERIFIER BEHAVIOR CHANGED: `NO`

POPULATION CHANGED: `NO`

CATEGORICAL MATCH REQUIREMENT: `UNCHANGED / EXACT ZERO MISMATCH`

R2 AUTHORIZED: `NO`

NEXT STEP: `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN`
