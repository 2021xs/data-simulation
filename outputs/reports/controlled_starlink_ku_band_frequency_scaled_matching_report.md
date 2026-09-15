# Controlled Starlink Multi-target Matcher 报告

生成时间：2026-05-05 13:56

## 本轮目标

在 `controlled_starlink` 模式下，对多 target Starlink 仿真数据运行 candidate-conditioned `b+k` profile least-squares Doppler matcher。本报告对应 `error_model_variant=frequency_scaled`。

## 输入数据

- dataset 序列数：2000
- dataset 行数：730800
- candidate library 行数：730800
- pass 数：10
- 每个 pass candidate 数：200 到 200
- center_freq_hz：11325000000
- mode：controlled_starlink
- observation_id：null
- 9424971：未参与本轮 Starlink 仿真

## 匹配方法

对每条仿真序列和同一 `pass_id` 下的每个候选曲线，拟合 `delta_i = b + k(t_i-t0) + e_i`，并用 `RMSE(e_i)` 作为 score。拟合 `b+k` 是为了吸收 registered offset 和一阶慢漂移，让比较聚焦在 Doppler 曲线形状上。

## 总体结果

- accuracy：1.0000
- min margin：3456.044588 Hz

## 按 scenario 统计

| scenario | 序列数 | accuracy | mean true RMSE | mean best wrong RMSE | mean margin | error count |
|---|---:|---:|---:|---:|---:|---:|
| `clean` | 500 | 1.0000 | 0.000000 | 13099.110965 | 13099.110965 | 0 |
| `offset_linear_noise` | 500 | 1.0000 | 194.289563 | 13100.573764 | 12906.284201 | 0 |
| `offset_only` | 500 | 1.0000 | 0.000001 | 13099.110965 | 13099.110963 | 0 |
| `offset_plus_noise` | 500 | 1.0000 | 196.834178 | 13100.076578 | 12903.242400 | 0 |

## 按 target 统计

| target | NORAD | accuracy | mean margin | min margin | error count |
|---|---|---:|---:|---:|---:|
| `STARLINK-1008` | `44714` | 1.0000 | 3610.635349 | 3456.044588 | 0 |
| `STARLINK-1227` | `45230` | 1.0000 | 19419.911832 | 19255.426280 | 0 |
| `STARLINK-2103` | `47383` | 1.0000 | 11895.110762 | 11747.694619 | 0 |
| `STARLINK-2163` | `47749` | 1.0000 | 21004.783736 | 20851.380506 | 0 |
| `STARLINK-2517` | `48309` | 1.0000 | 24908.161879 | 24760.084792 | 0 |
| `STARLINK-34983` | `65411` | 1.0000 | 10808.444620 | 10654.593228 | 0 |
| `STARLINK-35022` | `65409` | 1.0000 | 6485.305524 | 6333.894801 | 0 |
| `STARLINK-35024` | `65410` | 1.0000 | 11109.092704 | 10962.684832 | 0 |
| `STARLINK-35137` | `65686` | 1.0000 | 13422.055206 | 13273.716584 | 0 |
| `STARLINK-35146` | `65421` | 1.0000 | 7355.869713 | 7210.308965 | 0 |

## 最容易混淆的样本对

- target：`STARLINK-1008` / `44714`
- best wrong candidate：`STARLINK-35760` / `66274`
- min margin：3456.044588 Hz

## 边界说明

当前只是 controlled Starlink TLE-based simulation baseline，不是真实 SatNOGS observation，不是攻击场景，不说明攻击成功率，也不说明 pure CFO truth。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；噪声是第一版高斯近似。
