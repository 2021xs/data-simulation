# Starlink Doppler Residual Claimed-Identity Verifier

本项目用于构造和评估一个受控的 Starlink Doppler residual claimed-identity verifier。当前主线不是高精度定轨，也不是真实 SatNOGS Starlink observation replay，而是：

```text
真实 Starlink TLE
+ 受控地面站
+ Ku-band 合理频率
+ automatic pass search
+ engineering effective residual model
+ claimed-identity Doppler verifier
+ near-neighbor / synthetic orbit attack stress test
```

前期 SatNOGS / STRF / rffit 工作提供工程级 effective residual 参数来源；当前 Starlink 阶段用这些参数构造 controlled orbit-based simulation 和 verifier stress test。所有结论都应理解为受控仿真 baseline，不代表真实 Starlink Ku-band residual 分布，也不代表真实攻击成功率。

## 1. 核心模型

默认观测模型为：

```text
f_obs(t) = f_geo(t) + b + k(t - t0) + noise
```

其中：

- `f_geo(t)`：由 TLE / station / frequency 计算出的几何 Doppler 频率基线。
- `b`：effective constant frequency bias，对应 `registered_frequency_offset_hz`。
- `k`：linear slow drift，对应 `linear_slope_hz_per_s`。
- `noise`：detrended residual disturbance 的 first-order Gaussian approximation，对应 `detrended_std_hz`。

重要边界：

- 不把 `registered_frequency_offset_hz` 写成 true CFO、pure CFO 或 CFO ground truth。
- 不把 `frequency_scaled` 写成真实 Starlink Ku-band CFO 分布。
- 不把 `noise` 写成严格白噪声。
- `b/k/noise` 在 verifier / attack 实验中统一称为 observation/model residual terms 或 effective residual terms，不解释为攻击者精确可控参数。

## 2. 当前输入与配置

主要输入：

```text
configs/simulation_parameter_config.yaml
configs/orbit_simulation_cases.yaml
data/tle/starlink_tle.txt
data/source_residual_datasets/
outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv
outputs/metrics/controlled_starlink_20target_selection_table.csv
```

默认受控 station：

```text
lat = 52.2100 deg
lon = 5.1600 deg
alt = 14 m
```

Ku-band simulation frequency：

```text
simulation_center_freq_hz = 11325000000
```

当前 residual main range：

```text
b_hz:          [3179.0, 3728.0]
k_hz_per_s:   [-1.110156, -0.197808]
sigma_hz:     [23.215, 32.890]
```

## 3. Verifier 定义

当前 verifier 是 single-target claimed-identity verifier。输入是：

```text
claimed target A
observation curve y(t)
claimed target geometry f_geo_A(t)
```

计算：

```text
delta_A(t) = y(t) - f_geo_A(t)
delta_A(t) ~= b_hat + k_hat(t - t0) + residual
score_A = RMSE(residual)
```

score-only 判决：

```text
accepted = score_A <= threshold_A
```

verifier v2 在 score-only 后增加 fitted-parameter sanity gate：

```text
accepted = score_A <= threshold_A
           AND k_hat in legal k range
```

当前重点使用：

- per-target `k_hat` p01-p99 range
- per-pass `k_hat` p01-p99 range（multi-pass retest 中重新校准）

## 4. 当前实验进展

### 4.1 Ku-band controlled Starlink baseline

已完成 20-target / Ku-band / candidate-library controlled baseline 和 partial-pass validation。相关输出位于：

```text
outputs/datasets/controlled_starlink_20target_*.csv
outputs/metrics/controlled_starlink_20target_*.csv
outputs/reports/controlled_starlink_20target_*.md
```

这些结果用于 verifier 的 target/pass/candidate 基础，不应解读为真实 observation replay。

### 4.2 Verifier v2 最小闭环

上一轮 score-only attack evaluation：

```text
attack sequences = 2000
score-only false accepts = 3 / 2000
false accepts 全部来自 same_plane_altitude_offset / delta_h_-5km
false accepts 的 k_hat 约为 -3.22 到 -3.32 Hz/s
```

加入 fitted k sanity gate 后：

```text
global k gate 拒绝全部 3 个 false accepts
per-target k p01-p99 gate 拒绝全部 3 个 false accepts
p95 下 per-target k p01-p99 gate attack false accept rate = 0.0
p95 下 per-target k p01-p99 gate legit accept rate 额外损失 = 0.0
```

主要输出：

```text
outputs/metrics/verifier_v2_sequence_eval.csv
outputs/metrics/verifier_v2_gate_ablation.csv
outputs/metrics/verifier_v2_false_accepts_detail.csv
outputs/metrics/attack_visibility_timing_diagnostic.csv
outputs/metrics/attack_visibility_timing_summary.csv
outputs/reports/verifier_v2_summary.md
outputs/figures/verifier_v2/
```

### 4.3 Fine sweep 边界压力测试

随后对 same-plane altitude / phase perturbation 做更细粒度 sweep。

altitude fine sweep：

```text
delta_h_km = [-10, -7.5, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7.5, 10]
p95 attack sequences = 1400
score-only false accepts = 56
score + per-target k p01-p99 false accepts = 17
```

phase fine sweep：

```text
phase_offset_s = [-300, -120, -60, -30, -10, -5, 5, 10, 30, 60, 120, 300]
p95/p99 score-only false accepts = 0
```

最危险区域：

```text
delta_h = -2 km:
  p95 score-only = 13 / 100
  p95 per-target k p01-p99 = 8 / 100

delta_h = -1 km:
  p95 score-only = 13 / 100
  p95 per-target k p01-p99 = 9 / 100
```

涉及 target：

```text
STARLINK-35060 / 65693
STARLINK-2698  / 48458
STARLINK-2185  / 47767
STARLINK-1008  / 44714
```

主要输出：

```text
outputs/metrics/verifier_v2_altitude_fine_sweep_sequence_eval.csv
outputs/metrics/verifier_v2_phase_fine_sweep_sequence_eval.csv
outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv
outputs/metrics/verifier_v2_fine_sweep_hard_cases.csv
outputs/reports/verifier_v2_fine_sweep_summary.md
outputs/figures/verifier_v2_fine_sweep/
```

### 4.4 Hard case forensic + temporal consistency

对 `delta_h=-1/-2 km` 且通过 `score + per-target k p01-p99` 的 hard cases 做 forensic 和 temporal retest。

selected hard cases：

```text
17
```

forensic 结论：

- 这些样本不是简单的 `k_hat` 贴边通过。
- 一些最低分样本的 `k_hat` 位于合法区间内部。
- `f_geo_B(t)` 与 claimed `f_geo_A(t)` 在特定 pass geometry 下天然接近，且 b+k profile 能吸收主要差异。

multi-pass retest：

```text
hard-case targets = 4
passes per target = 4
p95 attack sequences = 640
score-only accepted = 84 / 640 = 0.13125
per-pass k gate accepted = 50 / 640 = 0.078125
```

风险集中在低仰角 pass：

```text
pass_01 max elevation 约 14-15 deg
后续较高 elevation pass 基本不再 accepted
```

multi-window consistency：

```text
30s all-windows:
  legit accept rate  = 0.4125
  attack accept rate = 0.2333

60s all-windows:
  legit accept rate  = 0.4625
  attack accept rate = 0.3792

120s all-windows:
  legit accept rate  = 0.6750
  attack accept rate = 0.3208
```

结论：多窗口一致性可以降低一部分 attack accepted rate，但严格规则会明显损失 legit accept rate；宽松 majority / mean-normalized 规则对 legit 友好但难以过滤 hard cases。因此不能把单个 random short window 宣称为防御增强。

主要输出：

```text
outputs/metrics/verifier_v2_hard_case_selected_pairs.csv
outputs/metrics/verifier_v2_hard_case_forensic_summary.csv
outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv
outputs/metrics/verifier_v2_hard_case_multipass_summary.csv
outputs/metrics/verifier_v2_hard_case_multiwindow_sequence_eval.csv
outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv
outputs/reports/verifier_v2_hard_case_temporal_summary.md
outputs/figures/verifier_v2_hard_case_forensics/
outputs/figures/verifier_v2_hard_case_temporal/
```

## 5. 主要脚本

Verifier v2：

```text
scripts/run_doppler_verifier_initial_experiments.py
scripts/evaluate_verifier_v2_gates.py
scripts/diagnose_attack_visibility_timing.py
scripts/plot_verifier_v2_results.py
```

Fine sweep：

```text
scripts/run_verifier_v2_fine_sweep_attacks.py
scripts/analyze_verifier_v2_fine_sweep.py
scripts/plot_verifier_v2_fine_sweep.py
```

Hard case temporal analysis：

```text
scripts/analyze_verifier_v2_hard_cases.py
scripts/run_verifier_v2_hard_case_multipass.py
scripts/run_verifier_v2_hard_case_multiwindow.py
scripts/plot_verifier_v2_hard_case_temporal.py
```

Orbit / matcher baseline：

```text
scripts/build_controlled_starlink_multitarget_dataset.py
scripts/build_multitarget_candidate_library.py
scripts/multitarget_orbit_residual_matcher.py
scripts/near_neighbor_stress_matcher.py
scripts/run_multitarget_partial_pass_validation.py
scripts/run_partial_pass_boundary_refinement.py
```

## 6. 常用复现命令

Verifier v2 gate ablation：

```bash
python scripts/evaluate_verifier_v2_gates.py --overwrite
python scripts/diagnose_attack_visibility_timing.py --overwrite
python scripts/plot_verifier_v2_results.py --overwrite
```

Fine sweep：

```bash
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 20 --num-sims-per-case 5 --overwrite
python scripts/analyze_verifier_v2_fine_sweep.py --overwrite
python scripts/plot_verifier_v2_fine_sweep.py --overwrite
```

Hard case temporal retest：

```bash
python scripts/analyze_verifier_v2_hard_cases.py --overwrite
python scripts/run_verifier_v2_hard_case_multipass.py --max-targets 20 --num-passes-per-target 4 --num-sims-per-case 20 --overwrite
python scripts/run_verifier_v2_hard_case_multiwindow.py --max-targets 20 --num-sims-per-case 20 --num-windows 8 --window-lengths 30 60 120 --overwrite
python scripts/plot_verifier_v2_hard_case_temporal.py --overwrite
```

小样本验证：

```bash
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 2 --num-sims-per-case 2 --overwrite
python scripts/run_verifier_v2_hard_case_multipass.py --max-targets 1 --num-passes-per-target 2 --num-sims-per-case 2 --overwrite
python scripts/run_verifier_v2_hard_case_multiwindow.py --max-targets 1 --num-sims-per-case 2 --num-windows 3 --window-lengths 30 60 --overwrite
```

## 7. 当前阶段结论

1. Score-only verifier 在 coarse attack sweep 中看似 false accept 很少，但 fine altitude sweep 暴露出 `delta_h=-1/-2 km` 的边界风险。
2. Fitted `k_hat` sanity gate 明显优于 score-only，但不是充分条件；特定低仰角 pass 下仍会出现 `score + k` accepted hard cases。
3. Hard cases 更像是几何曲线天然接近并被 b+k profile 吸收，而不是简单的 k range 贴边问题。
4. Multi-pass / pass-quality-aware verifier 比单 pass verifier 更值得优先推进。
5. Random short window 不能单独宣称为增强防御；multi-window consistency 必须同时报告 legit accept rate 和 attack accept rate。

## 8. 下一步建议

优先级建议：

```text
1. multi-pass claimed-identity verifier
2. pass-quality-aware verifier / low-elevation pass defer rule
3. random challenge window with calibrated legit accept rate
4. multi-station consistency
```

暂不建议：

```text
active frequency compensation
继续盲目扩大 altitude sweep
仅靠收紧 k gate 消灭 hard cases
把 single random short window 当作强防御
```

## 9. 目录结构

```text
data-simulation/
├─ configs/
├─ data/
│  ├─ tle/
│  ├─ source_residual_datasets/
│  └─ metadata/
├─ scripts/
├─ outputs/
│  ├─ datasets/
│  ├─ metrics/
│  ├─ reports/
│  ├─ plots/
│  └─ figures/
└─ logs/
```

每轮实验结束应追加 `logs/work_log.md`，不得覆盖原始输入数据，不得覆盖旧 baseline 输出，除非明确使用 `--overwrite` 生成当前阶段的后处理结果。

## 10. 禁止表述

不要写：

```text
我们得到了 Starlink 的真实 CFO。
frequency_scaled 就是 Starlink Ku-band CFO 真值。
9424971 是当前 Starlink observation。
accuracy = 1 证明攻击无效。
当前已经验证真实 Starlink SatNOGS observation。
hard case accepted rate 就是真实攻击成功率。
```

推荐写：

```text
工程级 effective residual 参数范围
controlled Starlink TLE / station / frequency baseline
claimed-identity Doppler verifier
score + fitted k_hat sanity gate
fine sweep / hard-case temporal stress test
当前 controlled setting 下的 accept / reject behavior
```
