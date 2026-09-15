# Legitimate orbit uncertainty Stage-0 smoke报告

> **Starlink分支更新（2026-08-23）：** historical SupGP CSV已经到达，65409、65410、65411的Starlink Stage-0状态现为`COMPLETE`。本报告下方CelesTrak `WAITING_FOR_DATA`表格是Sentinel分支完成时的历史快照，已由独立的[Starlink Stage-0报告](orbit_uncertainty_stage0_starlink_report.md)取代；Sentinel结果未重跑。

## 1. 授权与数据获取

Space-Track login/query HTTP 200；CDSE token/catalogue HTTP 200。四个变量仅记录configured状态。

CDSE token仅驻留下载进程内存，未写入文件。动态catalogue选择得到`2026-06-27T22:59:42+00:00`至`2026-07-01T00:59:42+00:00`连续74.0小时覆盖，共3个AUX_POEORB原始EOF。Space-Track GP_HISTORY一次查询得到29条Sentinel-1A OMM JSON记录。

| product_type   | validity_start_utc          | validity_stop_utc           | product_id                           | original_filename                                                             |   file_size_bytes | sha256                                                           |
|:---------------|:----------------------------|:----------------------------|:-------------------------------------|:------------------------------------------------------------------------------|------------------:|:-----------------------------------------------------------------|
| AUX_POEORB     | 2026-06-27T22:59:42.000000Z | 2026-06-29T00:59:42.000000Z | 387ec906-fe68-4e14-9c7b-d40b2225c72a | S1A_OPER_AUX_POEORB_OPOD_20260718T070712_V20260627T225942_20260629T005942.EOF |           4653276 | E637649C46723D581D8DE30AE6601B6E117F1B307CDFF6BE72153C6D06F6F3E0 |
| AUX_POEORB     | 2026-06-28T22:59:42.000000Z | 2026-06-30T00:59:42.000000Z | e886a1e0-e9d1-4405-89ac-8654440f8c71 | S1A_OPER_AUX_POEORB_OPOD_20260719T070640_V20260628T225942_20260630T005942.EOF |           4653048 | F1D23BEE705140DA9D5B67C4AB3016B3409819908E864F613344E3F297EECDCE |
| AUX_POEORB     | 2026-06-29T22:59:42.000000Z | 2026-07-01T00:59:42.000000Z | 364f0745-6903-4c85-90f9-ef95d6762066 | S1A_OPER_AUX_POEORB_OPOD_20260720T070517_V20260629T225942_20260701T005942.EOF |           4653695 | 5F891E0FB0901BE7D97F930C6889833577E89A45D86D339A9BE686FBDA00EDEE |

## 2. 实际POEORB metadata

| original_filename                                                             | reference_frame_raw   | time_scale_raw   | position_unit   | velocity_unit   |   declared_osv_count |   osv_interval_median_seconds | validity_start_utc   | validity_stop_utc    |
|:------------------------------------------------------------------------------|:----------------------|:-----------------|:----------------|:----------------|---------------------:|------------------------------:|:---------------------|:---------------------|
| S1A_OPER_AUX_POEORB_OPOD_20260718T070712_V20260627T225942_20260629T005942.EOF | EARTH_FIXED           | UTC              | m               | m/s             |                 9361 |                            10 | 2026-06-27T22:59:42Z | 2026-06-29T00:59:42Z |
| S1A_OPER_AUX_POEORB_OPOD_20260719T070640_V20260628T225942_20260630T005942.EOF | EARTH_FIXED           | UTC              | m               | m/s             |                 9361 |                            10 | 2026-06-28T22:59:42Z | 2026-06-30T00:59:42Z |
| S1A_OPER_AUX_POEORB_OPOD_20260720T070517_V20260629T225942_20260701T005942.EOF | EARTH_FIXED           | UTC              | m               | m/s             |                 9361 |                            10 | 2026-06-29T22:59:42Z | 2026-07-01T00:59:42Z |

`EARTH_FIXED`依据实际EOF映射为Astropy ITRS；随后POEORB ITRS与SGP4 TEME均通过Astropy转换到GCRS。position和velocity使用同一个带`CartesianDifferential`的state转换。EOF未给出更具体的ITRF realization，因此报告保留这一frame语义边界。

## 3. Frame/time correctness smoke

| check                                                    | value                      | unit   | passed   |
|:---------------------------------------------------------|:---------------------------|:-------|:---------|
| POEORB ITRS-GCRS-ITRS position roundtrip                 | 1.8189894035458565e-09     | m      | True     |
| POEORB ITRS-GCRS-ITRS velocity roundtrip                 | 2.7919888623273437e-06     | mm/s   | True     |
| SGP4 TEME-GCRS-TEME position roundtrip                   | 2.7284841053187847e-09     | m      | True     |
| SGP4 TEME-GCRS-TEME velocity roundtrip                   | 2.594813253153916e-06      | mm/s   | True     |
| POEORB transformed velocity vs five-point OSV derivative | 2.5908916968146796e-05     | m/s    | True     |
| SGP4 transformed velocity vs 1-second central difference | 0.007457606030921818       | m/s    | True     |
| actual POEORB metadata frame                             | EARTH_FIXED                | text   | True     |
| actual POEORB metadata time scale                        | UTC                        | text   | True     |
| actual POEORB position unit                              | m                          | text   | True     |
| actual POEORB velocity unit                              | m/s                        | text   | True     |
| actual POEORB OSV interval                               | 10.0                       | s      | True     |
| POEORB overlap state consistency position                | 0.0016700800172780705      | m      | True     |
| POEORB overlap state consistency velocity                | 0.00424264103815695        | mm/s   | True     |
| causal GP selection excludes future creation             | True                       | bool   | True     |
| coordinate warnings                                      | 0                          | count  | True     |
| IERS Earth-orientation table covers evaluation epochs    | IERS_Auto:41684.0..61645.0 | MJD    | True     |
| EOF versus Astropy UT1-UTC consistency                   | 5.888268055555604e-05      | s      | True     |

只在实际OSV epoch计算，不使用reference插值。重叠产品的同epoch state另作一致性检查；速度转换同时通过round-trip和中心差分检查。

## 4. 三组Sentinel对照

| comparison                          |   samples |   position_error_min_km |   position_error_median_km |   position_error_max_km |   velocity_error_min_km_s |   velocity_error_median_km_s |   velocity_error_max_km_s |
|:------------------------------------|----------:|------------------------:|---------------------------:|------------------------:|--------------------------:|-----------------------------:|--------------------------:|
| A_old_causal_gp_to_poeorb           |         3 |               0.922568  |                   1.13852  |                1.20247  |               0.000898361 |                  0.00109911  |               0.00116758  |
| B_newer_nearest_causal_gp_to_poeorb |         3 |               0.433296  |                   0.860737 |                1.02057  |               0.000414631 |                  0.000854659 |               0.000967779 |
| C_old_gp_to_later_gp                |         3 |               0.0886016 |                   0.13062  |                0.837563 |               8.44393e-05 |                  0.000141155 |               0.000905371 |

三组均使用相同的3个evaluation epoch。A/B分别使用second-newest causal GP和newest causal GP对比POEORB；C为同一epoch的old GP与later GP disagreement。所有GP满足`CREATION_DATE <= evaluation time`。

这些数值只证明数据、causal selector、frame/time和RTN/full-state链路跑通。3个epoch不构成uncertainty分布，也不能据此设定任何攻击阈值。

三个epoch中，newer causal GP的POEORB位置误差都低于对应old causal GP；但old→later GP disagreement的中位数仅0.131 km、最大值却达到0.838 km，而old/newer GP对POEORB的中位数分别为1.139/0.861 km。later-GP differencing与independent precise-reference error明显不是同一个量，单个epoch也不能保证前者稳定代表后者。

## 5. CelesTrak historical SupGP

| status           | raw_file   | schema_has_source   | schema_has_fit_rms   | epoch_overlap_with_cached_starlink_gp   | notes                                                           |
|:-----------------|:-----------|:--------------------|:---------------------|:----------------------------------------|:----------------------------------------------------------------|
| WAITING_FOR_DATA |            | False               | False                | False                                   | Historical SupGP CSV not present; no substitute reference used. |

若状态为`WAITING_FOR_DATA`，Starlink GP↔SupGP分支保持等待，没有用later GP或Sentinel数据替代。

## 6. 正确性审计

| check                                               | status   | observed                                                       |
|:----------------------------------------------------|:---------|:---------------------------------------------------------------|
| four credential variables configured at acquisition | pass     | configured/configured/configured/configured; values not stored |
| temporary CDSE token not persisted                  | pass     | False                                                          |
| exactly three minimum POEORB products               | pass     | 3                                                              |
| continuous approximately three-day coverage         | pass     | 74.0                                                           |
| Sentinel ordinary GP required schema                | pass     | records=29; required missing=0                                 |
| no future-created GP used                           | pass     | True                                                           |
| position and velocity transformed by mature library | pass     | Astropy TEME/ITRS/GCRS with CartesianDifferential              |
| frame/time independent sanity checks                | pass     | 17/17                                                          |
| three Sentinel comparison types present             | pass     | 3                                                              |
| CelesTrak SupGP branch                              | waiting  | WAITING_FOR_DATA                                               |
| no Doppler/verifier/threshold/model work            | pass     | Stage-0 source/state pipeline only                             |

## 7. 停止边界

本轮在授权验证、Sentinel原始数据获取、实际metadata审计、common-frame sanity和少量RTN/full-state residual后停止。没有执行24星下载、conformal prediction、attack threshold、synthetic B、Doppler propagation、新verifier或正式uncertainty model。
