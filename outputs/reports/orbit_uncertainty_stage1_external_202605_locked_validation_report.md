# May locked external validation 参数冻结预检报告

状态：`MAY_LOCKED_EXTERNAL_VALIDATION_BLOCKED_APRIL_PARAMETER_PROVENANCE`

## 1. 已通过的冻结检查

- April Stage-1B canonical SHA：`2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23`，与冻结值一致。
- April 受保护 inventory 共 81 项，覆盖 Stage-1A/B/C/D/E 与 raw/provenance；当前 mismatch=0。
- April Stage-1D/1E status、window、manifest output SHA 均一致；Stage-1E freeze decision 仍为 `HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。
- May Stage-1B dataset SHA：`119F2DAA3896476E120F010A436D0B250E404D41326B57FAABFEAA9F2F73EF3F`，与 May manifest 完整绑定值一致。
- May Stage-1A 非空 manifest/reference 共 4 项，当前 SHA mismatch=0。
- May support 按 `0 < element_age_seconds / 3600 <= 36` 精确划分：PRIMARY=6094，OUTSIDE=87，总计 6181 行。
- May-derived fitted parameter count=`0`；未生成 coverage、per-satellite、freshness-bin、scale-persistence、regime-transfer 或 figures。

## 2. Parameter freeze audit

- M0：position base curves 与 velocity descriptive curves 已落盘。
- M1：April publication-age strata factors 已落盘。
- M2：20 颗 April partial-pooled satellite factors 已落盘。
- M3/M4：risk factors 与 P50/P90 risk-score cutpoints 已落盘；April classifier 只导出了 16 个 standardized coefficients。
- 缺失：`logistic_intercept`, `StandardScaler.mean_`, `StandardScaler.scale_`, `SimpleImputer.statistics_`, `serialized_fitted_pipeline_or_equivalent_complete_parameter_record`。

April 生产实现使用 `SimpleImputer(add_indicator=True) -> StandardScaler -> LogisticRegression`。仅有 standardized coefficients 不能把 May raw causal features唯一映射为 `predict_proba`；缺少 intercept 和 preprocessing statistics 时，同一组 coefficients 可对应不同 risk score 与 risk stratum。用 April feature/label 重新运行 `fit_regime_classifier` 或重新计算 preprocessing statistics 都属于重新拟合/重建未冻结参数，本轮没有执行。

## 3. 停止点

由于 M3/M4 无法从现有 April artifacts 无歧义恢复，严格的 M0-M4 locked external validation 未执行，不能输出 `MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE`。需要先在独立 provenance 修复任务中找回 April 当时已经拟合并冻结的完整 classifier artifact；不能使用 May 数据补参数，也不能现在重跑 April fit 后把新结果冒充原 frozen model。

详细逐项结果见 `outputs/metrics/orbit_uncertainty_stage1_external_202605_parameter_freeze_audit.csv` 与 `outputs/metrics/orbit_uncertainty_stage1_external_202605_correctness_audit.csv`。
