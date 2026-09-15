# Controlled Starlink 多候选 Orbit-Based Matcher 报告

生成时间：2026-05-04 12:00

## 1. 本轮目标

在 `controlled_starlink` 模式下，为多个 Starlink candidate 生成同一 station / frequency / time window 下的 `f_geo_candidate_hz`，并用 candidate-conditioned profile least-squares Doppler matcher 判断 target 仿真序列是否能匹配回 `STARLINK-1008`。本轮不使用 SatNOGS observation_id，`9424971` 不参与。

## 2. 输入数据

- target dataset：`outputs/datasets/orbit_based_frequency_dataset.csv`
- candidate library：`outputs/datasets/orbit_candidate_geometry_library.csv`
- mode：`controlled_starlink`
- target：`STARLINK-1008`
- target NORAD：`44714`
- candidate 数量：100
- station：`controlled_example_station`
- center frequency：1623192000 Hz
- time window：2026-03-10T02:34:37Z 至 2026-03-10T02:39:04Z

## 3. Candidate Library 构建方法

候选来自 `data/tle/starlink_tle.txt`，只选择 Starlink。target 必须包含在库中。其他候选按简单轨道相似度排序：

```text
abs(inclination_deg - target_inclination_deg)
+ 10 * abs(mean_motion_rev_per_day - target_mean_motion_rev_per_day)
```

所有候选使用与 target dataset 完全一致的时间网格、station、center frequency 和 Doppler 公式。

## 4. 匹配方法

对每条 `sim_id` 序列和每个 candidate，计算：

```text
delta_i = f_sim_i - f_geo_candidate_i
delta_i = b + k * (t_i - t0) + e_i
score = sqrt(mean(e_i^2))
```

先拟合 `b+k` 是为了吸收 registered offset 和线性慢漂移，使 RMSE 更集中反映候选轨道 Doppler 曲线形状差异。不能直接用原始 RMSE，因为常数偏置会主导结果。

## 5. 总体结果

- 总序列数：400
- 总体 accuracy：1.0000
- 每条序列评估候选数：100

## 6. 按 scenario 统计

| scenario | 序列数 | accuracy | mean true RMSE | median true RMSE | mean best wrong RMSE | median best wrong RMSE | mean margin | median margin | error count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `clean` | 100 | 1.0000 | 0.000000 | 0.000000 | 531.181778 | 531.181778 | 531.181778 | 531.181778 | 0 |
| `offset_linear_noise` | 100 | 1.0000 | 28.291740 | 28.589665 | 531.765571 | 531.722763 | 503.473830 | 503.538284 | 0 |
| `offset_only` | 100 | 1.0000 | 0.000000 | 0.000000 | 531.181778 | 531.181778 | 531.181778 | 531.181778 | 0 |
| `offset_plus_noise` | 100 | 1.0000 | 27.955912 | 27.986252 | 531.654764 | 531.723707 | 503.698852 | 503.930415 | 0 |

## 7. 最接近 target 的错误 candidate

- candidate：`STARLINK-35760`
- NORAD：`66274`
- best wrong RMSE：526.775193 Hz
- margin：503.592450 Hz

## 8. 当前结果说明什么

- 在受控 Starlink 场景下，多候选 matcher 是否能识别目标；
- target 与相近 Starlink 候选的 Doppler 曲线差距可通过 true RMSE、best wrong RMSE 和 margin 初步观察；
- 当前只是 controlled Starlink 多候选匹配 sanity check。

## 9. 当前结果不能说明什么

- 不能说明真实 SatNOGS observation；
- 不能说明攻击成功率；
- 不能说明 pure CFO truth；
- 图表只用于 sanity check，不是强证明。

## 10. 下一步建议

- 扩展多 target；
- 寻找真实 Starlink SatNOGS observation；
- 在此基础上再加入 altitude difference / TCA shift / similar orbit 攻击场景。
