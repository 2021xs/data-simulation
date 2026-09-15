# 阶段收尾简报

## 1. 当前阶段做了什么

本阶段围绕 LEO / Starlink 多普勒残差 claimed-identity verification，已经完成以下受控仿真实验与诊断：

- fixed-C 主动补偿；
- b/k 消融；
- 多站一致性；
- service-area-first segmented service-center compensation；
- M2_fast 段长审计；
- M2_block_30s / 60s / 120s 驻留时间实验。

本文继续将服务区分段补偿表述为 controlled segmented service-center compensation simulation，不是 Starlink 真实 beam scheduling / service cell binding / handover policy / 无线资源调度复现。

## 2. 服务区分段模型结论

M2_fast 的段长审计表明，部分小 `R_cell / alpha` 设置下切换过快，更接近快速离散 moving-reference。例如上一轮 scaled main 中，M2_fast 平均段长约 22.478 s，`R_cell=50 km, alpha=0.5` 时平均约 4.000 s。

因此补充了 M2_block，让每个服务区中心驻留 30s / 60s / 120s。当前 scaled main 中，M2_fast 和 M2_block_30s / 60s / 120s 均未观察到非目标样本误接受。wide_bk 也没有放大出 M2_block 风险。因此，服务区中心分段变化本身没有自然扩大 fixed-C 的主动补偿风险。

M0 fixed-C 的 ACCEPT 来源审计显示：共有 `640` 条 M0 ACCEPT；按 receiver_mode 为 `heatmap_mode=320, sequence_mode=320`；按 verification_strategy 为 `single-window=384, window-aware accumulation=256`；按 sample_group 为 `boundary_case=384, ordinary_similar=256`；按 bk_mode 为 `wide_bk=384, current_bk=256`。`no_bk` 下 M0 ACCEPT 数为 `0`，`coverage_valid=false` 的 M0 ACCEPT 数为 `0`。详细审计见 `outputs/metrics/stage_wrapup_m0_accept_audit.csv`。

## 3. 当前阶段总判断

当前实验链说明，单站 Doppler residual verifier 在完整窗口和普通样本下较稳健；短窗口不能单独 ACCEPT，需要 window-aware accumulation。fixed-C 主动补偿会暴露单站边界，但风险主要集中在边界样本、小参考点误差和较宽 b/k 吸收条件下。b/k 消融表明 b/k 是单站验证器的重要安全边界。多站一致性和 b/k 风险暂缓可以显著降低误接受。

针对服务区域变化假设，service-area-first segmented service-center compensation 在当前受控缩放实验中未观察到额外误接受，说明服务区中心分段变化本身不会自然扩大 fixed-C 风险。后续不建议继续构造更复杂的不可验证 Starlink 调度假设，而应先整理阶段报告，并和导师讨论是否转向验证器策略收敛或真实 residual 噪声校准。

## 4. 局限性

- service-area segmented experiments 是 scaled main，不是全量大规模 sweep；
- 不是真实 Starlink 调度复现；
- `R_cell`、`alpha`、`T_service` 都是受控敏感性参数；
- 真实 beam boundary、service cell binding、handover policy 不公开；
- 当前误接受率是受控仿真中的非目标样本误接受率，不是真实世界攻击成功率。

## 5. 和导师讨论的问题

1. 服务区分段补偿这条线是否作为补充实验阶段收尾？
2. 是否需要扩大 `max_targets` / attacker 数量做确认版实验？
3. 后续是否转向验证器策略收敛，例如 DEFER policy、b/k gate、多站一致性和真实 residual 噪声校准？
