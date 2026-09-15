# Full-Pass Quality Expanded Resampled Summary

## 1. 实验目的

上一轮 sanity check 发现 medium legit accept rate 偏低主要来自每个 pass 只有 5 条 legitimate calibration samples。本轮只补足 medium/high full-pass 的合法校准样本，不新增攻击类型、不做 multi-window / multi-station / active compensation，也不扩大 altitude sweep。

## 2. Coverage 与校准设置

原始 coverage：

| elevation_bin   |   total_passes |   total_sequences |   target_count |   attack_pair_count | notes                   |
|:----------------|---------------:|------------------:|---------------:|--------------------:|:------------------------|
| low             |              4 |               480 |              4 |                   8 | nan                     |
| medium          |              0 |                 0 |              0 |                   0 | missing_medium_coverage |
| high            |             12 |              1440 |              4 |                   8 | nan                     |

本轮 expansion 使用 `num_legit_sims_per_pass=50` 计算同一 pass 的 p95/p99 score threshold 与 p01/p99 k range；attack samples 仍保持 `num_sims_per_case=5`。

## 3. Legit Calibration Sanity

| elevation_bin   | threshold_type   |   legit_calibration_count_per_pass_median |   total_legit_sequences |   score_only_accept_rate |   per_pass_k_gate_accept_rate |   score_fail_count |   k_gate_fail_count |   both_fail_count |   median_k_range_width | notes                                  |
|:----------------|:-----------------|------------------------------------------:|------------------------:|-------------------------:|------------------------------:|-------------------:|--------------------:|------------------:|-----------------------:|:---------------------------------------|
| low             | p95              |                                       nan |                      80 |                  0.95    |                      0.875    |                  4 |                   0 |                 0 |             nan        | some_rows_missing_k_range_audit_fields |
| medium          | p95              |                                        50 |                     600 |                  0.94    |                      0.9      |                 36 |                  24 |                 0 |               0.876145 | nan                                    |
| high            | p95              |                                        50 |                     640 |                  0.94375 |                      0.8875   |                 34 |                  14 |                 2 |               0.863345 | some_rows_missing_k_range_audit_fields |
| low             | p99              |                                       nan |                      80 |                  0.95    |                      0.875    |                  4 |                   0 |                 0 |             nan        | some_rows_missing_k_range_audit_fields |
| medium          | p99              |                                        50 |                     600 |                  0.98    |                      0.94     |                 12 |                  24 |                 0 |               0.876145 | nan                                    |
| high            | p99              |                                        50 |                     640 |                  0.96875 |                      0.910937 |                 19 |                  15 |                 1 |               0.863345 | some_rows_missing_k_range_audit_fields |

关键对比：

- old medium p95 score+k accept rate = `0.4500`
- new medium p95 score+k accept rate = `0.9000`
- old medium p95 score-only accept rate = `0.8000`
- new medium p95 score-only accept rate = `0.9400`
- new medium p99 score+k accept rate = `0.9400`
- p95 medium k gate extra reject count = `24`
- p99 medium k gate extra reject count = `24`

## 4. Attack Accept Rate

- p95 low attack per-pass k accept rate = `0.3125`
- p95 medium attack per-pass k accept rate = `0.0000`
- p95 high attack per-pass k accept rate = `0.0000`

补足合法校准样本后，medium/high attack accept rate 仍为 0，说明上一轮 full-pass quality 主结论没有被合法校准样本量问题推翻。

## 5. Elevation Threshold 与 Aggregation

以 p95、`elevation_min_deg=20` 为例：

- tri-state attack accept rate = `0.0000`
- tri-state legit accept rate = `0.8394`
- `any_high_quality_accept` attack final accept rate = `0.0000`
- `any_high_quality_accept` legit final accept rate = `1.0000`
- `two_high_quality_accept` legit final accept rate = `1.0000`

当前仍支持 `20 deg` 作为初步 high-quality full-pass threshold。`any_high_quality_accept` / `defer_if_only_low_quality` 仍是最平衡规则：低质量 pass 通过也只 DEFER，至少一个 high-quality full-pass 通过才最终 ACCEPT。

## 6. 字段保留检查

`full_pass_quality_expanded_sequence_eval.csv` 已保留 `pass_k_min_p01 / pass_k_max_p99`：`True`。同时保留 `pass_k_min_p05 / pass_k_max_p95 / k_range_width / legit_calibration_count / score_threshold_source / k_range_source`，旧 base rows 若没有这些字段则为空并在 analyze 阶段 warning。

## 7. 结论

1. 增加合法校准样本后，medium legit p95 score+k accept rate 从 `0.4500` 恢复到 `0.9000`。
2. p95/p99 合法接受率已回到更合理范围，k gate 额外拒绝明显减少。
3. medium/high attack accept rate 仍为 0。
4. `20 deg` threshold 与 full-pass multi-pass aggregation 主线仍成立。
5. 当前可以进入 pass-quality-aware / multi-pass-aware attacker 阶段；同时建议继续扩大合法校准样本和 target 覆盖。
