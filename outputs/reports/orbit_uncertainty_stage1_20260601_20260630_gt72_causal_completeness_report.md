# June >72 h causal GP completeness audit

## 1. Scope

本轮只审计ordinary-GP historical availability。未生成或读取RTN residual、Stage-1F score、P95/P99 coverage或security classification；没有修改当前1693-record raw，也没有将future publication代入历史evaluation。

## 2. Targeted query

- affected NORAD：['47383', '47767', '47844', '48458', '60265', '65409', '65421']
- requested EPOCH window：`[2026-06-18T00:00:00Z, 2026-06-25T00:00:00Z)`
- raw response：`data/orbit_uncertainty_stage1/audits/spacetrack_gp_history_20260618_20260625_7sat_gt72_completeness.json`
- raw SHA：`A96A1A8426F0AE27994FA871A0CF08FC378C23C9894B01170502E03E1A75E126`
- response records：65；local half-open window records：65；outside records：0
- returned satellites：7/7
- reused without network：False

## 3. Comparison with frozen Stage-1A raw

- targeted records not in current raw by GP_ID：0
- targeted records not in current raw by NORAD+EPOCH+CREATION_DATE：0
- union missing records：0
- Class A, causally eligible and newer at an affected evaluation：0
- Class B, published only after affected evaluations：0

[
  {
    "NORAD_CAT_ID": "47383",
    "affected_evaluation_count": 6,
    "targeted_query_records": 8,
    "current_raw_records_in_targeted_epoch_window": 8,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "47767",
    "affected_evaluation_count": 1,
    "targeted_query_records": 11,
    "current_raw_records_in_targeted_epoch_window": 11,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "47844",
    "affected_evaluation_count": 3,
    "targeted_query_records": 9,
    "current_raw_records_in_targeted_epoch_window": 9,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "48458",
    "affected_evaluation_count": 2,
    "targeted_query_records": 9,
    "current_raw_records_in_targeted_epoch_window": 9,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "60265",
    "affected_evaluation_count": 5,
    "targeted_query_records": 8,
    "current_raw_records_in_targeted_epoch_window": 8,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "65409",
    "affected_evaluation_count": 2,
    "targeted_query_records": 11,
    "current_raw_records_in_targeted_epoch_window": 11,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  },
  {
    "NORAD_CAT_ID": "65421",
    "affected_evaluation_count": 6,
    "targeted_query_records": 9,
    "current_raw_records_in_targeted_epoch_window": 9,
    "targeted_not_in_raw_by_gp_id": 0,
    "targeted_not_in_raw_by_composite_key": 0,
    "class_a_causally_eligible_newer": 0,
    "class_b_published_only_after": 0
  }
]

## 4. The 25 evaluations

全部25行均保留在`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_cases.csv`；每行的最近5个causal publications共125行，保存在`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_recent_causal_publications.csv`。每个case的rank 1均复现当前selected GP。

## 5. Scientific conclusion

`JUNE_GT72H_IS_REAL_CAUSAL_PUBLIC_DATA_STALENESS`

没有发现evaluation-time之前已经发布、EPOCH又比当前selected GP更新、但缺失于当前raw的记录。因此不能用今天获得的later GP“修复”这25个历史case；它们是当时public ordinary-GP availability/staleness事实，不是acquisition漏记录。

## 6. 72 h versus 36 h semantics

- 72 h：Stage-1A ordinary-GP acquisition lookback/readiness policy，用于输入可用性与因果准备度审计；不是Stage-1F uncertainty model的scientific support。
- 36 h：Stage-1F-lite冻结的scientific support，精确定义为`0 < element_age_hours <= 36`。
- 本次25个>72 h rows全部同时满足`element_age_hours >36`，因此全部属于`OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`。

这两个阈值不能互相替代，也没有在本轮修改。由于72 h是早期Stage-1A readiness policy，而25行在Stage-1F中本就DEFER，进入Stage-1B前需要在不查看June residual的前提下对Stage-1A task-level readiness进行protocol adjudication；本报告不代替该科研决定。
