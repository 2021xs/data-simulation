# Controlled Starlink Ku-band Frequency Variant 对比报告

生成时间：2026-05-05 13:56

## 1. 实验目的

本轮是 Starlink Ku-band frequency variant + error model sensitivity baseline。它不是攻击实验，不是真实 Starlink observation replay，不是高精度定轨，也不是真实 CFO 分布估计。

## 2. 输入配置

- source_center_freq_hz：1623192000
- simulation_center_freq_hz：11325000000
- frequency_scale_factor：6.976993480
- target_count：10
- candidate_limit：200
- num_sims_per_target：50
- scenarios：clean, offset_only, offset_plus_noise, offset_linear_noise
- station：controlled_example_station / lat=52.21 / lon=5.16 / alt_m=14
- TLE 文件：data\tle\starlink_tle.txt
- mode：controlled_starlink
- observation_id：null
- pass duration 概况：267.0 - 444.0 s
- candidate library 行数：730800

## 3. 两版误差模型说明

`unscaled` 使用前期 SatNOGS / STRF 提取的 effective residual 参数范围，用于 first-order robustness test，不能解释成 Starlink Ku-band 真值。

`frequency_scaled` 按频率比例缩放 `b / k / sigma`，用于 ppm-sensitive sensitivity setting，不能解释成所有误差真实线性缩放，也不能写成真实 Starlink Ku-band CFO 分布。

## 4. 数据集规模

| variant | target 数 | sequence 数 | row 数 | scenario 数 | candidate 数 |
|---|---:|---:|---:|---:|---:|
| unscaled | 10 | 2000 | 730800 | 4 | 200 |
| frequency_scaled | 10 | 2000 | 730800 | 4 | 200 |

## 5. Matcher 结果

| error_model_variant | scenario | sequences | accuracy | mean_margin_hz | min_margin_hz | mean_true_score_rmse_hz | mean_best_wrong_score_rmse_hz |
| --- | --- | --- | --- | --- | --- | --- | --- |
| frequency_scaled | clean | 500 | 1.000000 | 13099.110965 | 3706.051805 | 0.000000 | 13099.110965 |
| frequency_scaled | offset_linear_noise | 500 | 1.000000 | 12906.284201 | 3467.815261 | 194.289563 | 13100.573764 |
| frequency_scaled | offset_only | 500 | 1.000000 | 13099.110963 | 3706.051803 | 0.000001 | 13099.110965 |
| frequency_scaled | offset_plus_noise | 500 | 1.000000 | 12903.242400 | 3456.044588 | 196.834178 | 13100.076578 |
| unscaled | clean | 500 | 1.000000 | 13099.110965 | 3706.051805 | 0.000000 | 13099.110965 |
| unscaled | offset_linear_noise | 500 | 1.000000 | 13071.233072 | 3671.056637 | 27.847176 | 13099.080248 |
| unscaled | offset_only | 500 | 1.000000 | 13099.110963 | 3706.051803 | 0.000001 | 13099.110965 |
| unscaled | offset_plus_noise | 500 | 1.000000 | 13070.789995 | 3669.339725 | 28.211891 | 13099.001886 |

## 6. hardest target / most confusable pair

| error_model_variant | target_name | target_norad_id | accuracy | mean_margin_hz | min_margin_hz |
| --- | --- | --- | --- | --- | --- |
| frequency_scaled | STARLINK-1008 | 44714 | 1.000000 | 3610.635349 | 3456.044588 |
| unscaled | STARLINK-1008 | 44714 | 1.000000 | 3692.059512 | 3669.339725 |

- unscaled most confusable pair：STARLINK-1008 / 44714 vs STARLINK-35760 / 66274，min margin=3669.339725 Hz
- frequency_scaled most confusable pair：STARLINK-1008 / 44714 vs STARLINK-35760 / 66274，min margin=3456.044588 Hz
- hardest target 是否为 STARLINK-1008 / 44714：unscaled=True，frequency_scaled=True
- most confusable pair 是否仍为 STARLINK-1008 / 44714 vs STARLINK-35760 / 66274：unscaled=True，frequency_scaled=True

## 7. 关键结论

- Ku-band 后 Doppler Hz 量级明显变大：本轮 Doppler 范围约为 -253820.363 到 253764.869 Hz。
- unscaled mean margin 为 13085.061249 Hz；frequency_scaled mean margin 为 13001.937132 Hz；二者比例约为 0.993647。
- `frequency_scaled` 会同步放大 `b / k / noise`，其中 `b+k` 会被 matcher 的 nuisance 拟合吸收，噪声会直接抬高 true RMSE 并可能压低 margin。
- 当前 controlled baseline 下 matcher 是否稳定识别 true target：unscaled accuracy=1.0000，frequency_scaled accuracy=1.0000。
- 即使 accuracy 为 1，也不能解释为攻击不可能；当前没有 near-neighbor stress、time shift、replay 或 partial pass 攻击设置。

## 8. 边界说明

本轮不使用真实 SatNOGS observation，不使用 observation_id，不使用 9424971，不混用 Iridium observation 和 Starlink TLE。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；`noise` 是第一版高斯近似。

## 9. 后续建议

下一阶段建议优先做 `near-neighbor stress test`，随后加入 `sigma_multiplier = 1 / 2 / 5 / 10`、`candidate_limit = 200 / 500 / 1000`、partial pass、time shift attack 和 near-neighbor replay attack。
