# Causal-A Doppler reconstruction reproduction validation rerun (R1)

## 1. Result

`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`

Primary population 使用 erratum 后的 64 units / 6,280 rows；200 verifier-v2 rows 仅作 secondary cross-check。未处理 821 个 A-semantics-mismatch units，也未进行 orbit-distinct security analysis。

## 2. Numerical reproduction

| Quantity | Maximum error |
|---|---:|
| A position norm | 0 km |
| A velocity norm | 0 km/s |
| B position norm | 0 km |
| B velocity norm | 0 km/s |
| Doppler geometry | 1.90734863281e-06 Hz |
| active compensation | 3.81475547329e-06 Hz |
| observation | 3.81469726562e-06 Hz |
| residual | 3.81475547329e-06 Hz |
| b_hat | 8.24657035992e-08 Hz |
| k_hat | 1.62799551617e-09 Hz/s |
| score | 1.61517164088e-07 Hz |
| score relative | 1.27427901556e-09 |

所有 pass/fail 均使用 R0 protocol 已冻结 tolerance，没有新增或放宽阈值。

## 3. Categorical reproduction

| Check | Mismatches |
|---|---:|
| score gate | 0 |
| b gate | 0 |
| k gate | 0 |
| coverage | 0 |
| quality gate | 0 |
| final decision | 0 |

## 4. Correctness and provenance

| check                                    |   expected |   observed | passed   |
|:-----------------------------------------|-----------:|-----------:|:---------|
| primary_expected_units                   |         64 |         64 | True     |
| primary_expected_rows                    |       6280 |       6280 | True     |
| secondary_expected_rows                  |        200 |          0 | False    |
| primary_secondary_overlap                |          0 |          0 | True     |
| future_publication_count                 |          0 |          0 | True     |
| new_random_draw_count                    |          0 |          0 | True     |
| replayed_random_vector_count             |       2040 |       2040 | True     |
| semantics_mismatch_units_executed        |          0 |          0 | True     |
| legacy_source_modifications              |          0 |          0 | True     |
| frozen_threshold_modifications           |          0 |          0 | True     |
| frozen_b_k_modifications                 |          0 |          0 | True     |
| orbit_uncertainty_artifact_modifications |          0 |          0 | True     |
| spotcheck_rows                           |         30 |         30 | True     |
| spotcheck_failures                       |          0 |          4 | False    |

Independent spot-check 使用 `SHA256('R1_SPOTCHECK_V1|' + stable_row_identity)` 的 deterministic stratified selection，先覆盖 family × old-decision strata，再按 hash 补足 30 rows。结果：26/30 pass。

Verifier-v2 secondary cross-check：`LIMITATION`，未执行（PRIMARY_FAILED）。

## 5. Required answers

1. Primary units：64/64 covered；34/64 通过全部 reproduction levels。
2. Primary rows：6120/6280 通过全部 reproduction levels；categorical requirements 见上表。
3. A state 最大 position/velocity error：0 km / 0 km/s。
4. B state 最大 position/velocity error：0 km / 0 km/s。
5. Doppler geometry 最大误差：1.90734863281e-06 Hz。
6. Active compensation 最大误差：3.81475547329e-06 Hz。
7. Residual 最大误差：3.81475547329e-06 Hz。
8. b_hat 最大误差：8.24657035992e-08 Hz。
9. k_hat 最大误差：1.62799551617e-09 Hz/s。
10. Score 最大误差：1.61517164088e-07 Hz。
11-15. score/b/k/coverage/final mismatch：0/0/0/0/0。
16. Frozen numerical tolerance：未全部通过。
17. Earliest divergence layer：`LEVEL_4_DOPPLER_GEOMETRY`。
18. Verifier-v2：`LIMITATION`。
19. 30-row spot-check：26/30。
20. Reconstruction implementation 不改变 verifier science：不支持。
21. R2 authorization：NO。

## 6. Formal status

`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`

`R1 PRIMARY: FAIL`

`PRIMARY POPULATION: 64 units / 6280 rows`

`VERIFIER-V2 CROSSCHECK: LIMITATION`

`R2 AUTHORIZED: NO`

`NEXT STEP: STOP_AT_R1_EARLIEST_DIVERGENCE`
