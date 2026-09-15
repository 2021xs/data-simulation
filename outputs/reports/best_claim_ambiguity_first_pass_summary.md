# Best-Claim 多普勒可混淆性 First Pass 总结

生成时间：2026-06-09T21:29:45

## 1. 实验目的

主动补偿攻击已经显示：在完整窗口与单公共补偿假设下，除精确对站上界外较难成功。因此本轮审查另一个更基础的假设：攻击者是否必须固定声称某个 A。本实验把攻击者改为 best-claim/untargeted impersonation：真实卫星 B 生成无主动补偿观测曲线，然后在候选 claim identity 中选择 residual score 最低的 A_best。

## 2. 实验设置

- true_sat 数量：`10`
- max claim candidates：`100`
- candidate_pool：`visible`
- residual_mode：`empirical`
- top-k：`5`
- strong-prior：`score <= per-target p95 threshold` 且 `k_hat` 落入该 claim 的合法样本 p01/p99 范围，并满足过境质量条件。
- weak-prior：`score <= per-target p95 threshold` 且满足过境质量条件，不使用 b/k gate 直接拒绝。

当前 first pass 的 claim identities 限定在已有合法 threshold 与合法 b/k calibration 的 controlled target 集合内；`visible` pool 会用项目 SGP4/geo_curve 逻辑补算候选在同一时间网格上的最大仰角。

输出文件：

- `outputs\metrics\best_claim_sequence_eval.csv`
- `outputs\metrics\best_claim_summary.csv`
- `outputs\datasets\best_claim_candidate_scores.csv`
- `outputs\metrics\doppler_ambiguity_pairs.csv`
- `outputs\metrics\doppler_ambiguity_summary.csv`

## 3. Best-Claim 结果

| candidate_pool   | residual_mode   |   n |   top1_self_rate |   top5_self_rate |   best_claim_accept_rate |   best_claim_defer_rate |   best_claim_reject_rate |   strong_best_claim_accept_rate |   weak_best_claim_accept_rate |   accept_rate_gap |   weak_only_accept_count |   score_margin_median |   score_margin_p10 |   true_sat_rank_median |   num_claim_candidates_median |   non_self_best_count |
|:-----------------|:----------------|----:|-----------------:|-----------------:|-------------------------:|------------------------:|-------------------------:|--------------------------------:|------------------------------:|------------------:|-------------------------:|----------------------:|-------------------:|-----------------------:|------------------------------:|----------------------:|
| visible          | empirical       |  10 |                1 |                1 |                      0.8 |                     0.1 |                      0.1 |                             0.8 |                           0.8 |                 0 |                        0 |               20778.3 |            11540.6 |                      1 |                             2 |                     0 |

非真实卫星成为 best claim 的序列数为 `0`。`score_margin = second_best_score - best_score`，margin 越小表示 top candidates 越接近。

补充 all_sampled 小规模对照使用 5 条 true_sat 序列、每条 20 个已有校准 claim candidates。结果为 `top1_self_rate = 1.0`、`top5_self_rate = 1.0`、`strong_best_claim_accept_rate = 0.6`、`weak_best_claim_accept_rate = 0.6`、`non_self_best_count = 0`、score margin median 约 `19369.63 Hz`。这说明候选池扩大到当前 controlled calibrated set 后，仍未观察到非真实身份成为 best claim。

## 4. Weak-Prior Ablation 结果

weak-only accept 样本数为 `0`。若 weak-prior 接受率明显高于 strong-prior，说明当前判决较依赖 fitted k sanity gate；若差异很小，则说明 residual shape 和质量条件本身已经提供主要区分力。本轮只量化贡献，不预设 b/k gate 是否合理。

本轮 visible 与 all_sampled 两版中，strong-prior 与 weak-prior 接受率相同，accept_rate_gap 均为 `0`。因此在当前 controlled claim pool、完整窗口和 empirical residual 下，best-claim 风险没有主要依赖 k gate 才被压住；未发现 residual score 很低但仅因 k_hat 不合理而被 strong-prior 拒绝的 best-claim 样本。

## 5. Ambiguity Set 初步观察

| residual_mode   | candidate_pool   |   top_k |   num_sequences |   num_non_self_best |   num_pairs_in_topk |   median_best_score |   median_score_margin |   weak_only_accept_count |
|:----------------|:-----------------|--------:|----------------:|--------------------:|--------------------:|--------------------:|----------------------:|-------------------------:|
| empirical       | visible          |       5 |              10 |                   0 |                  26 |             24.8543 |               20778.3 |                        0 |

Top ambiguity pairs：

|   true_sat |   claim_sat |   count |   mean_rank |   median_score |   confusion_rate |   accept_count_strong |   accept_count_weak |   range_rate_corr_median |
|-----------:|------------:|--------:|------------:|---------------:|-----------------:|----------------------:|--------------------:|-------------------------:|
|      44714 |       48458 |       1 |           2 |        11147.1 |                1 |                     0 |                   0 |                 0.96226  |
|      47749 |       48309 |       1 |           2 |        32713.3 |                1 |                     0 |                   0 |                 0.97767  |
|      65409 |       65410 |       1 |           2 |        20812.6 |                1 |                     0 |                   0 |                 0.989601 |
|      65410 |       65409 |       1 |           2 |        20956.5 |                1 |                     0 |                   0 |                 0.989507 |
|      65411 |       47749 |       1 |           2 |        11842.9 |                1 |                     0 |                   0 |                -0.408769 |
|      65421 |       65405 |       1 |           2 |        35982.1 |                1 |                     0 |                   0 |                 0.878328 |
|      65686 |       65405 |       1 |           2 |        16834.1 |                1 |                     0 |                   0 |                 0.921168 |
|      65409 |       65421 |       1 |           3 |        38993.3 |                1 |                     0 |                   0 |                 0.955166 |
|      65410 |       65405 |       1 |           3 |        32135.1 |                1 |                     0 |                   0 |                 0.971516 |
|      65421 |       65409 |       1 |           3 |        38588.8 |                1 |                     0 |                   0 |                 0.955985 |

这些 pair 只表示 first-pass top-k 排名中的可混淆候选，不等价于真实攻击成功率。若非 self pair 反复进入 top-k 且 score margin 很小，后续值得做正式 Doppler ambiguity cluster 和阈值敏感性分析。

可见池中存在若干非 self top-k pair，例如 `65409 -> 65410` 和 `65410 -> 65409`，range-rate correlation 约 `0.99`，说明相近过境几何下确实存在 ranking-level 的 Doppler 相似性。但这些非 self 候选的 residual score 仍为万 Hz 量级，且 strong/weak 均未接受。all_sampled 中也出现高相关非 self top-k 候选，但不少 claim 在该窗口最大仰角为负，属于几何曲线形状相似但不可见或质量不满足的候选。

## 6. 下一步建议

- 如果 best-claim 误接受明显：下一步正式研究 adversarial claim selection。
- 如果 weak-prior 明显更脆弱：下一步重点研究 calibration-free / weak-prior verifier 的安全边界。
- 如果 top-k 混淆明显但未接受：下一步做 Doppler ambiguity cluster 和阈值敏感性。
- 如果全部都很稳：说明单站 Doppler residual 在当前设置下具有较强可识别性，后续应考虑 TLE 误差、短窗口、真实噪声和多物理特征。
