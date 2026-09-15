# Stage 5 Group Meeting Assets

主题：Top10 样本扩展、规则化分层与 residual / offset 联合分析。

| 页码 | 对应文件 | 这一页讲什么 | 核心一句话 |
|---|---|---|---|
| 1 | slide01_stage_position.md | 阶段定位 | 从两样本验证推进到 Top10 统一分析和 residual / offset 联合框架。 |
| 2 | top10_analyzed_status_table.md / .csv | Top10 状态 | 10 个候选样本均已进入 analyzed，并具备 residual / detrended / offset 汇总。 |
| 3 | top10_residual_summary_for_slide.md / .csv | residual 指标 | Top10 residual 强弱不同，一阶慢漂移结构普遍存在。 |
| 4 | sample_tiering_slide_table.md / .csv | 分层结果 | Top10 不变，accepted / borderline / rejected 是分析使用分层。 |
| 5 | offset_lineage_slide.md；top10_offset_summary_for_slide.md / .csv | offset 来源 | registered offset 来自 rffit fitline 与 strf_ready 参考频率之差，不是纯 CFO 真值。 |
| 6 | joint_residual_offset_interpretation.md；figures/registered_frequency_offset_vs_detrended_std.svg；figures/registered_frequency_offset_vs_linear_slope.svg | 联合分析 | 当前未观察到 offset 与慢漂移/去趋势噪声的明显简单线性对应关系。 |
| 7 | stage5_conclusion_and_next_steps.md | 结论与下一步 | 下一步应在 accepted 主分析池上做模型比较和参数范围统计。 |

补充材料：

- presentation_materials_checklist.md：展示材料清单。
- teacher_qa_for_stage5.md：老师可能追问与简洁回答。
- example_9424971_lineage_and_metrics.md：单样本 `9424971` 的 residual 数据链路与指标解释，可作为汇报中的具体案例页或备份讲解页。

输入来源：

- codex_workspace/tables/sample_progress_tracker.csv
- bridge/out/residual_analysis_summary.csv
- bridge/out/detrended_residual_summary.csv
- bridge/out/fit_offset_summary.csv
- bridge/out/sample_tiering_review.csv
- bridge/out/master_sample_summary.csv
- bridge/out/plots/registered_frequency_offset_vs_detrended_std.svg
- bridge/out/plots/registered_frequency_offset_vs_linear_slope.svg

注意：

- 本轮没有重新跑 residual 主线，没有重新分层，也没有改写旧 summary。
- 用户要求预读的 `codex_workspace/reports/data_lineage_from_rffit_gui_to_analysis_zh.md` 和 `codex_workspace/reports/fit_offset_lineage_and_reproduction_zh.md` 当前未在该目录下找到；实际已读取并遵循的是 `docs/data_lineage_from_rffit_gui_to_analysis_zh.md` 和 `docs/fit_offset_lineage_and_reproduction_zh.md`。
- `registered_frequency_offset_hz` 在本材料中统一解释为 registered offset / effective constant frequency bias，不写成 true CFO 或 CFO ground truth。
