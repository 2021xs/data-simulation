# Short-Window Best-Claim / Ambiguity First Pass

## 0. 人工摘要

本轮使用 `all_sampled` candidate pool、20 个 controlled true_sat、最多 200 个 claim candidates（当前有效 calibrated claim pool 为 20 个），在完整窗口、固定短窗口和滑动 best-duration 窗口下做 best-claim ranking。

核心结果：

| window_mode | duration_s | n_sequences | top1_self_rate | top5_self_rate | non_self_best_count | strong_nonself_accept_count | weak_nonself_accept_count | margin_median_hz | margin_p10_hz | margin_min_hz |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_pass | full | 20 | 1.000 | 1.000 | 0 | 0 | 0 | 19516.57 | 4671.36 | 3956.85 |
| fixed_duration | 30 | 60 | 0.967 | 0.983 | 2 | 0 | 0 | 89.14 | 5.06 | -1.98 |
| fixed_duration | 60 | 60 | 1.000 | 1.000 | 0 | 0 | 0 | 458.43 | 131.90 | 51.49 |
| fixed_duration | 120 | 60 | 1.000 | 1.000 | 0 | 0 | 0 | 2644.15 | 1092.44 | 531.78 |
| fixed_duration | 180 | 60 | 1.000 | 1.000 | 0 | 0 | 0 | 7164.70 | 2477.94 | 1690.79 |
| best_duration | 30 | 20 | 0.850 | 0.950 | 3 | 0 | 2 | 10.04 | -0.68 | -1.93 |
| best_duration | 60 | 20 | 1.000 | 1.000 | 0 | 0 | 0 | 144.15 | 66.66 | 57.94 |
| best_duration | 120 | 20 | 1.000 | 1.000 | 0 | 0 | 0 | 1211.58 | 597.97 | 543.26 |
| best_duration | 180 | 20 | 1.000 | 1.000 | 0 | 0 | 0 | 3500.77 | 1786.90 | 1626.79 |

短窗口显著压缩 self 与 best non-self 的 score margin：完整窗口 margin median 为约 `19.5 kHz`，60s best-duration 降至约 `144 Hz`，30s best-duration 降至约 `10 Hz`。30s fixed/best 窗口出现 non-self best claim，说明 ranking-level ambiguity 在短窗口下被明显放大。

verification-level 观察：

- strong-prior 下没有 non-self accept。
- weak-prior 下出现 2 个 30s best-duration non-self accept，分别是 `65409 -> 65410` 和 `65410 -> 65409`。
- 这说明弱化 k gate 后，极短窗口可能把部分邻近/相似 Doppler pair 推近到 verification-level ambiguity；但这只是在当前 controlled pool、30s best-window 搜索、weak-prior 条件下观察到的边界现象。

具体 non-self best cases：

| sequence_id | true_sat | mode | duration_s | window | best_nonself | self_score | nonself_score | margin |
|---|---:|---|---:|---|---:|---:|---:|---:|
| sw_best_claim_000122 | 65411 | fixed_duration | 30 | middle | 47749 | 23.67 | 23.05 | -0.63 |
| sw_best_claim_000133 | 65411 | best_duration | 30 | best_015 | 47749 | 23.67 | 23.05 | -0.63 |
| sw_best_claim_000286 | 65693 | best_duration | 30 | best_012 | 47749 | 28.92 | 26.99 | -1.93 |
| sw_best_claim_000326 | 48458 | fixed_duration | 30 | middle | 58380 | 23.07 | 21.09 | -1.98 |
| sw_best_claim_000337 | 48458 | best_duration | 30 | best_011 | 58380 | 22.77 | 21.59 | -1.18 |

具体 weak-prior non-self accept cases：

| sequence_id | true_sat | mode | duration_s | window | best_nonself | self_score | nonself_score | margin | strong_nonself | weak_nonself |
|---|---:|---|---:|---|---:|---:|---:|---:|---|---|
| sw_best_claim_000065 | 65409 | best_duration | 30 | best_022 | 65410 | 30.80 | 32.61 | 1.81 | false | true |
| sw_best_claim_000082 | 65410 | best_duration | 30 | best_012 | 65409 | 21.37 | 28.61 | 7.24 | false | true |

结论边界：短窗口不是最终身份判定协议，而是可识别性边界测试。当前结果支持后续进入 top ambiguity pair 的定向分析，尤其是 30s 窗口下的 `65409 <-> 65410`、`65411 -> 47749`、`48458 -> 58380`、`65693 -> 47749` 等 pair。若未来 verifier 面对很短窗口，应倾向输出 DEFER，而不是直接 ACCEPT。

生成时间：2026-06-09T22:21:19

## 1. 实验目的

完整窗口 best-claim 实验中，真实身份稳定 top-1，未发现 non-self accept。本轮测试窗口缩短后，多普勒身份可区分性是否下降，以及 ranking-level ambiguity 是否会放大为 verification-level ambiguity。

## 2. 实验设置

- max_true_sats：`20`
- candidate_pool：`all_sampled`
- max_claim_candidates：`200`
- residual_mode：`empirical`
- window_mode：`full_pass, fixed_duration, best_duration`
- window_duration_s：`30.0, 60.0, 120.0, 180.0`
- window_step_s：`10.0`
- strong-prior：score + per-target k gate + quality gate
- weak-prior：score + quality gate，不用 b/k gate 直接拒绝
- incremental write：每条窗口 sequence 完成后追加写入 sequence/candidate CSV

输出文件：

- `outputs\metrics\short_window_best_claim_sequence_eval.csv`
- `outputs\datasets\short_window_best_claim_candidate_scores.csv`
- `outputs\metrics\short_window_doppler_ambiguity_pairs.csv`
- `outputs\metrics\short_window_doppler_ambiguity_summary.csv`

## 3. 短窗口 Best-Claim 结果

| candidate_pool   | residual_mode   | window_mode    |   window_duration_s |   n_sequences |   n_candidate_scores |   num_claim_candidates_median |   top1_self_rate |   top5_self_rate |   non_self_best_count |   non_self_best_rate |   strong_nonself_accept_count |   weak_nonself_accept_count |   weak_only_nonself_accept_count |   self_score_median |   best_nonself_score_median |   score_margin_self_to_best_nonself_median |   score_margin_self_to_best_nonself_p10 |   score_margin_self_to_best_nonself_min |
|:-----------------|:----------------|:---------------|--------------------:|--------------:|---------------------:|------------------------------:|-----------------:|-----------------:|----------------------:|---------------------:|------------------------------:|----------------------------:|---------------------------------:|--------------------:|----------------------------:|-------------------------------------------:|----------------------------------------:|----------------------------------------:|
| all_sampled      | empirical       | best_duration  |                  30 |            20 |                  365 |                            20 |         0.85     |         0.95     |                     3 |            0.15      |                             0 |                           2 |                                2 |             27.2336 |                     37.6041 |                                    10.044  |                                -0.6816  |                                -1.9345  |
| all_sampled      | empirical       | best_duration  |                  60 |            20 |                  365 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.3092 |                    170.702  |                                   144.153  |                                66.6587  |                                57.9434  |
| all_sampled      | empirical       | best_duration  |                 120 |            20 |                  365 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.0397 |                   1237.72   |                                  1211.58   |                               597.969   |                               543.262   |
| all_sampled      | empirical       | best_duration  |                 180 |            20 |                  365 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.6453 |                   3526.93   |                                  3500.77   |                              1786.9     |                              1626.79    |
| all_sampled      | empirical       | fixed_duration |                  30 |            60 |                 1095 |                            20 |         0.966667 |         0.983333 |                     2 |            0.0333333 |                             0 |                           0 |                                0 |             25.8335 |                    112.068  |                                    89.1406 |                                 5.05624 |                                -1.98015 |
| all_sampled      | empirical       | fixed_duration |                  60 |            60 |                 1095 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.6418 |                    488.817  |                                   458.432  |                               131.905   |                                51.4918  |
| all_sampled      | empirical       | fixed_duration |                 120 |            60 |                 1095 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.8232 |                   2669.17   |                                  2644.15   |                              1092.44    |                               531.785   |
| all_sampled      | empirical       | fixed_duration |                 180 |            60 |                 1095 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             25.5955 |                   7190.33   |                                  7164.7    |                              2477.94    |                              1690.79    |
| all_sampled      | empirical       | full_pass      |                 248 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             23.2427 |                   3980.09   |                                  3956.85   |                              3956.85    |                              3956.85    |
| all_sampled      | empirical       | full_pass      |                 251 |             1 |                    2 |                             2 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             23.0562 |                   4110.48   |                                  4087.43   |                              4087.43    |                              4087.43    |
| all_sampled      | empirical       | full_pass      |                 264 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             28.3067 |                   4764.55   |                                  4736.24   |                              4736.24    |                              4736.24    |
| all_sampled      | empirical       | full_pass      |                 267 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             22.6936 |                   5127.2    |                                  5104.5    |                              5104.5     |                              5104.5     |
| all_sampled      | empirical       | full_pass      |                 330 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             24.7984 |                  10908.1    |                                 10883.3    |                             10883.3     |                             10883.3     |
| all_sampled      | empirical       | full_pass      |                 343 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             28.6032 |                  13576.5    |                                 13547.9    |                             13547.9     |                             13547.9     |
| all_sampled      | empirical       | full_pass      |                 346 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             24.6444 |                  14221.7    |                                 14197.1    |                             14197.1     |                             14197.1     |
| all_sampled      | empirical       | full_pass      |                 360 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             26.677  |                  16905      |                                 16878.4    |                             16878.4     |                             16878.4     |
| all_sampled      | empirical       | full_pass      |                 369 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             27.7971 |                  18831.8    |                                 18804      |                             18804       |                             18804       |
| all_sampled      | empirical       | full_pass      |                 371 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             23.1982 |                  19392.8    |                                 19369.6    |                             19369.6     |                             19369.6     |
| all_sampled      | empirical       | full_pass      |                 372 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             34.3145 |                  19697.8    |                                 19663.5    |                             19663.5     |                             19663.5     |
| all_sampled      | empirical       | full_pass      |                 375 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             27.0589 |                  20426      |                                 20399      |                             20399       |                             20399       |
| all_sampled      | empirical       | full_pass      |                 376 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             32.8964 |                  20547.8    |                                 20514.9    |                             20514.9     |                             20514.9     |
| all_sampled      | empirical       | full_pass      |                 386 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             30.8655 |                  23733.8    |                                 23703      |                             23703       |                             23703       |
| all_sampled      | empirical       | full_pass      |                 404 |             1 |                    3 |                             3 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             33.4845 |                  29608      |                                 29574.5    |                             29574.5     |                             29574.5     |
| all_sampled      | empirical       | full_pass      |                 408 |             1 |                   20 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             24.9688 |                  31348.2    |                                 31323.2    |                             31323.2     |                             31323.2     |
| all_sampled      | empirical       | full_pass      |                 410 |             2 |                   40 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             24.2865 |                  32668.8    |                                 32644.5    |                             32609.4     |                             32600.6     |
| all_sampled      | empirical       | full_pass      |                 444 |             2 |                   40 |                            20 |         1        |         1        |                     0 |            0         |                             0 |                           0 |                                0 |             26.6011 |                  57072.4    |                                 57045.8    |                             56873.5     |                             56830.4     |

如果短窗口出现 non-self best 或 non-self accept，应进入定向 ambiguity cluster 分析。如果只是 margin 变小但未接受，说明仍停留在 ranking-level ambiguity。

## 4. Ambiguity Pair 结果

Top pairs by count_in_topk：

|   true_sat |   claim_sat |   window_duration_s |   count_in_topk |   count_as_nonself_best |   mean_rank |   median_score |   median_score_margin_to_self |   median_range_rate_corr |   strong_accept_count |   weak_accept_count |
|-----------:|------------:|--------------------:|----------------:|------------------------:|------------:|---------------:|------------------------------:|-------------------------:|----------------------:|--------------------:|
|      48458 |       58380 |                  30 |               4 |                       4 |        1.5  |       137.113  |                      115.775  |                -0.999827 |                     0 |                   0 |
|      48111 |       47383 |                 120 |               4 |                       4 |        2    |      3407.31   |                     3383.76   |                 0.99082  |                     0 |                   0 |
|      48458 |       58380 |                  60 |               4 |                       4 |        2    |       483.168  |                      459.477  |                -0.99943  |                     0 |                   0 |
|      48458 |       58380 |                 120 |               4 |                       4 |        2    |      1720.82   |                     1697.42   |                -0.998759 |                     0 |                   0 |
|      48458 |       58380 |                 180 |               4 |                       4 |        2    |      2835.99   |                     2812.15   |                -0.998944 |                     0 |                   0 |
|      65411 |       58380 |                  60 |               4 |                       4 |        2    |       489.886  |                      466.422  |                 0.999251 |                     0 |                   0 |
|      65411 |       58380 |                 120 |               4 |                       4 |        2    |      2426.51   |                     2402.41   |                 0.997591 |                     0 |                   0 |
|      48111 |       47383 |                 180 |               4 |                       3 |        2.25 |     10717.1    |                    10692      |                 0.981078 |                     0 |                   0 |
|      65411 |       58380 |                 180 |               4 |                       3 |        2.25 |      5496.64   |                     5471.71   |                 0.9969   |                     0 |                   0 |
|      65407 |       65686 |                  30 |               4 |                       3 |        2.75 |        96.4553 |                       75.5709 |                 0.999709 |                     0 |                   0 |
|      48309 |       45230 |                  60 |               4 |                       2 |        2.5  |       256.526  |                      229.932  |                 0.993412 |                     0 |                   0 |
|      58380 |       48458 |                  30 |               4 |                       2 |        2.5  |       126.521  |                       93.9206 |                -0.999419 |                     0 |                   0 |
|      58380 |       48458 |                  60 |               4 |                       2 |        2.5  |       544.409  |                      512.884  |                -0.997623 |                     0 |                   0 |
|      58380 |       48458 |                 120 |               4 |                       2 |        2.5  |      3389.54   |                     3356.99   |                -0.990133 |                     0 |                   0 |
|      58380 |       48458 |                 180 |               4 |                       2 |        2.5  |     10364.4    |                    10332      |                -0.980902 |                     0 |                   0 |
|      58380 |       60265 |                  30 |               4 |                       2 |        2.5  |       127.085  |                       92.4162 |                -0.999532 |                     0 |                   0 |
|      58380 |       60265 |                  60 |               4 |                       2 |        2.5  |       546.303  |                      511.388  |                -0.998025 |                     0 |                   0 |
|      58380 |       60265 |                 120 |               4 |                       2 |        2.5  |      3405.02   |                     3370.65   |                -0.991582 |                     0 |                   0 |
|      58380 |       60265 |                 180 |               4 |                       2 |        2.5  |     10407.9    |                    10373.2    |                -0.983493 |                     0 |                   0 |
|      48111 |       65421 |                  30 |               4 |                       2 |        3    |        93.4085 |                       69.322  |                 0.999591 |                     0 |                   0 |

Top pairs by lowest median_score：

|   true_sat |   claim_sat |   window_duration_s |   count_in_topk |   count_as_nonself_best |   mean_rank |   median_score |   median_score_margin_to_self |   median_range_rate_corr |   strong_accept_count |   weak_accept_count |
|-----------:|------------:|--------------------:|----------------:|------------------------:|------------:|---------------:|------------------------------:|-------------------------:|----------------------:|--------------------:|
|      65411 |       47749 |                  30 |               3 |                       2 |     2       |        23.0469 |                     -0.626497 |                -0.995889 |                     0 |                   0 |
|      65411 |       45230 |                  30 |               2 |                       0 |     2       |        23.2818 |                     -0.391628 |                -0.999988 |                     0 |                   0 |
|      65411 |       47844 |                  30 |               2 |                       0 |     3       |        23.2944 |                     -0.378972 |                -0.999997 |                     0 |                   0 |
|      65411 |       47767 |                  30 |               2 |                       0 |     4       |        23.3378 |                     -0.335562 |                -0.999998 |                     0 |                   0 |
|      65411 |       44714 |                  30 |               2 |                       0 |     5       |        23.3888 |                     -0.284574 |                -0.999998 |                     0 |                   0 |
|      65693 |       47844 |                  30 |               1 |                       0 |     5       |        27.4966 |                      4.16691  |                -0.999997 |                     0 |                   0 |
|      44714 |       65693 |                  30 |               1 |                       1 |     2       |        28.3563 |                      6.42948  |                -0.999971 |                     0 |                   0 |
|      44714 |       47383 |                  30 |               1 |                       0 |     4       |        28.5219 |                      6.5951   |                -0.999998 |                     0 |                   0 |
|      44714 |       48111 |                  30 |               1 |                       0 |     5       |        28.5433 |                      6.61648  |                -0.999999 |                     0 |                   0 |
|      47767 |       48458 |                  30 |               2 |                       0 |     3.5     |        29.1879 |                      1.65756  |                -0.998078 |                     0 |                   0 |
|      47767 |       65407 |                  30 |               2 |                       1 |     3       |        29.5616 |                      2.03121  |                -0.999967 |                     0 |                   0 |
|      47767 |       48111 |                  30 |               1 |                       0 |     5       |        29.7524 |                      1.06717  |                -0.999999 |                     0 |                   0 |
|      65410 |       58380 |                  30 |               1 |                       0 |     3       |        31.6902 |                     10.7494   |                -0.999942 |                     0 |                   0 |
|      65410 |       65411 |                  30 |               1 |                       0 |     4       |        32.0032 |                     11.0624   |                -0.999988 |                     0 |                   0 |
|      48309 |       47749 |                  30 |               3 |                       2 |     2.33333 |        32.9003 |                     10.1058   |                 0.998912 |                     0 |                   0 |
|      47844 |       47749 |                  30 |               1 |                       1 |     2       |        33.2957 |                      7.94197  |                -0.999997 |                     0 |                   0 |
|      47844 |       58380 |                  30 |               1 |                       0 |     3       |        33.3    |                      7.94631  |                -0.999998 |                     0 |                   0 |
|      47844 |       65411 |                  30 |               1 |                       0 |     5       |        33.3069 |                      7.95315  |                -0.999998 |                     0 |                   0 |
|      65686 |       65693 |                  30 |               1 |                       0 |     5       |        34.2752 |                      5.35571  |                -0.999997 |                     0 |                   0 |
|      47383 |       44714 |                  30 |               2 |                       0 |     5       |        35.0499 |                      7.16961  |                -0.999918 |                     0 |                   0 |

## 5. 结论与下一步

短窗口是可识别性边界测试，不应直接作为最终身份判定。如果短窗口不稳定，最终 verifier 对短窗口应倾向输出 DEFER，而不是 ACCEPT。后续方向根据本轮结果选择：ambiguity cluster 定向分析、open-set unknown rejection，或 TLE误差 / 真实噪声敏感性。
