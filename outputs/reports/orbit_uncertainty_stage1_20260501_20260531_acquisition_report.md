# Orbit uncertainty Stage-1 acquisition report

## 1. 状态与范围

状态：`SUPGP_INGESTED`。窗口tag：`20260501_20260531`；formal window：`[2026-05-01T00:00:00Z, 2026-06-01T00:00:00Z)`。本轮只完成正式ordinary GP_HISTORY acquisition、raw provenance、ingestion gate和全SupGP epoch causal support audit；没有计算6D residual、regime classifier、freshness model、calibration、synthetic B或Doppler。

权威cohort：20 rows / 20 unique NORAD，来源`outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv`。

## 2. Ordinary GP acquisition

- raw：`data\orbit_uncertainty_stage1\raw\spacetrack_gp\spacetrack_gp_history_20260428_20260601_20sat_omm.json`
- records：2295
- returned satellites：20/20
- ingestion complete：20/20
- 72 h pre-window causal support：20/20
- missing satellites：[]
- reused without network：True
- raw SHA-256：`E2023C9370EE0018E5F7AC5887E5D8ACDAF0D0761A1D75B7E2FDD4E55B0E77F1`
- records before requested acquisition start：0（Space-Track返回的额外记录，原样保留并显式审计）

`2026-05-01T00:00:00Z`的pre-window support和全部SupGP evaluation epoch均只允许`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID确定性选择。

## 3. Causal readiness at all SupGP epochs

- evaluations：6181
- causal candidate available：6181/6181
- future publication use：0
- selected GP epoch > evaluation time：0
- GP age >72 h：0
- GP age seconds min/median/max：2380.001011 / 42420.347309 / 255228.856416
- publication age seconds min/median/max：1e-05 / 14510.000029 / 192899.0

- duplicate GP_ID：0
- duplicate epoch groups：292；duplicate excess records：298，涉及20/20颗；保留不同GP_ID/CREATION_DATE记录，不静默去重。
- descriptive ordinary-GP gap candidates (>48 h)：{"65407": 57.999393}。这些不是reference RMS/gap结论；本轮已完成选择可用性审计，但未传播轨道或计算residual。

## 4. Historical SupGP ingestion

- status：`SUPGP_INGESTED`
- formal raw directory：`data\orbit_uncertainty_stage1\respecialdatarequest (4)`
- raw CSV files：20
- raw rows：6181
- descriptive cohort reference pause：2026-05-13T01:42:41.999962Z 至 2026-05-13T22:13:42.000038Z，20.516667 h，affected=20/20；是否超过冻结48 h gate：False
- formal reference-quality gate binding：{"status": "VERIFIED", "path": "outputs\\metrics\\orbit_uncertainty_stage1_20260501_20260531_supgp_reference_quality_manifest.json", "sha256": "7EFC2606B6B5FE6DDE7ABA2CF6954C996D85728C90CCCBD4A7745402422B22BB", "window_tag": "20260501_20260531", "status_counts": {"READY": 20}, "raw_file_count": 20, "raw_sha_inventory_match": true}

若状态为`WAITING_FOR_SUPGP`，没有使用Stage-0 SupGP、current SupGP、later GP或其他source替代。若CSV已到达，coverage表只审计header、source、RMS、epoch、duplicate和gap，不删除RMS outlier且不计算residual。

## 5. Cohort readiness

{"READY": 20}

只有`READY`对象才能进入Stage-1B residual-library construction。当前是否可进入取决于`READY`数量及SupGP状态；`NO_REFERENCE`不代表ordinary GP失败。

## 6. 输出

- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_gp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_gp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_supgp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_supgp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_ordinary_gp_causal_support_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_ordinary_gp_causal_readiness_summary.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_cohort_readiness.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_download_manifest.json`
- `outputs\metrics\orbit_uncertainty_stage1_20260501_20260531_acquisition_correctness_audit.csv`
