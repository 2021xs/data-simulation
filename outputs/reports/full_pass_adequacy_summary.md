# Full-Pass Multi-Pass Adequacy Summary

## 1. 实验目的

本轮先评估多个完整过境窗口 full-pass 是否已经足够支撑认证增强，不做 multi-window，不做 multi-station，也不做 active frequency compensation。

## 2. Full-Pass 分层结果

p95 下 low elevation attack 的 per-pass k gate accept rate 为 `0.3125`，high elevation attack 为 `0.0000`。这说明 low elevation pass 是当前 hard-case 接受风险的主要来源。

p95 下 legit 的 per-pass k gate accept rate：low elevation 为 `0.8750`，high elevation 为 `0.8583`。合法样本在不同 elevation 下也会有差异，因此 max elevation 更适合作为 pass quality / defer 指标，而不是直接判假指标。

当前数据没有 medium elevation pass，因此 medium bin 不能下结论。

## 3. 三态判决结果

低质量 pass 更适合 `DEFER`，而不是直接 `ACCEPT` 或 `REJECT`。低仰角 pass 中攻击和合法样本都可能通过 score/k；直接 reject 会伤害合法样本，直接 accept 会保留 hard-case 风险。

## 4. Multi-Pass Full-Window 聚合结果

以 `elevation_min_deg = 20`、p95 为例：

- `single_pass_v2_baseline` attack final accept rate = `0.3125`
- `defer_if_only_low_quality` attack final accept rate = `0.0000`
- `two_high_quality_accept` attack final accept rate = `0.0000`
- `any_high_quality_accept` legit final accept rate = `1.0000`
- `two_high_quality_accept` legit final accept rate = `0.9250`，attack defer rate = `0.3125`

`defer_if_only_low_quality` 能把只来自低质量 pass 的 accept 从最终接受中移出；`two_high_quality_accept` 更保守，但会增加 defer / reject 压力。当前最平衡的主线规则是：低质量 pass 不最终 accept，至少等待 high-quality full pass；是否要求两个 high-quality pass 需要结合可用 pass 数量和合法接受率进一步扩样。

## 5. 是否需要 Multi-Window 辅助

当前 high-quality full-pass 已基本能拒绝 hard cases，multi-pass full-window aggregation 表现比单 pass 更有解释力。因此暂不需要把 multi-window 作为主防线；它可以保留为 residual 局部结构 forensic 的附录诊断。

## 6. 推荐下一步

1. 继续扩大 full-pass multi-pass 样本，补充 medium elevation pass。
2. 做 pass-quality-aware threshold calibration。
3. 进入组会材料整理，明确 low elevation defer 策略的边界。
4. multi-window 仅作为 forensic 辅助。
5. multi-station consistency 放在后续更强验证层。
