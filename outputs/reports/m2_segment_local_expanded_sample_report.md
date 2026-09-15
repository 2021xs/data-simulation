# Expanded segment-local fixed-site confirmation

生成时间：2026-07-06 16:28:55

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。

## 1. 实验目的

前一轮 fine sweep 的真实 TLE 样本规模较小；新旧 fixed-C 对账又显示 legacy synthetic hard cases 的旧高风险结果基本可 near replay。因此本轮把真实 TLE candidate 与 legacy synthetic hard cases 放入同一套 `segment_local + fixed_site_segment_center` 口径中，比较距离服务中心的风险曲线。

## 2. 实际参数

- preset: `expanded`
- attack_model: `['M0', 'M2_block']`
- receiver_mode: `heatmap_mode`
- evaluation_scope: `segment_local`
- doppler_reference_mode: `fixed_site_segment_center`
- verification_strategy: `single-window`
- T_service_s: `60.0`
- R_cell_km: `[50.0, 100.0, 200.0, 500.0]`
- distance_to_center_km: `[0.0, 2.5, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]`
- phi_deg: `[0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]`
- bk_mode: `['no_bk', 'current_bk', 'wide_bk']`
- real max_targets: `5`
- real max_attackers_per_group: `5`
- max_heatmap_segments: `1`

## 3. 样本规模

- dataset rows: `89280`
- row summary rows: `720`
- pair summary rows: `216`
- actual targets by source: `{'legacy_synthetic': 4, 'real_tle_candidate': 5}`
- actual pair counts by source/group: `{('legacy_synthetic', 'boundary_case'): 6, ('legacy_synthetic', 'ordinary_similar'): 6, ('real_tle_candidate', 'boundary_case'): 25, ('real_tle_candidate', 'ordinary_similar'): 25}`

## 4. 正确性审计

| evaluation_scope_ok   | doppler_reference_ok   | coverage_ok   |   distance_error_max_km |   rho0_rmse_r_geo_max_hz |
|:----------------------|:-----------------------|:--------------|------------------------:|-------------------------:|
| True                  | True                   | True          |             2.10942e-12 |              1.51791e-06 |

## 5. current_bk / M2_block 距离趋势

### real TLE ordinary_similar

| sample_source      | sample_group     | attack_model   |   distance_to_center_km | bk_mode    |   pair_count |   mean_pair_accept_fraction |   median_pair_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_any_accept_rate_wilson_low |   pairs_with_any_accept_rate_wilson_high |
|:-------------------|:-----------------|:---------------|------------------------:|:-----------|-------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|----------------------------------------:|-----------------------------------------:|
| real_tle_candidate | ordinary_similar | M2_block       |                     0   | current_bk |           25 |                       0.68  |                             1 |                      17 |                         0.68 |                             0.484103    |                                 0.827948 |
| real_tle_candidate | ordinary_similar | M2_block       |                     2.5 | current_bk |           25 |                       0.045 |                             0 |                       9 |                         0.36 |                             0.202479    |                                 0.554815 |
| real_tle_candidate | ordinary_similar | M2_block       |                     5   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                    10   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                    20   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                    50   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                   100   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                   200   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | ordinary_similar | M2_block       |                   500   | current_bk |           25 |                       0     |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |

### real TLE boundary_case

| sample_source      | sample_group   | attack_model   |   distance_to_center_km | bk_mode    |   pair_count |   mean_pair_accept_fraction |   median_pair_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_any_accept_rate_wilson_low |   pairs_with_any_accept_rate_wilson_high |
|:-------------------|:---------------|:---------------|------------------------:|:-----------|-------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|----------------------------------------:|-----------------------------------------:|
| real_tle_candidate | boundary_case  | M2_block       |                     0   | current_bk |           25 |                        0.72 |                             1 |                      18 |                         0.72 |                             0.524234    |                                 0.857161 |
| real_tle_candidate | boundary_case  | M2_block       |                     2.5 | current_bk |           25 |                        0.05 |                             0 |                      10 |                         0.4  |                             0.234033    |                                 0.592605 |
| real_tle_candidate | boundary_case  | M2_block       |                     5   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                    10   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                    20   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                    50   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                   100   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                   200   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |
| real_tle_candidate | boundary_case  | M2_block       |                   500   | current_bk |           25 |                        0    |                             0 |                       0 |                         0    |                             1.38778e-17 |                                 0.133192 |

### legacy original_like

| sample_source    | sample_group     | attack_model   |   distance_to_center_km | bk_mode    |   pair_count |   mean_pair_accept_fraction |   median_pair_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_any_accept_rate_wilson_low |   pairs_with_any_accept_rate_wilson_high |
|:-----------------|:-----------------|:---------------|------------------------:|:-----------|-------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|----------------------------------------:|-----------------------------------------:|
| legacy_synthetic | ordinary_similar | M2_block       |                     0   | current_bk |            6 |                   1         |                        1      |                       6 |                     1        |                               0.609666  |                                 1        |
| legacy_synthetic | ordinary_similar | M2_block       |                     2.5 | current_bk |            6 |                   0.604167  |                        0.75   |                       5 |                     0.833333 |                               0.436497  |                                 0.969947 |
| legacy_synthetic | ordinary_similar | M2_block       |                     5   | current_bk |            6 |                   0.479167  |                        0.4375 |                       4 |                     0.666667 |                               0.299993  |                                 0.903229 |
| legacy_synthetic | ordinary_similar | M2_block       |                    10   | current_bk |            6 |                   0.416667  |                        0.25   |                       4 |                     0.666667 |                               0.299993  |                                 0.903229 |
| legacy_synthetic | ordinary_similar | M2_block       |                    20   | current_bk |            6 |                   0.416667  |                        0.25   |                       4 |                     0.666667 |                               0.299993  |                                 0.903229 |
| legacy_synthetic | ordinary_similar | M2_block       |                    50   | current_bk |            6 |                   0.3125    |                        0.125  |                       4 |                     0.666667 |                               0.299993  |                                 0.903229 |
| legacy_synthetic | ordinary_similar | M2_block       |                   100   | current_bk |            6 |                   0.145833  |                        0      |                       2 |                     0.333333 |                               0.0967714 |                                 0.700007 |
| legacy_synthetic | ordinary_similar | M2_block       |                   200   | current_bk |            6 |                   0.0208333 |                        0      |                       1 |                     0.166667 |                               0.0300534 |                                 0.563503 |
| legacy_synthetic | ordinary_similar | M2_block       |                   500   | current_bk |            6 |                   0.0416667 |                        0      |                       1 |                     0.166667 |                               0.0300534 |                                 0.563503 |

### legacy hard_case_weighted

| sample_source    | sample_group   | attack_model   |   distance_to_center_km | bk_mode    |   pair_count |   mean_pair_accept_fraction |   median_pair_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_any_accept_rate_wilson_low |   pairs_with_any_accept_rate_wilson_high |
|:-----------------|:---------------|:---------------|------------------------:|:-----------|-------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|----------------------------------------:|-----------------------------------------:|
| legacy_synthetic | boundary_case  | M2_block       |                     0   | current_bk |            6 |                   0.666667  |                        1      |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                     2.5 | current_bk |            6 |                   0.666667  |                        1      |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                     5   | current_bk |            6 |                   0.604167  |                        0.8125 |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                    10   | current_bk |            6 |                   0.583333  |                        0.75   |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                    20   | current_bk |            6 |                   0.479167  |                        0.5625 |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                    50   | current_bk |            6 |                   0.208333  |                        0.25   |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                   100   | current_bk |            6 |                   0.145833  |                        0.1875 |                       4 |                     0.666667 |                             0.299993    |                                 0.903229 |
| legacy_synthetic | boundary_case  | M2_block       |                   200   | current_bk |            6 |                   0.0833333 |                        0.0625 |                       3 |                     0.5      |                             0.187616    |                                 0.812384 |
| legacy_synthetic | boundary_case  | M2_block       |                   500   | current_bk |            6 |                   0         |                        0      |                       0 |                     0        |                             2.77556e-17 |                                 0.390334 |

## 6. 风险过渡摘要

| sample_source      | sample_group     | attack_model   | bk_mode    |   max_distance_km_with_accept |   first_zero_accept_distance_km |   peak_pairs_with_any_accept_rate |   distance_at_peak | note                                                    |
|:-------------------|:-----------------|:---------------|:-----------|------------------------------:|--------------------------------:|----------------------------------:|-------------------:|:--------------------------------------------------------|
| legacy_synthetic   | boundary_case    | M0             | current_bk |                         500   |                             nan |                          0.666667 |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | boundary_case    | M0             | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | boundary_case    | M0             | wide_bk    |                         500   |                             nan |                          0.666667 |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | boundary_case    | M2_block       | current_bk |                         200   |                             500 |                          0.666667 |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | boundary_case    | M2_block       | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | boundary_case    | M2_block       | wide_bk    |                         500   |                             nan |                          0.666667 |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M0             | current_bk |                         500   |                             nan |                          1        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M0             | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M0             | wide_bk    |                         500   |                             nan |                          1        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M2_block       | current_bk |                         500   |                             nan |                          1        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M2_block       | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| legacy_synthetic   | ordinary_similar | M2_block       | wide_bk    |                         500   |                             nan |                          1        |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M0             | current_bk |                           5   |                              10 |                          0.72     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M0             | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M0             | wide_bk    |                          10   |                              20 |                          0.92     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M2_block       | current_bk |                           2.5 |                               5 |                          0.72     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M2_block       | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | boundary_case    | M2_block       | wide_bk    |                           5   |                              10 |                          0.92     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M0             | current_bk |                          10   |                              20 |                          0.68     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M0             | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M0             | wide_bk    |                          10   |                              20 |                          0.84     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M2_block       | current_bk |                           2.5 |                               5 |                          0.68     |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M2_block       | no_bk      |                         nan   |                               0 |                          0        |                  0 | observed risk transition; not a strict safety threshold |
| real_tle_candidate | ordinary_similar | M2_block       | wide_bk    |                           5   |                              10 |                          0.84     |                  0 | observed risk transition; not a strict safety threshold |

## 7. 图像

- `outputs/figures/m2_segment_local_expanded_sample/accept_rate_vs_distance_real_tle.png`
- `outputs/figures/m2_segment_local_expanded_sample/accept_rate_vs_distance_legacy_synthetic.png`
- `outputs/figures/m2_segment_local_expanded_sample/real_vs_synthetic_comparison.png`
- `outputs/figures/m2_segment_local_expanded_sample/bk_mode_distance_comparison.png`

## 8. 表述边界

当前非目标样本误接受率是受控仿真中的比例，不是真实世界攻击成功率。`R_cell`、`T_service_s` 和距离扫描均为敏感性参数，不声称等同真实 Starlink cell radius、handover period 或 beam boundary。
