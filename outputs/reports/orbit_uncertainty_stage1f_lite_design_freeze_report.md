# Orbit Uncertainty Stage-1F-lite design and freeze report

状态：`STAGE1F_LITE_DESIGN_AND_FREEZE_COMPLETE`

本轮将April与May共同定义为development/calibration data，冻结signed 3D RTN joint uncertainty set及未来June confirmatory protocol。没有获取、打开、分析或使用June Stage-1科学数据；June scientific rows read=`0`。

## 1. 科学边界与support

- estimand：ordinary public GP propagated state relative to SpaceX-E/SupGP higher-quality historical reference；不是ground truth或true orbit covariance。
- residual sign：ordinary minus reference；RTN由SupGP/reference GCRS state定义。
- development：April 5675 rows + May 6181 rows = 11856；formal fit support=`0 < element_age_hours <= 36`，11756 rows。
- outside support=100 rows，全部保留但fit/prediction count=0；rows removed=0。
- frozen bins：`0-6 h | 6-9 h | 9-12 h | 12-18 h | 18-24 h | 24-36 h`，右端包含、左端不包含。
- primary state仅为signed position `[delta_R, delta_T, delta_N]`；velocity仅diagnostic。

June blindness preflight只检查path/metadata。Stage-1 June suspicious paths=`0`；无内容读取。仓库中的May acquisition右边界文件名和无关Sentinel pilot路径不属于当前20-Starlink Stage-1 June confirmatory data。

## 2. 两个冻结candidate

### Candidate B: JOINT_MAX_SCORE_BOX

每bin中心为component median，scale=`1.4826 * MAD`，score为三个signed centered component standardized magnitude的maximum。`c95/c99`均使用全部training legitimate scores的`numpy.quantile(method="higher")`；MAD floor=`1e-12 km`，无fallback estimator。

### Candidate E: ROBUST_EMPIRICAL_ELLIPSOID

每bin使用`MinCovDet(random_state=0, support_fraction=None)`估计signed center/covariance，Mahalanobis D2 threshold同样由全部training legitimate D2的empirical score quantile得到；没有使用Gaussian chi-square threshold。任何nonfinite/non-positive eigenvalue、singular inverse或condition number>`1e+08`均使freeze失败，不做ridge、shrinkage或pseudo-inverse。

## 3. Signed structure

April/May/combined overall：

| scope    |     n |   median_R_km |   median_T_km |   median_N_km |   median_abs_R_km |   median_abs_T_km |   median_abs_N_km |   T_dominant_fraction |   pearson_R_T |   pearson_R_N |   pearson_T_N |
|:---------|------:|--------------:|--------------:|--------------:|------------------:|------------------:|------------------:|----------------------:|--------------:|--------------:|--------------:|
| APRIL    |  5662 |     -0.030978 |       1.5415  |      0.005735 |          0.123771 |           3.02213 |          0.113191 |              0.962204 |      0.121061 |      0.024379 |     -0.00254  |
| MAY      |  6094 |     -0.035605 |       1.36924 |      0.001332 |          0.125887 |           2.88575 |          0.108849 |              0.962094 |     -0.670737 |     -0.048315 |      0.031522 |
| COMBINED | 11756 |     -0.033566 |       1.46362 |      0.003523 |          0.124722 |           2.94586 |          0.110757 |              0.962147 |     -0.60887  |     -0.03256  |      0.020777 |

Combined per-bin center/correlation：

| freshness_bin   |    n |   median_R_km |   median_T_km |   median_N_km |   robust_center_R_km |   robust_center_T_km |   robust_center_N_km |   pearson_R_T |   pearson_R_N |   pearson_T_N |   robust_eigenvalue_ratio |
|:----------------|-----:|--------------:|--------------:|--------------:|---------------------:|---------------------:|---------------------:|--------------:|--------------:|--------------:|--------------------------:|
| 0-6 h           | 1548 |     -0.029917 |      0.060362 |     -0.030712 |            -0.02853  |             0.099704 |            -0.028297 |      0.513106 |     -0.008734 |     -0.084446 |                   196.645 |
| 6-9 h           | 2466 |      0.00034  |      0.962774 |      0.00363  |            -0.004426 |             1.04398  |             0.001048 |     -0.349118 |      0.127114 |     -0.034184 |                   350.101 |
| 9-12 h          | 2308 |     -0.032472 |      1.57471  |      0.014524 |            -0.033977 |             1.44929  |             0.016673 |     -0.085665 |      0.037984 |      0.047282 |                   571.929 |
| 12-18 h         | 3163 |     -0.055135 |      2.59152  |      0.011602 |            -0.062919 |             2.5645   |             0.011773 |     -0.710488 |     -0.024882 |      0.040473 |                  1267.52  |
| 18-24 h         | 1540 |     -0.021619 |      4.88383  |      0.018143 |            -0.025297 |             4.68061  |             0.007898 |     -0.867761 |     -0.142025 |      0.075672 |                  3850.72  |
| 24-36 h         |  731 |     -0.124603 |      7.04269  |     -0.020218 |            -0.117886 |             6.80264  |            -0.025626 |     -0.724056 |      0.008357 |     -0.063413 |                  6602.94  |

T conditional center从0-6 h的约`0.060 km`增至24-36 h的约`7.043 km`，明显非零且随freshness变化；R在较旧bin呈较小negative center，N整体接近0。因此不能把joint geometry固定为全局zero-centered。R-T Spearman在April/May保持约-0.29/-0.27，但Pearson受尾部影响明显，说明correlation structure不是完全稳定常数；相关性、rotated covariance与强anisotropy共同使joint score有意义。T dominance在April、May与combined均约96.2%，但protocol没有硬编码“T永远最大”。

## 4. Internal joint validation

所有center/scale/covariance/threshold只由对应training fold拟合；没有random row split。Month-direction为April→May与May→April；LOSO为20个satellite folds；forward contiguous blocks为Apr1-15→Apr16-30、April→May1-15、April+May1-15→May16-31。

| candidate                  | validation_scheme       |   quantile |     n |   joint_coverage |   coverage_error |
|:---------------------------|:------------------------|-----------:|------:|-----------------:|-----------------:|
| JOINT_MAX_SCORE_BOX        | MONTH_DIRECTION         |       0.95 | 11756 |         0.947346 |        -0.002654 |
| JOINT_MAX_SCORE_BOX        | MONTH_DIRECTION         |       0.99 | 11756 |         0.989537 |        -0.000463 |
| ROBUST_EMPIRICAL_ELLIPSOID | MONTH_DIRECTION         |       0.95 | 11756 |         0.949898 |        -0.000102 |
| ROBUST_EMPIRICAL_ELLIPSOID | MONTH_DIRECTION         |       0.99 | 11756 |         0.989027 |        -0.000973 |
| JOINT_MAX_SCORE_BOX        | LEAVE_ONE_SATELLITE_OUT |       0.95 | 11756 |         0.949217 |        -0.000783 |
| JOINT_MAX_SCORE_BOX        | LEAVE_ONE_SATELLITE_OUT |       0.99 | 11756 |         0.989707 |        -0.000293 |
| ROBUST_EMPIRICAL_ELLIPSOID | LEAVE_ONE_SATELLITE_OUT |       0.95 | 11756 |         0.949217 |        -0.000783 |
| ROBUST_EMPIRICAL_ELLIPSOID | LEAVE_ONE_SATELLITE_OUT |       0.99 | 11756 |         0.989792 |        -0.000208 |
| JOINT_MAX_SCORE_BOX        | FORWARD_CONTIGUOUS_TIME |       0.95 |  9176 |         0.93265  |        -0.01735  |
| JOINT_MAX_SCORE_BOX        | FORWARD_CONTIGUOUS_TIME |       0.99 |  9176 |         0.981037 |        -0.008963 |
| ROBUST_EMPIRICAL_ELLIPSOID | FORWARD_CONTIGUOUS_TIME |       0.95 |  9176 |         0.934612 |        -0.015388 |
| ROBUST_EMPIRICAL_ELLIPSOID | FORWARD_CONTIGUOUS_TIME |       0.99 |  9176 |         0.980057 |        -0.009943 |

Month-direction明细：

| candidate                  | fold_id      |   quantile |    n |   joint_coverage |   coverage_error |
|:---------------------------|:-------------|-----------:|-----:|-----------------:|-----------------:|
| JOINT_MAX_SCORE_BOX        | APRIL_TO_MAY |       0.95 | 6094 |         0.9447   |        -0.0053   |
| JOINT_MAX_SCORE_BOX        | APRIL_TO_MAY |       0.99 | 6094 |         0.985395 |        -0.004605 |
| ROBUST_EMPIRICAL_ELLIPSOID | APRIL_TO_MAY |       0.95 | 6094 |         0.946012 |        -0.003988 |
| ROBUST_EMPIRICAL_ELLIPSOID | APRIL_TO_MAY |       0.99 | 6094 |         0.984739 |        -0.005261 |
| JOINT_MAX_SCORE_BOX        | MAY_TO_APRIL |       0.95 | 5662 |         0.950194 |         0.000194 |
| JOINT_MAX_SCORE_BOX        | MAY_TO_APRIL |       0.99 | 5662 |         0.993995 |         0.003995 |
| ROBUST_EMPIRICAL_ELLIPSOID | MAY_TO_APRIL |       0.95 | 5662 |         0.95408  |         0.00408  |
| ROBUST_EMPIRICAL_ELLIPSOID | MAY_TO_APRIL |       0.99 | 5662 |         0.993642 |         0.003642 |

Internal status：BOX=`PASS`；ELLIPSOID=`PASS`。判据在本轮代码中固定为month-direction与LOSO pooled P99均>=98%，且二者均无n>=100、P99<95%的structural bin。

Forward-contiguous P99仍为BOX=`98.104%`、ELLIPSOID=`98.006%`，但P95降至`93.265%`/`93.461%`；这是development nonstationarity limitation，也是June必须保留time-block与continuous-episode endpoints的原因，不用于事后改变candidate。

## 5. Numerical stability与volume

Ellipsoid全部training/final fits的最小eigenvalue=`0.0104196235 km^2`，最大condition number=`8767.5`，均通过冻结门槛。

| candidate                  | validation_scheme       |   occupancy_weighted_mean_log_volume |   equal_bin_mean_log_volume |   geometric_mean_volume_km3 |
|:---------------------------|:------------------------|-------------------------------------:|----------------------------:|----------------------------:|
| JOINT_MAX_SCORE_BOX        | FINAL_COMBINED          |                             10.1628  |                    10.5209  |                    25919.5  |
| JOINT_MAX_SCORE_BOX        | FORWARD_CONTIGUOUS_TIME |                              8.87395 |                     9.16468 |                     7143.41 |
| JOINT_MAX_SCORE_BOX        | LEAVE_ONE_SATELLITE_OUT |                             10.1753  |                    10.6239  |                    26246.9  |
| JOINT_MAX_SCORE_BOX        | MONTH_DIRECTION         |                             10.0407  |                    10.5167  |                    22942.1  |
| ROBUST_EMPIRICAL_ELLIPSOID | FINAL_COMBINED          |                              9.79799 |                    10.258   |                    17997.5  |
| ROBUST_EMPIRICAL_ELLIPSOID | FORWARD_CONTIGUOUS_TIME |                              8.57203 |                     8.92751 |                     5281.83 |
| ROBUST_EMPIRICAL_ELLIPSOID | LEAVE_ONE_SATELLITE_OUT |                              9.81496 |                    10.3202  |                    18305.6  |
| ROBUST_EMPIRICAL_ELLIPSOID | MONTH_DIRECTION         |                              9.80702 |                    10.2594  |                    18160.8  |

Ellipse/Box P99 occupancy-weighted geometric mean volume ratio：month-direction=`0.791596`、LOSO=`0.697438`、final combined=`0.694360`。稳定>=10% reduction=`True`；coverage non-degradation=`True`；new structural-bin undercoverage=`0`。

## 6. Frozen selection与parameters

- selection rule case：`CASE_3_BOTH_PASS_ELLIPSOID_EARNS_COMPLEXITY`。
- `PRIMARY_CANDIDATE_FOR_JUNE = ROBUST_EMPIRICAL_ELLIPSOID`。
- `SECONDARY_SENSITIVITY_CANDIDATE = JOINT_MAX_SCORE_BOX`。
- final parameters：April+May全部11756 support rows重新拟合两个candidate，每个6 bins，共12 rows；参数文件SHA由manifest绑定。
- June后不得根据结果交换primary/secondary；primary fail而secondary pass只能报告confirmatory failure和secondary sensitivity。

## 7. Velocity与reference diagnostics

| scope    |     n |   satellite_count |   median_abs_vR_km_s |   median_abs_vT_km_s |   median_abs_vN_km_s |   pearson_vR_vT |   pearson_vR_vN |   pearson_vT_vN |   spearman_vR_vT |   spearman_vR_vN |   spearman_vT_vN |   pearson_delta_T_delta_v_R |   spearman_delta_T_delta_v_R | primary_gate_dimension      |   velocity_operational_parameter_count |
|:---------|------:|------------------:|---------------------:|---------------------:|---------------------:|----------------:|----------------:|----------------:|-----------------:|-----------------:|-----------------:|----------------------------:|-----------------------------:|:----------------------------|---------------------------------------:|
| APRIL    |  5662 |                20 |             0.003375 |             0.000117 |             0.000123 |       -0.423619 |       -0.025318 |        0.005413 |        -0.157337 |        -0.036054 |         0.011247 |                   -0.999968 |                    -0.999013 | SIGNED_POSITION_RTN_3D_ONLY |                                      0 |
| MAY      |  6094 |                20 |             0.003208 |             0.000115 |             0.000123 |        0.567989 |       -0.154012 |       -0.361321 |        -0.124642 |        -0.024873 |         0.042702 |                   -0.999944 |                    -0.998811 | SIGNED_POSITION_RTN_3D_ONLY |                                      0 |
| COMBINED | 11756 |                20 |             0.003291 |             0.000115 |             0.000123 |        0.493482 |       -0.117969 |       -0.279166 |        -0.14012  |        -0.030184 |         0.02716  |                   -0.999947 |                    -0.998918 | SIGNED_POSITION_RTN_3D_ONLY |                                      0 |

Velocity没有进入primary gate。April/May/combined的`corr(delta_T, delta_v_R)`均接近-1，支持phase-error coupling，但也表明velocity-R与position-T高度冗余；尚无证据证明velocity会改变orbit-distinct/security conclusion。因此冻结：`6D_EXTENSION_DECISION = NOT_NEEDED_YET`。

| candidate                  | rms_quartile   |    n |   satellite_count |   rms_min_km |   rms_median_km |   rms_max_km |   normalized_score_to_c99_median |   normalized_score_to_c99_p95 |   normalized_score_to_c99_p99 |   p95_joint_coverage |   p99_joint_coverage |   out_of_u95_frequency |   out_of_u99_frequency | rms_role                  |   rms_operational_parameter_count | quartile_definition                                                       |
|:---------------------------|:---------------|-----:|------------------:|-------------:|----------------:|-------------:|---------------------------------:|------------------------------:|------------------------------:|---------------------:|---------------------:|-----------------------:|-----------------------:|:--------------------------|----------------------------------:|:--------------------------------------------------------------------------|
| ROBUST_EMPIRICAL_ELLIPSOID | RMS_Q1         | 2939 |                20 |        0.106 |           0.16  |        0.172 |                         0.002195 |                      0.024497 |                      0.386526 |             0.960191 |             0.992514 |               0.039809 |               0.007486 | REFERENCE_ONLY_DIAGNOSTIC |                                 0 | combined-development rank(method=first) qcut into four equal-count groups |
| ROBUST_EMPIRICAL_ELLIPSOID | RMS_Q2         | 2939 |                20 |        0.172 |           0.182 |        0.194 |                         0.001907 |                      0.020568 |                      0.576331 |             0.95951  |             0.992174 |               0.04049  |               0.007826 | REFERENCE_ONLY_DIAGNOSTIC |                                 0 | combined-development rank(method=first) qcut into four equal-count groups |
| ROBUST_EMPIRICAL_ELLIPSOID | RMS_Q3         | 2939 |                20 |        0.194 |           0.21  |        0.225 |                         0.001977 |                      0.025694 |                      1.77353  |             0.956448 |             0.988431 |               0.043552 |               0.011569 | REFERENCE_ONLY_DIAGNOSTIC |                                 0 | combined-development rank(method=first) qcut into four equal-count groups |
| ROBUST_EMPIRICAL_ELLIPSOID | RMS_Q4         | 2939 |                20 |        0.225 |           0.255 |        1.778 |                         0.002263 |                      0.078089 |                      1.26072  |             0.924804 |             0.987751 |               0.075196 |               0.012249 | REFERENCE_ONLY_DIAGNOSTIC |                                 0 | combined-development rank(method=first) qcut into four equal-count groups |

SupGP RMS始终为`REFERENCE_ONLY`；没有RMS cutoff、adjustment或RMS-dependent set。
RMS_Q4的development P95 coverage较低（`92.480%`），P99仍为`98.775%`；记录为reference-sensitivity limitation，不据此调整operational set。

## 8. Frozen June confirmatory protocol

PRIMARY endpoint为P99 joint legitimate coverage及`1-P99` legitimate false-orbit-distinct rate；SECONDARY为P95、frozen-bin coverage、per-satellite distribution、June halves、continuous episodes、volume、signed structure和T-dominance；SUPPORTIVE为satellite ranking、velocity coupling及RMS sensitivity。

June success rule（在读取June前冻结）：primary pooled P99>=98%；任何n>=100 bin若P99<95%则`STRUCTURAL_BIN_UNDERCOVERAGE`；n<100只报告point estimate与uncertainty。Satellite-cluster bootstrap固定为从June出现的satellite IDs中有放回抽取同样数量的satellite clusters，重复cluster保留全部rows并按抽样次数重复计权；2000次、seed=20260601，使用2.5%/97.5% empirical percentile（`numpy.quantile(method="linear")`）。June halves固定为`[June 1, June 16)`与`[June 16, July 1)`。不得June fitting，不得>36 h extrapolation，也不得June后增加primary endpoint。

Decision semantics：score<=c95为`NOT_ORBIT_DISTINCT`；c95<score<=c99为`AMBIGUOUS`；score>c99为`ORBIT_DISTINCT`；age<=0或age>36 h为`OUTSIDE_CALIBRATED_SUPPORT / DEFER`。P99是本研究为降低legitimate false-orbit-distinct而采用的conservative engineering gate，不是航天行业统一标准。

Continuous out-of-set episode定义为每颗卫星按真实evaluation time排序后的maximal consecutive outside rows；in-set row或相邻观测gap>6 h即断开，不插值。报告U95/U99最大持续时间、U99 episode数及每个episode的NORAD/start/end/duration/row count/max score，不称为maneuver。

Satellite rule：不要求每颗星精确99%；只有同一satellite在至少两个external periods重复出现同方向严重failure，才重新考虑subgroup effect，不因June单星一次点估计重启M2。

## 9. Stopping rules

June后若freshness未定性失效、RTN anisotropy未反转、primary达到冻结coverage要求、常用bin无持续严重undercoverage、复杂度比较完成、无新的stable satellite-wide scale证据、regime classifier不是security结论必要条件、RMS sensitivity不反转主要结论，则记为`ORBIT_UNCERTAINTY_BRANCH_COMPLETE`，停止M5/M6、逐星调参、regime tuning和更多月份predictor search，进入orbit-distinct→Doppler distinguishability→security analysis。

未来synthetic-B阶段，若simple primary与complex sensitivity仅改变少量boundary cases且不反转主要orbit-distinct region或Doppler security conclusion，不得重启Orbit Uncertainty predictor optimization。

## 10. 结论与下一步

两个candidate定义完整、internal validation完成、selection rule已执行、final parameters已冻结、June endpoints/pass-fail/stopping rules已在任何June Stage-1科学数据读取前冻结。当前可申请下一步：`JUNE CONFIRMATORY DATA ACQUISITION`。

本轮没有执行M1/M2/M3/M4、6D set、chi-square threshold、outlier/episode filtering、synthetic B、Doppler、Monte Carlo或verifier。
