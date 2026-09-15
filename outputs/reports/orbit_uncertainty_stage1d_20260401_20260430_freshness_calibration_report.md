# Orbit Uncertainty Stage-1D：freshness-conditioned legitimate disagreement calibration

## 1. Scope与输入

输入为冻结的Stage-1B canonical dataset：`outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv`，20颗、5675行、5675 nominal、0 excluded。Stage-1B未重建且SHA在本轮前后保持不变。Stage-1C的12个candidate episodes已按原算法复现，映射58行；其中50行位于primary support。

Primary conditioning variable为`element_age_seconds = evaluation_time - ordinary_gp_epoch`。`publication_age_seconds`只作为secondary sensitivity；SupGP RMS只做stratification，未成为filter或gate。

## 2. Calibrated support与经验基准

- formal calibrated support：`0 < element_age_hours <= 36`，共5662行、20颗。
- `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT`：13行，仍保留在canonical dataset，不生成formal prediction。
- requested `0-3 h`只有35行/14星，因此与`3-6 h`合并；requested `30-36 h`只有46行/15星，因此与`24-30 h`合并。最终6个bins均覆盖20/20星。
- 经验P50/P75/P90/P95及satellite-cluster bootstrap 500次95% CI见`outputs/metrics/orbit_uncertainty_stage1d_20260401_20260430_freshness_quantiles.csv`。

## 3. Continuous conditional quantile model

第一版连续模型采用：经验bin quantile → satellite-count weighted isotonic monotone projection → bin-center间piecewise-linear interpolation。该设计可解释、确定性、无>36 h extrapolation。P50/P90/P95 grid的最大monotone adjustment=0.000000 km，quantile-order adjustment=0.000000 km。

Grid中的0 h与36 h若超出实际observed min/max，会标记`boundary_display_only=true`并clamp到最近经验bin center，不声称observed support。

在grid的12 h位置：`|R| P95=0.617795 km`、`|T| P95=12.998018 km`、`|N| P95=0.356750 km`、position norm P95=`13.004771 km`。这些是conditional summaries，不是最终orbit-space boundary。

## 4. Coverage validation

- full-fit in-sample P95 coverage=95.11%，satellite-cluster CI=[93.71%, 96.53%]。
- LOSO P90 coverage=90.20%；P95 coverage=94.81%，cluster CI=[93.19%, 96.45%]。
- 20颗中有2颗的LOSO P95 coverage低于`target-0.05` descriptive line：48458, 60265。
- forward time block（Apr1-20 train → Apr21-30 test）P95=93.33%；reverse block P95=97.11%。

Forward/reverse相差3.79 percentage points；两者仍接近目标，但非完全时间稳定。forward test包含主要late-April high-disagreement episodes，不能把该差异解释成纯随机波动。

这些coverage是legitimate disagreement envelope validation，不是attack acceptance probability。

## 5. Regime sensitivity

FULL_SUPPORTED保留所有candidate rows；REGIME_EXCLUDED_SENSITIVITY仅用于诊断。position P95的最大经验bin相对变化发生在`24-36 h`：-22.89%（absolute -9.356424 km）。因此candidate episodes对高freshness tail的影响必须显式保留，不能静默合并或删除。

Regime comparison figure generated=true，触发标准为position P95任一bin绝对相对变化≥10%。

## 6. Secondary sensitivities

- element age vs position Spearman=0.476261；publication age=0.369976。element age继续表现出更强的rank association。
- RMS median split只用于stratified model comparison，不是cutoff。局部P95 grid最大相对变化=42.34%，但方向随freshness反转；最高RMS quartile在pooled envelope下coverage=93.01%。这不是稳定单调RMS effect，却说明下一版值得验证joint freshness×RMS conditioning，而不是建立RMS hard cutoff。

## 7. 当前判断

1. 0–36 h内经验quantile总体随freshness上升；连续模型通过显式monotone projection保持可解释，边缘bins的合并理由已冻结。
2. pooled coverage需结合LOSO逐星结果解释，不能只引用in-sample pooled比例。
3. satellite-specific undercoverage对象已单列，Wilson区间仅为行级描述并明确保留temporal-dependence限制。
4. candidate regime对P95 envelope的影响并非处处相同，在高age bin可明显改变tail。
5. time-block结果保留forward/reverse两个连续切分，未使用随机row split。
6. element age仍优于publication age作为primary conditioning variable；RMS不是第一阶替代变量。
7. 当前数据足以冻结calibration v1的方法、支持范围、经验表与validation artifacts；但由于candidate-regime P95 sensitivity、两颗LOSO undercoverage及forward/reverse time asymmetry，尚不足以把单一pooled envelope冻结为最终nominal uncertainty model。
8. 下一步应优先保留component-wise RTN calibration，因为position由T主导而velocity由vR主导；随后再研究能够保留相关结构的multivariate RTN/full-state set，而不是退化为fixed km sphere。

## 8. Scope guards

本轮没有synthetic B、1/5 km distinctness、Doppler、fixed global km threshold、confirmed maneuver label、RMS hard filter或>36 h formal extrapolation。没有从canonical dataset删除任何行。
