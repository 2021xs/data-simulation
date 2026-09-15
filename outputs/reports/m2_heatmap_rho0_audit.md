# M2 heatmap rho=0 审计

本轮只做审计：读取既有 `outputs/datasets/segmented_service_center_dwell_dataset.csv`，并对 `rho=0` 的 M2 heatmap 样本做最小几何残差重建；没有新增攻击模型，没有扩大实验规模，也没有重新运行完整 Doppler 主实验。

本审计仍属于 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。

## 1. 关键计数

- M2 heatmap `rho=0` 且 `coverage_valid=true` 的行数：15360。
- 最终判决：15360 行全部为 `DEFER`，`ACCEPT=0`，`REJECT=0`。
- gate 通过行数：
  - `score_gate_pass`: 768
  - `b_gate_pass`: 3072
  - `k_gate_pass`: 3072
  - `coverage_gate_pass`: 0
- 输出行中 `S` 到所选段中心 `C_i` 的最大距离：0 m。

## 2. 代码链路结论

`heatmap_mode` 下，M2 确实围绕当前 `center_i` 对应的 `C_i` 放置验证站。`rho=0` 时，输出 CSV 中 `S_lat == C_lat` 且 `S_lon == C_lon`，`distance_to_center_km=0`。

但当前 verifier 判决不是 segment-local。`single-window` 使用 full-pass window；`window-aware accumulation` 使用 full pass 上的 spread windows。也就是说，一个 heatmap row 虽然把 `S` 放在某个服务段中心 `C_i`，但最终判断时仍把这个固定 `S` 放进完整 pass 或跨窗口证据累计里。

因此，M2 heatmap 当前实现并不等价于“每个 segment 独立 fixed-C 实验”。它更接近：选一个 segment center 放置固定站点，然后用同一条全 pass 分段补偿 `u(t)` 评估完整窗口或跨窗口策略。

## 3. 几何残差检查

对 `M2_fast` 和 `M2_block` 的 `heatmap_mode / rho=0 / coverage_valid=true` 样本，重建：

```text
r_geo = F_B(t;S) + F_A(t;C(t)) - F_B(t;C(t)) - F_A(t;S)
```

full pass 上的 `r_geo` 不接近 0：

| summary | max_abs_r_geo_hz | mean_abs_r_geo_hz | rmse_r_geo_hz |
|---|---:|---:|---:|
| mean | 360762 | 211450 | 235747 |
| min | 266809 | 66957 | 105358 |
| max | 520923 | 357610 | 385158 |

只看所选 segment 内，`r_geo` 明显小很多，但不是机器精度 0：

| summary | max_abs_r_geo_hz | mean_abs_r_geo_hz | rmse_r_geo_hz |
|---|---:|---:|---:|
| mean | 1823.3 | 93.8817 | 362.559 |
| min | 1105.73 | 19.9692 | 163.106 |
| max | 2040.23 | 510.579 | 1020.12 |

这个 segment-local 非零主要来自实现细节：`F_A/F_B(t;C(t))` 通过 moving-reference finite-difference 路径计算，`F_A/F_B(t;S)` 通过 fixed-site Doppler 路径计算；在 segment 边界附近，moving-reference finite-difference 还会受到 `C(t)` 跳变影响。因此当前实现下不是严格代数抵消到数值精度，但相对 full-pass residual 已经显著降低。

## 4. 失败原因统计

| failure_reason | count |
|---|---:|
| coverage failed + score failed + b failed + k failed | 11520 |
| coverage failed + score failed | 3072 |
| coverage failed + b failed + k failed | 768 |

最关键的是 `coverage_gate_pass=0`。也就是说，M2 `rho=0` 的 0 ACCEPT 主要是 DEFER/coverage-evidence 口径导致，不是所有样本都被 residual gate 明确 REJECT。

## 5. M0 与 M2 差异

M0 heatmap ACCEPT 共 320 行，全部满足：

- `rho=0`
- `coverage_valid_fraction=1`
- `score_gate_pass=true`
- `b_gate_pass=true`
- `k_gate_pass=true`
- `coverage_gate_pass=true`

M0 的 `C(t)=C0` 在完整 pass 中不变，所以 `rho=0` 的固定站点始终位于该固定中心处，full-pass coverage 成立，并能形成 full-pass 或 window-aware 的 ACCEPT。

M2 的 `C(t)` 随 segment 改变。heatmap row 里的 `S` 只等于被选中的那个 segment center；一旦 verifier 用完整 pass 或跨 segment windows，这个固定 `S` 不再等于其他 segment 的 `C(t)`，coverage fraction 平均只有约 0.1908，最高也只有约 0.4478。因此 M2 `rho=0` 没有 ACCEPT 的直接原因是判决窗口语义不同，而不是所选 segment 中心放置错误。

## 6. 辅助服务区重叠统计

已输出 `outputs/metrics/m2_heatmap_adjacent_center_overlap_audit.csv`。该统计只作为辅助信息，不作为解释 M2 heatmap `rho=0` 0 ACCEPT 的主要原因。

## 7. 当前判断

未发现 `S` 与所选 `C_i` 行级错位，也未发现 M2 补偿量使用了 per-station customized `u_i(t)`。但发现一个统计口径问题：当前 `heatmap_mode` 的 M2 判决不是 segment-local，因此不能把当前 M2 heatmap `rho=0` 的 0 ACCEPT 解读为“每个服务段独立 fixed-C 中心补偿也无法 ACCEPT”。

如果后续要验证“多个独立 fixed-C 服务块”的 heatmap 风险，需要最小修改为：给 heatmap 增加 segment-local evaluation mask，使 `single-window` 只评价当前 segment，`window-aware accumulation` 不跨不同 `S` 的 segment 累计；同时重新标注该结果与现有 full-pass heatmap 口径的区别。
