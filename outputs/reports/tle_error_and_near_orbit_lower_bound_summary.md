# Freshness-Aware TLE Error Calibration 与 Near-Orbit Delta 下界

生成时间：2026-06-10

## 1. 为什么重做 freshness-aware calibration

上一版使用 `epoch_sep_hours <= 72h` 的 TLE-to-TLE proxy 后，误差带非常宽。例如 30s middle p95 约 386.6 Hz，full-pass p95 约 29.2 kHz。这类 all-pair / stale-TLE 差异更适合作为 stale-TLE sensitivity，不适合直接作为 normal-error lower bound。

本轮把同星多 TLE 差异按 TLE freshness 相对观测窗口中心重新分层。目标是区分：

- fresh public TLE uncertainty：适合作为 near-orbit attack 下界参考；
- stale TLE / propagation aging：只作为敏感性分析，不直接作为 normal-error band。

TLE-to-TLE difference is not precise orbit truth. It is an empirical proxy for public-TLE uncertainty under different data freshness assumptions.

## 2. 数据与去重

- TLE history source：`data/tle/history/starlink_gp_history_20260301_20260320.tle`
- 原始 TLE records：431
- 按 `(NORAD, epoch)` 去重后：386
- duplicate `(NORAD, epoch)` records removed：45
- 参与 NORAD：`47749, 48458, 58380, 65409, 65410, 65411, 65693`
- selected targets：7
- tle_error_available：`true`
- diagnostic_delta_sweep_only：`false`

## 3. Freshness Bin 样本数

重点窗口位置 `middle/full_pass`、`epoch_sep_bin=all_pairs` 下的样本数：

| freshness_bin | n_tle_pairs | n_sats | primary use |
|---|---:|---:|---|
| fresh_6h | 0 | 0 | sample too small, not used |
| fresh_12h | 6 | 5 | sample too small, not used |
| operational_24h | 51 | 7 | primary band |
| stale_72h | 287 | 7 | stale sensitivity only |
| all | 1313 | 7 | stale/all sensitivity only |

Primary band 选择规则：优先 `fresh_12h`，若样本数少于 30 则使用 `operational_24h`。本轮 `fresh_12h` 样本不足，因此：

```text
primary_error_band_source = operational_24h
```

## 4. Freshness-Aware Tau Error Band

下表为 `middle/full_pass`、`epoch_sep_bin=all_pairs` 的 p95/p99。`operational_24h` 是本轮 primary band。

| window | p95_fresh_12h | p99_fresh_12h | p95_operational_24h | p99_operational_24h | p95_stale_72h | p99_stale_72h | p95_all | p99_all |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 30s middle | 24.579 | 30.134 | 43.276 | 60.707 | 185.551 | 293.191 | 361.125 | 546.681 |
| 45s middle | 51.025 | 62.300 | 97.786 | 131.652 | 435.171 | 604.852 | 802.003 | 1159.089 |
| 60s middle | 90.559 | 110.779 | 166.088 | 229.112 | 737.030 | 1083.757 | 1400.767 | 2126.653 |
| 90s middle | 185.820 | 226.795 | 355.884 | 481.454 | 1633.758 | 2259.207 | 3137.590 | 4671.818 |
| 120s middle | 295.925 | 360.205 | 597.853 | 788.226 | 2842.481 | 3848.512 | 5478.661 | 8130.902 |
| 180s middle | 514.334 | 622.000 | 1207.650 | 1460.179 | 5846.993 | 7759.135 | 11200.277 | 15889.584 |
| full_pass | 911.924 | 1106.252 | 2095.695 | 2518.873 | 10018.374 | 17645.226 | 33581.911 | 47451.023 |

Freshness-aware calibration 显著降低了 error band。以 30s middle 为例，上一版 `<=72h` p95 约 386.6 Hz；本轮 primary `operational_24h` p95 为 43.3 Hz。full-pass 从约 29.2 kHz 降到约 2.10 kHz。

## 5. Near-Orbit Delta Min 更新

使用 `operational_24h` primary band 后，0.1-200 km along-track perturbation 开始出现 crossing。

重点窗口：

| window | position | n sat/direction | median delta_min_p95 | median delta_min_p99 | crossed p95 | crossed p99 |
|---|---|---:|---:|---:|---:|---:|
| 30s | middle | 14 | 50 km | 50 km | 14 | 14 |
| 45s | middle | 14 | 50 km | 50 km | 14 | 14 |
| 60s | middle | 14 | 50 km | 50 km | 14 | 14 |
| 90s | middle | 14 | 50 km | 50 km | 14 | 14 |
| 120s | middle | 14 | 50 km | 50 km | 14 | 14 |
| 180s | middle | 14 | 50 km | 50 km | 14 | 14 |
| full_pass | full_pass | 14 | 50 km | 50 km | 14 | 14 |
| 30s-180s | best_attack | 14 each | NaN | NaN | 0 | 0 |

`best_attack` 窗口仍无 crossing，说明攻击者若能选择最相似短窗口，0.1-200 km along-track perturbation 仍可落在 fresh primary band 内。固定 `middle` 和 full-pass 则更容易超过 primary band。

## 6. Perturbation Score Growth

全窗口/位置聚合的 median residual RMSE 随 delta 增大：

| delta_km | median residual RMSE |
|---:|---:|
| 0.1 | 0.240 Hz |
| 1 | 2.404 Hz |
| 10 | 24.174 Hz |
| 20 | 48.809 Hz |
| 50 | 125.291 Hz |
| 100 | 248.256 Hz |
| 200 | 432.858 Hz |

这解释了为什么 fresh primary band 后，约 50 km 会成为多个 fixed-window 的 crossing 中位数。

## 7. 结论边界

按 TLE 新鲜度分层后的同星多 TLE 差异，可以作为公开 TLE 数据不确定性的经验代理，用来避免把低于该不确定性的扰动误解释为攻击。

本轮不能写成“真实轨道误差真值”。也不能把 `stale_72h` 或 `all` 直接当 normal-error lower bound。它们显示的是 stale-TLE sensitivity。

## 8. 下一步建议

可以进入 constrained near-orbit impersonation attack first pass，但要按窗口策略分开：

- fixed-window / full-pass：从 `50 km` 左右开始作为 mild near-orbit crossing case；
- moderate：`100-200 km`，用于稳定超过 fresh primary band 的 stress case；
- strong：`500 km+` 仅作为更强 stress sweep，需额外说明是否仍满足 near-orbit / same-shell assumption；
- best_attack short window：0.1-200 km 仍未 crossing，应作为短窗口 DEFER 或多窗口一致性策略的重点测试，而不是直接 ACCEPT。

建议下一轮 attack runner 同时报告：

- 是否超过 `operational_24h` primary tau；
- 是否超过 `stale_72h` sensitivity tau；
- verifier strong/weak decision；
- fixed middle / full-pass / best-window 三种窗口策略的差异。
