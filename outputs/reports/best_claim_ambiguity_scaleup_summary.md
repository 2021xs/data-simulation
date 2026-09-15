# Best-Claim / Ambiguity 规模扩展总结

生成时间：2026-06-09 22:10

## 1. 实验目的

上一轮 best-claim 多普勒可混淆性 first pass 候选池较小，未发现 non-self best claim。本轮扩大 true_sat 与 claim candidate 规模，验证该结论是否在更大候选池下仍成立。

本轮不继续主动补偿、不做多站、不做完整 open-set 系统。claimed-identity verification 仍是合理基础模型；best-claim 用于评估攻击者可选择声明身份时的最坏情况。

## 2. 运行规模

脚本已改进为逐 sequence incremental write：每处理完一条 `(true_sat, residual_mode)`，立即追加写入 sequence CSV 和 candidate score CSV。新增 `--resume` 可从已有 sequence CSV 跳过已完成序列。

实际数据边界：当前 controlled selection table 只有 20 个受控目标，且 strong/weak 判决需要已有 threshold 与合法 b/k calibration，因此本轮 50/100 true_sat 请求实际落到 20 条 controlled true_sat sequence；all_sampled 的有效 claim pool 上限为当前 20 个已校准 controlled identities。

实际运行命令：

```bash
python -m py_compile scripts/run_best_claim_impersonation_first_pass.py
```

```bash
python scripts/run_best_claim_impersonation_first_pass.py --max-true-sats 50 --max-claim-candidates 100 --candidate-pool visible --residual-mode empirical --top-k 5 --sequence-output outputs/metrics/best_claim_sequence_eval_visible_50x100.csv --summary-output outputs/metrics/best_claim_summary_visible_50x100.csv --candidate-scores-output outputs/datasets/best_claim_candidate_scores_visible_50x100.csv --ambiguity-pairs-output outputs/metrics/doppler_ambiguity_pairs_visible_50x100.csv --ambiguity-summary-output outputs/metrics/doppler_ambiguity_summary_visible_50x100.csv --report-output outputs/reports/best_claim_ambiguity_summary_visible_50x100.md --overwrite
```

```bash
python scripts/run_best_claim_impersonation_first_pass.py --max-true-sats 50 --max-claim-candidates 200 --candidate-pool all_sampled --residual-mode empirical --top-k 5 --sequence-output outputs/metrics/best_claim_sequence_eval_all_sampled_50x200.csv --summary-output outputs/metrics/best_claim_summary_all_sampled_50x200.csv --candidate-scores-output outputs/datasets/best_claim_candidate_scores_all_sampled_50x200.csv --ambiguity-pairs-output outputs/metrics/doppler_ambiguity_pairs_all_sampled_50x200.csv --ambiguity-summary-output outputs/metrics/doppler_ambiguity_summary_all_sampled_50x200.csv --report-output outputs/reports/best_claim_ambiguity_summary_all_sampled_50x200.md --overwrite
```

未继续跑 100x500：在当前数据边界下不会增加有效 true_sat 或 calibrated claim identities，只会重复同一 20 个 claim pool。

## 3. Best-Claim 结果

| candidate_pool | n_sequences | n_candidate_scores | candidates median/min/max | top1_self_rate | top5_self_rate | non_self_best_count | strong_nonself_accept_count | weak_nonself_accept_count | margin median | margin p10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| visible | 20 | 46 | 2 / 1 / 5 | 1.0 | 1.0 | 0 | 0 | 0 | 18389.77 Hz | 5520.26 Hz |
| all_sampled | 20 | 365 | 20 / 2 / 20 | 1.0 | 1.0 | 0 | 0 | 0 | 19516.57 Hz | 4671.36 Hz |

候选池扩大后，真实身份仍稳定排名第一。visible 与 all_sampled 两版均未观察到 non-self best claim，也未观察到 non-self claim 被 strong-prior 或 weak-prior 接受。

all_sampled 的 score margin p10 比 visible 更低，说明候选池扩大后最接近的非 self claim 会更近一些；但当前最接近的非 self score margin 仍为数千 Hz 量级，不属于 verification-level ambiguity。

## 4. Weak-Prior Ablation

visible 与 all_sampled 两版中：

- strong_best_claim_accept_rate = 0.65
- weak_best_claim_accept_rate = 0.70
- weak_only_accept_count = 1
- strong_nonself_accept_count = 0
- weak_nonself_accept_count = 0

weak-prior 比 strong-prior 多接受的样本是 self best claim，不是 non-self claim。因此本轮没有发现“去掉/弱化 k gate 后 non-self best-claim 更容易被接受”的现象。当前 best-claim 风险没有主要依赖 b/k gate 才被压住；非 self claim 主要仍被 residual score 和质量条件拉开。

## 5. Ambiguity Pairs

需要区分两类：

- Ranking-level ambiguity：非真实卫星进入 top-k，但 score 仍明显高，不会通过验证。
- Verification-level ambiguity：非真实卫星进入 top-k，且 score 低到可能 ACCEPT / DEFER。

本轮只观察到 ranking-level ambiguity，未观察到 verification-level ambiguity。

### visible top pairs

按最低 non-self score：

| true_sat | claim_sat | rank | median_score | margin_to_self | corr | strong/weak accept |
|---:|---:|---:|---:|---:|---:|---:|
| 47767 | 48458 | 2 | 5062.08 | 5033.77 | -0.816 | 0 / 0 |
| 65693 | 65411 | 2 | 5543.50 | 5520.26 | 0.951 | 0 / 0 |
| 44714 | 48458 | 2 | 11147.10 | 11124.41 | 0.962 | 0 / 0 |
| 65409 | 65410 | 2 | 20812.61 | 20778.30 | 0.990 | 0 / 0 |
| 65410 | 65409 | 2 | 20956.47 | 20933.27 | 0.990 | 0 / 0 |

### all_sampled top pairs

按最低 non-self score：

| true_sat | claim_sat | rank | median_score | margin_to_self | corr | strong/weak accept |
|---:|---:|---:|---:|---:|---:|---:|
| 65693 | 48672 | 2 | 3980.09 | 3956.85 | 0.999 | 0 / 0 |
| 65693 | 47844 | 3 | 3991.28 | 3968.04 | -0.999 | 0 / 0 |
| 65693 | 48309 | 4 | 3992.36 | 3969.12 | -0.999 | 0 / 0 |
| 48458 | 58380 | 2 | 4110.48 | 4087.43 | -0.999 | 0 / 0 |
| 47767 | 47844 | 2 | 4764.55 | 4736.24 | 0.999 | 0 / 0 |
| 44714 | 65686 | 2 | 5127.20 | 5104.50 | 0.999 | 0 / 0 |

这些 pair 的 range-rate correlation 很高，说明 Starlink / LEO 内部确实存在 Doppler curve shape 层面的相似候选。但它们的 residual score 与 self score 仍相差数千 Hz 到数万 Hz，当前完整窗口 verifier 不接受这些 non-self claim。

## 6. 下一步建议

当前不建议继续盲目扩大同一 controlled calibrated pool，因为 20 个受控目标已经用尽。更有价值的方向是：

1. 短窗口 best-claim：验证局部窗口是否会把 ranking-level ambiguity 推近到 verification-level ambiguity。
2. TLE 误差 / 真实噪声敏感性：检查 self score 上升或非 self margin 缩小时是否会出现 non-self accept。
3. Top-pair 定向分析：对 `65693 -> 48672/47844/48309/48458`、`47767 -> 47844`、`65409 <-> 65410` 等 pair 做不同窗口、不同站点或不同阈值设置的复测。
4. 更大 calibrated claim pool：如果要真正做 50/100/500 claim candidates，需要先为更多 controlled identities 建立合法 thresholds 和 b/k calibration，而不是直接把未校准全星座候选纳入 strong verifier。

结论边界：在当前候选池、完整窗口、empirical residual 和已校准 controlled claim identities 下，未观察到 best-claim verification-level ambiguity；但这不说明 best-claim 攻击不可能，也不代表短窗口、TLE误差或更大校准池下结果必然相同。
