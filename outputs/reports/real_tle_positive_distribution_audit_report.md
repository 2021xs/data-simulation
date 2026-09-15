# 真实轨道非中心误接受分布与独立性审计

## 1. 目的与边界

本轮只读取全量机制表，未进行轨道传播、攻击重放、验证器修改或模型训练。主筛选为 `sample_source=real_tle_candidate`、`bk_mode=current_bk`、`distance_km>0`、`formal_final_decision=ACCEPT`；局部范围显式检查为 `distance_km<=10`。

## 2. 两种统计视图与主键

- 原始条件实例视图：22 条正式 ACCEPT 标签行。
- 物理条件去重视图：19 个物理键，移除 3 条双标签 ACCEPT 重复。
- 物理键：`target_sat_id + attack_sat_id + service_area_id + service_area_segment_index + distance + direction + bk_mode`。行表没有 evaluation start/end，也没有 observation realization / residual seed。

同一 `pair_id` 始终映射唯一 target/attack，因此本轮另建可读的 `physical_pair_id=target->attack`，但不把样本组写入物理 pair。

## 3. 数据正确性与冲突

| check                               | passed   | observed                                                                                                                                                                                                                                                                            | tolerance                  | notes                                  |
|:------------------------------------|:---------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------------------------|:---------------------------------------|
| 输入全量行表存在且字段完整          | True     | 0                                                                                                                                                                                                                                                                                   | 0 missing                  |                                        |
| 主筛选条件正确                      | True     | 22                                                                                                                                                                                                                                                                                  | real/current/d>0/ACCEPT    |                                        |
| raw positive与前轮一致              | True     | current=22, prior=22.0                                                                                                                                                                                                                                                              | equal or prior unavailable |                                        |
| 物理去重主键唯一                    | True     | 0                                                                                                                                                                                                                                                                                   | 0 duplicate                |                                        |
| 同一物理条件不存在ACCEPT/REJECT冲突 | False    | 16                                                                                                                                                                                                                                                                                  | 0                          | 冲突已完整写入 duplicate_conflicts.csv |
| 所有正例均为真实轨道                | True     | ['real_tle_candidate']                                                                                                                                                                                                                                                              | real_tle_candidate         |                                        |
| 所有正例均为current_bk              | True     | ['current_bk']                                                                                                                                                                                                                                                                      | current_bk                 |                                        |
| 所有正例distance>0                  | True     | 2.5                                                                                                                                                                                                                                                                                 | >0                         |                                        |
| 所有正例落在局部范围                | True     | 0                                                                                                                                                                                                                                                                                   | 0 rows above 10 km         |                                        |
| 实体汇总可回加物理正例              | True     | {"target": 19, "pair": 19, "area": 19, "distance": 19, "direction_raw": 19}                                                                                                                                                                                                         | 19                         |                                        |
| positive_share总和为1               | True     | {"target": 1.0, "pair": 1.0, "area": 1.0, "distance": 1.0, "direction_raw": 1.0, "group_fractional": 1.0}                                                                                                                                                                           | 1±1e-9                     |                                        |
| HHI与有效实体数正确                 | True     | {"target_positive_hhi": 0.25207756232686973, "pair_positive_hhi": 0.06925207756232686, "service_area_positive_hhi": 0.2299168975069252, "effective_target_count": 3.967032967032968, "effective_pair_count": 14.440000000000001, "effective_service_area_count": 4.349397590361446} | HHI∈(0,1], HHI*N_eff=1     |                                        |
| ordinary/boundary重复准确识别       | True     | physical=3, raw=3                                                                                                                                                                                                                                                                   | equal                      |                                        |
| 所有输出主键唯一                    | True     | {"physical": 0, "target": 0, "pair": 0, "area": 0, "distance": 0, "direction": 0, "group": 0, "conflicts": 0, "target_pair": 0, "pair_area": 0, "pair_distance": 0, "pair_direction": 0}                                                                                            | all zero                   |                                        |
| 每条raw正例可回溯唯一正式记录       | True     | 0                                                                                                                                                                                                                                                                                   | 0 duplicate raw keys       |                                        |
| pair_id唯一表示物理卫星对           | True     | {'target_sat_id': 1, 'attack_sat_id': 1}                                                                                                                                                                                                                                            | max unique target/attack=1 |                                        |

前轮正例计数来源：grouped_validation real_all/local/M0 positive_n。发现 16 个物理条件在 ordinary/boundary 标签行之间同时出现 ACCEPT 与 REJECT；共有 32 条冲突标签明细。这表明这些标签行可能包含未保存的不同随机残差 realization，不能在缺少 realization 主键时既视为相同物理条件、又视为独立观测。

由于正确性审计并非全部通过，后续集中程度仍作为描述性结果输出，但扩样启发式结论暂缓。

## 4. 目标卫星分布

|   target_sat_id |   positive_raw_rows |   positive_physical_conditions |   positive_physical_pair_count |   positive_service_area_count |   positive_share |   all_real_conditions |   target_condition_accept_rate |
|----------------:|--------------------:|-------------------------------:|-------------------------------:|------------------------------:|-----------------:|----------------------:|-------------------------------:|
|           44714 |                   9 |                              7 |                              5 |                             1 |        0.368421  |                  1120 |                    0.00625     |
|           65410 |                   4 |                              4 |                              3 |                             1 |        0.210526  |                  1400 |                    0.00285714  |
|           65686 |                   5 |                              4 |                              4 |                             2 |        0.210526  |                  1400 |                    0.00285714  |
|           65409 |                   3 |                              3 |                              3 |                             1 |        0.157895  |                  1400 |                    0.00214286  |
|           65421 |                   1 |                              1 |                              1 |                             1 |        0.0526316 |                  1400 |                    0.000714286 |

## 5. 物理卫星对分布与集中程度

Top pair：

| physical_pair_id   |   positive_raw_rows |   positive_physical_conditions |   positive_service_area_count |   positive_direction_count |   positive_share |   pair_condition_accept_rate |   ordinary_positive_count |   boundary_positive_count |
|:-------------------|--------------------:|-------------------------------:|------------------------------:|---------------------------:|-----------------:|-----------------------------:|--------------------------:|--------------------------:|
| 44714->65410       |                   2 |                              2 |                             1 |                          2 |        0.105263  |                   0.00892857 |                         1 |                         1 |
| 44714->65421       |                   2 |                              2 |                             1 |                          2 |        0.105263  |                   0.00892857 |                         1 |                         1 |
| 65410->65686       |                   2 |                              2 |                             1 |                          2 |        0.105263  |                   0.00714286 |                         1 |                         1 |
| 44714->47749       |                   2 |                              1 |                             1 |                          1 |        0.0526316 |                   0.00446429 |                         1 |                         1 |
| 44714->65409       |                   2 |                              1 |                             1 |                          1 |        0.0526316 |                   0.00446429 |                         1 |                         1 |

Top1/2/3 pair 占比分别为 10.53%、21.05%、31.58%。pair HHI=0.0693，有效 pair 数=14.44。HHI 越接近 1 表示越集中；有效实体数 `1/HHI` 表示当前分布约等价于多少个均匀贡献实体。目标 HHI=0.2521（有效目标 3.97），服务区 HHI=0.2299（有效服务区 4.35）。

## 6. 服务区、距离、方向与样本组

服务区：

| target_service_area_id              | service_area_id               |   target_sat_id |   positive_physical_conditions |   positive_physical_pair_count |   positive_distance_count |   positive_direction_count |   positive_share |
|:------------------------------------|:------------------------------|----------------:|-------------------------------:|-------------------------------:|--------------------------:|---------------------------:|-----------------:|
| 44714|44714_20260310T023437Z_area_0 | 44714_20260310T023437Z_area_0 |           44714 |                              7 |                              5 |                         1 |                          2 |        0.368421  |
| 65410|65410_20260310T064012Z_area_0 | 65410_20260310T064012Z_area_0 |           65410 |                              4 |                              3 |                         1 |                          2 |        0.210526  |
| 65409|65409_20260310T064053Z_area_0 | 65409_20260310T064053Z_area_0 |           65409 |                              3 |                              3 |                         1 |                          1 |        0.157895  |
| 65686|65686_20260310T131505Z_area_0 | 65686_20260310T131505Z_area_0 |           65686 |                              2 |                              2 |                         1 |                          2 |        0.105263  |
| 65686|65686_20260310T131505Z_area_3 | 65686_20260310T131505Z_area_3 |           65686 |                              2 |                              2 |                         1 |                          1 |        0.105263  |
| 65421|65421_20260310T064222Z_area_0 | 65421_20260310T064222Z_area_0 |           65421 |                              1 |                              1 |                         1 |                          1 |        0.0526316 |

距离：

|   distance_km |   positive_physical_conditions |   positive_physical_pair_count |   positive_target_count |   positive_service_area_count |   positive_share |   all_real_conditions |   distance_condition_accept_rate |
|--------------:|-------------------------------:|-------------------------------:|------------------------:|------------------------------:|-----------------:|----------------------:|---------------------------------:|
|           2.5 |                             19 |                             16 |                       5 |                             6 |                1 |                   960 |                        0.0197917 |
|           5   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |
|          10   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |
|          50   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |
|         100   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |
|         200   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |
|         500   |                              0 |                              0 |                       0 |                             0 |                0 |                   960 |                        0         |

方向原始统计（0°北、90°东、顺时针）为主；轴向合并只作辅助，不能假定相反方向几何等价：

| summary_level         |   direction_deg | axis_group   |   positive_physical_conditions |   positive_physical_pair_count |   positive_target_count |   positive_service_area_count |   positive_share |   all_real_conditions |   direction_condition_accept_rate |
|:----------------------|----------------:|:-------------|-------------------------------:|-------------------------------:|------------------------:|------------------------------:|-----------------:|----------------------:|----------------------------------:|
| raw_direction_primary |               0 | 北—南轴      |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |              45 | 东北—西南轴  |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |              90 | 东—西轴      |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |             135 | 东南—西北轴  |                             10 |                             10 |                       4 |                             4 |         0.526316 |                   840 |                         0.0119048 |
| raw_direction_primary |             180 | 北—南轴      |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |             225 | 东北—西南轴  |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |             270 | 东—西轴      |                              0 |                              0 |                       0 |                             0 |         0        |                   840 |                         0         |
| raw_direction_primary |             315 | 东南—西北轴  |                              9 |                              9 |                       4 |                             5 |         0.473684 |                   840 |                         0.0107143 |
| axis_auxiliary        |             nan | 东—西轴      |                              0 |                              0 |                       0 |                             0 |         0        |                  1680 |                         0         |
| axis_auxiliary        |             nan | 东北—西南轴  |                              0 |                              0 |                       0 |                             0 |         0        |                  1680 |                         0         |
| axis_auxiliary        |             nan | 东南—西北轴  |                             19 |                             19 |                       8 |                             9 |         1        |                  1680 |                         0.0113095 |
| axis_auxiliary        |             nan | 北—南轴      |                              0 |                              0 |                       0 |                             0 |         0        |                  1680 |                         0         |

样本组使用 fractional attribution 计算 share，使一个双组正例条件在两个组各贡献 1/2，share 总和保持 1；`positive_physical_conditions` 仍保留各组内实际去重计数：

| sample_group     |   positive_raw_rows |   positive_physical_conditions |   positive_physical_pair_count |   positive_target_count |   positive_fractional_equivalent |   positive_share |   all_real_conditions |   group_condition_accept_rate |   physical_conditions_positive_in_both_groups |
|:-----------------|--------------------:|-------------------------------:|-------------------------------:|------------------------:|---------------------------------:|-----------------:|----------------------:|------------------------------:|----------------------------------------------:|
| boundary_case    |                  12 |                             12 |                             12 |                       5 |                             10.5 |         0.552632 |                  6720 |                    0.00178571 |                                             3 |
| ordinary_similar |                  10 |                             10 |                             10 |                       4 |                              8.5 |         0.447368 |                  6720 |                    0.0014881  |                                             3 |

## 7. 覆盖矩阵与机制描述

已输出 target×pair、pair×area、pair×distance、pair×direction 四个矩阵。物理正例逐条保存 raw geometry、方向/最弱敏感度、两类吸收、formal b/k 及 gate margin；目标、pair、距离、样本组汇总包含均值、中位数、最小和最大值。没有引入聚类或新预测模型。

## 8. 必须回答的十五个问题

1. 原始真实轨道非中心正例：**22 条**。
2. 标签去重后：**19 个物理正例条件**，移除 3 条双 ACCEPT 重复。
3. 覆盖目标卫星：**5 颗**。
4. 覆盖物理卫星对：**16 个**。
5. 覆盖服务区：**6 个 target-area**。
6. 是否主要集中于一个目标：描述上 44714 占比最高，但 top1 target=36.84%；是否可作独立性结论受标签冲突限制。
7. 是否集中于1～2个 pair：描述上否；top1 pair=10.53%、top2=21.05%。
8. top1/top2/top3 pair：10.53% / 21.05% / 31.58%。
9. 是否全部在2.5 km：**True**。
10. 5 km 或10 km误接受：5 km=0，10 km=0。
11. 是否集中少数方向：只出现在 2 个方向，分布为 {135.0: 10, 315.0: 9}，因此方向覆盖集中。
12. ordinary/boundary 大量物理重复：双 ACCEPT 重复 3 个；更严重的是 16 个相同物理键存在相反判决。
13. 多个独立场景还是少数条件重复：描述上覆盖多个目标/pair，但独立 realization 无法从当前字段证明；不能把19个键直接解释为19个独立观测。
14. 是否足以支持真实轨道机制结论：足以支持“存在这些几何条件与正式误接受关联”的描述，不足以支持正例独立性或发生频率的稳健结论。
15. 是否立即扩充数据集：**暂缓扩样判断：物理条件判决冲突尚未解决**。

## 9. 扩样启发式判断与优先级

本节标准是研究规划启发式，不是统计定理。当前审计失败项使正式扩样建议暂缓。优先事项：

1. 优先补充 observation realization / residual seed 主键，解释 ordinary/boundary 相同几何条件为何出现相反判决
2. 在冲突语义澄清前，不把19个去重条件作为19个独立观测
3. 随后再按目标、独立pair和不同过境决定定向扩样

在 realization 语义修复后，如果仍需扩样，应优先新增独立目标/pair与不同日期过境，而不是增加同一次过境中的距离和方向行密度。

## 10. 图表与输出

生成 8 张图：target_positive_count_and_rate.png, pair_positive_share.png, positive_by_distance.png, positive_by_direction.png, pair_area_heatmap.png, pair_distance_heatmap.png, pair_direction_heatmap.png, positive_mechanism_relationship.png。冲突明细、物理条件表和所有汇总/矩阵均使用独立 `real_tle_positive_audit_*` 文件名，未覆盖旧输出。

## 11. 局限

- 当前只有一个日期/过境族，无法估计跨过境独立性。
- 样本组可能不仅是标签，还隐含不同经验误差 realization；行表缺少 seed/realization ID。
- HHI、top-k 与有效实体数只描述这批正例，不是总体攻击成功概率或显著性检验。
