# Verifier v2 Hard Case Temporal Summary

## 1. 实验目的

fine sweep 发现 `delta_h=-1/-2 km` hard cases 后，本轮检验这些 hard cases 是否具有跨 pass / 跨窗口稳定性。这里没有做 multi-station，也没有做 active frequency compensation。

## 2. Hard Case Forensic 结果

selected hard cases 数量：`17`。这些样本的共同特征是完整 pass 下 `f_geo_B(t)` 与 claimed `f_geo_A(t)` 的差异可被 b+k profile 较强吸收，残差 RMSE 低于阈值；部分样本的 k_hat 并不是贴边通过，而是落在 per-target k range 内部。

| sequence_id | target | delta_h_km | normalized_score | k_hat | residual_std | residual_max_abs |
| --- | --- | --- | --- | --- | --- | --- |
| alt_fine_001147 | STARLINK-35060 / 65693 | -2.0 | 0.7604 | -0.5606 | 25.420 | 100.989 |
| alt_fine_001151 | STARLINK-35060 / 65693 | -1.0 | 0.8244 | -0.6204 | 27.557 | 78.864 |
| alt_fine_001360 | STARLINK-2698 / 48458 | -2.0 | 0.8367 | -0.5950 | 26.788 | 70.823 |
| alt_fine_001358 | STARLINK-2698 / 48458 | -2.0 | 0.8440 | -0.5396 | 27.019 | 78.601 |
| alt_fine_000866 | STARLINK-2185 / 47767 | -2.0 | 0.8845 | -0.6601 | 29.527 | 95.051 |

## 3. Multi-Pass 结果

hard-case target / delta_h 在多 pass retest 下，平均 score-only accept rate = `0.1313`，per-pass k gate accept rate = `0.0781`。per-pass k gate 重新用每个 pass 的合法样本校准，因此比上一轮固定 per-target k range 更贴合 pass geometry。

## 4. Multi-Window 结果

多子窗口聚合结果如下。短窗口本身可能更弱，所以这里比较的是多窗口一致性聚合，而不是单个 random short window。

| aggregation_rule | legit_accept_rate | attack_accept_rate |
| --- | --- | --- |
| all_windows_accept | 0.5167 | 0.3111 |
| majority_windows_accept | 0.9125 | 0.8875 |
| max_normalized_score_accept | 0.5167 | 0.3111 |
| mean_normalized_score_accept | 0.9083 | 0.8875 |

## 5. 阶段性结论

1. `score + k` gate 的边界集中在小幅 altitude offset 且几何曲线天然接近的区域。
2. hard cases 不是单纯 k_hat 贴边问题；部分样本 residual 低且 k_hat 位于合法区间内部。
3. 时间多样性有帮助，尤其是 multi-pass 和多窗口一致性可以暴露单 pass 低 score 的不稳定性。
4. 下一步优先做 multi-pass verifier / random challenge window；multi-station consistency 更适合作为后续更强验证层。
