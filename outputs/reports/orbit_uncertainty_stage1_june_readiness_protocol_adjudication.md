# June Stage-1A readiness protocol adjudication

状态：`JUNE_STAGE1A_PROTOCOL_ADJUDICATED_CAUSAL_READY`

本 amendment 只解决 Stage-1A engineering readiness 与 Stage-1F scientific support 的语义冲突。它在任何 June RTN residual、Stage-1F score、P95/P99 coverage、false-orbit-distinct rate 或逐星 confirmatory performance 被读取或计算之前完成。

## 1. Provenance finding

- `72 h` 的历史来源是 ordinary-GP acquisition pre-window/lookback，并在 Stage-1A/早期 Stage-1B correctness 中被用作 engineering readiness check。它不是 uncertainty model 的 scientific support，也不是 safety threshold。
- Stage-1F-lite 的 formal scientific support 独立冻结为 `0 < element_age_hours <= 36`；freshness bins、candidate identity、frozen parameters、empirical P95/P99 threshold 和 June success rule 均未改变。
- April/May 的 `>72 h=0`，因此本 clarification 不要求回写或重跑任何历史 artifact。

72 h 历史角色判定：

| Candidate role | Provenance decision |
|---|---|
| A. causal lookback acquisition support | `true` |
| B. Stage-1A engineering/readiness condition | `true` |
| C. scientific uncertainty support | `false` |
| D. safety threshold | `false` |

## 2. OLD RULE

Legacy June Stage-1A implementation 将任何 selected ordinary-GP element age `>72 h` 作为 task-level completion blocker。因此 June 虽然 `5927/5927` rows 均有合法 causal candidate，仍得到 `JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H`。

该旧状态保留为历史 provenance，不覆盖、不删除。

## 3. NEW CLARIFIED RULE: CAUSAL_DATA_READINESS_V2

1. 每个真实 SupGP evaluation row 必须存在 causal ordinary-GP candidate。
2. `CREATION_DATE <= evaluation_time`；选择顺序保持 latest `CREATION_DATE` → latest `EPOCH` → `GP_ID`。
3. future publication use、selected GP epoch after evaluation、negative element age、negative publication age必须均为0。
4. 满足上述 causal validity 的 rows 全部允许进入 canonical Stage-1B residual library。
5. element age `>72 h` 标记为 `ENGINEERING_STALENESS_GT72H`，但它本身不再阻塞 Stage-1B construction。
6. Stage-1F formal eligibility 仍只由 `0 < element_age_hours <=36` 决定；`>36 h` 一律 `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`。

Readiness states：`READY_CAUSAL_SUPPORTED`、`READY_WITH_GT72H_STALENESS`、`BLOCKED_MISSING_CAUSAL_SUPPORT`、`BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION`。

## 4. June adjudication

- SupGP evaluations：5927
- causal candidate：5927/5927
- future publication use：0
- selected GP EPOCH after evaluation：0
- negative element/publication age：0/0
- nonpositive element age：0
- element age >36 h：538
- element age >72 h：25，affected satellites=['47383', '47767', '47844', '48458', '60265', '65409', '65421']
- >72 h subset of >36 h：25/25
- V2 per-satellite status counts：{'READY_CAUSAL_SUPPORTED': 13, 'READY_WITH_GT72H_STALENESS': 7}
- cohort status：`READY_WITH_GT72H_STALENESS`

Targeted completeness audit 已确认7/7 satellites、65/65 same-window records完全一致，missing GP_ID=0、missing composite key=0、evaluation-time-before-published newer GP=0、25/25 rank-1 selection复现。因此25 rows是 real causal public-data staleness，不能也没有使用 later GP替换。

## 5. Stage effects

- Stage-1B：`5927/5927` causal-supported rows eligible for canonical construction。预期 canonical rows仍为5927；538 rows和其中25个>72 h rows均不得删除、截断或替换。
- Stage-1F：future primary confirmatory rows=`5389`；outside support=`538`。outside rows不产生formal ellipsoid/box classification、P95/P99 coverage或false-orbit-distinct contribution，只输出`DEFER`。
- Stage-1F scientific protocol changed=`false`。

## 6. Why this is not post-hoc model tuning

本 amendment 不接触 June scientific outcomes，只澄清 input readiness 与 model support 的职责边界。它不改变 primary/secondary candidate、center、covariance、scale、c95/c99、freshness support/bins、complexity rule、model-selection rule、decision semantics或June pass/fail criteria。Frozen parameter SHA仍为`6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1`。

## 7. Decision

没有科学理由仅因真实 causal element age `>72 h` 阻止完整 canonical residual library 的生成；这些rows对 public-data availability 的描述本身有价值。科学约束在 Stage-1F gate处执行：全部`>36 h` rows保留但`DEFER`。

因此确有必要在不查看 June residual 的前提下完成这次 protocol adjudication；否则会把 input availability policy 错当成 frozen model support，并无依据地丢失真实 causal rows。

`JUNE_STAGE1A_PROTOCOL_ADJUDICATED_CAUSAL_READY`

NEXT STEP: `JUNE_STAGE1B_RESIDUAL_LIBRARY_CONSTRUCTION`
