# Verifier v2 最小实验闭环总结

生成时间：2026-05-19 18:00:12

## 1. Baseline 复现结果

- 合法序列数：`1000`
- 攻击序列数：`2000`
- `p95` score-only false accepts：`3`
- false accepts 来源：
- `same_plane_altitude_offset / delta_h_-5km`: 3

本轮使用上一阶段 score-only verifier 输出作为输入，没有重做 matcher，也没有重生成攻击样本。`b_hat/k_hat` 是 claimed target A 条件下对 observation/model residual terms 的线性拟合参数，不是攻击者精确可控参数。

## 2. Fitted-Parameter Gate 结果

- `score_plus_global_k_gate` 后 false accepts：`0`，legit accept rate：`0.9290`
- `score_plus_per_target_k_quantile_gate(p01-p99)` 后 false accepts：`0`，legit accept rate：`0.9400`
- 当前最有效 gate：`score_plus_global_k_gate`，attack false accept rate：`0.000000`
- 相对 score-only 的 legit accept rate 损失：`0.0110`

上一轮 3 个 score-only false accepts 的 `k_hat` 明显低于 main_range 的全局 k 范围，因此 global k gate 能直接拒绝它们；per-target k quantile gate 也能拒绝它们。

## 3. Visibility / Timing Diagnostic

- 高度偏移攻击 mean visible fraction 均值：`1.0000`
- 相位偏移攻击 mean visible fraction 均值：`1.0000`
- 当前 visibility 仅作为诊断输出，visible mask 来自项目 time_window 的 elevation mask；没有作为强 gate 参与验收。

这些结果支持后续把 visibility/timing 变成 verifier 的前置诊断或 defer 条件，但建议先做 multi-pass / multi-station 后再定硬阈值，避免把受控合成轨道的可见性特征过拟合成规则。

## 4. 组会可用结论

1. score-only verifier 在本轮 2000 条 controlled attack sequence 中只有 3 条 false accepts，但这 3 条暴露了 b+k 拟合项会吸收异常慢变趋势的边界。
2. fitted `k_hat` sanity gate 合理，因为合法样本的 effective residual drift 来自 SatNOGS/STRF main_range，而 3 条 false accepts 的 `k_hat` 约为 -3.22 到 -3.32 Hz/s，明显越界。
3. verifier v2 相比上一阶段新增了 score 后的 fitted-parameter 消融表、false accept 明细和 visibility/timing 诊断，不改变原 score-only baseline。
4. visibility diagnostic 显示不同 attack_type / attack_param 的可见窗口结构可被量化，后续值得纳入 multi-pass / multi-station 验证。
5. 当前结论仍是 controlled baseline，不是真实 Starlink SatNOGS replay，也不代表真实 Ku-band residual 分布。

## 5. 生成文件列表

- `outputs/figures/verifier_v2/score_distribution_legit_vs_attack.png`
- `outputs/figures/verifier_v2/k_hat_distribution_with_false_accepts.png`
- `outputs/figures/verifier_v2/gate_ablation_bar.png`
- `outputs/figures/verifier_v2/visibility_by_attack_type.png`
- `outputs/reports/verifier_v2_summary.md`

## 6. 运行命令

```bash
python scripts/evaluate_verifier_v2_gates.py --overwrite
python scripts/diagnose_attack_visibility_timing.py --overwrite
python scripts/plot_verifier_v2_results.py --overwrite
```
