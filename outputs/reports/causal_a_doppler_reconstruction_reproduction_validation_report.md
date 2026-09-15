# Causal-A Doppler reconstruction reproduction validation (R1)

## 1. Formal result

`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`

R1 在任何 state propagation、Doppler geometry、random replay、OLS 或 verifier execution 之前，由 frozen-population provenance gate 阻止。失败不是 numerical mismatch，而是 R0 population count 与 authoritative row binding 不一致。

## 2. Frozen population inconsistency

R0 protocol 同时冻结：

- primary reproduction rows = 6,480
- verifier-v2 secondary rows = 200

这要求两个互斥层级共 6,680 rows。但 authoritative relabel binding 实际只有 6,480 rows，其中 primary source 为 6,280，verifier-v2 derived view 为 200：

| experiment_family                               | r1_role               |   rows |
|:------------------------------------------------|:----------------------|-------:|
| active_compensation_first_pass                  | PRIMARY_SOURCE        |     60 |
| controlled_altitude_difference_synthetic_B      | PRIMARY_SOURCE        |   5400 |
| same_pair_multi_pass_real_TLE                   | PRIMARY_SOURCE        |    720 |
| score_only_verifier_and_synthetic_orbit_attacks | PRIMARY_SOURCE        |    100 |
| score_only_verifier_and_synthetic_orbit_attacks | SECONDARY_VERIFIER_V2 |    200 |

因此不能达到 `6480/6480 primary rows`。将 verifier-v2 的 200 rows 同时计入 primary 和 secondary 会重复计数；补造 200 rows 或重新选择 population 均违反冻结规则。

## 3. Unit provenance

64/64 units 可由 authoritative state audit 唯一恢复，且状态全部属于 `EXACT_ORBIT_SOURCE_MATCH` 或 `DETERMINISTIC_EQUIVALENT_RECONSTRUCTION`。没有 unit 被静默删除。但 R0 manifest 只记录数量，没有嵌入具体 unit list；本轮已在 state reproduction artifact 中固化该 64-unit identity。

## 4. Reproduction hierarchy

| Level | Quantity | R1 status |
|---|---|---|
| 1 | A state | NOT EXECUTED |
| 2 | B state | NOT EXECUTED |
| 3 | Doppler geometry | NOT EXECUTED |
| 4 | active compensation | NOT EXECUTED |
| 5 | observation residual | NOT EXECUTED |
| 6 | b_hat / k_hat | NOT EXECUTED |
| 7 | score | NOT EXECUTED |
| 8 | gates / coverage | NOT EXECUTED |
| 9 | final decision | NOT EXECUTED |

最早 divergence layer：`PROVENANCE_UNKNOWN / FROZEN_POPULATION_INCONSISTENCY`。

## 5. Required answers

1. 64/64 frozen units 已恢复 identity，但 numerical reproduction 未执行。
2. 6480/6480 primary rows：否；authoritative primary 只有 6,280。
3. A state 最大 R1 数值差异：`NOT_EVALUATED`。
4. B state 最大 R1 数值差异：`NOT_EVALUATED`。
5. Doppler geometry 最大差异：`NOT_EVALUATED`。
6. active compensation 最大差异：`NOT_EVALUATED`。
7. residual 最大差异：`NOT_EVALUATED`。
8. b_hat 最大差异：`NOT_EVALUATED`。
9. k_hat 最大差异：`NOT_EVALUATED`。
10. score 最大差异：`NOT_EVALUATED`。
11. score gate mismatch：`NOT_EVALUATED`。
12. b gate mismatch：`NOT_EVALUATED`。
13. k gate mismatch：`NOT_EVALUATED`。
14. coverage mismatch：`NOT_EVALUATED`。
15. final ACCEPT/REJECT mismatch：`NOT_EVALUATED`。
16. frozen numerical tolerances：未进入适用阶段，不能判 PASS。
17. 200 verifier-v2 cross-check：`LIMITATION_NOT_RUN_PRIMARY_POPULATION_GATE_FAILED`。
18. 最早失败层：frozen population provenance。
19. 尚未证明 semantic wrapper 在 A semantics 不变时保持 verifier science。
20. 不满足进入 `CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION` 的条件。

## 6. Resolution required

必须先发布一个明确的 R0 population erratum，只能二选一：

1. primary = 6,280，secondary verifier-v2 = 200，总绑定 = 6,480；或
2. 明确另外 200 条不属于 verifier-v2 derived view 的 authoritative primary rows 及其 identities/source SHA。

在 population 定义被正式修正前，R1 保持失败状态，不进入 R2。
