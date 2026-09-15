# Orbit Uncertainty Stage-1C：residual structure / freshness / regime characterization

## 1. Scope与输入

输入为冻结的Stage-1B canonical dataset：`outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv`，20颗、5675行、5675 nominal、0 excluded。本脚本仅读取该dataset及其provenance所指ordinary/SupGP raw，用于回查orbital elements；没有重建residual、改变sign/frame或修改Stage-1B。

本轮所有trimmed view、top-tail与episode label均为descriptive diagnostic。没有建立legitimate uncertainty threshold、RMS cutoff、maneuver detector或final calibration。

## 2. Freshness structure

- pooled element age vs position：Spearman=0.479595；Pearson=0.227122。
- pooled publication age vs position：Spearman=0.374009；Pearson=0.214289。
- element age关联强于publication age，但两者都只是描述性association。
- exclude pooled top 1%后 element-age Spearman=0.477866；逐星各自exclude top 1%后再pool为0.477625。
- 20颗中20/20的within-satellite element-age Spearman为正；逐星Spearman中位数=0.513444，per-satellite trimmed diagnostic中位数=0.514987。
- full-view element-age bin counts：0-6 h: n=737, 6-12 h: n=2435, 12-24 h: n=2215, 24-36 h: n=275, 36-48 h: n=11, 48-72 h: n=2。前四个样本量较充分的bin，其position median依次为0-6 h: 1.263 km, 6-12 h: 2.245 km, 12-24 h: 5.236 km, 24-36 h: 10.098 km。

36 h以上仅13行（36–48 h为11行，48–72 h为2行），且与高disagreement episode重叠；其极高bin quantile不可解释为稳定的cohort-wide freshness curve。

因此freshness relationship并非完全由少数最大值制造，但其强度随satellite和episode而异，不能只使用一个pooled curve代表所有目标。

## 3. RTN structure

Pooled position disagreement最常见dominant component为`T`，dominant proportion=0.9623。完整R/T/N median/P90/P95/max及逐星dominance见`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_rtn_component_summary.csv`与`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_satellite_summary.csv`。

结论来自实际absolute RTN components与逐行argmax，没有预设along-track必须主导。

## 4. SupGP RMS association

- RMS vs position Spearman=-0.001766。
- RMS vs velocity Spearman=-0.003120。
- typical（position低于pooled P95）RMS median=0.193000 km；global top-1% RMS median=0.211000 km。

RMS没有解释主要long tail；RMS quantile bins和高disagreement group比较只作描述，不建立cutoff。

## 5. Long-tail / regime candidates

- global top 1%：57行，最低position=127.197045 km。
- global top 0.5%：29行，最低position=264.093558 km。
- episode pattern counts：`{"candidate_transition": 4, "isolated_single_point_spike": 1, "persistent_high_disagreement": 2, "several_consecutive_epochs_elevated": 5}`。
- 831.098 km最大值属于同星多epoch连续高disagreement episode，不是isolated single-point spike。episode summary同时保存前后ordinary GP publication与ordinary/SupGP orbital-element变化，但这些只是candidate evidence，不是confirmed maneuver。
- 2/12个candidate episode在episode内部出现selected ordinary GP切换。最大episode为NORAD 48309，持续53.583 h、包含25个top-1% rows、内部selected GP切换3次；这说明publication/state变化可回查，但不足以赋予maneuver因果标签。

代表性时间序列卫星：48309, 60265, 47844, 47767。

## 6. Sensitivity与heterogeneity

Full、pooled top-1% trimmed和per-satellite top-1% trimmed均保留正的element-age association；因此pooled freshness/RTN structure不完全由极端长尾驱动。另一方面，逐星correlation和tail magnitude差异明显，正式nominal model需要按freshness并保留satellite/regime heterogeneity，而不是立即拟合一个无条件pooled threshold。

Trimmed view is diagnostic only, not the formal uncertainty population.

## 7. 当前研究判断

1. Legitimate disagreement随element age呈明显但非决定性的单调增长关系。
2. element age与position disagreement的关系强于publication age。
3. pooled RTN通常由`T`方向主导；逐星结果见satellite summary。
4. SupGP RMS与position/velocity disagreement的rank association接近零，不能解释主要long tail。
5. 最大long tail包含明显时间连续episode；并非全部是孤立点，但本轮不将其标为confirmed maneuver。
6. freshness关系在pooled/per-satellite trimmed sensitivity后仍存在，但强度具有明显异质性。
7. 已具备设计freshness-conditioned nominal uncertainty model的基础；仍需下一阶段显式决定regime handling、层级结构和calibration protocol。本轮不执行该calibration。

## 8. Outputs

- freshness：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_freshness_summary.csv`
- RTN：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_rtn_component_summary.csv`
- per-satellite：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_satellite_summary.csv`
- extreme rows：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_extreme_episode_audit.csv`
- regime candidates：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_regime_candidate_summary.csv`
- RMS：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_rms_association_summary.csv`
- correctness：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_correctness_audit.csv`
- manifest：`outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_manifest.json`
- figures：`outputs/figures/orbit_uncertainty_stage1c_20260401_20260430`
