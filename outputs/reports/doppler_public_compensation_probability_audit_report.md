# A2 公共补偿攻击与 geometry-conditioned acceptance probability 理论审计

## 1. 范围

本轮没有生成新轨道、新观测或新 threshold，也没有修改 verifier。概率验证只读取 fixed geometry、same-pair multi-pass 和 controlled altitude 的 current_bk realization。

## 2. A1→A2 公共补偿

令 `ΔF_S(t)=F_A(S,t)-F_B(S,t)`，公共补偿 q 在 S 的残差为 `r_S(q)=q-ΔF_S`。A2 至少有三个不同目标：

- 平均损失 `min_q E_S[D(S,q)]`：对应攻击者知道区域站点分布并优化平均效果；若 D 为平方 projected energy，无约束时间轨迹的最优解是区域 `ΔF_S` 的均值，模 nuisance 子空间不唯一。
- 最坏站点 `min_q max_S D(S,q)`：对应攻击者希望覆盖整个区域，解是 projected curve 集合的 Chebyshev center，一般不等于某个物理 C 的曲线。
- 接受概率 `max_q P_S(ACCEPT|q)`：最贴近认证风险，但包含 score 与 b/k slabs，通常非凸，也不等同于平均能量最小。

当前 A1 `q_C=ΔF_C` 是 A2 的可行特例，不一般地是全局最优解。令 `S=C+Δx`、`ΔF_S≈ΔF_C+JΔx`，则 C 补偿消掉零阶项并留下 `r≈-JΔx`。投影后 `||Qr||²≈Δx^T(J^TQJ)Δx=Δx^TMΔx`。若 Ω 小、分布关于 C 对称且平方 projected energy 是目标，则 `E[Δx]=0`，q_C 是一阶平均意义最优；期望剩余能量为 `tr(M Cov(Δx))`。当前 C 是服务段固定代表点，不保证等于真实站点分布的空间质心，因此这只是带条件的局部解释。

## 3. A1/A2/A3 层级

- A1：固定 C 和 `q_C`，位置知识最弱，残差由 S-C 空间差产生。
- A2：知道 `S∈Ω` 并优化一条公共 q；知识和控制更强，但一个 q 通常不能同时消除所有 S 的差异。
- A3：知道真实 S 且可逐时刻自由控制 q，取 `q*=ΔF_S` 后标量 Doppler residual 为零，形成模型内严格不可识别性。

A3 仍不代表现实攻击者具备完美站址/轨道/同步、无限控制带宽或任意协议能力。

## 4. 代码一致的随机模型

代码从 main ranges 独立均匀采样：`b_env∼U(3179.0, 3728.0)` Hz、`k_env∼U(-1.110156, -0.197808)` Hz/s、`σ∼U(23.215, 32.89)` Hz；给定 σ 后逐点噪声 `n∼N(0,σ²I)`。这是一阶工程近似，不声称真实噪声严格 iid Gaussian。

在 mask-centered `x=t-mean(t)` 下：

`b_hat=b_geo+b_env+Δt·k_env+ζ_b`，`k_hat=k_geo+k_env+ζ_k`；条件于 σ，`ζ_b∼N(0,σ²/N)`、`ζ_k∼N(0,σ²/(x^Tx))`，且与 projected noise `Qn` 正交独立。Δt 是 environment t0 与 mask 均值之差，因此 b/k gate 通过共享 k_env 而相关。

score 条件分布满足：`N·score²/σ² ∼ χ'²_{N-2}(λ)`，其中 `λ=D_proj²/σ²`。本轮用确定性 Gauss–Legendre 对 σ 和 k_env 积分，并解析积分 b_env；没有生成 Monte Carlo realization。

## 5. 生成分布数值审计

| dataset_group        |   realization_count |   b_min |   b_max |    k_min |     k_max |   sigma_min |   sigma_max |   max_abs_environment_spearman |   normalized_b_noise_variance_ratio |   normalized_k_noise_variance_ratio |   b_environment_time_offset_min_s |   b_environment_time_offset_max_s | main_ranges                                                                    |
|:---------------------|--------------------:|--------:|--------:|---------:|----------:|------------:|------------:|-------------------------------:|------------------------------------:|------------------------------------:|----------------------------------:|----------------------------------:|:-------------------------------------------------------------------------------|
| fixed_geometry       |                1170 | 3179.63 | 3727.84 | -1.11001 | -0.19811  |     23.2225 |     32.8754 |                     0.0539114  |                            0.969318 |                            0.994686 |                            -158   |                                38 | {"b": [3179.0, 3728.0], "k": [-1.110156, -0.197808], "sigma": [23.215, 32.89]} |
| same_pair_multi_pass |                2400 | 3179.08 | 3727.87 | -1.10983 | -0.197876 |     23.2176 |     32.8896 |                     0.0231102  |                            0.962709 |                            0.995137 |                             -20.5 |                                27 | {"b": [3179.0, 3728.0], "k": [-1.110156, -0.197808], "sigma": [23.215, 32.89]} |
| controlled_altitude  |               18000 | 3179    | 3727.97 | -1.11015 | -0.197818 |     23.2158 |     32.889  |                     0.00577493 |                            1.00936  |                            1.00203  |                             -20.5 |                                27 | {"b": [3179.0, 3728.0], "k": [-1.110156, -0.197808], "sigma": [23.215, 32.89]} |

noise coefficient 的归一化方差比应接近 1；偏差来自有限已有 realization，而不是另行拟合分布。

## 6. 概率验证

| dataset_group        |   geometry_count |   prediction_mae |   prediction_rmse |   mean_predicted_accept_probability |   mean_observed_accept_fraction |   score_gate_probability_mae |   b_gate_probability_mae |   k_gate_probability_mae |   spearman_predicted_vs_observed |   spearman_p |   fraction_observed_counts_inside_theory_binomial_95 |
|:---------------------|-----------------:|-----------------:|------------------:|------------------------------------:|--------------------------------:|-----------------------------:|-------------------------:|-------------------------:|---------------------------------:|-------------:|-----------------------------------------------------:|
| controlled_altitude  |              840 |       0.0555963  |         0.0767145 |                           0.590764  |                        0.595298 |                    0.050002  |                0.0384907 |               0.0363626  |                         0.903788 | 4.13932e-311 |                                             0.986905 |
| fixed_geometry       |               39 |       0.0375253  |         0.057602  |                           0.195909  |                        0.209402 |                    0.0301978 |                0.029097  |               0.0468359  |                         0.935117 | 2.95798e-18  |                                             0.974359 |
| same_pair_multi_pass |              120 |       0.00625149 |         0.0250815 |                           0.0179649 |                        0.01875  |                    0.0412672 |                0.0498593 |               0.00665834 |                         0.489293 | 1.42121e-08  |                                             1        |

`P_accept` 使用 score 与 b/k 联合 gate 的条件概率乘积再对 σ 积分；不是训练出来的预测器。有限的 20/30 realization 使 observed fraction 本身有明显二项抽样误差，因此同时报告观测计数是否落在理论二项 95% 区间。

## 7. 各组成量

- D_proj 决定 score 非中心参数；D_proj 越大，score gate 概率通常越低。
- b_geo 决定 b 分布相对 b slab 的位置，并受 Δt·k_env 平移。
- k_geo 决定 k 分布相对 k slab 的位置，是既有 k-boundary 翻转的直接几何项。
- environment uniform distribution 决定 coefficient 在 slabs 中的覆盖概率。
- σ 同时控制 score、bnoise、knoise，边际上三个 gate 并非完全独立；本轮在给定 σ 后联合，再对 σ 积分。
- coverage 不通过时理论接受概率置零。

分 gate MAE 已列入 validation summary。高度、方向、固定几何 selection group 以及 same-pair/pass 的预测—观测分层结果见 `doppler_public_compensation_probability_audit_stratified_validation.csv`；没有只依赖 pooled correlation。

## 8. 为什么同一 geometry 会翻转

geometry 固定只固定 D_proj、b_geo、k_geo。每次 realization 重新抽取 b_env、k_env、σ 和 n，使 score 与 coefficient margins 改变。尤其 k_geo 靠近 k slab 边界时，k_env 和 noise slope 会把 k_hat 推过边界；这不是 geometry 本身随机。

## 9. 理论价值与限制

现有结果支持形成 `geometry-conditioned probabilistic identity verification boundary`：geometry 给出非中心 score 和 coefficient 均值位置，environment/noise 给出接受概率。但这不是普适真实世界概率，因为 b/k/σ 分布来自工程 main_range baseline，threshold 也是有限校准样本的实现值。

其他限制：A2 尚未求解真实服务区优化；C 未证明是区域质心；没有建模相关/有色噪声、TLE 不确定性或攻击控制误差；没有训练分类器，也没有提出新防御。

## 10. 正确性审计

| check                                                 | passed   | observed                                         |
|:------------------------------------------------------|:---------|:-------------------------------------------------|
| no new geometry or realization generated              | True     | deterministic integration over existing geometry |
| all environment samples inside configured main ranges | True     | 0                                                |
| probabilities finite and in [0,1]                     | True     | 0..0.94525                                       |
| all three existing datasets represented               | True     | 3                                                |
| current_bk only and one prediction per geometry       | True     | 1059                                             |
| quadrature orders recorded                            | True     | sigma=32,k=48                                    |
| probability quadrature converged under higher orders  | True     | 9.59979873371708e-11                             |
