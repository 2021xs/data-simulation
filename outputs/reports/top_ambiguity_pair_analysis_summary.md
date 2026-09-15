# Top Ambiguity Pair 定向复测总结

生成时间：2026-06-10

## 1. 实验目的

上一轮 short-window best-claim first pass 显示，完整窗口下真实身份稳定 top-1，但 30s 短窗口会显著放大 Doppler ambiguity：`65409 -> 65410` 和 `65410 -> 65409` 在 weak-prior 下出现 non-self accept，strong-prior 下没有 non-self accept。

本轮不继续扩大候选池，也不引入主动补偿，而是对已经暴露的 top ambiguity pairs 做定向复测，判断这些 pair 的混淆是否稳定、窗口变长后是否快速消失，以及 strong-prior 的拒绝主要来自 residual score 还是 fitted b/k gate。

## 2. 实验设置

分析 pair：

- `65409 -> 65410`
- `65410 -> 65409`
- `65411 -> 47749`
- `48458 -> 58380`
- `65693 -> 47749`

窗口设置：

- window_duration_s：`30, 45, 60, 90, 120, 180, full`
- window_position：`first, middle, last, best_margin, best_score`
- window_step_s：`10`
- residual_mode：`empirical`

判决设置：

- strong-prior：residual score + fitted b/k gate + quality gate。
- weak-prior：residual score + necessary quality gate，不因 b/k gate 失败直接拒绝。

输出文件：

- `outputs/metrics/top_ambiguity_pair_eval.csv`
- `outputs/metrics/top_ambiguity_pair_summary.csv`
- `outputs/datasets/top_ambiguity_pair_window_curves.csv`
- `outputs/reports/top_ambiguity_pair_analysis_summary.md`

图表：

- `outputs/figures/top_ambiguity_pair_margin_vs_duration.png`
- `outputs/figures/top_pair_65409_65410_30s_residuals.png`

本轮输出规模：

- pair/window evaluation rows：155
- window curve rows：14839
- summary rows：35

## 3. 65409 <-> 65410 重点分析

`65409` 与 `65410` 是本轮最明确的双向短窗口 ambiguity pair。两方向在 30s 下 self 与 claim 的 score margin 都接近 0，并且都出现 weak-prior non-self accept；但 strong-prior 没有接受。

| pair | duration | min margin Hz | median margin Hz | weak accept | strong accept | median range-rate corr |
|---|---:|---:|---:|---:|---:|---:|
| 65409 -> 65410 | 30s | 0.509 | 52.576 | 2 | 0 | 0.999922 |
| 65409 -> 65410 | 45s | 26.840 | 150.108 | 0 | 0 | 0.999818 |
| 65409 -> 65410 | 60s | 86.759 | 307.038 | 0 | 0 | 0.999704 |
| 65409 -> 65410 | 90s | 330.628 | 836.877 | 0 | 0 | 0.999420 |
| 65409 -> 65410 | 120s | 755.799 | 1364.575 | 0 | 0 | 0.999072 |
| 65409 -> 65410 | 180s | 2052.233 | 2871.738 | 0 | 0 | 0.997798 |
| 65409 -> 65410 | full | 20783.235 | 20783.235 | 0 | 0 | 0.989601 |
| 65410 -> 65409 | 30s | 5.452 | 54.433 | 2 | 0 | 0.999914 |
| 65410 -> 65409 | 45s | 33.839 | 160.865 | 0 | 0 | 0.999825 |
| 65410 -> 65409 | 60s | 96.678 | 323.533 | 0 | 0 | 0.999715 |
| 65410 -> 65409 | 90s | 361.861 | 852.133 | 0 | 0 | 0.999442 |
| 65410 -> 65409 | 120s | 793.249 | 1474.893 | 0 | 0 | 0.999106 |
| 65410 -> 65409 | 180s | 2031.938 | 2671.781 | 0 | 0 | 0.998228 |
| 65410 -> 65409 | full | 20933.203 | 20933.203 | 0 | 0 | 0.989507 |

观察：

- 30s best-window 下，两个方向都接近 verification-level ambiguity，但仅限 weak-prior。
- 45s 开始 weak-prior accept 消失；60s 后 margin 继续扩大。
- full-pass margin 回到约 20 kHz，和上一轮完整窗口 best-claim 稳定结论一致。
- `claim_b_gate_fail_count` 和 `claim_k_gate_fail_count` 在所有窗口位置上均为失败，因此 strong-prior 拒绝 weak-only 样本的主要原因是 fitted b/k gate，而不是 residual shape 完全不可拟合。
- range-rate correlation 在 30s 下约 0.9999，说明短窗口内两颗卫星的几何 Doppler 形状高度相似；随着窗口变长，细微曲率差异累积，margin 快速扩大。

结论：`65409 <-> 65410` 是稳定的双向 short-window ambiguity pair，但当前实验中它只在 30s weak-prior 条件下达到 verification-level ambiguity；strong-prior 下仍被 fitted b/k gate 拒绝。

## 4. 其他 Ambiguity Pairs

### 65411 -> 47749

| duration | min margin Hz | median margin Hz | weak accept | strong accept | median range-rate corr |
|---:|---:|---:|---:|---:|---:|
| 30s | 6.124 | 6.124 | 0 | 0 | -0.995889 |
| 45s | 35.146 | 49.666 | 0 | 0 | -0.989662 |
| 60s | 111.877 | 152.004 | 0 | 0 | -0.987025 |
| 120s | 943.141 | 1010.887 | 0 | 0 | -0.946911 |
| full | 11813.843 | 11813.843 | 0 | 0 | -0.408769 |

该 pair 在 30s 下 margin 很小，但没有 strong 或 weak accept。当前更像 ranking-level ambiguity，尚未形成 verification-level ambiguity。

### 48458 -> 58380

| duration | min margin Hz | median margin Hz | nonself best windows | weak accept | strong accept | median range-rate corr |
|---:|---:|---:|---:|---:|---:|
| 30s | -2.435 | -1.585 | 3 | 0 | 0 | -1.000000 |
| 45s | 15.504 | 23.599 | 0 | 0 | 0 | -0.999998 |
| 60s | 53.711 | 75.861 | 0 | 0 | 0 | -0.999990 |
| 120s | 532.819 | 597.758 | 0 | 0 | 0 | -0.999909 |
| full | 4082.447 | 4082.447 | 0 | 0 | 0 | -0.998972 |

这是本轮除 `65409 <-> 65410` 外最值得关注的 pair。30s 下 claim score 在 3 个窗口中低于 self score，说明存在 top-1 ranking-level ambiguity；但 weak-prior 和 strong-prior 均未接受，因此还不是 verification-level ambiguity。该 pair 适合后续做定向噪声/TLE 误差敏感性复测。

### 65693 -> 47749

| duration | min margin Hz | median margin Hz | weak accept | strong accept | median range-rate corr |
|---:|---:|---:|---:|---:|---:|
| 30s | 3.516 | 22.595 | 0 | 0 | 0.999950 |
| 45s | 18.780 | 76.680 | 0 | 0 | 0.999893 |
| 60s | 75.722 | 155.341 | 0 | 0 | 0.999802 |
| 120s | 545.749 | 810.959 | 0 | 0 | 0.999670 |
| full | 4605.984 | 4605.984 | 0 | 0 | 0.996182 |

该 pair 在 30s 下 margin 也很小，且 range-rate correlation 极高，但没有 non-self best 或 non-self accept。当前属于 ranking-level ambiguity。

## 5. 总体结论

本轮定向复测支持上一轮 short-window first pass 的判断：完整窗口下 Doppler residual 的身份可区分性较强；短窗口，尤其是 30s，会显著放大多普勒可混淆性。

需要区分两个层级：

- Ranking-level ambiguity：短窗口下 claim score 接近 self，甚至在少数窗口低于 self，但仍未通过验证。
- Verification-level ambiguity：短窗口下 non-self claim 被 strong-prior 或 weak-prior 接受。

在当前 controlled pool、empirical residual、单站、短窗口定向复测设置下：

- strong-prior 没有出现 non-self accept。
- weak-prior 仅在 `65409 -> 65410` 与 `65410 -> 65409` 的 30s 窗口中出现 non-self accept。
- `48458 -> 58380` 在 30s 下出现 non-self best，但未被 strong/weak 接受。
- 45s 后 weak-prior accept 消失；60s 及以上窗口 margin 继续扩大。
- full-pass 下所有 pair 的 margin 都回到 kHz 到 20 kHz 量级。

因此，本轮结果不支持继续盲目扩大同一候选池。更合适的下一步是：

1. 对 `65409 <-> 65410` 和 `48458 -> 58380` 做正式 ambiguity cluster / top-pair 定向分析，重点加入更多时间段、更多 pass 和不同站点。
2. 对短窗口 best-claim 做 TLE 误差、真实噪声和 residual 参数扰动敏感性测试，判断 weak-prior 边界是否稳定。
3. 在 verifier 策略上，把短窗口结果作为可识别性边界测试；短窗口单独判定更适合输出 DEFER，最终接受应依赖完整窗口或多窗口一致性。

本轮不能表述为“短窗口攻击已经完全突破系统”。更准确的表述是：短窗口显著放大 Doppler ambiguity，在 weak-prior 设置下暴露出局部 verification-level ambiguity；strong-prior 的 b/k sanity gate 在当前样本中阻止了这些 non-self accept，但这也说明需要继续量化 b/k gate 对安全边界的贡献。
