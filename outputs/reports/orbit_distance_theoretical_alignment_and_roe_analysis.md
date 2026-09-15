# 轨道差异理论对齐与有限 ROE 解释分析

## 1. 审计范围与结论

本轮只读取冻结 R2/R3 provenance 与历史正文，未重跑 407 个 Level-A units、26780 条 observation rows、Monte Carlo、verifier、joint-security aggregate，也未修改 orbit uncertainty model。唯一数值工作是：对 11 个已存在 frozen units 按其原始 provenance 重建共同历元的完整 `r_A,v_A,r_B,v_B`，再做确定性的二体 osculating-element / ROE 后处理。

**最终 verdict：`THEORETICAL_ALIGNMENT_COMPLETE`。**

当前正式方法可稳定分层为：

1. `physical_position_separation_km`：共同历元 GCRS 中的瞬时 Euclidean position separation；
2. `ΔR/ΔT/ΔN`：同一瞬时相对位置在 chief A 的 RTN 中的有符号分量；
3. `rho99`：冻结 empirical RTN uncertainty model 的无量纲归一化距离，是 security primary representation 的判别尺度；
4. ROE：由共同历元完整 `r,v` 推出的 secondary explanatory layer，用来说明相同瞬时 km 背后是 relative semimajor axis、phase、eccentricity 还是 inclination structure；
5. 地面 `C–S distance` / receiver bearing：ground geometry，绝不是 satellite orbit separation。

没有发现新的 primary physics error。现有 primary experiment 无需因术语或轨道定义重跑；唯一 position-only historical family 继续维持 local geometric sensitivity diagnostic 定位。

## 2. 理论口径与计算约定

采用 A 为 chief、B 为 deputy 的准非奇异 ROE：

```text
δa   = (a_B - a_A) / a_A
δλ   = (u_B - u_A) + (Ω_B - Ω_A) cos(i_A),  u = ω + M
δe_x = e_B cos(ω_B) - e_A cos(ω_A)
δe_y = e_B sin(ω_B) - e_A sin(ω_A)
δi_x = i_B - i_A
δi_y = (Ω_B - Ω_A) sin(i_A)
```

角差 wrap 到 `[-π,π)`；长度尺度全部乘 chief semi-major axis `a_A`。这一口径与 D’Amico 等对 near-circular formation flight 的 relative mean longitude、relative eccentricity vector、relative inclination vector定义一致；文献也明确指出 instantaneous Hill/RTN position 是随 argument of latitude 变化的映射，relative eccentricity 产生 R/T 周期结构，relative inclination 产生幅值约 `aδi` 的 N 周期结构。[D’Amico et al., ISSFD 2009](https://issfd.org/ISSFD_2009/FormationFlyingI/Damico.pdf)；[Stanford Space Rendezvous Laboratory, relative astrodynamics models](https://slab.stanford.edu/projects/models)。

本报告的状态/元素约定：

- A 的 causal GP 与 real B 的 static TLE 均先按原工程 SGP4 传播，再由 TEME 转为 GCRS；synthetic B 复用原工程 complete circular two-body `r,v` construction。
- 在每条 frozen unit 的 `evaluation_time` 同时计算 A/B；所有 `Δ` 与 ROE 都是 B minus A。
- `μ = 398600.4418000 km³/s²`；从共同历元 GCRS Cartesian state 计算二体瞬时 osculating elements。
- `a·δλ` 等是可解释的 length-scaled ROE，不是新的 distance norm，不进入 gate。
- 对相距数千至一万 km 的 real pairs，ROE 数值仍可由完整 state 定义，但 near-circular small-separation linear RTN mapping 只作定性结构解释，不能当高精度局部线性模型。
- 单时刻 RTN position **不能唯一反演 ROE**：六维相对轨道至少需要共同历元的完整相对 state（含 velocity）；不同 `Δv` 可在同一个 `Δr` 下给出不同 `δa/δe/δi`。

## 3. 术语 mapping

| historical_term | actual_semantics | coordinate/frame | recommended_term | paper_risk | action |
|---|---|---|---|---|---|
| orbit distance / orbital distance | 未限定时没有单一物理量；历史上下文可能指瞬时位置距离或不确定度归一化距离 | undefined unless qualified | 明确写 instantaneous A–B position separation、RTN displacement 或 rho99 | HIGH | 正式正文禁用裸术语；每次附量纲、历元与 frame |
| orbit difference | 对 A/B 完整相对状态或轨道结构的泛称，不等于单个 km 标量 | common-epoch GCRS state and/or element space | complete relative state / relative-orbit difference | MEDIUM | 如需定量，拆成 Δr/Δv、RTN 和/或 ROE |
| physical_position_separation_km | 共同 evaluation epoch 的 |r_B-r_A| | GCRS Cartesian Euclidean norm | instantaneous Euclidean A–B position separation | LOW | 保留；正文补 common epoch 与 GCRS |
| physical_velocity_separation_km_s | 共同 evaluation epoch 的 |v_B-v_A| | GCRS Cartesian Euclidean norm | instantaneous Euclidean A–B velocity separation | LOW | 保留并与 position 一起说明 complete state |
| delta_R_km / delta_T_km / delta_N_km | 共同 evaluation epoch 的 r_B-r_A 在 A 的 RTN 基底投影 | chief-A RTN; R outward, T direction of motion, N orbit normal | instantaneous chief-RTN relative-position components | LOW | 保留作为 security primary representation |
| rho99 | 冻结 empirical RTN 椭球中的 sqrt(D2/c99)，无 km 量纲且不是概率 | signed 3-D RTN uncertainty-normalized space | P99-normalized empirical RTN distance (not probability) | HIGH | 不得称 km distance、概率或 ROE distance |
| 5 km / 10 km | 孤立写法语义不唯一；项目中至少出现地面距离、anchor radius offset、瞬时 A–B separation、RTN component | context dependent | 总是加限定词与 frame | HIGH | 逐处替换为 ground geodesic / anchor-radius / instantaneous GCRS / RTN |
| distance_km / distance_to_center_km | segment/direction family 中地面参考点 C 到服务点 S 的测地距离 | Earth surface geodesic / receiver local tangent parameterization | ground C–S geodesic separation | HIGH | 不得写成 satellite orbit distance |
| C_S_distance_km / e_km / R_km | A2/fixed-C 语境中的地面 C–S 或参考半径实验因子 | Earth surface geodesic or prescribed ground-radius grid | ground C–S geodesic separation / ground radius factor | HIGH | 首次出现给出 C、S 定义；禁止与 r_A/r_B 混用 |
| along_track_offset_km (segment receiver geometry) | 历史字段实际为 d cos(phi) 的地面局部二维分量 | receiver local tangent / bearing parameterization | receiver-local ground-direction component | HIGH | 论文重命名；不得称 orbital along-track |
| cross_track_offset_km (segment receiver geometry) | 历史字段实际为 d sin(phi) 的地面局部二维分量 | receiver local tangent / bearing parameterization | receiver-local ground-direction component | HIGH | 论文重命名；不得称 orbital cross-track |
| along-track / cross-track / radial (orbit context) | 相对于 chief A 的 T/N/R 方向，不等于 East/North 或地面 bearing | chief-A RTN | RTN transverse / normal / radial | MEDIUM | 每处显式写 RTN；不要和 receiver-local 术语混用 |
| altitude difference / altitude_offset_km / delta_h_km | synthetic anchor 时刻在 A 的径向单位矢量上改变圆轨道半径；B 的圆轨道速度随新半径共同定义 | anchor GCRS radial direction; circular two-body construction | synthetic anchor orbital-radius offset | HIGH | 不要自动写成 ΔR=Δa 或恒定 A–B 距离 |
| same-plane phase offset / phase_offset_s | B 在其完整圆轨道上使用 dt+phase_offset_s；是时间参数化的相位偏移 | synthetic orbital plane / mean-longitude-like phase | synthetic orbital phase-time offset | MEDIUM | 正文可同时给 a·δλ，不能把秒直接称 km |
| inclination offset / orbit-plane perturbation | anchor 处旋转目标法向后重建 B 的圆轨道平面与完整速度 | GCRS inertial orbit-plane construction | synthetic orbit-plane/inclination construction parameter | MEDIUM | 报告实际 ROE inclination vector；参数角不等于单时刻 ΔN |
| direction offset / direction sensitivity | 可能指地面 C→S bearing，也可能指 orbital RTN；历史主线以前者居多 | receiver local tangent or chief-A RTN depending family | ground service-bearing sensitivity / RTN-direction sensitivity | HIGH | 拆分命名，不单写 direction offset |
| position offset | 必须区分完整 state construction 与仅改 position 的 historical diagnostic | Cartesian frame, epoch dependent | complete-state local perturbation 或 position-only local diagnostic | HIGH | 检查 velocity provenance；不能据单个 Δr 宣称另一条轨道 |
| perturb_along_track / near-orbit lower-bound family | 逐时刻沿速度方向平移 position，velocity 未作为 B state 定义 | local Cartesian direction at each sample | local along-track position sensitivity diagnostic | HIGH | 维持降级；不得作为 different-orbit evidence |
| SYNTHETIC_RELATIVE_TO_A | 由 causal A 的 anchor 完整 r,v 基底构造新的 circular two-body r_B,v_B 并传播到 evaluation epoch | GCRS state; two-body circular synthetic propagation | physically consistent local-state-initialized synthetic orbit | LOW | 保留；同时报告 construction parameter 与实际 common-epoch RTN/ROE |
| REAL_B | 静态 Starlink TLE 中另一 NORAD 对象在 A evaluation epoch 的完整传播状态 | TLE/SGP4 TEME transformed to GCRS | real-catalog B propagated to common epoch | LOW | 保留；声明来源为 static TLE，不称 synthetic |

### 3.1 主要混淆风险

- 裸写“5 km orbit difference”风险最高：它可能是 ground C–S geodesic、synthetic anchor orbital-radius offset、common-epoch `|Δr|`，或某一 RTN component。论文必须明确是哪一种。
- segment-local 历史字段 `along_track_offset_km/cross_track_offset_km` 实际是 receiver-local ground geometry；应改称 ground/service-bearing components，不得拿来解释 satellite RTN T/N。
- controlled altitude 的 `±1/±5/±10 km` 是 **anchor 时刻 orbital-radius construction factor**，不是 universal orbit-distance threshold，也不保证在所有 epoch 有 `|Δr|=|Δh|`、`ΔR=Δh` 或 `Δa=Δh`。
- `rho99` 无量纲、依赖 signed RTN、freshness bin、empirical center/covariance/c99；它既不是 physical km、概率，也不是 ROE norm。

## 4. Representative-case selection 与复算一致性

共 11 cases：同一 A/pass geometry 上的 `Δh=0,±1,±5,±10 km` 七点；冻结的 `+60 s` phase case；冻结的 `+0.2 deg` orbit-plane construction case；real-B ORBIT_DISTINCT 中 controlled acceptance 最大的一例；以及 zero-acceptance 中 rho99 最接近边界的一例。高度组用“拥有全部七个 levels 的最小 A_id/segment id”选择，不读结果；加入 frozen `Δh=0` 只为分离 circularization baseline 与 signed altitude factor 的增量。real 高/低组因任务明确要求两个 acceptance strata，分别在冻结 strata 内按预先声明的极值和稳定 tie-break 选择。没有新造 case 或随机观测。

冻结状态复算最大误差：position norm `1.110e-16 km`，velocity norm `8.153e-17 km/s`，RTN component `5.684e-14 km`。这确认 CSV 中 ROE 来自与 frozen joint-security unit 一致的 A/B state provenance，而不是新实验状态。

| case | B type | factor | ΔR / ΔT / ΔN (km) | aδa / aδλ (km) | a‖δe‖ / a‖δi‖ (km) | dominant ROE | frozen orbit / acceptance |
|---|---|---:|---:|---:|---:|---|---|
| controlled_altitude_-10_km<br>orbit_unit_0d7f59dc2c168fe16e2ac110 | SYNTHETIC_RELATIVE_TO_A | Δh=-10 km | -10.0029 / -0.00734456 / -9.5879e-07 | -13.6987 / -10.4709 | 6.40488 / 0.00450462 | relative_semimajor_axis | ORBIT_DISTINCT / 0.6333 |
| controlled_altitude_-5_km<br>orbit_unit_44ec0da0cd3264a2a475a8bb | SYNTHETIC_RELATIVE_TO_A | Δh=-5 km | -5.00292 / -0.00316015 / -9.62248e-07 | -8.69865 / -10.4667 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | AMBIGUOUS / 0.7 |
| controlled_altitude_-1_km<br>orbit_unit_7fa107f4ff07ae402763820f | SYNTHETIC_RELATIVE_TO_A | Δh=-1 km | -1.00292 / 0.000186277 / -9.65013e-07 | -4.69865 / -10.4634 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | AMBIGUOUS / 0.8333 |
| controlled_altitude_+0_km<br>orbit_unit_6b6addf52d23e271a1a78016 | SYNTHETIC_RELATIVE_TO_A | Δh=0 km | -0.00291756 / 0.00102273 / -9.65705e-07 | -3.69865 / -10.4625 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | NOT_ORBIT_DISTINCT / NA |
| controlled_altitude_+1_km<br>orbit_unit_2a0f2654b7f8156be143251e | SYNTHETIC_RELATIVE_TO_A | Δh=1 km | 0.997082 / 0.00185912 / -9.66396e-07 | -2.69865 / -10.4617 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | AMBIGUOUS / 0.7167 |
| controlled_altitude_+5_km<br>orbit_unit_a513b0aa321888ed64e05bf6 | SYNTHETIC_RELATIVE_TO_A | Δh=5 km | 4.99708 / 0.00520409 / -9.6916e-07 | 1.30135 / -10.4583 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | AMBIGUOUS / 0.8 |
| controlled_altitude_+10_km<br>orbit_unit_154e14b7a22c30461694b5f5 | SYNTHETIC_RELATIVE_TO_A | Δh=10 km | 9.99708 / 0.00938392 / -9.72614e-07 | 6.30135 / -10.4542 | 6.40488 / 0.00450462 | relative_mean_longitude_phase | ORBIT_DISTINCT / 0.7667 |
| phase_offset_plus_60_s<br>orbit_unit_239d32e6ed93ab3d8bf26832 | SYNTHETIC_RELATIVE_TO_A | Δt=60 s | -15.3111 / 457.522 / -0.000276533 | -4.45569 / 445.659 | 7.67383 / 0.00412021 | relative_mean_longitude_phase | ORBIT_DISTINCT / 0.04 |
| inclination_offset_plus_0p2_deg<br>orbit_unit_8d45467e3c60a8d8865e75f5 | SYNTHETIC_RELATIVE_TO_A | Δi_param=0.2 deg | -0.00348542 / 0.00124129 / -0.00797476 | -4.45569 / -12.4941 | 7.67383 / 14.3051 | relative_inclination_vector | NOT_ORBIT_DISTINCT / 0.8 |
| real_pair_highest_existing_controlled_acceptance<br>orbit_unit_4338539a1e1193e95fa38af5 | REAL_B | 47383 | -8062.6 / -3687.45 / 5641.2 | 10.0015 / 17661.1 | 8.45314 / 13573.1 | relative_mean_longitude_phase | ORBIT_DISTINCT / 0.35 |
| real_pair_zero_acceptance_nearest_rho99_boundary<br>orbit_unit_812f05a5b480962313951faf | REAL_B | 65410 | -6.81898 / 306.713 / 0.273473 | -0.259353 / 307.197 | 0.56034 / 0.918712 | relative_mean_longitude_phase | ORBIT_DISTINCT / 0 |

完整 state、A/B osculating elements、六个 dimensionless ROE、六个 `a·ROE` 与复算误差见 `outputs/metrics/representative_roe_characterization.csv`。

## 5. 三个 synthetic family 的特别验证

### 5.1 Controlled altitude

| Δh parameter (km) | common-epoch ΔR (km) | absolute aδa (km) | Δ(aδa) vs Δh=0 (km) | absolute aδλ (km) | Δ(aδλ) vs Δh=0 (km) | a‖δe‖ (km) |
|---:|---:|---:|---:|---:|---:|---:|
| -10 | -10.002918 | -13.698654 | -10 | -10.470906 | -0.0083825683 | 6.4048829 |
| -5 | -5.0029176 | -8.6986537 | -5 | -10.46671 | -0.0041874539 | 6.4048829 |
| -1 | -1.0029176 | -4.6986537 | -1 | -10.46336 | -0.00083687889 | 6.4048829 |
| 0 | -0.0029175649 | -3.6986537 | 0 | -10.462523 | 0 | 6.4048829 |
| 1 | 0.99708243 | -2.6986537 | 1 | -10.461686 | 0.00083657326 | 6.4048829 |
| 5 | 4.9970824 | 1.3013463 | 5 | -10.458343 | 0.0041798131 | 6.4048829 |
| 10 | 9.9970824 | 6.3013463 | 10 | -10.454171 | 0.0083520048 | 6.4048829 |

绝对 B−A ROE 不能被简化成“只有 δa”：即使 frozen `Δh=0`，B 仍按 anchor radius 被圆化，而 A 是 causal TLE/SGP4 state，所以本例已有 `aδa=-3.69865 km`、`aδλ=-10.4625 km`、`a‖δe‖=6.40488 km` 的 construction baseline。表中多数单例按最大 length-scaled component 会显示 phase-dominant，这不是 altitude 因子失效，而是 absolute B−A ROE 包含了共同的 circularization baseline。

隔离 `Δh=0` baseline 后，signed altitude sweep 的 **增量结构** 很清楚：`Δ(aδa)` 与输入 `Δh` 在数值精度内一一对应；`a‖δe‖` 在七点间保持不变；`aδλ` 只因不同半径的 mean motion 在 anchor/evaluation 半秒差中发生毫米至米级变化。换言之，controlled factor 主要注入 relative semimajor-axis / orbital-radius structure，但每个 absolute A/B pair 还同时带有 phase/eccentricity background。`ΔR` 与 absolute `aδa` 不是定义上相等；本例二者相差约 `3.69574 km`。结论应写“anchor orbital-radius offset whose incremental ROE effect is primarily relative semimajor axis”，不能写 `ΔR=Δa=Δh`。

### 5.2 Phase offset

`+60 s` case 的 common-epoch RTN 为 `ΔR=-15.3111 km, ΔT=457.522 km, ΔN=-0.000276533 km`；length-scaled ROE 为 `aδλ=445.659 km`、`a‖δe‖=7.67383 km`、`aδa=-4.45569 km`。因此主结构是 relative mean longitude / phase；同时存在非零 relative eccentricity，原因仍包括 synthetic B circularization 与 A osculating eccentricity。不能把它表述成一个纯 Cartesian T translation，也不能声称除 phase 外其他 ROE 严格为零。

### 5.3 Inclination / orbit-plane offset

`+0.2 deg` 是 constructor input label，不是本例最终 classical `i_B-i_A` 或两轨道面夹角的保证值。共同历元完整 state 给出 `i_B-i_A=0.0717196 deg`、plane separation=`0.119699 deg`、`a‖δi‖=14.3051 km`；其 dominant structure 为 `relative_inclination_vector`。这不影响 B 的动力学一致性，但论文应称“`+0.2 deg` orbit-plane construction parameter”，不能称“实际 classical inclination 精确增加 0.2 deg”。

该 case 的瞬时 `ΔN=-0.0079747574 km`，远小于 `a‖δi‖`，正是“single-epoch N 很小不代表 plane difference 很小”的例子：near-circular 一阶图景中 N 随 chief argument of latitude 近似谐波变化，振幅与相位由 relative inclination vector 决定；如果 evaluation epoch 接近两轨道面的交线，瞬时 `ΔN` 可以接近零，而别的 orbital phase 会变大。实际 `δi_x/δi_y` 必须由完整 `r,v` 计算，不能只从参数标签或单点 `ΔN` 推断。该标签—realized-angle 差异只要求术语校正；R3 的 orbit gate 与 joint result 本来就使用 realized `r,v→RTN→rho99`，所以无需重跑 primary experiment。

## 6. Real-pair 与 Doppler outcome 的解释边界

两个 real-B case 证明两件事：

1. real B 的来源是 static Starlink TLE，经 SGP4 传播到 A 的同一 evaluation epoch；不属于 synthetic construction。
2. frozen controlled acceptance 与“某一个 Euclidean km”不存在一一对应。高 acceptance representative 与 zero acceptance representative 分别为 `orbit_unit_4338539a1e1193e95fa38af5` 和 `orbit_unit_812f05a5b480962313951faf`；其 Doppler outcome 仍由 pass/receiver geometry、时间曲线与 verifier profile fit 共同决定。ROE 在此只解释相对轨道结构，不预测 acceptance，也不建立新 gate。

## 7. 对五个最终问题的回答

1. **“同样 5 km 的 R/T/N 是否应视为不同？”——是，且 RTN + ROE 已足够作理论解释。** RTN 首先区分同一瞬时 5 km 位于 radial、transverse 还是 normal；ROE 再解释它来自 semimajor-axis/phase/eccentricity/inclination 的何种六维相对轨道结构。二者不等价，但互补。
2. **当前 RTN empirical uncertainty model 仍适合作为 security primary representation。** 它直接对应已冻结、可校准的 public-orbit prediction error coordinates 与 signed covariance structure；本轮没有发现需要替换它的物理错误。
3. **ROE 只需要作为 explanatory layer。** 不建 ROE ellipsoid、不设 P95/P99、不替代 rho99、不进入 verifier/security gate。
4. **没有 primary experiment 因术语/轨道定义必须重跑。** 需要的是论文术语收紧与图表 caption 对齐。historical `perturb_along_track` 继续只称 local position sensitivity；若未来想把该 family 当 different-orbit evidence，才需要另行重构，但这不是当前 primary 的缺口。
5. **可以正式结束 orbit-distance methodological alignment。** 结束条件是正文遵循本报告 mapping，固定写清 quantity、epoch、frame 与 construction semantics；不要求改 orbit uncertainty model 或重跑 frozen joint science。

## 8. Paper-ready wording

推荐：

> The primary orbit-distinctness representation remains the signed, freshness-conditioned RTN empirical uncertainty model. Physical separation is reported as an instantaneous common-epoch GCRS norm, while finite quasi-nonsingular ROE are used only post hoc to explain whether a given RTN displacement is associated mainly with relative semimajor axis, mean longitude, eccentricity, or inclination structure.

> The controlled ±1/±5/±10 km altitude parameter is an orbital-radius offset applied at the synthetic construction anchor. It is not assumed to equal the common-epoch radial displacement, semimajor-axis difference, or a universal orbit-distance threshold.

禁止：

> A 5 km orbit difference means the same geometry in every direction.

> rho99 is the probability that two satellites occupy different orbits.

> A single RTN position vector uniquely determines the relative orbit.

## 9. Provenance 与只读边界

输入 SHA256（运行前后未改变）：

- `outputs/datasets/causal_a_doppler_r3_unit_summary.csv`: `9C5EB780673C584DE7D92D14C55D2D6DB6FB9B0C523A02625BE32C31E2AD13CE`
- `outputs/metrics/causal_a_doppler_r2_core_population.csv`: `68C1A150438A17D74CD8CB3FEF1C13F03EE452BB42BA43C4519DD8ED6FB87074`
- `data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260226_20260329_20sat_omm.json`: `3E826D049CE3CEFC66875D5178617D8E388B87ED9ED41D36D700AD38005A56B1`
- `data/tle/starlink_tle.txt`: `B63220F9798B0E7B77876C28AB9E90BE6878E37A629762795BBF0DEA354D8625`

本轮新增的三个 artifact 是解释性审计产物，不属于 Monte Carlo dataset、verifier metrics 或 frozen joint-security result。脚本为 `scripts/analyze_orbit_distance_roe_alignment.py`；运行只允许覆盖该脚本自己的三个输出。
