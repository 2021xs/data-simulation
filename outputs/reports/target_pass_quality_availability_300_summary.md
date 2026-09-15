# 300-Target Pass-Quality Availability Audit Summary

## 1. 实验目的

本轮将 pass-quality availability audit 从 100 个 Starlink targets 扩展到 300 个 targets，用于检查 verifier v3 的 low-pass DEFER 规则是否存在大样本可用性长尾问题。本轮只统计可见完整过境窗口的质量分布，不生成 attack observation，不运行 score / k_hat verifier，也不改变 observation/model residual terms。

## 2. 设置

- station: `controlled_example_station`, lat = `52.2100`, lon = `5.1600`, alt = `14 m`
- target selection: 先保留已有 20-target selection table 中的目标，再从本地 Starlink TLE 按 NORAD ID 排序补足到 300 个 targets
- actual target_count: `300`
- audit duration: `7 / 14 / 30 days`
- scan_step_s: `30`
- visible pass finder / SGP4 / elevation 计算: 复用当前 verifier/pass finder 逻辑
- low: `max_elevation_deg < 20`
- medium: `20 <= max_elevation_deg < 40`
- high: `max_elevation_deg >= 40`
- high-quality pass: `max_elevation_deg >= 20`

## 3. 总体结果

| duration_days | high-quality targets | only-low targets | no-visible targets | median time-to-first-HQ (h) | p90 (h) | max (h) | HQ pass count mean | median | p10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 7 | 300 / 300 | 0 | 0 | 5.46 | 16.60 | 20.17 | 27.87 | 28 | 26 |
| 14 | 300 / 300 | 0 | 0 | 5.46 | 16.60 | 20.17 | 55.41 | 56 | 52 |
| 30 | 300 / 300 | 0 | 0 | 5.46 | 16.60 | 20.17 | 116.43 | 119 | 108 |

300 个 targets 在 7 / 14 / 30 天内全部存在 high-quality pass，`only_low_single_station_count = 0`，`delayed_authentication_count = 0`，`no_visible_target_count = 0`。

30 天窗口下 high-quality pass count 的最低值为 `19`，对应 `STARLINK-1738 / 46336`；该 target 仍有 high-quality pass，且 `max_elevation_deg_max = 88.88`，因此不是 only-low target。

## 4. 与 20 / 100 Target 结果对比

- 20-target: `20 / 20` 有 high-quality pass，only-low = `0`，median time-to-first-HQ = `6.68 h`，p90 = `14.48 h`
- 100-target: `100 / 100` 有 high-quality pass，only-low = `0`，median time-to-first-HQ = `7.48 h`，p90 = `16.00 h`，max = `17.92 h`
- 300-target: `300 / 300` 有 high-quality pass，only-low = `0`，median time-to-first-HQ = `5.46 h`，p90 = `16.60 h`，max = `20.17 h`

与 100-target 相比，300-target 的 p90 和 max 等待时间略有增加，但没有出现 only-low 或 delayed_authentication targets。30 天 high-quality pass count 的 p10 为 `108`，没有出现明显的低值长尾。

## 5. 对 Verifier v3 的影响

当前 300-target controlled set 下，low-pass DEFER 规则没有造成明显可用性阻塞。所有目标都能在 7 天窗口内等到 `max_elevation_deg >= 20` 的 high-quality pass，因此单站 v3 可以从 DEFER 进入可执行的 ACCEPT/REJECT 判决。

本轮仍支持 `max_elevation_deg >= 20` 作为当前 high-quality pass 初步规则。该结论只覆盖当前 controlled station、本地 TLE、当前 pass finder 和 300-target 选择规则；不等价于全星座、任意地面站或真实业务调度保证。

## 6. 后续建议

在当前 300-target 结果下，暂不需要立刻进入 multi-station availability audit。更合适的下一步是先整理组会材料，说明 v3 在 20 / 100 / 300 targets 下均未出现单站可用性阻塞。

如果后续需要进一步扩大外推边界，可以把 500-target availability audit 作为附加验证；如果 500-target 或其他 station 下出现 only-low / delayed 长尾，再进入 multi-station availability audit。

## 7. 阶段性结论

1. 300-target audit 中 `300 / 300` targets 在 7 / 14 / 30 天内均有 high-quality pass。
2. only-low targets 仍为 `0`，说明当前 controlled station 下 low-pass DEFER 没有造成长期无法认证的目标集合。
3. time-to-first-high-quality 的长尾有限：p90 = `16.60 h`，max = `20.17 h`。
4. 30 天 high-quality pass count 的 p10 = `108`，未出现明显 high-quality pass count 低值长尾。
5. 当前结果支持继续使用 verifier v3 的 `max_elevation_deg >= 20` high-quality 初步规则；500-target 可作为附加验证，而不是当前主线阻塞项。
