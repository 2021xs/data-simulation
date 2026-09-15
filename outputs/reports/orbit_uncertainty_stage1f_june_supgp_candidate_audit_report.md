# June Stage-1F-lite confirmatory SupGP reference availability audit

本审计只检查 historical SupGP reference 的 availability、integrity 与 SGP4 OMM schema compatibility。未读取 ordinary GP，未构造 signed RTN residual，未加载或运行冻结 ellipsoid/box，未计算 P95/P99 coverage 或任何 security classification。SupGP/SpaceX-E 是 higher-quality historical reference，不是 ground truth。

## 1. June Raw Identification

- path：`data/orbit_uncertainty_stage1/june`
- CSV files：20
- records：5927；June window 内 5927；window 外 0；EPOCH 不可解析 0
- cohort：expected=20，returned=20，missing=[]，extra=[]
- epoch range：`2026-06-01T00:11:42Z` 至 `2026-06-30T23:49:41.999981Z`
- DATA_SOURCE：`{"SpaceX-E": 5927}`
- RMS availability：5927/5927
- headers consistent：True
- filename/content NORAD consistent：True
- raw SHA inventory：`D:/Project/data-simulation/outputs/metrics/orbit_uncertainty_stage1f_june_supgp_candidate_raw_inventory.csv`

## 2. Per-Satellite Coverage

| norad_id | records | first_epoch | last_epoch | start_boundary_distance_hours | end_boundary_distance_hours | median_gap_hours | max_gap_hours | max_gap_start | max_gap_end | boundary_ok | simulated_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 44714 | 300 | 2026-06-01T02:55:42.000010Z | 2026-06-30T23:49:41.999981Z | 2.928333 | 0.171667 | 2.233333 | 6.2 | 2026-06-23T15:31:42.000010Z | 2026-06-23T21:43:41.999981Z | True | READY |
| 65686 | 293 | 2026-06-01T00:59:41.999971Z | 2026-06-30T22:48:41.999990Z | 0.995 | 1.188333 | 2.15 | 8.283333 | 2026-06-24T14:17:42Z | 2026-06-24T22:34:42.000010Z | True | READY |
| 65421 | 301 | 2026-06-01T01:42:41.999962Z | 2026-06-30T23:34:42.000038Z | 1.711667 | 0.421667 | 2.15 | 6.866667 | 2026-06-28T15:39:41.999962Z | 2026-06-28T22:31:42.000038Z | True | READY |
| 65409 | 298 | 2026-06-01T01:29:42.000029Z | 2026-06-30T23:47:41.999971Z | 1.495 | 0.205 | 2.15 | 6.133333 | 2026-06-30T06:06:42.000019Z | 2026-06-30T12:14:41.999971Z | True | READY |
| 65410 | 302 | 2026-06-01T00:19:42.000038Z | 2026-06-30T22:44:41.999971Z | 0.328333 | 1.255 | 2.0 | 5.583333 | 2026-06-01T09:21:41.999962Z | 2026-06-01T14:56:41.999971Z | True | READY |
| 47749 | 295 | 2026-06-01T02:57:42.000019Z | 2026-06-30T22:39:41.999990Z | 2.961667 | 1.338333 | 2.258333 | 6.85 | 2026-06-15T17:38:41.999971Z | 2026-06-16T00:29:42Z | True | READY |
| 47383 | 297 | 2026-06-01T00:57:41.999962Z | 2026-06-30T21:58:42.000010Z | 0.961667 | 2.021667 | 2.258333 | 8.65 | 2026-06-24T13:02:42.000029Z | 2026-06-24T21:41:41.999971Z | True | READY |
| 65411 | 299 | 2026-06-01T01:47:42.000029Z | 2026-06-30T19:50:42Z | 1.795 | 4.155 | 2.15 | 5.766667 | 2026-06-15T19:47:42.000029Z | 2026-06-16T01:33:41.999962Z | True | READY |
| 48309 | 290 | 2026-06-01T00:45:41.999990Z | 2026-06-30T18:12:41.999962Z | 0.761667 | 5.788333 | 2.166667 | 7.05 | 2026-06-24T12:45:41.999990Z | 2026-06-24T19:48:41.999990Z | True | READY |
| 45230 | 293 | 2026-06-01T00:54:41.999990Z | 2026-06-30T19:53:41.999971Z | 0.911667 | 4.105 | 2.3 | 10.2 | 2026-06-24T12:14:41.999971Z | 2026-06-24T22:26:41.999971Z | True | READY |
| 47844 | 295 | 2026-06-01T00:17:42.000029Z | 2026-06-30T22:58:42.000038Z | 0.295 | 1.021667 | 2.175 | 6.416667 | 2026-06-22T13:06:41.999962Z | 2026-06-22T19:31:42.000038Z | True | READY |
| 65407 | 296 | 2026-06-01T00:24:42.000019Z | 2026-06-30T19:16:42.000010Z | 0.411667 | 4.721667 | 2.15 | 7.2 | 2026-06-23T16:34:42.000010Z | 2026-06-23T23:46:42.000010Z | True | READY |
| 47767 | 291 | 2026-06-01T00:30:41.999962Z | 2026-06-30T22:41:42Z | 0.511667 | 1.305 | 2.35 | 5.85 | 2026-06-24T15:34:41.999981Z | 2026-06-24T21:25:41.999981Z | True | READY |
| 65405 | 298 | 2026-06-01T00:26:42.000029Z | 2026-06-30T23:07:42.000038Z | 0.445 | 0.871667 | 2.15 | 5.066667 | 2026-06-26T20:10:42.000010Z | 2026-06-27T01:14:42Z | True | READY |
| 48672 | 297 | 2026-06-01T01:05:42Z | 2026-06-30T22:15:41.999962Z | 1.095 | 1.738333 | 2.166667 | 6.116667 | 2026-06-01T07:19:41.999981Z | 2026-06-01T13:26:41.999971Z | True | READY |
| 48111 | 297 | 2026-06-01T03:01:42.000038Z | 2026-06-30T21:58:42.000010Z | 3.028333 | 2.021667 | 2.225 | 4.816667 | 2026-06-14T07:02:42.000029Z | 2026-06-14T11:51:41.999990Z | True | READY |
| 65693 | 297 | 2026-06-01T01:11:42.000029Z | 2026-06-30T18:07:41.999981Z | 1.195 | 5.871667 | 2.15 | 5.016667 | 2026-06-07T03:17:42.000029Z | 2026-06-07T08:18:41.999962Z | True | READY |
| 60265 | 296 | 2026-06-01T00:11:42Z | 2026-06-30T19:51:41.999962Z | 0.195 | 4.138333 | 2.15 | 6.266667 | 2026-06-28T15:48:41.999962Z | 2026-06-28T22:04:42.000038Z | True | READY |
| 58380 | 297 | 2026-06-01T01:07:42.000010Z | 2026-06-30T22:17:41.999971Z | 1.128333 | 1.705 | 2.15 | 9.216667 | 2026-06-24T13:37:41.999981Z | 2026-06-24T22:50:42Z | True | READY |
| 48458 | 295 | 2026-06-01T02:58:41.999981Z | 2026-06-30T23:24:41.999990Z | 2.978333 | 0.588333 | 2.333333 | 9.4 | 2026-06-24T12:28:42.000038Z | 2026-06-24T21:52:41.999981Z | True | READY |

## 3. Daily Coverage

- UTC dates with any SupGP：30/30
- UTC dates with 20/20 satellites：30/30
- minimum records/day：126
- minimum satellites/day：20
- abnormal dates：[]

完整逐日表：`D:/Project/data-simulation/outputs/metrics/orbit_uncertainty_stage1f_june_supgp_candidate_daily_coverage.csv`。

## 4. Cohort-Wide Gap Audit

- satellites with >48 h internal gap：0
- total >48 h intervals：0
- `MARCH_STYLE_ARCHIVE_GAP = NO`

未发现 >12 h 的 20/20 同步 raw-record pause。

> 上述 pause 是 raw reference cadence 的描述性事实。未插值、未补值，也未改变冻结的 48 h engineering gate。

## 5. Duplicate / Variant Audit

- duplicate epoch groups：0
- duplicate excess：0
- exact duplicate excess：0
- same-epoch orbital variants：0
- same-epoch DATA_SOURCE variants：0
- same-epoch RMS variants：0
- affected satellites：0

原始记录全部保留，没有静默去重、按 RMS 选择或任取第一条。

## 6. Reference Quality

- DATA_SOURCE set：['SpaceX-E']；source-switch satellites=0；missing=0
- RMS km：min=0.113，median=0.198，P90=0.27，P95=0.3067，max=2.036，missing=0，invalid=0
- required-field missing=0；invalid numeric=0；SGP4 OMM initialization errors=0；propagation-ready=5927/5927

RMS 为 `REFERENCE_ONLY`，没有 scientific cutoff，也未进入 window decision。

## 7. Simulated Gate

- READY = 20
- PARTIAL = 0
- NO_REFERENCE = 0

复用 `audit_orbit_uncertainty_stage1a_supgp.py` 的 pure gate logic：boundary tolerance=24 h，internal gap threshold=48 h，same-epoch variant→PARTIAL，RMS 不设 acceptance cutoff。本报告是 candidate/read-only audit，不是正式 June Stage-1A artifact。

## 8. Window Decision

`A. JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE`

该决策仅依据 reference availability、integrity 与 coverage；不含 residual、uncertainty score 或模型表现。

## 9. If A

ordinary GP acquisition window：`[2026-05-29T00:00:00Z, 2026-07-01T00:00:00Z)`，用于冻结的 72 h causal lookback。本轮没有执行 acquisition。

未来顺序固定为：June Stage-1A → June Stage-1B → frozen Stage-1F-lite confirmatory validation。禁止 June refit、threshold recalibration、candidate swap、covariance/box fit。
