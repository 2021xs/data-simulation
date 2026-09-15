# Pass-Quality-Aware Attacker Summary

## 1. 实验目的

防御侧 verifier v3 已经收口：low-quality full-pass 只 DEFER，high-quality full-pass 需要 score threshold 与 per-pass k p01-p99 gate 同时通过。本轮进入攻击增强阶段，假设攻击者知道 pass quality 规则，在受约束的 same-plane altitude / phase perturbation 空间中寻找能在 medium/high-quality full-pass 上通过的攻击轨道 B。

## 2. 搜索空间

- `delta_h_km`: `[-5, -4, -3, -2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2, 3, 4, 5]`
- `phase_offset_s`: `[-120, -60, -30, -10, 0, 10, 30, 60, 120]`
- 只评估 `max_elevation_deg >= 20` 的完整 pass。
- 每个 pass 使用 legitimate calibration samples 校准 score threshold 与 per-pass k range；attack observation 仍只使用 observation/model residual terms，不把 b/k/noise 写成攻击者精确可控参数。

本轮不做 active frequency compensation、不做 multi-station、不做 multi-window，也不做全星座无约束搜索。

## 3. Single High-Quality Pass 攻击结果

- p95 score-only accepted rows = `0`
- p95 score+k accepted rows = `0`
- p95 accepted_v3_single_pass rows = `0`
- p99 accepted_v3_single_pass rows = `0`

score+k accepted 样本区域：

无 accepted 区域。

最小 normalized_score Top 10：

| target_name    | pass_id                  |   delta_h_km |   phase_offset_s |   normalized_score |       k_hat | accepted_score_only   | accepted_per_pass_k_p01_p99   |
|:---------------|:-------------------------|-------------:|-----------------:|-------------------:|------------:|:----------------------|:------------------------------|
| STARLINK-1008  | 44714_attacker_01_medium |         -1   |                0 |            1.09962 | -0.811691   | False                 | False                         |
| STARLINK-2185  | 47767_attacker_01_medium |         -0.5 |                0 |            1.11985 | -0.0970856  | False                 | False                         |
| STARLINK-2185  | 47767_attacker_01_medium |         -1   |                0 |            1.12243 | -0.500989   | False                 | False                         |
| STARLINK-1008  | 44714_attacker_01_medium |         -0.5 |                0 |            1.13778 | -0.176316   | False                 | False                         |
| STARLINK-2185  | 47767_attacker_03_medium |         -0.5 |                0 |            1.1427  | -0.578347   | False                 | False                         |
| STARLINK-2185  | 47767_attacker_01_medium |         -1   |                0 |            1.14402 | -0.701794   | False                 | False                         |
| STARLINK-1008  | 44714_attacker_01_medium |         -0.5 |                0 |            1.14731 | -0.00675594 | False                 | False                         |
| STARLINK-2185  | 47767_attacker_02_medium |         -1   |                0 |            1.14984 | -0.266959   | False                 | False                         |
| STARLINK-35060 | 65693_attacker_01_medium |         -0.5 |                0 |            1.15296 |  0.0790554  | False                 | False                         |
| STARLINK-2185  | 47767_attacker_02_medium |         -0.5 |                0 |            1.15957 | -0.246474   | False                 | False                         |

accepted 样本明细：

未发现 p95 high-quality full-pass score+k accepted attack samples。

## 4. Multi-Pass-Aware 攻击结果

p95 下：

- `any_high_quality_accept` 可通过的 candidate perturbations = `0`
- `two_high_quality_accept` 可通过的 candidate perturbations = `0`
- `all_high_quality_accept` 可通过的 candidate perturbations = `0`

这用于判断同一个扰动 B 是否能跨多个 high-quality pass 稳定通过。

## 5. 对 Verifier v3 的影响

如果 p95/p99 均没有 high-quality score+k accepted attack，说明当前 v3 规则仍成立，可以继续扩大 constrained search 或整理组会材料。如果出现 single-pass accepted 但没有 multi-pass accepted，则应考虑把推荐聚合从 `any_high_quality_accept` 提升到 `two_high_quality_accept`。如果同一 B 在多个 high-quality pass 上通过，则需要进入 multi-station consistency 或更强特征。

## 6. 下一步建议

基于本轮输出，优先按结果决定：无 accepted 则扩大受约束搜索维度；single-pass accepted 则测试更严格 full-pass aggregation；multi-pass accepted 则进入 multi-station consistency。
