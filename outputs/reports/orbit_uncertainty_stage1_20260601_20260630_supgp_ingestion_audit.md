# Orbit Uncertainty Stage-1A：historical SupGP ingestion audit

## 1. 范围与方法边界

本报告只审计 historical SupGP ingestion 与 reference quality，不传播轨道、不执行 ordinary-GP→SupGP pairing、不计算 RTN/residual、不建立 uncertainty boundary，也不运行 synthetic-B 或 Doppler verifier。SupGP 始终按 operator-derived higher-quality reference 表述，不作为 ground truth。

- formal window：`[2026-06-01T00:00:00Z, 2026-07-01T00:00:00Z)`
- target shell：项目既有 controlled Starlink 20-target cohort，约 53.16° / 473 km proxy；结论不外推至整个 Starlink constellation
- raw CSV 文件：20
- target coverage：20/20
- total records：5927
- formal-window records：5927
- raw returned span across cohort：`2026-06-01T00:11:42Z` 至 `2026-06-30T23:49:41.999981Z`
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
| 44714 | READY | 300 | 2026-06-01T02:55:42.000010Z | 2026-06-30T23:49:41.999981Z | 0.186 | 0.26605 | 0.32 | 6.2 |  | 0 | 无 gate warning |
| 65686 | READY | 293 | 2026-06-01T00:59:41.999971Z | 2026-06-30T22:48:41.999990Z | 0.209 | 0.3924 | 2.036 | 8.283333 |  | 0 | 无 gate warning |
| 65421 | READY | 301 | 2026-06-01T01:42:41.999962Z | 2026-06-30T23:34:42.000038Z | 0.204 | 0.287 | 0.403 | 6.866667 |  | 0 | 无 gate warning |
| 65409 | READY | 298 | 2026-06-01T01:29:42.000029Z | 2026-06-30T23:47:41.999971Z | 0.2045 | 0.2953 | 0.509 | 6.133333 |  | 0 | 无 gate warning |
| 65410 | READY | 302 | 2026-06-01T00:19:42.000038Z | 2026-06-30T22:44:41.999971Z | 0.2045 | 0.36835 | 0.584 | 5.583333 |  | 0 | 无 gate warning |
| 47749 | READY | 295 | 2026-06-01T02:57:42.000019Z | 2026-06-30T22:39:41.999990Z | 0.205 | 0.366 | 1.119 | 6.85 |  | 0 | 无 gate warning |
| 47383 | READY | 297 | 2026-06-01T00:57:41.999962Z | 2026-06-30T21:58:42.000010Z | 0.189 | 0.264 | 0.387 | 8.65 |  | 0 | 无 gate warning |
| 65411 | READY | 299 | 2026-06-01T01:47:42.000029Z | 2026-06-30T19:50:42Z | 0.199 | 0.278 | 0.402 | 5.766667 |  | 0 | 无 gate warning |
| 48309 | READY | 290 | 2026-06-01T00:45:41.999990Z | 2026-06-30T18:12:41.999962Z | 0.1995 | 0.3471 | 0.746 | 7.05 |  | 0 | 无 gate warning |
| 45230 | READY | 293 | 2026-06-01T00:54:41.999990Z | 2026-06-30T19:53:41.999971Z | 0.188 | 0.2588 | 0.286 | 10.2 |  | 0 | 无 gate warning |
| 47844 | READY | 295 | 2026-06-01T00:17:42.000029Z | 2026-06-30T22:58:42.000038Z | 0.184 | 0.2553 | 0.289 | 6.416667 |  | 0 | 无 gate warning |
| 65407 | READY | 296 | 2026-06-01T00:24:42.000019Z | 2026-06-30T19:16:42.000010Z | 0.2035 | 0.2885 | 0.421 | 7.2 |  | 0 | 无 gate warning |
| 47767 | READY | 291 | 2026-06-01T00:30:41.999962Z | 2026-06-30T22:41:42Z | 0.224 | 0.353 | 0.497 | 5.85 |  | 0 | 无 gate warning |
| 65405 | READY | 298 | 2026-06-01T00:26:42.000029Z | 2026-06-30T23:07:42.000038Z | 0.2015 | 0.2932 | 0.671 | 5.066667 |  | 0 | 无 gate warning |
| 48672 | READY | 297 | 2026-06-01T01:05:42Z | 2026-06-30T22:15:41.999962Z | 0.204 | 0.2772 | 0.359 | 6.116667 |  | 0 | 无 gate warning |
| 48111 | READY | 297 | 2026-06-01T03:01:42.000038Z | 2026-06-30T21:58:42.000010Z | 0.184 | 0.2538 | 0.282 | 4.816667 |  | 0 | 无 gate warning |
| 65693 | READY | 297 | 2026-06-01T01:11:42.000029Z | 2026-06-30T18:07:41.999981Z | 0.208 | 0.3428 | 0.507 | 5.016667 |  | 0 | 无 gate warning |
| 60265 | READY | 296 | 2026-06-01T00:11:42Z | 2026-06-30T19:51:41.999962Z | 0.2105 | 0.33 | 0.526 | 6.266667 |  | 0 | 无 gate warning |
| 58380 | READY | 297 | 2026-06-01T01:07:42.000010Z | 2026-06-30T22:17:41.999971Z | 0.205 | 0.5176 | 1.524 | 9.216667 |  | 0 | 无 gate warning |
| 48458 | READY | 295 | 2026-06-01T02:58:41.999981Z | 2026-06-30T23:24:41.999990Z | 0.195 | 0.2806 | 0.413 | 9.4 |  | 0 | 无 gate warning |

逐星 status reason 由与 quality classification 相同的 `classify_status()` 动态重算；如果 report 与 quality status 不一致，报告生成会直接失败。

（无）

当前 coverage warning 摘要：formal-window boundary incomplete=0/20，internal gap > 48 h=0/20，same-epoch variant=0/20 颗、共 0 组。逐星原生 reference span、large-gap interval 与全部 excluded intervals 以 quality CSV 为准；这些区间不代表自动插值、补值或批准进入 segmented pilot。

## 3. DATA_SOURCE audit

- distribution：`{"SpaceX-E": 5927}`
- source switch satellites：0
- missing DATA_SOURCE：0

当前 source 统计由本次输入动态生成。若 source switch satellites 或 missing DATA_SOURCE 非零，相关对象会在逐星 reason 中标记为 PARTIAL；本 gate 不自动合并不同 source。

## 4. RMS descriptive audit

RMS 单位沿用 Stage-0 已记录的 CelesTrak SupGP fit-RMS 语义（km）。本报告给出 min/median/p90/p95/max，并复用 Stage-0 的 robust-z > 3.5 规则标记描述性检查候选；该规则不剔除记录、不改变 quality status，也不能单独证明 maneuver/regime change。

| norad_id | rms_max_km | robust_candidates | sudden_spikes | longest_run | run_start | run_end |
| --- | --- | --- | --- | --- | --- | --- |
| 65686 | 2.036 | 18 | 10 | 8 | 2026-06-06T07:40:42.000038Z | 2026-06-07T00:11:42Z |
| 58380 | 1.524 | 20 | 9 | 6 | 2026-06-11T18:42:42.000019Z | 2026-06-12T06:48:41.999962Z |
| 47749 | 1.119 | 15 | 6 | 7 | 2026-06-18T13:19:41.999981Z | 2026-06-19T01:17:41.999971Z |
| 48309 | 0.746 | 21 | 8 | 6 | 2026-06-19T04:16:42.000010Z | 2026-06-19T14:13:41.999981Z |
| 65405 | 0.671 | 9 | 6 | 4 | 2026-06-15T09:16:41.999981Z | 2026-06-15T14:50:42.000029Z |
| 65410 | 0.584 | 20 | 10 | 5 | 2026-06-02T12:46:42.000038Z | 2026-06-02T21:14:41.999971Z |
| 60265 | 0.526 | 11 | 6 | 5 | 2026-06-02T02:09:41.999962Z | 2026-06-02T10:24:41.999962Z |
| 65409 | 0.509 | 5 | 4 | 2 | 2026-06-19T14:22:41.999981Z | 2026-06-19T18:09:41.999990Z |
| 65693 | 0.507 | 12 | 9 | 4 | 2026-06-02T13:47:42.000029Z | 2026-06-02T20:13:41.999981Z |
| 65407 | 0.421 | 3 | 3 | 1 | 2026-06-02T21:53:42.000029Z | 2026-06-02T21:53:42.000029Z |
| 48458 | 0.413 | 4 | 4 | 1 | 2026-06-02T07:51:41.999962Z | 2026-06-02T07:51:41.999962Z |
| 65421 | 0.403 | 6 | 5 | 2 | 2026-06-26T01:43:42.000010Z | 2026-06-26T04:14:42Z |
| 65411 | 0.402 | 9 | 6 | 3 | 2026-06-24T22:31:42.000038Z | 2026-06-25T02:29:41.999971Z |
| 47383 | 0.387 | 3 | 2 | 2 | 2026-06-01T00:57:41.999962Z | 2026-06-01T02:36:41.999962Z |
| 48672 | 0.359 | 2 | 2 | 1 | 2026-06-05T03:22:42.000010Z | 2026-06-05T03:22:42.000010Z |

`rms_high_candidate_longest_run` 用来观察候选是否连续；所有逐星数值见 quality CSV。Stage-0 对 65411 的 `possible_regime_change` 仍只是 exploratory label，本报告不升级为 confirmed maneuver。

## 5. Coverage / gap audit

- formal-window boundary-incomplete satellites：0/20
- internal gap > 48 h satellites：0/20
- cohort max internal gap：10.200000 h
- raw-order inversion satellites：0
- EPOCH parse errors：0
- obvious-year anomalies：0
- descriptive cohort gap overlap（逐星 gap > 12 h）：未发现满足描述性最小 gap 条件的 20/20 cohort overlap。

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
- propagation-ready formal records：5927/5927

required field set 直接复用 Stage-0 已成功使用的 CelesTrak SupGP→`sgp4.omm.initialize` schema。本轮只初始化 state object 做 schema/value validation，没有执行任何 epoch propagation。

## 8. Stage-1B readiness

20 颗均可按完整 30 天 reference coverage 进入 Stage-1B。

要进入既定 formal 20 × 30-day Stage-1B，必须先解决本次逐星 gate reason 与 `excluded_intervals` 中实际列出的 reference-quality 问题。不得使用 later ordinary GP、插值、current SupGP 或 Stage-0 三星文件冒充缺失 reference；本报告也不替科研决策选择 same-epoch variant 或制定 RMS cutoff。

## 9. 输出与限制

- quality table：`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_supgp_reference_quality.csv`
- raw inventory：`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_supgp_raw_inventory.csv`
- duplicate audit：`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_supgp_duplicate_epoch_audit.csv`
- manifest：`outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_supgp_reference_quality_manifest.json`
- 本报告：`outputs/reports/orbit_uncertainty_stage1_20260601_20260630_supgp_ingestion_audit.md`

本 pilot 仅代表当前约 53.16° / 473 km proxy 的 Starlink shell。RMS spike、element episode 或 Stage-0 label 均不等于 confirmed maneuver；本轮没有建立 universal km threshold。
