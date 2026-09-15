# 第一版仿真数据集生成报告

生成时间：2026-05-03 20:56  
配置版本：`effective_cfo_simulation_v1`  
YAML 读取方式：`pyyaml`

## 1. 本轮目标

基于 accepted 样本中的 `t_rel_s` 和 `f_geo_fit_hz`，使用 `configs/simulation_parameter_config.yaml` 中的有效频偏参数范围，生成第一版工程级 frequency offset 仿真数据集。本轮只生成数据集、manifest、sanity check 报告和图表；未实现 baseline matcher，未进入攻击场景。

## 2. 输入文件

- 配置文件：`configs\simulation_parameter_config.yaml`
- 输入样本目录：`data\source_residual_datasets\accepted`
- accepted 样本：8535896, 8641460, 8707816, 8733468, 9424971

## 3. 使用模型

默认模型：

```text
f_sim(t) = f_geo(t) + b + k(t - t0) + noise
```

其中 `t0 = mean(t_rel_s)`，`f_geo(t)` 在第一版中来自 `residual_dataset.csv["f_geo_fit_hz"]`。

## 4. 使用参数范围

本轮使用 `parameter_range_type = main`。

| 参数 | 使用范围 |
|---|---|
| `b_hz` | `[3179.0, 3728.0]` |
| `k_hz_per_s` | `[-1.110156, -0.197808]` |
| `sigma_hz` | `[23.215, 32.89]` |

## 5. 生成场景

| scenario | 序列数 | 行数 |
|---|---:|---:|
| `clean` | 500 | 75900 |
| `offset_only` | 500 | 75900 |
| `offset_plus_noise` | 500 | 75900 |
| `offset_linear_noise` | 500 | 75900 |

每个 accepted 样本生成序列数：

| base_observation_id | 序列数 |
|---|---:|
| `8535896` | 400 |
| `8641460` | 400 |
| `8707816` | 400 |
| `8733468` | 400 |
| `9424971` | 400 |

## 6. 参数采样范围检查

- `b_hz`: 通过，范围 `[3179.0, 3728.0]`
- `k_hz_per_s`: 通过，范围 `[-1.110156, -0.197808]`
- `sigma_hz`: 通过，范围 `[23.215, 32.89]`

说明：`clean` 场景固定 `b_hz=0`、`k_hz_per_s=0`、`sigma_hz=0`；`offset_only` 固定 `k_hz_per_s=0`、`sigma_hz=0`；`offset_plus_noise` 固定 `k_hz_per_s=0`。

## 7. Scenario 基本统计

统计量基于 `f_sim_hz - f_geo_hz`。

| scenario | mean | std | min | max | count |
|---|---:|---:|---:|---:|---:|
| `clean` | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 75900 |
| `offset_linear_noise` | 3449.444385 | 165.937372 | 3004.334899 | 3878.049624 | 75900 |
| `offset_only` | 3450.897674 | 153.528146 | 3179.143842 | 3724.188539 | 75900 |
| `offset_plus_noise` | 3438.595176 | 165.089548 | 3070.391233 | 3815.668696 | 75900 |

## 8. 输出文件

- 数据集：`outputs\datasets\simulated_frequency_dataset.csv`
- Manifest：`outputs\datasets\simulation_manifest.json`
- 图表目录：`outputs\plots`
- `sim_delta_hist_by_scenario.png`
- `example_sim_timeseries_offset_linear_noise.png`
- `parameter_samples_b_k_sigma.png`

## 9. Sanity check 结论

本轮输出行数与 accepted 样本长度、场景数、`num_sims_per_sample=100` 一致。主动采样的 `b_hz`、`k_hz_per_s`、`sigma_hz` 均落在 `main_range` 内。随机过程由 `seed=42` 控制，可复现。

## 10. 边界说明

- 第一版使用已有样本的 `f_geo_fit_hz` 作为基线频率序列；
- 本轮不重新传播轨道，不重跑 rffit，不重新分析 residual；
- `registered_frequency_offset_hz` 解释为 registered offset / effective constant frequency bias，不解释为 pure CFO ground truth；
- 噪声是第一版高斯近似，不代表严格白噪声；
- 图表只用于 sanity check，不作为证明性结论。
