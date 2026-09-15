# Target Pass-Quality Availability Summary

## 1. 实验目的

verifier v3 使用 pass-quality-aware DEFER 规则：low-quality full-pass 不直接 ACCEPT，而是等待 high-quality full-pass。本轮检查该规则在当前单站设置下的可用性，回答目标卫星是否能在合理时间内等到 `max_elevation_deg >= 20` 的认证窗口。

## 2. 设置

- station: `controlled_example_station`, lat=`52.2100`, lon=`5.1600`, alt=`14 m`
- target set: 当前 `controlled_starlink_20target_selection_table.csv` 中的 `20` 个 Starlink targets
- visible pass finder: 复用现有 Skyfield / SGP4 `find_pass` 逻辑
- visible mask: 使用当前 time_window 的 `min_elevation_deg`
- audit scan step: `10.0 s`；用于 availability 统计，elevation 定义与当前 verifier/pass finder 一致
- low: `max_elevation_deg < 20`
- medium: `20 <= max_elevation_deg < 40`
- high: `max_elevation_deg >= 40`
- high-quality pass for verifier v3: `max_elevation_deg >= 20`

## 3. 总体结果

- 7 days: high-quality targets = `20/20`, only-low = `0`, no-visible = `0`, median time-to-first-HQ = `6.68 h`, p90 = `14.48 h`
- 14 days: high-quality targets = `20/20`, only-low = `0`, no-visible = `0`, median time-to-first-HQ = `6.68 h`, p90 = `14.48 h`
- 30 days: high-quality targets = `20/20`, only-low = `0`, no-visible = `0`, median time-to-first-HQ = `6.68 h`, p90 = `14.48 h`

30 天窗口下：

- total targets = `20`
- visible target count = `20`
- targets with high-quality pass = `20`
- only-low targets = `0`，占比 `0.00%`
- mean time-to-first-high-quality = `7.03 h`
- median time-to-first-high-quality = `6.68 h`
- p90 time-to-first-high-quality = `14.48 h`

## 4. Only-Low Target 分析

30 天窗口内没有 only-low target。

如果存在 only-low target，说明单站 v3 可能长期 DEFER，需要考虑更长 audit window、多个低仰角 pass 聚合，或 multi-station consistency。

## 5. Delayed Target 分析

30 天窗口内没有 delayed target。

## 6. 对 Verifier v3 的影响

如果大多数目标在 7/14/30 天内都有 high-quality pass，则当前 v3 的可用性较好；如果 only-low 或 delayed target 比例高，则单站规则会带来较多 DEFER，需要进入 multi-station availability audit。

本轮仍支持 `max_elevation_deg >= 20` 作为当前 high-quality pass 初步规则；它不会被可用性结果自动推翻，但如果目标长期无法等到 20 度以上 pass，则需要从系统层面补站或延长等待窗口。

## 7. 阶段性结论

1. 当前单站 availability audit 给出了 v3 DEFER 规则的可用性边界。
2. high-quality pass 的覆盖率决定 v3 能否从 DEFER 进入 ACCEPT。
3. only-low targets 是 multi-station consistency 的优先候选。
4. delayed targets 更适合调度式 high-quality pass challenge。
5. 下一步应根据 only-low / delayed 比例决定是否进入 multi-station availability audit。
