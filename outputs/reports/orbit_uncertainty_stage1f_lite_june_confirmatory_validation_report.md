# Orbit Uncertainty Stage-1F-lite June locked confirmatory validation

## 1. 冻结输入与协议

本次是冻结 April+May 模型对 untouched June 的首次预注册 confirmatory test。Primary 固定为 `ROBUST_EMPIRICAL_ELLIPSOID`，secondary 固定为 `JOINT_MAX_SCORE_BOX`；二者身份未交换。冻结参数 SHA256 为 `6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1`，June canonical SHA256 为 `DBE3551373D5EFDAF33CFB16296A564ADA29AA49E9852A92F599AD49B00934ED`。

正式支持域严格为 `0 < element_age_hours <= 36`：总计 5927 rows，其中 5389 rows 进入 confirmatory denominator，538 rows 记为 `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`，其中 25 rows 为真实 `ENGINEERING_STALENESS_GT72H`。outside-support rows 未进入 coverage、bin、candidate comparison 或 false-orbit-distinct 分母。

## 2. Primary confirmatory endpoint

- P99 joint legitimate coverage：`0.994618668`（5360/5389）
- false-orbit-distinct rate：`0.005381332`（29/5389）
- satellite-cluster bootstrap P99 95% CI：`[0.989914825, 0.998529979]`
- P95 joint coverage：`0.936908517`；cluster-bootstrap 95% CI：`[0.909719954, 0.961496810]`
- pooled P99 >= 98%：`True`
- structural bin undercoverage count：`0`

冻结 primary 判据只由 pooled P99、structural-bin rule、数值/provenance integrity 和 zero June fitting 决定。P95 是 secondary endpoint，不覆盖 primary 判决。

## 3. Freshness-bin coverage

| group_id   |    n |   p95_joint_coverage |   p99_joint_coverage | structural_bin_undercoverage   |
|:-----------|-----:|---------------------:|---------------------:|:-------------------------------|
| 0-6 h      |  489 |             0.92229  |             0.993865 | False                          |
| 6-9 h      |  788 |             0.950508 |             0.997462 | False                          |
| 9-12 h     |  849 |             0.916372 |             0.992933 | False                          |
| 12-18 h    | 1442 |             0.941748 |             0.993759 | False                          |
| 18-24 h    |  960 |             0.938542 |             0.992708 | False                          |
| 24-36 h    |  861 |             0.943089 |             0.997677 | False                          |

## 4. June halves

| group_id    |    n |   p95_joint_coverage |   p99_joint_coverage |   false_orbit_distinct_rate |
|:------------|-----:|---------------------:|---------------------:|----------------------------:|
| FIRST_HALF  | 2887 |             0.928646 |             0.993419 |                    0.006581 |
| SECOND_HALF | 2502 |             0.946443 |             0.996003 |                    0.003997 |

P95/P99 half-to-half absolute difference 分别为 `0.017797193` / `0.002584424`，未按 half 重校准。

## 5. Satellite-cluster distribution and May context

20 颗卫星 P99 median=`1.000000000`，range=`[0.966037736, 1.000000000]`。最低为 NORAD `58380`（n=265, P99=`0.966037736`）。单星 point estimate 不构成 hard pass/fail。

May→June 重复 severe satellite undercoverage（描述性、非冻结判据）：`未识别`。May context 使用冻结的 April M0→May external-validation P95 输出，只作事后 persistence interpretation，未拟合 satellite effect。

## 6. Continuous out-of-set episodes

episode 使用冻结的 6 h break rule：in-set row 或相邻 formal-support evaluation gap >6 h 结束 run。最大 U99 episode：NORAD 58380，2026-06-07T21:35:42.000029Z 至 2026-06-08T16:08:41.999971Z，18.550000 h，8 rows。U99 episodes=`9`，U95 episodes=`131`。这些均称为 continuous out-of-set episodes，不解释为 maneuver。

## 7. Secondary box sensitivity

Box pooled P95=`0.938949712`，P99=`0.995732047`。相较 primary，P95 difference (Box-Ellipsoid)=`0.002041195`，P99 difference=`0.001113379`。无论方向如何，primary 始终保持 Ellipsoid。

## 8. Supportive structure diagnostics

June overall median |R/T/N|=`0.140563` / `3.958705` / `0.107546` km，T-dominant fraction=`0.972351`。这是 signed RTN anisotropy 的 supportive replication，不参与 primary pass/fail。

`corr(delta_T, delta_v_R)`：Pearson=`-0.999911367`，Spearman=`-0.999320316`。仍只作 velocity supportive diagnostic，未建立 6D set。

RMS Q4 primary P95/P99=`0.902746845` / `0.991833705`。RMS 始终为 `REFERENCE_ONLY_DIAGNOSTIC`，未设置 cutoff、未删除 Q4、未建立 RMS-conditioned threshold。

## 9. Correctness, fitting firewall, and provenance

Correctness checks：`34/34` passed。30-row-or-more deterministic independent audit 覆盖多个 satellites、6 个 bins、near-c95、near-c99 和可用 decision classes；production/independent score 与 classification 一致。June-derived center/covariance/MAD-scale/threshold/freshness-bin/satellite/regime parameter counts 全部为 0。参数文件、April/May canonical、Stage-1F freeze artifacts 和 June Stage-1A/B inputs 的 before/after SHA fingerprints 一致。

## 10. 正式结论

`JUNE_STAGE1F_LITE_CONFIRMATORY_SUPPORTED`

该结论不触发 refit、threshold inflation、bin merge、support change、satellite exclusion、candidate swap 或 6D extension。

## 11. Orbit Uncertainty stopping-criteria snapshot

| criterion                    | status     | evidence                                                                                                                                                       |
|:-----------------------------|:-----------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| freshness structure          | PASS       | all six bin P99 >= 0.992708; no qualitative failure                                                                                                            |
| RTN anisotropy               | PASS       | T has largest median absolute component and dominant fraction in every bin                                                                                     |
| joint coverage               | PASS       | primary pooled P99=0.994619                                                                                                                                    |
| structural-bin stability     | PASS       | structural failures=0                                                                                                                                          |
| candidate comparison         | PASS       | frozen primary and secondary both applied; candidate identity unchanged                                                                                        |
| satellite-specific necessity | LIMITATION | June per-satellite P99 range 0.966038-1.000000; repeated severe named satellites=0; heterogeneity is descriptive and does not establish a stable fitted effect |
| regime necessity             | PASS       | primary rule passed without a regime classifier; no regime fitting performed                                                                                   |
| reference sensitivity        | LIMITATION | RMS Q4 P95=0.902747 vs Q1=0.947329; Q4 P99=0.991834 does not reverse primary conclusion                                                                        |

这是 confirmatory-stage evidence snapshot，不替代下一步 `ORBIT_UNCERTAINTY_FINAL_EVIDENCE_AND_STOPPING_REVIEW`。`LIMITATION` 不覆盖本轮预注册 primary success；也不自动触发 predictor、satellite scale 或 regime tuning。
