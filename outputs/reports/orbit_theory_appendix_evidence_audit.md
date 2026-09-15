# 轨道理论附录 A.2–A.5 证据审计

审计日期：2026-08-27  
审计范围：只读取当前项目代码、既有 theory/verifier audit 与历史输出；未修改 verifier、配置、历史数据集或历史科研输出；未运行轨道传播或新 Monte Carlo。唯一新增计算是对既有 1,582 条纯几何 curve 的只读 OLS correctness check，以及对既有 current/wide CSV 的单调性计数。

状态约定：

- `CODE_VERIFIED`：数学陈述直接对应当前代码，并已有数值审计或本轮允许的小型只读 correctness check。
- `PARTIALLY_VERIFIED`：实现映射明确，但某一外推、近似或 gate 组合未被项目数值验证完整覆盖。
- `THEORY_ONLY`：标准数学推导成立，但项目未做对应数值验证；不得包装成实验结论。

## 0. Authoritative implementation 与调用关系

本附录所审计的“正式 verifier”不是最早的 score-only verifier，也不是 `run_window_reliability_calibration.py::decision_for(strong_prior)`。它是 fixed-reference compensation、fixed-geometry、same-pair multi-pass 和 controlled-altitude 正式输出共同调用的单站单窗实现：

```text
fixed / multi-pass / altitude observation builder
  -> run_segmented_service_center_compensation.evaluate_single_station(...)
     -> fit_for_mask(...)
        -> run_window_reliability_calibration.fit_on_mask(...)
           -> run_doppler_verifier_initial_experiments.fit_bias_and_slope(...)
     -> threshold_for(..., current_bk | wide_bk)
     -> score / b / k / coverage boolean decision
```

### 0.1 authoritative code path

| 内容 | 文件与函数 | 关键实现 |
|---|---|---|
| Doppler residual construction | `scripts/run_doppler_verifier_initial_experiments.py::fit_bias_and_slope`，L236–248 | `delta = y_obs - f_geo_claimed` |
| mask selection | `scripts/run_window_reliability_calibration.py::slice_mask`，L147–149 | 闭区间 mask，容差 `1e-9` |
| mask 后拟合 | `scripts/run_window_reliability_calibration.py::fit_on_mask`，L169–170 | 先切 `y_obs/f_geo/t_rel`，再调用底层拟合 |
| centered time / OLS / score | `scripts/run_doppler_verifier_initial_experiments.py::fit_bias_and_slope`，L236–248 | `x=t_rel-mean(t_rel)`；`np.linalg.lstsq`；RMSE |
| formal wrapper | `scripts/run_segmented_service_center_compensation.py::fit_for_mask`，L503–509 | `current_bk/wide_bk` 均调用同一 OLS；`no_bk` 例外 |
| b/k threshold | `scripts/run_segmented_service_center_compensation.py::threshold_for`，L486–500 | current 使用 calibration p99 绝对偏差乘已有 multiplier；wide 将 B/K 各乘 2 |
| score/b/k/coverage gate | `scripts/run_segmented_service_center_compensation.py::evaluate_single_station`，L518–601 | 单窗：coverage false→DEFER；否则 score∧b∧k 决定 ACCEPT/REJECT |
| quality diagnostic | fixed：`run_fixed_geometry_multi_realization_confirmation.py` L293–333；multi-pass：`run_same_pair_multi_pass_confirmation.py` L434–465；altitude：`run_controlled_altitude_difference_risk_experiment.py` L376–402 | `quality_gate_pass=isfinite(score,b_hat,k_hat)` 在 `evaluate_single_station()` 返回后计算；没有传回 final decision |
| active compensation geometry | fixed：`run_fixed_geometry_multi_realization_confirmation.py` L266–290；multi-pass geometry：`run_same_pair_multi_pass_confirmation.py` L390–396；altitude：`run_controlled_altitude_difference_risk_experiment.py` L247–309 | `raw = F_B(S)+F_A(C)-F_B(C)-F_A(S)`；observation 再叠加 environment/noise |
| current/wide shared observation | fixed correctness L541–556；multi-pass correctness L680–685；altitude correctness L608–612 | observation、score、b_hat、k_hat 相同，只有 B/K 改变 |

### 0.2 quality gate 的代码不一致风险

`run_window_reliability_calibration.py::decision_for` 的 `weak_prior/strong_prior` 路径（L456–493）确实把 quality 不通过写成 `DEFER`。但本次理论审计读取的三个 formal realization dataset 并不调用该 `decision_for`；它们调用 `evaluate_single_station()`。因此本附录 A.5 的正式接受集合不得把 `quality_gate_pass` 作为显式 AND 项。既有 theory audit 已在 `doppler_identifiability_theory_audit_verifier_math_audit.csv` 将此记录为 `NOTE`。置信度：`CODE_VERIFIED`。

---

## A.2 b/k 最小二乘与投影矩阵 Q

### A.2.1 三种 residual 必须分开

建议附录不要复用含义不稳定的单个 `d`，而使用：

1. `r_geo`：主动补偿后的纯几何 residual，代码是 `raw` / `raw_geometric_residual_hz`：

   ```text
   r_geo(S,t) = F_B(S,t) + F_A(C,t) - F_B(C,t) - F_A(S,t)
   ```

2. `δ`：production OLS 真正拟合的 observation residual：

   ```text
   δ = y_obs - f_geo_A
   ```

3. `e=Qδ`：去除 fitted b/k 后的 production residual。

对应关系：

- 几何可分性与 `D_proj` 应使用 `r_geo`，不含 environment/noise。
- `run_doppler_identifiability_theory_audit.py::projection_audit`（L105–137）对 `raw_geometric_residual_hz` 做 `Qd`，即使用 `r_geo`。
- production verifier 拟合 `δ`，不是 pure geometry residual。
- A.4 probability model 固定 `r_geo`，但随机拟合对象是 `δ=r_geo+b_env+k_env(t-t0)+n`。

状态：`CODE_VERIFIED`。

### A.2.2 时间、mask 与 N

- `t_rel_s` 单位为秒。
- formal 60 s 条件不是一律把原时间重置为 `0,...,59`。`et=t_rel[mask]` 可以是完整 pass 相对时间中的任意连续 60 点片段；例如 segment 可能位于完整 pass 中部。
- `fit_on_mask()` 先应用 mask，底层才计算 `x_i=t_i-mean(t_mask)`；mean 是 valid/masked samples 的均值，不是 full window 的均值。
- formal fixed-geometry、same-pair multi-pass、controlled-altitude 三个 realization dataset 的 `point_count` 全部为 60；theory projection audit 的 1,582 条 curve 也全部为 60 点。
- 一般实现允许 N 变化：window verifier 只要求 `mask.sum()>=3`；短窗、缺失窗口或其他策略会改变 N。相应的 Q、自由度和 `x^Tx` 都必须按当前 mask 重算。
- environment drift 的参考 `t0` 与 OLS centered mean 可能不同：fixed geometry 使用完整 target `tr` 的均值；multi-pass/altitude 使用完整 pass `full_t` 的均值，而 OLS 使用 segment `et` 的均值。

状态：formal 60 点口径 `CODE_VERIFIED`；其他 N 的理论公式 `THEORY_ONLY`，实现支持但本次概率审计未验证。

### A.2.3 符号—代码变量映射

| 数学符号 | 含义 | 代码变量 | 单位/维度 |
|---|---|---|---|
| `t` | 当前 valid mask 的时间 | `t_rel_s[mask]` / `et` | s，`N×1` |
| `x` | centered time | `x=t_rel_s-mean(t_rel_s)` | s，`N×1` |
| `δ` | observed residual | `delta=y_obs-f_geo_claimed` | Hz，`N×1` |
| `G` | nuisance design | `design=np.column_stack([ones_like(x),x])` | `N×2` |
| `β=[b,k]^T` | 常量/线性系数 | `coef` | `[Hz, Hz/s]^T` |
| `β_hat` | OLS fitted coefficients | `fit.b_hat_hz`, `fit.k_hat_hz_s` | `2×1` |
| `e` | detrended residual | `residual=delta-design@coef` | Hz，`N×1` |
| `Q` | orthogonal residual projector | 代码未显式构造；由 `delta-design@lstsq(...)` 实现 | `N×N` |
| `score` | residual RMSE | `score_rmse_hz` / `residual_rmse_hz` | Hz，标量 |
| `N` | 当前 mask 的有效点数 | `len(delta)` / `mask.sum()` / `point_count` | 无量纲 |

### A.2.4 标准推导

在一个 valid mask 内，令 `G=[1,x]` 且 `x=t-mean(t)`：

```text
β_hat = arg min_β ||δ-Gβ||_2^2
      = G^+ δ
```

production 使用 `np.linalg.lstsq(G,δ,rcond=None)`，即数值 pseudoinverse 解。若 `rank(G)=2`，则：

```text
G^+ = (G^T G)^(-1)G^T
β_hat = (G^T G)^(-1)G^Tδ
fitted = Gβ_hat
Q = I-GG^+ = I-G(G^TG)^(-1)G^T
e = δ-fitted = Qδ
score = sqrt((e^Te)/N) = ||Qδ||_2/sqrt(N)
```

由于 `sum(x_i)=0`，`G^TG=diag(N,x^Tx)`。当 N≥2 且时间点不全相同，`x^Tx>0`，故可逆。正式 evaluator 要求 N≥3，且现有 60 点 1 s 连续时间显然满列秩。普通 inverse 是满秩条件下的理论等价式；不得写成 production 实际调用了 inverse。状态：推导 `THEORY_ONLY`（标准线性代数），与实现等价性 `CODE_VERIFIED`。

### A.2.5 score 精确定义

production score 是：

```text
score = sqrt(mean(residual**2))
      = ||Qδ||_2/sqrt(N)
```

N 是当前 mask 内实际进入 OLS 的点数，不是完整 pass 总点数，也不是 calibration curve 总数。状态：`CODE_VERIFIED`。

### A.2.6 数值核验证据

Authoritative audit：

- 脚本：`scripts/run_doppler_identifiability_theory_audit.py::projection_audit`。
- 数据：`outputs/datasets/differential_doppler_mechanism_timeseries.csv`，只取 `current_bk` 的 pure geometry `raw_geometric_residual_hz`。
- curve 数：1,582；每条 60 点，共 94,920 个 current-bk time rows。
- 既有 manifest：`outputs/metrics/doppler_identifiability_theory_audit_manifest.json`。
- 既有 correctness：`outputs/metrics/doppler_identifiability_theory_audit_correctness_audit.csv`。
- `Qd` 与 production residual 最大绝对误差：`0.0 Hz`。
- 全部 residual difference 的 global RMSE：`0.0 Hz`。
- 本轮在同一 1,582 条既有 curve 上只读复核：score 最大绝对误差 `0.0 Hz`，`b_hat` 最大绝对误差 `0.0 Hz`，`k_hat` 最大绝对误差 `0.0 Hz/s`；未生成新几何、观测或科研输出。

状态：`CODE_VERIFIED`。

### A.2.7 可安全写入报告的结论

当前单窗 formal verifier 的 score 部分严格等价于：在当前 valid mask 上，将 observed residual `δ=y_obs-f_geo,A` 等权投影到 `span{1,x}` 的正交补，并计算投影 residual 的 RMSE。用于几何可分性时，同一投影应施加到 pure compensated geometry residual `r_geo`，不得把它与含 environment/noise 的 `δ` 混写。

不能过度声称：

- 等权 OLS 与实现一致，不证明真实噪声为 iid Gaussian。
- 1,582 条 audit 验证的是既有 pure geometry curve 的 projection 等价性，不是现实 Starlink 观测复现。
- `registered_frequency_offset_hz` 不是 pure CFO truth。

置信度：`CODE_VERIFIED`。

---

## A.3 局部位置微扰、J 与 M

### A.3.1 Δx 的坐标与函数定义

现有 local direction analysis 使用地表局部二维 East/North 坐标：

```text
Δx = [ΔE, ΔN]^T  (km)
```

方向角约定为 `0°=North, 90°=East, clockwise`，单位方向为 `u(φ)=[sinφ,cosφ]^T`。高度不属于这里的 `Δx`；altitude experiment 的 `delta_h_km` 是另一维轨道构造变量，不能塞入这个二维 Jacobian。

代码 `finite_difference()` 定义的基础函数是：

```text
ΔF(S,t) = F_A(S,t)-F_B(S,t)
```

它在 C 附近求 `J=∂ΔF/∂x`。而 production 主动补偿后的 pure geometry residual 是：

```text
r_geo(S,t)=ΔF(C,t)-ΔF(S,t)
```

因此：

```text
r_geo(C+Δx,t) = -JΔx + O(||Δx||^2)
```

符号负号不影响 `J^TQJ` 和方向敏感度，但附录若把 `d` 定义成 production `raw`，则 `d≈JΔx` 是错的；应写 `r_geo≈-JΔx`。若另定义 `d_sep=ΔF(S)-ΔF(C)`，才可写 `d_sep≈JΔx`。

状态：`CODE_VERIFIED`。

### A.3.2 J 的代码实现

Authoritative path：`scripts/run_differential_doppler_mechanism_audit.py::finite_difference`，L256–267。

- 方法：forward finite difference，不是 analytic derivative，也不是 central difference。
- 主步长：1 km；同时保存 0.5 km、1 km、2 km 结果用于稳定性诊断。
- East：从 C 沿 bearing 90° 调用 `destination()`；North：bearing 0°。
- 每个位移点重新计算 `F_A` 与 `F_B` Doppler；C 点也重算。
- A/B、pass/time grid、C、frequency 和 TLE 在一次差分中固定。
- `J=[j_E,j_N]`，维度 `N×2`，单位 Hz/km。
- `projected_jacobian()` 对 J 的两列分别调用与 A.2 相同的 centered-time OLS，得到 `J_p=QJ`。

0.5/1/2 km 稳定性最大相对变化：direction mechanism `0.00201147`，same-pair multi-pass `0.000965417`，controlled altitude `0.00200601`；另一个 full-analysis correctness report 给出的全量最大值为 `0.00201333`。这些值只支持公里级局部差分稳定，不支持 500 km 外推。状态：`CODE_VERIFIED`。

### A.3.3 M、N 与 sensitivity

项目当前理论定义是未归一化矩阵：

```text
M = J^T Q J = (QJ)^T(QJ)       [Hz^2/km^2]
```

而 `D_proj` 是 RMSE：

```text
D_proj(r_geo) = ||Qr_geo||_2/sqrt(N)
D_proj^2 ≈ Δx^T M Δx / N
s(u) = sqrt(u^T M u / N)       [Hz/km], ||u||=1
```

代码通过 `sv=np.linalg.svd(QJ)` 后使用 `sv/sqrt(N)`；因此最弱/最强 sensitivity 是 `sqrt(lambda_min(M)/N)`、`sqrt(lambda_max(M)/N)`。若希望正文不反复写 `/N`，可以另定义 `M_RMSE=M/N`，但必须明确这是新记号；不要把它和项目既有 `M=J^TQJ` 混用。

状态：公式与 SVD 实现 `CODE_VERIFIED`。

### A.3.4 数学性质

满秩条件下，`Q=I-G(G^TG)^(-1)G^T`，故 `Q^T=Q` 且 `Q^2=Q`。于是：

```text
M^T = (J^TQJ)^T = J^TQJ = M
v^TMv = (Jv)^TQ(Jv) = ||QJv||_2^2 >= 0
```

所以 M 为 symmetric positive semidefinite。状态：`THEORY_ONLY`（标准投影矩阵推导；代码通过 SVD 使用了这一结构，但未单独输出 `||Q^2-Q||`）。

### A.3.5 特征方向与原 8 方向实验

- `eigenvector_min` / SVD `vt[-1]`：C 附近地表单位位移中投影后 Doppler RMSE 增长最慢的方向轴。
- `eigenvector_max` / `vt[0]`：增长最快的方向轴。
- 原 8 directions：`0,45,90,135,180,225,270,315°`。
- 每个方向使用 `u=[sinφ,cosφ]`，计算 `sqrt(mean((QJ u)^2))`，单位 Hz/km。
- 连续 eigenvector 与八方向 comparison 是“轴角误差”和“方向 sensitivity 公式一致性”，不是用 500 km finite displacement 直接验证 infinitesimal Taylor 近似。
- 八方向最低/最高只是 45° 网格上的离散近似，理论最大轴误差约 22.5°。

既有数值验证：

| 数据组 | 方向公式 comparison 数 | ratio median | 最大相对误差 | Spearman | 连续轴 vs 离散最低/最高 comparison 数 | 最低轴角误差 median/max | 最高轴角误差 median/max |
|---|---:|---:|---:|---:|---:|---:|---:|
| direction mechanism | 1,582 | 1.0000000000000002 | `1.13674e-14` | 0.9999928 | 46 | 10.1445° / 22.3003° | 10.1445° / 22.3003° |
| same-pair multi-pass | 120 | 1.0 | `1.29112e-14` | 0.9999965 | 40 | 10.7683° / 22.3013° | 10.7683° / 22.3013° |
| controlled altitude | 900 | 1.0 | `5.70708e-14` | 0.9999994 | 300 | 12.6417° / 22.4297° | 12.6417° / 22.4297° |

证据：`doppler_identifiability_theory_audit_direction_alignment_summary.csv` 与 details CSV。状态：`CODE_VERIFIED`。

### A.3.6 局部近似边界

- M 只描述固定 A/B/pass/C 附近的地表二维一阶变化。
- full mechanism report 明确把 local main analysis 限定为 `0<d<=10 km`。
- 50–500 km 只使用精确重算的 raw geometry 与 absorption，不外推 Jacobian；报告明确写明 local Jacobian 不能解释为远距离精确量。
- 项目没有把局部椭圆数值验证成整个 500 km 服务区的全局风险等值线。

因此“局部椭圆可覆盖整个服务区”必须标记 `THEORY_ONLY` 且当前证据不支持；安全写法是“局部一阶可分性椭圆”。置信度：局部实现 `CODE_VERIFIED`，全局外推否定 `CODE_VERIFIED`，椭圆以外的高阶误差界 `THEORY_ONLY`。

---

## A.4 固定几何下的随机观测与条件接受概率

### A.4.1 真实 observation chain

以 fixed-geometry path 为例（multi-pass/altitude 使用同构公式）：

```text
1. 传播 A，得到 F_A(C,t) 与 verifier 位置 S 的 F_A(S,t)=fa_s。
2. 传播/构造 B，得到 F_B(C,t)=fb_c 与 F_B(S,t)=fb_s。
3. 在 C 生成公共主动补偿 u_C(t)=F_A(C,t)-F_B(C,t)。
4. S 处攻击几何观测为 F_B(S,t)+u_C(t)。
5. 对 claimed A 相减：
   r_geo = F_B(S)+F_A(C)-F_B(C)-F_A(S) = raw。
6. 每 realization 采样 b_env、k_env、sigma，并生成 noise。
7. 构造 observed frequency：
   y_obs = F_A(S)+r_geo+b_env+k_env(t-t0)+n。
8. verifier 拟合：
   delta = y_obs-F_A(S)
         = r_geo+b_env+k_env(t-t0)+n。
```

fixed code：`run_fixed_geometry_multi_realization_confirmation.py` L266–290；multi-pass code：`run_same_pair_multi_pass_confirmation.py` L423–435；altitude code：`run_controlled_altitude_difference_risk_experiment.py` L356–378。状态：`CODE_VERIFIED`。

### A.4.2 environment distributions 与随机性

配置来源：`configs/simulation_parameter_config.yaml`；采样函数：`run_doppler_verifier_initial_experiments.py::sample_error_params` L265–269。

```text
b_env   ~ Uniform(3179.0, 3728.0) Hz
k_env   ~ Uniform(-1.110156, -0.197808) Hz/s
sigma   ~ Uniform(23.215, 32.89) Hz
n | sigma ~ Normal(0, sigma^2 I)
```

- b、k、sigma 用同一个 environment RNG 连续独立 uniform draws；在模型语义上独立。
- noise 使用独立派生的 `noise_seed`；逐点 Gaussian draws。
- 每个 geometry×realization 重新采样；同一 observation 的 no/current/wide 共享完全相同 environment 和 noise。
- seed 是确定性派生且可重放；不是无 seed 随机数据。
- 该 iid Gaussian 是项目的一阶工程近似，不是现实严格白噪声结论。

既有 distribution audit 的最大绝对 environment Spearman 分别为 0.0539、0.0231、0.00577；只作为有限样本 independence sanity，不是独立性的数学证明。状态：`CODE_VERIFIED`。

### A.4.3 b_hat/k_hat 的解析分解

令 `x=t-mean(t_mask)`、`Sxx=x^Tx`、`Δt=mean(t_mask)-t0`，并把 pure geometry 的 OLS 投影系数记为：

```text
a0_geo = (1^T r_geo)/N
a1_geo = (x^T r_geo)/Sxx
```

这两个量是 residual 的数学投影系数，对应代码字段 `unbounded_geometry_b_hat_hz`、`unbounded_geometry_k_hat_hz_per_s`；它们不是物理上新增的 “geometry CFO/drift”。则：

```text
b_hat = a0_geo + b_env + Δt*k_env + zeta_b
k_hat = a1_geo + k_env + zeta_k
zeta_b = (1^T n)/N
zeta_k = (x^T n)/Sxx
```

条件于 sigma：

```text
Var(zeta_b|sigma) = sigma^2/N
Var(zeta_k|sigma) = sigma^2/Sxx
Cov(zeta_b,zeta_k|sigma) = sigma^2*(1^Tx)/(N*Sxx) = 0
```

合法 A 且理想 `r_geo≈0` 时，b_hat/k_hat 主要反映 environment 项与 noise projection。非目标 B 时，`r_geo` 在 `span{1,x}` 上的分量进入 a0/a1，并可被 fitted coefficients 吸收；这只是一种 OLS 分解，不是声明攻击源存在可控的物理 “b_geo/k_geo”。状态：解析式 `THEORY_ONLY`，字段分解/方差 ratio audit `CODE_VERIFIED`。

### A.4.4 为什么 linear drift 推动 k_hat

最短关系是：

```text
x^T[k_env(t-t0)]/Sxx
= x^T[k_env(x+Δt)]/Sxx
= k_env
```

因此 `k_hat=a1_geo+k_env+zeta_k`。既有 Spearman：

| 数据组 | pooled corr(k_env,k_hat) | geometry 内中心化 corr(k_env,k_hat) | realization 数 |
|---|---:|---:|---:|
| fixed geometry | 0.237331 | 0.803773 | 1,170 |
| same-pair multi-pass | 0.079117 | 0.794501 | 2,400 |
| controlled altitude | 0.378567 | 0.791805 | 18,000 |

跨 geometry 的 pooled correlation 会被不同 a1_geo 混合削弱，因此正文应引用 geometry 内中心化值为主。`k_hat-(a1_geo+k_env)` 的 RMSE 约 0.210 Hz/s，是 noise slope projection，不是理论失配。证据：`doppler_identifiability_theory_audit_environment_gate_diagnostic.csv`。状态：`CODE_VERIFIED`。

### A.4.5 score 的条件分布

对固定 `r_geo` 和 sigma，在 iid Gaussian 近似且 `rank(G)=2` 时：

```text
N*score^2/sigma^2 ~ noncentral_chi_square(df=N-2, lambda)
lambda = ||Q r_geo||_2^2/sigma^2
       = N*D_proj^2/sigma^2
```

semi-analytic code 在 `predict_geometry()` L153–182 中使用：

```text
ncx2.cdf(N*tau^2/sigma^2, df=N-2,
          nc=N*projected_geo_rmse^2/sigma^2)
```

注意：该实现还用 `Sxx=N(N^2-1)/12`，明确假设 1 s 等间隔连续点。当前三个 formal dataset 全部 N=60，满足假设。若 mask 不规则或 N 改变，必须使用实际 `x^Tx`；df 应为 `N-rank(G)`。状态：当前 formal 数据 `CODE_VERIFIED`；一般不规则 mask 扩展 `THEORY_ONLY`。

### A.4.6 semi-analytic P_accept

Authoritative implementation：`scripts/run_doppler_public_compensation_probability_audit.py`。

- sigma：32 点 Gauss–Legendre。
- k_env：48 点 Gauss–Legendre。
- b_env：`normal_uniform_interval_prob()` 解析积分 uniform+normal interval probability。
- k gate：给定 sigma/k_env 的 normal CDF interval。
- b/k joint：给定 sigma，对共享 k_env 的 `p_b(k)*p_k(k)` 积分；没有错误地把 b/k 边际直接相乘。
- score 与 coefficient gates：给定 sigma 时，Gaussian orthogonal projection 下 score residual 与 OLS coefficients 独立，因此使用 `p_score*p_bk`；对 sigma 再联合积分。边际上它们共享 sigma，并非无条件独立。
- coverage：false 时 `P_accept=0`。
- quality：不进入该概率式；这与 authoritative `evaluate_single_station` 没有显式 quality gate 一致。
- 32×48 对更高阶 40×60 的最大概率差：`9.5997987e-11`。

状态：`CODE_VERIFIED`。

### A.4.7 Monte Carlo validation

概率审计没有生成新 realization；它用现有 formal Monte Carlo fraction 验证 semi-analytic prediction：

| validation set | geometry 数 | current realization 总数 | theory mean | observed mean | MAE | RMSE | Spearman | observed count 落入 theory binomial 95% 的比例 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed geometry | 39 | 1,170（30/geometry） | 0.195909 | 0.209402 | 0.0375253 | 0.0576020 | 0.935117 | 0.974359 |
| same-pair multi-pass | 120 | 2,400（20/geometry） | 0.0179649 | 0.0187500 | 0.00625149 | 0.0250815 | 0.489293 | 1.000000 |
| controlled altitude | 840 个非零高度正式 geometry | 16,800 对应非零正式 realization；完整 current 文件含 18,000（含 60 个零高度 reference×20） | 0.590764 | 0.595298 | 0.0555963 | 0.0767145 | 0.903788 | 0.986905 |

证据：`doppler_public_compensation_probability_audit_validation_summary.csv`。注意 same-pair Spearman 较低但 mean/MAE/binomial coverage 仍给出 calibration sanity；不能只报相关性。状态：`CODE_VERIFIED`。

### A.4.8 适用范围

该 `P_accept` 是在当前受控 `b_env/k_env/sigma/noise` 分布、当前 finite calibration thresholds、fixed geometry 和 authoritative single-window current_bk verifier 下的条件接受概率。对非目标 geometry 可解释为受控条件 false-accept probability；不得解释成现实 Starlink attack success probability，也不得称为普适频偏分布。置信度：`CODE_VERIFIED`（对当前模型）；现实外推禁止。

---

## A.5 完整 verifier 接受区域

### A.5.1 production final accept logic

对于 `verification_strategy="single-window"`、`bk_mode="current_bk"` 且存在至少 3 个点：

```text
score_pass = score <= tau
b_pass = |b_hat-b_c| <= B
k_pass = |k_hat-k_c| <= K
coverage_pass = all(coverage_mask[window])

if not coverage_pass:
    decision = DEFER
else:
    decision = ACCEPT iff score_pass and b_pass and k_pass
```

`quality_gate_pass=isfinite(score,b_hat,k_hat)` 是 formal dataset 的下游 diagnostic；没有 AND 进 final accept。对于 NaN/Inf，普通数值比较通常为 false，因而会间接拒绝，但这不等于显式 quality gate。状态：`CODE_VERIFIED`。

### A.5.2 数学接受集合

令 `L=G^+=(G^TG)^(-1)G^T`（满秩理论形式），`e_1=[1,0]^T`、`e_2=[0,1]^T`。对 coverage 有效的有限 residual `δ`：

```text
A_current = {
  δ in R^N :
  coverage(S,window)=1,
  ||Qδ||_2/sqrt(N) <= tau,
  |e_1^T Lδ-b_c| <= B,
  |e_2^T Lδ-k_c| <= K
}
```

coverage 是由 C/S 距离或可用性 mask 给出的外部空间/观测可用条件，不是 residual-space 条件。quality 不写入该集合；如附录要讨论 window-reliability strong-prior 的另一集合，必须另立小节，不得混入 current formal compensation verifier。状态：`CODE_VERIFIED`。

### A.5.3 几何解释

- `||Qδ||<=sqrt(N)tau` 是沿 `col(G)` 无界的 projected-residual cylinder。
- b gate 与 k gate 是 OLS coefficient 线性函数的两个 slabs。
- 完整 residual-space 接受区是 cylinder 与两个 slabs 的交集，再附加外部 coverage 条件。
- `D_proj` 只描述 pure geometry 在 cylinder 横截面中的半径；它不提供 observation realization 的 coefficient 位置，也不提供 coverage。

因此“D_proj 表示完整 acceptance condition”不成立。状态：`CODE_VERIFIED`。

### A.5.4 current_bk 与 wide_bk

`threshold_for()` 的 wide 逻辑：

```text
tau_wide = tau_current
b_c,wide = b_c,current
k_c,wide = k_c,current
B_wide = 2*B_current
K_wide = 2*K_current
```

observation、mask、OLS、score、b_hat、k_hat 完全相同；wide 不重新拟合。故对同一 observation，理论上 `A_current subset A_wide`，不可能 current ACCEPT→wide REJECT。

既有 correctness audits：

- fixed geometry：1,170 observations；score/b/k 最大差均 0；current ACCEPT→wide REJECT=0。
- multi-pass：2,400 observations；score/b/k 最大差均 0；current ACCEPT→wide REJECT=0。
- altitude：18,000 observations；既有 audit 记录 current/wide score/b/k 最大差均 0；本轮只读 CSV check 得 current ACCEPT→wide REJECT=0。
- 合计 21,570 observation pairs，反向单调性违反数为 0。

状态：`CODE_VERIFIED`。

### A.5.5 bounded nuisance alternative（OPTIONAL_APPENDIX）

替代集合定义：

```text
A_bounded = {
  δ : coverage=1,
  min_{β in [b_c-B,b_c+B]×[k_c-K,k_c+K]}
      ||δ-Gβ||_2/sqrt(N) <= tau
}
```

与真实 verifier 的区别：真实 verifier 先做无约束 OLS，再要求 `β_hat` 落在 box；bounded-distance test 允许 box 边界上的次优系数。故 `A_current ⊆ A_bounded`，一般为真子集。

既有 comparison：

| box | fixed mismatch | multi-pass mismatch | altitude mismatch | 合计 | disagreement direction |
|---|---:|---:|---:|---:|---|
| current | 448 | 212 | 2,998 | 3,658 | 全部 bounded accept / verifier reject；反向 0 |
| wide | 78 | 329 | 976 | 1,383 | 全部 bounded accept / verifier reject；反向 0 |
| total | 526 | 541 | 3,974 | 5,041 | 反向总计 0 |

证据：`doppler_identifiability_theory_audit_bounded_nuisance_comparison.csv`。因此 bounded nuisance minimum-distance 不能替代现有 verifier。状态：`CODE_VERIFIED`。

### A.5.6 verifier-aware margins

formal realization 输出定义：

```text
score_margin = tau-score
b_margin = B-|b_hat-b_c|
k_margin = K-|k_hat-k_c|
```

margin≥0 表示对应 gate 通过。theory audit 另对 pure geometry 构造 `geometry_score_margin`、`geometry_b_margin`、`geometry_k_margin` 及三者归一化最小值，用于描述 geometry 相对各边界的位置。它们比单独 `D_proj` 多保留 coefficient slabs 信息，但仍不是新 verifier，也不包含随机 realization 和 coverage 的全部状态。状态：公式 `CODE_VERIFIED`；把 margin 当预测器是禁止性外推。

---

## 统一符号表

| 符号 | 含义 | 单位 | 维度 | 对应代码变量 | 首次章节 |
|---|---|---|---|---|---|
| `A` | claimed target satellite | — | 对象 | `sat_a`, `target_sat_id` | A.3 |
| `B_sat` | 非目标/攻击源卫星；为避免与 b gate 半宽 `B` 冲突，正文建议写 `B_sat` | — | 对象 | `sat_b`, `attack_sat_id` | A.3 |
| `C` | 公共补偿参考地面点/segment center | deg/deg/m | 地点 | `C_lat`, `C_lon`, altitude 0 | A.3 |
| `S` | verifier/receiver 实际地面点 | deg/deg/m | 地点 | `S_lat`, `S_lon` | A.3 |
| `t` | 当前 mask 的相对时间 | s | `N×1` | `t_rel_s[mask]`, `et` | A.2 |
| `x` | centered time `t-mean(t)` | s | `N×1` | `x` | A.2 |
| `N` | 当前 valid mask 点数 | — | 标量 | `len(delta)`, `point_count` | A.2 |
| `r_geo` | C 补偿后 pure geometry residual | Hz | `N×1` | `raw`, `raw_geometric_residual_hz` | A.2 |
| `δ` | verifier 拟合的 observed residual `y_obs-F_A(S)` | Hz | `N×1` | `delta` | A.2 |
| `y_obs` | 最终 observed frequency，不建议把它叫 residual | Hz | `N×1` | `y`, `y_obs` | A.4 |
| `G` | `[1,x]` nuisance design | mixed columns | `N×2` | `design` | A.2 |
| `Q` | `I-GG^+` residual projector | — | `N×N` | 隐式 `delta-design@coef` | A.2 |
| `J` | `∂(F_A-F_B)/∂(E,N)` at C | Hz/km | `N×2` | `np.column_stack([je,jn])` | A.3 |
| `M` | `J^TQJ`，未除 N | Hz²/km² | `2×2` | 由 `QJ` SVD 隐式使用 | A.3 |
| `D_proj` | `||Qr_geo||/sqrt(N)` pure geometry projected RMSE | Hz | 标量 | `projected_rmse_hz` / `unbounded_geometry_post_rmse_hz` | A.3 |
| `b_env` | effective constant frequency bias | Hz | 标量/realization | `err.b_hz`, `b_env[_hz]` | A.4 |
| `k_env` | linear slow drift | Hz/s | 标量/realization | `err.k_hz_s`, `k_env[_hz_per_s]` | A.4 |
| `sigma` | Gaussian first-order noise scale | Hz | 标量/realization | `sigma_hz`, `noise_sigma_hz` | A.4 |
| `n` | pointwise noise vector | Hz | `N×1` | `noise` | A.4 |
| `b_hat` | OLS intercept at masked-time mean | Hz | 标量 | `b_hat_hz`, `formal_b_hat_hz` | A.2 |
| `k_hat` | OLS centered-time slope | Hz/s | 标量 | `k_hat_hz_s`, `formal_k_hat_hz_per_s` | A.2 |
| `tau` | score threshold | Hz | 标量 | `score_threshold` / `formal_score_threshold[_hz]` | A.5 |
| `b_c` | b gate center | Hz | 标量 | `b_center`, `formal_b_center_hz` | A.5 |
| `B` | b gate half-width；不要与 attack satellite B 混用 | Hz | 标量 | `b_threshold`, `formal_b_threshold_hz` | A.5 |
| `k_c` | k gate center | Hz/s | 标量 | `k_center`, `formal_k_center_hz_per_s` | A.5 |
| `K` | k gate half-width | Hz/s | 标量 | `k_threshold`, `formal_k_threshold_hz_per_s` | A.5 |
| `Δx` | C 附近 `[East,North]^T` 地表位移 | km | `2×1` | destination bearing/distance | A.3 |

推荐命名：不要在 A.2–A.4 用同一个 `d`。正文统一用 `r_geo`（pure geometry）、`δ`（observed residual）、`e=Qδ`（detrended residual）。攻击源卫星写 `B_sat`，b gate 半宽保留大写 `B`。

---

## 当前附录草稿公式逐条审计

| # | 草稿 | 判断 | 精确修改 |
|---:|---|---|---|
| 1 | `G=[1,t]` | `INCORRECT` | production 为 `G=[1,x]`，`x=t_mask-mean(t_mask)`。 |
| 2 | `Q=I-G(G^TG)^(-1)G^T` | `CORRECT_WITH_CAVEAT` | G 必须是 masked centered-time design；production 用 `lstsq/pseudoinverse`，普通 inverse 仅在 rank(G)=2 时等价。 |
| 3 | `D_proj=||Qd||/sqrt(N)` | `CORRECT_WITH_CAVEAT` | 几何可分性时 `d` 必须明确为 `r_geo`，N 为当前 valid mask 点数。 |
| 4 | `d≈JΔx` | `INCORRECT` | 若 J 按代码定义为 `∂(F_A-F_B)/∂x` 且 d 是 production `raw=r_geo`，应写 `r_geo≈-JΔx`；只有定义 `d_sep=ΔF(S)-ΔF(C)` 才是正号。 |
| 5 | `M=J^TQJ` | `CORRECT_WITH_CAVEAT` | 这是项目当前未归一化 M，单位 Hz²/km²；不要同时暗示已除 N。 |
| 6 | `D_proj^2≈Δx^TMΔx` | `INCORRECT` | 在 M=`J^TQJ` 且 D_proj 是 RMSE 时必须写 `D_proj^2≈Δx^TMΔx/N`。或另定义 `M_RMSE=M/N`。 |
| 7 | `y=d_geo+b_env+k_env(t-t0)+n` | `CORRECT_WITH_CAVEAT` | 若 y 表示 residual，应改名 `δ=r_geo+b_env+k_env(t-t0)+n`；代码的 `y_obs` 是 frequency，等于 `F_A(S)+δ`。另注明 t0 常为 full-pass mean，不一定等于 masked mean。 |
| 8 | “环境线性漂移直接推动 k_hat” | `CORRECT_WITH_CAVEAT` | 写成 `k_hat=a1_geo+k_env+zeta_k`；“直接”指 OLS 斜率中的加法系数，不代表 pooled corr=1 或攻击者可精确控制。 |
| 9 | “D_proj 表示 verifier 的完整 acceptance condition” | `INCORRECT` | 完整条件还包括 b slab、k slab 与 coverage；quality 在本 formal path 不是显式 gate。 |
| 10 | “wide b/k 会重新拟合” | `INCORRECT` | wide 复用同一 observation/OLS/score/b_hat/k_hat，只把 B、K 各扩大 2 倍。 |

最关键修改是第 4 项的符号和第 6 项缺失的 `1/N`。

---

## 证据充分性与停止结论

1. **A.2：足够写完整推导。** OLS、centered time、mask、Q、score 和 1,582-curve 数值等价均已闭环；普通 inverse 只作为满秩理论形式。
2. **A.3：足够写“局部二维一阶”完整推导。** J 的 EN forward difference、M、N 归一化、SVD 方向与八方向对齐均有证据；不足以写 500 km 全局椭圆或高阶误差界。
3. **A.4：足够写当前受控模型的条件概率推导。** 观测链、environment 分布、coefficient 分解、noncentral chi-square、32×48 quadrature 和三组 calibration sanity 均已闭环；不足以外推现实攻击成功率、相关/有色噪声或不规则 mask 概率模型。
4. **A.5：足够写当前 formal single-window current_bk 接受区域。** 必须删除显式 quality AND；如要写 window-reliability strong-prior，应另作不同 verifier 变体。
5. **仍缺证据：** local Taylor remainder 的数值上界；M 在 10 km 以外尤其 500 km 的全局有效性；不规则/缺失采样下 semi-analytic probability；现实噪声相关性、TLE uncertainty 和 attack-control error。
6. **必须修改的草稿公式：** `G=[1,t]`、production raw 的 `d≈JΔx`、`D_proj²≈Δx^TMΔx`、把 `y_obs` 与 residual 混写、D_proj=完整接受条件、wide 重新拟合。
7. **无需额外实验的标准数学：** 满秩 OLS closed form、Q 对称/幂等、M symmetric PSD、Gaussian 正交投影下 coefficient covariance、noncentral chi-square 形式。它们应标 `THEORY_ONLY` 或“标准推导”，不能冒充数值实验。
8. **必须依赖现有数值审计才能写入的结论：** 1,582 curves 的 Qd/production 零误差；direction quadratic identity 与轴角误差；0.5/1/2 km finite-difference 稳定性；k_env→k_hat 相关与 gate flips；32×48 quadrature 收敛；三个 validation set 的 MAE/RMSE/Spearman/binomial coverage；current→wide 零反向违反；bounded nuisance 的 5,041 个 disagreement。

本轮至此停止；未修改 verifier，未重跑大规模 Monte Carlo，未生成新轨道、uncertainty model、synthetic B 或 Doppler attack 实验。
