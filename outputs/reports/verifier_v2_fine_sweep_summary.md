# Verifier v2 Fine Sweep 边界压力测试总结

生成时间：2026-05-19 20:33:43

## 1. 实验目的

本轮不是重新设计 verifier，也不是重做 matcher，而是在更细粒度的 same-plane altitude / phase perturbation 空间中检查 verifier v2 是否稳定。重点问题是：是否存在攻击轨道 B 既能让 `score_A(B) <= threshold_A`，又能让 fitted `k_hat` 落在合法 per-target k range 内。

## 2. 实验设置

- altitude fine sweep：`[-10.0, -7.5, -5.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0]`
- phase fine sweep：`[-300.0, -120.0, -60.0, -30.0, -10.0, -5.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]` 秒
- target 数量：altitude `20`，phase `20`
- `p95` 下 altitude attack sequences：`1400`
- `p95` 下 phase attack sequences：`1200`
- 每个 target / perturbation 的样本数：由 `--num-sims-per-case` 控制，本轮完整实验为 `5`
- gate：score-only、global k gate、per-target k p01-p99、per-target k p05-p95

`b/k/noise` 仍作为 observation/model residual terms 或 effective residual terms 采样，不解释为攻击者精确可控参数。

## 3. Altitude Sweep 结果

- score-only false accepts：`56`
- score + per-target k p01-p99 后 false accepts：`17`
- 是否存在 score + per-target k gate 仍然 accepted 的攻击样本：`是`

最危险 altitude 参数按 score-only accepts 与低分排序：

| attack_param_value | total_sequences | score_only_accepts | per_target_k_p01_p99_accepts | p05_normalized_score | median_k_hat |
| --- | --- | --- | --- | --- | --- |
| -2 | 100 | 13 | 8 | 0.887234 | -1.35457 |
| -1 | 100 | 13 | 9 | 0.941862 | -0.572167 |
| -3 | 100 | 11 | 0 | 0.960756 | -2.03276 |
| 1 | 100 | 8 | 0 | 0.962767 | 0.954912 |
| 2 | 100 | 5 | 0 | 0.999856 | 1.61379 |

## 4. Phase Sweep 结果

- score-only false accepts：`0`
- score + per-target k p01-p99 后 false accepts：`0`
- 是否存在 score + per-target k gate 仍然 accepted 的攻击样本：`否`

最危险 phase 参数按 score-only accepts 与低分排序：

| attack_param_value | total_sequences | score_only_accepts | per_target_k_p01_p99_accepts | p05_normalized_score | median_k_hat |
| --- | --- | --- | --- | --- | --- |
| -5 | 100 | 0 | 0 | 28.2324 | 0.394887 |
| 5 | 100 | 0 | 0 | 28.8448 | 1.69769 |
| -10 | 100 | 0 | 0 | 56.69 | 2.10844 |
| 10 | 100 | 0 | 0 | 57.1039 | 5.13505 |
| 30 | 100 | 0 | 0 | 164.254 | 35.8048 |

## 5. Hard Cases

最危险样本摘录：

| hard_case_type | sequence_id | target | attack_type | attack_param | normalized_score | k_hat | accepted_score_only | accepted_per_target_k_p01_p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lowest_normalized_score_top30 | alt_fine_001147 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.760415 | -0.560637 | True | True |
| lowest_normalized_score_top30 | alt_fine_001151 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=-1.0 | 0.824351 | -0.62036 | True | True |
| lowest_normalized_score_top30 | alt_fine_001144 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=-3.0 | 0.834014 | -1.64723 | True | False |
| lowest_normalized_score_top30 | alt_fine_001360 | STARLINK-2698 / 48458 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.836747 | -0.594991 | True | True |
| lowest_normalized_score_top30 | alt_fine_001358 | STARLINK-2698 / 48458 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.843955 | -0.539636 | True | True |
| lowest_normalized_score_top30 | alt_fine_001148 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.858206 | -1.20598 | True | False |
| lowest_normalized_score_top30 | alt_fine_001157 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=1.0 | 0.863211 | 1.38235 | True | False |
| lowest_normalized_score_top30 | alt_fine_001160 | STARLINK-35060 / 65693 | same_plane_altitude_offset_fine | delta_h_km=1.0 | 0.868444 | 1.37581 | True | False |
| lowest_normalized_score_top30 | alt_fine_000866 | STARLINK-2185 / 47767 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.884547 | -0.66015 | True | True |
| lowest_normalized_score_top30 | alt_fine_001356 | STARLINK-2698 / 48458 | same_plane_altitude_offset_fine | delta_h_km=-2.0 | 0.887375 | -0.930742 | True | True |

这些 hard cases 的危险性主要来自 normalized_score 接近或低于 1；但如果 `k_hat` 落在 per-target 合法范围外，verifier v2 的 fitted-parameter sanity gate 会把它们从 score-only accept 中剔除。

## 6. 阶段性结论

1. verifier v2 比 score-only 更稳：fine sweep 中 altitude score-only false accepts 为 `56`，per-target k p01-p99 gate 后降为 `17`。
2. 当前最危险区域集中在更小幅的 negative altitude offset，尤其是 `delta_h=-2 km` 与 `delta_h=-1 km`；上一轮的 `delta_h=-5 km` 在细扫中仍有 score-only accept，但会被 per-target k gate 过滤。
3. 本轮发现了 score + per-target k p01-p99 仍然 accepted 的 altitude hard cases，说明 k_hat sanity gate 不是充分条件，后续需要 random sub-window / multi-pass 继续收紧边界。
4. phase offset 在当前 sweep 尺度下仍远离可接受区，score-only 与 k gate 后 false accepts 均为 `0`。
5. 下一步建议进入 random sub-window / multi-pass，再考虑 multi-station；本轮暂不需要 active frequency compensation。

## 7. 生成文件

- `outputs/figures/verifier_v2_fine_sweep/altitude_sweep_false_accepts_by_delta_h.png`
- `outputs/figures/verifier_v2_fine_sweep/altitude_sweep_normalized_score_by_delta_h.png`
- `outputs/figures/verifier_v2_fine_sweep/altitude_sweep_k_hat_by_delta_h.png`
- `outputs/figures/verifier_v2_fine_sweep/phase_sweep_false_accepts_by_offset.png`
- `outputs/figures/verifier_v2_fine_sweep/phase_sweep_normalized_score_by_offset.png`
- `outputs/figures/verifier_v2_fine_sweep/fine_sweep_hard_cases_scatter.png`
- `outputs/reports/verifier_v2_fine_sweep_summary.md`

## 8. 运行命令

```bash
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 2 --num-sims-per-case 2 --overwrite
python scripts/analyze_verifier_v2_fine_sweep.py --overwrite
python scripts/plot_verifier_v2_fine_sweep.py --overwrite
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 20 --num-sims-per-case 5 --overwrite
python scripts/analyze_verifier_v2_fine_sweep.py --overwrite
python scripts/plot_verifier_v2_fine_sweep.py --overwrite
```
