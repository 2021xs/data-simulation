# May partial locked external validation report

状态：`MAY_PARTIAL_LOCKED_EXTERNAL_VALIDATION_COMPLETE`

这是一轮**部分 locked external validation**：M0/M1/M2 使用 April frozen artifacts 在 May test data 上评估；M3/M4 因 April fitted classifier provenance 不完整而未评估。本状态不等于、也不替代 `MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE`。

## 1. Recoverability 与锁定边界

| model   | all_parameters_available   |   May-derived_parameters | status                       | notes                                                                                                                                  |
|:--------|:---------------------------|-------------------------:|:-----------------------------|:---------------------------------------------------------------------------------------------------------------------------------------|
| M0      | True                       |                        0 | LOCKED_RECOVERABLE           | 13-point grid inversion max check=7.105e-15 km                                                                                         |
| M1      | True                       |                        0 | LOCKED_RECOVERABLE           | 40 factors + 8 target/quantile fallback values; all May rows map to frozen strata                                                      |
| M2      | True                       |                        0 | LOCKED_RECOVERABLE           | 160 factors + 8 target/quantile fallback values; exact 20-satellite May cohort present                                                 |
| M3      | False                      |                        0 | BLOCKED_PARAMETER_PROVENANCE | logistic intercept; StandardScaler.mean_/scale_; SimpleImputer.statistics_; manifest-bound fitted pipeline; search proven candidates=0 |
| M4      | False                      |                        0 | BLOCKED_PARAMETER_PROVENANCE | logistic intercept; StandardScaler.mean_/scale_; SimpleImputer.statistics_; manifest-bound fitted pipeline; search proven candidates=0 |

M3/M4 artifact search：serialized candidate=23，可证明来自 April Stage-1E 的 fitted classifier=0，git history available=False。因此二者正式记为 `NOT_EVALUATED: APRIL_FITTED_CLASSIFIER_PROVENANCE_INCOMPLETE`，不是 model failure，也不是 `NOT_SUPPORTED`。

May-derived fitted parameter count=`0`。本轮没有重新拟合 freshness curve、publication factor、satellite scale、quantile、threshold 或 classifier。

## 2. May support 与总体 coverage

- May Stage-1B总行数：6181；PRIMARY=`6094`；OUTSIDE=`87`。
- 形式条件严格为 `0 < element_age_seconds / 3600 <= 36`。
- 87条 outside-support rows 的 formal prediction=`0`、coverage score=`0`；全部保留在 descriptive summary。

| model   | target                 |   quantile |    n |   observed_coverage |   coverage_error |   pinball_loss |
|:--------|:-----------------------|-----------:|-----:|--------------------:|-----------------:|---------------:|
| M0      | abs_delta_R_km         |   0.900000 | 6094 |            0.894979 |        -0.005021 |       0.511688 |
| M1      | abs_delta_R_km         |   0.900000 | 6094 |            0.894650 |        -0.005350 |       0.511725 |
| M2      | abs_delta_R_km         |   0.900000 | 6094 |            0.887594 |        -0.012406 |       0.510392 |
| M0      | abs_delta_R_km         |   0.950000 | 6094 |            0.946997 |        -0.003003 |       0.520347 |
| M1      | abs_delta_R_km         |   0.950000 | 6094 |            0.944864 |        -0.005136 |       0.520679 |
| M2      | abs_delta_R_km         |   0.950000 | 6094 |            0.941090 |        -0.008910 |       0.522319 |
| M0      | abs_delta_T_km         |   0.900000 | 6094 |            0.911716 |         0.011716 |       7.649476 |
| M1      | abs_delta_T_km         |   0.900000 | 6094 |            0.908763 |         0.008763 |       7.645763 |
| M2      | abs_delta_T_km         |   0.900000 | 6094 |            0.905645 |         0.005645 |       7.636964 |
| M0      | abs_delta_T_km         |   0.950000 | 6094 |            0.957991 |         0.007991 |       7.608167 |
| M1      | abs_delta_T_km         |   0.950000 | 6094 |            0.956679 |         0.006679 |       7.612108 |
| M2      | abs_delta_T_km         |   0.950000 | 6094 |            0.951756 |         0.001756 |       7.706048 |
| M0      | abs_delta_N_km         |   0.900000 | 6094 |            0.890712 |        -0.009288 |       0.031168 |
| M1      | abs_delta_N_km         |   0.900000 | 6094 |            0.890712 |        -0.009288 |       0.031163 |
| M2      | abs_delta_N_km         |   0.900000 | 6094 |            0.887102 |        -0.012898 |       0.030079 |
| M0      | abs_delta_N_km         |   0.950000 | 6094 |            0.934690 |        -0.015310 |       0.021220 |
| M1      | abs_delta_N_km         |   0.950000 | 6094 |            0.936823 |        -0.013177 |       0.021176 |
| M2      | abs_delta_N_km         |   0.950000 | 6094 |            0.933705 |        -0.016295 |       0.020200 |
| M0      | position_error_norm_km |   0.900000 | 6094 |            0.911716 |         0.011716 |       7.673342 |
| M1      | position_error_norm_km |   0.900000 | 6094 |            0.908599 |         0.008599 |       7.669512 |
| M2      | position_error_norm_km |   0.900000 | 6094 |            0.904989 |         0.004989 |       7.660827 |
| M0      | position_error_norm_km |   0.950000 | 6094 |            0.957991 |         0.007991 |       7.633809 |
| M1      | position_error_norm_km |   0.950000 | 6094 |            0.956351 |         0.006351 |       7.637771 |
| M2      | position_error_norm_km |   0.950000 | 6094 |            0.951756 |         0.001756 |       7.732216 |

跨 target/quantile 的描述性汇总：

| model   |   overall_absolute_calibration_error |   mean_per_satellite_absolute_calibration_error |   worst_satellite_coverage |   per_satellite_coverage_std |   overall_pinball_loss |   overall_abs_error_improvement_vs_m0 |   mean_per_satellite_abs_error_improvement_vs_m0 |   coverage_dispersion_reduction_vs_m0 |   pinball_improvement_vs_m0 |
|:--------|-------------------------------------:|------------------------------------------------:|---------------------------:|-----------------------------:|-----------------------:|--------------------------------------:|-------------------------------------------------:|--------------------------------------:|----------------------------:|
| M0      |                             0.009005 |                                        0.044769 |                   0.812298 |                     0.053609 |               3.956152 |                              0.000000 |                                         0.000000 |                              0.000000 |                    0.000000 |
| M1      |                             0.007918 |                                        0.045006 |                   0.818770 |                     0.054097 |               3.956237 |                              0.001087 |                                        -0.000236 |                             -0.000488 |                   -0.000085 |
| M2      |                             0.008082 |                                        0.042135 |                   0.805825 |                     0.050504 |               3.977381 |                              0.000923 |                                         0.002635 |                              0.003105 |                   -0.021228 |

M0 pooled P90 coverage范围=`89.0712%`至`91.1716%`，P95范围=`93.4690%`至`95.7991%`。总体上仍接近90%/95%，但N-P95=`93.4690%`，且逐星worst P95=`81.2298%`，因此不是无条件stable transfer。

## 3. 三颗重点卫星：M0/M1/M2 P95

|   NORAD_CAT_ID | model   | target                 |   n |   observed_coverage |   coverage_error |   pinball_loss |
|---------------:|:--------|:-----------------------|----:|--------------------:|-----------------:|---------------:|
|          48309 | M0      | abs_delta_N_km         | 308 |            0.977273 |         0.027273 |       0.014398 |
|          48309 | M1      | abs_delta_N_km         | 308 |            0.980519 |         0.030519 |       0.014701 |
|          48309 | M2      | abs_delta_N_km         | 308 |            0.987013 |         0.037013 |       0.016621 |
|          48309 | M0      | abs_delta_R_km         | 308 |            0.951299 |         0.001299 |       0.062532 |
|          48309 | M1      | abs_delta_R_km         | 308 |            0.951299 |         0.001299 |       0.062753 |
|          48309 | M2      | abs_delta_R_km         | 308 |            0.977273 |         0.027273 |       0.084042 |
|          48309 | M0      | abs_delta_T_km         | 308 |            0.944805 |        -0.005195 |       2.382580 |
|          48309 | M1      | abs_delta_T_km         | 308 |            0.944805 |        -0.005195 |       2.363848 |
|          48309 | M2      | abs_delta_T_km         | 308 |            0.990260 |         0.040260 |       4.159519 |
|          48309 | M0      | position_error_norm_km | 308 |            0.944805 |        -0.005195 |       2.382696 |
|          48309 | M1      | position_error_norm_km | 308 |            0.944805 |        -0.005195 |       2.363966 |
|          48309 | M2      | position_error_norm_km | 308 |            0.990260 |         0.040260 |       4.162506 |
|          48458 | M0      | abs_delta_N_km         | 300 |            0.886667 |        -0.063333 |       0.038750 |
|          48458 | M1      | abs_delta_N_km         | 300 |            0.890000 |        -0.060000 |       0.038260 |
|          48458 | M2      | abs_delta_N_km         | 300 |            0.926667 |        -0.023333 |       0.033547 |
|          48458 | M0      | abs_delta_R_km         | 300 |            0.983333 |         0.033333 |       0.025697 |
|          48458 | M1      | abs_delta_R_km         | 300 |            0.990000 |         0.040000 |       0.025924 |
|          48458 | M2      | abs_delta_R_km         | 300 |            0.996667 |         0.046667 |       0.029730 |
|          48458 | M0      | abs_delta_T_km         | 300 |            0.963333 |         0.013333 |       1.286541 |
|          48458 | M1      | abs_delta_T_km         | 300 |            0.963333 |         0.013333 |       1.311084 |
|          48458 | M2      | abs_delta_T_km         | 300 |            0.993333 |         0.043333 |       1.513596 |
|          48458 | M0      | position_error_norm_km | 300 |            0.963333 |         0.013333 |       1.285009 |
|          48458 | M1      | position_error_norm_km | 300 |            0.963333 |         0.013333 |       1.309552 |
|          48458 | M2      | position_error_norm_km | 300 |            0.993333 |         0.043333 |       1.515898 |
|          60265 | M0      | abs_delta_N_km         | 309 |            0.812298 |        -0.137702 |       0.026092 |
|          60265 | M1      | abs_delta_N_km         | 309 |            0.818770 |        -0.131230 |       0.025331 |
|          60265 | M2      | abs_delta_N_km         | 309 |            0.805825 |        -0.144175 |       0.027591 |
|          60265 | M0      | abs_delta_R_km         | 309 |            0.932039 |        -0.017961 |       0.053621 |
|          60265 | M1      | abs_delta_R_km         | 309 |            0.925566 |        -0.024434 |       0.054561 |
|          60265 | M2      | abs_delta_R_km         | 309 |            0.983819 |         0.033819 |       0.064828 |
|          60265 | M0      | abs_delta_T_km         | 309 |            0.915858 |        -0.034142 |       4.312468 |
|          60265 | M1      | abs_delta_T_km         | 309 |            0.919094 |        -0.030906 |       4.295372 |
|          60265 | M2      | abs_delta_T_km         | 309 |            0.970874 |         0.020874 |       4.732527 |
|          60265 | M0      | position_error_norm_km | 309 |            0.915858 |        -0.034142 |       4.311793 |
|          60265 | M1      | position_error_norm_km | 309 |            0.919094 |        -0.030906 |       4.294587 |
|          60265 | M2      | position_error_norm_km | 309 |            0.970874 |         0.020874 |       4.732635 |

- 48458：N-P95从`88.667%`升至`92.667%`（`+4.000`个百分点），更接近95%；但T与position norm分别`+3.000`和`+3.000`个百分点，均从轻度overcoverage变为更强overcoverage。April scale只在N方向转移，整体不是稳定优于M0。
- 60265：T与position norm P95均从`91.586%`升至`97.087%`（`+5.502`个百分点），更接近目标；N却从`81.230%`降至`80.583%`，严重undercoverage未改善。属于component-specific partial transfer。
- 48309：M0的R/T/N/norm P95已分别为`95.130%`/`94.481%`/`97.727%`/`94.481%`，April undercoverage在May明显恢复；M2把T/norm推到`99.026%`，不再显示明显必要性。这不支持48309存在稳定的satellite-wide scale。

这里所有M2阈值都直接使用 April satellite factor；没有使用May observed tendency修正prediction。

## 4. 全20星 satellite-scale persistence

May observed tendency定义为：每颗星上 `observed absolute residual / April M0 prediction` 的相应经验quantile。它只用于评价April factor的排序预测意义，不进入M2 prediction。

| target                 |   quantile |   spearman_rank_correlation |   pearson_log_scale_correlation |
|:-----------------------|-----------:|----------------------------:|--------------------------------:|
| abs_delta_R_km         |   0.900000 |                    0.434586 |                        0.415184 |
| abs_delta_R_km         |   0.950000 |                    0.187970 |                        0.169432 |
| abs_delta_T_km         |   0.900000 |                    0.248120 |                        0.150695 |
| abs_delta_T_km         |   0.950000 |                    0.181955 |                        0.092767 |
| abs_delta_N_km         |   0.900000 |                    0.589474 |                        0.746901 |
| abs_delta_N_km         |   0.950000 |                    0.685714 |                        0.786846 |
| position_error_norm_km |   0.900000 |                    0.251128 |                        0.149726 |
| position_error_norm_km |   0.950000 |                    0.181955 |                        0.092440 |

P95 Spearman在R/T/N/norm分别为`0.188`/`0.182`/`0.686`/`0.182`：只有N方向保留较明显跨月排序，其他方向较弱。

M2相对M0将跨target/quantile平均逐星absolute calibration error改善`0.263`个百分点、coverage dispersion降低`0.310`个百分点；但worst-satellite P95从`81.230%`降至`80.583%`，平均pinball变化=`+0.021228 km`（正值表示loss增加）。综合结论：`PARTIALLY_SUPPORTED`。

## 5. Freshness-bin 与月内时间稳定性

Frozen bins的P95结果：

| model   | target                 | freshness_bin   |    n |   satellite_count |   observed_coverage |   coverage_error |
|:--------|:-----------------------|:----------------|-----:|------------------:|--------------------:|-----------------:|
| M0      | abs_delta_R_km         | 12-18 h         | 1629 |                20 |             0.94475 |         -0.00525 |
| M0      | abs_delta_R_km         | 9-12 h          | 1133 |                20 |             0.94086 |         -0.00914 |
| M0      | abs_delta_R_km         | 18-24 h         |  859 |                20 |             0.95227 |          0.00227 |
| M0      | abs_delta_R_km         | 24-36 h         |  456 |                20 |             0.95175 |          0.00175 |
| M0      | abs_delta_R_km         | 0-6 h           |  811 |                20 |             0.94698 |         -0.00302 |
| M0      | abs_delta_R_km         | 6-9 h           | 1206 |                20 |             0.95025 |          0.00025 |
| M1      | abs_delta_R_km         | 12-18 h         | 1629 |                20 |             0.93923 |         -0.01077 |
| M1      | abs_delta_R_km         | 9-12 h          | 1133 |                20 |             0.93822 |         -0.01178 |
| M1      | abs_delta_R_km         | 18-24 h         |  859 |                20 |             0.94529 |         -0.00471 |
| M1      | abs_delta_R_km         | 24-36 h         |  456 |                20 |             0.95175 |          0.00175 |
| M1      | abs_delta_R_km         | 0-6 h           |  811 |                20 |             0.95314 |          0.00314 |
| M1      | abs_delta_R_km         | 6-9 h           | 1206 |                20 |             0.95025 |          0.00025 |
| M2      | abs_delta_R_km         | 12-18 h         | 1629 |                20 |             0.93616 |         -0.01384 |
| M2      | abs_delta_R_km         | 9-12 h          | 1133 |                20 |             0.92939 |         -0.02061 |
| M2      | abs_delta_R_km         | 18-24 h         |  859 |                20 |             0.94994 |         -0.00006 |
| M2      | abs_delta_R_km         | 24-36 h         |  456 |                20 |             0.94518 |         -0.00482 |
| M2      | abs_delta_R_km         | 0-6 h           |  811 |                20 |             0.94698 |         -0.00302 |
| M2      | abs_delta_R_km         | 6-9 h           | 1206 |                20 |             0.94693 |         -0.00307 |
| M0      | abs_delta_T_km         | 12-18 h         | 1629 |                20 |             0.95703 |          0.00703 |
| M0      | abs_delta_T_km         | 9-12 h          | 1133 |                20 |             0.94881 |         -0.00119 |
| M0      | abs_delta_T_km         | 18-24 h         |  859 |                20 |             0.95460 |          0.00460 |
| M0      | abs_delta_T_km         | 24-36 h         |  456 |                20 |             0.95175 |          0.00175 |
| M0      | abs_delta_T_km         | 0-6 h           |  811 |                20 |             0.96917 |          0.01917 |
| M0      | abs_delta_T_km         | 6-9 h           | 1206 |                20 |             0.96517 |          0.01517 |
| M1      | abs_delta_T_km         | 12-18 h         | 1629 |                20 |             0.95457 |          0.00457 |
| M1      | abs_delta_T_km         | 9-12 h          | 1133 |                20 |             0.94793 |         -0.00207 |
| M1      | abs_delta_T_km         | 18-24 h         |  859 |                20 |             0.95576 |          0.00576 |
| M1      | abs_delta_T_km         | 24-36 h         |  456 |                20 |             0.93640 |         -0.01360 |
| M1      | abs_delta_T_km         | 0-6 h           |  811 |                20 |             0.96917 |          0.01917 |
| M1      | abs_delta_T_km         | 6-9 h           | 1206 |                20 |             0.96766 |          0.01766 |
| M2      | abs_delta_T_km         | 12-18 h         | 1629 |                20 |             0.94782 |         -0.00218 |
| M2      | abs_delta_T_km         | 9-12 h          | 1133 |                20 |             0.93645 |         -0.01355 |
| M2      | abs_delta_T_km         | 18-24 h         |  859 |                20 |             0.94529 |         -0.00471 |
| M2      | abs_delta_T_km         | 24-36 h         |  456 |                20 |             0.94298 |         -0.00702 |
| M2      | abs_delta_T_km         | 0-6 h           |  811 |                20 |             0.97041 |          0.02041 |
| M2      | abs_delta_T_km         | 6-9 h           | 1206 |                20 |             0.96683 |          0.01683 |
| M0      | abs_delta_N_km         | 12-18 h         | 1629 |                20 |             0.93738 |         -0.01262 |
| M0      | abs_delta_N_km         | 9-12 h          | 1133 |                20 |             0.93292 |         -0.01708 |
| M0      | abs_delta_N_km         | 18-24 h         |  859 |                20 |             0.93481 |         -0.01519 |
| M0      | abs_delta_N_km         | 24-36 h         |  456 |                20 |             0.90132 |         -0.04868 |
| M0      | abs_delta_N_km         | 0-6 h           |  811 |                20 |             0.92478 |         -0.02522 |
| M0      | abs_delta_N_km         | 6-9 h           | 1206 |                20 |             0.95191 |          0.00191 |
| M1      | abs_delta_N_km         | 12-18 h         | 1629 |                20 |             0.94107 |         -0.00893 |
| M1      | abs_delta_N_km         | 9-12 h          | 1133 |                20 |             0.93380 |         -0.01620 |
| M1      | abs_delta_N_km         | 18-24 h         |  859 |                20 |             0.93714 |         -0.01286 |
| M1      | abs_delta_N_km         | 24-36 h         |  456 |                20 |             0.90570 |         -0.04430 |
| M1      | abs_delta_N_km         | 0-6 h           |  811 |                20 |             0.92848 |         -0.02152 |
| M1      | abs_delta_N_km         | 6-9 h           | 1206 |                20 |             0.95108 |          0.00108 |
| M2      | abs_delta_N_km         | 12-18 h         | 1629 |                20 |             0.93616 |         -0.01384 |
| M2      | abs_delta_N_km         | 9-12 h          | 1133 |                20 |             0.93469 |         -0.01531 |
| M2      | abs_delta_N_km         | 18-24 h         |  859 |                20 |             0.92899 |         -0.02101 |
| M2      | abs_delta_N_km         | 24-36 h         |  456 |                20 |             0.87939 |         -0.07061 |
| M2      | abs_delta_N_km         | 0-6 h           |  811 |                20 |             0.93711 |         -0.01289 |
| M2      | abs_delta_N_km         | 6-9 h           | 1206 |                20 |             0.95108 |          0.00108 |
| M0      | position_error_norm_km | 12-18 h         | 1629 |                20 |             0.95703 |          0.00703 |
| M0      | position_error_norm_km | 9-12 h          | 1133 |                20 |             0.94881 |         -0.00119 |
| M0      | position_error_norm_km | 18-24 h         |  859 |                20 |             0.95460 |          0.00460 |
| M0      | position_error_norm_km | 24-36 h         |  456 |                20 |             0.95175 |          0.00175 |
| M0      | position_error_norm_km | 0-6 h           |  811 |                20 |             0.96917 |          0.01917 |
| M0      | position_error_norm_km | 6-9 h           | 1206 |                20 |             0.96517 |          0.01517 |
| M1      | position_error_norm_km | 12-18 h         | 1629 |                20 |             0.95457 |          0.00457 |
| M1      | position_error_norm_km | 9-12 h          | 1133 |                20 |             0.94793 |         -0.00207 |
| M1      | position_error_norm_km | 18-24 h         |  859 |                20 |             0.95576 |          0.00576 |
| M1      | position_error_norm_km | 24-36 h         |  456 |                20 |             0.93640 |         -0.01360 |
| M1      | position_error_norm_km | 0-6 h           |  811 |                20 |             0.96917 |          0.01917 |
| M1      | position_error_norm_km | 6-9 h           | 1206 |                20 |             0.96600 |          0.01600 |
| M2      | position_error_norm_km | 12-18 h         | 1629 |                20 |             0.94843 |         -0.00157 |
| M2      | position_error_norm_km | 9-12 h          | 1133 |                20 |             0.93645 |         -0.01355 |
| M2      | position_error_norm_km | 18-24 h         |  859 |                20 |             0.94529 |         -0.00471 |
| M2      | position_error_norm_km | 24-36 h         |  456 |                20 |             0.94298 |         -0.00702 |
| M2      | position_error_norm_km | 0-6 h           |  811 |                20 |             0.96917 |          0.01917 |
| M2      | position_error_norm_km | 6-9 h           | 1206 |                20 |             0.96683 |          0.01683 |

May 1-15 / May 16-31的P95结果：

| model   | target                 | time_half   |    n |   satellite_count |   observed_coverage |   coverage_error |
|:--------|:-----------------------|:------------|-----:|------------------:|--------------------:|-----------------:|
| M0      | abs_delta_R_km         | MAY_01_15   | 2882 |                20 |             0.96461 |          0.01461 |
| M0      | abs_delta_R_km         | MAY_16_31   | 3212 |                20 |             0.93120 |         -0.01880 |
| M1      | abs_delta_R_km         | MAY_01_15   | 2882 |                20 |             0.96322 |          0.01322 |
| M1      | abs_delta_R_km         | MAY_16_31   | 3212 |                20 |             0.92839 |         -0.02161 |
| M2      | abs_delta_R_km         | MAY_01_15   | 2882 |                20 |             0.96322 |          0.01322 |
| M2      | abs_delta_R_km         | MAY_16_31   | 3212 |                20 |             0.92123 |         -0.02877 |
| M0      | abs_delta_T_km         | MAY_01_15   | 2882 |                20 |             0.96669 |          0.01669 |
| M0      | abs_delta_T_km         | MAY_16_31   | 3212 |                20 |             0.95019 |          0.00019 |
| M1      | abs_delta_T_km         | MAY_01_15   | 2882 |                20 |             0.96565 |          0.01565 |
| M1      | abs_delta_T_km         | MAY_16_31   | 3212 |                20 |             0.94863 |         -0.00137 |
| M2      | abs_delta_T_km         | MAY_01_15   | 2882 |                20 |             0.96947 |          0.01947 |
| M2      | abs_delta_T_km         | MAY_16_31   | 3212 |                20 |             0.93587 |         -0.01413 |
| M0      | abs_delta_N_km         | MAY_01_15   | 2882 |                20 |             0.94587 |         -0.00413 |
| M0      | abs_delta_N_km         | MAY_16_31   | 3212 |                20 |             0.92466 |         -0.02534 |
| M1      | abs_delta_N_km         | MAY_01_15   | 2882 |                20 |             0.94795 |         -0.00205 |
| M1      | abs_delta_N_km         | MAY_16_31   | 3212 |                20 |             0.92684 |         -0.02316 |
| M2      | abs_delta_N_km         | MAY_01_15   | 2882 |                20 |             0.94656 |         -0.00344 |
| M2      | abs_delta_N_km         | MAY_16_31   | 3212 |                20 |             0.92217 |         -0.02783 |
| M0      | position_error_norm_km | MAY_01_15   | 2882 |                20 |             0.96669 |          0.01669 |
| M0      | position_error_norm_km | MAY_16_31   | 3212 |                20 |             0.95019 |          0.00019 |
| M1      | position_error_norm_km | MAY_01_15   | 2882 |                20 |             0.96530 |          0.01530 |
| M1      | position_error_norm_km | MAY_16_31   | 3212 |                20 |             0.94832 |         -0.00168 |
| M2      | position_error_norm_km | MAY_01_15   | 2882 |                20 |             0.96947 |          0.01947 |
| M2      | position_error_norm_km | MAY_16_31   | 3212 |                20 |             0.93587 |         -0.01413 |

M0 freshness transferability：`PARTIALLY_SUPPORTED`。May后半月的M0 P95相对前半月在R/T/N/norm分别变化`-3.341`/`-1.650`/`-2.121`/`-1.650`个百分点，显示月内时间差异。

M1 publication-age transferability：`NOT_SUPPORTED`。相对M0，pooled absolute calibration error平均改善仅`0.109`个百分点，但逐星absolute error变化=`-0.024`个百分点、dispersion变化=`+0.049`个百分点、平均pinball loss变化=`+0.000085 km`；没有形成跨层级一致增益。

## 6. Extreme residual 与 reference availability

May最大position norm=`2178.659816 km`，NORAD=`65410`，evaluation_time=`2026-05-26T08:37:42.000010+00:00`，element age=`23.108382 h`，support=`PRIMARY_EXTERNAL_VALIDATION`。该行自然进入其适用的正式validation，没有删除、winsorize、episode filtering或maneuver labeling。

| model   |   satellite_n |   extreme_prediction_km |   exceedance_count_with_extreme |   coverage_with_extreme |   coverage_without_single_extreme |   single_row_coverage_effect_percentage_points |
|:--------|--------------:|------------------------:|--------------------------------:|------------------------:|----------------------------------:|-----------------------------------------------:|
| M0      |           307 |               31.715253 |                              41 |                0.866450 |                          0.869281 |                                      -0.283153 |
| M2      |           307 |               33.084798 |                              40 |                0.869707 |                          0.872549 |                                      -0.284218 |

该单行使65410 position-norm P95 coverage下降约`0.283`个百分点；但该星M0/M2分别共有`41`/`40`个P95 exceedances，因此coverage问题不是由2178 km单行独占。这里只做satellite/time localization，不定义May episode或maneuver。

May 13真实existing rows=`17`；20.516667 h cohort-wide pause只作为provenance fact保留，没有插值、填补或创建evaluation rows。absence of rows不作为model success证据。

Outside-support descriptive overall：

| NORAD_CAT_ID   |   n |   satellite_count |   element_age_min_h |   element_age_median_h |   element_age_max_h |   position_norm_min_km |   position_norm_median_km |   position_norm_p95_km |   position_norm_max_km |   velocity_norm_min_km_s |   velocity_norm_median_km_s |   velocity_norm_p95_km_s |   velocity_norm_max_km_s | support_status                             |   formal_prediction_count | coverage_scored   |
|:---------------|----:|------------------:|--------------------:|-----------------------:|--------------------:|-----------------------:|--------------------------:|-----------------------:|-----------------------:|-------------------------:|----------------------------:|-------------------------:|-------------------------:|:-------------------------------------------|--------------------------:|:------------------|
| ALL            |  87 |                15 |           36.011389 |              40.838510 |           70.896905 |               4.215682 |                 15.225608 |              65.424581 |              77.662138 |                 0.004582 |                    0.017295 |                 0.072919 |                 0.086602 | OUTSIDE_APRIL_CALIBRATED_FRESHNESS_SUPPORT |                         0 | False             |

## 7. 分层结论与研究问题

- A. M0 freshness transferability：`PARTIALLY_SUPPORTED`。
- B. M1 publication-age transferability：`NOT_SUPPORTED`。
- C. M2 satellite-scale temporal persistence：`PARTIALLY_SUPPORTED`。
- D. M3/M4 causal-regime transferability：`NOT_EVALUATED: APRIL_PARAMETER_PROVENANCE_BLOCKED`。
- E. Component-wise RTN structure：`SUPPORTED`。
- May PRIMARY median |R|/|T|/|N|=`0.125887`/`2.885746`/`0.108849 km`，T显著主导position magnitude；同时M0 P95 coverage在R/T/N分别为`94.700%`/`95.799%`/`93.469%`，说明误差与calibration都保持component-specific，而不是isotropic norm即可概括。
- M3/M4 provenance缺失不影响M0/M2的frozen prediction或回答satellite-scale persistence；它只阻止causal-regime transferability问题。
- Stage-1F decision：`可推进component-wise/multivariate uncertainty-set的结构设计，但不应冻结stable satellite-scale nominal model；需要another independent month继续检验temporal heterogeneity`。

## 8. 输出

- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_locked_coverage.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_per_satellite.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_freshness_bin.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_time_half.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_satellite_scale_persistence.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_model_comparison.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_model_recoverability.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_m3_m4_artifact_search.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_outside_support.csv`
- `outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_correctness_audit.csv`

本轮没有执行Stage-1F、May calibration、episode discovery、RMS operational modeling、synthetic B、Doppler、verifier或Monte Carlo。
