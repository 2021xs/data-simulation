# 从 rffit GUI 导出到 residual / offset 分析的数据血缘

## 1. 总览

当前项目的数据流可以分成两条线：

```text
residual 主线：
waterfall 图像
-> tracking / calibration
-> physical CSV
-> bridge 生成 rffit .dat 和 normalized.csv
-> rffit GUI 中按 s / f / j
-> residuals.dat，保存为 residuals_rffit.dat
-> residual_dataset.csv
-> residual_analysis_summary.csv
-> detrended_residual_summary.csv
-> master_sample_summary.csv
-> sample_tiering_review.csv
```

```text
offset 支线：
rffit GUI 中按 f 后终端输出高精度拟合行
-> 用户从终端复制整理为 bridge/input/rffit_fitline_summary.csv
-> build_fit_offset_summary.py
-> fit_offset_summary.csv
-> master_sample_summary.csv
-> offset 相关图表
```

最重要的边界：

- residual 主线的最原始分析输入是 rffit GUI 按 `j` 导出的 `residuals.dat`，当前保存为 `bridge/out/<obs_id>/residuals_rffit.dat`。
- offset 支线的最原始归档输入是用户从 rffit 终端复制整理的 `bridge/input/rffit_fitline_summary.csv`。
- `registered_frequency_offset_hz` 不是纯 CFO 真值，只能解释为注册频偏 / 有效常数频率偏置。

## 2. 必看文件顺序

如果你想理解整条数据来龙去脉，建议按下面顺序看。

### 第 1 组：总入口

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 1 | `docs/data_lineage_from_rffit_gui_to_analysis_zh.md` | 中文总览，先建立整条链路地图 |
| 2 | `docs/fit_offset_lineage_and_reproduction_zh.md` | offset 支线从终端整理表到 offset summary 的复现逻辑 |
| 3 | `codex_workspace/reports/sample_progress_tracker.md` | Top10 当前样本状态和已有产物位置 |

### 第 2 组：rffit GUI 到 residual 文件

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 4 | `bridge/README.md` | bridge 流程、rffit 操作 SOP、`s/f/j` 的人工步骤 |
| 5 | `rffit.c` | rffit 源码中 `f` 和 `j` 的真实行为 |
| 6 | `bridge/out/<obs_id>/residuals_rffit.dat` | rffit GUI 按 `j` 导出的 residual 文件保存版 |
| 7 | `bridge/out/<obs_id>/obs_<obs_id>_normalized.csv` | bridge 输出的观测时间和观测频率 |

### 第 3 组：residual_dataset.csv 如何生成

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 8 | `bridge/scripts/export_residual_dataset.py` | 如何把 `normalized.csv` 和 `residuals_rffit.dat` 按行对齐 |
| 9 | `bridge/out/<obs_id>/residual_dataset.csv` | 标准化后的 residual 数据集 |

关键公式：

```text
residual_hz = residual_khz * 1000
f_geo_fit_hz = f_obs_hz - residual_hz
residual_hz = f_obs_hz - f_geo_fit_hz
```

### 第 4 组：residual summary 和 detrended residual

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 10 | `bridge/scripts/analyze_residual_dataset.py` | residual 均值、标准差、RMS、一阶 slope、improvement ratio 怎么算 |
| 11 | `bridge/out/residual_analysis_summary.csv` | 10 个样本的 residual 主线样本级统计 |
| 12 | `bridge/scripts/analyze_detrended_residual.py` | 去趋势 residual、JB 检验、lag1 自相关、二阶改善率怎么计算 |
| 13 | `bridge/out/detrended_residual_summary.csv` | 去趋势 residual 的分布统计 |
| 14 | `bridge/out/<obs_id>/analysis/residual_dataset_detrended_<obs_id>.csv` | 单样本逐点的一阶拟合值和去趋势 residual |

一阶模型是：

```text
residual_hz = b0 + k * (t_rel_s - t0) + e
t0 = mean(t_rel_s)
```

### 第 5 组：offset 支线

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 15 | `bridge/input/rffit_fitline_summary.csv` | offset 支线最原始归档表，由 rffit 终端输出复制整理而来 |
| 16 | `bridge/input/<obs_id>/strf_ready.json` | 参考中心频率字段 `center_freq_hz` |
| 17 | `bridge/scripts/build_fit_offset_summary.py` | 如何复现 `fit_offset_summary.csv` |
| 18 | `bridge/out/fit_offset_summary.csv` | 每个样本的注册频偏结果 |
| 19 | `bridge/out/<obs_id>/fit_offset_summary.json` | 单样本 offset 血缘记录 |

关键公式：

```text
fitted_frequency_hz = fitted_frequency_mhz * 1e6
reference_frequency_hz = center_freq_hz
registered_frequency_offset_hz = fitted_frequency_hz - reference_frequency_hz
```

### 第 6 组：联合总表、分层、图表

| 阅读顺序 | 文件 | 看什么 |
|---:|---|---|
| 20 | `codex_workspace/scripts/build_master_sample_summary.py` | 如何合并 residual、detrended、offset 和旧分层草案 |
| 21 | `bridge/out/master_sample_summary.csv` | 联合总表 |
| 22 | `codex_workspace/scripts/build_sample_tiering_review.py` | accepted / borderline / rejected 的规则化复核 |
| 23 | `bridge/out/sample_tiering_review.csv` | 最终分层复核结果 |
| 24 | `bridge/out/plots/*.svg` | offset 与 residual 指标关系图 |

## 3. rffit GUI 输出了什么

### 3.1 按 `f`

rffit GUI 中按 `f` 后，源码会执行拟合，并在终端输出高精度结果行。

相关源码位置：

```text
rffit.c
```

关键输出字段包括：

```text
norad_id
fitted_frequency_mhz
rms_khz
tca_utc
site_id
tle_epoch_yyddd
measurements
```

当前这些终端输出被用户复制整理到：

```text
bridge/input/rffit_fitline_summary.csv
```

### 3.2 按 `j`

rffit GUI 中按 `j` 后，源码会写出：

```text
residuals.dat
```

当前保存为：

```text
bridge/out/<obs_id>/residuals_rffit.dat
```

每行格式是：

```text
mjd  observed_frequency_khz  residual_khz  site_id
```

residual 的符号方向由 rffit 源码确认：

```text
residual = observed_frequency - fitted_model_frequency
```

## 4. residual_dataset.csv 如何生成

脚本：

```text
bridge/scripts/export_residual_dataset.py
```

输入：

```text
bridge/input/<obs_id>/strf_ready.json
bridge/out/<obs_id>/obs_<obs_id>_normalized.csv
bridge/out/<obs_id>/residuals_rffit.dat
```

对齐方式：

- 按行顺序对齐；
- 不是按 MJD join；
- MJD 和频率只用于一致性校验；
- 默认 MJD 容差是 `1e-6 day`；
- 默认频率容差是 `0.1 Hz`；
- 超容差会报错。

核心字段血缘：

| 字段 | 来源 | 公式 / 说明 |
|---|---|---|
| `observation_id` | `strf_ready.json` | 直接读取 |
| `norad_id` | `strf_ready.json` | 直接读取 |
| `station_id` | `strf_ready.json:satnogs_station_id` | SatNOGS station id，不是 STRF site id |
| `t_rel_s` | normalized UTC + `start_utc` | `t_abs_utc - start_utc` |
| `t_abs_utc` | normalized CSV | 直接读取 |
| `f_obs_hz` | normalized CSV | 观测频率 |
| `residual_hz` | residuals_rffit.dat 第 3 列 | `residual_khz * 1000` |
| `f_geo_fit_hz` | `f_obs_hz` 和 `residual_hz` | `f_obs_hz - residual_hz` |

## 5. residual_analysis_summary.csv 如何生成

脚本：

```text
bridge/scripts/analyze_residual_dataset.py
```

输入：

```text
bridge/out/<obs_id>/residual_dataset.csv
```

主要指标：

| 字段 | 计算方式 |
|---|---|
| `N` | 行数 |
| `residual_mean_hz` | `residual_hz` 均值 |
| `residual_std_hz` | `residual_hz` 总体标准差 |
| `residual_rms_hz` | `sqrt(mean(residual_hz^2))` |
| `residual_range_hz` | max - min |
| `slope_hz_per_s` | 中心化一阶拟合斜率 |
| `detrended_std_hz` | 一阶去趋势后的总体标准差 |
| `improvement_ratio` | `(residual_std_hz - detrended_std_hz) / residual_std_hz` |

## 6. detrended_residual_summary.csv 如何生成

脚本：

```text
bridge/scripts/analyze_detrended_residual.py
```

输入仍然是：

```text
bridge/out/<obs_id>/residual_dataset.csv
```

它会重新计算一阶去趋势，不是简单读取 residual summary。

输出包括：

```text
detrended_std_hz
skewness
kurtosis
normality_p_value
gaussian_like_judgement
remaining_time_structure_judgement
model_order_suggestion
```

注意：

- JB p-value 高，只说明边际分布形状接近高斯；
- lag1 自相关高，说明时间顺序上仍有相关结构；
- 所以“近似高斯”不等于“白噪声”。

## 7. registered_frequency_offset_hz 如何生成

脚本：

```text
bridge/scripts/build_fit_offset_summary.py
```

输入：

```text
bridge/input/rffit_fitline_summary.csv
bridge/input/<obs_id>/strf_ready.json
```

参考频率真实字段名：

```text
center_freq_hz
```

公式：

```text
fitted_frequency_hz = fitted_frequency_mhz * 1e6
reference_frequency_hz = center_freq_hz
registered_frequency_offset_hz = fitted_frequency_hz - reference_frequency_hz
```

这个量的物理解释：

- 它是 rffit Frequency 拟合吸收掉的整体频率平移；
- 可称为注册频偏 / 有效常数频率偏置；
- 不能称为纯 CFO 真值；
- 可能混合接收机本振偏差、中心频率设定误差、图像标定误差、TLE / 几何模型误差中被常数项吸收的部分。

## 8. master_sample_summary.csv 和 sample_tiering_review.csv

联合总表脚本：

```text
codex_workspace/scripts/build_master_sample_summary.py
```

输入：

```text
bridge/out/fit_offset_summary.csv
bridge/out/residual_analysis_summary.csv
bridge/out/detrended_residual_summary.csv
codex_workspace/reports/sample_acceptance_draft.md
bridge/out/<obs_id>/analysis/detrended_residual_analysis_<obs_id>.md
```

分层复核脚本：

```text
codex_workspace/scripts/build_sample_tiering_review.py
```

分层依据主要是：

```text
rms_khz
measurements
detrended_std_hz
improvement_ratio
lag1_autocorr
quadratic_improvement_ratio
```

当前分层：

| 分层 | 样本 |
|---|---|
| `accepted` | `8535896`, `8641460`, `8707816`, `8733468`, `9424971` |
| `borderline` | `8493026`, `8788317`, `8814142`, `9462382` |
| `rejected` | `8823291` |

注意：

- Top10 是前期筛图得到的候选样本池；
- accepted / borderline / rejected 是 Top10 内部用于 residual 分析的使用分层；
- 这不是重新筛图，也不是否定 Top10。

## 9. 你可以怎样向老师解释

可以这样说：

```text
这套数据不是 AI 编出来的。residual 主线来自 rffit GUI 按 j 导出的 residuals.dat，
我们保存为 residuals_rffit.dat，然后脚本按行与 normalized.csv 校验对齐，
再计算 residual_dataset.csv 和各类统计表。

offset 支线来自 rffit GUI 按 f 后终端输出的高精度拟合频率。
我把终端输出复制整理成 bridge/input/rffit_fitline_summary.csv，
这个文件是 offset 支线当前的最原始归档表。
现在已有 build_fit_offset_summary.py 可以从这个表和 strf_ready.json:center_freq_hz
复现 fit_offset_summary.csv。

registered_frequency_offset_hz 只是注册频偏或有效常数频率偏置，
不能解释成纯 CFO 真值。
```
