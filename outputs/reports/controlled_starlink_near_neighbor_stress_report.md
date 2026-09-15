# Controlled Starlink Ku-band Near-neighbor Stress Report

生成时间：2026-05-05 16:44

## 1. 实验目的

本轮是 near-neighbor stress test，用于观察当前最难 pair 在噪声放大、观测窗口变短、候选库变大时的 matcher 稳定性。它不是攻击实验，不是攻击成功率，不是真实 SatNOGS Starlink observation replay，也不是 Starlink CFO truth 验证。

## 2. 输入配置

- target：STARLINK-1008 / 44714
- known nearest neighbor：STARLINK-35760 / 66274
- center frequency：11325000000 Hz
- station：controlled_example_station / lat=52.21 / lon=5.16 / alt_m=14.0
- error_model_variants：frequency_scaled, unscaled
- sigma_multipliers：1.0, 2.0, 5.0, 10.0
- partial_pass_windows：full, first_30_percent, middle_30_percent, last_30_percent, center_60s, center_120s, center_180s
- candidate_limits：200, 500, 1000
- scenarios：offset_linear_noise, offset_plus_noise
- num_sims_per_setting：100
- mode：controlled_starlink
- observation_id：null

## 3. 数据集规模

- total_sequences：11200
- total_rows：1393600
- matcher result rows：33600
- candidate library rows：455600
- skipped windows：无

## 4. 总体结果

- overall accuracy：0.915565
- overall min margin：-205.382989 Hz
- 是否出现误匹配：是
- 是否预测成 known nearest neighbor 66274：是

## 5. sigma_multiplier 影响

| error_model_variant | sigma_multiplier | mean_margin_hz | min_margin_hz |
| --- | --- | --- | --- |
| frequency_scaled | 1.000000 | 637.386898 | -18.883930 |
| frequency_scaled | 2.000000 | 557.891818 | -21.978832 |
| frequency_scaled | 5.000000 | 419.561033 | -86.530047 |
| frequency_scaled | 10.000000 | 291.136049 | -205.382989 |
| unscaled | 1.000000 | 745.028490 | 16.878822 |
| unscaled | 2.000000 | 721.963010 | 3.283166 |
| unscaled | 5.000000 | 666.841616 | -9.742892 |
| unscaled | 10.000000 | 599.710585 | -23.110520 |

## 6. partial pass 影响

| partial_pass_window | min_margin_hz | accuracy |
| --- | --- | --- |
| center_60s | -205.382989 | 0.140000 |
| first_30_percent | -110.707776 | 0.390000 |
| middle_30_percent | -96.290630 | 0.290000 |
| last_30_percent | -74.514781 | 0.340000 |
| center_120s | -69.344029 | 0.650000 |
| center_180s | -24.260397 | 0.950000 |
| full | 101.981834 | 1.000000 |

## 7. candidate_limit 影响

| candidate_limit | min_margin_hz | accuracy |
| --- | --- | --- |
| 200.000000 | -153.735891 | 0.230000 |
| 500.000000 | -205.382989 | 0.230000 |
| 1000.000000 | -205.382989 | 0.140000 |

candidate_limit 对应 best wrong 候选集合：
- 200: 47767, 47844, 48458, 48639, 58043, 60265, 61676, 62310, 62770, 62873, 62970, 63045, 63434, 63508, 63717, 64098, 64184, 64262, 64450, 64596, 64733, 64762, 64777, 64930, 65079, 65203, 65407, 65416, 65509, 65686, 65693, 65828, 65859, 65876, 65895, 66064, 66072, 66074, 66159, 66185, 66192, 66256, 66271, 66274, 66353, 66938, 66950
- 500: 46061, 47767, 47844, 48458, 48639, 58043, 60265, 61954, 62021, 62073, 62308, 62310, 62770, 62867, 62873, 62970, 63041, 63045, 63049, 63434, 63447, 63458, 63502, 63508, 63515, 63517, 63703, 63707, 63717, 64204, 64205, 64225, 64262, 64270, 64272, 64275, 64450, 64480, 64596, 64613, 64664, 64665, 64682, 64729, 64748, 64749, 64762, 64912, 64930, 65079, 65203, 65366, 65469, 65629, 65683, 65686, 65828, 65840, 65876, 65895, 66031, 66063, 66072, 66077, 66116, 66123, 66185, 66219, 66256, 66271, 66274, 66353, 66355, 66402, 66944, 66945, 66950
- 1000: 46061, 47767, 48359, 48458, 48482, 48639, 58043, 60151, 60265, 60438, 61954, 62025, 62073, 62310, 62316, 62770, 62867, 62873, 62875, 62965, 62970, 63043, 63379, 63388, 63447, 63453, 63458, 63495, 63502, 63503, 63508, 63515, 63517, 63703, 63707, 63717, 64111, 64177, 64204, 64205, 64223, 64225, 64270, 64272, 64274, 64275, 64450, 64453, 64459, 64613, 64664, 64665, 64668, 64682, 64684, 64686, 64729, 64732, 64743, 64748, 64749, 64763, 64776, 64912, 64930, 64931, 65022, 65079, 65203, 65346, 65362, 65461, 65681, 65683, 65698, 65840, 65895, 65924, 66010, 66015, 66018, 66031, 66067, 66104, 66116, 66123, 66139, 66181, 66185, 66187, 66271, 66274, 66353, 66398, 66402, 66641, 66644, 66950

## 8. 最危险 setting

- error_model_variant：frequency_scaled
- sigma_multiplier：10.0
- partial_pass_window：center_60s
- scenario：offset_plus_noise
- candidate_limit：500
- min_margin_hz：-205.382989
- best_wrong candidate：STARLINK-33818 / 63502
- known_neighbor_score_rmse_hz：2049.859853
- true_score_rmse_hz：2003.204151
- n_time_points：61
- window_duration_s：60.0

## 9. 结论边界

当前仍是 controlled stress baseline。accuracy 为 1 只能说明当前 stress 条件下 matcher 仍稳定；如果未来出现误匹配，也只能说明在该 controlled stress 条件下存在 near-neighbor confusion 风险。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；`frequency_scaled` 只是 frequency sensitivity setting，不是真实 Starlink Ku-band CFO 分布。

## 10. 下一步建议

若 margin 仍远大于 0，继续加大 sigma_multiplier 或缩短窗口；若 partial window 显著降低 margin，进入 partial-pass attack / time alignment stress；若 66274 接近 true target，进入 near-neighbor replay attack；若 candidate_limit 1000 出现新 hard wrong，后续攻击场景应优先使用新的 hard wrong。
