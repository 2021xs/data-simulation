# Orbit uncertainty Stage-1 acquisition report

## 1. 状态与范围

状态：`WAITING_FOR_SUPGP`。本轮只完成正式ordinary GP_HISTORY acquisition、raw provenance和ingestion gate；没有计算6D residual、regime classifier、freshness model、calibration、synthetic B或Doppler。

权威cohort：20 rows / 20 unique NORAD，来源`outputs\metrics\orbit_uncertainty_stage1a_satellite_selection.csv`。

## 2. Ordinary GP acquisition

- raw：`data\orbit_uncertainty_stage1\raw\spacetrack_gp\spacetrack_gp_history_20260226_20260329_20sat_omm.json`
- records：1965
- returned satellites：20/20
- ingestion complete：20/20
- 72 h pre-window causal support：20/20
- missing satellites：[]
- reused without network：True
- raw SHA-256：`3E826D049CE3CEFC66875D5178617D8E388B87ED9ED41D36D700AD38005A56B1`

`2026-03-01T00:00:00Z`的support检查只允许`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID确定性选择；selected GP epoch必须位于72小时lookback内。没有执行全部SupGP epoch pairing。

- duplicate GP_ID：0
- duplicate epoch：230，涉及20/20颗；保留不同GP_ID/CREATION_DATE记录，不静默去重。
- descriptive ordinary-GP gap candidates (>48 h)：{"44714": 71.214065, "47844": 62.668123, "65405": 49.943747, "58380": 68.999977}。这些不是reference RMS/gap结论，也没有在本轮执行所有evaluation-time causal pairing。

## 3. Historical SupGP ingestion

- status：`WAITING_FOR_SUPGP`
- formal raw directory：`data\orbit_uncertainty_stage1\raw\celestrak_supgp`
- raw CSV files：0
- raw rows：0

若状态为`WAITING_FOR_SUPGP`，没有使用Stage-0 SupGP、current SupGP、later GP或其他source替代。若CSV已到达，coverage表只审计header、source、RMS、epoch、duplicate和gap，不删除RMS outlier且不计算residual。

## 4. Cohort readiness

{"NO_REFERENCE": 20}

只有`READY`对象才能进入Stage-1B residual-library construction。当前是否可进入取决于`READY`数量及SupGP状态；`NO_REFERENCE`不代表ordinary GP失败。

## 5. 输出

- `outputs\metrics\orbit_uncertainty_stage1_acquisition_gp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_gp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_supgp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_supgp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_cohort_readiness.csv`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_download_manifest.json`
- `outputs\metrics\orbit_uncertainty_stage1_acquisition_correctness_audit.csv`
