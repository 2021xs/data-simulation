# Controlled Starlink 多 Target Baseline 报告

生成时间：2026-05-04 13:16

## 1. 本轮目标

在 `controlled_starlink` 模式下，对多个 Starlink target 分别自动寻找 pass、生成仿真数据，并为每个 pass 构建 candidate library 后运行 `b+k` profile least-squares matcher。本轮不使用 SatNOGS observation_id，不使用 9424971，不做攻击场景。

## 2. 数据规模

- target 数：10
- scenario 数：4
- sim 序列数：2000
- 数据行数：730800
- candidate library 行数：730800
- 每 pass candidate 数：200 到 200
- true target 是否均包含：是

## 3. Target 选择方法

从 `data/tle/starlink_tle.txt` 解析 Starlink TLE，强制包含 `STARLINK-1008 / 44714`。其余 target 按 inclination 和 mean motion 与 STARLINK-1008 的简单相似度排序选择。若 target 无可见 pass 会被记录并跳过，本轮未伪造 pass。

## 4. 成功生成数据的 target / pass

| pass_id | target | NORAD | pass_start_utc | pass_end_utc | duration_s | max_elevation_deg | time_points |
|---|---|---|---|---|---:|---:|---:|
| `pass_44714` | `STARLINK-1008` | `44714` | 2026-03-10T02:34:37Z | 2026-03-10T02:39:04Z | 267.0 | 15.380 | 268 |
| `pass_65686` | `STARLINK-35137` | `65686` | 2026-03-10T13:15:05Z | 2026-03-10T13:20:48Z | 343.0 | 21.449 | 344 |
| `pass_65421` | `STARLINK-35146` | `65421` | 2026-03-10T06:42:22Z | 2026-03-10T06:48:37Z | 375.0 | 26.254 | 376 |
| `pass_65409` | `STARLINK-35022` | `65409` | 2026-03-10T06:40:53Z | 2026-03-10T06:47:05Z | 372.0 | 25.759 | 373 |
| `pass_65410` | `STARLINK-35024` | `65410` | 2026-03-10T06:40:12Z | 2026-03-10T06:46:23Z | 371.0 | 25.526 | 372 |
| `pass_47749` | `STARLINK-2163` | `47749` | 2026-03-10T04:37:31Z | 2026-03-10T04:44:21Z | 410.0 | 36.648 | 411 |
| `pass_47383` | `STARLINK-2103` | `47383` | 2026-03-10T15:48:22Z | 2026-03-10T15:54:08Z | 346.0 | 21.836 | 347 |
| `pass_65411` | `STARLINK-34983` | `65411` | 2026-03-10T06:22:21Z | 2026-03-10T06:27:51Z | 330.0 | 20.011 | 331 |
| `pass_48309` | `STARLINK-2517` | `48309` | 2026-03-10T01:21:05Z | 2026-03-10T01:28:29Z | 444.0 | 87.567 | 445 |
| `pass_45230` | `STARLINK-1227` | `45230` | 2026-03-10T15:07:32Z | 2026-03-10T15:13:58Z | 386.0 | 28.786 | 387 |

未成功 target 及原因：无

## 5. Candidate library 规模

| pass_id | candidate 数 | 包含 true target |
|---|---:|---|
| `pass_44714` | 200 | 是 |
| `pass_45230` | 200 | 是 |
| `pass_47383` | 200 | 是 |
| `pass_47749` | 200 | 是 |
| `pass_48309` | 200 | 是 |
| `pass_65409` | 200 | 是 |
| `pass_65410` | 200 | 是 |
| `pass_65411` | 200 | 是 |
| `pass_65421` | 200 | 是 |
| `pass_65686` | 200 | 是 |

## 6. 匹配方法

对每条仿真序列，只使用同一 `pass_id` 下的 candidate 曲线，拟合 `delta_i = b + k(t_i-t0) + e_i`，用 `RMSE(e_i)` 评分。这样可以吸收 registered offset 和线性慢漂移，比较 Doppler 曲线形状。

## 7. 总体结果

- 总体 accuracy：1.0000

## 8. 按 scenario

| scenario | 序列数 | accuracy | mean margin | error count |
|---|---:|---:|---:|---:|
| `clean` | 500 | 1.0000 | 1877.472152 | 0 |
| `offset_linear_noise` | 500 | 1.0000 | 1849.834637 | 0 |
| `offset_only` | 500 | 1.0000 | 1877.472152 | 0 |
| `offset_plus_noise` | 500 | 1.0000 | 1849.398661 | 0 |

## 9. 按 target

| target | NORAD | accuracy | mean margin | error count |
|---|---|---:|---:|---:|
| `STARLINK-1008` | `44714` | 1.0000 | 517.505908 | 0 |
| `STARLINK-1227` | `45230` | 1.0000 | 2783.421239 | 0 |
| `STARLINK-2103` | `47383` | 1.0000 | 1704.904956 | 0 |
| `STARLINK-2163` | `47749` | 1.0000 | 3010.578095 | 0 |
| `STARLINK-2517` | `48309` | 1.0000 | 3570.042304 | 0 |
| `STARLINK-34983` | `65411` | 1.0000 | 1549.155041 | 0 |
| `STARLINK-35022` | `65409` | 1.0000 | 929.527245 | 0 |
| `STARLINK-35024` | `65410` | 1.0000 | 1592.246393 | 0 |
| `STARLINK-35137` | `65686` | 1.0000 | 1923.759173 | 0 |
| `STARLINK-35146` | `65421` | 1.0000 | 1054.303653 | 0 |

## 10. 最难样本与混淆对

- margin 最小 target：`STARLINK-1008` / `44714`
- 最接近错误候选：`STARLINK-35760` / `66274`
- 最小 margin：495.348691 Hz
- 错误最多 target：无误匹配

## 11. 当前结果说明什么

说明 controlled Starlink 多 target baseline 在当前候选库和受控条件下是否稳定；margin 可作为 target 与近邻 Starlink Doppler 曲线差异的 sanity check。

## 12. 当前结果不能说明什么

这不是真实 SatNOGS observation，不是攻击场景，不是攻击成功率，也不说明 pure CFO truth。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias。

## 13. 下一步建议

寻找真实 Starlink SatNOGS observation；做 near-neighbor / TCA shift / similar orbit 攻击；增加 threshold verification。
