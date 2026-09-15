# 合法 A 公开轨道误差 → Doppler / OLS 输出实验报告

## 1. 研究边界与执行状态

本实验独立于旧 frozen joint-security population，只研究合法 A。April/May 为 exploratory，June 在 protocol 与 population SHA 冻结后才执行 confirmatory science。全程没有引入额外发射源、补偿、`b_env`、`k_env`、noise 或随机观测误差；没有执行 production b/k gate，也不报告 false reject rate。

reference 语义固定为 SpaceX-E/SupGP higher-quality historical reference，不是 ground truth、true orbit 或 exact state。

- protocol SHA：`75C051F0A3D61D38FF043A37D9B4E2DBB5588959FAB6D26C1DFF4EA212AC77B7`
- population SHA：`4C4C0D1B96CE66CDA18FEF56144812CBD49FDEF4A1B42E5141BE32C90268DB81`
- population：2088 segments / 696 passes / 20 satellites
- April+May：1386 segments；June：702 segments
- residual sign：`delta_f_orbit = F_ref - F_public`
- Stage-A final verdict：`GEOMETRY_EFFECT_DOMINATES_OR_INTERACTS_STRONGLY`

## 2. Freshness coverage

六个 bin 的总 segment 数：

| analysis_role   | freshness_bin   |   segments |
|:----------------|:----------------|-----------:|
| CONFIRMATORY    | 0-6 h           |        112 |
| CONFIRMATORY    | 12-18 h         |        120 |
| CONFIRMATORY    | 18-24 h         |        120 |
| CONFIRMATORY    | 24-36 h         |        114 |
| CONFIRMATORY    | 6-9 h           |        119 |
| CONFIRMATORY    | 9-12 h          |        117 |
| EXPLORATORY     | 0-6 h           |        239 |
| EXPLORATORY     | 12-18 h         |        242 |
| EXPLORATORY     | 18-24 h         |        239 |
| EXPLORATORY     | 24-36 h         |        186 |
| EXPLORATORY     | 6-9 h           |        240 |
| EXPLORATORY     | 9-12 h          |        240 |

satellite×month×bin 的完整 coverage 见 `outputs/metrics/orbit_error_to_doppler_legitimate_freshness_coverage.csv`。P99 只有 n≥100 时报告；不足时保留 `LIMITED_SUPPORT`，没有补窗口。

## 3. Raw Doppler 与 b+kt projection

| analysis_split        | freshness_bin   | metric                     |   n |      median |         p90 |         p95 |           p99 | p99_support_status   |
|:----------------------|:----------------|:---------------------------|----:|------------:|------------:|------------:|--------------:|:---------------------|
| EXPLORATORY_APRIL_MAY | 0-6 h           | raw_rms_hz                 | 239 |  172.564    |  704.442    | 1044.54     |   1954.47     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 0-6 h           | abs_delta_k_orbit_hz_per_s | 239 |    1.44199  |    4.07286  |    5.64918  |      8.01662  | REPORTED             |
| EXPLORATORY_APRIL_MAY | 0-6 h           | score_orbit_hz             | 239 |    6.6258   |   55.1144   |   72.914    |    160.498    | REPORTED             |
| EXPLORATORY_APRIL_MAY | 0-6 h           | explained_fraction         | 239 |    0.997138 |    0.999942 |    0.999979 |      0.999995 | REPORTED             |
| EXPLORATORY_APRIL_MAY | 6-9 h           | raw_rms_hz                 | 240 |  336.537    | 1313.61     | 1704.99     |   2192.23     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 6-9 h           | abs_delta_k_orbit_hz_per_s | 240 |    2.02039  |    7.4556   |    8.60147  |     10.2754   | REPORTED             |
| EXPLORATORY_APRIL_MAY | 6-9 h           | score_orbit_hz             | 240 |   10.8386   |   73.6387   |  104.19     |    157.324    | REPORTED             |
| EXPLORATORY_APRIL_MAY | 6-9 h           | explained_fraction         | 240 |    0.997844 |    0.999899 |    0.999979 |      0.999997 | REPORTED             |
| EXPLORATORY_APRIL_MAY | 9-12 h          | raw_rms_hz                 | 240 |  547.884    | 2060.16     | 2759.09     |   4934.42     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 9-12 h          | abs_delta_k_orbit_hz_per_s | 240 |    1.50758  |    8.71572  |   11.3917   |     31.5931   | REPORTED             |
| EXPLORATORY_APRIL_MAY | 9-12 h          | score_orbit_hz             | 240 |    7.10982  |   63.1842   |  157.908    |    243.035    | REPORTED             |
| EXPLORATORY_APRIL_MAY | 9-12 h          | explained_fraction         | 240 |    0.999786 |    0.999981 |    0.99999  |      0.999997 | REPORTED             |
| EXPLORATORY_APRIL_MAY | 12-18 h         | raw_rms_hz                 | 242 |  605.041    | 2711.26     | 3517.15     |   7725.53     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 12-18 h         | abs_delta_k_orbit_hz_per_s | 242 |    3.02615  |   13.8913   |   17.336    |     32.5354   | REPORTED             |
| EXPLORATORY_APRIL_MAY | 12-18 h         | score_orbit_hz             | 242 |   20.9253   |  165.034    |  264.922    |    609.276    | REPORTED             |
| EXPLORATORY_APRIL_MAY | 12-18 h         | explained_fraction         | 242 |    0.996765 |    0.999921 |    0.999967 |      0.999994 | REPORTED             |
| EXPLORATORY_APRIL_MAY | 18-24 h         | raw_rms_hz                 | 239 | 1126.64     | 3994.49     | 6021.74     |   8659.57     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 18-24 h         | abs_delta_k_orbit_hz_per_s | 239 |    5.66449  |   24.4109   |   28.1251   |     36.46     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 18-24 h         | score_orbit_hz             | 239 |   17.7521   |  140.336    |  451.81     |    669.63     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 18-24 h         | explained_fraction         | 239 |    0.999622 |    0.999993 |    0.999996 |      0.999997 | REPORTED             |
| EXPLORATORY_APRIL_MAY | 24-36 h         | raw_rms_hz                 | 186 | 1623.12     | 4995.01     | 7448.13     | 143182        | REPORTED             |
| EXPLORATORY_APRIL_MAY | 24-36 h         | abs_delta_k_orbit_hz_per_s | 186 |    5.14925  |   28.194    |   43.406    |    991.546    | REPORTED             |
| EXPLORATORY_APRIL_MAY | 24-36 h         | score_orbit_hz             | 186 |   21.1645   |  265.647    |  485.851    |   1640.35     | REPORTED             |
| EXPLORATORY_APRIL_MAY | 24-36 h         | explained_fraction         | 186 |    0.999569 |    0.999984 |    0.999995 |      0.999997 | REPORTED             |
| CONFIRMATORY_JUNE     | 0-6 h           | raw_rms_hz                 | 112 |  194.439    | 1061.74     | 1482.37     |   2487.94     | REPORTED             |
| CONFIRMATORY_JUNE     | 0-6 h           | abs_delta_k_orbit_hz_per_s | 112 |    1.32242  |    6.78831  |    8.8522   |     19.0259   | REPORTED             |
| CONFIRMATORY_JUNE     | 0-6 h           | score_orbit_hz             | 112 |    7.63136  |   63.913    |  106.753    |    298.66     | REPORTED             |
| CONFIRMATORY_JUNE     | 0-6 h           | explained_fraction         | 112 |    0.997719 |    0.999912 |    0.999952 |      0.999991 | REPORTED             |
| CONFIRMATORY_JUNE     | 6-9 h           | raw_rms_hz                 | 119 |  301.427    | 2040.74     | 6763.99     |  16049.5      | REPORTED             |
| CONFIRMATORY_JUNE     | 6-9 h           | abs_delta_k_orbit_hz_per_s | 119 |    1.61577  |   12.6795   |   21.8543   |    213.435    | REPORTED             |
| CONFIRMATORY_JUNE     | 6-9 h           | score_orbit_hz             | 119 |   13.6711   |  107.379    |  310.794    |    722.676    | REPORTED             |
| CONFIRMATORY_JUNE     | 6-9 h           | explained_fraction         | 119 |    0.997592 |    0.999882 |    0.999935 |      0.999976 | REPORTED             |
| CONFIRMATORY_JUNE     | 9-12 h          | raw_rms_hz                 | 117 |  499.961    | 4192.15     | 6868.67     |  31859.9      | REPORTED             |
| CONFIRMATORY_JUNE     | 9-12 h          | abs_delta_k_orbit_hz_per_s | 117 |    1.68474  |   36.9808   |   84.1706   |    124.893    | REPORTED             |
| CONFIRMATORY_JUNE     | 9-12 h          | score_orbit_hz             | 117 |   11.1648   |  231.999    |  385.13     |   2384.22     | REPORTED             |
| CONFIRMATORY_JUNE     | 9-12 h          | explained_fraction         | 117 |    0.999202 |    0.999959 |    0.999979 |      0.999985 | REPORTED             |
| CONFIRMATORY_JUNE     | 12-18 h         | raw_rms_hz                 | 120 |  775.8      | 4751.16     | 8804.49     | 206253        | REPORTED             |
| CONFIRMATORY_JUNE     | 12-18 h         | abs_delta_k_orbit_hz_per_s | 120 |    4.72628  |   27.9907   |   33.9156   |    742.828    | REPORTED             |
| CONFIRMATORY_JUNE     | 12-18 h         | score_orbit_hz             | 120 |   40.7767   |  345.131    |  688.109    |   1528.91     | REPORTED             |
| CONFIRMATORY_JUNE     | 12-18 h         | explained_fraction         | 120 |    0.996486 |    0.999882 |    0.999964 |      0.999996 | REPORTED             |
| CONFIRMATORY_JUNE     | 18-24 h         | raw_rms_hz                 | 120 |  947.709    | 4248.1      | 7370.07     |  21902.4      | REPORTED             |
| CONFIRMATORY_JUNE     | 18-24 h         | abs_delta_k_orbit_hz_per_s | 120 |    4.56643  |   25.1294   |   35.7817   |    153.214    | REPORTED             |
| CONFIRMATORY_JUNE     | 18-24 h         | score_orbit_hz             | 120 |   18.5225   |  141.043    |  264.105    |    831.744    | REPORTED             |
| CONFIRMATORY_JUNE     | 18-24 h         | explained_fraction         | 120 |    0.999683 |    0.999977 |    0.999989 |      0.999996 | REPORTED             |
| CONFIRMATORY_JUNE     | 24-36 h         | raw_rms_hz                 | 114 | 2210.96     | 7640.61     | 9491.03     |  12633.5      | REPORTED             |
| CONFIRMATORY_JUNE     | 24-36 h         | abs_delta_k_orbit_hz_per_s | 114 |    7.65708  |   43.4967   |   53.0587   |     83.3605   | REPORTED             |
| CONFIRMATORY_JUNE     | 24-36 h         | score_orbit_hz             | 114 |   40.5948   |  348.341    |  623.784    |    914.818    | REPORTED             |
| CONFIRMATORY_JUNE     | 24-36 h         | explained_fraction         | 114 |    0.998891 |    0.999971 |    0.999989 |      0.999997 | REPORTED             |

April/May explained-fraction median=`0.998534`；June median=`0.998073`。`delta_b_orbit` / `delta_k_orbit` 仅表示轨道 disagreement 引起的增量 fitted shift，不是完整 production b/k。

跨 freshness bin 汇总时，April/May 的 raw RMS median/P90/P95/P99 为 `543.75 / 2581.18 / 3753.43 / 8917.70 Hz`，production score 为 `12.94 / 102.19 / 201.78 / 680.15 Hz`；June 对应 raw RMS 为 `626.44 / 4377.14 / 7684.77 / 30989.34 Hz`，score 为 `17.66 / 222.88 / 438.02 / 1067.57 Hz`。分布有明显长尾，最大 raw RMS 在 April/May 与 June 分别达到 `218393.65 Hz` 和 `361020.01 Hz`；这些单位按冻结排除规则保留，没有结果驱动剔除，且不得把它们解释为相对 ground truth 的误差。

预冻结 curvature flag 在 April/May 为 `1280/1386`，June 为 `652/702`。因此，“raw energy 大部分可被线性投影吸收”不等价于剩余曲线严格线性或 score 恒为零；curvature 与长尾是 Stage B 前需要继续审计 reference/geometry 分层的诊断信号。

## 4. Freshness association 与 June replication

| analysis_split        | metric                     |    n |   spearman_rho |   spearman_pvalue |
|:----------------------|:---------------------------|-----:|---------------:|------------------:|
| EXPLORATORY_APRIL_MAY | raw_rms_hz                 | 1386 |       0.517923 |       5.72428e-96 |
| EXPLORATORY_APRIL_MAY | abs_delta_b_orbit_hz       | 1386 |       0.514934 |       1.06007e-94 |
| EXPLORATORY_APRIL_MAY | abs_delta_k_orbit_hz_per_s | 1386 |       0.315381 |       2.20821e-33 |
| EXPLORATORY_APRIL_MAY | score_orbit_hz             | 1386 |       0.290158 |       2.71713e-28 |
| EXPLORATORY_APRIL_MAY | explained_fraction         | 1386 |       0.199378 |       6.82054e-14 |
| CONFIRMATORY_JUNE     | raw_rms_hz                 |  702 |       0.483264 |       2.30943e-42 |
| CONFIRMATORY_JUNE     | abs_delta_b_orbit_hz       |  702 |       0.48169  |       4.63217e-42 |
| CONFIRMATORY_JUNE     | abs_delta_k_orbit_hz_per_s |  702 |       0.324198 |       1.2123e-18  |
| CONFIRMATORY_JUNE     | score_orbit_hz             |  702 |       0.310347 |       3.86983e-17 |
| CONFIRMATORY_JUNE     | explained_fraction         |  702 |       0.172356 |       4.37116e-06 |

| metric                     |   exploratory_rho |   exploratory_pvalue |   june_rho |   june_pvalue | signs_agree   | exploratory_predeclared_structure   | june_predeclared_structure   | structure_replicated   |
|:---------------------------|------------------:|---------------------:|-----------:|--------------:|:--------------|:------------------------------------|:-----------------------------|:-----------------------|
| raw_rms_hz                 |          0.517923 |          5.72428e-96 |   0.483264 |   2.30943e-42 | True          | True                                | True                         | True                   |
| abs_delta_b_orbit_hz       |          0.514934 |          1.06007e-94 |   0.48169  |   4.63217e-42 | True          | True                                | True                         | True                   |
| abs_delta_k_orbit_hz_per_s |          0.315381 |          2.20821e-33 |   0.324198 |   1.2123e-18  | True          | True                                | True                         | True                   |
| score_orbit_hz             |          0.290158 |          2.71713e-28 |   0.310347 |   3.86983e-17 | True          | False                               | True                         | False                  |
| explained_fraction         |          0.199378 |          6.82054e-14 |   0.172356 |   4.37116e-06 | True          | False                               | False                        | False                  |

相关系数只作连续-age描述；结论同时检查 bin median/quantile 与 June 符号、效应量和显著性复现，没有据此修改 bins 或 score。

## 5. Geometry diagnostic

| metric                     |   qualifying_freshness_bins | geometry_effect_nonnegligible   | status                        | evidence                                                                                                                                                                                                                                                                                               |
|:---------------------------|----------------------------:|:--------------------------------|:------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| raw_rms_hz                 |                           5 | True                            | GEOMETRY_EFFECT_NONNEGLIGIBLE | 6-9 h:elevation_bin:ratio=6.26094:range=1205.12;9-12 h:elevation_bin:ratio=4.55323:range=1659.04;12-18 h:elevation_bin:ratio=4.36401:range=1545.9;18-24 h:elevation_bin:ratio=6.13154:range=4739.94;24-36 h:elevation_bin:ratio=5.86165:range=4492.93                                                  |
| score_orbit_hz             |                           6 | True                            | GEOMETRY_EFFECT_NONNEGLIGIBLE | 0-6 h:elevation_bin:ratio=31.4886:range=44.3465;6-9 h:elevation_bin:ratio=42.5714:range=70.1305;9-12 h:elevation_bin:ratio=50.5311:range=184.249;12-18 h:elevation_bin:ratio=43.8241:range=156.476;18-24 h:elevation_bin:ratio=93.0141:range=461.497;24-36 h:elevation_bin:ratio=25.6173:range=271.589 |
| abs_delta_k_orbit_hz_per_s |                           5 | True                            | GEOMETRY_EFFECT_NONNEGLIGIBLE | 6-9 h:phase_label:ratio=5.03912:range=2.85693;9-12 h:elevation_bin:ratio=8.77323:range=4.20881;12-18 h:elevation_bin:ratio=11.3142:range=5.66213;18-24 h:elevation_bin:ratio=2.19031:range=5.29073;24-36 h:elevation_bin:ratio=6.4312:range=8.76312                                                    |

固定站只有一个，无法估计 station-between effect。可检验的 geometry 包括预冻结 elevation bins、上升/峰值/下降 phase、satellite 与 month。完整分组表见 geometry summary。

## 6. Primary questions

1. raw Doppler 大小：见 freshness summary 的 `raw_rms_hz`；这是 public/reference disagreement 的 observation-space 映射。
2. raw error 是否随 freshness 增大：由 exploratory 与 June 的 bin quantile + Spearman replication 共同判断，见 replication 表。
3. b+kt 吸收量：explained fraction 的 exploratory/June median 分别为 `0.998534` / `0.998073`。
4. projected score 是否仍受 freshness 影响：见 `score_orbit_hz` replication=`False`；explained-fraction replication=`False`。
5. Δb / Δk 是否随 freshness：`abs_delta_b_orbit_hz` replication=`True`；`abs_delta_k_orbit_hz_per_s` replication=`True`。本轮按协议不执行 b/k gate。
6. rejection attribution：不适用，本轮没有 verifier decision endpoint。
7. 鲁棒性：只能对 b+kt projection 的吸收能力作 Stage-A 诊断，不能转换为 false reject claim。
8. Stage B：warranted=`True`，主要关注 `delta_k, geometry`；若进入 Stage B，先冻结 nominal legitimate b/k anchor semantics，本轮不设计 threshold。
9. 若 Stage B 不值得，则应停止增加 online uncertainty layer；本轮 verdict 不修改现有 verifier。
10. geometry：predeclared flag=`True`；若为 true，freshness-only 描述不足。

## 7. 保护与局限

- 旧 332 windows 未复用；407 Level-A、265-unit joint endpoint、orbit uncertainty parameters、thresholds、verifier 和 final synthesis 均未修改。
- population selection 不读取 `F_ref-F_public`、raw error、Δb、Δk、score 或 outcome。
- production Doppler 和 centered-time OLS 通过冻结源码 SHA 绑定。
- reference 最近历元限制为 3 h，使用单个 SupGP OMM propagation，不做状态插值。
- 单一固定站限制了 station heterogeneity 结论。

## 8. 最终 verdict

`GEOMETRY_EFFECT_DOMINATES_OR_INTERACTS_STRONGLY`

是否值得进入 Stage B：`True`；建议关注：`delta_k, geometry`。本结论仅针对 ordinary-GP/reference disagreement 对 verifier 内部量的增量影响，不是合法卫星 false-reject rate。
