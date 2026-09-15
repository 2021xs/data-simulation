# Orbit-distinct 与 Doppler 联合安全分析

## 正式状态

`ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS_COMPLETE`

本轮只分析 R3 已冻结并完成的 407 个 LEVEL-A units / 26,780 observation rows。没有生成新 B、没有新增随机数，也没有修改 causal-A reconstruction、Orbit-Uncertainty、verifier、b/k、threshold 或 R3 population。主分析单位是 `A × B × segment/time`，observation rows 只用于 unit 内 endpoint 与 verifier mechanism。

## 1. Primary result: ORBIT_DISTINCT units

Primary population 为 265 个 `D2>c99` 的 LEVEL-A units。`controlled_observation_acceptance_fraction` 是冻结 observation model 下的 conditional verifier acceptance fraction，不是 attack success rate 或真实世界 probability。

- mean=0.307057, median=0.333333, Q1=0.000000, Q3=0.550000
- P10=0.000000, P90=0.700000, min=0.000000, max=0.966667
- ZERO=67, RARE=37, MIXED=156, HIGH=5, FULL=0
- 明细区间（`DESCRIPTIVE_ONLY`）：0=67; (0,0.1]=37; (0.1,0.5]=80; (0.5,0.9]=77; (0.9,1)=4; 1=0。

198 个 non-zero units 并不等价于 198/265 的“攻击成功率”：其中 37 个仅属 RARE，156 个属 MIXED，5 个属 HIGH，FULL 为 0。

| family_label        |   ORBIT_DISTINCT_units | rho99 median [IQR]            | acceptance median [IQR]   |   zero_acceptance_units |   nonzero_acceptance_units |   high_units |   full_acceptance_units |
|:--------------------|-----------------------:|:------------------------------|:--------------------------|------------------------:|---------------------------:|-------------:|------------------------:|
| Direction           |                     29 | 1.42e+03 [86.2, 1.8e+03]      | 0.040 [0.020, 0.040]      |                       2 |                         27 |            0 |                       0 |
| Altitude            |                    166 | 4.29 [2.14, 10.7]             | 0.500 [0.167, 0.633]      |                      25 |                        141 |            5 |                       0 |
| Multi-pass          |                     40 | 1.64e+03 [1.37e+03, 2.03e+03] | 0.000 [0.000, 0.000]      |                      35 |                          5 |            0 |                       0 |
| Active compensation |                     30 | 1.55e+03 [897, 2.25e+03]      | 0.333 [0.333, 0.333]      |                       5 |                         25 |            0 |                       0 |

## 2. rho99 relationship and boundary robustness

ORBIT_DISTINCT subset 的 rho99: min=1.06823, Q1=3.87705, median=10.7324, Q3=1212.83, P90=1991.58, max=2968.47。rho99 不是概率。

`log10(rho99)` 与 acceptance fraction 的 Spearman rho=-0.750654（n=265，`EXPLORATORY_DESCRIPTIVE`）。该负关联主要由 controlled-altitude 梯度及 family composition 驱动，不能单凭相关系数声称普适单调规律。

远离边界后 acceptance 没有消失：在 `rho99>10` 的 138 units 中，75 个 non-zero，median=0.020000，Q3=0.245833，max=0.600000，其中 3 个 fraction>0.5。即使 `rho99>1000`，仍有 36/68 non-zero，max=0.350000。这些都是 descriptive robustness checks，不是新阈值。

## 3. Physical km and public-orbit normalization

在 ORBIT_DISTINCT units 中，physical separation 与 rho99 高度相关（Spearman rho=0.966256），但二者不能互换。rho99 同时依赖 freshness bin、public RTN direction、该 bin 的中心与协方差、以及 c99；相同数量级 km 会映射到不同标准化距离。数据中 `(100,1000] km` 的 rho99 范围为 1.97 到 86.2。因此 1/5/10 km 是实验因子，不是 orbit-distinctness 判据。

## 4. Direction and RTN anisotropy

Direction family 的 29 个 ORBIT_DISTINCT units 中，rho99 是 unit-level orbit quantity，对同一 unit 的 service-bearing conditions 保持不变；Doppler acceptance 则随冻结的接收/服务几何明显不同。以下是每个 bearing 上先按 unit 聚合后的 condition-level descriptive summary：

| direction_label   |   distinct_LEVEL_A_units |   acceptance_fraction_median |   acceptance_fraction_q1 |   acceptance_fraction_q3 |   nonzero_count |
|:------------------|-------------------------:|-----------------------------:|-------------------------:|-------------------------:|----------------:|
| phi=0 deg         |                       29 |                         0.25 |                    0.125 |                     0.25 |              27 |
| phi=45 deg        |                       29 |                         0    |                    0     |                     0    |               0 |
| phi=90 deg        |                       29 |                         0    |                    0     |                     0    |               1 |
| phi=135 deg       |                       29 |                         0    |                    0     |                     0    |               2 |
| phi=180 deg       |                       29 |                         0    |                    0     |                     0    |               0 |
| phi=225 deg       |                       29 |                         0    |                    0     |                     0    |               0 |
| phi=270 deg       |                       29 |                         0    |                    0     |                     0    |               0 |
| phi=315 deg       |                       29 |                         0    |                    0     |                     0    |               2 |

`phi=0 deg` 的中位 condition fraction 为 0.250，其余多数 bearing 的中位数为 0。说明旧有 Doppler direction sensitivity 在 orbit normalization 后仍存在；它不是 rho99 自身随 receiver direction 改变，而是固定 orbit distinctness 下的 Doppler geometry anisotropy。RTN dominant-direction strata 样本较小，只作解释，不拟合新 direction model。

## 5. Controlled altitude reinterpretation

|   signed_altitude_delta_km |   NOT_ORBIT_DISTINCT_units |   AMBIGUOUS_units |   ORBIT_DISTINCT_units |   distinct_rho99_median |   distinct_acceptance_fraction_median |   distinct_nonzero_acceptance_units |
|---------------------------:|---------------------------:|------------------:|-----------------------:|------------------------:|--------------------------------------:|------------------------------------:|
|                       -100 |                          0 |                 0 |                     20 |                19.3651  |                              0        |                                   3 |
|                        -50 |                          0 |                 0 |                     20 |                 9.68555 |                              0.208333 |                                  18 |
|                        -20 |                          0 |                 0 |                     20 |                 3.87782 |                              0.533333 |                                  20 |
|                        -10 |                          0 |                 0 |                     20 |                 1.94193 |                              0.7      |                                  20 |
|                         -5 |                          0 |                17 |                      3 |                 1.07739 |                              0.866667 |                                   3 |
|                         -2 |                          0 |                20 |                      0 |               nan       |                            nan        |                                   0 |
|                         -1 |                          0 |                20 |                      0 |               nan       |                            nan        |                                   0 |
|                          0 |                         20 |                 0 |                      0 |               nan       |                            nan        |                                   0 |
|                          1 |                          0 |                20 |                      0 |               nan       |                            nan        |                                   0 |
|                          2 |                          0 |                20 |                      0 |               nan       |                            nan        |                                   0 |
|                          5 |                          0 |                17 |                      3 |                 1.06836 |                              0.916667 |                                   3 |
|                         10 |                          0 |                 0 |                     20 |                 1.9306  |                              0.741667 |                                  20 |
|                         20 |                          0 |                 0 |                     20 |                 3.86649 |                              0.575    |                                  20 |
|                         50 |                          0 |                 0 |                     20 |                 9.67422 |                              0.35     |                                  19 |
|                        100 |                          0 |                 0 |                     20 |                19.3538  |                              0.075    |                                  15 |

`delta_h=0` 的 20 units 全部 NOT_ORBIT_DISTINCT；`±1/±2 km` 全部 AMBIGUOUS；`±5 km` 各有 17 AMBIGUOUS 与 3 ORBIT_DISTINCT；从 `|delta_h|>=10 km` 起，本冻结样本的对应 units 全部 ORBIT_DISTINCT。ORBIT_DISTINCT subset 中 acceptance fraction 随绝对高度差总体下降，但正负号、pass 与 receiver-direction conditions 保留明显差异。原 km-distance 规律应重述为：km 是 construction factor，rho99 才是相对于合法 public-orbit uncertainty 的尺度；本样本不支持普适 km 安全阈值。

## 6. Same-pair multi-pass

40/40 passes 均 ORBIT_DISTINCT，来自 10 个 real A/B pairs、每 pair 4 passes。5 pairs 全部 pass 为 zero；另 5 pairs 各只有 1 个 pass non-zero；多个 pass 持续 non-zero 的 pair 为 0，任何 pass fraction>0.5 的 pair 为 0。因此在该冻结样本中，单次过境 Doppler ambiguity 没有跨多个 pass 持续，multi-pass observation 明显削弱了单-pass ambiguity；这仍是 10-pair 条件性结果，不是“永久安全 pair”结论。

## 7. Active compensation

三种 mode 的 30 个 units 在 A/B/time、rho99、b/k/sigma、noise hash 与 point count 上 exact paired，orbit-score mismatch=0。

| comparison     |   paired_LEVEL_A_units |   accepted_units_for_condition |   condition_acceptance_fraction_across_units |
|:---------------|-----------------------:|-------------------------------:|---------------------------------------------:|
| none           |                     30 |                              0 |                                     0        |
| subpoint_A     |                     30 |                              0 |                                     0        |
| direct_S_ideal |                     30 |                             25 |                                     0.833333 |

`none -> subpoint_A` 为 30/30 REJECT->REJECT；`none -> direct_S_ideal` 为 25/30 REJECT->ACCEPT、5/30 REJECT->REJECT。主动补偿效果取决于空间 reference：subpoint-A 没有改变判决，而 direct-S ideal 上界条件明显改变了 Doppler distinguishability。direct-S ideal 不能外推为现实攻击概率或一般 attacker capability。

## 8. Verifier mechanism under current b/k

ORBIT_DISTINCT primary endpoint rows 共 17850，其中 ACCEPT_ALL_GATES_PASS=4530。REJECT 的 exclusive gate combinations 如下；这是 row-level mechanism attribution，不是 primary security weighting：

| gate_attribution      |   observation_row_count |   fraction_of_rejected_rows |
|:----------------------|------------------------:|----------------------------:|
| ACCEPT_ALL_GATES_PASS |                    4530 |                nan          |
| score                 |                     420 |                  0.0315315  |
| b                     |                     231 |                  0.0173423  |
| k                     |                    5133 |                  0.38536    |
| score+b               |                      25 |                  0.00187688 |
| score+k               |                     906 |                  0.068018   |
| b+k                   |                    1188 |                  0.0891892  |
| score+b+k             |                    5417 |                  0.406682   |

最大 exclusive reject mechanism 是 `score+b+k`，其次是 `k only`。仍被 ACCEPT 的 rows 必然同时通过 score/b/k/coverage/quality；多数 accepted rows 的 geometric residual RMSE 本身低于 score threshold，但 multi-pass accepted rows 则显示常数/线性拟合可吸收较大的几何分量。由于 b/k 同时含 frozen environment contribution，本分析不把 `b_hat-b_env` 解释成纯物理真值。

## 9. Orbit-state controls

| orbit_decision     |   all_LEVEL_A_units |   endpoint_available_units |   acceptance_fraction_median |   acceptance_fraction_q1 |   acceptance_fraction_q3 |   nonzero_acceptance_units |
|:-------------------|--------------------:|---------------------------:|-----------------------------:|-------------------------:|-------------------------:|---------------------------:|
| NOT_ORBIT_DISTINCT |                  23 |                          3 |                     0.8      |                 0.4      |                     0.8  |                          2 |
| AMBIGUOUS          |                 119 |                        119 |                     0.833333 |                 0.783333 |                     0.9  |                        118 |
| ORBIT_DISTINCT     |                 265 |                        265 |                     0.333333 |                 0        |                     0.55 |                        198 |
| DEFER              |                   0 |                          0 |                   nan        |               nan        |                   nan    |                          0 |

AMBIGUOUS 与 ORBIT_DISTINCT 的分布明显不同，但 family composition、factor grid 与 observation setup 均不同，因此这里只回答“超出 uncertainty 后 acceptance 是否消失”，不建立 orbit distance 对 Doppler outcome 的因果模型。NOT_ORBIT_DISTINCT 的 23 units 中仅 3 个有 primary endpoint；另外 20 个是 altitude zero reference-only units，不能把 n=3 的分布当成完整 control population。

## 10. Claim hierarchy and decision

直接支持的核心结论是：冻结的 causal-A core population 中，存在 `ORBIT_DISTINCT yet DOPPLER_ACCEPTED` units，而且该现象不只位于 rho99≈1；其强度从 rare 到 high 不等，没有 full-acceptance unit。Direction、altitude、pass 和 compensation 均呈现条件性结构，其中 multi-pass 减少了持续 ambiguity，而 direct-S ideal compensation 显著增加 paired ACCEPT。

不能声称真实 Starlink attack success probability、普适安全距离、所有 LEO 卫星的规律、永久 vulnerable pair、SupGP truth，或 rho99 是概率。

R3 已有 40 个 `0.8<=rho99<=1.2` units，且本轮核心问题可由现有 population 回答。没有因 transition support 不足而启动 R4 的科学必要。

`R4: NOT REQUIRED`

`NEXT STEP: JOINT_SECURITY_RESULT_FREEZE_AND_PAPER_SYNTHESIS`

## 11. Artifacts

Machine-readable summaries、5 张主图、supported-claims table 与 SHA manifest 均写入 `outputs/metrics/`、`outputs/figures/` 和 `outputs/reports/`。完整路径与 hashes 见 `outputs/metrics/orbit_distinct_doppler_joint_analysis_manifest.json`。
