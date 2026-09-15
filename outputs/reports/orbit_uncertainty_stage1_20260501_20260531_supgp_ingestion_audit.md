# Orbit Uncertainty Stage-1A：historical SupGP ingestion audit

## 1. 范围与方法边界

本报告只审计 historical SupGP ingestion 与 reference quality，不传播轨道、不执行 ordinary-GP→SupGP pairing、不计算 RTN/residual、不建立 uncertainty boundary，也不运行 synthetic-B 或 Doppler verifier。SupGP 始终按 operator-derived higher-quality reference 表述，不作为 ground truth。

- formal window：`[2026-05-01T00:00:00Z, 2026-06-01T00:00:00Z)`
- target shell：项目既有 controlled Starlink 20-target cohort，约 53.16° / 473 km proxy；结论不外推至整个 Starlink constellation
- raw CSV 文件：20
- target coverage：20/20
- total records：6181
- formal-window records：6181
- raw returned span across cohort：`2026-05-01T00:00:41.999990Z` 至 `2026-05-31T23:55:42.000010Z`
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
| 44714 | READY | 312 | 2026-05-01T02:00:41.999962Z | 2026-05-31T21:31:42.000010Z | 0.186 | 0.26545 | 0.281 | 24.866667 |  | 0 | 无 gate warning |
| 65686 | READY | 309 | 2026-05-01T00:15:42.000019Z | 2026-05-31T23:11:41.999971Z | 0.196 | 0.344 | 1.778 | 24.95 |  | 0 | 无 gate warning |
| 65421 | READY | 308 | 2026-05-01T00:36:41.999990Z | 2026-05-31T23:55:42.000010Z | 0.1935 | 0.3013 | 0.462 | 22.583333 |  | 0 | 无 gate warning |
| 65409 | READY | 306 | 2026-05-01T00:00:41.999990Z | 2026-05-31T23:30:42.000019Z | 0.2 | 0.271 | 0.382 | 24.666667 |  | 0 | 无 gate warning |
| 65410 | READY | 311 | 2026-05-01T00:03:41.999962Z | 2026-05-31T22:31:42.000038Z | 0.202 | 0.296 | 0.437 | 24.8 |  | 0 | 无 gate warning |
| 47749 | READY | 310 | 2026-05-01T00:00:41.999990Z | 2026-05-31T23:04:41.999981Z | 0.217 | 0.57495 | 0.83 | 26.183333 |  | 0 | 无 gate warning |
| 47383 | READY | 307 | 2026-05-01T02:09:41.999962Z | 2026-05-31T20:41:42.000029Z | 0.188 | 0.2644 | 0.426 | 25.2 |  | 0 | 无 gate warning |
| 65411 | READY | 309 | 2026-05-01T01:10:41.999981Z | 2026-05-31T22:11:42.000029Z | 0.197 | 0.3474 | 0.966 | 24.85 |  | 0 | 无 gate warning |
| 48309 | READY | 308 | 2026-05-01T01:18:42.000019Z | 2026-05-31T23:18:41.999962Z | 0.193 | 0.30795 | 0.621 | 24.733333 |  | 0 | 无 gate warning |
| 45230 | READY | 312 | 2026-05-01T00:40:42.000010Z | 2026-05-31T23:11:41.999971Z | 0.184 | 0.25545 | 0.289 | 23.683333 |  | 0 | 无 gate warning |
| 47844 | READY | 307 | 2026-05-01T00:36:41.999990Z | 2026-05-31T22:18:42.000019Z | 0.197 | 0.3341 | 0.773 | 23.016667 |  | 0 | 无 gate warning |
| 65407 | READY | 310 | 2026-05-01T01:19:41.999981Z | 2026-05-31T22:36:42.000019Z | 0.203 | 0.265 | 0.36 | 24.7 |  | 0 | 无 gate warning |
| 47767 | READY | 309 | 2026-05-01T00:01:42.000038Z | 2026-05-31T23:10:42.000010Z | 0.19 | 0.2586 | 0.292 | 25.066667 |  | 0 | 无 gate warning |
| 65405 | READY | 308 | 2026-05-01T01:18:42.000019Z | 2026-05-31T22:38:42.000029Z | 0.1955 | 0.2763 | 0.677 | 24.766667 |  | 0 | 无 gate warning |
| 48672 | READY | 308 | 2026-05-01T02:23:42.000029Z | 2026-05-31T23:38:41.999971Z | 0.195 | 0.31125 | 0.569 | 24.366667 |  | 0 | 无 gate warning |
| 48111 | READY | 310 | 2026-05-01T01:17:41.999971Z | 2026-05-31T22:24:41.999962Z | 0.186 | 0.255 | 0.288 | 21.833333 |  | 0 | 无 gate warning |
| 65693 | READY | 306 | 2026-05-01T00:57:41.999962Z | 2026-05-31T23:23:42.000029Z | 0.1975 | 0.288 | 0.376 | 24.833333 |  | 0 | 无 gate warning |
| 60265 | READY | 309 | 2026-05-01T00:25:41.999981Z | 2026-05-31T22:21:41.999990Z | 0.198 | 0.3196 | 0.465 | 22.5 |  | 0 | 无 gate warning |
| 58380 | READY | 312 | 2026-05-01T01:03:41.999990Z | 2026-05-31T23:20:41.999971Z | 0.2005 | 0.27145 | 0.319 | 22.566667 |  | 0 | 无 gate warning |
| 48458 | READY | 310 | 2026-05-01T01:20:42.000029Z | 2026-05-31T22:37:41.999981Z | 0.1955 | 0.269 | 0.367 | 25.1 |  | 0 | 无 gate warning |

逐星 status reason 由与 quality classification 相同的 `classify_status()` 动态重算；如果 report 与 quality status 不一致，报告生成会直接失败。

（无）

当前 coverage warning 摘要：formal-window boundary incomplete=0/20，internal gap > 48 h=0/20，same-epoch variant=0/20 颗、共 0 组。逐星原生 reference span、large-gap interval 与全部 excluded intervals 以 quality CSV 为准；这些区间不代表自动插值、补值或批准进入 segmented pilot。

## 3. DATA_SOURCE audit

- distribution：`{"SpaceX-E": 6181}`
- source switch satellites：0
- missing DATA_SOURCE：0

当前 source 统计由本次输入动态生成。若 source switch satellites 或 missing DATA_SOURCE 非零，相关对象会在逐星 reason 中标记为 PARTIAL；本 gate 不自动合并不同 source。

## 4. RMS descriptive audit

RMS 单位沿用 Stage-0 已记录的 CelesTrak SupGP fit-RMS 语义（km）。本报告给出 min/median/p90/p95/max，并复用 Stage-0 的 robust-z > 3.5 规则标记描述性检查候选；该规则不剔除记录、不改变 quality status，也不能单独证明 maneuver/regime change。

| norad_id | rms_max_km | robust_candidates | sudden_spikes | longest_run | run_start | run_end |
| --- | --- | --- | --- | --- | --- | --- |
| 65686 | 1.778 | 17 | 6 | 4 | 2026-05-29T06:39:41.999962Z | 2026-05-29T14:29:41.999971Z |
| 65411 | 0.966 | 16 | 8 | 6 | 2026-05-29T08:26:42Z | 2026-05-29T19:46:41.999981Z |
| 47749 | 0.83 | 27 | 10 | 14 | 2026-05-18T06:58:42.000010Z | 2026-05-19T12:19:42.000038Z |
| 47844 | 0.773 | 18 | 7 | 11 | 2026-05-25T02:56:41.999971Z | 2026-05-26T02:15:41.999990Z |
| 65405 | 0.677 | 11 | 4 | 5 | 2026-05-07T03:40:42.000010Z | 2026-05-07T11:50:42.000029Z |
| 48309 | 0.621 | 11 | 6 | 8 | 2026-05-11T06:39:41.999962Z | 2026-05-11T23:09:41.999962Z |
| 48672 | 0.569 | 10 | 5 | 5 | 2026-05-01T02:23:42.000029Z | 2026-05-01T10:35:41.999971Z |
| 60265 | 0.465 | 15 | 9 | 4 | 2026-05-14T12:42:42.000019Z | 2026-05-14T20:42:41.999990Z |
| 65421 | 0.462 | 15 | 9 | 4 | 2026-05-27T20:08:42Z | 2026-05-28T02:34:42.000038Z |
| 65410 | 0.437 | 6 | 5 | 3 | 2026-05-01T08:06:41.999990Z | 2026-05-01T11:09:41.999962Z |
| 47383 | 0.426 | 6 | 3 | 5 | 2026-05-04T10:30:41.999990Z | 2026-05-04T19:43:42.000010Z |
| 65409 | 0.382 | 3 | 3 | 1 | 2026-05-03T22:55:41.999981Z | 2026-05-03T22:55:41.999981Z |
| 65693 | 0.376 | 4 | 4 | 1 | 2026-05-12T08:37:42.000010Z | 2026-05-12T08:37:42.000010Z |
| 48458 | 0.367 | 4 | 4 | 1 | 2026-05-02T15:13:42.000010Z | 2026-05-02T15:13:42.000010Z |
| 65407 | 0.36 | 1 | 1 | 1 | 2026-05-27T15:30:41.999962Z | 2026-05-27T15:30:41.999962Z |

`rms_high_candidate_longest_run` 用来观察候选是否连续；所有逐星数值见 quality CSV。Stage-0 对 65411 的 `possible_regime_change` 仍只是 exploratory label，本报告不升级为 confirmed maneuver。

## 5. Coverage / gap audit

- formal-window boundary-incomplete satellites：0/20
- internal gap > 48 h satellites：0/20
- cohort max internal gap：26.183333 h
- raw-order inversion satellites：0
- EPOCH parse errors：0
- obvious-year anomalies：0
- descriptive cohort gap overlap（逐星 gap > 12 h）：最长 20/20 overlap：`2026-05-13T01:42:41.999962Z` 至 `2026-05-13T22:13:42.000038Z`，20.516667 h；是否超过冻结 48 h gate：False。

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
- propagation-ready formal records：6181/6181

required field set 直接复用 Stage-0 已成功使用的 CelesTrak SupGP→`sgp4.omm.initialize` schema。本轮只初始化 state object 做 schema/value validation，没有执行任何 epoch propagation。

## 8. Stage-1B readiness

20 颗均可按完整 31 天 reference coverage 进入 Stage-1B。

要进入既定 formal 20 × 31-day Stage-1B，必须先解决本次逐星 gate reason 与 `excluded_intervals` 中实际列出的 reference-quality 问题。不得使用 later ordinary GP、插值、current SupGP 或 Stage-0 三星文件冒充缺失 reference；本报告也不替科研决策选择 same-epoch variant 或制定 RMS cutoff。

## 9. 输出与限制

- quality table：`outputs/metrics/orbit_uncertainty_stage1_20260501_20260531_supgp_reference_quality.csv`
- raw inventory：`outputs/metrics/orbit_uncertainty_stage1_20260501_20260531_supgp_raw_inventory.csv`
- duplicate audit：`outputs/metrics/orbit_uncertainty_stage1_20260501_20260531_supgp_duplicate_epoch_audit.csv`
- manifest：`outputs/metrics/orbit_uncertainty_stage1_20260501_20260531_supgp_reference_quality_manifest.json`
- 本报告：`outputs/reports/orbit_uncertainty_stage1_20260501_20260531_supgp_ingestion_audit.md`

本 pilot 仅代表当前约 53.16° / 473 km proxy 的 Starlink shell。RMS spike、element episode 或 Stage-0 label 均不等于 confirmed maneuver；本轮没有建立 universal km threshold。
