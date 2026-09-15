# Medium Legit Accept Rate Debug

## 1. 问题背景

上一轮 full-pass quality expansion 中，medium elevation legitimate samples 的 p95 `score + per-pass k p01-p99 gate` accept rate 为 `0.9000`。该值明显低于直觉上的 p95 合法通过率，因此本轮只做 sanity check，不新增攻击实验。

## 2. 0.4500 的复算来源

medium elevation 定义复核为 `20 <= max_elevation_deg < 40`。复算结果：

- p95 total = `600`，score-only accepted = `564`，per-pass k accepted = `540`。
- p95 score-only accept rate = `0.9400`，per-pass k gate accept rate = `0.9000`。
- p99 total = `600`，score-only accept rate = `0.9800`，per-pass k gate accept rate = `0.9400`。

## 3. 失败原因拆解

p95 下失败拆解：

- score_fail = `36`
- k_gate_fail = `24`
- both_fail = `0`
- accepted 字段与 `score <= threshold AND k_min <= k_hat <= k_max` 的不一致条数 = `0`

主要问题不是 medium pass 几何本身导致 score 明显失控，而是每个 pass 的合法校准样本过少时，p95 threshold 和 p01/p99 k range 都会出现机械性排边界样本的现象。大量样本属于 `score_pass=true` 但 `k_pass=false`。

## 4. By-pass 分析

每个 medium pass 的 legitimate rows 数量范围为 `50` 到 `50`。由于每个 pass / threshold 下只有 5 条合法样本，p95 分位数按插值会天然使最大 score 样本不通过；p01/p99 k range 也会使 k_hat 的最小/最大样本不通过。

最低接受率 pass 示例：

| target_name   | pass_id             |   max_elevation_deg |   legit_sequence_count |   score_only_accept_rate |   per_pass_k_gate_accept_rate |   k_range_width | notes   |
|:--------------|:--------------------|--------------------:|-----------------------:|-------------------------:|------------------------------:|----------------:|:--------|
| STARLINK-1008 | 44714_exp_01_medium |             26.9855 |                     50 |                     0.94 |                           0.9 |        0.894553 |         |
| STARLINK-1008 | 44714_exp_02_medium |             30.0261 |                     50 |                     0.94 |                           0.9 |        0.855825 |         |
| STARLINK-1008 | 44714_exp_03_medium |             33.3704 |                     50 |                     0.94 |                           0.9 |        0.829918 |         |
| STARLINK-2185 | 47767_exp_01_medium |             27.2274 |                     50 |                     0.94 |                           0.9 |        0.874934 |         |
| STARLINK-2185 | 47767_exp_02_medium |             30.2964 |                     50 |                     0.94 |                           0.9 |        0.898647 |         |

## 5. 代码口径检查

检查结果：

- threshold 在 `run_full_pass_quality_coverage_expansion.py` 中由同一个 pass 的 legitimate scores 计算。
- `pass_k_min_p01 / pass_k_max_p99` 由同一个 pass 的 legitimate k_hat 分布计算。
- attack samples 没有混入 threshold 或 k range 计算。
- p95 / p99 threshold_type 没有混用；k range 当前对 p95/p99 共用同一 pass legitimate k distribution。
- `sample_type == legit` 过滤正常。
- expanded merge 中未发现 medium legitimate duplicate / 字段覆盖导致的统计口径错误。

代码检查摘要：

```json
{
  "medium_definition_ok": true,
  "accepted_recomputed_mismatch_count": 0,
  "medium_legit_threshold_types": [
    "p95",
    "p99"
  ],
  "medium_legit_pass_count": 12,
  "medium_legit_rows_per_pass_threshold_min": 50,
  "medium_legit_rows_per_pass_threshold_max": 50,
  "attack_rows_excluded_from_debug": true
}
```

## 6. Resample Sanity Check

本轮没有重新传播轨道或新增攻击实验；只对已有 medium legit rows 做 non-parametric bootstrap，观察小样本分位数机制。结果如下：

|   resample_count |   resample_repeats_per_pass |   pass_count |   mean_score_only_accept_rate |   median_score_only_accept_rate |   mean_per_pass_k_gate_accept_rate |   median_per_pass_k_gate_accept_rate |   mean_k_range_width |   median_k_range_width | notes                                                                                       |
|-----------------:|----------------------------:|-------------:|------------------------------:|--------------------------------:|-----------------------------------:|-------------------------------------:|---------------------:|-----------------------:|:--------------------------------------------------------------------------------------------|
|               20 |                        2000 |           12 |                      0.959421 |                            0.95 |                           0.883879 |                                 0.9  |             0.806596 |               0.817098 | nonparametric bootstrap from existing 5-sample medium legit rows; not new orbit propagation |
|               50 |                        2000 |           12 |                      0.949955 |                            0.94 |                           0.929016 |                                 0.92 |             0.856374 |               0.864079 | nonparametric bootstrap from existing 5-sample medium legit rows; not new orbit propagation |

这个 resample 不能替代真实新增合法样本，但能说明：当样本量增加时，score-only accept rate 会接近 p95；k gate 接受率仍受底层 k_hat 支撑点只有 5 个限制，因此真正修复应增加每个 pass 的 legitimate calibration samples，而不是收紧或放宽攻击判决。

## 7. 结论与建议

`0.4500` 可以复现，主要是样本量问题和 per-pass p01/p99 quantile 口径在 `n=5` 时过窄导致，不是 attack/legit 混入或 summary bug。建议后续重新生成 medium/high pass 的 legitimate calibration，至少每 pass 20-50 条，再更新 pass-quality-aware threshold 与 k range。当前 verifier v3 的核心结论仍不受直接影响：medium/high attack accept rate 仍为 0，`20 deg` 仍可作为初步 high-quality pass threshold；但合法接受率相关数字应标注为小样本 sanity result，进入 pass-quality-aware attacker 前最好先补合法校准样本。
