# Orbit Uncertainty Stage-1A：historical SupGP ingestion audit

## 1. 范围与方法边界

本报告只审计 historical SupGP ingestion 与 reference quality，不传播轨道、不执行 ordinary-GP→SupGP pairing、不计算 RTN/residual、不建立 uncertainty boundary，也不运行 synthetic-B 或 Doppler verifier。SupGP 始终按 operator-derived higher-quality reference 表述，不作为 ground truth。

- formal window：`[2026-04-01T00:00:00Z, 2026-05-01T00:00:00Z)`
- target shell：项目既有 controlled Starlink 20-target cohort，约 53.16° / 473 km proxy；结论不外推至整个 Starlink constellation
- raw CSV 文件：20
- target coverage：20/20
- total records：5675
- formal-window records：5675
- raw returned span across cohort：`2026-04-01T00:04:42.000010Z` 至 `2026-04-30T23:46:42.000010Z`
- non-target NORAD records：[]

### 仓库实现审计

- `scripts/prepare_orbit_uncertainty_stage1a_design.py`：Stage-1A 设计/请求清单生成器，属于 acquisition 前的 design artifact，不是 SupGP production ingestion。
- `scripts/acquire_orbit_uncertainty_stage1.py`：ordinary GP acquisition 已是 production-style、支持 `--reuse-only` 并正确保留 duplicate GP records；其 SupGP 部分已有 file discovery、source/RMS/epoch/gap 简化审计，但历史输出仍停在 `WAITING_FOR_SUPGP`，且缺少本轮要求的 formal count、required-field value audit、RMS p90/p95、p95 gap、duplicate variant 分类和三态 gate 明细。
- `scripts/run_orbit_uncertainty_stage0_starlink_smoke.py`：三星 exploratory smoke，已有可复用的 SupGP CSV parser、`sgp4.omm.initialize`、SGP4 propagation、TEME→GCRS 与 RTN 工具。本 gate 只复用其 schema/初始化约定，没有调用 propagation/RTN/residual。
- 既有 Stage-1 acquisition 输出目录为 `outputs/metrics/` 与 `outputs/reports/`；raw 固定在 `data/orbit_uncertainty_stage1/raw/`。本轮沿用该目录，不覆盖旧 acquisition baseline 输出。
- 现有 targeted tests 覆盖 parser、formal-window、duplicate preservation、source、gap、status 与 report semantic consistency。
- actual CSV schema 为 19 列 CelesTrak SupGP CSV，包含 Stage-0 已验证的 17 个 SGP4-compatible orbital fields，以及 `RMS`、`DATA_SOURCE`；不包含 `CREATION_DATE`。

## 2. Reference-quality gate

- READY = 20
- PARTIAL = 0
- NO_REFERENCE = 0

READY/PARTIAL 的 coverage 判断沿用 acquisition pipeline 已记录的 engineering rule：formal-window 两端各 24 h 容差、内部 gap > 48 h 记作 large gap。它们只用于 ingestion readiness，不是轨道不确定性的科学阈值。RMS 不设 acceptance cutoff。

| norad_id | status | records | first_epoch | last_epoch | rms_median_km | rms_p95_km | rms_max_km | max_gap_h | large_gap_intervals | variant_groups | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 44714 | READY | 285 | 2026-04-01T01:08:41.999971Z | 2026-04-30T22:48:41.999990Z | 0.196 | 0.5104 | 0.944 | 7.4 |  | 0 | 无 gate warning |
| 65686 | READY | 287 | 2026-04-01T00:08:42.000029Z | 2026-04-30T22:39:41.999990Z | 0.19 | 0.2941 | 0.485 | 6.816667 |  | 0 | 无 gate warning |
| 65421 | READY | 288 | 2026-04-01T00:05:41.999971Z | 2026-04-30T22:48:41.999990Z | 0.187 | 0.273 | 0.579 | 6.116667 |  | 0 | 无 gate warning |
| 65409 | READY | 281 | 2026-04-01T01:52:42.000010Z | 2026-04-30T22:24:41.999962Z | 0.196 | 0.278 | 0.584 | 6.833333 |  | 0 | 无 gate warning |
| 65410 | READY | 283 | 2026-04-01T02:04:41.999981Z | 2026-04-30T22:25:42.000010Z | 0.202 | 0.3186 | 0.748 | 5.566667 |  | 0 | 无 gate warning |
| 47749 | READY | 287 | 2026-04-01T01:52:42.000010Z | 2026-04-30T20:48:42.000019Z | 0.187 | 0.267 | 0.289 | 6.05 |  | 0 | 无 gate warning |
| 47383 | READY | 278 | 2026-04-01T01:20:42.000029Z | 2026-04-30T22:21:41.999990Z | 0.196 | 0.33175 | 0.523 | 5.95 |  | 0 | 无 gate warning |
| 65411 | READY | 283 | 2026-04-01T02:23:42.000029Z | 2026-04-30T21:46:42.000038Z | 0.197 | 0.2884 | 0.766 | 6.116667 |  | 0 | 无 gate warning |
| 48309 | READY | 286 | 2026-04-01T01:11:42.000029Z | 2026-04-30T22:58:42.000038Z | 0.1975 | 0.31925 | 0.637 | 7.033333 |  | 0 | 无 gate warning |
| 45230 | READY | 276 | 2026-04-01T02:23:42.000029Z | 2026-04-30T22:49:42.000038Z | 0.186 | 0.26575 | 0.392 | 7.566667 |  | 0 | 无 gate warning |
| 47844 | READY | 286 | 2026-04-01T01:23:42Z | 2026-04-30T22:58:42.000038Z | 0.197 | 0.2825 | 0.557 | 6.833333 |  | 0 | 无 gate warning |
| 65407 | READY | 280 | 2026-04-01T01:02:42.000029Z | 2026-04-30T21:54:41.999990Z | 0.1895 | 0.26415 | 0.521 | 5.983333 |  | 0 | 无 gate warning |
| 47767 | READY | 287 | 2026-04-01T02:45:41.999962Z | 2026-04-30T23:10:42.000010Z | 0.187 | 0.2657 | 0.374 | 6.883333 |  | 0 | 无 gate warning |
| 65405 | READY | 283 | 2026-04-01T00:04:42.000010Z | 2026-04-30T22:04:42.000038Z | 0.189 | 0.2649 | 0.382 | 6.65 |  | 0 | 无 gate warning |
| 48672 | READY | 286 | 2026-04-01T01:12:41.999990Z | 2026-04-30T23:14:42.000029Z | 0.2065 | 0.31975 | 0.629 | 7.55 |  | 0 | 无 gate warning |
| 48111 | READY | 285 | 2026-04-01T01:59:42Z | 2026-04-30T23:46:42.000010Z | 0.185 | 0.2518 | 0.313 | 9.416667 |  | 0 | 无 gate warning |
| 65693 | READY | 281 | 2026-04-01T02:12:42.000019Z | 2026-04-30T21:43:41.999981Z | 0.19 | 0.271 | 0.387 | 6.283333 |  | 0 | 无 gate warning |
| 60265 | READY | 285 | 2026-04-01T00:33:42.000019Z | 2026-04-30T22:37:41.999981Z | 0.198 | 0.4288 | 1.316 | 6.083333 |  | 0 | 无 gate warning |
| 58380 | READY | 287 | 2026-04-01T01:20:42.000029Z | 2026-04-30T21:38:42Z | 0.191 | 0.276 | 0.519 | 6.083333 |  | 0 | 无 gate warning |
| 48458 | READY | 281 | 2026-04-01T03:17:42.000029Z | 2026-04-30T23:10:42.000010Z | 0.201 | 0.321 | 0.467 | 6.45 |  | 0 | 无 gate warning |

逐星 status reason 由与 quality classification 相同的 `classify_status()` 动态重算；如果 report 与 quality status 不一致，报告生成会直接失败。

（无）

当前 coverage warning 摘要：formal-window boundary incomplete=0/20，internal gap > 48 h=0/20，same-epoch variant=0/20 颗、共 0 组。逐星原生 reference span、large-gap interval 与全部 excluded intervals 以 quality CSV 为准；这些区间不代表自动插值、补值或批准进入 segmented pilot。

## 3. DATA_SOURCE audit

- distribution：`{"SpaceX-E": 5675}`
- source switch satellites：0
- missing DATA_SOURCE：0

当前 source 统计由本次输入动态生成。若 source switch satellites 或 missing DATA_SOURCE 非零，相关对象会在逐星 reason 中标记为 PARTIAL；本 gate 不自动合并不同 source。

## 4. RMS descriptive audit

RMS 单位沿用 Stage-0 已记录的 CelesTrak SupGP fit-RMS 语义（km）。本报告给出 min/median/p90/p95/max，并复用 Stage-0 的 robust-z > 3.5 规则标记描述性检查候选；该规则不剔除记录、不改变 quality status，也不能单独证明 maneuver/regime change。

| norad_id | rms_max_km | robust_candidates | sudden_spikes | longest_run | run_start | run_end |
| --- | --- | --- | --- | --- | --- | --- |
| 60265 | 1.316 | 26 | 9 | 6 | 2026-04-17T02:39:42.000019Z | 2026-04-17T14:19:42.000010Z |
| 44714 | 0.944 | 51 | 13 | 51 | 2026-04-18T11:03:42.000019Z | 2026-04-23T10:07:42.000010Z |
| 65411 | 0.766 | 9 | 3 | 4 | 2026-04-23T23:34:42.000038Z | 2026-04-24T05:20:41.999971Z |
| 65410 | 0.748 | 9 | 5 | 3 | 2026-04-30T08:48:42.000019Z | 2026-04-30T13:37:41.999981Z |
| 48309 | 0.637 | 8 | 7 | 2 | 2026-04-04T10:25:42.000010Z | 2026-04-04T13:48:41.999990Z |
| 48672 | 0.629 | 6 | 4 | 2 | 2026-04-25T10:41:42Z | 2026-04-25T12:22:42.000010Z |
| 65409 | 0.584 | 8 | 4 | 3 | 2026-04-27T21:08:42.000029Z | 2026-04-28T00:24:42.000019Z |
| 65421 | 0.579 | 8 | 4 | 4 | 2026-04-19T22:51:41.999962Z | 2026-04-20T05:50:42.000029Z |
| 47844 | 0.557 | 8 | 4 | 4 | 2026-04-26T20:21:42.000019Z | 2026-04-27T03:23:41.999971Z |
| 47383 | 0.523 | 15 | 10 | 4 | 2026-04-16T18:28:42.000038Z | 2026-04-17T01:40:42.000038Z |
| 65407 | 0.521 | 4 | 2 | 4 | 2026-04-20T20:54:41.999962Z | 2026-04-21T04:10:41.999981Z |
| 58380 | 0.519 | 6 | 4 | 4 | 2026-04-18T09:57:41.999962Z | 2026-04-18T17:09:41.999962Z |
| 65686 | 0.485 | 5 | 3 | 3 | 2026-04-03T00:27:41.999990Z | 2026-04-03T06:33:42.000019Z |
| 48458 | 0.467 | 13 | 7 | 4 | 2026-04-21T20:57:42.000019Z | 2026-04-22T02:23:42.000029Z |
| 45230 | 0.392 | 2 | 2 | 1 | 2026-04-10T00:54:41.999990Z | 2026-04-10T00:54:41.999990Z |
| 65693 | 0.387 | 7 | 4 | 3 | 2026-04-02T23:47:41.999971Z | 2026-04-03T05:54:41.999962Z |
| 65405 | 0.382 | 4 | 2 | 3 | 2026-04-17T22:25:42.000010Z | 2026-04-18T03:17:42.000029Z |
| 47767 | 0.374 | 1 | 1 | 1 | 2026-04-21T17:41:42.000029Z | 2026-04-21T17:41:42.000029Z |
| 48111 | 0.313 | 1 | 1 | 1 | 2026-04-03T15:32:41.999971Z | 2026-04-03T15:32:41.999971Z |

`rms_high_candidate_longest_run` 用来观察候选是否连续；所有逐星数值见 quality CSV。Stage-0 对 65411 的 `possible_regime_change` 仍只是 exploratory label，本报告不升级为 confirmed maneuver。

## 5. Coverage / gap audit

- formal-window boundary-incomplete satellites：0/20
- internal gap > 48 h satellites：0/20
- cohort max internal gap：9.416667 h
- raw-order inversion satellites：0
- EPOCH parse errors：0
- obvious-year anomalies：0

CSV EPOCH 字符串本身无 `Z`/offset；按 CelesTrak SupGP schema 与既有 Stage-0 解析约定显式当作 UTC，并在 quality CSV 中记录 assumed count。CSV 不含 `CREATION_DATE`；这不妨碍其作为离线 reference，但它不能替代 ordinary GP 的 causal `CREATION_DATE <= evaluation_time` 选择逻辑。

## 6. Duplicate audit

- duplicate epoch excess records：0
- duplicate epoch groups：0
- exact duplicate excess records：0
- same-epoch variant groups：0
- same-epoch variant satellites：0/20

原始记录未修改、未按 EPOCH 去重。当前没有 duplicate epoch group；duplicate detail 文件保留表头。

## 7. Schema / required-field audit

- required orbital-field missing values：0
- invalid required numeric values：0
- SGP4 OMM initialization errors：0
- propagation-ready formal records：5675/5675

required field set 直接复用 Stage-0 已成功使用的 CelesTrak SupGP→`sgp4.omm.initialize` schema。本轮只初始化 state object 做 schema/value validation，没有执行任何 epoch propagation。

## 8. Stage-1B readiness

20 颗均可按完整 30 天 reference coverage 进入 Stage-1B。

要进入既定 formal 20 × 30-day Stage-1B，必须先解决本次逐星 gate reason 与 `excluded_intervals` 中实际列出的 reference-quality 问题。不得使用 later ordinary GP、插值、current SupGP 或 Stage-0 三星文件冒充缺失 reference；本报告也不替科研决策选择 same-epoch variant 或制定 RMS cutoff。

## 9. 输出与限制

- quality table：`outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_supgp_reference_quality.csv`
- raw inventory：`outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_supgp_raw_inventory.csv`
- duplicate audit：`outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_supgp_duplicate_epoch_audit.csv`
- manifest：`outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_supgp_reference_quality_manifest.json`
- 本报告：`outputs/reports/orbit_uncertainty_stage1_20260401_20260430_supgp_ingestion_audit.md`

本 pilot 仅代表当前约 53.16° / 473 km proxy 的 Starlink shell。RMS spike、element episode 或 Stage-0 label 均不等于 confirmed maneuver；本轮没有建立 universal km threshold。
