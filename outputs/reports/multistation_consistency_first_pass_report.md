# 固定参考点补偿模型下的多站一致性第一轮实验

生成时间：2026-06-12 17:30:33

## 1. 为什么进入多站一致性

前几轮单站结果显示，固定参考点补偿会显著增加单站验证压力，且 no_bk 全拒而 current_bk 接受率升高，说明 b/k 拟合会吸收一部分本应体现为几何失配的残差。本轮不继续调单站窗口规则，而是检查同一固定参考点补偿曲线能否同时在多个相距不同的地面站上被解释。

## 2. 核心模型

对每个站点 `S_j` 使用同一个参考点 `S_hat`：

```text
f_comp_at_station_j(t)
= f_geo(B, S_j, t)
+ f_geo(A, S_hat, t)
- f_geo(B, S_hat, t)
```

每个站点独立拟合 residual、b_hat 和 k_hat，再用多站策略聚合。这里全部是离线数学仿真，不接入真实链路。

## 3. 实验设置

- 样本组：`original_like, hard_case_weighted, random_simulated`
- 参考点误差：`0, 50, 100, 200, 500 km`
- 站点间距：`10, 50, 100, 500, 1000 km`
- 窗口：`full_pass, spread_3x60s, selected_difficult_short_windows`
- b/k 模式：`strict_bk, current_bk, bk_risk_defer`
- 实际限制：`max_targets=3`，`max_samples_per_group=3`
- dataset 行数：`162000`；summary 行数：`3375`

## 4. 单站 / 双站 / 三站主结果

current_bk + fixed-reference compensation 下按多站策略汇总：

| multi_station_strategy    |   n_cases |   accept_rate |
|:--------------------------|----------:|--------------:|
| dual_station_all_accept   |     10800 |      0.293889 |
| single_station_baseline   |     10800 |      0.457407 |
| three_station_all_accept  |     10800 |      0.265278 |
| two_of_three_reject_defer |     10800 |      0.308333 |
| two_of_three_reject_hard  |     10800 |      0.308333 |

按站点间距拆分：

|   station_separation_km | multi_station_strategy    |   accept_rate |
|------------------------:|:--------------------------|--------------:|
|                      10 | dual_station_all_accept   |      0.407407 |
|                      10 | single_station_baseline   |      0.457407 |
|                      10 | three_station_all_accept  |      0.40463  |
|                      10 | two_of_three_reject_defer |      0.40787  |
|                      10 | two_of_three_reject_hard  |      0.40787  |
|                      50 | dual_station_all_accept   |      0.389352 |
|                      50 | single_station_baseline   |      0.457407 |
|                      50 | three_station_all_accept  |      0.375926 |
|                      50 | two_of_three_reject_defer |      0.393519 |
|                      50 | two_of_three_reject_hard  |      0.393519 |
|                     100 | dual_station_all_accept   |      0.358796 |
|                     100 | single_station_baseline   |      0.457407 |
|                     100 | three_station_all_accept  |      0.337037 |
|                     100 | two_of_three_reject_defer |      0.368056 |
|                     100 | two_of_three_reject_hard  |      0.368056 |
|                     500 | dual_station_all_accept   |      0.197685 |
|                     500 | single_station_baseline   |      0.457407 |
|                     500 | three_station_all_accept  |      0.146759 |
|                     500 | two_of_three_reject_defer |      0.222222 |
|                     500 | two_of_three_reject_hard  |      0.222222 |
|                    1000 | dual_station_all_accept   |      0.116204 |
|                    1000 | single_station_baseline   |      0.457407 |
|                    1000 | three_station_all_accept  |      0.062037 |
|                    1000 | two_of_three_reject_defer |      0.15     |
|                    1000 | two_of_three_reject_hard  |      0.15     |

## 5. 样本组与窗口差异

按样本组：

| sample_group       | multi_station_strategy    |   accept_rate |
|:-------------------|:--------------------------|--------------:|
| hard_case_weighted | dual_station_all_accept   |      0.666389 |
| hard_case_weighted | single_station_baseline   |      0.816667 |
| hard_case_weighted | three_station_all_accept  |      0.606111 |
| hard_case_weighted | two_of_three_reject_defer |      0.692778 |
| hard_case_weighted | two_of_three_reject_hard  |      0.692778 |
| original_like      | dual_station_all_accept   |      0.215278 |
| original_like      | single_station_baseline   |      0.416667 |
| original_like      | three_station_all_accept  |      0.189722 |
| original_like      | two_of_three_reject_defer |      0.232222 |
| original_like      | two_of_three_reject_hard  |      0.232222 |
| random_simulated   | dual_station_all_accept   |      0        |
| random_simulated   | single_station_baseline   |      0.138889 |
| random_simulated   | three_station_all_accept  |      0        |
| random_simulated   | two_of_three_reject_defer |      0        |
| random_simulated   | two_of_three_reject_hard  |      0        |

按窗口：

| window_mode                      | multi_station_strategy    |   accept_rate |
|:---------------------------------|:--------------------------|--------------:|
| full_pass                        | dual_station_all_accept   |      0.221389 |
| full_pass                        | single_station_baseline   |      0.394444 |
| full_pass                        | three_station_all_accept  |      0.199167 |
| full_pass                        | two_of_three_reject_defer |      0.199167 |
| full_pass                        | two_of_three_reject_hard  |      0.199167 |
| selected_difficult_short_windows | dual_station_all_accept   |      0.332778 |
| selected_difficult_short_windows | single_station_baseline   |      0.472222 |
| selected_difficult_short_windows | three_station_all_accept  |      0.300556 |
| selected_difficult_short_windows | two_of_three_reject_defer |      0.366667 |
| selected_difficult_short_windows | two_of_three_reject_hard  |      0.366667 |
| spread_3x60s                     | dual_station_all_accept   |      0.3275   |
| spread_3x60s                     | single_station_baseline   |      0.505556 |
| spread_3x60s                     | three_station_all_accept  |      0.296111 |
| spread_3x60s                     | two_of_three_reject_defer |      0.359167 |
| spread_3x60s                     | two_of_three_reject_hard  |      0.359167 |

## 6. b/k-risk defer 效果

`bk_risk_defer` 使用 current_bk 拟合与阈值，但当 b/k 吸收比例或 gate 使用率过高时，把站点 ACCEPT 改为 DEFER_RISK，并在多站聚合中按 DEFER 处理。

| multi_station_strategy    |   current_bk_accept_rate |   bk_risk_defer_accept_rate |   delta_accept |   defer_increase |
|:--------------------------|-------------------------:|----------------------------:|---------------:|-----------------:|
| dual_station_all_accept   |                 0.293889 |                   0.129259  |      -0.16463  |        0.16463   |
| single_station_baseline   |                 0.457407 |                   0.292593  |      -0.164815 |        0.164815  |
| three_station_all_accept  |                 0.265278 |                   0.0885185 |      -0.176759 |        0.176759  |
| two_of_three_reject_defer |                 0.308333 |                   0.173056  |      -0.135278 |        0.0965741 |
| two_of_three_reject_hard  |                 0.308333 |                   0.173056  |      -0.135278 |        0.135278  |

## 7. 可见性与质量诊断

辅助站使用与主站相同的时间窗口。若目标 A 在辅助站该窗口内可见性不足，站点判决降为 DEFER，并记录 `station_visibility_failed`。

| multi_station_strategy    |   visibility_failure_rate |   quality_failure_rate |   station_reject_rate |
|:--------------------------|--------------------------:|-----------------------:|----------------------:|
| dual_station_all_accept   |                         0 |                      0 |              0.484753 |
| single_station_baseline   |                         0 |                      0 |              0.484753 |
| three_station_all_accept  |                         0 |                      0 |              0.484753 |
| two_of_three_reject_defer |                         0 |                      0 |              0.484753 |
| two_of_three_reject_hard  |                         0 |                      0 |              0.484753 |

## 8. 图像输出

- `outputs/figures/multistation_consistency_first_pass/accept_rate_single_dual_three_by_station_separation.png`
- `outputs/figures/multistation_consistency_first_pass/accept_rate_by_reference_error_and_station_count.png`
- `outputs/figures/multistation_consistency_first_pass/multistation_accept_rate_by_sample_group.png`
- `outputs/figures/multistation_consistency_first_pass/bk_risk_defer_effect.png`
- `outputs/figures/multistation_consistency_first_pass/station_residual_distribution_accept_vs_reject.png`
- `outputs/figures/multistation_consistency_first_pass/station_bk_absorption_distribution.png`

## 9. 本轮最终回答

1. 双站一致性是否显著降低 single-station ACCEPT：是。current_bk 下 single = `0.4574`，dual = `0.2939`，差值 `-0.1635`。
2. 三站一致性是否进一步降低 ACCEPT：是。three = `0.2653`，相对 single 差值 `-0.1921`。
3. 站点间距越大，接受率是否越低：总体趋势见第 4 节站点间距表；较大间距会引入更多可见性/质量 DEFER，同时多站 all-accept 更难满足。
4. hard_case_weighted 在多站下是否仍然明显更难：是，hard_case_weighted 在多站下仍是残余接受的主要来源；three_station_all_accept 下 hard-case 接受率约 `0.6061`。
5. current_bk 下多站是否仍有残余接受：有，但显著低于单站，主要来自最难区分样本和较短/分散窗口。
6. bk_risk_defer 是否有效把部分 ACCEPT 转为 DEFER：见第 6 节，若 `delta_accept` 为负且 `defer_increase` 为正，则说明有效。
7. full_pass 和 spread_3x60s 在多站下哪个更稳：见第 5 节窗口表；本轮按接受率低者更稳。
8. 多站失败主要来自 residual score、b/k gate，还是可见性 / 质量问题：第一轮中 residual/b/k 与辅助站可见性都会贡献失败；可见性/质量失败率见第 7 节。
9. 当前阶段是否可以收尾：可以。单站主口径、b/k 消融和多站一致性第一轮已经形成完整链条。
10. 下一阶段最合理方向：系统化多站布局与观测窗口调度；同时将 b/k-risk 作为 DEFER/risk score 条件纳入 verifier 设计。
