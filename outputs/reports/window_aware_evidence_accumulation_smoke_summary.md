# Window-aware evidence accumulation verifier summary

生成时间：2026-06-11 22:36:03

## 1. 实验目的

本轮实现并验证“窗口感知的三态累计验证器”：`ACCEPT / REJECT / DEFER`。目标是检验短窗口不单独 ACCEPT、而是作为时间分散的累计证据时，能否降低规则化轨道相似攻击的误接受，同时尽量把不确定样本转为 DEFER 而不是误 REJECT。

本轮仍然不评价主动频率补偿攻击，也不把结果写成真实世界安全边界。

## 2. 上一轮 calibration 发现

上一轮 window reliability calibration 显示：full-pass 平均 attack accept rate 约 `0.0083`，30s/60s 短窗口约 `0.0498`；best_attack window 明显比 middle window 更危险；30s/60s 对 b/k gate 的依赖更强。因此短窗口不应单独触发最终 ACCEPT。

## 3. 新验证器规则

- `full_pass` 和 `180s` 正常通过可直接 ACCEPT。
- `120s` 正常通过计 `2` 分，边界通过计 `1` 分。
- `60s` 正常通过计 `1` 分，边界通过计 `0.5` 分。
- `30s` 正常通过计 `0.5` 分，边界通过计 `0.25` 分。
- 累计分数达到 `3` 后，还必须通过时间分散、joint score、joint b/k gate，且没有 extreme anomaly。
- 证据不足但无明显异常时输出 DEFER；明显异常时输出 REJECT。

## 4. b/k 设置方式

每个 target / window length 的 b/k 范围只由 benign_A 校准。使用 `median` 作为中心，用 `abs(value - center)` 的 p99 作为正常范围。短窗口按长度放宽：120s 为 1.2 倍，60s 为 1.5 倍，30s 的 b 为 2.0 倍、k 为 1.5 倍。k 是主要可疑指标。

## 5. 时间分散和 joint fitting

多窗口要求任意窗口 overlap ratio 小于 `0.2`，且中心间隔满足最小 gap。joint fitting 把同一次 pass 内多个窗口的采样点合并，统一拟合一组 `b_pass + k_pass(t-t0)`，用于检查多个片段能否由同一个整体频率平移和线性慢漂移解释。不同 pass 不共享 b/k，因为 effective residual 可能随过境、接收环境和时间变化。

## 6. 实验矩阵

- target 数：`2`
- benign sequence 数：`100`
- attack sequence 数：`80`
- group 行数：`28476`
- segment patterns：`middle_segments, spread_segments, best_attack_segments`
- strategies：`single_window, naive_accumulation, proposed_accumulation`
- skip group 数：`28`

## 7. 策略对比

| strategy_type | benign_accept_rate | benign_defer_rate | benign_reject_rate | attack_accept_rate | attack_defer_rate | attack_reject_rate |
| --- | --- | --- | --- | --- | --- | --- |
| naive_accumulation | 0.4027 | 0.5855 | 0.0118 | 0.0141 | 0.1203 | 0.8656 |
| proposed_accumulation | 0.3905 | 0.5832 | 0.0264 | 0.0094 | 0.0664 | 0.9242 |
| single_window | 0.9723 | 0.0223 | 0.0055 | 0.2094 | 0.1551 | 0.6355 |

## 8. benign 三态结果

在 `p95 + proposed_accumulation` 下，benign ACCEPT 约 `0.3905`，DEFER 约 `0.5832`。DEFER 是本轮设计中可接受的不确定输出，后续可由更多窗口或多 pass 累计继续处理。

## 9. attack 三态结果

`p95` 平均 attack accept rate：single-window `0.2094`，naive accumulation `0.0141`，proposed accumulation `0.0094`。如果 proposed 低于 naive，说明 joint b/k fitting 与异常门限对累计攻击样本有过滤作用。

## 10. 三类攻击对比

| attack_type | attack_accept_rate | attack_defer_rate | attack_reject_rate |
| --- | --- | --- | --- |
| same_plane_altitude_offset | 0.0205 | 0.1240 | 0.8555 |
| inclination_offset | 0.0039 | 0.0560 | 0.9401 |
| same_plane_phase_offset | 0.0000 | 0.0000 | 1.0000 |

当前 proposed accumulation 下最危险的攻击类型是：`same_plane_altitude_offset`。

## 11. middle / spread / best_attack segments 对比

| group_mode | attack_accept_rate | attack_defer_rate | attack_reject_rate |
| --- | --- | --- | --- |
| best_attack_segments | 0.0063 | 0.0887 | 0.9050 |
| full_pass | 0.0375 | 0.0000 | 0.9625 |
| middle | 0.0500 | 0.0000 | 0.9500 |
| middle_segments | 0.0112 | 0.0525 | 0.9363 |
| spread_segments | 0.0037 | 0.0712 | 0.9250 |

best_attack_segments 是 diagnostic worst-case，不代表攻击源进行主动频率补偿或利用随机噪声挑窗口。

## 12. 阶段性回答

1. 新的 window-aware accumulation verifier 是否降低短窗口 attack accept rate：见第 7 节，proposed 相对 single-window / naive 的 attack accept rate 变化用于回答该问题。
2. 是否主要把短窗口样本从 ACCEPT 转为 DEFER，而不是误 REJECT：见 benign 和 attack 的 DEFER / REJECT 比例。
3. 多个分散短窗口是否比单个 best_attack window 更可靠：见第 11 节，spread_segments 与 best_attack_segments 的 attack accept rate 对比。
4. joint b/k fitting 是否降低攻击接受率：见 naive accumulation 与 proposed accumulation 的差异。
5. benign_A 可用性：见第 8 节，当前 ACCEPT 与 DEFER 比例是可用性指标。
6. altitude / inclination / phase 哪类仍最危险：当前为 `same_plane_altitude_offset`。
7. 下一轮是否进入 partial-observation 下的 location-aware active compensation：建议先基于本轮 proposed 的 DEFER 样本和 best_attack_segments hard cases 做规则收紧；随后可以进入 partial-observation 下的 location-aware active compensation，但仍应明确它是下一轮压力测试，不属于本轮结果。

## 13. 生成文件

- `outputs/datasets/window_aware_evidence_accumulation_smoke_dataset.csv`
- `outputs/metrics/window_aware_evidence_accumulation_smoke_summary.csv`
- `outputs/metrics/window_aware_strategy_smoke_comparison.csv`
- `outputs/reports/window_aware_evidence_accumulation_smoke_summary.md`
- `outputs/figures/window_aware_smoke/strategy_attack_accept_rate_comparison.png`
- `outputs/figures/window_aware_smoke/strategy_benign_accept_defer_comparison.png`
- `outputs/figures/window_aware_smoke/accumulation_by_segment_pattern.png`
- `outputs/figures/window_aware_smoke/attack_type_under_accumulation.png`
- `outputs/figures/window_aware_smoke/evidence_score_distribution.png`
- `outputs/figures/window_aware_smoke/joint_bk_gate_effect.png`
