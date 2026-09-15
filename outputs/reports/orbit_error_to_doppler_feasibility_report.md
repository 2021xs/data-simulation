# 公开轨道预测误差 → Doppler / Verifier 最小可行性审计

## 1. 结论先行

本轮状态：`SEMANTIC_BLOCKER_FOUND`。

最终 verdict：`INSUFFICIENT_COVERAGE_FOR_DECISION`。

按照预先给定的停止条件，本轮没有执行轨道传播、Doppler 计算、OLS 拟合或 verifier 判决，也没有生成随机数。原因不是数值失败，而是 frozen population 与 reference 的时间覆盖不相交，并且纯 orbit-only `b_hat/k_hat` 如何进入当前总量 b/k gate 没有冻结语义。继续运行会要求新建科学 population 或自行定义 nominal b/k anchoring，二者均超出本轮授权。

## 2. 已冻结协议

- residual sign convention：`delta_f_orbit_hz = F_ref_hz - F_public_hz`。
- freshness bins：`0-6 h / 6-9 h / 9-12 h / 12-18 h / 18-24 h / 24-36 h`；正式支持域为 `0 < age <= 36 h`。
- aggregation unit：合法 A × frozen segment/time × station；不同 source-provenance 条目或 observation realization 在恢复 station 后去重。
- production score：复用 centered-time OLS 后的 residual RMSE；没有定义新 score。
- thresholds / b/k gate：保持 frozen 值不变；本轮没有修改 verifier。
- reference 语义：SpaceX-E/SupGP higher-quality historical reference，不是 ground truth 或 exact state。

protocol/config hash 见 `outputs/metrics/orbit_error_to_doppler_feasibility_protocol.json` 与 manifest。

## 3. Frozen window coverage

- frozen Level-A units：407；恢复并去重后的 A×segment/time×station analysis units：332。
- 不考虑 station 的唯一 A×segment/time：41；卫星数：10。
- frozen 时间范围：`2026-03-10T01:21:05Z` 至 `2026-03-12T15:32:59Z`。
- reference raw record 时间范围从 2026-04-01 开始；与上述 frozen March 窗口的 overlap units：0/332。
- 在 frozen evaluation time 存在 exact SupGP reference epoch 的 units：0/332。
- 同一 A×segment/time×station 映射到多个 frozen threshold profiles 的 units：62/332；本审计没有任取其一。

### Reference inventory

| month   | directory                                              |   file_count |   record_count | min_epoch                   | max_epoch                   | status    |
|:--------|:-------------------------------------------------------|-------------:|---------------:|:----------------------------|:----------------------------|:----------|
| 2026-04 | data/orbit_uncertainty_stage1/raw/celestrak_supgp      |           20 |           5675 | 2026-04-01T00:04:42.000010Z | 2026-04-30T23:46:42.000010Z | AVAILABLE |
| 2026-05 | data/orbit_uncertainty_stage1/respecialdatarequest (4) |           20 |           6181 | 2026-05-01T00:00:41.999990Z | 2026-05-31T23:55:42.000010Z | AVAILABLE |
| 2026-06 | data/orbit_uncertainty_stage1/june                     |           20 |           5927 | 2026-06-01T00:11:42Z        | 2026-06-30T23:49:41.999981Z | AVAILABLE |

### Freshness coverage（仅 coverage，不含 Doppler 结果）

| freshness_bin   |   frozen_analysis_units |   unique_satellites |   units_with_reference_record_in_window |   units_with_exact_reference_at_evaluation_time |
|:----------------|------------------------:|--------------------:|----------------------------------------:|------------------------------------------------:|
| 0-6 h           |                       1 |                   1 |                                       0 |                                               0 |
| 6-9 h           |                       0 |                   0 |                                       0 |                                               0 |
| 9-12 h          |                      13 |                   4 |                                       0 |                                               0 |
| 12-18 h         |                     304 |                   7 |                                       0 |                                               0 |
| 18-24 h         |                      14 |                   3 |                                       0 |                                               0 |
| 24-36 h         |                       0 |                   0 |                                       0 |                                               0 |

当前 frozen windows 没有 `6-9 h` 和 `24-36 h` 覆盖，且主要集中在 `12-18 h`。即使 reference 时间问题被解决，这个分布也不足以稳定回答 6 个 freshness bins 的单调性或 P99 endpoint。

## 4. Semantic blocker：orbit-only b/k 与 production gate

production centered-time OLS 本身可无歧义复用，`score_orbit` 与 projection absorption diagnostic 也可定义。但 frozen final gate 对总 fitted parameters 判决：

- 322 个 analysis units 启用有限 b gate，b center 为非零的 legitimate effective-bias calibration center；
- 10 个 full-pass provenance analysis units 的 b gate 被禁用；其 k gate 使用 per-target k quantile；
- 其余窗口使用 `current_bk`，b/k gate 作用于总 fitted b/k，而不是 orbit-induced additive delta。

本轮又明确禁止加入 `b_env`、`k_env`、noise。若把 `delta_f_orbit` 直接作为完整 residual，则非零 b center 的 gate failure 主要表示“没有 nominal effective bias”，不能解释为 ordinary-GP/reference disagreement 引起。若人为加上 b/k center，则需要新增一个未冻结的 deterministic anchoring rule，也违反“直接把 orbit-only residual 送入原 verifier”的字面语义。因此 final b/k pass/fail 和 combined decision 暂不可无歧义计算。

此外，62 个去重后的 A×segment/time×station 单位映射到多个 frozen threshold profile；Level-A provenance 没有为本轮合法-A去重单位冻结唯一选择规则。审计仅保存各 profile 的 min/max 与冲突计数，没有任取阈值。

## 5. Q1–Q10 回答状态

1. Q1 raw Doppler 大小：未回答；frozen window 无 matching reference record。
2. Q2 freshness 关系：未回答；无 Doppler output，且两个 freshness bins 为空。
3. Q3 b+kt 吸收比例：未回答；不得凭 Stage-1 state residual 推断 observation-space projection。
4. Q4 score 对 freshness：未回答。
5. Q5 b/k gate 是否触发：未回答；orbit-only additive coefficient 与 total-parameter gate 的 anchoring 未冻结。
6. Q6 rejection attribution：未回答。
7. Q7 verifier 鲁棒性：证据不足，不能声称 robust 或 non-robust。
8. Q8 freshness-aware calibration：当前没有支持证据。
9. Q9 无需新 uncertainty layer：当前也没有支持证据。
10. Q10 geometry vs freshness：未回答；现有窗口 station/geometry 可恢复，但没有 reference-overlap outcome。

## 6. 需要解除的最小 blocker

后续若要重新授权数值实验，至少需要先冻结以下两点：

1. 合法-A evaluation population：在 April/May（exploratory）和 June（confirmatory）内预先选择 existing/frozen pass segments 与 stations，并在看 Doppler 结果前冻结 unit、timestamps、coverage rule 和 exclusions。不得把 SupGP epoch 直接事后当作 pass center。
2. gate perturbation semantics：明确 orbit-only `b_hat_orbit/k_hat_orbit` 是只做 margin diagnostic，还是叠加到哪个预先冻结的 nominal legitimate b/k anchor 后再执行 total b/k gate。两者不能混写。

在此之前，正确停止点是 coverage/semantic audit，而不是建立 freshness-aware threshold。

## 7. 产物与保护检查

- segment dataset 是 blocker/coverage audit；所有 science metric 均为空，`final_verifier_decision=NOT_EVALUATED`。
- 未生成诊断图，因为没有合法的 numeric Doppler output。
- manifest binding 检查：11/11 PASS。
- 未修改 407 Level-A、265-unit joint endpoint、orbit uncertainty 参数、R1/R2/R3/R4、threshold 或 final synthesis。
