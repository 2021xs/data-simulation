# Orbit Uncertainty Stage-1A：historical SupGP ingestion audit

## 1. 范围与方法边界

本报告只审计 historical SupGP ingestion 与 reference quality，不传播轨道、不执行 ordinary-GP→SupGP pairing、不计算 RTN/residual、不建立 uncertainty boundary，也不运行 synthetic-B 或 Doppler verifier。SupGP 始终按 operator-derived higher-quality reference 表述，不作为 ground truth。

- formal window：`[2026-03-01T00:00:00Z, 2026-03-29T00:00:00Z)`
- target shell：项目既有 controlled Starlink 20-target cohort，约 53.16° / 473 km proxy；结论不外推至整个 Starlink constellation
- raw CSV 文件：20
- target coverage：20/20
- total records：2050
- formal-window records：2050
- raw returned span across cohort：`2026-03-01T02:57:42.000019Z` 至 `2026-03-28T23:59:42.000029Z`
- non-target NORAD records：[]

### 仓库实现审计

- `scripts/prepare_orbit_uncertainty_stage1a_design.py`：Stage-1A 设计/请求清单生成器，属于 acquisition 前的 design artifact，不是 SupGP production ingestion。
- `scripts/acquire_orbit_uncertainty_stage1.py`：ordinary GP acquisition 已是 production-style、支持 `--reuse-only` 并正确保留 duplicate GP records；其 SupGP 部分已有 file discovery、source/RMS/epoch/gap 简化审计，但历史输出仍停在 `WAITING_FOR_SUPGP`，且缺少本轮要求的 formal count、required-field value audit、RMS p90/p95、p95 gap、duplicate variant 分类和三态 gate 明细。
- `scripts/run_orbit_uncertainty_stage0_starlink_smoke.py`：三星 exploratory smoke，已有可复用的 SupGP CSV parser、`sgp4.omm.initialize`、SGP4 propagation、TEME→GCRS 与 RTN 工具。本 gate 只复用其 schema/初始化约定，没有调用 propagation/RTN/residual。
- 既有 Stage-1 acquisition 输出目录为 `outputs/metrics/` 与 `outputs/reports/`；raw 固定在 `data/orbit_uncertainty_stage1/raw/`。本轮沿用该目录，不覆盖旧 acquisition baseline 输出。
- 现有 targeted tests 覆盖 parser、formal-window、duplicate preservation、source、gap、status 与 report semantic consistency。
- actual CSV schema 为 19 列 CelesTrak SupGP CSV，包含 Stage-0 已验证的 17 个 SGP4-compatible orbital fields，以及 `RMS`、`DATA_SOURCE`；不包含 `CREATION_DATE`。

## 2. Reference-quality gate

- READY = 0
- PARTIAL = 20
- NO_REFERENCE = 0

READY/PARTIAL 的 coverage 判断沿用 acquisition pipeline 已记录的 engineering rule：formal-window 两端各 24 h 容差、内部 gap > 48 h 记作 large gap。它们只用于 ingestion readiness，不是轨道不确定性的科学阈值。RMS 不设 acceptance cutoff。

| norad_id | status | records | first_epoch | last_epoch | rms_median_km | rms_p95_km | rms_max_km | max_gap_h | large_gap_intervals | variant_groups | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 44714 | PARTIAL | 101 | 2026-03-01T04:51:41.999962Z | 2026-03-28T21:06:42.000019Z | 0.24 | 0.413 | 0.666 | 65.666667 | 2026-03-16T09:22:42.000010Z--2026-03-19T03:02:42Z (65.666667 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65686 | PARTIAL | 105 | 2026-03-01T02:58:41.999981Z | 2026-03-28T21:39:41.999962Z | 0.267 | 1.4384 | 7.676 | 74.2 | 2026-03-16T03:06:42.000019Z--2026-03-19T05:18:41.999962Z (74.200000 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65421 | PARTIAL | 108 | 2026-03-01T02:57:42.000019Z | 2026-03-28T21:32:41.999971Z | 0.2795 | 1.1021 | 6.009 | 74.266667 | 2026-03-16T03:07:41.999981Z--2026-03-19T05:23:42.000029Z (74.266667 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 65409 | PARTIAL | 107 | 2026-03-01T03:06:42.000019Z | 2026-03-28T22:22:42.000038Z | 0.294 | 1.1537 | 5.409 | 74.233333 | 2026-03-16T03:05:41.999971Z--2026-03-19T05:19:42.000010Z (74.233333 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 65410 | PARTIAL | 107 | 2026-03-01T03:05:41.999971Z | 2026-03-28T21:28:42.000038Z | 0.259 | 0.7019 | 5.623 | 74.283333 | 2026-03-16T03:00:41.999990Z--2026-03-19T05:17:42Z (74.283333 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 47749 | PARTIAL | 99 | 2026-03-01T04:30:41.999990Z | 2026-03-28T22:32:42Z | 0.364 | 0.6166 | 0.943 | 67.5 | 2026-03-16T08:13:41.999981Z--2026-03-19T03:43:41.999981Z (67.500000 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 47383 | PARTIAL | 100 | 2026-03-01T04:41:42Z | 2026-03-28T21:16:41.999981Z | 0.2595 | 0.52605 | 0.614 | 68.033333 | 2026-03-16T07:46:41.999981Z--2026-03-19T03:48:41.999962Z (68.033333 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65411 | PARTIAL | 104 | 2026-03-01T03:06:42.000019Z | 2026-03-28T22:20:42.000029Z | 0.2755 | 2.8239 | 5.777 | 74.316667 | 2026-03-16T03:04:42.000010Z--2026-03-19T05:23:42.000029Z (74.316667 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 48309 | PARTIAL | 100 | 2026-03-01T04:29:42.000029Z | 2026-03-28T21:55:42.000038Z | 0.2515 | 1.1841 | 3.113 | 67.033333 | 2026-03-16T08:53:42Z--2026-03-19T03:55:42.000038Z (67.033333 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 45230 | PARTIAL | 96 | 2026-03-01T04:55:41.999981Z | 2026-03-28T23:28:42.000010Z | 0.2735 | 0.4715 | 0.865 | 67.033333 | 2026-03-16T08:13:41.999981Z--2026-03-19T03:15:42.000019Z (67.033333 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 47844 | PARTIAL | 101 | 2026-03-01T03:05:41.999971Z | 2026-03-28T20:23:42.000029Z | 0.249 | 0.523 | 0.599 | 75.016667 | 2026-03-16T00:53:42.000029Z--2026-03-19T03:54:41.999990Z (75.016667 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65407 | PARTIAL | 103 | 2026-03-01T02:58:41.999981Z | 2026-03-28T21:28:42.000038Z | 0.275 | 1.3672 | 5.897 | 74.383333 | 2026-03-16T03:00:41.999990Z--2026-03-19T05:23:42.000029Z (74.383333 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 47767 | PARTIAL | 102 | 2026-03-01T04:42:41.999962Z | 2026-03-28T23:01:42.000010Z | 0.324 | 0.6477 | 1.963 | 66.433333 | 2026-03-16T08:58:41.999981Z--2026-03-19T03:24:42.000019Z (66.433333 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65405 | PARTIAL | 104 | 2026-03-01T03:02:42Z | 2026-03-28T23:06:41.999990Z | 0.281 | 1.23895 | 6.047 | 74.333333 | 2026-03-16T03:00:41.999990Z--2026-03-19T05:20:41.999971Z (74.333333 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 48672 | PARTIAL | 99 | 2026-03-01T04:47:42.000029Z | 2026-03-28T23:29:41.999971Z | 0.258 | 0.6719 | 2.827 | 67.266667 | 2026-03-16T08:24:41.999990Z--2026-03-19T03:40:42.000010Z (67.266667 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 48111 | PARTIAL | 101 | 2026-03-01T04:38:42.000029Z | 2026-03-28T23:50:42.000029Z | 0.241 | 0.359 | 0.495 | 67.166667 | 2026-03-16T08:32:42.000029Z--2026-03-19T03:42:42.000019Z (67.166667 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 65693 | PARTIAL | 104 | 2026-03-01T03:03:41.999962Z | 2026-03-28T22:27:42.000019Z | 0.26 | 2.6074 | 7.873 | 74.35 | 2026-03-16T02:59:42.000029Z--2026-03-19T05:20:41.999971Z (74.350000 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 60265 | PARTIAL | 103 | 2026-03-01T03:20:42Z | 2026-03-28T21:38:42Z | 0.25 | 0.2779 | 1.344 | 72.383333 | 2026-03-16T04:42:41.999962Z--2026-03-19T05:05:42.000029Z (72.383333 h) | 1 | 存在超过既有 engineering large-gap rule 的内部时间缺口；同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 |
| 58380 | PARTIAL | 105 | 2026-03-01T04:02:42.000029Z | 2026-03-28T23:59:42.000029Z | 0.251 | 1.0382 | 4.291 | 70.75 | 2026-03-16T05:49:41.999981Z--2026-03-19T04:34:42.000010Z (70.750000 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |
| 48458 | PARTIAL | 101 | 2026-03-01T04:44:41.999971Z | 2026-03-28T23:25:42.000038Z | 0.248 | 0.626 | 2.717 | 66.45 | 2026-03-16T08:51:41.999990Z--2026-03-19T03:18:41.999990Z (66.450000 h) | 0 | 存在超过既有 engineering large-gap rule 的内部时间缺口 |

逐星 status reason 由与 quality classification 相同的 `classify_status()` 动态重算；如果 report 与 quality status 不一致，报告生成会直接失败。

| gate_warning | satellites |
| --- | --- |
| 存在超过既有 engineering large-gap rule 的内部时间缺口 | 20 |
| 同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则 | 7 |

当前 coverage warning 摘要：formal-window boundary incomplete=0/20，internal gap > 48 h=20/20，same-epoch variant=7/20 颗、共 7 组。逐星原生 reference span、large-gap interval 与全部 excluded intervals 以 quality CSV 为准；这些区间不代表自动插值、补值或批准进入 segmented pilot。

## 3. DATA_SOURCE audit

- distribution：`{"SpaceX-E": 2050}`
- source switch satellites：0
- missing DATA_SOURCE：0

当前 source 统计由本次输入动态生成。若 source switch satellites 或 missing DATA_SOURCE 非零，相关对象会在逐星 reason 中标记为 PARTIAL；本 gate 不自动合并不同 source。

## 4. RMS descriptive audit

RMS 单位沿用 Stage-0 已记录的 CelesTrak SupGP fit-RMS 语义（km）。本报告给出 min/median/p90/p95/max，并复用 Stage-0 的 robust-z > 3.5 规则标记描述性检查候选；该规则不剔除记录、不改变 quality status，也不能单独证明 maneuver/regime change。

| norad_id | rms_max_km | robust_candidates | sudden_spikes | longest_run | run_start | run_end |
| --- | --- | --- | --- | --- | --- | --- |
| 65693 | 7.873 | 12 | 5 | 4 | 2026-03-27T09:23:41.999971Z | 2026-03-27T18:54:41.999990Z |
| 65686 | 7.676 | 10 | 5 | 4 | 2026-03-03T07:16:42.000010Z | 2026-03-04T10:54:42.000019Z |
| 65405 | 6.047 | 9 | 5 | 2 | 2026-03-01T10:51:41.999962Z | 2026-03-01T18:52:41.999981Z |
| 65421 | 6.009 | 11 | 5 | 4 | 2026-03-26T23:13:41.999981Z | 2026-03-27T08:32:42.000029Z |
| 65407 | 5.897 | 10 | 4 | 4 | 2026-03-04T10:51:41.999962Z | 2026-03-05T02:46:42.000010Z |
| 65411 | 5.777 | 11 | 4 | 3 | 2026-03-02T10:59:42Z | 2026-03-03T01:24:41.999962Z |
| 65410 | 5.623 | 9 | 7 | 3 | 2026-03-02T18:07:41.999981Z | 2026-03-03T07:18:42.000019Z |
| 65409 | 5.409 | 11 | 5 | 4 | 2026-03-23T03:59:41.999971Z | 2026-03-23T15:00:41.999990Z |
| 58380 | 4.291 | 10 | 5 | 5 | 2026-03-19T04:34:42.000010Z | 2026-03-20T14:14:42.000029Z |
| 48309 | 3.113 | 11 | 7 | 5 | 2026-03-04T03:52:41.999981Z | 2026-03-05T12:43:41.999981Z |
| 48672 | 2.827 | 8 | 3 | 4 | 2026-03-11T17:27:41.999962Z | 2026-03-12T20:20:41.999971Z |
| 48458 | 2.717 | 12 | 5 | 7 | 2026-03-07T04:29:42.000029Z | 2026-03-09T03:33:42.000019Z |
| 47767 | 1.963 | 5 | 3 | 4 | 2026-03-12T20:00:41.999962Z | 2026-03-13T18:39:41.999962Z |
| 60265 | 1.344 | 5 | 2 | 3 | 2026-03-24T06:51:42.000019Z | 2026-03-24T14:32:42.000029Z |
| 47749 | 0.943 | 1 | 1 | 1 | 2026-03-25T23:07:42.000038Z | 2026-03-25T23:07:42.000038Z |
| 45230 | 0.865 | 2 | 2 | 1 | 2026-03-25T03:20:42Z | 2026-03-25T03:20:42Z |
| 44714 | 0.666 | 2 | 2 | 1 | 2026-03-05T05:12:42.000019Z | 2026-03-05T05:12:42.000019Z |
| 47383 | 0.614 | 1 | 1 | 1 | 2026-03-27T23:16:42.000038Z | 2026-03-27T23:16:42.000038Z |
| 47844 | 0.599 | 2 | 2 | 1 | 2026-03-15T16:27:42.000019Z | 2026-03-15T16:27:42.000019Z |
| 48111 | 0.495 | 1 | 0 | 1 | 2026-03-01T04:38:42.000029Z | 2026-03-01T04:38:42.000029Z |

`rms_high_candidate_longest_run` 用来观察候选是否连续；所有逐星数值见 quality CSV。Stage-0 对 65411 的 `possible_regime_change` 仍只是 exploratory label，本报告不升级为 confirmed maneuver。

## 5. Coverage / gap audit

- formal-window boundary-incomplete satellites：0/20
- internal gap > 48 h satellites：20/20
- cohort max internal gap：75.016667 h
- raw-order inversion satellites：0
- EPOCH parse errors：0
- obvious-year anomalies：0

CSV EPOCH 字符串本身无 `Z`/offset；按 CelesTrak SupGP schema 与既有 Stage-0 解析约定显式当作 UTC，并在 quality CSV 中记录 assumed count。CSV 不含 `CREATION_DATE`；这不妨碍其作为离线 reference，但它不能替代 ordinary GP 的 causal `CREATION_DATE <= evaluation_time` 选择逻辑。

## 6. Duplicate audit

- duplicate epoch excess records：7
- duplicate epoch groups：7
- exact duplicate excess records：0
- same-epoch variant groups：7
- same-epoch variant satellites：7/20

原始记录未修改、未按 EPOCH 去重。当前 duplicate detail 记录 7 个 duplicate epoch group：exact duplicate excess records=0，same-epoch variant groups=7；每组保存 source/RMS/orbital-field 差异和 raw location。

## 7. Schema / required-field audit

- required orbital-field missing values：0
- invalid required numeric values：0
- SGP4 OMM initialization errors：0
- propagation-ready formal records：2050/2050

required field set 直接复用 Stage-0 已成功使用的 CelesTrak SupGP→`sgp4.omm.initialize` schema。本轮只初始化 state object 做 schema/value validation，没有执行任何 epoch propagation。

## 8. Stage-1B readiness

当前**不具备按既定 20 星 × 28 天口径进入 formal Stage-1B residual library 的条件**。当前 gate 状态为 READY=0、PARTIAL=20、NO_REFERENCE=0；20/20 颗具有可初始化的 formal-window reference。完整连续 coverage 未通过的实际 warning 已在逐星表和 `excluded_intervals` / `large_internal_gap_intervals` 字段中列出。是否采用 segmented pilot 必须另行冻结政策，本 gate 不插值、不补值，也不自动选择 same-epoch variant。

要进入既定 formal 20 × 28-day Stage-1B，必须先解决本次逐星 gate reason 与 `excluded_intervals` 中实际列出的 reference-quality 问题。不得使用 later ordinary GP、插值、current SupGP 或 Stage-0 三星文件冒充缺失 reference；本报告也不替科研决策选择 same-epoch variant 或制定 RMS cutoff。

## 9. 输出与限制

- quality table：`outputs/metrics/orbit_uncertainty_stage1_supgp_reference_quality.csv`
- raw inventory：`outputs/metrics/orbit_uncertainty_stage1_supgp_raw_inventory.csv`
- duplicate audit：`outputs/metrics/orbit_uncertainty_stage1_supgp_duplicate_epoch_audit.csv`
- manifest：`outputs/metrics/orbit_uncertainty_stage1_supgp_reference_quality_manifest.json`
- 本报告：`outputs/reports/orbit_uncertainty_stage1_supgp_ingestion_audit.md`

本 pilot 仅代表当前约 53.16° / 473 km proxy 的 Starlink shell。RMS spike、element episode 或 Stage-0 label 均不等于 confirmed maneuver；本轮没有建立 universal km threshold。
