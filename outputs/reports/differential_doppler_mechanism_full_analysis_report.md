# 目标卫星—非目标卫星差分多普勒全量机制分析报告

## 1. 目的与冻结口径

本轮把前一轮指标定义扩展到旧正式实验的全部样本，保持 60 秒服务段、segment-local、fixed-site、single-window、原服务中心与验证站、原阈值和原判决。没有新增攻击、handover、多站或尺度扫描。纯几何残差仍为 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。

正式 verifier 指标、无边界纯几何投影、几何容忍预算三类量严格分开。current/wide 正式使用同一无边界 b+kt 拟合；容忍预算 box 只是解释量，不是重新计算的正式 score。

## 2. 样本支持与全量清单

纳入 62 个来源/分组条件实例、37 个物理 `pair_id`。同一真实物理 pair 可能同时带 ordinary/boundary 标签；grouped validation 按物理 `pair_id` 整体留出以防泄漏。

| sample_source      | sample_group       |   pair_instances |
|:-------------------|:-------------------|-----------------:|
| legacy_synthetic   | hard_case_weighted |                6 |
| legacy_synthetic   | original_like      |                6 |
| real_tle_candidate | boundary_case      |               25 |
| real_tle_candidate | ordinary_similar   |               25 |

每个实例保留旧数据实际存在的 4～5 个服务区、全部距离/方向及 no/current/wide；未插值。真实轨道局部正例稀疏，因此置信区间和分来源结果优先于点估计。

## 3. 正确性审计

| check                            | passed   | observed                                                                                                                                                           | tolerance                                                                                                                                                                              | notes                        |
|:---------------------------------|:---------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------------------|
| 全量组合及分组数量               | True     | {"legacy_synthetic|hard_case_weighted": 6, "legacy_synthetic|original_like": 6, "real_tle_candidate|boundary_case": 25, "real_tle_candidate|ordinary_similar": 25} | {('real_tle_candidate', 'ordinary_similar'): 25, ('real_tle_candidate', 'boundary_case'): 25, ('legacy_synthetic', 'original_like'): 6, ('legacy_synthetic', 'hard_case_weighted'): 6} | 62为组条件实例；物理pair另计 |
| d=0距离误差                      | True     | 0.0                                                                                                                                                                | <=1e-6 km                                                                                                                                                                              |                              |
| d=0原始几何残差                  | True     | 1.595802357738639e-06                                                                                                                                              | <=1e-3 Hz                                                                                                                                                                              |                              |
| no_bk恒等                        | True     | 0                                                                                                                                                                  | b=k=0且post=raw                                                                                                                                                                        |                              |
| 无边界拟合RMSE不增               | True     | -2.370776714020872e-10                                                                                                                                             | <=1e-8 Hz                                                                                                                                                                              |                              |
| 容忍预算参数满足box              | True     | 0                                                                                                                                                                  | 0 violations                                                                                                                                                                           |                              |
| wide容忍预算残差不高于current    | True     | 0.0                                                                                                                                                                | <=1e-8 Hz                                                                                                                                                                              |                              |
| 正式判决重放一致率               | True     | 1.0                                                                                                                                                                | 100%                                                                                                                                                                                   |                              |
| current/wide正式score相同        | True     | 0.0                                                                                                                                                                | <=1e-9 Hz                                                                                                                                                                              |                              |
| current/wide正式b_hat相同        | True     | 0.0                                                                                                                                                                | <=1e-9 Hz                                                                                                                                                                              |                              |
| current/wide正式k_hat相同        | True     | 0.0                                                                                                                                                                | <=1e-12 Hz/s                                                                                                                                                                           |                              |
| wide正式b/k gate为current超集    | True     | 0                                                                                                                                                                  | 0 violations                                                                                                                                                                           |                              |
| 0.5/1/2km有限差分稳定            | True     | 0.0020133255710179                                                                                                                                                 | <=15%                                                                                                                                                                                  |                              |
| ENU方向角及km/m                  | True     | 2.4300561562995426e-12                                                                                                                                             | 0°北/90°东/顺时针；<=1e-6km                                                                                                                                                            |                              |
| 吸收比例范围                     | True     | 0                                                                                                                                                                  | [0,1]浮点容差                                                                                                                                                                          |                              |
| 不同输出主键唯一性               | True     | {"inventory": 0, "rows": 0, "pair_area": 0, "repeatability": 0, "representative_timeseries": 0}                                                                    | all zero                                                                                                                                                                               |                              |
| grouped validation无物理pair泄漏 | True     | 0                                                                                                                                                                  | 0 overlap                                                                                                                                                                              |                              |

判决重放一致率 100.00%。只有全部审计通过时，第 12 节才给出正式停止判断。

## 4. 分组样本外验证方法

局部主分析限定 current_bk、`0<d<=10 km`，d=0 只用于数值审计。leave-one-pair-out 以物理 `pair_id` 留出，防止同一真实轨道对的不同样本标签跨训练/测试；leave-one-target-out 完整留出目标卫星。bootstrap 以物理 pair 为重采样单位，固定 seed，1000 次。合并辅助模型加入 sample_group one-hot；主要证据仍来自分来源/分组模型。

## 5. 局部区域主要 OOF 结果

| stratum        | validation           | model                                                               |    n |   positive_n |   pair_n |   target_n |     roc_auc |   roc_auc_ci_low |   roc_auc_ci_high |      pr_auc |   pr_auc_ci_low |   pr_auc_ci_high |   balanced_accuracy |   brier_score | status   |
|:---------------|:---------------------|:--------------------------------------------------------------------|-----:|-------------:|---------:|-----------:|------------:|-----------------:|------------------:|------------:|----------------:|-----------------:|--------------------:|--------------:|:---------|
| real_all       | leave_one_pair_out   | M3_distance_tolerance_absorption                                    | 5760 |           22 |       25 |          5 |  0.987214   |       0.982428   |        0.991207   |  0.137695   |     0.08957     |        0.229933  |            0.5      |    0.00355685 | ok       |
| real_all       | leave_one_target_out | M3_distance_tolerance_absorption                                    | 5760 |           22 |       25 |          5 |  0.973431   |       0.966671   |        0.981049   |  0.0788033  |     0.0518022   |        0.132774  |            0.5      |    0.00360937 | ok       |
| real_all       | leave_one_pair_out   | M7_unbounded_post_rmse                                              | 5760 |           22 |       25 |          5 |  0.979483   |       0.967067   |        0.990365   |  0.118886   |     0.0708296   |        0.203927  |            0.5      |    0.00368377 | ok       |
| real_all       | leave_one_target_out | M7_unbounded_post_rmse                                              | 5760 |           22 |       25 |          5 |  0.960819   |       0.95134    |        0.972781   |  0.0789529  |     0.0357875   |        0.145322  |            0.5      |    0.00371173 | ok       |
| real_all       | leave_one_pair_out   | M8_formal_score                                                     | 5760 |           22 |       25 |          5 |  0.884692   |       0.856511   |        0.910527   |  0.0162493  |     0.0103365   |        0.0282101 |            0.5      |    0.00377736 | ok       |
| real_all       | leave_one_target_out | M8_formal_score                                                     | 5760 |           22 |       25 |          5 |  0.838445   |       0.801228   |        0.881545   |  0.0131198  |     0.00836213  |        0.0257532 |            0.5      |    0.00378406 | ok       |
| controlled_all | leave_one_pair_out   | M3_distance_tolerance_absorption                                    | 1248 |          863 |       12 |          4 |  0.76255    |       0.583839   |        0.891276   |  0.800123   |     0.701456    |        0.913067  |            0.734847 |    0.143229   | ok       |
| controlled_all | leave_one_target_out | M3_distance_tolerance_absorption                                    | 1248 |          863 |       12 |          4 |  0.750102   |       0.576619   |        0.892678   |  0.83345    |     0.713836    |        0.939142  |            0.666214 |    0.163088   | ok       |
| controlled_all | leave_one_pair_out   | M7_unbounded_post_rmse                                              | 1248 |          863 |       12 |          4 |  0.812542   |       0.536533   |        0.941815   |  0.849184   |     0.800416    |        0.938286  |            0.741558 |    0.12188    | ok       |
| controlled_all | leave_one_target_out | M7_unbounded_post_rmse                                              | 1248 |          863 |       12 |          4 |  0.111773   |       0.023117   |        0.325479   |  0.500545   |     0.316414    |        0.771043  |            0.5      |    0.276528   | ok       |
| controlled_all | leave_one_pair_out   | M8_formal_score                                                     | 1248 |          863 |       12 |          4 |  0.626687   |       0.289925   |        0.842207   |  0.720759   |     0.587786    |        0.910134  |            0.666614 |    0.169965   | ok       |
| controlled_all | leave_one_target_out | M8_formal_score                                                     | 1248 |          863 |       12 |          4 |  0.573397   |       0.368111   |        0.774961   |  0.748892   |     0.56911     |        0.896719  |            0.532848 |    0.224333   | ok       |
| real_all       | leave_one_pair_out   | M0_distance                                                         | 5760 |           22 |       25 |          5 |  0.749501   |       0.722945   |        0.776953   |  0.00751223 |     0.00506166  |        0.0112468 |            0.5      |    0.00377984 | ok       |
| real_all       | leave_one_target_out | M0_distance                                                         | 5760 |           22 |       25 |          5 |  0.773456   |       0.743146   |        0.8002     |  0.00854167 |     0.00571154  |        0.0126379 |            0.5      |    0.00378719 | ok       |
| real_all       | leave_one_pair_out   | M1_distance_direction                                               | 5760 |           22 |       25 |          5 |  0.984371   |       0.974832   |        0.992339   |  0.143829   |     0.0837372   |        0.244951  |            0.5      |    0.00347565 | ok       |
| real_all       | leave_one_target_out | M1_distance_direction                                               | 5760 |           22 |       25 |          5 |  0.980465   |       0.971354   |        0.988426   |  0.110494   |     0.0709042   |        0.188764  |            0.5      |    0.00353511 | ok       |
| real_all       | leave_one_pair_out   | M2_distance_unbounded_absorption                                    | 5760 |           22 |       25 |          5 |  0.789299   |       0.745685   |        0.829246   |  0.0215567  |     0.00676057  |        0.0548633 |            0.5      |    0.00382283 | ok       |
| real_all       | leave_one_target_out | M2_distance_unbounded_absorption                                    | 5760 |           22 |       25 |          5 |  0.798156   |       0.760507   |        0.837788   |  0.0170301  |     0.0078381   |        0.0327962 |            0.517586 |    0.0129243  | ok       |
| real_all       | leave_one_pair_out   | M4_distance_direction_unbounded_absorption                          | 5760 |           22 |       25 |          5 |  0.989131   |       0.979986   |        0.995077   |  0.21556    |     0.141219    |        0.360519  |            0.499826 |    0.00347834 | ok       |
| real_all       | leave_one_target_out | M4_distance_direction_unbounded_absorption                          | 5760 |           22 |       25 |          5 |  0.979324   |       0.969879   |        0.987758   |  0.0885647  |     0.0624753   |        0.17376   |            0.520897 |    0.00645371 | ok       |
| real_all       | leave_one_pair_out   | M5_distance_raw_geometry                                            | 5760 |           22 |       25 |          5 |  0.988292   |       0.982824   |        0.991935   |  0.158992   |     0.102712    |        0.252405  |            0.5      |    0.00359847 | ok       |
| real_all       | leave_one_target_out | M5_distance_raw_geometry                                            | 5760 |           22 |       25 |          5 |  0.97679    |       0.971809   |        0.983316   |  0.0851425  |     0.055899    |        0.145093  |            0.5      |    0.00364382 | ok       |
| real_all       | leave_one_pair_out   | M6_distance_raw_direction_absorption                                | 5760 |           22 |       25 |          5 |  0.98967    |       0.980845   |        0.995011   |  0.243208   |     0.165008    |        0.389992  |            0.5      |    0.00341998 | ok       |
| real_all       | leave_one_target_out | M6_distance_raw_direction_absorption                                | 5760 |           22 |       25 |          5 |  0.981162   |       0.972425   |        0.988609   |  0.0955261  |     0.0654286   |        0.173785  |            0.520897 |    0.00629949 | ok       |
| controlled_all | leave_one_pair_out   | M0_distance                                                         | 1248 |          863 |       12 |          4 |  0.35953    |       0.273723   |        0.515526   |  0.599753   |     0.399646    |        0.860532  |            0.5      |    0.23323    | ok       |
| controlled_all | leave_one_target_out | M0_distance                                                         | 1248 |          863 |       12 |          4 |  0.374494   |       0.225011   |        0.584352   |  0.640572   |     0.422165    |        0.887202  |            0.5      |    0.259626   | ok       |
| controlled_all | leave_one_pair_out   | M1_distance_direction                                               | 1248 |          863 |       12 |          4 |  0.839391   |       0.615827   |        0.94895    |  0.882441   |     0.820121    |        0.965337  |            0.747473 |    0.119938   | ok       |
| controlled_all | leave_one_target_out | M1_distance_direction                                               | 1248 |          863 |       12 |          4 |  0.120895   |       0.0387933  |        0.347013   |  0.50175    |     0.307393    |        0.777259  |            0.5      |    0.306328   | ok       |
| controlled_all | leave_one_pair_out   | M2_distance_unbounded_absorption                                    | 1248 |          863 |       12 |          4 |  0.504615   |       0.412469   |        0.659292   |  0.708294   |     0.500976    |        0.913378  |            0.480301 |    0.22146    | ok       |
| controlled_all | leave_one_target_out | M2_distance_unbounded_absorption                                    | 1248 |          863 |       12 |          4 |  0.425231   |       0.251565   |        0.624904   |  0.685633   |     0.478503    |        0.887154  |            0.495365 |    0.261455   | ok       |
| controlled_all | leave_one_pair_out   | M4_distance_direction_unbounded_absorption                          | 1248 |          863 |       12 |          4 |  0.842215   |       0.649345   |        0.95725    |  0.872922   |     0.811207    |        0.973439  |            0.747473 |    0.120358   | ok       |
| controlled_all | leave_one_target_out | M4_distance_direction_unbounded_absorption                          | 1248 |          863 |       12 |          4 |  0.130201   |       0.0320616  |        0.331942   |  0.502763   |     0.302727    |        0.772426  |            0.5      |    0.307472   | ok       |
| controlled_all | leave_one_pair_out   | M5_distance_raw_geometry                                            | 1248 |          863 |       12 |          4 |  0.818239   |       0.618983   |        0.934309   |  0.859982   |     0.801215    |        0.939786  |            0.736364 |    0.122673   | ok       |
| controlled_all | leave_one_target_out | M5_distance_raw_geometry                                            | 1248 |          863 |       12 |          4 |  0.888212   |       0.730979   |        0.970171   |  0.93161    |     0.86046     |        0.979461  |            0.793506 |    0.101417   | ok       |
| controlled_all | leave_one_pair_out   | M6_distance_raw_direction_absorption                                | 1248 |          863 |       12 |          4 |  0.851012   |       0.644884   |        0.952506   |  0.875991   |     0.812974    |        0.969039  |            0.747473 |    0.115042   | ok       |
| controlled_all | leave_one_target_out | M6_distance_raw_direction_absorption                                | 1248 |          863 |       12 |          4 |  0.660845   |       0.583242   |        0.730602   |  0.706195   |     0.519319    |        0.883641  |            0.720164 |    0.182276   | ok       |
| controlled_all | leave_one_pair_out   | DELTA:M1_distance_direction-M0_distance                             | 1248 |          863 |       12 |          4 |  0.479862   |       0.141175   |        0.656603   |  0.282688   |     0.0347427   |        0.484348  |          nan        |  nan          | ok       |
| controlled_all | leave_one_pair_out   | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 1248 |          863 |       12 |          4 |  0.145086   |       0.0608285  |        0.197006   |  0.108542   |     0.0160324   |        0.149864  |          nan        |  nan          | ok       |
| controlled_all | leave_one_pair_out   | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 1248 |          863 |       12 |          4 |  0.482685   |       0.137208   |        0.667948   |  0.27317    |     0.0248966   |        0.489857  |          nan        |  nan          | ok       |
| controlled_all | leave_one_pair_out   | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 1248 |          863 |       12 |          4 |  0.032773   |      -0.0120036  |        0.0817454  |  0.0160091  |    -0.0154003   |        0.0851972 |          nan        |  nan          | ok       |
| controlled_all | leave_one_target_out | DELTA:M1_distance_direction-M0_distance                             | 1248 |          863 |       12 |          4 | -0.253599   |      -0.445229   |       -0.0994778  | -0.138823   |    -0.208937    |       -0.0569308 |          nan        |  nan          | ok       |
| controlled_all | leave_one_target_out | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 1248 |          863 |       12 |          4 |  0.0507366  |      -0.0820116  |        0.202998   |  0.0450607  |    -0.0390829   |        0.145941  |          nan        |  nan          | ok       |
| controlled_all | leave_one_target_out | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 1248 |          863 |       12 |          4 | -0.244293   |      -0.445819   |       -0.0585292  | -0.13781    |    -0.215352    |       -0.04836   |          nan        |  nan          | ok       |
| controlled_all | leave_one_target_out | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 1248 |          863 |       12 |          4 | -0.227368   |      -0.311086   |       -0.071429   | -0.225414   |    -0.394339    |       -0.0602788 |          nan        |  nan          | ok       |
| real_all       | leave_one_pair_out   | DELTA:M1_distance_direction-M0_distance                             | 5760 |           22 |       25 |          5 |  0.23487    |       0.207334   |        0.261892   |  0.136317   |     0.0800274   |        0.232616  |          nan        |  nan          | ok       |
| real_all       | leave_one_pair_out   | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 5760 |           22 |       25 |          5 |  0.0397985  |       0.00142623 |        0.0683187  |  0.0140444  |     0.000259258 |        0.0478703 |          nan        |  nan          | ok       |
| real_all       | leave_one_pair_out   | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 5760 |           22 |       25 |          5 |  0.239631   |       0.211833   |        0.265849   |  0.208048   |     0.135226    |        0.342008  |          nan        |  nan          | ok       |
| real_all       | leave_one_pair_out   | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 5760 |           22 |       25 |          5 |  0.00137837 |      -0.00309283 |        0.00528855 |  0.0842165  |     0.0253105   |        0.184487  |          nan        |  nan          | ok       |
| real_all       | leave_one_target_out | DELTA:M1_distance_direction-M0_distance                             | 5760 |           22 |       25 |          5 |  0.207009   |       0.180343   |        0.231766   |  0.101952   |     0.0654971   |        0.178283  |          nan        |  nan          | ok       |
| real_all       | leave_one_target_out | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 5760 |           22 |       25 |          5 |  0.0246998  |      -0.00987164 |        0.069309   |  0.00848843 |    -0.000369972 |        0.02694   |          nan        |  nan          | ok       |
| real_all       | leave_one_target_out | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 5760 |           22 |       25 |          5 |  0.205868   |       0.177702   |        0.233223   |  0.080023   |     0.0534621   |        0.147136  |          nan        |  nan          | ok       |
| real_all       | leave_one_target_out | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 5760 |           22 |       25 |          5 |  0.00437276 |      -0.00499864 |        0.0122055  |  0.0103836  |    -0.0350365   |        0.0677036 |          nan        |  nan          | ok       |

重点增量为 M1-M0、M2-M0、M4-M0 与 M6-M5。M7/M8 接近最终判决，只作为上界型对照，不作为新机制宣传。真实轨道与受控样本敏感度量级不同，合并结果仅辅助。

## 6. 方向敏感度与吸收比例的泛化

方向是否优于距离、吸收是否对未知 pair 有效，以各来源 LOPO 的 delta 区间判断，而不是行随机拆分。详细结果见 `differential_doppler_mechanism_full_grouped_validation.csv`。组内 Spearman、同距离均值/中位数和 pair-cluster effect 区间见 `differential_doppler_mechanism_full_group_comparison.csv`。

| stratum             | model                                                               |    n |     roc_auc |   roc_auc_ci_low |   roc_auc_ci_high |       pr_auc |   pr_auc_ci_low |   pr_auc_ci_high |
|:--------------------|:--------------------------------------------------------------------|-----:|------------:|-----------------:|------------------:|-------------:|----------------:|-----------------:|
| controlled_all      | DELTA:M1_distance_direction-M0_distance                             | 1248 |  0.479862   |      0.141175    |        0.656603   |  0.282688    |     0.0347427   |       0.484348   |
| controlled_all      | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 1248 |  0.145086   |      0.0608285   |        0.197006   |  0.108542    |     0.0160324   |       0.149864   |
| controlled_all      | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 1248 |  0.482685   |      0.137208    |        0.667948   |  0.27317     |     0.0248966   |       0.489857   |
| controlled_all      | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 1248 |  0.032773   |     -0.0120036   |        0.0817454  |  0.0160091   |    -0.0154003   |       0.0851972  |
| controlled_hard     | DELTA:M1_distance_direction-M0_distance                             |  672 | -0.0579497  |     -0.288795    |       -0.0156645  | -0.00970495  |    -0.0484952   |       0.00805453 |
| controlled_hard     | DELTA:M2_distance_unbounded_absorption-M0_distance                  |  672 | -0.0141892  |     -0.0599202   |        0.0153817  | -0.00832246  |    -0.043287    |       0.00324149 |
| controlled_hard     | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        |  672 | -0.0906461  |     -0.308787    |       -0.0186409  | -0.0205119   |    -0.0523553   |      -0.00470417 |
| controlled_hard     | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry |  672 |  0.0701225  |     -0.0962429   |        0.0934637  |  0.0300385   |    -0.00967213  |       0.0525307  |
| controlled_ordinary | DELTA:M1_distance_direction-M0_distance                             |  576 |  0.637015   |      0.163951    |        0.992786   |  0.382464    |     0.0571273   |       0.727604   |
| controlled_ordinary | DELTA:M2_distance_unbounded_absorption-M0_distance                  |  576 |  0.22384    |     -0.0130493   |        0.372069   |  0.157066    |    -0.0735929   |       0.266124   |
| controlled_ordinary | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        |  576 |  0.671024   |      0.247599    |        0.990427   |  0.462114    |     0.124999    |       0.73951    |
| controlled_ordinary | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry |  576 |  0.101603   |     -0.00927291  |        0.261069   |  0.143962    |    -0.0125449   |       0.187593   |
| real_all            | DELTA:M1_distance_direction-M0_distance                             | 5760 |  0.23487    |      0.207334    |        0.261892   |  0.136317    |     0.0800274   |       0.232616   |
| real_all            | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 5760 |  0.0397985  |      0.00142623  |        0.0683187  |  0.0140444   |     0.000259258 |       0.0478703  |
| real_all            | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 5760 |  0.239631   |      0.211833    |        0.265849   |  0.208048    |     0.135226    |       0.342008   |
| real_all            | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 5760 |  0.00137837 |     -0.00309283  |        0.00528855 |  0.0842165   |     0.0253105   |       0.184487   |
| real_boundary       | DELTA:M1_distance_direction-M0_distance                             | 2880 |  0.23245    |      0.199828    |        0.269091   |  0.119173    |     0.0670719   |       0.219602   |
| real_boundary       | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 2880 |  0.0403301  |     -0.00253322  |        0.0899639  |  0.0429661   |    -3.92049e-05 |       0.144842   |
| real_boundary       | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 2880 |  0.239017   |      0.203054    |        0.273866   |  0.158109    |     0.0873337   |       0.314713   |
| real_boundary       | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 2880 |  0.00255695 |     -0.00417449  |        0.00905611 |  0.051338    |    -0.00256859  |       0.208154   |
| real_ordinary       | DELTA:M1_distance_direction-M0_distance                             | 2880 |  0.257143   |      0.225765    |        0.287076   |  0.119381    |     0.062628    |       0.229314   |
| real_ordinary       | DELTA:M2_distance_unbounded_absorption-M0_distance                  | 2880 |  0.0162718  |     -0.00929232  |        0.0412417  |  6.09937e-05 |    -0.000719244 |       0.00205273 |
| real_ordinary       | DELTA:M4_distance_direction_unbounded_absorption-M0_distance        | 2880 |  0.255157   |      0.226852    |        0.284506   |  0.103406    |     0.0534484   |       0.188499   |
| real_ordinary       | DELTA:M6_distance_raw_direction_absorption-M5_distance_raw_geometry | 2880 |  0.00463415 |     -0.000857235 |        0.00993075 |  0.035931    |     0.00928361  |       0.079463   |

真实与受控合并来源的 LOPO 都显示 M1/M4 明显优于 M0；但四组拆开后，高难度受控组的 M1/M4 不优于距离，而普通受控组提升明显。这不是统一效应：高难度受控样本的 raw geometry 已处于很小量级，方向项的剩余区分空间有限。

leave-one-target-out 结果为：

| stratum        | model                                      |    n |   positive_n |   pair_n |   target_n |   roc_auc |     pr_auc |   balanced_accuracy |   brier_score | status   |
|:---------------|:-------------------------------------------|-----:|-------------:|---------:|-----------:|----------:|-----------:|--------------------:|--------------:|:---------|
| real_all       | M0_distance                                | 5760 |           22 |       25 |          5 |  0.773456 | 0.00854167 |            0.5      |    0.00378719 | ok       |
| real_all       | M1_distance_direction                      | 5760 |           22 |       25 |          5 |  0.980465 | 0.110494   |            0.5      |    0.00353511 | ok       |
| real_all       | M2_distance_unbounded_absorption           | 5760 |           22 |       25 |          5 |  0.798156 | 0.0170301  |            0.517586 |    0.0129243  | ok       |
| real_all       | M4_distance_direction_unbounded_absorption | 5760 |           22 |       25 |          5 |  0.979324 | 0.0885647  |            0.520897 |    0.00645371 | ok       |
| real_all       | M5_distance_raw_geometry                   | 5760 |           22 |       25 |          5 |  0.97679  | 0.0851425  |            0.5      |    0.00364382 | ok       |
| real_all       | M6_distance_raw_direction_absorption       | 5760 |           22 |       25 |          5 |  0.981162 | 0.0955261  |            0.520897 |    0.00629949 | ok       |
| controlled_all | M0_distance                                | 1248 |          863 |       12 |          4 |  0.374494 | 0.640572   |            0.5      |    0.259626   | ok       |
| controlled_all | M1_distance_direction                      | 1248 |          863 |       12 |          4 |  0.120895 | 0.50175    |            0.5      |    0.306328   | ok       |
| controlled_all | M2_distance_unbounded_absorption           | 1248 |          863 |       12 |          4 |  0.425231 | 0.685633   |            0.495365 |    0.261455   | ok       |
| controlled_all | M4_distance_direction_unbounded_absorption | 1248 |          863 |       12 |          4 |  0.130201 | 0.502763   |            0.5      |    0.307472   | ok       |
| controlled_all | M5_distance_raw_geometry                   | 1248 |          863 |       12 |          4 |  0.888212 | 0.93161    |            0.793506 |    0.101417   | ok       |
| controlled_all | M6_distance_raw_direction_absorption       | 1248 |          863 |       12 |          4 |  0.660845 | 0.706195   |            0.720164 |    0.182276   | ok       |

真实轨道跨目标仍保留方向机制增益；受控样本跨目标的 M1/M4 退化，说明受控不同目标间的几何尺度/构造差异不可由统一模型直接迁移。

## 7. raw geometry 之外的增量与难例类型

M6-M5 检查控制 raw_geo_rmse 后方向和无边界吸收的增量。二维图把难例分为：原始几何本来小；原始几何不小但主要落在常数/线性趋势；两者共同作用。`unbounded_geometry_post_rmse` 与 formal score 是上界对照，不包装成独立新指标。

| sample_source      | sample_group       | decision_group   |    n |   raw_geo_rmse_mean |   raw_geo_rmse_median |   unbounded_absorption_mean |   tolerance_absorption_mean |   direction_sensitivity_mean |
|:-------------------|:-------------------|:-----------------|-----:|--------------------:|----------------------:|----------------------------:|----------------------------:|-----------------------------:|
| legacy_synthetic   | hard_case_weighted | ACCEPT           |  592 |             2.41957 |               1.62665 |                    0.973409 |                    0.973409 |                    0.0576144 |
| legacy_synthetic   | hard_case_weighted | REJECT           |   80 |             3.87915 |               2.66907 |                    0.966056 |                    0.966056 |                    0.0563552 |
| legacy_synthetic   | original_like      | ACCEPT           |  271 |             5.84683 |               3.74571 |                    0.963763 |                    0.96315  |                    0.110831  |
| legacy_synthetic   | original_like      | REJECT           |  305 |           639.813   |             324.786   |                    0.99498  |                    0.540053 |                    7.27636   |
| real_tle_candidate | boundary_case      | ACCEPT           |   12 |            77.7569  |              76.0482  |                    0.995377 |                    0.991864 |                    1.25892   |
| real_tle_candidate | boundary_case      | REJECT           | 2868 |          1674.82    |            1202.34    |                    0.998822 |                    0.444196 |                    8.3405    |
| real_tle_candidate | ordinary_similar   | ACCEPT           |   10 |            74.6932  |              70.4177  |                    0.998293 |                    0.996831 |                    1.05574   |
| real_tle_candidate | ordinary_similar   | REJECT           | 2870 |          1673.71    |            1201.61    |                    0.998809 |                    0.444561 |                    8.33627   |

M6−M5 的 ROC-AUC 区间在 real_all 和 controlled_all 中均跨 0；real_all 的 PR-AUC 增量为正且 pair-bootstrap 区间不跨 0，说明对极稀疏真实误接受的排序仍有补充，但证据弱于 M1/M4 相对距离的提升。高难度受控样本主要属于“原始几何本来就小、同时高度线性可吸收”；普通受控与真实轨道拒绝样本则更常出现较大的 raw geometry。两类机制都存在，不应压缩为单一安全距离。

## 8. current→wide 正式 gate 机制

共有 540 条 current REJECT→wide ACCEPT：

| formal_gate_release_type   |   count |
|:---------------------------|--------:|
| k gate解除                 |     384 |
| b gate解除                 |     117 |
| b/k同时解除                |      39 |

正式 score/b_hat/k_hat 相等率分别为 100.00%、100.00%、100.00%。正式 gate 解除与纯几何 budget 触边是不同概念；budget 吸收增量和触边变化单列在 transition CSV。

## 9. 全距离受控样本

50～500 km 只使用精确重算的 raw geometry 和吸收量做模型；局部 Jacobian 字段仅是服务区描述，不声称精确预测远距离非线性残差。结果见 grouped validation 中 `scope=full_distance_controlled`。

## 10. 排除中心后的跨服务区重复性

兼容口径保留 d=0；主口径排除 d=0，并以固定距离×方向条件跨服务区接受比例为基础，不做跨区 all-accept。真实/受控来源的组合级相关如下：

| stratum        | metric                                      |   n |   spearman_rho |   spearman_p |   effect_ci_low |   effect_ci_high |
|:---------------|:--------------------------------------------|----:|---------------:|-------------:|----------------:|-----------------:|
| real_all       | mean_actual_direction_sensitivity_local     |  50 |      -0.551788 |  3.27215e-05 |       -0.760254 |      -0.237327   |
| real_all       | mean_weakest_direction_sensitivity          |  50 |      -0.297364 |  0.0359759   |       -0.558941 |       0.00803188 |
| real_all       | mean_unbounded_absorption_ratio             |  50 |      -0.371437 |  0.00791256  |       -0.593119 |      -0.107077   |
| real_all       | mean_tolerance_budget_absorption_ratio      |  50 |       0.394518 |  0.00458124  |        0.104297 |       0.638412   |
| real_all       | service_area_direction_sensitivity_variance |  50 |      -0.419101 |  0.00245085  |       -0.65697  |      -0.0818555  |
| real_all       | service_area_unbounded_absorption_variance  |  50 |      -0.329248 |  0.0195559   |       -0.584344 |      -0.040177   |
| real_all       | service_area_tolerance_absorption_variance  |  50 |      -0.421785 |  0.00228256  |       -0.671221 |      -0.0756865  |
| controlled_all | mean_actual_direction_sensitivity_local     |  12 |      -0.741259 |  0.00580115  |       -0.978723 |      -0.211147   |
| controlled_all | mean_weakest_direction_sensitivity          |  12 |      -0.34965  |  0.265239    |       -0.863978 |       0.467797   |
| controlled_all | mean_unbounded_absorption_ratio             |  12 |      -0.692308 |  0.012593    |       -0.971119 |      -0.0967271  |
| controlled_all | mean_tolerance_budget_absorption_ratio      |  12 |       0.937063 |  6.99316e-06 |        0.686074 |       1          |
| controlled_all | service_area_direction_sensitivity_variance |  12 |       0.020979 |  0.948402    |       -0.566787 |       0.829184   |
| controlled_all | service_area_unbounded_absorption_variance  |  12 |       0.832168 |  0.000785442 |        0.364171 |       1          |
| controlled_all | service_area_tolerance_absorption_variance  |  12 |      -0.34965  |  0.265239    |       -0.864262 |       0.359719   |

局部方向敏感度只在 `0<d<=10 km` 用于主结论；远距离重复性主要看 raw geometry 与吸收指标。

## 11. 图表

生成 10 张图：current_to_wide_gate_release.png, direction_sensitivity_by_group.png, grouped_model_comparison.png, grouped_oof_roc_pr.png, noncenter_cross_area_heatmap.png, raw_geometry_absorption_hard_cases.png, repeatability_vs_absorption.png, repeatability_vs_direction.png, same_distance_direction_decision.png, unbounded_absorption_by_group.png。

## 12. 最终判断

**建议进入正式理论化阶段（限定为分层机制解释，不作为统一跨目标风险预测器）**。

对必须回答的九个问题，结论如下：

1. **未知 pair 上的方向敏感度**：是。real_all 与 controlled_all 的 M1−M0 LOPO 区间均严格大于 0；真实 ordinary/boundary 和普通受控组成立，高难度受控组不成立。
2. **未知 pair 上的吸收比例**：有解释力但弱于方向。real_all、controlled_all 的 M2−M0 区间为正；四组中并非全部稳定。
3. **控制 raw geometry 后的增量**：ROC-AUC 增量不稳定；真实样本 PR-AUC 有稳定正增量。更可靠的价值是区分“raw 本就小”与“趋势可吸收”两类难例，而不是替代 raw_geo_rmse。
4. **真实与受控是否一致**：pair 留出层面方向趋势一致，但 target 留出不一致；受控跨目标 M1/M4 退化。因此不能主张统一跨来源、跨目标模型。
5. **current→wide 是否只改变 gate**：是。540 条转换全部由 b、k 或二者 gate 解除解释；正式 score/b_hat/k_hat 100% 不变。
6. **高难度样本机制**：以 raw geometry 本就较小且高度可吸收的共同作用为主；普通受控/真实样本还包含 raw 较大但趋势受限或不可接受的另一类。
7. **排除 d=0 后的跨区重复性**：仍可解释。real_all 和 controlled_all 的非中心接受比例都与较低局部方向敏感度、较高 tolerance-budget 吸收相关，pair-bootstrap 区间不跨 0。
8. **局部方向敏感度有效范围**：主结论仅限 `0<d<=10 km`；50～500 km 只使用精确 raw geometry 与吸收量，不外推 Jacobian。
9. **是否进入理论化与论文阶段**：建议进入，但理论对象应是“分层几何可分性 + b/k 容忍机制”，不是统一安全距离或统一跨目标风险预测器。

该判断依次检查了分来源 LOPO、M6−M5/难例分型、current/wide 正式拟合不变、排除中心后的组合级重复性，以及结果是否只是 post-RMSE 的重述。

## 13. 局限

- 真实轨道 ACCEPT 极少，部分单独 target 折没有正例；pooled OOF 可计算，但单折 AUC 不可定义。
- 只有 5 个真实目标卫星，leave-one-target-out 区间仍有限。
- 受控 original_like 只有 1 个目标，无法单独做有意义的 leave-one-target-out。
- 本分析不证明统一安全距离、真实 Starlink 频偏真值或局部 Jacobian 的远距离外推能力。
