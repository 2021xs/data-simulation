# Best-Claim 多普勒可混淆性 First Pass 总结

生成时间：2026-06-09T21:30:36

## 1. 实验目的

主动补偿攻击已经显示：在完整窗口与单公共补偿假设下，除精确对站上界外较难成功。因此本轮审查另一个更基础的假设：攻击者是否必须固定声称某个 A。本实验把攻击者改为 best-claim/untargeted impersonation：真实卫星 B 生成无主动补偿观测曲线，然后在候选 claim identity 中选择 residual score 最低的 A_best。

## 2. 实验设置

- true_sat 数量：`5`
- max claim candidates：`100`
- candidate_pool：`all_sampled`
- residual_mode：`empirical`
- top-k：`5`
- strong-prior：`score <= per-target p95 threshold` 且 `k_hat` 落入该 claim 的合法样本 p01/p99 范围，并满足过境质量条件。
- weak-prior：`score <= per-target p95 threshold` 且满足过境质量条件，不使用 b/k gate 直接拒绝。

当前 first pass 的 claim identities 限定在已有合法 threshold 与合法 b/k calibration 的 controlled target 集合内；`visible` pool 会用项目 SGP4/geo_curve 逻辑补算候选在同一时间网格上的最大仰角。

输出文件：

- `outputs\metrics\best_claim_sequence_eval_all_sampled.csv`
- `outputs\metrics\best_claim_summary_all_sampled.csv`
- `outputs\datasets\best_claim_candidate_scores_all_sampled.csv`
- `outputs\metrics\doppler_ambiguity_pairs_all_sampled.csv`
- `outputs\metrics\doppler_ambiguity_summary_all_sampled.csv`

## 3. Best-Claim 结果

| candidate_pool   | residual_mode   |   n |   top1_self_rate |   top5_self_rate |   best_claim_accept_rate |   best_claim_defer_rate |   best_claim_reject_rate |   strong_best_claim_accept_rate |   weak_best_claim_accept_rate |   accept_rate_gap |   weak_only_accept_count |   score_margin_median |   score_margin_p10 |   true_sat_rank_median |   num_claim_candidates_median |   non_self_best_count |
|:-----------------|:----------------|----:|-----------------:|-----------------:|-------------------------:|------------------------:|-------------------------:|--------------------------------:|------------------------------:|------------------:|-------------------------:|----------------------:|-------------------:|-----------------------:|------------------------------:|----------------------:|
| all_sampled      | empirical       |   5 |                1 |                1 |                      0.6 |                     0.2 |                      0.2 |                             0.6 |                           0.6 |                 0 |                        0 |               19369.6 |            8481.85 |                      1 |                            20 |                     0 |

非真实卫星成为 best claim 的序列数为 `0`。`score_margin = second_best_score - best_score`，margin 越小表示 top candidates 越接近。

## 4. Weak-Prior Ablation 结果

weak-only accept 样本数为 `0`。若 weak-prior 接受率明显高于 strong-prior，说明当前判决较依赖 fitted k sanity gate；若差异很小，则说明 residual shape 和质量条件本身已经提供主要区分力。本轮只量化贡献，不预设 b/k gate 是否合理。

## 5. Ambiguity Set 初步观察

| residual_mode   | candidate_pool   |   top_k |   num_sequences |   num_non_self_best |   num_pairs_in_topk |   median_best_score |   median_score_margin |   weak_only_accept_count |
|:----------------|:-----------------|--------:|----------------:|--------------------:|--------------------:|--------------------:|----------------------:|-------------------------:|
| empirical       | all_sampled      |       5 |               5 |                   0 |                  25 |             27.0589 |               19369.6 |                        0 |

Top ambiguity pairs：

|   true_sat |   claim_sat |   count |   mean_rank |   median_score |   confusion_rate |   accept_count_strong |   accept_count_weak |   range_rate_corr_median |
|-----------:|------------:|--------:|------------:|---------------:|-----------------:|----------------------:|--------------------:|-------------------------:|
|      44714 |       65686 |       1 |           2 |         5127.2 |                1 |                     0 |                   0 |                 0.998691 |
|      65409 |       47383 |       1 |           2 |        19697.8 |                1 |                     0 |                   0 |                 0.99076  |
|      65410 |       47383 |       1 |           2 |        19392.8 |                1 |                     0 |                   0 |                 0.991217 |
|      65421 |       47383 |       1 |           2 |        20426   |                1 |                     0 |                   0 |                 0.989765 |
|      65686 |       48111 |       1 |           2 |        13576.5 |                1 |                     0 |                   0 |                 0.994923 |
|      44714 |       48111 |       1 |           3 |         5155.4 |                1 |                     0 |                   0 |                -0.998518 |
|      65409 |       65693 |       1 |           3 |        19726.1 |                1 |                     0 |                   0 |                 0.986314 |
|      65410 |       65693 |       1 |           3 |        19415   |                1 |                     0 |                   0 |                 0.987561 |
|      65421 |       65693 |       1 |           3 |        20451   |                1 |                     0 |                   0 |                 0.983125 |
|      65686 |       58380 |       1 |           3 |        13658.3 |                1 |                     0 |                   0 |                -0.994395 |

这些 pair 只表示 first-pass top-k 排名中的可混淆候选，不等价于真实攻击成功率。若非 self pair 反复进入 top-k 且 score margin 很小，后续值得做正式 Doppler ambiguity cluster 和阈值敏感性分析。

## 6. 下一步建议

- 如果 best-claim 误接受明显：下一步正式研究 adversarial claim selection。
- 如果 weak-prior 明显更脆弱：下一步重点研究 calibration-free / weak-prior verifier 的安全边界。
- 如果 top-k 混淆明显但未接受：下一步做 Doppler ambiguity cluster 和阈值敏感性。
- 如果全部都很稳：说明单站 Doppler residual 在当前设置下具有较强可识别性，后续应考虑 TLE 误差、短窗口、真实噪声和多物理特征。
