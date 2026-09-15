# Orbit-Based 仿真数据集报告

生成时间：2026-05-04 10:15

## 1. 本轮模式

- mode：`controlled_starlink`
- 本轮使用真实 Starlink TLE，但没有使用真实 SatNOGS observation 条件。station / frequency / time window 是受控实验配置。9424971 只是前一阶段 waterfall/residual 提取中的高质量样本，不参与本轮 Starlink orbit-based simulation。

## 2. 输入与来源

- target：`STARLINK-1008`
- NORAD ID：`44714`
- TLE 来源：`data/tle/starlink_tle.txt`
- observation_id：`None`
- observation_source：`controlled_manual`
- station_source：`controlled_manual`
- frequency_source：`controlled_manual`
- time_window_source：`auto_pass_search`

## 3. station / frequency / time window

- station：`controlled_example_station`，lat=52.21 deg，lon=5.16 deg，alt=14.0 m
- center frequency：1623192000 Hz
- start：2026-03-10T02:34:37Z
- end：2026-03-10T02:39:04Z
- duration：267.0 s
- step：1.0 s
- time points：268
- elevation range：10.012 到 15.380 deg

## 4. Doppler 计算公式

```text
doppler_hz = - center_freq_hz * range_rate_mps / c
f_geo_tle_hz = center_freq_hz + doppler_hz
```

`range_rate_mps` 使用相邻 range 的有限差分估计。符号约定是第一版工程约定，后续应结合真实样本或 STRF 结果做 sanity check。

## 5. 频率范围

- `f_geo_tle_hz` min：1623169907.750823 Hz
- `f_geo_tle_hz` max：1623213909.556452 Hz
- `f_geo_tle_hz` range：44001.805629 Hz
- `doppler_hz` min：-22092.249177 Hz
- `doppler_hz` max：21909.556452 Hz
- `doppler_hz` range：44001.805629 Hz

## 6. 参数范围

| 参数 | main_range |
|---|---|
| `b_hz` | `[3179.0, 3728.0]` |
| `k_hz_per_s` | `[-1.110156, -0.197808]` |
| `sigma_hz` | `[23.215, 32.89]` |

## 7. 生成场景

| scenario | 序列数 | 行数 |
|---|---:|---:|
| `clean` | 100 | 26800 |
| `offset_only` | 100 | 26800 |
| `offset_plus_noise` | 100 | 26800 |
| `offset_linear_noise` | 100 | 26800 |

## 8. f_sim_hz - f_geo_tle_hz 统计

| scenario | mean | std | min | max | count |
|---|---:|---:|---:|---:|---:|
| `clean` | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 26800 |
| `offset_linear_noise` | 3453.621271 | 174.710373 | 2984.691486 | 3885.078510 | 26800 |
| `offset_only` | 3446.208434 | 149.466997 | 3183.041886 | 3714.616671 | 26800 |
| `offset_plus_noise` | 3458.572158 | 161.911473 | 3099.835364 | 3806.424922 | 26800 |

## 9. 当前结果说明什么

本轮结果说明 TLE-based Doppler 生成链路跑通，并能在 `f_geo_tle_hz` 上叠加 registered offset / linear drift / first-order Gaussian noise。

## 10. 当前结果不能说明什么

- 不能说明真实 SatNOGS observation 对齐，除非 mode 为 `satnogs_observation`；
- 不能说明攻击成功率；
- `registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias，不是 pure CFO truth；
- noise 是第一版高斯近似。

## 11. 下一步

下一步应建立多候选 Starlink TLE 库，在同一 station / frequency / time window 下生成候选 `f_geo_tle_hz`，再进入 orbit-based matcher。
