# Multi-service-area single-station repeatability

生成时间：2026-07-06 17:24:03

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。本轮也不是多站一致性实验；不同服务区中的 `S_i` 不是同时工作的多个接收站。

## 1. 实验目标

本轮只回答：同一种服务中心补偿风险，在多个不同服务区和各自固定验证站上，是偶发的局部几何现象，还是能够稳定重复出现。

## 2. 实验设置

- attack_model: `M2_block`
- receiver_mode: `heatmap_mode`
- evaluation_scope: `segment_local`
- doppler_reference_mode: `fixed_site_segment_center`
- verification_strategy: `single-window`
- T_service_s: `60.0`
- R_cell_km: `500.0`，仅为受控尺度参数，不代表真实 Starlink 服务区半径。
- distance_to_center_km: `[0.0, 5.0, 50.0, 200.0]`
- d=0 只保留 `phi=0`；d>0 使用 `[0.0, 90.0, 180.0, 270.0]`
- bk_mode: `['current_bk', 'wide_bk']`
- max_service_areas_per_pass: `3`
- min_segment_duration_s: `45.0`

## 3. 样本规模

- dataset rows: `624`
- row summary rows: `96`
- repeatability summary rows: `32`
- sample pair counts: `{('legacy_synthetic', 'hard_case_weighted'): 2, ('legacy_synthetic', 'original_like'): 2, ('real_tle_candidate', 'boundary_case'): 2, ('real_tle_candidate', 'ordinary_similar'): 2}`
- service area counts: `{('legacy_synthetic', 'hard_case_weighted'): 3, ('legacy_synthetic', 'original_like'): 3, ('real_tle_candidate', 'boundary_case'): 3, ('real_tle_candidate', 'ordinary_similar'): 3}`

## 4. 正确性审计

| evaluation_scope_ok   | doppler_reference_ok   | coverage_ok   | interval_equals_segment   |   max_distance_error_km |   rho0_rmse_r_geo_max_hz |
|:----------------------|:-----------------------|:--------------|:--------------------------|------------------------:|-------------------------:|
| True                  | True                   | True          | True                      |             1.07292e-12 |               1.4358e-06 |

## 5. current_bk 跨服务区重复性

### real TLE ordinary_similar

| sample_source      | sample_group     |   distance_to_center_km | bk_mode    |   pair_condition_count |   target_attacker_pair_count |   mean_area_accept_fraction |   median_area_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_recurrent_accept |   pairs_with_recurrent_accept_rate |   pairs_with_persistent_accept |   pairs_with_persistent_accept_rate |   none_count |   sporadic_count |   recurrent_count |   persistent_count |
|:-------------------|:-----------------|------------------------:|:-----------|-----------------------:|-----------------------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|------------------------------:|-----------------------------------:|-------------------------------:|------------------------------------:|-------------:|-----------------:|------------------:|-------------------:|
| real_tle_candidate | ordinary_similar |                       0 | current_bk |                      2 |                            2 |                    0.666667 |                      0.666667 |                       2 |                            1 |                             1 |                                0.5 |                              1 |                                 0.5 |            0 |                1 |                 0 |                  1 |
| real_tle_candidate | ordinary_similar |                       5 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                0   |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |
| real_tle_candidate | ordinary_similar |                      50 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                0   |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |
| real_tle_candidate | ordinary_similar |                     200 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                0   |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |

### real TLE boundary_case

| sample_source      | sample_group   |   distance_to_center_km | bk_mode    |   pair_condition_count |   target_attacker_pair_count |   mean_area_accept_fraction |   median_area_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_recurrent_accept |   pairs_with_recurrent_accept_rate |   pairs_with_persistent_accept |   pairs_with_persistent_accept_rate |   none_count |   sporadic_count |   recurrent_count |   persistent_count |
|:-------------------|:---------------|------------------------:|:-----------|-----------------------:|-----------------------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|------------------------------:|-----------------------------------:|-------------------------------:|------------------------------------:|-------------:|-----------------:|------------------:|-------------------:|
| real_tle_candidate | boundary_case  |                       0 | current_bk |                      2 |                            2 |                    0.833333 |                      0.833333 |                       2 |                            1 |                             2 |                                  1 |                              1 |                                 0.5 |            0 |                0 |                 1 |                  1 |
| real_tle_candidate | boundary_case  |                       5 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                  0 |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |
| real_tle_candidate | boundary_case  |                      50 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                  0 |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |
| real_tle_candidate | boundary_case  |                     200 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                            0 |                             0 |                                  0 |                              0 |                                 0   |            8 |                0 |                 0 |                  0 |

### legacy original_like

| sample_source    | sample_group   |   distance_to_center_km | bk_mode    |   pair_condition_count |   target_attacker_pair_count |   mean_area_accept_fraction |   median_area_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_recurrent_accept |   pairs_with_recurrent_accept_rate |   pairs_with_persistent_accept |   pairs_with_persistent_accept_rate |   none_count |   sporadic_count |   recurrent_count |   persistent_count |
|:-----------------|:---------------|------------------------:|:-----------|-----------------------:|-----------------------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|------------------------------:|-----------------------------------:|-------------------------------:|------------------------------------:|-------------:|-----------------:|------------------:|-------------------:|
| legacy_synthetic | original_like  |                       0 | current_bk |                      2 |                            2 |                    1        |                      1        |                       2 |                          1   |                             2 |                               1    |                              2 |                                1    |            0 |                0 |                 0 |                  2 |
| legacy_synthetic | original_like  |                       5 | current_bk |                      8 |                            2 |                    0.333333 |                      0.166667 |                       4 |                          0.5 |                             2 |                               0.25 |                              2 |                                0.25 |            4 |                2 |                 0 |                  2 |
| legacy_synthetic | original_like  |                      50 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                          0   |                             0 |                               0    |                              0 |                                0    |            8 |                0 |                 0 |                  0 |
| legacy_synthetic | original_like  |                     200 | current_bk |                      8 |                            2 |                    0        |                      0        |                       0 |                          0   |                             0 |                               0    |                              0 |                                0    |            8 |                0 |                 0 |                  0 |

### legacy hard_case_weighted

| sample_source    | sample_group       |   distance_to_center_km | bk_mode    |   pair_condition_count |   target_attacker_pair_count |   mean_area_accept_fraction |   median_area_accept_fraction |   pairs_with_any_accept |   pairs_with_any_accept_rate |   pairs_with_recurrent_accept |   pairs_with_recurrent_accept_rate |   pairs_with_persistent_accept |   pairs_with_persistent_accept_rate |   none_count |   sporadic_count |   recurrent_count |   persistent_count |
|:-----------------|:-------------------|------------------------:|:-----------|-----------------------:|-----------------------------:|----------------------------:|------------------------------:|------------------------:|-----------------------------:|------------------------------:|-----------------------------------:|-------------------------------:|------------------------------------:|-------------:|-----------------:|------------------:|-------------------:|
| legacy_synthetic | hard_case_weighted |                       0 | current_bk |                      2 |                            2 |                    1        |                             1 |                       2 |                         1    |                             2 |                              1     |                              2 |                               1     |            0 |                0 |                 0 |                  2 |
| legacy_synthetic | hard_case_weighted |                       5 | current_bk |                      8 |                            2 |                    0.916667 |                             1 |                       8 |                         1    |                             8 |                              1     |                              6 |                               0.75  |            0 |                0 |                 2 |                  6 |
| legacy_synthetic | hard_case_weighted |                      50 | current_bk |                      8 |                            2 |                    0.166667 |                             0 |                       2 |                         0.25 |                             1 |                              0.125 |                              1 |                               0.125 |            6 |                1 |                 0 |                  1 |
| legacy_synthetic | hard_case_weighted |                     200 | current_bk |                      8 |                            2 |                    0        |                             0 |                       0 |                         0    |                             0 |                              0     |                              0 |                               0     |            8 |                0 |                 0 |                  0 |

## 6. 服务区位置统计

|   service_area_index | service_area_phase   | sample_source      | sample_group       |   distance_to_center_km | bk_mode    |   total_rows |   accept_rows |   accept_rate |   mean_normalized_score |
|---------------------:|:---------------------|:-------------------|:-------------------|------------------------:|:-----------|-------------:|--------------:|--------------:|------------------------:|
|                    0 | early                | legacy_synthetic   | hard_case_weighted |                       0 | current_bk |            2 |             2 |         1     |                0.702862 |
|                    0 | early                | legacy_synthetic   | hard_case_weighted |                       5 | current_bk |            8 |             8 |         1     |                0.703073 |
|                    0 | early                | legacy_synthetic   | hard_case_weighted |                      50 | current_bk |            8 |             2 |         0.25  |                0.724405 |
|                    0 | early                | legacy_synthetic   | hard_case_weighted |                     200 | current_bk |            8 |             0 |         0     |                1.08487  |
|                    0 | early                | legacy_synthetic   | original_like      |                       0 | current_bk |            2 |             2 |         1     |                0.769096 |
|                    0 | early                | legacy_synthetic   | original_like      |                       5 | current_bk |            8 |             4 |         0.5   |                0.770962 |
|                    0 | early                | legacy_synthetic   | original_like      |                      50 | current_bk |            8 |             0 |         0     |                1.00495  |
|                    0 | early                | legacy_synthetic   | original_like      |                     200 | current_bk |            8 |             0 |         0     |                4.85333  |
|                    0 | early                | real_tle_candidate | boundary_case      |                       0 | current_bk |            2 |             2 |         1     |                0.928315 |
|                    0 | early                | real_tle_candidate | boundary_case      |                       5 | current_bk |            8 |             0 |         0     |                1.63753  |
|                    0 | early                | real_tle_candidate | boundary_case      |                      50 | current_bk |            8 |             0 |         0     |               13.8742   |
|                    0 | early                | real_tle_candidate | boundary_case      |                     200 | current_bk |            8 |             0 |         0     |               75.0086   |
|                    0 | early                | real_tle_candidate | ordinary_similar   |                       0 | current_bk |            2 |             2 |         1     |                0.916773 |
|                    0 | early                | real_tle_candidate | ordinary_similar   |                       5 | current_bk |            8 |             0 |         0     |                1.62823  |
|                    0 | early                | real_tle_candidate | ordinary_similar   |                      50 | current_bk |            8 |             0 |         0     |               13.8681   |
|                    0 | early                | real_tle_candidate | ordinary_similar   |                     200 | current_bk |            8 |             0 |         0     |               74.9269   |
|                    1 | middle               | legacy_synthetic   | hard_case_weighted |                       0 | current_bk |            2 |             2 |         1     |                0.717665 |
|                    1 | middle               | legacy_synthetic   | hard_case_weighted |                       5 | current_bk |            8 |             6 |         0.75  |                0.717808 |
|                    1 | middle               | legacy_synthetic   | hard_case_weighted |                      50 | current_bk |            8 |             1 |         0.125 |                0.733029 |
|                    1 | middle               | legacy_synthetic   | hard_case_weighted |                     200 | current_bk |            8 |             0 |         0     |                1.07044  |
|                    1 | middle               | legacy_synthetic   | original_like      |                       0 | current_bk |            2 |             2 |         1     |                0.836853 |
|                    1 | middle               | legacy_synthetic   | original_like      |                       5 | current_bk |            8 |             2 |         0.25  |                0.839359 |
|                    1 | middle               | legacy_synthetic   | original_like      |                      50 | current_bk |            8 |             0 |         0     |                1.11216  |
|                    1 | middle               | legacy_synthetic   | original_like      |                     200 | current_bk |            8 |             0 |         0     |                5.14883  |
|                    1 | middle               | real_tle_candidate | boundary_case      |                       0 | current_bk |            2 |             1 |         0.5   |                0.961174 |
|                    1 | middle               | real_tle_candidate | boundary_case      |                       5 | current_bk |            8 |             0 |         0     |                1.71252  |
|                    1 | middle               | real_tle_candidate | boundary_case      |                      50 | current_bk |            8 |             0 |         0     |               14.5867   |
|                    1 | middle               | real_tle_candidate | boundary_case      |                     200 | current_bk |            8 |             0 |         0     |               79.1326   |
|                    1 | middle               | real_tle_candidate | ordinary_similar   |                       0 | current_bk |            2 |             1 |         0.5   |                0.900936 |
|                    1 | middle               | real_tle_candidate | ordinary_similar   |                       5 | current_bk |            8 |             0 |         0     |                1.68082  |
|                    1 | middle               | real_tle_candidate | ordinary_similar   |                      50 | current_bk |            8 |             0 |         0     |               14.5291   |
|                    1 | middle               | real_tle_candidate | ordinary_similar   |                     200 | current_bk |            8 |             0 |         0     |               79.0858   |
|                    2 | late                 | legacy_synthetic   | hard_case_weighted |                       0 | current_bk |            2 |             2 |         1     |                0.701094 |
|                    2 | late                 | legacy_synthetic   | hard_case_weighted |                       5 | current_bk |            8 |             8 |         1     |                0.701186 |
|                    2 | late                 | legacy_synthetic   | hard_case_weighted |                      50 | current_bk |            8 |             1 |         0.125 |                0.711371 |
|                    2 | late                 | legacy_synthetic   | hard_case_weighted |                     200 | current_bk |            8 |             0 |         0     |                0.979953 |
|                    2 | late                 | legacy_synthetic   | original_like      |                       0 | current_bk |            2 |             2 |         1     |                0.654476 |
|                    2 | late                 | legacy_synthetic   | original_like      |                       5 | current_bk |            8 |             2 |         0.25  |                0.656869 |
|                    2 | late                 | legacy_synthetic   | original_like      |                      50 | current_bk |            8 |             0 |         0     |                0.911269 |
|                    2 | late                 | legacy_synthetic   | original_like      |                     200 | current_bk |            8 |             0 |         0     |                4.48987  |
|                    2 | late                 | real_tle_candidate | boundary_case      |                       0 | current_bk |            2 |             2 |         1     |                0.852131 |
|                    2 | late                 | real_tle_candidate | boundary_case      |                       5 | current_bk |            8 |             0 |         0     |                1.50218  |
|                    2 | late                 | real_tle_candidate | boundary_case      |                      50 | current_bk |            8 |             0 |         0     |               12.6353   |
|                    2 | late                 | real_tle_candidate | boundary_case      |                     200 | current_bk |            8 |             0 |         0     |               69.1212   |
|                    2 | late                 | real_tle_candidate | ordinary_similar   |                       0 | current_bk |            2 |             1 |         0.5   |                0.91463  |
|                    2 | late                 | real_tle_candidate | ordinary_similar   |                       5 | current_bk |            8 |             0 |         0     |                1.5399   |
|                    2 | late                 | real_tle_candidate | ordinary_similar   |                      50 | current_bk |            8 |             0 |         0     |               12.6255   |
|                    2 | late                 | real_tle_candidate | ordinary_similar   |                     200 | current_bk |            8 |             0 |         0     |               69.0221   |

## 7. 图像

- `outputs/figures/multi_service_area_single_station_smoke/area_accept_fraction_vs_distance.png`
- `outputs/figures/multi_service_area_single_station_smoke/repeatability_class_vs_distance.png`
- `outputs/figures/multi_service_area_single_station_smoke/real_vs_synthetic_cross_area_repeatability.png`
- `outputs/figures/multi_service_area_single_station_smoke/service_area_index_accept_rate.png`

## 8. 表述边界

跨服务区重复性分类只是描述性统计，不是新的 verifier 判决规则。不同服务区使用各自的局部补偿 `u_i(t)`，因此这些结果不能解释为多站 all-accept 或 majority 策略。
