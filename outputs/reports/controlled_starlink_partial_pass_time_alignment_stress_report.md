# Controlled Starlink Partial-pass / Time-alignment Stress Report

生成时间：2026-05-05 19:49

## 1. 实验目的

本轮是 partial-pass / time-alignment stress，用于在 Stage 2.5 已确认 negative margin 可信的基础上，定位最危险的窗口长度和窗口中心位置。当前不是攻击实验，不是攻击成功率，不是真实 Starlink observation replay，也不是 Starlink CFO truth。

## 2. 输入配置

- target：STARLINK-1008 / 44714
- hard wrong candidates：63502 / 64732 / 66274
- error_model_variant：frequency_scaled
- sigma_multiplier：10
- scenario：offset_plus_noise
- candidate_limit：1000
- center frequency：11325000000 Hz
- station：controlled_example_station / lat=52.21 / lon=5.16 / alt_m=14.0
- window_durations_s：[30, 45, 60, 90, 120, 150, 180, 240, 'full']
- window_center_offsets_s：[-90, -60, -45, -30, -15, 0, 15, 30, 45, 60, 90]
- num_sims_per_setting：100
- mode：controlled_starlink
- observation_id：null

## 3. 数据集规模

- total_sequences：8900
- total_rows：978000
- full pass duration：267.0 s
- window point range：30 - 268
- skipped windows：0

## 4. 总体结果

- overall accuracy：0.577865
- overall min margin：-419.602774 Hz
- wrong_count：3757
- negative_margin_count：3757
- 全局最危险 window setting：duration=30, offset=0.0, best_wrong=STARLINK-33809/63508, margin=-419.602774 Hz

## 5. 窗口长度影响

- 最早出现负 margin 的窗口长度：30 s
- full window 稳定性：accuracy=1.0000, min_margin=98.867053 Hz
- 最低 min margin 的 duration：30

## 6. 窗口中心偏移影响

最危险 offset 为 `0.0` 秒。危险区域是否集中在 pass 中心附近，请结合 heatmap 和 summary CSV 查看。

## 7. hard wrong candidate 对比

- best wrong 计数 top 10：{'64732': 5348, '65373': 281, '62025': 216, '65924': 204, '64748': 171, '64184': 169, '61720': 160, '63434': 141, '65840': 138, '66274': 137}
- 63502 作为 best wrong 次数：68
- 64732 作为 best wrong 次数：5348
- 66274 作为 best wrong 次数：137

## 8. 最危险 setting

- window_duration_s：30
- window_center_offset_s：0.0
- min_margin_hz：-419.602774
- best_wrong candidate：STARLINK-33809 / 63508
- true_score_rmse_hz：2053.736499
- best_wrong_score_rmse_hz：1634.133724
- n_time_points：30
- wrong_count in setting：95
- negative_margin_count in setting：95

## 9. 结论边界

当前是 controlled partial-pass stress。负 margin 说明 matcher 在该受控条件下失稳；不能解释为真实攻击成功率，不能解释为真实 Starlink observation 结果。后续 attack 需要基于本轮定位出的窗口和 hard wrong 设计。

## 10. 下一步建议

若某个 duration/offset 明显最危险，进入 near-neighbor replay attack；若 time offset 显著影响结果，进入 time-shift attack；若没有明显规律，做更细窗口 sweep。
