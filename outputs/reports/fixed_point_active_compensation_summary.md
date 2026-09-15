# Fixed-point active compensation sensitivity summary

生成时间：2026-06-12 13:56:19

## 1. 实验目的

本轮测试固定参考点主动补偿攻击对位置误差 `e = dist(S_hat, S)` 的敏感性。实验不做三颗参考卫星定位，只扫描抽象位置误差，并优先使用上一轮 window-aware hard cases 中的高度极接近样本和倾角极接近样本。

## 2. 攻击模型与符号约定

本脚本沿用项目已有 active compensation 脚本中的单站补偿符号：

`f_attack(t) = f_geo(B, S, t) + [f_geo(A, S_hat, t) - f_geo(B, S_hat, t)]`

因此 `e=0` 且 `S_hat=S` 时，攻击几何项退化为 `f_geo(A, S, t)`，用于表示单站理想主动补偿上界。验证器仍只使用真实站 S 上 claimed target A 的理论曲线，不使用 B 的轨道参数作为判决输入。

用户提示中的差分式若直接套入当前 `f_geo` 观测符号，会在 `e=0` 时变成 `2 f_geo(B,S)-f_geo(A,S)`，不对应“补偿到 A”的单站理想情形；所以本轮报告按上述项目符号解释。

## 3. 实验规模

- 输出样本行数：`9576`
- summary 行数：`810`
- target 数：`4`
- attack hard-case 规格数：`10`
- e values：`0, 0.5, 1, 2, 5, 10`
- window patterns：`full_pass, single_30s_best, single_60s_best, spread_3x60s, spread_6x30s, hardest_previous`
- strategies：`single_window, proposed_v1, candidate_v1_1, full_pass`
- residual mode：`empirical`
- benign control rows：`912`

## 4. strategy / e 主结果

下表从逐样本 dataset 直接加权统计：

| strategy_type   |   e_km |   n |   accept_rate |   defer_rate |   reject_rate |
|:----------------|-------:|----:|--------------:|-------------:|--------------:|
| candidate_v1_1  |    0   | 456 |      0.355263 |    0.589912  |    0.0548246  |
| candidate_v1_1  |    0.5 | 456 |      0.423246 |    0.561404  |    0.0153509  |
| candidate_v1_1  |    1   | 456 |      0.401316 |    0.554825  |    0.0438596  |
| candidate_v1_1  |    2   | 456 |      0.421053 |    0.535088  |    0.0438596  |
| candidate_v1_1  |    5   | 456 |      0.462719 |    0.513158  |    0.0241228  |
| candidate_v1_1  |   10   | 456 |      0.427632 |    0.550439  |    0.0219298  |
| full_pass       |    0   |  76 |      0.855263 |    0.0657895 |    0.0789474  |
| full_pass       |    0.5 |  76 |      0.934211 |    0.0263158 |    0.0394737  |
| full_pass       |    1   |  76 |      0.881579 |    0.0131579 |    0.105263   |
| full_pass       |    2   |  76 |      0.934211 |    0.0131579 |    0.0526316  |
| full_pass       |    5   |  76 |      0.907895 |    0.0526316 |    0.0394737  |
| full_pass       |   10   |  76 |      0.921053 |    0.0394737 |    0.0394737  |
| proposed_v1     |    0   | 456 |      0.427632 |    0.517544  |    0.0548246  |
| proposed_v1     |    0.5 | 456 |      0.434211 |    0.550439  |    0.0153509  |
| proposed_v1     |    1   | 456 |      0.414474 |    0.541667  |    0.0438596  |
| proposed_v1     |    2   | 456 |      0.438596 |    0.517544  |    0.0438596  |
| proposed_v1     |    5   | 456 |      0.47807  |    0.497807  |    0.0241228  |
| proposed_v1     |   10   | 456 |      0.442982 |    0.535088  |    0.0219298  |
| single_window   |    0   | 456 |      0.912281 |    0.0657895 |    0.0219298  |
| single_window   |    0.5 | 456 |      0.927632 |    0.0657895 |    0.00657895 |
| single_window   |    1   | 456 |      0.929825 |    0.0482456 |    0.0219298  |
| single_window   |    2   | 456 |      0.914474 |    0.0614035 |    0.0241228  |
| single_window   |    5   | 456 |      0.936404 |    0.0526316 |    0.0109649  |
| single_window   |   10   | 456 |      0.923246 |    0.0592105 |    0.0175439  |

## 5. 攻击类型与窗口模式

按攻击类型聚合：

| strategy_type   | attack_type                |    n |   accept_rate |   defer_rate |   reject_rate |
|:----------------|:---------------------------|-----:|--------------:|-------------:|--------------:|
| candidate_v1_1  | inclination_offset         |  864 |      0.393519 |    0.584491  |     0.0219907 |
| candidate_v1_1  | same_plane_altitude_offset | 1872 |      0.425214 |    0.535256  |     0.0395299 |
| full_pass       | inclination_offset         |  144 |      0.923611 |    0.0416667 |     0.0347222 |
| full_pass       | same_plane_altitude_offset |  312 |      0.897436 |    0.0320513 |     0.0705128 |
| proposed_v1     | inclination_offset         |  864 |      0.431713 |    0.546296  |     0.0219907 |
| proposed_v1     | same_plane_altitude_offset | 1872 |      0.442842 |    0.517628  |     0.0395299 |
| single_window   | inclination_offset         |  864 |      0.918981 |    0.068287  |     0.0127315 |
| single_window   | same_plane_altitude_offset | 1872 |      0.926282 |    0.0544872 |     0.0192308 |

按窗口模式聚合：

| strategy_type   | window_pattern   |   n |   accept_rate |   defer_rate |   reject_rate |
|:----------------|:-----------------|----:|--------------:|-------------:|--------------:|
| candidate_v1_1  | full_pass        | 456 |      0.905702 |   0.0350877  |     0.0592105 |
| candidate_v1_1  | hardest_previous | 456 |      0.445175 |   0.530702   |     0.0241228 |
| candidate_v1_1  | single_30s_best  | 456 |      0        |   0.97807    |     0.0219298 |
| candidate_v1_1  | single_60s_best  | 456 |      0        |   0.980263   |     0.0197368 |
| candidate_v1_1  | spread_3x60s     | 456 |      0.666667 |   0.300439   |     0.0328947 |
| candidate_v1_1  | spread_6x30s     | 456 |      0.473684 |   0.480263   |     0.0460526 |
| full_pass       | full_pass        | 456 |      0.905702 |   0.0350877  |     0.0592105 |
| proposed_v1     | full_pass        | 456 |      0.905702 |   0.0350877  |     0.0592105 |
| proposed_v1     | hardest_previous | 456 |      0.589912 |   0.385965   |     0.0241228 |
| proposed_v1     | single_30s_best  | 456 |      0        |   0.97807    |     0.0219298 |
| proposed_v1     | single_60s_best  | 456 |      0        |   0.980263   |     0.0197368 |
| proposed_v1     | spread_3x60s     | 456 |      0.666667 |   0.300439   |     0.0328947 |
| proposed_v1     | spread_6x30s     | 456 |      0.473684 |   0.480263   |     0.0460526 |
| single_window   | full_pass        | 456 |      0.905702 |   0.0350877  |     0.0592105 |
| single_window   | hardest_previous | 456 |      0.991228 |   0.00877193 |     0         |
| single_window   | single_30s_best  | 456 |      0.813596 |   0.164474   |     0.0219298 |
| single_window   | single_60s_best  | 456 |      0.846491 |   0.131579   |     0.0219298 |
| single_window   | spread_3x60s     | 456 |      0.991228 |   0.00877193 |     0         |
| single_window   | spread_6x30s     | 456 |      0.995614 |   0.00438596 |     0         |

proposed v1 下 ACCEPT hard samples 主要分布：

| attack_type                |   attack_param_value | window_pattern   |   accept_count |
|:---------------------------|---------------------:|:-----------------|---------------:|
| same_plane_altitude_offset |                -1    | full_pass        |            192 |
| same_plane_altitude_offset |                -1    | spread_3x60s     |            147 |
| same_plane_altitude_offset |                -1    | hardest_previous |            125 |
| same_plane_altitude_offset |                -1    | spread_6x30s     |             99 |
| same_plane_altitude_offset |                -2    | full_pass        |             88 |
| same_plane_altitude_offset |                -2    | spread_3x60s     |             66 |
| same_plane_altitude_offset |                -2    | hardest_previous |             63 |
| same_plane_altitude_offset |                -2    | spread_6x30s     |             49 |
| inclination_offset         |                -0.1  | full_pass        |             44 |
| inclination_offset         |                 0.2  | full_pass        |             35 |
| inclination_offset         |                 0.05 | full_pass        |             31 |
| inclination_offset         |                -0.1  | spread_3x60s     |             31 |

## 6. benign 对照

| strategy_type   |   n |   accept_rate |   defer_rate |   reject_rate |
|:----------------|----:|--------------:|-------------:|--------------:|
| proposed_v1     | 456 |      0.432018 |    0.528509  |     0.0394737 |
| single_window   | 456 |      0.910088 |    0.0767544 |     0.0131579 |

## 7. 阶段性回答

1. `e` 多小主动补偿才能突破验证器：在本 hard-case 加权集合中，`e=0` 已明显突破 single-window 和 full-pass；`e=0.5-10 km` 仍保持较高接受率，说明 10 km 以内的位置误差并未自动消除单站固定点主动补偿压力。
2. v1 与 v1.1 差异：proposed v1 总体 attack ACCEPT 约为 `0.4393`，candidate v1.1 约为 `0.4152`。v1.1 主要把 best-attack 时间分散不足的 ACCEPT 转为 DEFER，收益存在但有限。
3. full-pass 是否最稳：在被动轨道相似攻击中 full-pass 是强证据；但在本轮固定点主动补偿压力下，full-pass ACCEPT 约为 `0.9057`，不应表述为最稳防线。
4. single-window baseline：single-window ACCEPT 约为 `0.9240`，仍是最脆弱对照。
5. hard samples：proposed v1 的 ACCEPT 主要来自 altitude `-1/-2 km` 与部分 small inclination，且集中在 full_pass、spread_3x60s、hardest_previous 和 spread_6x30s。
6. 下一步：本轮不证明真实定位可达到这些 e，只说明若攻击方能把固定参考点误差压到 0-10 km 区间，单站 verifier 会承受强压力。下一轮应评估 partial-observation 下 location-aware active compensation，并检查三参考模拟定位是否可能达到本轮高风险 e 区间。

## 8. 输出图

- `outputs/figures/fixed_point_active_compensation/fixed_point_attack_accept_vs_e_heatmap.png`
- `outputs/figures/fixed_point_active_compensation/fixed_point_strategy_window_comparison.png`
- `outputs/figures/fixed_point_active_compensation/fixed_point_attack_type_distribution.png`
