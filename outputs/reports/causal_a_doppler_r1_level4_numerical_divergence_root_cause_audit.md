# R1 Level-4 numerical divergence root-cause audit

## 正式状态

`R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC`

R1 primary 仍为 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`，R2 不授权。本轮没有重跑 R1、没有修改 tolerance、没有处理 821 个 mismatch units。

## 1. 上游一致性

A/B Cartesian state：64/64 units 均为 0 error。station、C（适用时）、timestamps、carrier frequency、constants、units 和 dtype 均一致；因此 earliest divergence 保持 `LEVEL_4_DOPPLER_GEOMETRY`。

## 2. Failing identities

冻结门限下 failing units=30，failing rows=160。失败集中于：active_compensation_first_pass, score_only_verifier_and_synthetic_orbit_attacks。逐 identity、最大差异 timestamp、old/new geometry、compensation、residual、OLS 和 score 见 `outputs/metrics/causal_a_doppler_r1_failing_identity_audit.csv`。

## 3. 离散结构与 ULP

在 11.325 GHz full-frequency intermediate，`numpy.spacing(11_325_000_000.0) = 1.9073486328125e-06 Hz`。该值正是观察到的 `1.9073486328125e-6 Hz` 量级；差异表中的整数倍见 `outputs/metrics/causal_a_doppler_r1_geometry_ulp_audit.csv`。旧 geometry artifacts 的 full-frequency 文本约为 6 位小数，float64 reload 后受 GHz-scale ULP 限制。active compensation 是两条 geometry 曲线之差，误差达到约两倍 ULP 是预期传播。

## 4. Formula / dtype / version

legacy candidate/library、legacy fixed-reference 和 new wrapper 使用等价的 `f_geo = freq - freq * gradient(range_m) / C_MPS` 定义，`C_MPS=299792458.0`、carrier=11325000000.0、数组为 float64。没有证据支持真实 code/math divergence；差异来自历史 full-frequency serialization 后的 float64 表示。逐函数 source hash 见 `outputs/metrics/causal_a_doppler_r1_implementation_path_comparison.csv`。

## 5. High-precision reference

使用 80 decimal digits 的 mpmath norm/range-rate arithmetic，输入为相同 Skyfield positions，计算 30 个 deterministic direct-family samples。由于 initial/active direct rows 全部是 frozen-R1 failures，本受限集合没有可用 passing direct row；没有用伪造或替代样本填充。结果见 `outputs/metrics/causal_a_doppler_r1_high_precision_reference.csv`。

## 6. Error propagation

geometry max=1.9073486328125e-06 Hz，compensation max=3.814755473285913e-06 Hz，residual max=3.814755473285913e-06 Hz，b_hat max=8.246570359915496e-08 Hz，k_hat max=1.627995516173542e-09 Hz/s，score max=1.615171640878543e-07 Hz。独立保守传播 bound 全部覆盖观察值，详见 `outputs/metrics/causal_a_doppler_r1_error_propagation_audit.csv`。

## 7. Passing / failing pattern

R1 state 64/64 通过；generated multipass/altitude geometry 64 units 中 34 units 的全层级 rows 通过，而 direct initial/active 30 units 因旧 full-frequency serialization/float path 失败。所有 categorical mismatch 仍为 0，不能据此忽略 numerical gate。

## 8. Frozen tolerance feasibility

本轮不修改 tolerance。证据表明，对当前 serialized legacy artifacts，geometry/compensation 的 1e-6 Hz 与 k_hat 的 1e-9 Hz/s 接近或低于可重复实现的 numerical floor，属于 `NUMERICALLY_OVERSTRICT` 风险；是否发布 protocol erratum 必须由下一轮基于独立 bound 决定，不能用 observed max 直接调参。

## 9. 结论

根因分类：`HISTORICAL_SERIALIZATION_QUANTIZATION`。没有证据支持 `TRUE_IMPLEMENTATION_DIFFERENCE` 或 categorical science behavior change。

正式状态：`R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC`

R2 AUTHORIZED: `NO`

NEXT STEP: `R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION`
