# Fixed-C Legacy Replay Reconciliation Report

本轮只做 fixed-C 新旧实验对账；没有新增攻击模型，没有扩大完整 main，也没有覆盖旧正式输出。本报告仍属于 controlled simulation 结果整理，不是真实 Starlink 调度或真实攻击成功率评估。

## 1. 旧 fixed-C 表格来源

用户给出的旧百分比精确对应以下数据源和过滤条件：

- dataset: `outputs/datasets/original_vs_current_fixed_reference_dataset.csv`
- script: `scripts/reproduce_original_50km_rejection_experiment.py`
- report: `outputs/reports/original_vs_current_fixed_reference_alignment.md`
- filter:
  - `style_type = original_style`
  - `compensation_mode = fixed_reference_compensation`
  - `bk_mode = current_bk`
  - `window_mode = full_pass`
  - `strategy_type = original_strong_prior`
- statistic: case/row-level `final_decision == ACCEPT` rate。
- 每个 `sample_group / R` 有 24 行，即 6 个样本乘以 4 个 bearing。

| sample_group | R_label_km | total_cases | accept_count | accept_rate |
|---|---:|---:|---:|---:|
| boundary_case | 50 | 24 | 23 | 95.83% |
| boundary_case | 100 | 24 | 20 | 83.33% |
| boundary_case | 200 | 24 | 16 | 66.67% |
| boundary_case | 500 | 24 | 6 | 25.00% |
| ordinary_similar | 50 | 24 | 9 | 37.50% |
| ordinary_similar | 100 | 24 | 8 | 33.33% |
| ordinary_similar | 200 | 24 | 3 | 12.50% |
| ordinary_similar | 500 | 24 | 1 | 4.17% |
| random_simulated | 50 | 24 | 0 | 0.00% |
| random_simulated | 100 | 24 | 0 | 0.00% |
| random_simulated | 200 | 24 | 0 | 0.00% |
| random_simulated | 500 | 24 | 0 | 0.00% |

## 2. Replay 等级

本轮不能做 exact replay，只能做 near replay。

原因是旧 dataset 保存了 `b_injected / k_injected / noise_std / noise_seed`，但没有保存逐点 noise vector 或完整 RNG state。旧脚本里的 `noise_seed` 是 provenance 标签，而不是每条 case 独立播种后即可重建同一噪声向量的完整状态。因此，本轮 replay 保持同一个 A/S/C/time/b/k/noise_std，并使用 deterministic noise 近似重建。

## 3. 旧 R 标签距离审计

已重新计算：

```text
actual_distance_S_C_km = d_geo(S, C)
```

其中旧表里的 `C` 对应 `S_hat_lat / S_hat_lon`。

结果：

```text
max_abs_distance_error_km = 1.25e-12 km
```

结论：旧表中的 `R=50/100/200/500 km` 与真实大圆距离一致，未发现 km/m 转换、经纬度欧氏距离或坐标单位错误。旧 R 标签不是本次矛盾的原因。

## 4. 配对样本选择

从旧 fixed-C 表中抽取：

- `ordinary_similar` 对应旧 `original_like`
- `boundary_case` 对应旧 `hard_case_weighted`
- 每个 `sample_group / R` 最多 5 个 ACCEPT 和 3 个 REJECT
- 如果不足则全部提取

最终选取 56 条旧样本：

- legacy ACCEPT: 34
- legacy REJECT: 22

输出 case list:

```text
outputs/metrics/fixed_c_legacy_replay_case_list.csv
```

## 5. Replay 判决转移

near replay 的总体转移：

| legacy_decision | replay_decision | count |
|---|---:|---:|
| ACCEPT | ACCEPT | 31 |
| ACCEPT | REJECT | 3 |
| REJECT | ACCEPT | 5 |
| REJECT | REJECT | 17 |

旧 ACCEPT 中：

```text
ACCEPT -> ACCEPT: 31
ACCEPT -> REJECT: 3
ACCEPT -> DEFER: 0
```

旧 REJECT 中：

```text
REJECT -> ACCEPT: 5
REJECT -> REJECT: 17
REJECT -> DEFER: 0
```

因此，在 near replay 口径下，旧 fixed-C ACCEPT 大多数仍可复现为 ACCEPT。旧结果不是单纯由 R 标签错误或明显 Doppler 路径错误造成的。

## 6. Gate 差异

旧 ACCEPT 变为 REJECT 的 3 条分别首个分歧 gate 为：

- score gate: 1
- b gate: 1
- k gate: 1

旧 REJECT 变为 ACCEPT 的 5 条分歧为：

- score gate: 3
- b gate: 1
- k gate: 1

这些差异主要符合 near replay 的预期：噪声向量不能精确恢复，且 replay 使用当前 calibration / threshold 口径，因此靠近门限的 case 会发生少量翻转。

## 7. 样本组定义对比

旧 fixed-C 表：

- `original_like` 映射到阶段报告中的 `ordinary_similar`。
- `hard_case_weighted` 映射到阶段报告中的 `boundary_case`。
- 二者主要是 synthetic orbit perturbation 样本，例如 altitude / inclination / phase offset。
- 本轮抽取的旧 ordinary/boundary case 中，`attacker_norad_id` 均为 `synthetic`，不是真实 TLE candidate。
- 旧 hard_case_weighted 还会从 hard-case 列表中优先选更危险样本。

新 rho fine sweep：

- 使用 `run_segmented_service_center_compensation.py` 的 candidate-library selection。
- `ordinary_similar` 和 `boundary_case` 来自真实 TLE candidate pool。
- 本轮 scaled run 中二者都选中了同一个真实 attacker：target `44714 / STARLINK-1008`，attacker `65686 / STARLINK-35137`。
- `max_targets=1`、`max_attackers_per_group=1`，样本覆盖远小于旧 fixed-C 表。

结论：旧 boundary_case 与新 fine sweep boundary_case 不是同一批样本，也不是同一套生成规则。新实验中的 boundary_case 不是旧 fixed-C 表中的最危险 hard_case_weighted synthetic 样本。

## 8. 主要实现口径差异

主要差异包括：

1. 样本来源不同：
   旧表使用 synthetic perturbation；新 fine sweep 使用真实 TLE candidate。

2. 时间窗口不同：
   旧表是 full-pass `original_style`；新 fine sweep 是 segment-local block。

3. reference point 语义不同：
   旧表的 `R` 是 `S_hat` 相对固定站 `S` 的偏移；新 fine sweep 的距离是 segment center `C_i` 到局部扫描站 `S` 的距离。

4. verifier / calibration 口径不同：
   旧表是 `original_strong_prior`；new replay / fine sweep 使用当前脚本中的 calibration 与 gate 逻辑。

5. exact replay 不可用：
   旧表缺少逐点噪声向量，因此只能 near replay。

## 9. 当前判断

三种情况中，当前更接近“情况 C，但偏向旧 ACCEPT 可复现”：

```text
legacy ACCEPT -> replay ACCEPT: 31 / 34
legacy ACCEPT -> replay REJECT: 3 / 34
```

这说明旧 fixed-C 高风险结果大体可信，至少不是由明显 R 标签错误或固定参考点补偿方向错误导致。

但旧结果不能直接与新 rho fine sweep 的“5 km 后未观察到 ACCEPT”并列解释，因为两者同时存在明显样本选择差异和实现口径差异。

## 10. 对核心矛盾的回答

旧实验中 50-500 km 仍有较高非目标样本误接受，而新实验在 5 km 后没有 ACCEPT，差异更可能来自：

```text
样本选择差异 + 实验实现口径差异共同作用
```

其中样本选择差异很大：

- 旧表中的高风险主要来自 synthetic hard_case_weighted / original_like。
- 新 fine sweep 只用了一个 target、一个真实 TLE attacker。

实现口径也不同：

- 旧表是 full-pass fixed-C。
- 新表是 segment-local fixed-C。

因此，当前不能用新 fine sweep 的 5 km 结果否定旧 fixed-C 表，也不能把旧 fixed-C 表直接外推到新 segment-local 服务区扫描。

## 11. 输出文件

- `outputs/metrics/fixed_c_legacy_replay_case_list.csv`
- `outputs/metrics/fixed_c_legacy_distance_audit.csv`
- `outputs/metrics/fixed_c_legacy_replay_comparison.csv`
- `outputs/metrics/fixed_c_legacy_replay_summary.csv`
- `outputs/reports/fixed_c_legacy_reconciliation_report.md`
