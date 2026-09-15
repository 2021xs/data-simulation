# Controlled Starlink 20-target Partial-pass Validation Report

生成时间：2026-05-05 21:41

## 实验目的
本轮是 20-target multi-target partial-pass validation，用于验证 44714 的 partial-pass failure 是否不是孤例。当前不是攻击实验，不是攻击成功率，不是真实 Starlink observation replay，也不是 Starlink CFO truth。

## 20 target 样本表
- CSV：`outputs\metrics\controlled_starlink_20target_selection_table.csv`
- Markdown：`outputs\reports\controlled_starlink_20target_selection_table.md`
- 有效 target 数：20
- skipped target 数：2
- pass duration 范围：248.0 - 444.0 s
- Doppler span 范围：285304.174 - 507598.487 Hz

## 输入配置
- target_count = 20
- candidate_limit = 1000
- center frequency = 11325000000 Hz
- station = controlled_example_station / lat=52.21 / lon=5.16 / alt_m=14
- error_model_variant = frequency_scaled
- sigma_multiplier = 10
- scenario = offset_plus_noise
- window_durations = ['full', 'center_180s', 'center_120s', 'center_60s', 'center_30s']
- num_sims_per_target_per_window = 50
- mode = controlled_starlink
- observation_id = null

## 数据集规模
- total_sequences：5000
- total_rows：752700
- candidate library rows：7198000
- skipped windows：0

## 总体结果
| window_duration_label | sequence_count | target_count | accuracy | wrong_count | negative_margin_count | mean_margin_hz | median_margin_hz | min_margin_hz | p05_margin_hz | mean_true_score_rmse_hz | mean_best_wrong_score_rmse_hz |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| center_120s | 1000 | 20 | 0.948000 | 52 | 52 | 449.882328 | 264.884008 | -104.983951 | -0.758400 | 1935.398519 | 2385.280847 |
| center_180s | 1000 | 20 | 0.994000 | 6 | 6 | 1708.791789 | 1454.429875 | -26.441090 | 58.878725 | 1935.572434 | 3644.364223 |
| center_30s | 1000 | 20 | 0.098000 | 902 | 902 | -33.241810 | -18.036328 | -417.140225 | -119.001461 | 1884.919537 | 1851.677727 |
| center_60s | 1000 | 20 | 0.455000 | 545 | 545 | 5.974931 | -2.161651 | -229.546409 | -66.381952 | 1927.728445 | 1933.703376 |
| full | 1000 | 20 | 0.999000 | 1 | 1 | 7185.800868 | 5630.697833 | -2.132823 | 175.200167 | 1948.067088 | 9133.867956 |

说明：overall / window accuracy 是 stress grid 平均值，不是真实场景准确率。

## full pass 是否稳定
- full accuracy：0.999000
- full negative_margin_count：1
- full min_margin_hz：-2.132823

## 短窗口影响
- 60s 出现 negative margin 的 target 数：20
- 30s 出现 negative margin 的 target 数：20
- 30s min_margin_hz：-417.140225
- 60s min_margin_hz：-229.546409
- 44714 是多个 failure case 之一，不是唯一目标。

## per-target 差异与 hard wrong
- 最脆弱 target：STARLINK-34983 / 65411，window=center_30s，min_margin=-417.140225
- hard wrong 分布 top 10：{'64267': 274, '65838': 216, '66233': 180, '63516': 171, '66082': 167, '66407': 166, '64732': 159, '62451': 154, '66880': 149, '47808': 147}
- 每个 target 的 hard wrong 见 `outputs\metrics\controlled_starlink_20target_partial_pass_hard_wrong_table.csv`。

## 结论边界
当前证明的是 controlled partial-pass validation。如果多个 target 短窗口失稳，只能说 controlled setting 下存在系统性 partial-pass confusion risk；不能解释为真实攻击成功率，不能解释为真实 Starlink observation 结果。

## 下一步建议
如果多数 target 在 30s/60s 失稳，进入 multi-target near-neighbor replay attack 设计；也可先挑最脆弱 target 做 case study。若需要统计版，可扩展到 50 target。
