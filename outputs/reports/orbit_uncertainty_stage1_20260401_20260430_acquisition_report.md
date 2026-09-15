# Orbit uncertainty Stage-1 acquisition report

## 1. 状态与范围

状态：`SUPGP_INGESTED`。窗口tag：`20260401_20260430`；formal window：`[2026-04-01T00:00:00Z, 2026-05-01T00:00:00Z)`。本轮只完成正式ordinary GP_HISTORY acquisition、raw provenance、ingestion gate和全SupGP epoch causal support audit；没有计算6D residual、regime classifier、freshness model、calibration、synthetic B或Doppler。

权威cohort：20 rows / 20 unique NORAD，来源`outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv`。

## 2. Ordinary GP acquisition

- raw：`data\orbit_uncertainty_stage1\raw\spacetrack_gp\spacetrack_gp_history_20260329_20260501_20sat_omm.json`
- records：2265
- returned satellites：20/20
- ingestion complete：20/20
- 72 h pre-window causal support：20/20
- missing satellites：[]
- reused without network：True
- raw SHA-256：`079DD7846CE44950DB4818CB66F155CB338B2C8154CA66D3F6609F6459B3FEFE`
- records before requested acquisition start：0（Space-Track返回的额外记录，原样保留并显式审计）

`2026-04-01T00:00:00Z`的pre-window support和全部SupGP evaluation epoch均只允许`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID确定性选择。

## 3. Causal readiness at all SupGP epochs

- evaluations：5675
- causal candidate available：5675/5675
- future publication use：0
- selected GP epoch > evaluation time：0
- GP age >72 h：0
- GP age seconds min/median/max：4180.001242 / 39745.017878 / 183342.732509

- duplicate GP_ID：0
- duplicate epoch：305，涉及20/20颗；保留不同GP_ID/CREATION_DATE记录，不静默去重。
- descriptive ordinary-GP gap candidates (>48 h)：{}。这些不是reference RMS/gap结论；本轮已完成选择可用性审计，但未传播轨道或计算residual。

## 4. Historical SupGP ingestion

- status：`SUPGP_INGESTED`
- formal raw directory：`data\orbit_uncertainty_stage1\raw\celestrak_supgp`
- raw CSV files：20
- raw rows：5675

若状态为`WAITING_FOR_SUPGP`，没有使用Stage-0 SupGP、current SupGP、later GP或其他source替代。若CSV已到达，coverage表只审计header、source、RMS、epoch、duplicate和gap，不删除RMS outlier且不计算residual。

## 5. Cohort readiness

{"READY": 20}

只有`READY`对象才能进入Stage-1B residual-library construction。当前是否可进入取决于`READY`数量及SupGP状态；`NO_REFERENCE`不代表ordinary GP失败。

## 6. 输出

- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_gp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_gp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_supgp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_supgp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_ordinary_gp_causal_support_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_ordinary_gp_causal_readiness_summary.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_cohort_readiness.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_download_manifest.json`
- `outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_acquisition_correctness_audit.csv`
