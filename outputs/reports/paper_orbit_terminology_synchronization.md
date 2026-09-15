# Paper-facing 轨道差异术语同步审计

## 1. 最终状态

**`PAPER_TERMINOLOGY_READY`**

本轮完成了论文相关报告、最终 frozen synthesis、claim/figure/table inventory、course-paper 导出物、主要图标题/坐标轴生成位置及历史 near-orbit diagnostic 的只读语义检查。没有修改任何 frozen report、figure、table、metrics、numerical result、verifier 或 uncertainty fitting；没有重跑实验，也没有建立 ROE gate。

审计结论是：现有数值证据与方法主线不需要改变，所有发现都可通过 paper-facing wording、caption、legend、heading 和 glossary 同步解决。逐文件建议共 44 条，保存在：

`outputs/metrics/paper_orbit_terminology_change_recommendations.csv`

其中：

- P0：34 条，需要在相关内容进入论文正文、caption 或正式 appendix 前同步；
- P1：5 条，建议补定义或限定；
- P2：5 条，已合规，或明确要求保留 frozen machine schema。

34 条 P0 不是 34 个独立科学错误。多数是同一语义同时出现在 frozen report、final inventory、figure generator 和历史 summary 中形成的重复 paper-facing 落点。当前没有 unresolved semantic ambiguity，因此不需要 `MANUAL_REVIEW_REQUIRED`。

## 2. 审计边界

### 2.1 纳入范围

- `README.md` 与 `docs/` 中的当前主线说明；
- `outputs/reports/` 中 joint-security final synthesis、orbit-distinct analysis、controlled-altitude、segment-local、uncertainty final review、历史 near-orbit summary 及两份已完成方法审计；
- `outputs/metrics/joint_security_final_*` 中 claim、terminology、figure、table 和 prohibited-wording inventory；
- `outputs/course_paper/*.tex` 的 table caption/row label；
- 直接生成 paper-facing figures 的脚本中的 title、axis label 与 caption 文本。

### 2.2 排除范围

- 原始/冻结 dataset 行值；
- `delta_h_km`、`phase_offset_s`、`inclination_offset_deg`、`distance_to_center_km` 等 machine schema；
- 数值结果、阈值、分类、acceptance fraction、rho99、RTN 数据；
- archive/smoke 文件中没有进入论文引用链的重复表格内容。

这些机器字段可以保留，论文第一次引用时必须用本报告的语义定义。禁止为了语言整洁而批量重命名 frozen schema。

## 3. 统一术语表

| 场景 | 论文首选中文 | Paper-facing English | 必须说明 | 禁止写法 |
|---|---|---|---|---|
| 瞬时 A/B 位置距离 | 共同评估历元 GCRS 瞬时 Euclidean A/B 位置间隔 | instantaneous common-epoch GCRS Euclidean A/B position separation | `|r_B-r_A|`、epoch、GCRS | bare `orbit distance`、`B is X km away in orbit` |
| Controlled altitude | anchor 历元有符号轨道半径构造偏移 `Δh` | anchor-epoch signed orbital-radius construction offset | `R_B(anchor)=‖r_A(anchor)‖+Δh`；完整速度随半径定义；实际 RTN 另报 | 恒定 A/B separation；`ΔR=Δa=Δh` |
| Phase family | 轨道面内轨道相位/时间构造参数 | in-plane orbital-phase/time construction parameter | B 沿完整 circular orbit 改变 phase | along-track Cartesian translation |
| Inclination family | `+0.2 deg` 轨道面构造参数 | `+0.2 deg` orbit-plane construction parameter | 参数不是实际 `i_B-i_A`；必要时给 audited realized geometry | actual inclination difference = 0.2 deg |
| Segment-local distance | 地面 C–S 测地距离 | ground C–S geodesic distance | `phi` 为 clockwise bearing；0° North，90° East | satellite separation、RTN T/N distance |
| Historical `perturb_along_track` | 瞬时沿轨位置敏感度 / 局部几何扰动诊断 | instantaneous along-track position-offset sensitivity / local geometric perturbation diagnostic | position-only；无完整 B velocity/propagated orbit | near-orbit distinct-orbit evidence |
| RTN primary gate | 新鲜度条件化经验 RTN 预测误差区域；不确定性感知相对位置可区分度 | freshness-conditioned empirical RTN prediction-error region; uncertainty-aware relative-position distinctness | signed RTN、freshness、empirical center/covariance/c99 | universal orbital distance、probability、ROE gate |
| ROE | 事后相对轨道结构解释 | post-hoc quasi-nonsingular ROE structural characterization | explanatory only；由完整共同历元 `r,v` 计算 | new threshold、new uncertainty model、security gate |

## 4. 发布前必须同步的主要位置

完整逐文件、逐行建议见 44-row CSV。以下为论文引用链中的最高优先级位置。

### 4.1 Final synthesis 与正式 claim inventory

| 文件/位置 | 当前风险 | 建议 |
|---|---|---|
| `joint_security_final_results_freeze_and_paper_synthesis.md:78` | 使用 `physical orbit distance` 裸术语 | 改为 `instantaneous common-epoch GCRS position separation`，并与 legitimate public-orbit uncertainty 分开 |
| 同文件 `:83` | `From physical separation...` 缺 frame/epoch | 改为 `From instantaneous common-epoch position separation to uncertainty-aware RTN relative-position distinctness` |
| 同文件 `:96`，figure F1 | `Physical separation versus rho99` 过宽 | caption 写明 GCRS、common epoch、`|r_B-r_A|` 与 empirical RTN `rho99` |
| 同文件 `:98`，figure F3 | `Controlled altitude` 可能被读成恒定高度差 | 改为 anchor-epoch signed orbital-radius offset |
| `joint_security_final_terminology.csv:8` | `uncertainty-normalized orbit distance rho99` 仍像 universal distance | 论文 glossary 覆盖为 `freshness-conditioned empirical RTN distinctness rho99` |
| `joint_security_final_claim_evidence_matrix.csv:C2` | `orbit separation` 含糊 | 改为 empirical RTN distinctness `rho99` |
| 同文件 `C3` | `Physical separation in km` 未限定 | 改为 instantaneous common-epoch GCRS Euclidean position separation |
| 同文件 `C4` | direction frame 未明确 | 明写 ground C–S geodesic + clockwise bearing；不是 satellite RTN |

`joint_security_final_prohibited_claims.csv` 中 P04/P05 的禁止句本身正确，但 safe replacement 也应将 `±5/±10 km` 限定为 anchor-epoch signed orbital-radius offsets。

### 4.2 Controlled altitude

必须在正文或第一次出现 `delta_h_km` 的 caption 中给出：

```text
R_B(anchor) = ||r_A(anchor)|| + Δh
```

并说明 B 的 circular speed/velocity 与该半径共同定义，随后沿完整 synthetic orbit 传播。推荐句式：

> The controlled factor Δh is an anchor-epoch signed orbital-radius offset. It is not assumed to equal the common-epoch radial displacement, the osculating semimajor-axis difference, or a constant A/B separation throughout the evaluation window.

需优先处理：

- `controlled_altitude_difference_report.md:1,9-11,266-272`：标题和结论中的“高度差”改为“anchor 历元有符号轨道半径偏移”；表内 frozen 字段不改。
- `controlled_altitude_difference_smoke_report.md:22`：不得引用 `r_B=r_A_reference+delta_h`；应写标量 radius 关系。
- `causal_a_doppler_core_reconstruction_design_and_freeze.md:14,33`：将 `signed physical altitude perturbation` 改为 anchor-radius construction description。
- `table_experiment_settings.tex:13`：`altitude fine sweep` 改成 `anchor-epoch signed orbital-radius-offset sweep`。
- paper plot generator `export_course_paper_verifier_artifacts.py:354-356` 和 joint plot generator `analyze_orbit_distinct_doppler_joint_security.py:698-702`：下次论文导出时同步 axis/title。

已审计的 `+1/+5/+10 km` 或负号数值仍然完全保留；只改变它们在论文中的物理释义。

### 4.3 Phase construction

推荐 caption：

> Synthetic B generated with an in-plane orbital-phase/time construction parameter Δt; this is not an along-track Cartesian position translation.

早期 `doppler_verifier_initial_experiment_report.md:43` 已使用“沿轨道相位/时间偏移”，基本合规。需要同步的是较短标签：

- `table_experiment_settings.tex:13` 与 `table_verifier_results.tex:13`；
- README 中 `same-plane altitude / phase perturbation` 的首次定义；
- figure legend 中的 `phase fine sweep`。

字段 `same_plane_phase_offset` 和 `phase_offset_s` 可原样保留。

### 4.4 Inclination / orbit-plane construction

所有 `inclination_offset=±0.2` 或 `synthetic_inclination_offset_0.2` 在 prose/caption 中必须解释为 constructor parameter，而不是 realized classical inclination difference。

对已审计的正向代表 case，如需报告实际几何量，使用：

```text
+0.2 deg orbit-plane construction parameter
i_B - i_A = 0.071720 deg
orbit-plane separation = 0.119699 deg
```

优先位置：

- `window_reliability_calibration_summary.md:9-18`；
- `window_aware_hard_case_and_defer_analysis.md:33-34`；
- `fixed_point_active_compensation_summary.md:114`；
- `differential_doppler_mechanism_audit_report.md:21-24,106-107`。

最后一项中的 frozen identifier 可以保持不变，但 caption/gloss 必须解释参数语义。该同步不改变 B 的动力学一致性，也不触发重跑。

### 4.5 Segment-local / heatmap

所有 `d=5 km`、`d=10 km`、`distance_to_center_km`、`phi_deg` 的 paper-facing 展示必须附：

```text
d = ground C–S geodesic distance
phi = clockwise initial bearing from North
phi=0 deg: North
phi=90 deg: East
```

这些数值不是 satellite `ΔT/ΔN`。优先位置：

- `m2_segment_local_expanded_sample_report.md:21-22`；
- `m2_segment_local_rho_fine_sweep_report.md:89-129`；
- `orbit_distinct_doppler_joint_security_analysis.md:41-54`；
- `run_segment_local_expanded_sample_confirmation.py:419-449` 的下次 paper figure axis。

最终 claim 中可写：

> Conditional verifier acceptance retained dependence on ground C–S geodesic distance and clockwise service bearing in the studied segment-local family.

不得把该现象称为 satellite RTN direction sweep。

### 4.6 Historical position-only diagnostic

`run_tle_error_lower_bound_calibration.py::perturb_along_track` 只改逐时刻 position，并未定义完整 B velocity。若历史结果被引用：

- `tle_error_and_near_orbit_lower_bound_summary.md:1,61-78,104-108` 改称 instantaneous along-track position-offset sensitivity；
- `run_tle_error_lower_bound_calibration.py:648-674` 的 figure title 改称 local position-offset crossing；
- 禁止使用 `near-orbit impersonation attack`、`physically distinct orbit` 或 `orbit difference X km` 作为该 family 的结论。

该 family 不进入 frozen joint primary，因此只需降级命名，不需要重跑。

## 5. Figure / table caption 模板

### Figure F1

> Instantaneous common-epoch GCRS A/B position separation versus freshness-conditioned empirical RTN distinctness `rho99`. The horizontal/vertical relationship is descriptive; physical kilometers do not define the uncertainty gate.

### Figure F3

> Anchor-epoch signed orbital-radius construction offset `Δh`, realized common-epoch RTN distinctness `rho99`, and conditional verifier acceptance. `Δh` is not a constant A/B separation and is not assumed to satisfy `ΔR=Δa=Δh`.

### Segment-local heatmap

> Conditional acceptance over ground C–S geodesic distance and clockwise initial bearing `phi` (`0°=North`, `90°=East`). These axes describe receiver/service geometry, not satellite RTN displacement.

### Phase sweep

> In-plane orbital-phase/time construction sweep for a complete synthetic-B state; not an along-track Cartesian translation.

### Inclination family

> Results indexed by the orbit-plane construction parameter. For the audited `+0.2°` case, the realized common-epoch values are `i_B-i_A=0.071720°` and orbit-plane separation `0.119699°`.

### Historical local diagnostic

> Instantaneous along-track position-offset sensitivity relative to the selected TLE residual band. This position-only diagnostic is not evidence for a separately propagated physical orbit.

## 6. RTN 与 ROE 的 paper-facing 边界

### RTN primary

保持以下表述：

> freshness-conditioned empirical RTN prediction-error region

> uncertainty-aware relative-position distinctness under the frozen empirical RTN model

可以保留正式方法名 `Freshness-Conditioned Robust Empirical RTN Ellipsoid`，但首次出现应加 plain-language definition。`rho99=sqrt(D2/c99)` 是无量纲 normalized distinctness scale，不是概率、物理 km 或 universal orbital distance。

### ROE explanatory only

ROE 在论文中只承担：

- 解释 altitude sweep 的增量 relative-semimajor-axis structure；
- 解释 phase family 的 relative-mean-longitude dominance；
- 解释 inclination family 的 relative-inclination-vector structure，以及瞬时 `ΔN` 随 orbital phase 变化；
- 说明单时刻 RTN position 不能唯一确定完整 relative orbit。

禁止出现：

- ROE threshold；
- ROE P95/P99；
- ROE uncertainty ellipsoid；
- ROE security gate；
- 用 ROE 替代 frozen RTN primary model。

当前项目中 ROE 仅出现在已完成的 theoretical-alignment report 与其确定性生成脚本中，尚未污染 verifier、uncertainty model 或 frozen joint-security result。

## 7. Exact banned-phrase check

对 paper-facing text/source 的 exact-string 搜索结果：

- `B is 5 km away in orbit`：0 个命中；
- `5km orbit difference`：0 个命中；
- `5-km orbit difference`：0 个命中；
- `5 km orbit difference`：4 个命中，全部位于 theoretical-alignment report/生成脚本中，作为“禁止写法”示例，不是 affirmative paper claim。

真正需要修正的是语义等价但不够精确的表达，例如 `physical orbit distance`、`uncertainty-normalized orbit separation`、`Controlled altitude`、`actual distance 5/10 km` 和未解释的 `inclination_offset=0.2`。

## 8. 应用顺序

建议在正式 manuscript layout 阶段按以下顺序人工应用，不回写 frozen artifacts：

1. 建立 manuscript-level glossary，覆盖 `joint_security_final_terminology.csv` 中过宽的 `orbit distance rho99` 表述。
2. 同步 final synthesis 的 section title、Claim C2/C3/C4、F1/F3 captions。
3. 同步 course-paper table/figure labels。
4. 对 controlled-altitude、segment-local、phase、inclination 的第一次出现加入 construction/frame definition。
5. 将 historical near-orbit family 从正文 primary evidence 排除；如放 appendix，使用 local position-sensitivity caption。
6. 全文最终搜索裸 `orbit distance`、`altitude difference`、`along-track`、`inclination offset` 与未定义的 `5 km/10 km`。

## 9. 最终判断

### PAPER_TERMINOLOGY_READY

- 已有 primary science、numerical results、RTN gate 和 joint-security conclusions 均可保留。
- 没有新增 science、模型或实验需求。
- ROE 仅作为 post-hoc explanatory layer。
- 所有已发现的 paper-facing 风险均有确定的 replacement wording 和定位。
- 本轮不直接修改 frozen reports；44-row change list 可供 manuscript 人工同步或后续单独的非科学性排版任务使用。

