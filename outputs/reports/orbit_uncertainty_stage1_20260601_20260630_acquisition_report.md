# Orbit uncertainty Stage-1 acquisition report

## 1. 状态与范围

状态：`JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H`（SupGP ingestion=`SUPGP_INGESTED`）。窗口tag：`20260601_20260630`；formal window：`[2026-06-01T00:00:00Z, 2026-07-01T00:00:00Z)`。本轮只完成正式ordinary GP_HISTORY acquisition、raw provenance、ingestion gate和全SupGP epoch causal support audit；没有计算6D residual、regime classifier、freshness model、calibration、synthetic B或Doppler。

权威cohort：20 rows / 20 unique NORAD，来源`outputs\metrics\orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv`。

## 2. Ordinary GP acquisition

- raw：`data\orbit_uncertainty_stage1\raw\spacetrack_gp\spacetrack_gp_history_20260529_20260701_20sat_omm.json`
- records：1693
- formal-window EPOCH records：1507
- EPOCH range：2026-05-29T00:10:45.509088Z 至 2026-06-30T23:56:46.240224Z
- CREATION_DATE range：2026-05-29T07:26:53Z 至 2026-07-01T10:22:27Z（query按EPOCH；晚于formal stop的publication未被任何June evaluation因果选择）
- returned satellites：20/20
- ingestion complete：20/20
- 72 h pre-window causal support：20/20
- missing satellites：[]
- reused without network：True
- raw SHA-256：`1F5A8BA23D1C8AE605C4142F44E424711D1D85014DB46C28BBC18C3ABC326A96`
- records before requested acquisition start：0（Space-Track返回的额外记录，原样保留并显式审计）

`2026-06-01T00:00:00Z`的pre-window support和全部SupGP evaluation epoch均只允许`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID确定性选择。

## 3. Causal readiness at all SupGP epochs

- evaluations：5927
- causal candidate available：5927/5927
- future publication use：0
- selected GP epoch > evaluation time：0
- GP age >72 h：25
- GP age hours min/median/P90/P95/max：1.061111063888889 / 15.347737608055555 / 34.5127485983889 / 45.501452066361075 / 84.71449663194444
- publication age hours min/median/P90/P95/max：0.0011111111111111111 / 5.785 / 23.690444445500027 / 35.18433332805556 / 79.02250000527779
- negative element/publication age：0/0
- element age >36 h：538（仅描述；后续为OUTSIDE_CALIBRATED_SUPPORT / DEFER）
- element age >72 h affected satellites：{"47383": {"count": 6, "first_evaluation": "2026-06-22T14:14:42.000029Z", "last_evaluation": "2026-06-23T01:00:42.000019Z", "minimum_element_age_hours": 72.596223, "maximum_element_age_hours": 83.362889, "selected_gp_ids": ["330725728"]}, "47767": {"count": 1, "first_evaluation": "2026-06-24T00:52:41.999981Z", "last_evaluation": "2026-06-24T00:52:41.999981Z", "minimum_element_age_hours": 72.365444, "maximum_element_age_hours": 72.365444, "selected_gp_ids": ["330964347"]}, "47844": {"count": 3, "first_evaluation": "2026-06-22T19:31:42.000038Z", "last_evaluation": "2026-06-23T01:53:41.999971Z", "minimum_element_age_hours": 77.061303, "maximum_element_age_hours": 83.427969, "selected_gp_ids": ["330804625"]}, "48458": {"count": 2, "first_evaluation": "2026-06-23T00:55:42.000038Z", "last_evaluation": "2026-06-23T03:38:42Z", "minimum_element_age_hours": 74.961958, "maximum_element_age_hours": 77.678625, "selected_gp_ids": ["330838826"]}, "60265": {"count": 5, "first_evaluation": "2026-06-22T16:07:42.000010Z", "last_evaluation": "2026-06-23T02:30:42.000019Z", "minimum_element_age_hours": 72.426841, "maximum_element_age_hours": 82.810175, "selected_gp_ids": ["330811351"]}, "65409": {"count": 2, "first_evaluation": "2026-06-22T23:37:42.000010Z", "last_evaluation": "2026-06-23T03:03:41.999962Z", "minimum_element_age_hours": 75.469823, "maximum_element_age_hours": 78.903157, "selected_gp_ids": ["330816641"]}, "65421": {"count": 6, "first_evaluation": "2026-06-22T14:23:42.000029Z", "last_evaluation": "2026-06-23T02:56:41.999971Z", "minimum_element_age_hours": 72.164497, "maximum_element_age_hours": 84.714497, "selected_gp_ids": ["330816147"]}}

- duplicate GP_ID：0
- duplicate epoch groups：228；duplicate excess records：240，涉及20/20颗；保留不同GP_ID/CREATION_DATE记录，不静默去重。
- descriptive ordinary-GP gap candidates (>48 h)：{"65686": 50.024687, "65421": 70.470473, "65409": 64.206405, "65410": 54.810375, "47749": 58.0, "47383": 70.300411, "65411": 54.81061, "48309": 62.644214, "47844": 59.476608, "65407": 54.864387, "47767": 69.382838, "65405": 54.810192, "48672": 48.546393, "65693": 50.161828, "60265": 70.578637, "58380": 48.460939, "48458": 59.507752}。这些不是reference RMS/gap结论；本轮已完成选择可用性审计，但未传播轨道或计算residual。

## 4. Historical SupGP ingestion

- status：`SUPGP_INGESTED`
- formal raw directory：`data\orbit_uncertainty_stage1\june`
- raw CSV files：20
- raw rows：5927
- descriptive cohort reference pause： 至 ， h，affected=0/20；是否超过冻结48 h gate：False
- formal reference-quality gate binding：{"status": "VERIFIED", "path": "outputs\\metrics\\orbit_uncertainty_stage1_20260601_20260630_supgp_reference_quality_manifest.json", "sha256": "DAFAD315CB8C147319C44EF2FB705F06380E342C765E3A5E535B02D78EECC468", "window_tag": "20260601_20260630", "status_counts": {"READY": 20}, "raw_file_count": 20, "raw_sha_inventory_match": true}
- candidate availability audit binding：{"status": "VERIFIED", "path": "outputs\\metrics\\orbit_uncertainty_stage1f_june_supgp_candidate_manifest.json", "sha256": "3FD73D1F9D116E83D12DB17C13CF43784734734F07FA9A08524E6DACF2F549F5", "decision": "JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE", "raw_file_count": 20, "raw_sha_inventory_match": true, "frozen_parameter_sha256": "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"}
- Stage-1F/development protected artifacts unchanged：True（11 files）

若状态为`WAITING_FOR_SUPGP`，没有使用Stage-0 SupGP、current SupGP、later GP或其他source替代。若CSV已到达，coverage表只审计header、source、RMS、epoch、duplicate和gap，不删除RMS outlier且不计算residual。

## 5. Cohort readiness

{"READY": 13, "CAUSAL_GP_AGE_GT_72H": 7}

只有`READY`对象才能进入Stage-1B residual-library construction。当前是否可进入取决于`READY`数量及SupGP状态；`NO_REFERENCE`不代表ordinary GP失败。

## 6. 输出

- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_gp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_gp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_supgp_raw_inventory.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_supgp_coverage_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_ordinary_gp_causal_support_audit.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_ordinary_gp_causal_readiness_summary.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_cohort_readiness.csv`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_download_manifest.json`
- `outputs\metrics\orbit_uncertainty_stage1_20260601_20260630_acquisition_correctness_audit.csv`
