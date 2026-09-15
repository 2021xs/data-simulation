# Joint-security final results freeze and paper synthesis

## 正式状态

`JOINT_SECURITY_RESULTS_FROZEN`

`EXPERIMENTAL MAINLINE: COMPLETE`

`ORBIT MODEL OPTIMIZATION: STOPPED`

`DOPPLER PIPELINE OPTIMIZATION: STOPPED`

`R4: NOT REQUIRED`

本文件把已经完成的 Orbit-Uncertainty、causal-A reconstruction 和 joint-security evidence 固化为论文可引用的 numbers、claims、figures、tables、terminology 与 limitations。本轮没有运行新实验、传播新轨道、生成 candidate B、执行 verifier、增加 Monte Carlo、拟合模型或调整阈值。

## 1. Frozen paper question

最终主问题：当 candidate/non-target satellite B 已超出 claimed satellite A 的 legitimate, freshness-conditioned public-orbit prediction uncertainty 后，single-station Doppler claimed-satellite verifier 是否仍存在 ambiguity？

Security-relevant joint state 为 `ORBIT_DISTINCT + DOPPLER_ACCEPTED`。ACCEPT 只表示 controlled observation model 下的 verifier outcome；primary response 是 LEVEL-A unit 内的 `conditional verifier acceptance fraction`，不是 attack success probability。

## 2. Three paper contributions

1. 提出 uncertainty-aware claimed-satellite security evaluation framework，用同一 causal public orbit prediction A 区分 physical separation、legitimate public-orbit uncertainty 与 security-relevant orbit distinctness。
2. 构建并冻结 freshness-conditioned signed 3D RTN empirical uncertainty set；April+May 拟合的 ellipsoid 在 untouched June 的 P99 legitimate reference-relative coverage 为 `5360/5389 = 0.994619`，satellite-cluster interval 为 `[0.989915, 0.998530]`。这为 downstream orbit gate 提供 transfer evidence，而不是 ground-truth orbit covariance。
3. 在 result-blind、causal-A-aligned core experiments 中表明：orbit distinctness 不自动产生 Doppler distinguishability；rho99、receiver geometry/direction、pass 与 ideal compensation condition 共同界定 single-station verifier boundary。

贡献 2 是 supporting method，贡献 3 是论文结果主线。Orbit-Uncertainty 建议占 Methods+Results 核心篇幅约 20%-25%，用一个方法小节、一个精简 validation table 和必要的 supplement 支撑，而不展开全部 Stage-1 分支。

## 3. Core frozen numbers

- Orbit gate validation: `5360/5389 = 0.994619`，cluster interval `[0.989915, 0.998530]`；April/May/June T-dominance `April/May/June = 0.962204/0.962094/0.972351`。
- Primary joint endpoint: 265 ORBIT_DISTINCT LEVEL-A units；mean `0.307057`，median[IQR] `0.3333333333333333 [0.0, 0.55]`；ZERO/RARE/MIXED/HIGH/FULL=`67/37/156/5/0`。
- Non-zero existence: `198/265` units；这不是 attack success rate。
- Far-boundary evidence: rho99>10 为 `75/138 non-zero; median=0.02; max=0.6`；rho99>1000 为 `36/68 non-zero; median=0.02; max=0.35`。Acceptance 明显降低但未消失。
- Conditional boundaries: multi-pass persistence `0/10 pairs`；active compensation `none=0/30; subpoint-A=0/30; direct-S ideal=25/30`。

## 4. Proposed claim adjudication

| CLAIM_ID                            | proposed_claim_adjudication   | allowed_wording                                                                                                                   |
|:------------------------------------|:------------------------------|:----------------------------------------------------------------------------------------------------------------------------------|
| C1_ORBIT_DISTINCT_ACCEPTANCE_EXISTS | SUPPORTED                     | Orbit-distinct yet Doppler-accepted units exist in the frozen causal-A core population.                                           |
| C2_AMBIGUITY_DECAYS_WITH_RHO99      | SUPPORTED_WITH_LIMITATION     | In the frozen population, acceptance generally decreased with rho99 but persisted well beyond the boundary.                       |
| C3_KM_NOT_ORBIT_GATE                | SUPPORTED                     | Fixed physical distance does not imply fixed orbit distinctness under the frozen uncertainty gate.                                |
| C4_DIRECTION_GEOMETRY_EFFECT        | SUPPORTED_WITH_LIMITATION     | Doppler acceptance retained direction and receiver-geometry dependence after orbit normalization in the studied direction family. |
| C5_MULTIPASS_REDUCES_PERSISTENCE    | SUPPORTED_WITH_LIMITATION     | In the studied real pairs, requiring repeatability across passes reduced single-pass ambiguity.                                   |
| C6_DIRECT_S_IDEAL_BOUND             | SUPPORTED_WITH_LIMITATION     | The direct-S ideal upper-bound condition changed 25/30 paired decisions from REJECT to ACCEPT, unlike subpoint-A.                 |

Claim 1 和 Claim 3 可直接支持。Claim 2、4、5、6 必须使用 matrix 中的限定措辞；特别是 Spearman 属 `EXPLORATORY_DESCRIPTIVE`，direction 属 condition-level descriptive，multi-pass 只有 10 pairs，direct-S ideal 是 receiver-specific upper bound。

## 5. Claim hierarchy

### Directly supported

| CLAIM_ID                            | allowed_wording                                                                                                      | supporting_metric                                                                                          |
|:------------------------------------|:---------------------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------|
| C1_ORBIT_DISTINCT_ACCEPTANCE_EXISTS | Orbit-distinct yet Doppler-accepted units exist in the frozen causal-A core population.                              | 198/265 units have acceptance_fraction>0; ZERO/RARE/MIXED/HIGH/FULL=67/37/156/5/0                          |
| C3_KM_NOT_ORBIT_GATE                | Fixed physical distance does not imply fixed orbit distinctness under the frozen uncertainty gate.                   | Within (100,1000] km, rho99 ranges 1.97 to 86.2; gate depends on freshness, signed RTN, covariance and c99 |
| OU2_RTN_ANISOTROPY                  | Signed RTN representation retains replicated directional structure omitted by a norm-only sphere.                    | T dominance April/May/June=96.2204%/96.2094%/97.2351%                                                      |
| OU3_UNTOUCHED_JUNE_P99              | The frozen empirical P99 gate achieved 99.4619% legitimate reference-relative joint coverage on untouched June.      | 5360/5389=99.4619%; satellite-cluster CI 98.9915%-99.8530%                                                 |
| M1_RECONSTRUCTION_EQUIVALENCE       | When A/B/time/randomness semantics are fixed, the reconstruction wrapper reproduces authoritative verifier behavior. | 64/64 units and 6280/6280 rows; all categorical mismatches=0; verifier-v2 200/200                          |

### Supported with limitation

| CLAIM_ID                         | allowed_wording                                                                                                                   | limitation                                                                                                                |
|:---------------------------------|:----------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------|
| C2_AMBIGUITY_DECAYS_WITH_RHO99   | In the frozen population, acceptance generally decreased with rho99 but persisted well beyond the boundary.                       | Association is influenced by controlled-altitude gradient and family composition; no causal or universal monotonic model. |
| C4_DIRECTION_GEOMETRY_EFFECT     | Doppler acceptance retained direction and receiver-geometry dependence after orbit normalization in the studied direction family. | Condition-level descriptive result; RTN dominant-direction strata are small; no formal hypothesis test.                   |
| C5_MULTIPASS_REDUCES_PERSISTENCE | In the studied real pairs, requiring repeatability across passes reduced single-pass ambiguity.                                   | Limited pairs/passes and geometry; descriptive repeatability, not a guarantee.                                            |
| C6_DIRECT_S_IDEAL_BOUND          | The direct-S ideal upper-bound condition changed 25/30 paired decisions from REJECT to ACCEPT, unlike subpoint-A.                 | Direct-S ideal is an idealized receiver-specific upper-bound capability; not operational feasibility.                     |
| OU1_FRESHNESS_CONDITIONING       | Element age is a supported conditioning variable for this empirical disagreement scale.                                           | Not strictly rowwise monotonic; reference-relative disagreement only.                                                     |

`198/265` 只能作为“至少一个 controlled realization 被 ACCEPT 的 unit existence count”。论文强度应由完整 fraction distribution 描述：67 ZERO、37 RARE、156 MIXED、5 HIGH、0 FULL。

## 6. Paper story and section structure

故事线保持单一：physical orbit distance 会混淆 true physical difference 与 legitimate public-orbit prediction uncertainty；frozen empirical RTN ellipsoid 先判定 B 是否真正 orbit-distinct；随后用同一 causal A 驱动 Doppler verifier，并研究 orbit-distinct yet Doppler-accepted joint state。

建议 Results：

1. `5.1 Legitimate public-orbit uncertainty`：只保留 freshness dependence、RTN anisotropy、untouched June P99 transfer 与 P95 limitation。
2. `5.2 From physical separation to orbit distinctness`：展示 km 与 rho99 不等价。
3. `5.3 Doppler distinguishability beyond legitimate orbit uncertainty`：265-unit distribution、rho99 relationship 与 far-boundary checks，作为正文中心。
4. `5.4 Geometry and direction dependence`：controlled altitude 和 service-bearing condition。
5. `5.5 Temporal repeatability across passes`：10-pair / 40-pass pair-aware result。
6. `5.6 Strong compensation boundary`：direct-S ideal upper bound，与 subpoint-A 对照。

Joint-security 应占 Methods+Results+Discussion 的主要篇幅，建议约 55%-65%。Discussion 围绕“orbit-distinctness is necessary for security relevance but insufficient for Doppler distinguishability”展开，而不是继续优化 orbit predictor 或 verifier。

## 7. Figure freeze

| figure_id   | title                                                 | status                           | paper_message                                                                                 |
|:------------|:------------------------------------------------------|:---------------------------------|:----------------------------------------------------------------------------------------------|
| F0          | Method framework schematic                            | TO_DRAW_DURING_MANUSCRIPT_LAYOUT | Public causal A -> uncertainty ellipsoid -> orbit decision -> Doppler verifier -> joint state |
| F1          | Physical separation versus rho99                      | EXISTING_FROZEN                  | Fixed km is not fixed uncertainty-normalized orbit distinctness                               |
| F2          | rho99 versus conditional verifier acceptance fraction | EXISTING_FROZEN                  | Acceptance decreases but persists beyond the P99 boundary                                     |
| F3          | Controlled altitude                                   | EXISTING_FROZEN                  | Connect legacy km factors to rho99 and ORBIT_DISTINCT acceptance                              |
| F4          | Same-pair multi-pass                                  | EXISTING_FROZEN                  | Show lack of persistent non-zero ambiguity across studied passes                              |

F0 是 manuscript layout 阶段根据已冻结 semantics 绘制的非数据 schematic，不需要新实验。F1-F4 已存在并由 joint manifest 绑定。F5 active-compensation 图优先放 supplement；版面允许时可作为第五张正文结果图。

## 8. Table freeze

| table_id   | title                                         | analysis_unit               | source_artifact                                             |
|:-----------|:----------------------------------------------|:----------------------------|:------------------------------------------------------------|
| T1         | Orbit-Uncertainty external validation summary | historical evaluation epoch | outputs/metrics/orbit_uncertainty_final_evidence_matrix.csv |
| T2         | ORBIT_DISTINCT family-level joint result      | LEVEL-A unit                | outputs/metrics/orbit_distinct_doppler_family_summary.csv   |

正文只保留 1-2 张核心表：T1 证明 orbit gate 的支持范围，T2 用 LEVEL-A unit N 汇总四个 family。不要以 26,780 rows 作为 security sample size。

## 9. Frozen limitations

| limitation_id   | topic                | frozen_scope                                                              | required_boundary                                                        |
|:----------------|:---------------------|:--------------------------------------------------------------------------|:-------------------------------------------------------------------------|
| L01             | Population           | 20-satellite same-shell Starlink cohort near the studied shell            | No universal Starlink or all-LEO extrapolation                           |
| L02             | Time                 | April-June 2026 historical period                                         | No untested season/year extrapolation                                    |
| L03             | Reference            | SpaceX-E/SupGP is a higher-quality historical reference                   | Not ground truth                                                         |
| L04             | Orbit support        | 0<element_age_hours<=36 h                                                 | Outside support is DEFER; 36 h is not universal validity                 |
| L05             | P99 semantics        | Study-specific preregistered conservative security gate                   | Not an aerospace or industry standard                                    |
| L06             | Observation model    | Controlled b/k/sigma/noise realizations                                   | Not an operational or real-world attack distribution                     |
| L07             | Receiver scope       | Single-station claimed-satellite verifier                                 | No multi-receiver spatial consistency conclusion                         |
| L08             | Scheduling           | Public beam/service scheduling was not reconstructed                      | No claim about real service availability or traffic                      |
| L09             | Service center C     | Analytical attack reference                                               | Not a claimed real beam center                                           |
| L10             | Compensation         | Direct-S ideal is an idealized upper-bound condition                      | No operational feasibility or multi-receiver generalization              |
| L11             | Multi-pass           | 10 real pairs, four studied passes each                                   | Conditional repeatability evidence, not a guarantee                      |
| L12             | Execution population | 407 result-blind structurally selected LEVEL-A units across four families | Not a prevalence sample; family endpoints are heterogeneous              |
| L14             | P95 calibration      | Untouched June P95=93.6909%, with reference-quality sensitivity           | P99 primary conclusion does not erase P95 undercoverage                  |
| L15             | Temporal dependence  | Out-of-set exceedances cluster; max June U99 episode=18.55 h              | Pointwise coverage is not temporal independence; no maneuver attribution |
| L16             | Attack execution     | No real attack was executed                                               | No real-world success or feasibility claim                               |

最危险的过度表述是把 `198/265` 或 `25/30 direct-S ideal` 写成 Starlink attack success rate。其次是把 rho99、P99、SupGP 或固定 km 误写为 probability、universal standard、ground truth 或普适安全阈值。完整 prohibited wording 见 `joint_security_final_prohibited_claims.csv`。

## 10. Stop decision

现有 evidence 已回答 frozen main question；R3 transition diagnostic 已是 `BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE`。没有新的 correctness/provenance issue，也没有阻塞论文撰写的科学缺口。剩余工作是非科学性的 method schematic、caption、正文压缩和组会/论文排版。

`NEW SCIENCE: NOT REQUIRED FOR MAINLINE`

`NEXT STEP: PAPER WRITING / GROUP-MEETING SYNTHESIS`
