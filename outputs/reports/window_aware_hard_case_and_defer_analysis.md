# Window-aware hard case and DEFER analysis

生成时间：2026-06-12 09:47:09

## 1. 本轮分析目的

本轮只做离线诊断，读取上一轮 `window_aware_evidence_accumulation_dataset.csv`，不重跑轨道仿真。目标是解释 proposed_accumulation 下剩余 attack ACCEPT hard cases 与 benign DEFER / REJECT 的来源，并用规则重放评估小范围微调的代价。

## 2. 上一轮 proposed verifier 关键结果

本次读取 `p95` / `proposed_accumulation` 行：attack group rows `25540`，benign group rows `22000`。proposed_v1 复现的 attack ACCEPT rate 为 `0.0073`，benign ACCEPT rate 为 `0.4146`。

## 3. Attack ACCEPT hard cases 分布

hard case 数量：`186`，占 attack group rows `0.0073`。

按 attack_type：

| attack_type | n |
| --- | --- |
| same_plane_altitude_offset | 141 |
| inclination_offset | 45 |

按参数：

| attack_type | attack_param_value | n |
| --- | --- | --- |
| same_plane_altitude_offset | -1.0 | 88 |
| same_plane_altitude_offset | -2.0 | 53 |
| inclination_offset | 0.05 | 16 |
| inclination_offset | -0.1 | 8 |
| inclination_offset | 0.1 | 8 |
| inclination_offset | 0.2 | 6 |
| inclination_offset | -0.2 | 4 |
| inclination_offset | -0.05 | 3 |

按 segment pattern：

| group_mode | n |
| --- | --- |
| best_attack_segments | 75 |
| middle_segments | 49 |
| spread_segments | 31 |
| middle | 21 |
| full_pass | 10 |

## 4. altitude / inclination / phase 对比

hard cases 主要集中在 altitude 与 inclination；phase 在本轮 proposed ACCEPT hard cases 中基本保持为 0 或极低。altitude 的小高度差，尤其 `-1/-2/+1/+2 km` 一类，应继续作为规则化轨道相似攻击压力源；inclination 则是 orbit-plane 小扰动压力源。

## 5. hard cases 是否接近边界

hard cases 的 median evidence score、joint normalized score 与 k loose-bound ratio 可见于 hard case summary。若 `k_loose_bound_ratio` 接近 `0.8~1.0`，说明 candidate C 这类 near-boundary DEFER 规则有诊断价值；若 joint score 明显小于 1，则 hard case 更多来自轨道几何确实局部相似，而不只是阈值边界抖动。

## 6. benign DEFER 原因拆解

| reason | n | ratio | median_evidence_score | median_joint_normalized_score | median_k_abs |
| --- | --- | --- | --- | --- | --- |
| evidence_score_insufficient | 11762 | 0.9585 | 2.0000 | 0.8400 | 0.6554 |
| temporal_diversity_failed | 373 | 0.0304 | 4.0000 | 0.8439 | 0.6007 |
| joint_score_failed | 83 | 0.0068 | 3.0000 | 1.0112 | 0.6576 |
| joint_b_gate_failed | 53 | 0.0043 | 3.0000 | 0.7955 | 0.4429 |

DEFER 不是失败判决。若主因是 evidence_score_insufficient 或 short_windows_only，说明需要更多窗口或多 pass 累计；若主因是 joint_score_failed / joint_k_gate_failed，则说明当前规则在合法样本上偏保守。

## 7. benign REJECT 原因检查

| reason | n | ratio | median_evidence_score | median_joint_normalized_score | median_k_loose_bound_ratio |
| --- | --- | --- | --- | --- | --- |
| joint_score_failed | 296 | 0.4876 | 1.0000 | 1.0502 | 0.3311 |
| joint_or_window_k_extreme | 241 | 0.3970 | 2.0000 | 0.8953 | 0.9979 |
| full_or_180_failed | 70 | 0.1153 | 0.0000 | 0.8771 | 0.6099 |

benign REJECT 需要重点关注是否由 joint score 或 k extreme 主导。如果集中在少数 target/pass，应优先做 target/pass 级质量诊断，而不是直接放宽全局规则。

## 8. 规则微调敏感性

| rule_variant | benign_accept_rate | benign_defer_rate | benign_reject_rate | attack_accept_rate | attack_defer_rate | attack_reject_rate | delta_benign_accept_vs_v1 | delta_attack_accept_vs_v1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| proposed_v1 | 0.4146 | 0.5578 | 0.0276 | 0.0073 | 0.0579 | 0.9348 | 0.0000 | 0.0000 |
| candidate_A_evidence_2p5_relax | 0.1393 | 0.8331 | 0.0276 | 0.0010 | 0.0642 | 0.9348 | -0.2754 | -0.0063 |
| candidate_B_strict_best_attack_diversity | 0.4146 | 0.5578 | 0.0276 | 0.0046 | 0.0605 | 0.9348 | 0.0000 | -0.0027 |
| candidate_C_k_near_boundary_defer | 0.3780 | 0.5944 | 0.0276 | 0.0060 | 0.0591 | 0.9348 | -0.0366 | -0.0013 |
| candidate_D_altitude_diagnostic_only | 0.4146 | 0.5578 | 0.0276 | 0.0073 | 0.0579 | 0.9348 | 0.0000 | 0.0000 |

当前按 attack accept 优先、benign accept 次优排序的候选为 `candidate_A_evidence_2p5_relax`。这只是离线规则重放，不是最终规则。

## 9. 是否建议修改 proposed verifier v1

若 candidate A 明显提高 benign ACCEPT 但也明显提高 attack ACCEPT，则不建议采用。若 candidate B 或 C 能降低 hard-case ACCEPT 且只把样本转为 DEFER，可作为 v1.1 候选。任何 v1.1 都应先在更多 pass / station 设置下复核。

## 10. 下一步

本轮没有进入主动频率补偿结论。建议下一轮可以进入 partial-observation 下的 location-aware active compensation 压力测试，但应保留本轮 hard cases 与 DEFER 分类作为输入，优先测试 altitude / inclination 小扰动和 best_attack_segments。

## 11. 最终问题回答

1. 剩余 attack ACCEPT 主要来自哪些攻击类型和参数：见第 3、4 节，主要看 altitude / inclination，小扰动参数是重点。
2. 是否集中在 best_attack_segments：见第 3 节 group_mode 分布；best_attack 是重要来源但需要和 middle/spread 对比。
3. 是否只是 joint score / k 接近边界：见第 5 节；near-boundary 只是部分解释，不能把所有 hard case 归因于阈值抖动。
4. benign DEFER 主因：见第 6 节 primary_reason。
5. benign REJECT 是否说明规则过严：见第 7 节；若集中于 joint score/k extreme，说明需要质量诊断而非简单放宽。
6. 是否有低风险微调：见第 8 节；优先考虑把可疑 attack ACCEPT 转 DEFER 的规则，不优先追求直接提高 ACCEPT。
7. 是否保持 v1：当前建议默认保持 proposed v1，把 candidate B/C 作为 v1.1 候选继续验证。
8. 下一轮是否进入 location-aware active compensation：可以进入压力测试，但本轮结果不是主动补偿结论。

## 12. 生成图

- `outputs/figures/attack_accept_hard_cases_by_type.png`
- `outputs/figures/attack_accept_hard_cases_by_param.png`
- `outputs/figures/attack_accept_hard_cases_by_segment_pattern.png`
- `outputs/figures/benign_defer_reason_breakdown.png`
- `outputs/figures/rule_sensitivity_tradeoff.png`
- `outputs/figures/joint_k_near_boundary_distribution.png`
