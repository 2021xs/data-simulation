# Orbit Uncertainty final evidence and stopping review

## Executive decision

正式状态：`ORBIT_UNCERTAINTY_BRANCH_COMPLETE`。

主线决策：`STOP ORBIT-UNCERTAINTY MODEL OPTIMIZATION`。July：`NOT REQUIRED FOR MAINLINE`。Satellite-specific model：`DOWNGRADED / NOT REQUIRED`。Regime detector：`OPTIONAL / NON-BLOCKING`。6D：`NOT NEEDED YET`。

最终论文术语统一为 **Freshness-Conditioned Robust Empirical RTN Ellipsoid**。下一主线严格为 `ORBIT_DISTINCT_TO_DOPPLER_SECURITY_BRIDGE`。

## LEVEL 1: DATA / PROVENANCE VALIDITY

April、May、June 分别有 5675、6181、5927 个 historical SupGP evaluation epochs，全部存在 ordinary-GP causal candidate；selection 均为 `CREATION_DATE <= evaluation_time; latest CREATION_DATE -> latest EPOCH -> GP_ID`，future-publication use、selected future epoch、negative element/publication age 均为 0。SpaceX-E/SupGP 是 higher-quality historical reference，不是 ground truth；所得量是 ordinary-GP prediction disagreement relative to reference。

June 的 25 个 GT72 rows 经 7 星 targeted completeness query 确认：targeted/current same-window records=65/65，missing causal-newer record=0，因此属于真实 causal public-data staleness。`CAUSAL_DATA_READINESS_V2` 只澄清 engineering readiness，`Stage-1F scientific protocol changed=false`；25 rows 均在 >36 h outside-support population 中并保持 DEFER。

## LEVEL 2: REPLICATED ORBIT-ERROR STRUCTURE

Freshness：April element age 与 position norm Spearman=`0.479595`；May M0 transfer=`PARTIALLY_SUPPORTED`；June 冻结六 bin 的最小 P99=`99.2708%`。因此可写“conditional error scale statistically depends on freshness”，不可写逐行严格单调。

RTN anisotropy：April/May/June T-dominant fraction=`96.2204%` / `96.2094%` / `97.2351%`。June median |R/T/N|=`0.1406/3.9587/0.1075 km`，全部六 bin T dominant。结论：`RTN_ANISOTROPY_REPLICATED`；norm-only isotropic sphere 不能保留该方向结构。

Velocity：June `corr(delta_T,delta_v_R)` Pearson/Spearman=`-0.999911/-0.999320`，与 April/May 的极强耦合一致。但没有证据证明 6D set 改善 security decision，故 `6D_EXTENSION_DECISION=NOT_NEEDED_YET`。

## LEVEL 3: CALIBRATION / TRANSFERABILITY

- Publication age M1：May `NOT_SUPPORTED`，从 primary 删除；只表示控制 element age 后未见稳定 secondary transfer gain。
- Satellite-wide scale M2：May `PARTIALLY_SUPPORTED`；April→May P95 ranking R/T/N/norm约`0.188/0.182/0.686/0.182`。June 无 satellite P99<95%，没有 stable repeated severe joint undercoverage。因此 `NOT_SUFFICIENTLY_SUPPORTED`，仅保留 subgroup diagnostic。
- Regime M3/M4：April fitted preprocessing 缺 logistic intercept、StandardScaler、SimpleImputer 和 manifest-bound pipeline，严格 May transfer 未完成。由于 regime 不属于 final primary 且简单模型已通过 June，该问题为 `NON_BLOCKING_LIMITATION`，不重做 M3/M4。

## LEVEL 4: FINAL JOINT UNCERTAINTY GATE

Stage-1F-lite 从 marginal absolute components 升级为 signed 3D RTN joint set。Ellipsoid 使用 robust center 与 covariance geometry，但 c95/c99 来自 development legitimate residual score 的 empirical quantiles，不使用 Gaussian chi-square threshold，也不把 covariance 称为 true covariance。

在冻结支持域 `0 < element_age_hours <= 36` 内，April+May 校准的 primary Ellipsoid 在 untouched June 达到 `5360/5389=99.4619%` joint legitimate coverage，satellite-cluster 95% CI=`[98.9915%, 99.8530%]`；legitimate false-orbit-distinct rate=`0.5381%`。预注册 P99>=98% 和 structural-bin rule 均通过。

Box sensitivity P99=`99.5732%`，比 Ellipsoid 高 `0.1113 pp`。这表明成功不依赖单一 geometry；不能 post-hoc swap。Ellipsoid 的 development final P99 volume ratio=`0.6944`，仍满足预注册复杂度收益，故 `ELLIPSOID_PRIMARY_RETAINED`。

## LEVEL 5: LIMITATIONS / NON-GENERALIZABLE CLAIMS

P95=`93.6909%`，低于 nominal 95%；RMS Q4 P95=`90.2747%`，而 Q1=`94.7329%`。P95 对时间/reference-quality proxy 的 transfer 较弱，是正式 secondary calibration limitation。Q4 P99=`99.1834%`，没有反转 primary P99 conclusion；RMS 继续是 `REFERENCE_ONLY`。

June 最大 U99 continuous out-of-set episode=`18.55 h`，最大 U95=`41.97 h`。高 overall pointwise coverage 不意味着 exceedances 独立；`TEMPORAL_NONSTATIONARITY=LIMITATION`，不得称 episode 为 maneuver。

模型范围仅为 studied 20-Starlink same-shell cohort、April-June 2026、higher-quality historical reference 和 0-36 h calibrated support。36 h 不是 universal GP validity limit，P99 也不是 industry standard。

## LEVEL 6: STOPPING DECISION

| criterion | pre_registered_requirement | status | reason |
|---|---|---|---|
| Freshness structure | No qualitative failure | PASS_WITH_LIMITATION | Freshness is useful conditioning, not a strict rowwise monotone law. |
| RTN anisotropy | No qualitative reversal | PASS | Strong T dominance replicated across all months and all June bins. |
| Joint P99 external coverage | June pooled P99 >=98% | PASS | Untouched June primary endpoint passed. |
| Freshness-bin stability | No bin with n>=100 and P99<95% | PASS | All six populated bins exceed 99%. |
| Satellite-wise catastrophic failure | No stable repeated severe satellite failure | PASS_WITH_LIMITATION | Heterogeneity remains, but no June catastrophic or stable repeated severe pattern. |
| Candidate complexity comparison | Ellipsoid earns complexity only with >=10% stable volume reduction and <=0.5 pp P99 degradation | PASS | Frozen Ellipsoid selection remains justified; Box confirms robustness. |
| Satellite-specific model necessity | No new stable fixed satellite-wide scale evidence | PASS_WITH_LIMITATION | Satellite-specific effects remain diagnostic, not required in primary. |
| Regime-detector necessity | Not necessary for downstream security conclusion | PASS_WITH_LIMITATION | Regime detector is optional/non-blocking; its transferability remains unevaluated. |
| Reference sensitivity | Must not reverse primary conclusion | PASS_WITH_LIMITATION | P95 sensitivity exists; Q4 P99 remains above the pooled success threshold. |
| Temporal nonstationarity | Handled by abstention/episodes without primary-rule failure | PASS_WITH_LIMITATION | Temporal clustering remains a limitation, not a primary coverage failure. |
| 6D necessity | Only extend if incremental security-decision value is established | PASS_WITH_LIMITATION | Physical coupling replicates, but incremental decision value is unproven; NOT_NEEDED_YET. |
| Provenance/freeze integrity | Frozen and canonical artifacts unchanged; numerical audit passes | PASS | No provenance or numerical invalidation. |
| June-derived fitting | All June-derived fitted parameter counts equal zero | PASS | June remained confirmatory test data. |
| Downstream readiness | All blocking stopping conditions pass | PASS | Stable uncertainty interface is ready for orbit-distinct to Doppler security. |

所有 blocking stopping criteria 已满足。`PASS_WITH_LIMITATION` 项已进入论文限制和 downstream sensitivity 语义，但不要求继续优化 uncertainty predictor。只有这些 limitation 实际改变后续 orbit-distinct / Doppler security conclusion 时，才允许另开 sensitivity branch。

## Supported claims

| claim_id | claim | allowed_wording | boundary |
|---|---|---|---|
| S1 | Public ordinary-GP disagreement has statistically supported freshness dependence in the studied data. | Element age is a supported conditioning variable for the empirical disagreement scale. | Do not claim every residual increases monotonically with age. |
| S2 | Position residuals exhibit strong, cross-month stable RTN anisotropy with T dominance. | T-dominance replicated at 96.2%/96.2%/97.2% in April/May/June. | Restricted to the studied cohort/time/reference. |
| S3 | An isotropic position-norm sphere does not preserve the observed directional structure. | A signed RTN representation retains anisotropy that a norm-only sphere omits. | This is a representation claim, not universal superiority for every task. |
| S4 | A freshness-conditioned signed 3D RTN joint set is an appropriate decision representation for this pipeline. | Freshness-Conditioned Robust Empirical RTN Ellipsoid is the frozen primary uncertainty gate. | Do not call its covariance true orbit covariance. |
| S5 | The April+May frozen Ellipsoid achieved 99.4619% empirical P99 joint coverage on untouched June. | Legitimate ordinary-GP disagreement coverage was 5360/5389 with satellite-cluster CI 98.9915%-99.8530%. | Not accuracy, attack detection accuracy, or true-orbit coverage. |
| S6 | A fixed satellite-wide scalar lacks sufficient stable cross-month evidence for the primary model. | Satellite scale remains a subgroup diagnostic rather than a primary fitted effect. | Do not claim satellite identity never matters. |
| S7 | Publication age did not show stable additional transfer benefit after element-age conditioning. | M1 was not supported in the April-to-May locked transfer. | Do not claim publication age is universally irrelevant. |

## Limited claims

| claim_id | claim | allowed_wording | boundary |
|---|---|---|---|
| L1 | Population scope | 20 same-shell Starlink satellites near the studied 53.16-degree, 473-km shell. | Not universal Starlink or all LEO. |
| L2 | Temporal scope | April-June 2026 historical evaluation. | No untested year/season extrapolation. |
| L3 | Reference semantics | SpaceX-E/SupGP higher-quality historical reference. | Not ground truth. |
| L4 | Freshness support | Empirically calibrated for 0<element age<=36 h; outside is DEFER. | 36 h is not a universal GP validity limit. |
| L5 | P99 role | A conservative preregistered security-design gate for this study. | Not an aerospace or industry universal standard. |
| L6 | Temporal episodes | Continuous out-of-set episodes demonstrate clustered exceedances/nonstationarity. | Do not label episodes maneuvers. |
| L7 | P95/reference sensitivity | P95 transfers less stably and is lower in RMS Q4; P99 conclusion remains supported. | Do not hide P95 undercoverage or make RMS operational. |

## Unsupported / prohibited claims

| claim_id | claim | boundary |
|---|---|---|
| P1 | Universal Starlink uncertainty model | Cohort/time-limited evidence only. |
| P2 | Applicable to all LEO | No cross-constellation/orbit evidence. |
| P3 | SupGP is ground truth or covariance is true covariance | Reference-relative empirical disagreement only. |
| P4 | A high-score episode confirms a maneuver | Use continuous out-of-set episode. |
| P5 | Orbits older than 36 h are impossible or invalid | They are outside calibrated support and deferred. |
| P6 | P99 is an industry standard | Study-specific preregistered choice. |
| P7 | 0.5381% is an attack false-positive rate or attack success probability | It is legitimate false-orbit-distinct rate. |
| P8 | 99.4619% attack detection accuracy | It is legitimate reference-relative empirical joint coverage. |
| P9 | A fixed universal kilometer boundary | The gate is freshness-conditioned and anisotropic. |

## Downstream interface

稳定接口定义在 `outputs/metrics/orbit_uncertainty_final_downstream_interface.json`。输入为 claimed A causal public-GP prediction、evaluation time 与 candidate B state；输出 freshness、claimed-A-defined RTN displacement、frozen Ellipsoid D2 和 `NOT_ORBIT_DISTINCT / AMBIGUOUS / ORBIT_DISTINCT / DEFER`。

下一研究问题是：当 B 已被 frozen gate 判为 `ORBIT_DISTINCT` 时，Doppler claimed-identity verifier 是否仍可能接受 B。核心危险区域为 `ORBIT_DISTINCT + DOPPLER_INDISTINGUISHABLE`。
