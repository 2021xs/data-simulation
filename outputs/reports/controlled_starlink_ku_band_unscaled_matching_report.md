# Controlled Starlink Multi-target Matcher 报告

生成时间：2026-05-05 13:54

## 本轮目标

在 `controlled_starlink` 模式下，对多 target Starlink 仿真数据运行 candidate-conditioned `b+k` profile least-squares Doppler matcher。本报告对应 `error_model_variant=unscaled`。

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
- min margin：3669.339725 Hz

## 按 scenario 统计

| scenario | 序列数 | accuracy | mean true RMSE | mean best wrong RMSE | mean margin | error count |
|---|---:|---:|---:|---:|---:|---:|
| `clean` | 500 | 1.0000 | 0.000000 | 13099.110965 | 13099.110965 | 0 |
| `offset_linear_noise` | 500 | 1.0000 | 27.847176 | 13099.080248 | 13071.233072 | 0 |
| `offset_only` | 500 | 1.0000 | 0.000001 | 13099.110965 | 13099.110963 | 0 |
| `offset_plus_noise` | 500 | 1.0000 | 28.211891 | 13099.001886 | 13070.789995 | 0 |

## 按 target 统计

| target | NORAD | accuracy | mean margin | min margin | error count |
|---|---|---:|---:|---:|---:|
| `STARLINK-1008` | `44714` | 1.0000 | 3692.059512 | 3669.339725 | 0 |
| `STARLINK-1227` | `45230` | 1.0000 | 19503.648278 | 19479.949129 | 0 |
| `STARLINK-2103` | `47383` | 1.0000 | 11978.170911 | 11956.849263 | 0 |
| `STARLINK-2163` | `47749` | 1.0000 | 21088.343948 | 21066.259780 | 0 |
| `STARLINK-2517` | `48309` | 1.0000 | 24991.317314 | 24970.015652 | 0 |
| `STARLINK-34983` | `65411` | 1.0000 | 10892.390505 | 10870.135247 | 0 |
| `STARLINK-35022` | `65409` | 1.0000 | 6567.187200 | 6545.189658 | 0 |
| `STARLINK-35024` | `65410` | 1.0000 | 11191.019559 | 11169.880578 | 0 |
| `STARLINK-35137` | `65686` | 1.0000 | 13506.990718 | 13485.600145 | 0 |
| `STARLINK-35146` | `65421` | 1.0000 | 7439.484543 | 7418.330372 | 0 |

## 最容易混淆的样本对

- target：`STARLINK-1008` / `44714`
- best wrong candidate：`STARLINK-35760` / `66274`
- min margin：3669.339725 Hz

## 边界说明

当前只是 controlled Starlink TLE-based simulation baseline，不是真实 SatNOGS observation，不是攻击场景，不说明攻击成功率，也不说明 pure CFO truth。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；噪声是第一版高斯近似。
