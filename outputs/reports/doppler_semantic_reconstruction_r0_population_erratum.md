# Doppler semantic reconstruction R0 population erratum

## 1. Erratum decision

本 erratum 仅修正 R0 reproduction population 的 row-count accounting：

| Population | Original R0 | Corrected |
|---|---:|---:|
| compatible units | 64 | 64 |
| primary source rows | 6,480 | 6,280 |
| verifier-v2 secondary rows | 200 | 200 |
| total bound rows | implied 6,680 | 6,480 |

原 R0 中“6,480 primary”确认是 accounting error：该数值实际等于 primary 与 V2 secondary 的 union。authoritative binding 中不存在额外 200 条独立 primary identities。

## 2. Identity-set audit

- `|PRIMARY_SET| = 6280`
- `|VERIFIER_V2_SECONDARY_SET| = 200`
- `intersection = 0`
- `union = 6480`
- compatible units = 64
- duplicate stable identities = 0
- missing identity fields = 0
- orphan rows = 0

Stable row identity schema：`SHA256(source_artifact + source_view + case_id + orbit_unit_id)`。

| Set | SHA-256 |
|---|---|
| PRIMARY_SET | `BC13C5AFD60912B0F45C886C54E69F0D0A4B1C90B68736F4E06FEA418AAD2987` |
| VERIFIER_V2_SECONDARY_SET | `BCE07DB0FC336FB122C70092F5FC4B9A35268574AC2519D1143D494894062B76` |
| TOTAL_BOUND_SET | `39E608E5A974A660B4BF9D915E8903A60A74307C53D1BA75F0EA457CC1262CD3` |
| compatible unit identity | `C0C52BB0142558BC2617CC017BC5F78EE7DF3EC5C9068208EB2DC12171C4E0CB` |

## 3. Unit-level accounting

| experiment_family                               |   compatible_units |   primary_rows |   secondary_rows |   total_rows |
|:------------------------------------------------|-------------------:|---------------:|-----------------:|-------------:|
| active_compensation_first_pass                  |                 10 |             60 |                0 |           60 |
| controlled_altitude_difference_synthetic_B      |                 30 |           5400 |                0 |         5400 |
| same_pair_multi_pass_real_TLE                   |                  4 |            720 |                0 |          720 |
| score_only_verifier_and_synthetic_orbit_attacks |                 20 |            100 |              200 |          300 |

完整 64-unit 逐项计数见 machine-readable identity audit；各 unit 的 row count 没有被假设为相同。

## 4. Scientific scope

`R0 scientific method changed = false`。

以下全部不变：64-unit identities、family membership、A compatibility rule、B semantics、causal-A reconstruction、Doppler production chain、active-compensation formula、draws/seeds、OLS、score、thresholds、b/k gates、coverage、ACCEPT/REJECT logic、numerical tolerances、R1 hierarchy、zero categorical mismatch requirement 和 R2 authorization rule。

- `POST_HOC_SCIENTIFIC_TUNING = false`
- `RESULT_DRIVEN_POPULATION_CHANGE = false`
- `POPULATION_IDENTITY_CHANGE = false`
- `ACCOUNTING_CORRECTION_ONLY = true`

第一次 R1 在 `PRE_LEVEL_1_POPULATION_GATE` 停止。A/B state、Doppler、compensation、residual、OLS、fit、score、gates、decision 和 spot-check 均为 `NOT_EVALUATED`，所有 numerical execution counters 为 0。因此本 erratum 发生在任何数值结果生成或查看之前。

## 5. Corrected R1 expectation

R1 primary pass/fail 重新冻结为：64/64 units 与 6,280/6,280 primary rows，全部原 numerical tolerances 通过且所有 categorical/final-decision mismatch 为 0。只有 primary PASS 后，才对 200/200 verifier-v2 secondary rows 做 cross-check。

## 6. Formal answers

1. Compatible units：64，未改变。
2. Primary identities：精确 6,280。
3. V2 secondary identities：精确 200。
4. Primary/secondary intersection：0。
5. Union：精确 6,480。
6. “6,480 primary”只是 accounting error：是。
7. 缺失的额外 200 primary identities：不存在。
8. Erratum 前生成/查看 numerical R1 result：否。
9. Scientific protocol 修改：否。
10. Corrected machine-readable binding：已生成。
11. R1 可以按 corrected denominator 重新执行，但本轮未执行。

## 7. Formal status

`R0_POPULATION_ERRATUM_PUBLISHED`

`CORRECTED R1 PRIMARY: 64 units / 6280 rows`

`R1 SECONDARY: 200 verifier-v2 rows`

`TOTAL BOUND: 6480 rows`

`SCIENTIFIC METHOD CHANGED: NO`

`NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN`
