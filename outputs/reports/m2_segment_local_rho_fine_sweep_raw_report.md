# Segmented Service-Center Dwell Experiment Report

## 1. 实验目标

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。本轮目标是复核上一轮 M2 是否切换过快，并新增 dwell-time-controlled `M2_block`，评估较长服务区驻留时间下的分段服务中心补偿边界。

## 2. 模型定义

统一几何频率基线为 `F_X(t;x)`，补偿仍为：

```text
u(t) = F_A(t; C(t)) - F_B(t; C(t))
```

攻击观测为：

```text
y_atk(t;S) = F_B(t;S) + u(t) + b_env + k_env*(t-t0) + epsilon(t)
```

验证 residual 为 `delta_A(t;S)=y_atk(t;S)-F_A(t;S)`，几何残差为：

```text
r_geo(t;S) = F_B(t;S) + F_A(t;C(t)) - F_B(t;C(t)) - F_A(t;S)
```

当某段中 `S=C_i` 时，`r_geo=0`；当 `S` 偏离 `C_i` 时，体现 cell 内 differential Doppler mismatch。

## 3. M0 / M1 / M2-fast / M2-block

- `M0`: fixed-C baseline，`C(t)=C0`，整段固定。
- `M1`: continuous moving-reference baseline，`C(t)=G(t)=P_sub^A(t)`，只作为极端动态对照，不称为 upper bound。
- `M2_fast`: coverage-track-driven fast segmented service-center，即上一轮 M2，按 `L_step=alpha*R_cell` 快速分段更新。
- `M2_block`: dwell-time-controlled segmented service-center，每个 `C_i=G(t_i)` 固定持续 `T_service`，更接近“多个 fixed-C 服务区块按顺序拼接”的受控模型。
- `M2_hybrid`: 可选模型，空间步长和最小驻留时间同时满足才切换；本轮默认不跑。

`M2_block` 不是真实 Starlink 调度；`T_service` 只是服务区驻留时间敏感性参数，`R_cell` 只是服务区尺度参数，二者均不声称等同真实 Starlink cell radius 或 handover period。

## 4. M2-fast 段长审计

上一轮 M2_fast 采用空间步长 `L_step=alpha R_cell` 触发服务中心更新。如果生成的 `mean_segment_duration_s` 较短，则它更接近快速离散 moving-reference，而不是多个较长 fixed-C 服务区块。

本轮 M2_fast mean_segment_duration_s 平均值：`nan` s。

M2_fast 的平均段长未明显低于 30s，但仍应与 dwell-time-controlled M2_block 分开解释。

段长审计表输出到 `outputs/metrics/m2_segment_local_rho_fine_sweep_segment_audit.csv`。

## 5. 接收点和多站约束

`heatmap_mode` 只用于单段空间热力图，可以围绕当前 `C_i` 放置接收点。`sequence_mode` 用于跨段 / window-aware / 多站实验，`S` 从 `C_ref=G(t_mid)` 生成后在整个 pass 内保持固定。多站实验对同一个 A/B/pass 先生成全局 `C(t)` 和同一个 `u(t)`，再让多个站分别接收；脚本没有为每站定制 `C_i(t)` 或 `u_i(t)`。

## 6. 本轮参数

- preset: `main`
- attack_model: `['M0', 'M2_block']`
- R_cell_km: `[50.0, 100.0, 200.0, 500.0]`
- alpha: `[1.0]`
- T_service_s: `[60.0]`
- rho: `[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.75, 1.0]`
- phi_deg: `[0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]`
- sample_group: `['ordinary_similar', 'boundary_case']`
- bk_mode: `['no_bk', 'current_bk', 'wide_bk']`
- verification_strategy: `['single-window']`
- max_targets: `1`
- max_attackers_per_group: `1`
- max_heatmap_segments: `3`

## 7. 主要结果

### 模型误接受率对比

| model_label   |   accept_flag |
|:--------------|--------------:|
| M0            |     0.0512821 |
| M2_block_60s  |     0.0435363 |

### M2_block T_service 趋势

|   T_service_s |   accept_flag |
|--------------:|--------------:|
|            60 |     0.0435363 |

### M2_block b/k 消融

| bk_mode    |   accept_flag |
|:-----------|--------------:|
| current_bk |     0.0641026 |
| no_bk      |     0         |
| wide_bk    |     0.0665064 |

### M2_block single-window vs window-aware / multi-station

| verification_strategy   |   accept_flag |
|:------------------------|--------------:|
| single-window           |     0.0435363 |

完整 summary 输出到 `outputs/metrics/m2_segment_local_rho_fine_sweep_summary_raw.csv`；heatmap input 输出到 `outputs/metrics/m2_segment_local_rho_fine_sweep_heatmap_input.csv`。

## 8. 风险点和表述边界

非目标样本误接受率只表示受控仿真下非目标样本被误判为 `ACCEPT` 的比例，不等于真实世界攻击成功率。`b_env/k_env/noise` 来自经验误差模型，不是攻击者精确可控参数。`no_bk` 表示不允许 b/k 吸收 residual，是最严格基线，不是无门限。不能写成真实 Starlink 每 30/60/120 秒切换服务区，也不能把 `T_service` 写成真实 handover 周期。

## 9. 下一步建议

1. 放大 `max_targets` 和每组 attacker 数量，复核 M2_block 在更多 pass 几何下的稳定性。
2. 对 segment boundary 附近的 `rho/phi` 做更密集扫描。
3. 将 `coverage_valid` 从 diagnostic 升级为可配置前置 gate。
4. 后续再进入主动补偿攻击下的多接收端空间一致性约束。

## 10. 生成文件

- Dataset: `outputs/datasets/m2_segment_local_rho_fine_sweep_dataset.csv`
- Summary: `outputs/metrics/m2_segment_local_rho_fine_sweep_summary_raw.csv`
- Segment audit: `outputs/metrics/m2_segment_local_rho_fine_sweep_segment_audit.csv`
- Heatmap input: `outputs/metrics/m2_segment_local_rho_fine_sweep_heatmap_input.csv`
- Report: `outputs/reports/m2_segment_local_rho_fine_sweep_raw_report.md`
- Figures: `outputs/figures/m2_segment_local_rho_fine_sweep/segment_duration_audit.png, outputs/figures/m2_segment_local_rho_fine_sweep/attack_model_dwell_comparison.png, outputs/figures/m2_segment_local_rho_fine_sweep/tservice_sensitivity.png, outputs/figures/m2_segment_local_rho_fine_sweep/rho_sensitivity_m2_block.png, outputs/figures/m2_segment_local_rho_fine_sweep/bk_ablation_m2_block.png, outputs/figures/m2_segment_local_rho_fine_sweep/window_aware_vs_single_m2_block.png`
