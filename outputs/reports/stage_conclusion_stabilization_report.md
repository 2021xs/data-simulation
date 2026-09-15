# 当前阶段结论固化复核报告

生成时间：2026-07-02 18:07:17

## 1. 为什么要固化当前结论

本报告只复算和归一化已有离线仿真输出，不引入新传播模型、不接入真实链路，也不把结果解释为真实世界攻击成功率。目标是把短窗口累计、固定参考点补偿、b/k 消融和多站一致性四条已有结论链条放到同一统计口径下，使用“非目标样本误接受率”作为主指标，便于当前阶段收尾。

- 统一 dataset 行数：`148596`
- 主 summary 行数：`3137`
- 输入来源：window-aware、single-station b/k gate ablation、multi-station consistency first pass 的既有 CSV；脚本同时检查 fixed-reference extended CSV 是否存在。固定参考点主口径采用 single-station b/k gate ablation dataset，因为该表同时保留 b/k 模式和更完整的参考点误差范围。
- 样本组统一映射：`original_like/typical_orbit_similar -> ordinary_similar`，`hard_case_weighted -> boundary_case`，`random_simulated -> random_simulated`。

## 2. 短窗口结论是否稳定

`p95` 口径下，非目标样本误接受率：

| 策略 | n | 非目标样本误接受率 | DEFER 比例 | REJECT 比例 |
| --- | ---: | ---: | ---: | ---: |
| single_window | 3452 | 0.1805 | 0.1553 | 0.6643 |
| naive_accumulation | 3452 | 0.0046 | 0.0846 | 0.9108 |
| window_aware_accumulation | 3452 | 0.0032 | 0.0322 | 0.9647 |

窗口感知累计相对单窗口显著降低非目标样本误接受率；DEFER 保留了证据不足的样本，不把短窗口直接等价为最终 ACCEPT。

## 3. 固定参考点补偿的样本组差异

固定参考点补偿 current_bk / 单站主口径下，总体非目标样本误接受率为 `0.4083`。

按样本组拆分：

| sample_group     |   n_cases |   false_accept_rate |   defer_rate |   reject_rate |
|:-----------------|----------:|--------------------:|-------------:|--------------:|
| boundary_case    |       360 |            0.730556 |     0.194444 |      0.075    |
| ordinary_similar |       360 |            0.377778 |     0.461111 |      0.161111 |
| random_simulated |       360 |            0.116667 |     0.172222 |      0.711111 |

按参考点误差与样本组拆分：

| sample_group     |   reference_error_km |   n_cases |   false_accept_rate |   defer_rate |   reject_rate |
|:-----------------|---------------------:|----------:|--------------------:|-------------:|--------------:|
| boundary_case    |                    0 |        60 |           0.916667  |    0.0333333 |     0.05      |
| boundary_case    |                   50 |        60 |           0.816667  |    0.166667  |     0.0166667 |
| boundary_case    |                  100 |        60 |           0.783333  |    0.2       |     0.0166667 |
| boundary_case    |                  200 |        60 |           0.833333  |    0.0666667 |     0.1       |
| boundary_case    |                  500 |        60 |           0.633333  |    0.266667  |     0.1       |
| boundary_case    |                 1000 |        60 |           0.4       |    0.433333  |     0.166667  |
| ordinary_similar |                    0 |        60 |           0.833333  |    0.133333  |     0.0333333 |
| ordinary_similar |                   50 |        60 |           0.666667  |    0.233333  |     0.1       |
| ordinary_similar |                  100 |        60 |           0.4       |    0.4       |     0.2       |
| ordinary_similar |                  200 |        60 |           0.333333  |    0.533333  |     0.133333  |
| ordinary_similar |                  500 |        60 |           0.0333333 |    0.7       |     0.266667  |
| ordinary_similar |                 1000 |        60 |           0         |    0.766667  |     0.233333  |
| random_simulated |                    0 |        60 |           0.7       |    0.233333  |     0.0666667 |
| random_simulated |                   50 |        60 |           0         |    0.533333  |     0.466667  |
| random_simulated |                  100 |        60 |           0         |    0.266667  |     0.733333  |
| random_simulated |                  200 |        60 |           0         |    0         |     1         |
| random_simulated |                  500 |        60 |           0         |    0         |     1         |
| random_simulated |                 1000 |        60 |           0         |    0         |     1         |

随机样本在 50 km 后的非目标样本误接受率为 `0.0000`；普通相似样本在 200 km 后为 `0.1222`。混合平均值主要应结合样本组拆分解读，不能直接解释为所有普通样本在大参考点误差下都有同等风险。

## 4. b/k 是否仍是单站边界

fixed-reference compensation 下 b/k 消融结果：

| sample_group     | bk_mode    |   n_cases |   false_accept_rate |   defer_rate |   reject_rate |
|:-----------------|:-----------|----------:|--------------------:|-------------:|--------------:|
| boundary_case    | current_bk |       360 |            0.730556 |     0.194444 |     0.075     |
| boundary_case    | loose_bk   |       360 |            0.811111 |     0.130556 |     0.0583333 |
| boundary_case    | no_bk      |       360 |            0        |     0        |     1         |
| boundary_case    | strict_bk  |       360 |            0.475    |     0.45     |     0.075     |
| ordinary_similar | current_bk |       360 |            0.377778 |     0.461111 |     0.161111  |
| ordinary_similar | loose_bk   |       360 |            0.525    |     0.333333 |     0.141667  |
| ordinary_similar | no_bk      |       360 |            0        |     0        |     1         |
| ordinary_similar | strict_bk  |       360 |            0.194444 |     0.638889 |     0.166667  |
| random_simulated | current_bk |       360 |            0.116667 |     0.172222 |     0.711111  |
| random_simulated | loose_bk   |       360 |            0.119444 |     0.172222 |     0.708333  |
| random_simulated | no_bk      |       360 |            0        |     0        |     1         |
| random_simulated | strict_bk  |       360 |            0.05     |     0.233333 |     0.716667  |

总体上，`no_bk` 非目标样本误接受率为 `0.0000`，`current_bk` 为 `0.4083`，`loose_bk` 为 `0.4852`。这说明 b/k 拟合仍是单站验证器的重要边界；范围越宽，越容易把几何差异吸收到 fitted residual 参数中。

## 5. 多站一致性是否稳定有效

current_bk 下，多站策略汇总：

| station_strategy         |   station_separation_km |   n_cases |   false_accept_rate |   defer_rate |   reject_rate |
|:-------------------------|------------------------:|----------:|--------------------:|-------------:|--------------:|
| dual_station_all_accept  |                      10 |      2160 |            0.407407 |     0.218519 |      0.374074 |
| dual_station_all_accept  |                      50 |      2160 |            0.389352 |     0.193981 |      0.416667 |
| dual_station_all_accept  |                     100 |      2160 |            0.358796 |     0.191667 |      0.449537 |
| dual_station_all_accept  |                     500 |      2160 |            0.197685 |     0.27963  |      0.522685 |
| dual_station_all_accept  |                    1000 |      2160 |            0.116204 |     0.330093 |      0.553704 |
| single_station_baseline  |                      10 |      2160 |            0.457407 |     0.205556 |      0.337037 |
| single_station_baseline  |                      50 |      2160 |            0.457407 |     0.205556 |      0.337037 |
| single_station_baseline  |                     100 |      2160 |            0.457407 |     0.205556 |      0.337037 |
| single_station_baseline  |                     500 |      2160 |            0.457407 |     0.205556 |      0.337037 |
| single_station_baseline  |                    1000 |      2160 |            0.457407 |     0.205556 |      0.337037 |
| three_station_all_accept |                      10 |      2160 |            0.40463  |     0.203704 |      0.391667 |
| three_station_all_accept |                      50 |      2160 |            0.375926 |     0.18287  |      0.441204 |
| three_station_all_accept |                     100 |      2160 |            0.337037 |     0.196296 |      0.466667 |
| three_station_all_accept |                     500 |      2160 |            0.146759 |     0.313889 |      0.539352 |
| three_station_all_accept |                    1000 |      2160 |            0.062037 |     0.362037 |      0.575926 |

单站 current_bk 非目标样本误接受率为 `0.4574`，三站全通过为 `0.2653`，三站 + b/k 风险暂缓为 `0.0885`。站点间距增大时，多站 all-accept 约束整体更强，尤其在三站策略下更明显。

b/k 风险暂缓效果：

| station_strategy          |   current_bk_false_accept_rate |   bk_risk_defer_false_accept_rate |   defer_rate_increase |
|:--------------------------|-------------------------------:|----------------------------------:|----------------------:|
| dual_station_all_accept   |                       0.293889 |                         0.129259  |             0.16463   |
| single_station_baseline   |                       0.457407 |                         0.292593  |             0.164815  |
| three_station_all_accept  |                       0.265278 |                         0.0885185 |             0.176759  |
| two_of_three_reject_defer |                       0.308333 |                         0.173056  |             0.0965741 |

该结果支持：b/k 风险暂缓主要把一部分高风险 ACCEPT 转为 DEFER，而不是把它们直接解释为更强的 REJECT 证据。

## 6. 当前阶段是否可以收尾

当前阶段可以作为“单站边界与多站一致性初步分析”收尾。已经较稳定的结论是：

1. 短窗口单独判决风险高，窗口感知累计能降低非目标样本误接受率。
2. 固定参考点补偿风险主要集中在边界样本，小参考点误差和边界样本对混合平均值贡献较大。
3. b/k 拟合是单站误接受率升高的关键因素，no_bk 口径下非目标样本基本无法通过。
4. 多站一致性显著降低单站误接受率，站点间距越大约束通常越强。
5. b/k 风险暂缓可以把一部分高风险 ACCEPT 转为 DEFER。

仍需要下一阶段继续扩大的部分是：服务区域 / 分段参考点补偿、更多多站布局与窗口调度组合，以及更系统的边界样本覆盖。上述下一阶段仍应保持离线、合成、可复现仿真边界。

## 7. 本轮最终回答

1. 窗口感知累计是否稳定降低短窗口误接受率：是，single_window `0.1805` 降至 window_aware_accumulation `0.0032`。
2. 固定参考点补偿的误接受是否主要集中在边界样本：是，边界样本在 current_bk 下最高，详见样本组表。
3. 随机样本和普通样本是否在参考点误差增大后快速失效：随机样本 50 km 后保持低误接受；普通相似样本随误差增大整体下降，但需结合窗口和样本组拆分。
4. 不允许 b/k 吸收时，非目标样本是否基本无法通过：是，no_bk 为 `0.0000`。
5. 当前 b/k 设置是否显著提高单站误接受率：是，current_bk 为 `0.4083`，显著高于 no_bk。
6. b/k 风险暂缓是否主要将 ACCEPT 转为 DEFER：是，risk table 中 false accept 降低且 defer_rate_increase 为正。
7. 多站一致性是否稳定降低单站误接受率：是，single `0.4574`，three all-accept `0.2653`。
8. 站点间距越大，多站约束是否越强：总体是，三站 all-accept 随站距增大误接受率下降更明显。
9. 混合平均值是否由边界样本和小参考点误差主导：是，应优先看样本组和 reference_error 拆分表。
10. 当前阶段是否可以正式收尾，并进入“服务区域 / 分段参考点补偿”下一阶段：可以，但下一阶段仍应作为离线仿真压力测试，而非真实系统操作方法。

## 8. 生成的关键文件

- `outputs/datasets/stage_conclusion_stabilization_dataset.csv`
- `outputs/metrics/stage_conclusion_main_summary.csv`
- `outputs/metrics/stage_conclusion_by_sample_group.csv`
- `outputs/metrics/stage_conclusion_by_reference_error.csv`
- `outputs/metrics/stage_conclusion_by_bk_mode.csv`
- `outputs/metrics/stage_conclusion_by_station_separation.csv`
- `outputs/metrics/stage_conclusion_bk_risk_defer_effect.csv`
- `outputs/metrics/stage_conclusion_report_tables.csv`
- `outputs/reports/stage_conclusion_stabilization_report.md`
- `outputs/figures/stage_conclusion_stabilization/stage_pipeline_false_accept_rate.png`
- `outputs/figures/stage_conclusion_stabilization/false_accept_rate_by_reference_error_and_sample_group.png`
- `outputs/figures/stage_conclusion_stabilization/bk_ablation_false_accept_rate.png`
- `outputs/figures/stage_conclusion_stabilization/multistation_false_accept_rate_by_separation.png`
- `outputs/figures/stage_conclusion_stabilization/bk_risk_defer_accept_to_defer.png`
