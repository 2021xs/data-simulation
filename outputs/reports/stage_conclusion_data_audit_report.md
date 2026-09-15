# Stage Conclusion Data Audit Report

生成时间：2026-07-02 18:24

本报告只审计上一轮 `stage_conclusion_stabilization` 输出的数据来源和统计口径。审计过程未接入真实链路，未访问真实卫星通信系统，未发射或干扰任何信号。

## 1. Files checked

上一轮关键文件的时间和大小如下。`CreationTime` 是首次创建时间，`LastWriteTime` 是最后写入时间；dataset、summary、report 和 figures 的 `LastWriteTime` 均在 2026-07-02 18:07 左右，说明正式命令带 `--overwrite` 后重新写入过输出。

| path | size_bytes | last_write_time | creation_time |
|:--|--:|:--|:--|
| `scripts/run_stage_conclusion_stabilization.py` | 56099 | 2026-07-02 18:04:49 | 2026-07-02 18:01:37 |
| `outputs/datasets/stage_conclusion_stabilization_dataset.csv` | 117914190 | 2026-07-02 18:07:10 | 2026-07-02 18:02:03 |
| `outputs/metrics/stage_conclusion_main_summary.csv` | 739800 | 2026-07-02 18:07:10 | 2026-07-02 18:02:03 |
| `outputs/reports/stage_conclusion_stabilization_report.md` | 13174 | 2026-07-02 18:07:19 | 2026-07-02 18:02:04 |

图像目录 `outputs/figures/stage_conclusion_stabilization/`：

| file | size_bytes | last_write_time |
|:--|--:|:--|
| `stage_pipeline_false_accept_rate.png` | 107111 | 2026-07-02 18:07:11 |
| `false_accept_rate_by_reference_error_and_sample_group.png` | 106385 | 2026-07-02 18:07:12 |
| `bk_ablation_false_accept_rate.png` | 73215 | 2026-07-02 18:07:13 |
| `multistation_false_accept_rate_by_separation.png` | 111316 | 2026-07-02 18:07:16 |
| `bk_risk_defer_accept_to_defer.png` | 101527 | 2026-07-02 18:07:17 |

## 2. Script execution path

脚本执行路径可以从代码直接确认：

- `parse_args` 定义 4 个输入：`--window-aware-dataset`、`--fixed-reference-dataset`、`--single-station-bk-dataset`、`--multistation-dataset`。
- `check_inputs` 只检查这 4 个输入是否存在。注意：`fixed_reference_compensation_extended_dataset.csv` 只被检查存在，未进入 `build_dataset` 合并。
- `normalize_window_aware` 使用 `pd.read_csv(args.window_aware_dataset)` 读取旧 window-aware CSV，筛选 `threshold_type=p95`、`is_attack=True`、`max_targets`、`max_samples_per_group` 后重命名字段。
- `normalize_single_station` 使用 `pd.read_csv(source)` 读取旧 single-station b/k CSV，筛选 sample_group、reference_error、window_mode、bk_mode、`compensation_mode=fixed_reference_compensation` 和若干 strategy 后重命名字段。该函数被调用两次，分别标记为 `fixed_reference_compensation` 和 `bk_ablation`。
- `normalize_multistation` 使用 `pd.read_csv(args.multistation_dataset)` 读取旧 multistation CSV，筛选 sample_group、reference_error、window_mode、bk_mode、station_separation 和 station_strategy 后重命名字段。
- `build_dataset` 只执行 `pd.concat(parts, ignore_index=True)`，把三类来源规范化后拼接成 stage dataset。
- `summarize_group` 和 `build_summaries` 使用 groupby 计算误接受率、DEFER、REJECT 和 gate pass rate。
- `write_outputs` 使用 `to_csv` 写出 stage dataset 和 summary。
- `--overwrite` 的作用是：如果输出已存在且没有 `--overwrite`，`check_outputs` 直接停止；带 `--overwrite` 时允许 `to_csv` 覆盖写出。
- 脚本没有导入 `skyfield`、SGP4、`orbit_builder` 或既有 verifier 模块，也没有调用 `geo_curve`、`build_legitimate_observation`、`build_attack_observation`、`verify_claimed_identity` 或固定参考点补偿生成函数。
- `case_id` / `row_id` 来自旧 CSV：window-aware 使用 `group_id` 或 `observation_sequence_id` 与源 DataFrame index；single-station/multistation 使用源 `case_id`、`row_id`。
- stage dataset 保留了 `source_dataset` 字段，但没有 `source_file` / `input_source` 字段。

## 3. Input datasets and provenance

输入文件原始规模与是否进入 stage dataset：

| input_file | input_rows | input_columns | used_in_stage_dataset |
|:--|--:|--:|:--|
| `outputs/datasets/window_aware_evidence_accumulation_dataset.csv` | 285240 | 45 | True |
| `outputs/datasets/fixed_reference_compensation_extended_dataset.csv` | 24624 | 37 | False |
| `outputs/datasets/single_station_bk_gate_ablation_dataset.csv` | 15120 | 50 | True |
| `outputs/datasets/multistation_consistency_first_pass_dataset.csv` | 162000 | 85 | True |

按 `source_dataset x experiment_block` 拆分：

| source_dataset | bk_ablation | fixed_reference_compensation | multistation_consistency | window_accumulation |
|:--|--:|--:|--:|--:|
| `outputs/datasets/multistation_consistency_first_pass_dataset.csv` | 0 | 0 | 129600 | 0 |
| `outputs/datasets/single_station_bk_gate_ablation_dataset.csv` | 4320 | 4320 | 0 | 0 |
| `outputs/datasets/window_aware_evidence_accumulation_dataset.csv` | 0 | 0 | 0 | 10356 |

结论：148596 行 stage dataset 是新的样本级固化 CSV，但其行内容来自旧离线结果的读取、筛选、字段归一化、重复标记和汇总口径重算；不是重新生成的原始物理仿真样本。

## 4. Whether this round generated new simulation data

结论：**B. 旧仿真结果的统一复算 / 重新汇总**。

判断依据：

- 有新的输出 dataset：`outputs/datasets/stage_conclusion_stabilization_dataset.csv`，形状为 `(148596, 47)`。
- 但脚本没有重新做轨道传播、多普勒曲线生成、固定参考点补偿生成或 verifier 判决；它读取既有 CSV 后做字段规范化、concat、groupby、summary 和绘图。
- `fixed_reference_compensation_extended_dataset.csv` 没有被合并进 stage dataset，只作为存在性检查输入。固定参考点和 b/k 相关 stage 行实际来自 `single_station_bk_gate_ablation_dataset.csv`。
- 因此不能说“重新完成全量原始物理仿真”；可以说“生成了一个新的样本级固化 dataset，并对既有离线仿真结果做了统一统计口径复算”。

## 5. Row-count breakdown

stage dataset shape：`(148596, 47)`。

必需字段缺失：`[]`。

审计别名字段缺失：`source_file`、`input_source`。缺少这两个字段不会阻断主要来源追踪，因为存在 `source_dataset`，但外部脚本若按 `source_file` 自动审计会失败。

### experiment_block

| experiment_block | row_count |
|:--|--:|
| `multistation_consistency` | 129600 |
| `window_accumulation` | 10356 |
| `fixed_reference_compensation` | 4320 |
| `bk_ablation` | 4320 |

### source_dataset

| source_dataset | row_count |
|:--|--:|
| `outputs/datasets/multistation_consistency_first_pass_dataset.csv` | 129600 |
| `outputs/datasets/window_aware_evidence_accumulation_dataset.csv` | 10356 |
| `outputs/datasets/single_station_bk_gate_ablation_dataset.csv` | 8640 |

### sample_group

| sample_group | row_count |
|:--|--:|
| `ordinary_similar` | 46080 |
| `boundary_case` | 46080 |
| `random_simulated` | 46080 |
| `window_attack_mixed` | 10356 |

### reference_error_km

| reference_error_km | row_count |
|--:|--:|
| 0 | 37716 |
| 50 | 27360 |
| 100 | 27360 |
| 200 | 27360 |
| 500 | 27360 |
| 1000 | 1440 |

### window_mode

| window_mode | row_count |
|:--|--:|
| `spread_3x60s` | 49896 |
| `selected_difficult_short_windows` | 49884 |
| `full_pass` | 45252 |
| `spread_6x30s` | 3240 |
| `single_window` | 324 |

### bk_mode

| bk_mode | row_count |
|:--|--:|
| `current_bk` | 55716 |
| `strict_bk` | 45360 |
| `bk_risk_defer` | 43200 |
| `no_bk` | 2160 |
| `loose_bk` | 2160 |

### station_strategy

| station_strategy | row_count |
|:--|--:|
| `single_station_baseline` | 51396 |
| `dual_station_all_accept` | 32400 |
| `three_station_all_accept` | 32400 |
| `two_of_three_reject_defer` | 32400 |

### station_count

| station_count | row_count |
|--:|--:|
| 3 | 64800 |
| 1 | 51396 |
| 2 | 32400 |

### station_separation_km

| station_separation_km | row_count |
|--:|--:|
| 10 | 25920 |
| 50 | 25920 |
| 500 | 25920 |
| 100 | 25920 |
| 1000 | 25920 |
| 0 | 18996 |

### compensation_mode

| compensation_mode | row_count |
|:--|--:|
| `fixed_reference_compensation` | 138240 |
| `none` | 10356 |

### final_decision

| final_decision | row_count |
|:--|--:|
| `REJECT` | 67570 |
| `DEFER` | 47216 |
| `ACCEPT` | 33810 |

### case_id / row_id audit

| scope | duplicate_rows | unique_rows |
|:--|--:|--:|
| `experiment_block + source_dataset + case_id + row_id` | 0 | 148596 |
| `source_dataset + case_id + row_id` | 4320 | 144276 |
| `case_id + row_id` | 4320 | 144276 |

解释：在 `experiment_block + source_dataset + case_id + row_id` 口径下没有重复；去掉 `experiment_block` 后有 4320 行重复，原因是同一批 single-station b/k 旧行被同时作为 `fixed_reference_compensation` 和 `bk_ablation` 两个 experiment_block 进入 stage dataset。不存在新生成的物理 case_id；stage 层只是复用旧 case_id/row_id 或源 DataFrame index。

## 6. Key metric provenance

| metric_name | value | ACCEPT numerator | denominator cases | source CSV | filter condition | sample groups | reference errors | window modes | station separations |
|:--|--:|--:|--:|:--|:--|:--|:--|:--|:--|
| `single_window 非目标样本误接受率` | 0.1804750869 | 623 | 3452 | `window_aware_evidence_accumulation_dataset.csv` | `experiment_block=window_accumulation; strategy_type=single_window; threshold_type=p95; is_attack=True` | 1, `window_attack_mixed` | 1, `0` | 5, `full_pass, selected_difficult_short_windows, single_window, spread_3x60s, spread_6x30s` | 1, `0` |
| `window-aware accumulation` | 0.0031865585 | 11 | 3452 | `window_aware_evidence_accumulation_dataset.csv` | `experiment_block=window_accumulation; strategy_type=window_aware_accumulation; threshold_type=p95; is_attack=True` | 1, `window_attack_mixed` | 1, `0` | 5, same as above | 1, `0` |
| `no_bk` | 0.0000000000 | 0 | 1080 | `single_station_bk_gate_ablation_dataset.csv` | `experiment_block=bk_ablation; bk_mode=no_bk; compensation_mode=fixed_reference_compensation; station_strategy=single_station_baseline` | 3 | 6, `0,50,100,200,500,1000` | 3, `full_pass, spread_3x60s, selected_difficult_short_windows` | 1, `0` |
| `current_bk` | 0.4083333333 | 441 | 1080 | `single_station_bk_gate_ablation_dataset.csv` | `experiment_block=bk_ablation; bk_mode=current_bk; compensation_mode=fixed_reference_compensation; station_strategy=single_station_baseline` | 3 | 6, `0,50,100,200,500,1000` | 3 | 1, `0` |
| `单站 current_bk` | 0.4574074074 | 4940 | 10800 | `multistation_consistency_first_pass_dataset.csv` | `experiment_block=multistation_consistency; bk_mode=current_bk; station_strategy=single_station_baseline` | 3 | 5, `0,50,100,200,500` | 3 | 5, `10,50,100,500,1000` |
| `三站 all-accept current_bk` | 0.2652777778 | 2865 | 10800 | `multistation_consistency_first_pass_dataset.csv` | `experiment_block=multistation_consistency; bk_mode=current_bk; station_strategy=three_station_all_accept` | 3 | 5, `0,50,100,200,500` | 3 | 5, `10,50,100,500,1000` |
| `三站 + b/k 风险暂缓` | 0.0885185185 | 956 | 10800 | `multistation_consistency_first_pass_dataset.csv` | `experiment_block=multistation_consistency; bk_mode=bk_risk_defer; station_strategy=three_station_all_accept` | 3 | 5, `0,50,100,200,500` | 3 | 5, `10,50,100,500,1000` |

## 7. What can be claimed in group meeting

可以说：

- 上一轮确实生成了新的样本级固化 dataset、主 summary、拆分 summary、报告和图表。
- 这个 dataset 将既有 window-aware、single-station b/k、multistation 离线仿真结果统一到同一字段结构和统计口径。
- “扩大样本”和“细分样本”应表述为：扩大了统一复算/汇总口径下纳入的既有离线结果行数，并按样本组、参考点误差、b/k 模式、窗口模式、多站策略进行拆分统计。

不应说：

- 不应说上一轮重新进行了全量轨道传播、多普勒曲线生成、固定参考点补偿生成和 verifier 判决。
- 不应把这些结果解释成真实卫星链路验证或真实世界攻击成功率。
- 不应说 `fixed_reference_compensation_extended_dataset.csv` 的行直接进入 stage dataset；实际进入的是 single-station b/k dataset、multistation dataset 和 window-aware dataset。

## 8. Remaining uncertainty

- stage dataset 记录了 `source_dataset`，但没有记录源 CSV 的源行号字段；window-aware 的 `row_id` 是源 DataFrame index，single/multistation 的 `row_id` 来自源 CSV。若要逐行可逆追踪，建议后续增加 `source_row_index` 和 `source_experiment_block`。
- `fixed_reference_compensation_extended_dataset.csv` 被检查存在但未合并，这一点已在报告中说明；如果需要审计该旧 fixed-reference extended 表本身，应另做一轮 lineage 对比。
- single-station b/k 旧行被复用到 `fixed_reference_compensation` 和 `bk_ablation` 两个 block，适合阶段口径对照，但不是两个独立仿真来源。
- 本报告没有复核更早源 CSV 的生成过程，只确认 stage_conclusion 层没有重新运行底层仿真。
