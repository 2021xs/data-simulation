# Baseline Residual Matcher 报告

生成时间：2026-05-03 22:42

## 1. 本轮目标

实现并运行第一版 baseline residual matcher。目标是对每条仿真序列判断其最像哪个 accepted 样本的几何频率基线。本轮只做 accepted 候选上的 baseline 识别，不做攻击轨道场景，不修改仿真数据集。

当前 baseline 是 fitted-baseline sanity check，不是最终攻击实验。

## 2. 输入数据

- 仿真数据集：`outputs\datasets\simulated_frequency_dataset.csv`
- accepted 候选目录：`data\source_residual_datasets\accepted`
- 结果输出：`outputs\metrics\matching_result_summary.csv`
- 混淆矩阵：`outputs\metrics\confusion_matrix.csv`
- 图表目录：`outputs\plots`

候选时间范围：

| candidate | 点数 | t_min_s | t_max_s |
|---|---:|---:|---:|
| `8535896` | 151 | 49.194647 | 280.700978 |
| `8641460` | 157 | 39.695590 | 240.124480 |
| `8707816` | 141 | 24.613619 | 169.232629 |
| `8733468` | 149 | 42.425407 | 202.467826 |
| `9424971` | 161 | 40.767764 | 253.940815 |

## 3. 匹配方法

对每条 `sim_id` 序列，读取 `t_rel_s` 和 `f_sim_hz`。对每个 accepted 候选，读取 `t_rel_s` 与 `f_geo_fit_hz`，并将候选几何频率插值到仿真序列的时间点。若仿真序列时间范围超出候选时间范围，则跳过该候选。

随后计算：

```text
delta_i = f_sim_i - f_geo_candidate_i
delta_i = b + k * (t_i - t0) + e_i
score = sqrt(mean(e_i^2))
```

其中 `t0 = mean(t_i)`。RMSE 最小的候选作为 `predicted_label`。

## 4. 为什么拟合 b + k 后再比较 RMSE

仿真数据允许存在 registered offset / effective constant frequency bias 和一阶线性慢漂移。若直接比较原始 RMSE，评分会被常数偏置或线性项主导，而不是主要反映几何 Doppler 曲线形状差异。因此 baseline matcher 先拟合并吸收 `b + k(t-t0)`，再比较剩余残差 RMSE。当前方法是 candidate-conditioned profile least-squares Doppler matcher 的 baseline v1。

## 5. 总体结果

- 总序列数：2000
- 总体 accuracy：1.0000
- 平均评估候选数：1.40
- skipped candidate 总次数：7200

## 6. 按 scenario 的结果

| scenario | 序列数 | accuracy | mean true RMSE | median true RMSE | mean best wrong RMSE | median best wrong RMSE | mean margin | median margin | error count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `clean` | 500 | 1.0000 | 0.000000 | 0.000000 | 151.933494 | 151.933494 | 151.933494 | 151.933494 | 0 |
| `offset_linear_noise` | 500 | 1.0000 | 28.102234 | 27.850277 | 154.625150 | 154.297095 | 126.561617 | 126.658650 | 0 |
| `offset_only` | 500 | 1.0000 | 0.000000 | 0.000000 | 151.933494 | 151.933494 | 151.933494 | 151.933494 | 0 |
| `offset_plus_noise` | 500 | 1.0000 | 27.825550 | 27.499158 | 154.459039 | 154.438899 | 126.962454 | 127.077204 | 0 |

## 7. clean 和 offset_only 检查

- `clean` 是否全部正确匹配：是
- `offset_only` 是否全部正确匹配：是

## 8. 混淆矩阵摘要

| true_label | 8535896 | 8641460 | 8707816 | 8733468 | 9424971 |
|---|---:|---:|---:|---:|---:|
| `8535896` | 400 | 0 | 0 | 0 | 0 |
| `8641460` | 0 | 400 | 0 | 0 | 0 |
| `8707816` | 0 | 0 | 400 | 0 | 0 |
| `8733468` | 0 | 0 | 0 | 400 | 0 |
| `9424971` | 0 | 0 | 0 | 0 | 400 |

## 9. 最容易混淆的样本对

未发现误匹配样本对。

## 10. 当前结果说明什么

- 在当前 fitted-baseline 数据集下，matcher 能够识别来源几何曲线；
- `b / k` nuisance 拟合能够在本轮设置中吸收常数偏置和线性漂移，使比较更集中在几何频率曲线形状上；
- `clean` 和 `offset_only` 都能正确匹配，说明基础时间对齐、插值和残差评分流程没有明显错误。

## 11. 当前结果不能说明什么

- 不能说明真实攻击成功率；
- 不能说明 TLE / Skyfield 轨道攻击场景；
- 不能说明 pure CFO truth；
- 不能外推到当前 accepted 5 个候选以外的候选集合。

## 12. 图表输出

- `baseline_confusion_matrix.png`
- `rmse_margin_by_scenario.png`
- `accuracy_by_scenario.png`
- `true_vs_best_wrong_rmse_by_scenario.png`

图表仅用于 sanity check，不作为证明性结论。

## 13. 边界说明

- 当前候选只包含 accepted 5 个样本；
- 当前使用 `f_geo_fit_hz` 作为几何基线；
- 本轮不是攻击轨道场景，也不输出攻击成功率；
- 当前只是 baseline matcher，用于确认仿真数据集上的基础识别流程；
- 候选时间范围不足时按规则跳过，因此部分序列只与覆盖其完整时间范围的候选比较。

## 14. 下一步建议

如果 `clean` / `offset_only` 不能正确，需要先修 matcher；如果 baseline 正常，再进入 orbit-based generator。后续攻击场景再加入 altitude difference / TCA shift / similar orbit 等设置。
