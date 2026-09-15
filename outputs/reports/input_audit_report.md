# 新项目输入审计报告

生成时间：2026-05-03 20:51  
任务范围：新项目输入审计、目录初始化、数据字段检查  
结论摘要：核心输入文件齐全，5 个 accepted 样本的 `residual_dataset.csv` 齐全，后续第一版仿真所需字段 `t_rel_s` 与 `f_geo_fit_hz` 均存在且可解析为数值。本轮未生成仿真数据集，未编写 residual matcher，未编写攻击模块。

## 1. 输入来源

本项目为旧项目迁移包，当前审计依据如下文件和目录：

- `AGENTS.md`
- `README.md`
- `configs/simulation_parameter_config.yaml`
- `data/metadata/sample_tiering_review.csv`
- `data/metadata/master_sample_summary.csv`
- `data/source_residual_datasets/accepted/*/residual_dataset.csv`

说明：终端读取 `AGENTS.md` 时出现中文编码显示异常，但本轮任务消息中已提供完整清晰的 `AGENTS.md` 内容，因此审计和写作规范以任务消息中的 AGENTS 内容为准。

## 2. 目录结构检查

已存在目录：

| 目录 | 状态 |
|---|---|
| `configs/` | 存在 |
| `data/` | 存在 |
| `data/source_residual_datasets/` | 存在 |
| `data/source_residual_datasets/accepted/` | 存在 |
| `data/source_residual_datasets/borderline/` | 存在 |
| `data/source_residual_datasets/rejected/` | 存在 |
| `data/metadata/` | 存在 |
| `data/parameter_ranges/` | 存在 |
| `docs/` | 存在 |
| `docs/data_lineage/` | 存在 |
| `docs/reports/` | 存在 |

本轮初始化创建目录：

| 目录 | 状态 |
|---|---|
| `data/generated/` | 已创建 |
| `docs/parameter_recommendations/` | 已创建 |
| `docs/experiment_design/` | 已创建 |
| `scripts/` | 已创建 |
| `outputs/` | 已创建 |
| `outputs/datasets/` | 已创建 |
| `outputs/reports/` | 已创建 |
| `outputs/plots/` | 已创建 |
| `outputs/metrics/` | 已创建 |
| `logs/` | 已创建 |

## 3. 核心文件检查

| 文件 | 状态 | 备注 |
|---|---|---|
| `AGENTS.md` | 存在 | 终端显示存在编码问题；按任务消息中的正文执行 |
| `README.md` | 存在 | 可读取 |
| `configs/simulation_parameter_config.yaml` | 存在 | 可读取；当前 Python 环境缺少 `pyyaml`，本轮使用文本键值审计 |
| `data/metadata/sample_tiering_review.csv` | 存在 | 可读取，10 行 |
| `data/metadata/master_sample_summary.csv` | 存在 | 可读取，10 行 |

## 4. YAML 参数范围检查

配置文件：`configs/simulation_parameter_config.yaml`

文本审计确认存在以下配置：

| 参数 | source_field | main_range | extended_range | stress_range | 状态 |
|---|---|---:|---:|---:|---|
| `b_hz` | `registered_frequency_offset_hz` | `[3179.0, 3728.0]` | `[1980.0, 4692.0]` | `[1980.0, 4692.0]` | 完整 |
| `k_hz_per_s` | `linear_slope_hz_per_s` | `[-1.110156, -0.197808]` | `[-4.052513, 4.03749]` | `[-4.052513, 4.03749]` | 完整 |
| `sigma_hz` | `detrended_std_hz` | `[23.215, 32.89]` | `[10.917, 55.951]` | `[10.917, 84.073]` | 完整 |

配置中也存在四类第一版场景：

- `clean`
- `offset_only`
- `offset_plus_noise`
- `offset_linear_noise`

边界说明：`registered_frequency_offset_hz` 在本项目中应解释为 registered offset / effective constant frequency bias；`detrended_std_hz` 仅作为第一版高斯尺度近似，不代表严格白噪声结论。

## 5. Metadata 检查

`sample_tiering_review.csv` 字段：

```text
observation_id
previous_acceptance_status
reviewed_acceptance_status
rms_khz
measurements
detrended_std_hz
improvement_ratio
lag1_autocorr
quadratic_improvement_ratio
review_note
```

`master_sample_summary.csv` 字段：

```text
observation_id
norad_id
site_id
acceptance_status
fitted_frequency_hz
reference_frequency_hz
registered_frequency_offset_hz
rms_khz
measurements
tca_utc
residual_std_hz
residual_rms_hz
detrended_std_hz
linear_slope_hz_per_s
improvement_ratio
lag1_autocorr
jb_pvalue
quadratic_improvement_ratio
```

两个 metadata 文件中的 accepted 样本一致：

```text
8535896
8641460
8707816
8733468
9424971
```

## 6. Accepted residual_dataset 字段检查

后续第一版仿真最小必需字段：

- `t_rel_s`
- `f_geo_fit_hz`

辅助可用字段：

- `f_obs_hz`

检查结果：

| observation_id | residual_dataset.csv | 行数 | `t_rel_s` | `f_geo_fit_hz` | `f_obs_hz` | 空值/非数值 |
|---|---|---:|---|---|---|---|
| `8535896` | 存在 | 151 | 存在 | 存在 | 存在 | 无 |
| `8641460` | 存在 | 157 | 存在 | 存在 | 存在 | 无 |
| `8707816` | 存在 | 141 | 存在 | 存在 | 存在 | 无 |
| `8733468` | 存在 | 149 | 存在 | 存在 | 存在 | 无 |
| `9424971` | 存在 | 161 | 存在 | 存在 | 存在 | 无 |

所有 accepted residual 数据集字段一致：

```text
observation_id
norad_id
station_id
start_utc
t_rel_s
t_abs_utc
f_obs_hz
f_geo_fit_hz
residual_hz
source_physical_csv
source_residual_file
```

## 7. 当前结论

当前迁移包满足新项目 Step 1 的最小启动要求：

- 配置文件存在，b / k / sigma 参数范围完整；
- metadata 文件存在，accepted 样本清单与推荐主分析池一致；
- 5 个 accepted 样本的 `residual_dataset.csv` 齐全；
- 后续第一版仿真需要的时间序列字段和几何基线频率字段齐全；
- 缺失的推荐目录已初始化；
- 本轮没有覆盖迁移数据原始文件。

## 8. 结论边界与下一步

本报告仅完成输入审计，不说明任何仿真识别结果，也不外推攻击场景结论。  
第一版数据集使用已有样本的 `f_geo_fit_hz` 作为基线频率序列，用于验证频偏扰动生成和识别流程。后续攻击轨道场景中，可替换为不同候选轨道生成的 `f_geo_candidate(t)`。

建议下一步在确认审计报告后，再进入数据集生成脚本实现或运行；默认仍应只使用 accepted 主分析池和 `main_range`。
