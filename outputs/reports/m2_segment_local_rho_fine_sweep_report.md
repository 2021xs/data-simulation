# M2 Segment-Local Rho Fine Sweep Report

本轮在已经修正并验证的 segment-local heatmap 模型上做服务区内部位置细分扫描。实验仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。

## 1. 实际运行参数

- `receiver_mode = heatmap_mode`
- `evaluation_scope = segment_local`
- `doppler_reference_mode = fixed_site_segment_center`
- `verification_strategy = single-window`
- `attack_model = M0, M2_block`
- `T_service_s = 60`
- `R_cell_km = 50, 100, 200, 500`
- `rho = 0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.75, 1.00`
- `phi_deg = 0, 45, 90, 135, 180, 225, 270, 315`
- `sample_group = ordinary_similar, boundary_case`
- `bk_mode = no_bk, current_bk, wide_bk`
- scaled run: `max_targets=1`, `max_attackers_per_group=1`, `max_heatmap_segments=3`

本轮选择可控缩放版，优先保证 rho / R_cell / phi / b-k 网格完整，而不是扩大 target 和 attacker 数量。

## 2. 正确性审计

主扫描 dataset 共 `9984` 行。

- `evaluation_scope` 全部为 `segment_local`。
- `doppler_reference_mode` 全部为 `fixed_site_segment_center`。
- 每条 row 的 `evaluation_start_s/end_s` 与 `segment_start_s/end_s` 完全一致。
- `coverage_gate_pass = true` 对所有样本成立。
- `coverage_valid_fraction = 1.0` 对所有样本成立。
- `rho=0` 最大 `S-C` 距离为 `0 m`。
- `rho=0` 最大 `rmse_r_geo_hz` 为约 `1.49e-6 Hz`。

因此，本轮结果可以按 segment-local 服务区内部位置扫描解释。

## 3. 总体 rho 趋势

按所有 `R_cell / phi / sample_group / bk_mode` 聚合：

| attack_model | rho | total | ACCEPT | DEFER | REJECT | 非目标样本误接受率 |
|---|---:|---:|---:|---:|---:|---:|
| M0 | 0.00 | 192 | 128 | 0 | 64 | 66.67% |
| M0 | 0.05 | 192 | 0 | 0 | 192 | 0.00% |
| M0 | 0.10-1.00 | each 192 | 0 | 0 | 192 | 0.00% |
| M2_block | 0.00 | 576 | 320 | 0 | 256 | 55.56% |
| M2_block | 0.05 | 576 | 6 | 0 | 570 | 1.04% |
| M2_block | 0.10-1.00 | each 576 | 0 | 0 | 576 | 0.00% |

主结论：风险从服务区中心向外移动后下降很快。M2_block 在 `rho=0` 有明显误接受；到 `rho=0.05` 只剩少量误接受；到 `rho>=0.10` 后未观察到误接受。

## 4. 样本组差异

M2_block 在 `rho=0`：

- `ordinary_similar`: `192 ACCEPT / 96 REJECT`，非目标样本误接受率 `66.67%`。
- `boundary_case`: `128 ACCEPT / 160 REJECT`，非目标样本误接受率 `44.44%`。

M2_block 在 `rho=0.05`：

- `ordinary_similar`: `3 ACCEPT / 285 REJECT`，非目标样本误接受率 `1.04%`。
- `boundary_case`: `3 ACCEPT / 285 REJECT`，非目标样本误接受率 `1.04%`。

M2_block 在 `rho>=0.10`：两个 sample group 均为 `0 ACCEPT`。

当前 scaled run 中，ordinary_similar 在中心点更容易被接受；离开中心后，两类样本都快速降为低风险。

## 5. b/k 模式差异

M2_block 在 `rho=0`：

- `no_bk`: `0 ACCEPT / 192 REJECT`，仍是最严格基线。
- `current_bk`: `160 ACCEPT / 32 REJECT`，非目标样本误接受率 `83.33%`。
- `wide_bk`: `160 ACCEPT / 32 REJECT`，非目标样本误接受率 `83.33%`。

M2_block 在 `rho=0.05`：

- `no_bk`: `0 ACCEPT / 192 REJECT`。
- `current_bk`: `0 ACCEPT / 192 REJECT`。
- `wide_bk`: `6 ACCEPT / 186 REJECT`，非目标样本误接受率 `3.13%`。

M2_block 在 `rho>=0.10`：三种 b/k 模式均为 `0 ACCEPT`。

因此，`wide_bk` 会略微扩大中心附近风险区域，但没有把风险扩展到 `rho>=0.10`。`no_bk` 仍然最严格。

## 6. R_cell 与 rho

M2_block 在相同 `rho=0.05` 下：

- `R_cell=50 km`，实际距离 `2.5 km`，出现 `6 ACCEPT / 138 REJECT`。
- `R_cell=100/200/500 km`，实际距离分别为 `5/10/25 km`，均为 `0 ACCEPT`。

在相同 rho 下，R_cell 改变会改变绝对参考点误差 `d(S,C_i)`；风险并不完全由 rho 解释。

## 7. 绝对距离对照

M2_block 的相同绝对距离对照显示：

- `10 km`: `R_cell=50,rho=0.2`；`R_cell=100,rho=0.1`；`R_cell=200,rho=0.05`，均为 `0 ACCEPT`。
- `20 km`: `R_cell=50,rho=0.4`；`R_cell=100,rho=0.2`；`R_cell=200,rho=0.1`，均为 `0 ACCEPT`。
- `25 km`: `R_cell=50,rho=0.5`；`R_cell=100,rho=0.25`；`R_cell=500,rho=0.05`，均为 `0 ACCEPT`。
- `50 km`: 多个 `R_cell/rho` 组合均为 `0 ACCEPT`。

当前样本中，相同或接近绝对距离下，不同 `R_cell/rho` 组合的风险更接近。结果更支持：绝对距离 `d(S,C_i)` 比归一化位置 `rho` 更直接解释风险下降。

## 8. Observed Risk Transition

这些值只表示当前样本下观察到的风险过渡区间，不是严格安全阈值，也不是真实系统安全半径。

M2_block 的主要观察：

- `no_bk`: 从 `rho=0` 起就没有 ACCEPT。
- `current_bk`: ACCEPT 只出现在 `rho=0`。
- `wide_bk`: 大多数设置 ACCEPT 只出现在 `rho=0`；仅 `R_cell=50 km` 时在 `rho=0.05` 仍有少量 ACCEPT，对应距离 `2.5 km`。
- `rho>=0.10` 时，所有 `R_cell / sample_group / bk_mode` 均未观察到 ACCEPT。

因此，当前 scaled run 下观察到的高风险区间非常靠近服务中心：

```text
主风险点：rho = 0
残余风险：rho = 0.05 且 R_cell = 50 km / wide_bk
无观察到误接受：rho >= 0.10
```

按绝对距离看：

```text
d = 0 km：明显高风险
d = 2.5 km：仅 wide_bk 下有少量残余风险
d >= 5 km：当前样本未观察到误接受
```

## 9. T_service 小规模确认

主扫描后补充了一个小规模确认版：`T_service_s=30,120`，`R_cell=100 km`，`rho=0,0.1,0.2,0.3,0.5`，4 个方向，仍保持 `segment_local / fixed_site_segment_center / single-window`。

| T_service_s | rho | total | ACCEPT | DEFER | REJECT | 非目标样本误接受率 |
|---:|---:|---:|---:|---:|---:|---:|
| 30 | 0.0 | 72 | 32 | 0 | 40 | 44.44% |
| 30 | 0.1 | 72 | 0 | 0 | 72 | 0.00% |
| 30 | 0.2 | 72 | 0 | 0 | 72 | 0.00% |
| 30 | 0.3 | 72 | 0 | 0 | 72 | 0.00% |
| 30 | 0.5 | 72 | 0 | 0 | 72 | 0.00% |
| 120 | 0.0 | 72 | 48 | 0 | 24 | 66.67% |
| 120 | 0.1 | 72 | 0 | 0 | 72 | 0.00% |
| 120 | 0.2 | 72 | 0 | 0 | 72 | 0.00% |
| 120 | 0.3 | 72 | 0 | 0 | 72 | 0.00% |
| 120 | 0.5 | 72 | 0 | 0 | 72 | 0.00% |

确认版结果与主扫描一致：风险集中在 `rho=0`，`rho>=0.1` 未观察到非目标样本误接受。

## 10. M0 与 M2_block

M0 与 M2_block 在局部 fixed-C 语义下呈现一致空间趋势：

- 中心点 `rho=0` 风险最高；
- 轻微偏离中心后风险快速下降；
- `rho>=0.10` 后未观察到误接受。

二者数值不完全相同，原因是 M0 是一个固定参考点基线，M2_block 是多个 60s segment-local block 的拼接样本；但空间风险趋势是一致的。

## 11. 输出文件

- `outputs/datasets/m2_segment_local_rho_fine_sweep_dataset.csv`
- `outputs/metrics/m2_segment_local_rho_fine_sweep_summary.csv`
- `outputs/metrics/m2_segment_local_distance_sweep_summary.csv`
- `outputs/metrics/m2_segment_local_risk_boundary_summary.csv`
- `outputs/reports/m2_segment_local_rho_fine_sweep_report.md`
- `outputs/figures/m2_segment_local_rho_fine_sweep/accept_rate_vs_rho.png`
- `outputs/figures/m2_segment_local_rho_fine_sweep/accept_rate_vs_distance_km.png`
- `outputs/figures/m2_segment_local_rho_fine_sweep/rho_by_rcell_heatmap.png`
- `outputs/figures/m2_segment_local_rho_fine_sweep/sample_group_rho_comparison.png`
- `outputs/figures/m2_segment_local_rho_fine_sweep/bk_mode_rho_comparison.png`

补充确认版：

- `outputs/datasets/m2_segment_local_tservice_confirm_dataset.csv`
- `outputs/metrics/m2_segment_local_tservice_confirm_summary.csv`
