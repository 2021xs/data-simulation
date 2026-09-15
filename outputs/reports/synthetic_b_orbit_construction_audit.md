# Synthetic-B / Synthetic Orbit 构造只读证据审计

审计时间：2026-09-08  
审计性质：只读代码与 provenance 审计；未修改代码/配置/历史输出，未传播新轨道，未运行 verifier，未生成 Monte Carlo 数据。  
最终 verdict：`PARTIAL_LOCAL_POSITION_PERTURBATION_FOUND`

## 1. 结论先行

当前项目中不能把所有出现的“1 km / 5 km / 10 km perturbation”都理解成同一种轨道差异。

1. 当前论文冻结的 primary synthetic-B，包括 `controlled_altitude_difference_synthetic_B` 以及 `segment_local_heatmap_and_direction_sensitivity` 中的 synthetic 子集，**不是在单个时刻把 A 的 position 做 Cartesian translation**。它们从 A 在共同锚点时刻的惯性系 position/velocity 建立圆轨道平面、半径、相位和两体角速度，并在整个认证时间网格解析生成 B 的位置轨迹；joint-security reconstruction 还显式生成共同 epoch 的完整 `r_B, v_B`。这类构造归为 `B. PHYSICALLY_CONSISTENT_STATE_PERTURBATION`：动力学上是一条可传播的圆形 osculating orbit，但设计起点是 A 的局部状态，不是独立生成/拟合的 TLE，也不是高保真 Starlink 轨道。
2. 当前冻结的 `active_compensation_first_pass` 使用 `REAL_B`，B 来自 `data/tle/starlink_tle.txt` 中另一颗真实候选卫星的 TLE；不依赖 synthetic-B。
3. segment-local / heatmap / direction 实验里的 `distance_km`、`phi_deg`、East/North finite difference 和“lowest/high sensitivity direction”，主要是**地面接收点 S 相对服务中心 C 的局部地表方向**，不是把卫星 B 沿某个 Cartesian/RTN 方向平移 5 km。
4. 确实发现一个 `C. LOCAL_POSITION_PERTURBATION`：`scripts/run_tle_error_lower_bound_calibration.py` 的 historical near-orbit diagnostic 逐时刻执行 `r'(t)=r_A(t)±delta·v_hat_A(t)`，未定义/调整 `v_B`，也未从一个共同初始 `r,v` 传播。其输出 provenance 已写成 `instantaneous_along_track_position_offset`。它只能作为瞬时/局部位置敏感性曲线，不能严格作为“另一条相差 X km 的物理轨道”证据。
5. 该 local-position family 不在冻结的四个 joint-security core family 中，也未进入 265-unit joint primary endpoint。因此它不要求重开当前 orbit-uncertainty predictor，不推翻 joint-security 主结论；但若论文要把 near-orbit lower-bound 结果表述成“different orbit at X km”，则该特定 family 必须先重构并重跑。若保留现有结果，应改称 `instantaneous along-track position sensitivity / local position-offset diagnostic`。

## 2. 审计口径与分类解释

本审计搜索了项目脚本、配置、历史报告、manifest、semantic reconstruction matrix、R2 population、R3 unit summary 和 joint-security freeze。重点追踪以下链路：

```text
A state / TLE / causal GP
→ synthetic 参数
→ B construction
→ 是否得到完整 r,v 或全时段 r(t)
→ Doppler geometry
→ orbit gate / verifier / joint-security provenance
```

分类按任务指定口径，并作如下操作化解释：

- `A. PHYSICALLY_CONSISTENT_ORBIT`：独立完整轨道（例如另一颗真实 TLE）正常传播。REAL_B 会在表中注明 A 类物理来源，但不算 synthetic family。
- `B. PHYSICALLY_CONSISTENT_STATE_PERTURBATION`：由 A 的某个局部状态构造完整 B state/圆轨道参数，`r` 与 `v` 相容，并解析传播到后续时刻。
- `C. LOCAL_POSITION_PERTURBATION`：只构造位置偏移时间序列，未定义相容速度或可传播初始状态。
- `D. UNCLEAR`：证据不足。本轮没有 primary synthetic family 落入 D。

“使用解析圆轨道公式”在本审计中视为传播，不要求必须调用 SGP4；但会明确标为“两体圆轨道解析传播”，不能写成 TLE/SGP4 高保真轨道。

## 3. 共用 synthetic circular builder 的动力学证据

### 3.1 原始 Doppler synthetic builder

核心实现在 `scripts/run_doppler_verifier_initial_experiments.py:523-556`：

```python
r0 = pos_km[mid]
v0 = vel_km_s[mid]
h_hat = normalize(np.cross(r0, v0))
p_hat = normalize(r0)
q_hat = normalize(np.cross(h_hat, p_hat))
radius_km = np.linalg.norm(r0) + altitude_offset_km
angular_rate_rad_s = np.sqrt(mu / radius_km**3)
theta = angular_rate_rad_s * (t_centered + phase_offset_s)
attack_pos_km = radius_km * (cos(theta) * p_hat + sin(theta) * q_hat)
```

虽然这个早期 Doppler helper 没有把 `attack_vel_km_s` 保存为数组，但上述全时段位置公式唯一对应：

```text
v_B(t) = R n [-sin(theta) p_hat + cos(theta) q_hat]
```

其中 `R=|r_A(t_anchor)|+delta_h`，`n=sqrt(mu/R^3)`。因此它不是 `r_B=r_A+delta_r, v_B未定义` 的单点 translation；它定义了一条完整的圆形两体轨道，并用每个 observation timestamp 的 `r_B(t)` 计算距离，再对距离作数值梯度得到 range rate 和 Doppler。准确分类是 B，而不是 C。

局限是：

- B 不是从修改 TLE line/SGP4 mean elements 得到；
- 不含 J2、drag、机动和 TLE mean-element dynamics；
- A 的锚点 state 来自真实 TLE/causal GP 的传播，但 B 是以该 state 定向的 circular approximation；
- `delta_h=0` 只表示 synthetic circle 的半径等于锚点 `|r_A|`，不表示整个窗口内 synthetic B 与 SGP4 A 完全重合。

### 3.2 joint-security 中的显式完整 state

`scripts/run_existing_doppler_case_orbit_distinct_relabeling.py:273-301` 使用同一构造语义，但显式返回：

```python
position = R * (cos(theta) * p_hat + sin(theta) * q_hat)
velocity = R * n * (-sin(theta) * p_hat + cos(theta) * q_hat)
```

`scripts/run_causal_a_doppler_core_reconstruction.py:483-507` 在每个 frozen unit 的共同 `evaluation_time`：

- 从 latest causally available GP 传播 A，得到 `a_r, a_v`；
- 对 `REAL_B` 从真实 TLE 传播 `b_r, b_v`；
- 对 `SYNTHETIC_RELATIVE_TO_A` 调用上述 `synthetic_state(...)` 得到 `b_r, b_v`；
- 随后才在 A 的 RTN basis 中计算 `b_r-a_r`，并记录 `physical_velocity_separation_km_s=|b_v-a_v|`。

因此 formal joint orbit gate 并非只拿一个平移后 position 打分。R3 的 300 个 controlled-altitude units 和 12 个 segment-local synthetic units 都有完整 `r_B,v_B` 证据；`outputs/datasets/causal_a_doppler_r3_unit_summary.csv` 的 provenance 为 `SYNTHETIC_RELATIVE_TO_CAUSAL_A:FROZEN_ORIGINAL_PERTURBATION_RULE`。

### 3.3 元素空间的等效含义

代码没有直接编辑 classical orbital elements，但该 state construction 等效定义：

- 半长轴/圆轨道半径：`a_B=R`；
- 偏心率：`e_B=0`；
- 同平面 altitude family：继承由 `r_A×v_A` 定义的惯性轨道面；
- phase family：在同一圆轨道上改变相位 `n·delta_t`；
- inclination family：在惯性 frame 中围绕 node direction 旋转候选 angular-momentum direction，然后由 `p_hat,q_hat` 生成新的圆轨道平面；
- 圆轨道下 argument of perigee 本身不唯一，代码没有声称或保存该量。

这不是“只改 altitude element 后交给 SGP4”，而是“由 anchor Cartesian state 重新定义一条圆形两体轨道并解析传播”。

## 4. Family-by-family 审计表

| family | script | B_type | construction_method | position_handling | velocity_handling | propagated_or_not | common_epoch | coordinate_frame | classification | paper_implication |
|---|---|---|---|---|---|---|---|---|---|---|
| Legacy score-only synthetic altitude/phase | `run_doppler_verifier_initial_experiments.py:523-556, 587-632` | synthetic relative to A | A mid-pass state → circular plane; `R=|r0|+delta_h`; `theta=n(t+delta_t)` | 全窗口重建 `r_B(t)`，不是单点平移 | 早期 helper 未保存 v 数组，但 v 是解析轨迹的一阶导数；joint reproduction 显式生成同式 v | 是，两体圆轨道解析传播；非 SGP4 | 是；A/B geometry 使用同一 timestamp grid，anchor 为 A pass 中点 | Skyfield geocentric inertial/ECI-like basis | **B** | 可保留为 controlled circular-orbit stress test；不可写成另一条真实 Starlink TLE 轨道 |
| Verifier-v2 / fine sweep / hard-case / window reliability descendants | `analyze_verifier_v2_hard_cases.py`, `run_verifier_v2_fine_sweep_attacks.py`, `run_window_reliability_calibration.py`, `run_verifier_v2_hard_case_multiwindow.py`, `run_verifier_v2_hard_case_multipass.py`, `run_pass_quality_aware_attacker_search.py`, `run_full_pass_quality_coverage_expansion.py` | inherited synthetic relative to A | 复用 `synthetic_same_plane_geo`；inclination 复用 `synthetic_inclination_offset_geo` | 每个 timestamp 生成圆轨道位置 | implicit circular v；inclination 的轨迹同样有相容导数 | 是，解析传播 | 是 | ECI/inertial；inclination 使用 inertial z/node | **B** | 可保留；“1/2/5/10 km”是 anchor radius offset，不是 Cartesian translation 或全窗口恒定 Euclidean separation |
| Segment-local heatmap / direction synthetic subset | `run_segment_local_expanded_sample_confirmation.py:175-250,270-288,500-575`; `run_differential_doppler_mechanism_audit.py:256-267` | mixed: REAL_B + legacy synthetic relative to A | synthetic rows 经 `synthetic_spec → generate_synthetic_geo → generate_attack_geo` 复用 circular builder；real rows直接传播另一颗 TLE | B 的轨迹完整；另外改变的是地面 C→S 的位置 | synthetic 为相容 circular v；REAL_B 为 TLE velocity | 是 | 是；R3 对 37 units 均在共同 evaluation epoch 比较，其中 12 synthetic、25 REAL_B | B 在 ECI；方向扫描在地表 local tangent/geodesic bearing，0° north、90° east | synthetic **B**；REAL_B **A** | 现有 direction 结论可保留，但应写“receiver/service-bearing direction”，不能写成“B 沿 East/North 移动 X km” |
| Controlled altitude difference synthetic-B | `run_controlled_altitude_difference_risk_experiment.py:171-195,230-353`; formal Doppler复用 `synthetic_same_plane_geo` | synthetic relative to A | A 的 selected pass/segment state → same-plane circle；`R_B=|r_A(anchor)|+delta_h`，并按 `sqrt(mu/R_B^3)` 重算角速度 | 全 60 s 生成 `r_B(t)`；delta_h=0 为 circular reference | audit helper未返回 v，但完整公式隐含；R3 `synthetic_state` 显式返回 v | 是，两体圆轨道解析传播 | 是；joint unit在同一 evaluation_time 比较 A/B | 惯性 ECI/GCRS-like；`delta_h` 是 anchor radial/radius change | **B** | 可继续作为论文 F3 / controlled altitude 证据；应称 signed anchor-radius/altitude perturbation under circular model，不应称全时段恒定 A-B 距离或真实 Starlink 高度差分布 |
| Inclination / orbit-plane synthetic | `run_window_reliability_calibration.py:231-291,326-355` | synthetic relative to A | 从 A 中点 `r0,v0` 得 h；围绕 inertial node axis 旋转 h 候选；由 p/q 建圆轨道 | 全窗口重建 circular `r_B(t)`，anchor position direction 与 A 共用 | 圆轨道速度由轨迹隐式共同定义；joint helper显式生成 v | 是，解析传播 | 是 | ECI/inertial element-like plane perturbation，不是 RTN N translation | **B** | 可保留为 controlled orbital-plane state perturbation；“delta_i”是设计参数。代码的最终 plane 由实际 p/q 决定，不宜夸大成严格只改变某一个 TLE mean element |
| Historical fixed-point / fixed-reference active-compensation synthetic branches | `run_fixed_point_active_compensation_sensitivity.py:129-148,234-259`; `run_fixed_reference_compensation_extended_sensitivity.py:124-163`; 同构调用见 Appendix | synthetic altitude/inclination relative to A | 复用 window-reliability circular builders；`e_km` 另指攻击者 reference-point/location error | B 全窗口 circular position；`S_hat`/C 的 km 扰动是地面参考点误差 | B 有相容 circular v；地面点不属于轨道 state | 是 | 是 | B 为 ECI；`e_km`、bearing 为地表 local/geodesic | **B** | synthetic B 本身可作为 historical sensitivity 保留；但 semantic freeze 已将 fixed-point summary 从 formal joint mainline 删除，不能把 `e=1/5/10 km` 说成 B 的 orbit difference |
| Active compensation first pass（当前 formal core） | `run_active_compensation_attack_first_pass.py:158-183,657-700`; R3 `active_geometry` at `run_causal_a_doppler_core_reconstruction.py:889-934` | **REAL_B** | 从 candidate library 选不同 NORAD，按其 TLE传播 | TLE/SGP4完整位置 | TLE/SGP4完整速度 | 是，正常 TLE propagation | 是 | Skyfield geocentric inertial | REAL_B，物理来源相当于 **A** | 不受 synthetic construction 问题影响；direct-S ideal 25/30 主结论来自 real B，不是 local translation |
| Formal joint-security `SYNTHETIC_RELATIVE_TO_A` | `run_existing_doppler_case_orbit_distinct_relabeling.py:255-301`; `run_causal_a_doppler_core_reconstruction.py:450-568,621-656,753-795` | synthetic relative to causal A | latest published causal GP(A) → anchor state → frozen altitude/phase/inclination circular rule；orbit side显式 r/v，Doppler side重建全时段轨迹 | 共同 epoch完整 `b_r`；Doppler全时段 `r_B(t)` | 显式 `b_v` 并记录 A/B velocity separation | 是，解析传播 | 是；`evaluation_time`相同；construction anchor独立记录 | A/B 转到 GCRS 供 orbit scoring；Doppler使用同语义惯性轨迹；RTN仅用于评分差向量 | **B** | 300 altitude + 12 segment synthetic core units可以保留；没有发现 `r_B=r_A+delta_r, v_B=v_A/undefined` |
| Visibility/timing diagnostic | `diagnose_attack_visibility_timing.py:90-133` | inherited synthetic relative to A（诊断视图） | 复刻同一圆轨道位置公式以算 elevation | 全时段位置 | 不使用 v；但它继承已定义的圆轨道，而不是另造 local translation B | 是（继承解析轨迹） | 是 | ECI position → topocentric elevation | **B（继承）** | 不是独立攻击构造证据，只是对同一 B 做可见性诊断 |
| TLE-error / near-orbit along-track diagnostic | `run_tle_error_lower_bound_calibration.py:300-332` | local synthetic position offset | 每个时刻取 A 的 `v_hat(t)`，令 `r'(t)=r_A(t)±delta·v_hat(t)` | 只改 position；delta=0.1…200 km | 未定义/保存相容 `v_B`；没有从共同初始 state传播。range rate仅由偏移后range时间序列做 gradient | **否**，不是自由飞行轨道传播 | 位置样本与A同时间戳，但不存在单一共同初始B state/epoch语义 | A的惯性 position + time-varying velocity-direction offset；近似 along-track，不是完整 RTN state perturbation | **C** | 只能保留/重命名为 local instantaneous along-track position sensitivity；若要支持“different orbit X km”必须针对这一 family 重构并重跑 |

## 5. 每个 synthetic family 的 12 项问题答复

### 5.1 Legacy score-only 及 verifier descendants

1. 脚本：核心为 `scripts/run_doppler_verifier_initial_experiments.py`；下游 caller 见 Appendix A。
2. 关键位置：`523-556`（构造与 Doppler），`587-632`（altitude/phase 参数与调用）。
3. 输入：早期 altitude `[-100,-50,-20,-10,-5,5,10,20,50,100] km`；phase `[-300,-120,-60,-30,-10,10,30,60,120,300] s`；fine sweep含 `±1,±2,±3,±4,±5,±7.5,±10 km`。
4. A 来源：`data/tle/starlink_tle.txt` 的目标 TLE，经 Skyfield 在目标 pass 时间网格传播；claimed A Doppler来自对应 candidate library target row。
5. B 生成：A 中点 `r0,v0` 定平面，以 `R` 和 Kepler circular `n` 生成全时段轨迹。
6. 修改：不直接修改A的TLE elements；重新定义B的position轨迹、相容velocity及等效圆轨道参数。
7. 元素：等效改变 circular radius/semimajor axis、mean motion、phase，或 orbital plane；随后解析传播，不走SGP4。
8. Cartesian：不是加固定 `delta_r`；anchor state 导出新的 `r_B,v_B`。早期函数只物化r，但v由公式确定。
9. 同epoch：是，所有频率比较使用相同 timestamp。
10. Doppler：是，使用B在每个timestamp的完整 propagated position path；range rate从range梯度得到。
11. `r_B=r_A+delta_r` 且 `v_B=v_A/undefined`：否。
12. 文本一致性：`same-plane circular orbit approximation`一致；“orbit difference X km”应收窄为“anchor radius offset X km”。

### 5.2 Inclination / orbit-plane family

1. 脚本：`scripts/run_window_reliability_calibration.py`，由fixed-point、segment-local等复用。
2. 关键位置：`231-291`、`326-355`。
3. 输入：window calibration正式输出中为 `±0.05, ±0.1, ±0.2 deg`；R3选入的synthetic units包括 `+0.05,+0.2,-0.2 deg`。
4. A来源：目标 TLE或R3 causal GP传播的anchor state。
5. B生成：旋转惯性angular momentum候选，再以共享anchor radial direction建立新p/q平面和圆轨道。
6. position/velocity/element：全时段position和相容velocity共同改变；不直接改TLE line；等效plane/inclination-like perturbation。
7. 传播：解析圆轨道传播。
8. Cartesian一致性：是；anchor位置可与A重合，但速度方向改变，因此定义另一条osculating circle。
9. 同epoch：是。
10. Doppler：使用全时段B轨迹。
11. position-only：否。
12. 文字边界：可称controlled inclination/orbit-plane perturbation；由于最终plane由`p_hat,q_hat`实际决定，不能未经额外element back-conversion就宣称严格只改变某个SGP4/TLE inclination element且其他mean elements完全不变。

### 5.3 Segment-local direction / heatmap family

1. 脚本：`run_segment_local_expanded_sample_confirmation.py`、`run_segmented_service_center_compensation.py`、`run_differential_doppler_mechanism_audit.py`；R3重建在`run_causal_a_doppler_core_reconstruction.py`。
2. 关键位置：attack bridge `270-288`；C/S placement `500-575`；East/North finite difference `256-267`。
3. B输入：real candidate NORAD，或synthetic altitude `-1,-2,±10 km`、phase `±60 s`、inclination `+0.05,±0.2 deg`（R3选入集合）；地面几何另有 `distance_to_center_km` 和 `phi_deg`。
4. A来源：legacy为static target TLE；formal R3为causal GP(A)。
5. B生成：real B由TLE；synthetic B复用完整circular builder。
6-8. position/velocity/传播：同上；方向扫描本身不修改B state，而是移动receiver S。
9. 同epoch：是。
10. Doppler：A/B都在同一segment时间网格重新计算至C和S。
11. position-only B：否。
12. 文字一致性：`5 km direction`若指`distance_to_center_km=5`，是地面C→S geodesic距离，不是orbit difference。

### 5.4 Controlled altitude difference family

1. 脚本：`scripts/run_controlled_altitude_difference_risk_experiment.py`；R3 state reconstruction复用`run_existing_doppler_case_orbit_distinct_relabeling.py`。
2. 关键位置：`171-195`、`230-353`、R3 `483-507`。
3. 输入：正式 `delta_h=[-100,-50,-20,-10,-5,-2,-1,0,1,2,5,10,20,50,100] km`；5 targets × 4 passes；三种receiver direction role。
4. A来源：selected same-TLE pass；joint版本改为evaluation time之前latest causally published GP(A)。
5. B生成：same-plane circular state，半径加signed delta_h，角速度随新半径重算。
6. position与velocity共同改变；不编辑TLE elements。
7. 等效改变a/radius与mean motion；解析传播。
8. 完整r/v一致；不是radial translation后保持A velocity。
9. 同epoch：是。
10. Doppler：正式代码复用全时段B circular generator；correctness audit记录两条路径差为0。
11. position-only：否。
12. “altitude difference X km”在anchor-radius意义上一致。R3保存的共同evaluation-time物理分离与`|delta_h|`仅约相差不超过0.0031 km；但不应升级为全pass恒定separation或真实TLE altitude difference。`delta_h=0`仍有约0.0005-0.0031 km的model/half-sample anchor差，因此只是reference。

### 5.5 Active compensation families

1. 当前formal脚本：`run_active_compensation_attack_first_pass.py`；historical synthetic脚本：`run_fixed_point_active_compensation_sensitivity.py`及Appendix callers。
2. 当前formal关键位置：`158-183`选择real-TLE attacker，`657-700`传播A/B；R3 `889-934`重建。
3. 输入：formal B为不同NORAD；historical hard cases用altitude/inclination synthetic spec；`e_km`、controlled-R和bearing是地面reference-point误差。
4. A来源：static TLE或R3 causal GP。
5. B生成：formal为真实TLE；historical为circular builder。
6-8. formal完整TLE r/v；historical完整circular r/v；`e_km`不改B轨道。
9. 同epoch：是。
10. Doppler：formal对real A/B同网格传播；historical对synthetic B全网格解析传播。
11. position-only B：否。
12. 文字一致性：`e=1/5/10 km`只能称攻击方固定参考点/receiver location error，不是B orbit difference。冻结joint的active compensation结论只来自REAL_B。

### 5.6 Formal joint-security reconstruction

1. 脚本：`freeze_causal_a_doppler_core_reconstruction_design.py`、`run_causal_a_doppler_core_reconstruction.py`、`run_existing_doppler_case_orbit_distinct_relabeling.py`。
2. 关键位置：core family定义 `70-74/84-88`；synthetic spec `450-462`；state `483-568`；Doppler `621-656,753-795`。
3. 输入：R2 frozen `B_identity_or_perturbation_definition`；segment synthetic 12 units，controlled altitude 300 units；其余real B。
4. A来源：latest `CREATION_DATE<=evaluation_time` 的causal public GP，传播至anchor/evaluation time。
5. B生成：`Perturb(A_causal,frozen original factor/rule)`；不保留旧absolute synthetic B。
6. 显式生成position和velocity；不修改原GP/TLE。
7. 等效圆轨道参数后解析传播。
8. r/v共同定义物理可传播osculating circle。
9. A/B orbit scoring严格共同evaluation epoch。
10. Doppler使用同一causal A与同一规则的full saved segment timeseries；不是只使用orbit-gate时的单点B position。
11. 未发现position-only joint B。
12. `SYNTHETIC_RELATIVE_TO_A`与实现一致，但论文应注明“causal-A-relative two-body circular state perturbation”。

### 5.7 Near-orbit local position diagnostic

1. 脚本：`scripts/run_tle_error_lower_bound_calibration.py`。
2. 关键位置：`300-332`。
3. 输入：`delta=[0.1,0.2,0.5,1,2,5,10,20,50,100,200] km`，`along_pos/along_neg`。
4. A来源：目标TLE在每个timestamp传播的`position`和`velocity`。
5. B生成：每个时刻在A position上加减`delta·normalize(v_A(t))`。
6. 只修改position；没有共同定义velocity或orbital elements。
7. 无element构造、无B轨道传播。
8. `delta_r`沿每时刻速度方向变化；如果把这条position path求导，必然包含`delta·d(v_hat)/dt`，代码既未声明该速度，也未检验其满足引力动力学。
9. 样本timestamp与A相同，但没有一个B initial epoch state被传播。
10. Doppler来自偏移后range的数值gradient，不是完整propagated B state。
11. 存在velocity未明确定义；符合C。
12. 输出CSV自身的`perturbation_model=instantaneous_along_track_position_offset`是准确表述；报告标题/段落中的“Near-Orbit Delta下界”“along-track perturbation crossing”若被读成另一条物理轨道则过强。

## 6. 方向与坐标系专项结论

### 6.1 radial / altitude

- synthetic altitude不是ECEF z方向，也不是地面海拔方向。
- 它在A anchor的惯性radial方向上定义圆轨道半径差：`R_B=|r_A(anchor)|+delta_h`。
- formal joint随后把共同epoch的实际`r_B-r_A`投影到A的RTN；RTN是**评分/描述坐标系**，不是用来做position-only synthetic translation。

### 6.2 along-track / phase

- circular phase offset在由`p_hat,q_hat`定义的惯性轨道平面内改变相位，并使用同一共同观测timestamp；不是拿A在`t+delta_t`的SGP4 state冒充B，也不是单点Cartesian translation。
- near-orbit lower-bound脚本的`along_pos/along_neg`则是每时刻沿`v_hat_A(t)`做position offset，属于C。两者不可混称“along-track X km orbit”。

### 6.3 normal / inclination

- 当前synthetic inclination family是在惯性frame中围绕node axis旋转轨道面候选，再生成完整圆轨道。
- 它不是简单加`delta_N`的RTN position translation。
- orbit-uncertainty数据中的`delta_N_km`来自两个完整传播state之差投影到RTN，不是synthetic constructor。

### 6.4 East / North / direction / heatmap

- `destination(C,d,phi)`在地球表面按geodesic bearing布置接收点：`0°=North, 90°=East, clockwise`。
- East/North finite difference是在C附近分别移动地面参考/接收位置，重算`f_A-f_B`，用于receiver geometry sensitivity。
- `along_track_offset_km=d cos(phi)`、`cross_track_offset_km=d sin(phi)`是历史字段名；从实际代码看它们是C→S局部二维参数化，不是卫星RTN T/N，也不是B orbit displacement。论文中建议优先写`receiver local north/east or service-bearing offset`，避免与orbital along-track/cross-track混淆。

## 7. Paper wording 一致性裁决

### 可以继续保留

- legacy score-only、verifier-v2、window、fine-sweep、pass-quality等结果，前提是称为`controlled two-body circular synthetic-orbit/state perturbation`。
- formal controlled altitude family及joint F3：B具有动力学相容r/v，且R3确实对共同epoch完整state评分。
- segment-local synthetic子集及direction结论：B构造本身相容；方向结论应限定为receiver/service geometry。
- current active-compensation first-pass与direct-S ideal joint结论：使用REAL_B TLE，不受synthetic builder审计影响。
- orbit-uncertainty RTN ellipsoid、freshness conditioning与June validation：这些来自真实ordinary-GP/reference-GP完整state disagreement，不是position-only synthetic B。

### 只能重新命名为 local sensitivity analysis

- `outputs/metrics/near_orbit_perturbation_sweep.csv`及其派生`near_orbit_min_attack_delta.csv`中的`instantaneous_along_track_position_offset` family。
- 推荐论文/图注名称：`instantaneous along-track position-offset sensitivity`、`local geometric perturbation diagnostic`。
- 不应再把其`delta_min`写成物理可传播的“minimum different-orbit separation”或“另一条轨道的下界”。

### 若作为正式 different-orbit 证据必须重构

仅限上述near-orbit local-position family。需要从共同epoch定义完整`r_B,v_B`或受控orbital elements，再传播到全窗口；只有在论文仍需要该family作为正式“different orbit X km”证据时才需要重跑。当前primary synthetic families不需要因为本审计重构。

## 8. 对两条主线的影响

### 8.1 Orbit uncertainty 主线

影响：**无实质影响，不建议重开模型优化。**

原因：frozen orbit-uncertainty模型来自ordinary GP相对higher-quality reference GP的完整6D state disagreement，RTN primary虽使用signed position三维量，输入state本身有完整position/velocity provenance；它不依赖near-orbit local-position sweep来拟合、校准或验证。local diagnostic最多影响一个历史“near-orbit lower bound”的解释标签。

### 8.2 Joint-security 主结论

影响：**不推翻，也不要求R4或全量重跑。**

证据：冻结R2/R3 formal core仅含：

```text
segment_local_heatmap_and_direction_sensitivity
controlled_altitude_difference_synthetic_B
same_pair_multi_pass_real_TLE
active_compensation_first_pass
```

其中synthetic core在R3显式生成共同epoch `r_B,v_B`；real families正常传播TLE。near-orbit local-position family不在407个executed LEVEL-A units、26780 rows或265个ORBIT_DISTINCT primary units中。因此joint claim“orbit-distinct yet Doppler-accepted units exist”不依赖C类构造。

需要补到论文limitations/method wording的一点是：primary synthetic B是“由causal A局部state初始化的两体圆轨道扰动”，不是独立TLE/真实Starlink轨道样本。

## 9. 最终 verdict

`PARTIAL_LOCAL_POSITION_PERTURBATION_FOUND`

- 发现位置：historical TLE-error / near-orbit along-track diagnostic。
- 未发现位置：当前primary controlled altitude synthetic-B、segment-local synthetic subset、formal joint-security `SYNTHETIC_RELATIVE_TO_A`。
- redesign范围：只有当near-orbit diagnostic要承担正式“different orbit”证据时，才对该family重构并重跑。
- 当前主线处置：保留primary synthetic和REAL_B实验；不重开orbit uncertainty；不推翻joint-security；修正文稿对`km`和direction的坐标/语义标签。

## Appendix A. 共用 builder 的 caller inventory

直接复用`synthetic_same_plane_geo`的脚本：

```text
scripts/analyze_single_station_baseline_closure.py
scripts/analyze_verifier_v2_hard_cases.py
scripts/run_causal_a_doppler_r1_level4_numerical_divergence_root_cause_audit.py
scripts/run_causal_a_doppler_reconstruction_reproduction_validation_rerun.py
scripts/run_controlled_altitude_difference_risk_experiment.py
scripts/run_doppler_verifier_initial_experiments.py
scripts/run_full_pass_quality_coverage_expansion.py
scripts/run_pass_quality_aware_attacker_search.py
scripts/run_verifier_v2_fine_sweep_attacks.py
scripts/run_verifier_v2_hard_case_multipass.py
scripts/run_verifier_v2_hard_case_multiwindow.py
scripts/run_window_reliability_calibration.py
```

经`generate_attack_geo/generate_synthetic_geo`间接复用同一altitude/inclination builder的脚本：

```text
scripts/audit_fixed_point_active_compensation_outputs.py
scripts/check_fixed_reference_compensation_alignment.py
scripts/check_fixed_reference_compensation_sanity.py
scripts/reproduce_original_50km_rejection_experiment.py
scripts/run_fixed_point_active_compensation_sensitivity.py
scripts/run_fixed_reference_compensation_extended_sensitivity.py
scripts/run_multi_service_area_single_station_confirmation.py
scripts/run_multistation_consistency_first_pass.py
scripts/run_segment_local_expanded_sample_confirmation.py
scripts/run_single_station_bk_gate_ablation.py
scripts/run_window_aware_evidence_accumulation.py
scripts/run_window_reliability_calibration.py
```

完整state/reconstruction helper：

```text
scripts/run_existing_doppler_case_orbit_distinct_relabeling.py
scripts/run_causal_a_doppler_core_reconstruction.py
scripts/run_causal_a_doppler_reconstruction_reproduction_validation_rerun.py
```

唯一命中的position-only orbit-like perturbation helper：

```text
scripts/run_tle_error_lower_bound_calibration.py::perturb_along_track
```

## Appendix B. 关键 provenance 文件

- `outputs/datasets/doppler_verifier_initial_experiments_manifest.json`：声明same-plane circular approximation from target mid-pass ECI state。
- `outputs/metrics/controlled_altitude_difference_manifest.json`：formal delta_h、target/pass/seed与输入hash。
- `outputs/metrics/doppler_semantic_reconstruction_family_matrix.csv`：synthetic/real B family语义与主线裁决。
- `outputs/metrics/causal_a_doppler_r2_core_population.csv`：每个LEVEL-A unit的B class、扰动定义与重建规则。
- `outputs/datasets/causal_a_doppler_r3_unit_summary.csv`：共同epoch A/B state reconstruction identity、position/velocity separation、RTN displacement。
- `outputs/metrics/causal_a_doppler_r3_manifest.json`：407 units / 26780 rows执行与输入hash绑定。
- `outputs/reports/joint_security_final_results_freeze_and_paper_synthesis.md`：冻结论文主问题、265-unit endpoint与family边界。
- `outputs/metrics/near_orbit_perturbation_sweep.csv`：明确记录`perturbation_model=instantaneous_along_track_position_offset`。
