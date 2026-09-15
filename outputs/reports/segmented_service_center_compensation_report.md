# Service-Area-First Segmented Service-Center Compensation Report

## 1. 实验目标

本文实现的是 controlled segmented service-center compensation simulation，不是真实 Starlink 调度复现。实验在真实 Starlink TLE、controlled pass 时间网格和受控服务区域变化假设下，重新计算 `F_A(t;S)`、`F_B(t;S)`、`F_A(t;C)`、`F_B(t;C)`，评估攻击方只能按服务区中心做 Doppler pre-compensation 时，Doppler residual verifier、window-aware accumulation、b/k gate 和多站一致性的边界。

## 2. 模型定义

几何频率基线记为 `F_X(t;x)`。攻击补偿统一写为：

```text
u(t) = F_A(t; C(t)) - F_B(t; C(t))
```

真实接收点 `S` 处的攻击观测为：

```text
y_atk(t;S) = F_B(t;S) + u(t) + b_env + k_env*(t-t0) + epsilon(t)
```

验证器对 claimed target A 计算 `delta_A(t;S)=y_atk(t;S)-F_A(t;S)`。几何残差部分为：

```text
r_geo(t;S) = F_B(t;S) + F_A(t;C_i) - F_B(t;C_i) - F_A(t;S)
```

当 `S=C_i` 时，`r_geo=0`，说明服务区中心附近最危险；当 `S` 远离 `C_i` 时，剩下的是 cell 内 differential Doppler mismatch。

## 3. M0 / M1 / M2 区别

- `M0`: fixed-C baseline，默认 `C0=G(t_mid)`，且独立于 `S`。
- `M1`: continuous moving-reference baseline，`C(t)=G(t)=P_sub^A(t)`，只作为极端动态参考点对照。
- `M2`: service-area-first segmented service-center model，先用 `G(t)` 和 `L_step=alpha*R_cell` 生成 `C_i/I_i`，再在服务区中放置或扫描接收点。

## 4. heatmap_mode 和 sequence_mode

- `heatmap_mode`: 单段空间热力图。对服务区中心按 `rho/phi` 扫描接收点，用于观察同一服务区内位置对误接受的影响。
- `sequence_mode`: 跨段、window-aware、多站实验。`S` 由 `C_ref=G(t_mid)` 生成后，在整个 pass 内保持固定。

## 5. 跨段 S 固定规则

`sequence_mode` 中不会每段重新放置接收机。每段只计算固定 `S` 到当前 `C_i` 的地表大圆距离，并据此标记 `coverage_valid`；覆盖无效时该窗口或序列输出 `DEFER`。

## 6. 多站共用同一个 C_i(t) 和 u(t)

多站策略先为同一个 A/B/pass 生成全局 `C_i(t)` 和同一个 `u(t)`，然后 S0/S1/S2 分别接收并各自计算 residual。脚本没有为每个站生成不同的 `C_i` 或 `u_i(t)`。

## 7. smoke / main 参数

- 本次运行 preset: `main`。
- `R_cell_km`: `[50.0, 100.0, 200.0, 500.0]`。
- `alpha`: `[0.5, 1.0]`。
- `rho`: `[0.0, 0.25, 0.5, 0.75, 1.0]`。
- `phi_deg`: `[0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]`。
- `sample_group`: `['random_simulated', 'ordinary_similar', 'boundary_case']`。
- `bk_mode`: `['no_bk', 'strict_bk', 'current_bk', 'wide_bk', 'bk_risk_defer']`。
- `verification_strategy`: `['single-window', 'window-aware accumulation', 'multi-station all-accept', 'multi-station + bk-risk-defer']`。
- `max_targets`: `1`，`max_attackers_per_group`: `1`。

## 8. 主要结果表

### 三模型总体对比

| attack_model   |   accept_flag |
|:---------------|--------------:|
| M0             |     0.0222222 |
| M1             |     0         |
| M2             |     0         |

### M2 b/k 消融

| bk_mode       |   accept_flag |
|:--------------|--------------:|
| bk_risk_defer |             0 |
| current_bk    |             0 |
| no_bk         |             0 |
| strict_bk     |             0 |
| wide_bk       |             0 |

完整汇总表见 `outputs/metrics/segmented_service_center_main_summary.csv`，热力图输入表见 `outputs/metrics/segmented_service_center_heatmap_input.csv`。

## 9. 风险点和表述边界

本文构造的是受控的服务区域变化假设。`G(t)=P_sub^A(t)` 只是 coverage-center trajectory 的简化生成规则，不表示真实 Starlink beam center 或真实服务区中心必然等于星下点。`M1` 是极端动态参考点对照，不是真实调度模型。非目标样本误接受率只表示受控仿真下非目标样本被误判为 `ACCEPT` 的比例，不等于真实世界攻击成功率。`b_env/k_env/noise` 来自经验误差模型，不是攻击者精确可控参数。`no_bk` 表示不允许 b/k 吸收 residual，是最严格基线，不是无门限。

## 10. 下一步建议

1. 放大 `max_targets` 和每组 attacker 数量，检查不同 pass 几何下的稳定性。
2. 对 M2 的 segment boundary 附近增加更细的 `rho/phi` 和时间窗口扫描。
3. 将本轮 `coverage_valid` diagnostic 升级为可配置前置 gate。
4. 后续再引入主动补偿攻击下的多接收端空间一致性约束。

## 11. 生成文件

- Dataset: `outputs/datasets/segmented_service_center_compensation_dataset.csv`
- Summary: `outputs/metrics/segmented_service_center_main_summary.csv`
- Heatmap input: `outputs/metrics/segmented_service_center_heatmap_input.csv`
- Report: `outputs/reports/segmented_service_center_compensation_report.md`
- Figures: `outputs/figures/segmented_service_center/attack_model_comparison.png, outputs/figures/segmented_service_center/rho_sensitivity.png, outputs/figures/segmented_service_center/rcell_alpha_sensitivity.png, outputs/figures/segmented_service_center/bk_ablation_segmented_service_center.png, outputs/figures/segmented_service_center/heatmap_accept_rate.png`
