# 多普勒残差身份验证理论可行性审计

## 1. 审计范围

本轮只读取已有方向机制、固定几何多 realization、same-pair multi-pass 和 controlled altitude 输出；没有生成新 geometry、没有重校准 threshold、没有修改 verifier。

## 2. 当前 verifier 的精确数学形式

在单个有效 mask 内令 `x=t_rel-mean(t_rel)`、`G=[1,x]`、`δ=y-f_geo,A`。代码执行等权无权 OLS：

`θ_hat=(G^T G)^(-1)G^Tδ`，其中 `θ_hat=[b_hat,k_hat]^T`；`Q=I-G(G^TG)^(-1)G^T`；`score=||Qδ||_2/sqrt(N)`。

这里 b 的单位是 Hz，k 的单位是 Hz/s。single-window 使用完整 60 点 mask。threshold calibration 也调用同一个 centered-time OLS，因此与该时间定义一致。coverage 是额外布尔条件，不属于 residual 投影；quality 在正式 `evaluate_single_station()` 中不是一个独立显式 gate，有限值异常会通过数值比较间接失败。

真实接受集合是：coverage 有效，且同时满足 `||Qδ||/sqrt(N)<=τ`、`|b_hat-b_center|<=B`、`|k_hat-k_center|<=K`。这是投影残差圆柱与两个 coefficient slabs 的交集。

实现路径为 `scripts/run_segmented_service_center_compensation.py::fit_for_mask/evaluate_single_station/threshold_for`，OLS 底层为 `scripts/run_doppler_verifier_initial_experiments.py::fit_bias_and_slope`。逐点 projection audit 覆盖 1582 条已有纯几何曲线；`Qd` 与对同一 raw geometry 调用正式 OLS 后重建的 production residual 最大绝对差为 0.000e+00 Hz，全局 RMSE 差为 0.000e+00 Hz。

## 3. 与 bounded nuisance distance 的关系

当前 verifier 不严格等价于 `min_{θ∈Θ} ||δ-Gθ||`，其中与代码 gate 对齐的 `Θ=[b_center-B,b_center+B]×[k_center-K,k_center+K]`。只有无约束 OLS 解位于 gate box 内时，两者的最小 residual 才相同；OLS 解在 box 外时，当前 verifier 必然因 coefficient gate 拒绝，而 bounded-distance test 仍可能因到 box 边界的 residual 小于 τ 而接受。因此当前接受集是 bounded-distance 接受集的真子集或相等子集，而不是同一个集合。

| dataset_group        | bk_box   |   observation_count |   current_verifier_accept_count |   bounded_distance_accept_count |   decision_mismatch_count |   bounded_accept_but_verifier_reject_count |   verifier_accept_but_bounded_reject_count |   bounded_rmse_median_hz |   bounded_rmse_max_hz |
|:---------------------|:---------|--------------------:|--------------------------------:|--------------------------------:|--------------------------:|-------------------------------------------:|-------------------------------------------:|-------------------------:|----------------------:|
| fixed_geometry       | current  |                1170 |                             245 |                             693 |                       448 |                                        448 |                                          0 |                  31.0107 |              5240.2   |
| fixed_geometry       | wide     |                1170 |                             734 |                             812 |                        78 |                                         78 |                                          0 |                  29.2039 |              4980.39  |
| same_pair_multi_pass | current  |                2400 |                              45 |                             257 |                       212 |                                        212 |                                          0 |                 131.813  |              1292.05  |
| same_pair_multi_pass | wide     |                2400 |                             176 |                             505 |                       329 |                                        329 |                                          0 |                  61.5584 |              1039.24  |
| controlled_altitude  | current  |               18000 |                           11010 |                           14008 |                      2998 |                                       2998 |                                          0 |                  28.5537 |               241.178 |
| controlled_altitude  | wide     |               18000 |                           13960 |                           14936 |                       976 |                                        976 |                                          0 |                  28.0164 |               153.356 |

current→wide 在真实 verifier 中只扩大 coefficient slabs，score/b_hat/k_hat 不变；bounded model 则会改变其最小距离，甚至可接受 OLS 解仍在 enlarged box 外但靠近边界的样本。

## 4. 局部矩阵与方向

现有 finite difference 采用东向 90°、北向 0°的地表 destination，各以 1 km 为主步长，并保存 0.5/1/2 km 稳定性。先对 J 两列执行同一 b+k 投影，得到 `J_p=QJ`。因此 `M=J^TQJ=J_p^TJ_p`，且方向 u 的现有 sensitivity 精确为 `sqrt(u^TMu/N)`，不是新定义的替代指标。

fixed-geometry 汇总只保存了最弱/最强奇异值，没有保存连续特征向量角度，因此该来源的 v_min/v_max angle 保留 NaN；没有从其他实验强行回填。

| dataset_group        |   comparison_count |   v_min_lowest_error_median_deg |   v_min_lowest_error_max_deg |   v_max_high_error_median_deg |   v_max_high_error_max_deg |   quadratic_formula_ratio_median |   quadratic_formula_relative_error_max |   quadratic_formula_spearman_rho |   quadratic_formula_spearman_p |
|:---------------------|-------------------:|--------------------------------:|-----------------------------:|------------------------------:|---------------------------:|---------------------------------:|---------------------------------------:|---------------------------------:|-------------------------------:|
| controlled_altitude  |                300 |                         12.6417 |                      22.4297 |                       12.6417 |                    22.4297 |                              nan |                          nan           |                       nan        |                 nan            |
| direction_mechanism  |                 46 |                         10.1445 |                      22.3003 |                       10.1445 |                    22.3003 |                              nan |                          nan           |                       nan        |                 nan            |
| same_pair_multi_pass |                 40 |                         10.7683 |                      22.3013 |                       10.7683 |                    22.3013 |                              nan |                          nan           |                       nan        |                 nan            |
| controlled_altitude  |                900 |                        nan      |                     nan      |                      nan      |                   nan      |                                1 |                            5.70708e-14 |                         0.999999 |                   0            |
| direction_mechanism  |               1582 |                        nan      |                     nan      |                      nan      |                   nan      |                                1 |                            1.13674e-14 |                         0.999993 |                   0            |
| same_pair_multi_pass |                120 |                        nan      |                     nan      |                      nan      |                   nan      |                                1 |                            1.29112e-14 |                         0.999997 |                   3.33858e-306 |

## 5. 理论量与已有风险

| dataset_group        | stratum   | theory_metric          | outcome         |    n |   spearman_rho |   spearman_p |
|:---------------------|:----------|:-----------------------|:----------------|-----:|---------------:|-------------:|
| controlled_altitude  | all       | D_proj_hz_l2           | accept_fraction |  840 |     -0.764814  | 3.50396e-162 |
| controlled_altitude  | all       | lambda_min_hz2_per_km2 | accept_fraction |  840 |     -0.572763  | 2.1539e-74   |
| direction_mechanism  | all       | D_proj_hz_l2           | accept_fraction | 1582 |     -0.605089  | 1.25503e-158 |
| direction_mechanism  | all       | lambda_min_hz2_per_km2 | accept_fraction | 1582 |     -0.232063  | 8.69816e-21  |
| fixed_geometry       | all       | D_proj_hz_l2           | accept_fraction |   39 |     -0.531713  | 0.000495053  |
| fixed_geometry       | all       | lambda_min_hz2_per_km2 | accept_fraction |   39 |     -0.0839984 | 0.611171     |
| same_pair_multi_pass | all       | D_proj_hz_l2           | accept_fraction |  120 |     -0.409475  | 3.4188e-06   |
| same_pair_multi_pass | all       | lambda_min_hz2_per_km2 | accept_fraction |  120 |     -0.0776036 | 0.39952      |

分位数风险输出见独立 CSV。D_proj 通常能排序几何 score 风险，λ_min 描述局部最弱地面方向，但两者均不能单独表达 b/k coefficient 在 gate box 中的位置。

## 6. 固定几何的 environment 作用

| dataset_group        |   k_env_to_k_hat_spearman |   within_geometry_centered_k_env_to_k_hat_spearman |   k_hat_minus_geometry_plus_env_rmse_hz_per_s |   geometry_count_with_k_gate_flip |   geometry_count_with_accept_flip |   rows_geometry_Dproj_under_score_threshold_but_k_gate_fail |   rows_observed_score_pass_but_k_gate_fail | b_decomposition_note                                                                                                       |
|:---------------------|--------------------------:|---------------------------------------------------:|----------------------------------------------:|----------------------------------:|----------------------------------:|------------------------------------------------------------:|-------------------------------------------:|:---------------------------------------------------------------------------------------------------------------------------|
| fixed_geometry       |                  0.237331 |                                           0.803773 |                                      0.210055 |                                29 |                                29 |                                                         579 |                                        539 | b_hat includes environment k times the offset between environment t0 and masked-time mean; not reduced to b_geo+b_env here |
| same_pair_multi_pass |                  0.079117 |                                           0.794501 |                                      0.209797 |                                10 |                                 9 |                                                        2285 |                                       1404 | b_hat includes environment k times the offset between environment t0 and masked-time mean; not reduced to b_geo+b_env here |
| controlled_altitude  |                  0.378567 |                                           0.791805 |                                      0.210382 |                               457 |                               706 |                                                        5488 |                                       4745 | b_hat includes environment k times the offset between environment t0 and masked-time mean; not reduced to b_geo+b_env here |

geometry-derived D_proj、b_geo、k_geo 对同一 geometry 固定；不同 realization 的 environment b/k 和 noise 改变 formal b_hat/k_hat 与 margins。跨 geometry 的 pooled `k_env→k_hat` 会被不同 `k_geo` 淹没，因此应以表中的 geometry 内中心化相关为主。`k_hat=k_geo+k_env+noise_fit_slope`，其剩余 RMSE 是噪声在线性基上的投影，不是理论失配。b 的分解还包含 environment `t0` 与当前 mask 均值的参考时刻平移，不能简单写成 `b_geo+b_env`。所以相同 D_proj 下可因 k boundary 发生完全不同判决。

## 7. 八个核心结论

1. b+kt score 部分严格等价于当前 mask 上的等权 nuisance-subspace projection。
2. current verifier 不等价于 bounded-nuisance minimum-distance test。
3. 真实接受区域是 projected-RMSE 门限与 centered b/k coefficient slabs，再与 coverage 条件的交集。
4. 当前 direction_sensitivity 确实是 `J^TQJ` 二次型除以 N 后开方。
5. 连续 v_min/v_max 能预测八方向最低/最高轴；误差受 45°离散网格限制，详见 alignment CSV。
6. D_proj 与 λ_min 能统一描述距离、方向、pass、altitude 对“几何可分性”的一部分影响，但不能单独统一预测 final decision。
7. projected residual 相近仍可能判决不同，主要缺失 coefficient position、尤其 k boundary，以及 environment/noise distribution；b 和 coverage 也不能从 D_proj 推出。
8. A3 条件下，`q*(t)=F_A(S,t)-F_B(S,t)` 使模型内几何 residual 为零，单站标量 Doppler-only 存在严格不可识别性；这只是抽象模型边界。

## 8. 适用边界

- 等权 projection 与当前实现一致，不意味着噪声严格 iid Gaussian；本轮没有使用 FIM/CRLB。
- λ_min 是 C 附近地面位移的局部一阶量，不是轨道高度 Jacobian，也不能替代有限高度差的 D_proj。
- grouped ranking 是描述性分层检验，没有训练预测器。
- bounded nuisance distance 可作为替代模型的辅助量，但不得称为当前 verifier 判决函数。
- A3 不改变当前 A1 攻击实验，也不代表现实攻击必然可行。

## 9. 正确性审计

| check                                                   | passed   | observed                            |
|:--------------------------------------------------------|:---------|:------------------------------------|
| Qd equals production OLS residual at floating precision | True     | 0.0                                 |
| all four existing experiment families represented       | True     | 4                                   |
| no new geometry generated                               | True     | read-only existing CSV calculations |
| altitude reference retained but identifiable            | True     | 60                                  |
| bounded/current mismatch observed                       | True     | 5041                                |
| direction quadratic identity finite                     | True     | 5.70707555295603e-14                |
