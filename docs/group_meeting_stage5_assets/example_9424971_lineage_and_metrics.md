# 单样本示例：9424971 residual 数据链路与指标解释

本说明只基于当前仓库中的真实文件和脚本整理，用于组会中解释“一个样本的 residual 数据从哪里来、每个指标是什么意思、offset 支线和 residual 主线是什么关系”。本轮没有重新跑实验、没有修改旧 summary，也没有重新分层。

## 1. 为什么选 9424971 做例子

`9424971` 适合作为标准链路示例，原因有四点：

- 它是前期最早跑通 residual 链路的样本之一；
- 它当前属于 `accepted` 主分析池；
- rffit 拟合 RMS 较低，`rms_khz = 0.035`；
- 它的文件链路完整，bridge 输入、rffit residual、样本级分析和 offset JSON 都存在。

关键指标如下，来源分别是 `bridge/out/master_sample_summary.csv`、`bridge/out/residual_analysis_summary.csv`、`bridge/out/detrended_residual_summary.csv`、`bridge/out/sample_tiering_review.csv` 和 `bridge/out/9424971/fit_offset_summary.json`。

| 指标 | 数值 | 解释 |
|---|---:|---|
| `acceptance_status` | accepted | Top10 内部分析使用分层，适合进入主分析池 |
| `measurements` | 161 | rffit 参与拟合 / residual 分析的测量点数 |
| `rms_khz` | 0.035 | rffit Frequency 拟合后的 RMS，单位 kHz |
| `registered_frequency_offset_hz` | 4409.0 | 相对 `center_freq_hz` 的注册频偏 / 有效常数频率偏置 |
| `residual_std_hz` | 35.157545 | 原始 residual 的总体标准差 |
| `detrended_std_hz` | 32.889947 | 去掉一阶趋势后的 residual 总体标准差 |
| `linear_slope_hz_per_s` | -0.197808 | 一阶 residual 漂移斜率 |
| `improvement_ratio` | 0.064498 | 一阶去趋势相对原始 std 的改善比例 |
| `lag1_autocorr` | 0.961303 | 去趋势后 residual 的一阶自相关 |
| `quadratic_improvement_ratio` | 0.546793 | 在一阶去趋势后，再用二阶项解释剩余结构的 std 改善比例 |

组会讲法：`9424971` 是一个拟合质量好、点数充足、去趋势后噪声较低的 accepted 样本。它的线性趋势不强，但仍保留明显时间相关结构，因此很适合用来说明“残差数据链路”和“为什么不能只看高斯性”。

## 2. 9424971 的完整数据链路

```text
bridge/input/9424971/obs_9424971_track_physical.csv
+ bridge/input/9424971/strf_ready.json
+ bridge/input/9424971/catalog.tle
-> bridge/out/9424971/obs_9424971_rffit.dat
+ bridge/out/9424971/obs_9424971_normalized.csv
-> rffit GUI: s / f / j
-> bridge/out/9424971/residuals_rffit.dat
-> bridge/out/9424971/residual_dataset.csv
-> bridge/out/9424971/analysis/residual_analysis_9424971.md
-> bridge/out/9424971/analysis/detrended_residual_analysis_9424971.md
-> bridge/out/residual_analysis_summary.csv
+ bridge/out/detrended_residual_summary.csv
-> bridge/out/master_sample_summary.csv
+ bridge/out/sample_tiering_review.csv
```

offset 支线是并行链路：

```text
rffit GUI 按 f 后终端输出高精度拟合行
-> 用户复制整理为 bridge/input/rffit_fitline_summary.csv
+ bridge/input/9424971/strf_ready.json:center_freq_hz
-> bridge/scripts/build_fit_offset_summary.py
-> bridge/out/9424971/fit_offset_summary.json
+ bridge/out/fit_offset_summary.csv
-> bridge/out/master_sample_summary.csv
```

这里要明确区分：residual 主线分析的是拟合注册之后剩余的频率残差结构；offset 支线记录的是 rffit 为了对齐频率曲线而吸收的样本级整体频率平移。

## 3. 关键文件逐个说明

| 文件 | 是否存在 | 作用 |
|---|---|---|
| `bridge/input/9424971/strf_ready.json` | 存在 | 样本 metadata：`observation_id`、`start_utc`、`center_freq_hz`、`norad_id`、站点坐标等 |
| `bridge/input/9424971/catalog.tle` | 存在 | rffit/STRF 使用的 TLE；本样本为 `IRIDIUM 113`，NORAD `42803` |
| `bridge/input/9424971/obs_9424971_track_physical.csv` | 存在 | 从 waterfall 图像轨迹转换得到的物理量轨迹 |
| `bridge/out/9424971/obs_9424971_rffit.dat` | 存在 | 给 rffit GUI 使用的观测点文件 |
| `bridge/out/9424971/obs_9424971_normalized.csv` | 存在 | bridge 输出的标准化观测点，含 MJD、UTC、观测频率 |
| `bridge/out/9424971/residuals_rffit.dat` | 存在 | rffit GUI 按 `j` 导出的 residual 文件保存版 |
| `bridge/out/9424971/residual_dataset.csv` | 存在 | normalized CSV 与 rffit residual 对齐后的标准 residual 数据集 |
| `bridge/out/9424971/analysis/residual_analysis_9424971.md` | 存在 | 原始 residual 的样本级统计和一阶拟合说明 |
| `bridge/out/9424971/analysis/detrended_residual_analysis_9424971.md` | 存在 | 一阶去趋势后的分布统计、JB 检验、时间结构判断 |
| `bridge/out/9424971/analysis/residual_dataset_detrended_9424971.csv` | 存在 | 每个点的一阶拟合值和去趋势 residual |
| `bridge/out/9424971/fit_offset_summary.json` | 存在 | 单样本 offset 支线血缘记录 |

`strf_ready.json` 中本样本关键字段为：

| 字段 | 数值 |
|---|---:|
| `observation_id` | 9424971 |
| `start_utc` | 2024-04-25T17:44:54Z |
| `end_utc` | 2024-04-25T17:49:35Z |
| `center_freq_hz` | 1623192000 |
| `norad_id` | 42803 |
| `satnogs_station_id` | 3299 |
| `site_lat` | 52.21 |
| `site_lon` | 5.16 |
| `site_elev_m` | 14 |

## 4. residuals_rffit.dat 是什么

`bridge/out/9424971/residuals_rffit.dat` 是 rffit GUI 中按 `j` 导出的 residual 文件保存版。根据当前中文 lineage 报告和 `bridge/scripts/export_residual_dataset.py` 的读取逻辑，每行至少 4 列：

```text
mjd  observed_frequency_khz  residual_khz  site_id
```

本样本前 3 行为：

| 行 | MJD | observed_frequency_khz | residual_khz | site_id |
|---:|---:|---:|---:|---:|
| 1 | 60425.73998600 | 1623210.713400 | 0.092791 | 9999 |
| 2 | 60425.73999300 | 1623210.635520 | 0.088137 | 9999 |
| 3 | 60425.74000000 | 1623210.553590 | 0.079627 | 9999 |

这里的 residual 符号方向按当前 lineage 和脚本推导使用：

```text
residual_hz = f_obs_hz - f_geo_fit_hz
f_geo_fit_hz = f_obs_hz - residual_hz
```

因此 residual 为正时，表示观测频率高于拟合后的理论频率。

## 5. residual_dataset.csv 每一行是什么意思

`bridge/out/9424971/residual_dataset.csv` 是后续 residual 统计的标准输入。它由 `bridge/scripts/export_residual_dataset.py` 生成，脚本逻辑包括：

- 默认 MJD 容差：`1e-6 day`；
- 默认频率容差：`0.1 Hz`；
- `normalized.csv` 与 `residuals_rffit.dat` 行数必须相同；
- 两个文件按行顺序对齐；
- MJD 和观测频率用于一致性校验，超容差时报错；
- `residual_hz = residual_khz * 1000`；
- `f_geo_fit_hz = f_obs_hz - residual_hz`。

核心字段解释：

| 字段 | 来源 | 含义 / 公式 | 单位 |
|---|---|---|---|
| `observation_id` | `strf_ready.json` | 样本编号 | id |
| `norad_id` | `strf_ready.json` | 卫星 NORAD 编号 | id |
| `station_id` | `strf_ready.json:satnogs_station_id` | SatNOGS 站点编号 | id |
| `start_utc` | `strf_ready.json` | 样本起始时间 | UTC |
| `t_rel_s` | `t_abs_utc - start_utc` | 相对起始时间 | s |
| `t_abs_utc` | `normalized.csv:utc` | 该测量点的绝对时间 | UTC |
| `f_obs_hz` | `normalized.csv:freq_hz` | 观测频率 | Hz |
| `residual_hz` | `residuals_rffit.dat` 第 3 列 | `residual_khz * 1000` | Hz |
| `f_geo_fit_hz` | `f_obs_hz` 与 `residual_hz` | `f_obs_hz - residual_hz` | Hz |
| `source_residual_file` | 脚本写入 | residual 来源文件路径 | text |

### 第一行手工追踪

`obs_9424971_normalized.csv` 第一行：

```text
mjd=60425.739985738
utc=2024-04-25T17:45:34.767764Z
freq_hz=1623210713.396
site_id=9999
```

`residuals_rffit.dat` 第一行：

```text
60425.73998600 1623210.713400 0.092791 9999
```

换算和计算：

```text
residual_hz = 0.092791 kHz * 1000 = 92.791 Hz
f_geo_fit_hz = 1623210713.396 - 92.791 = 1623210620.605 Hz
t_rel_s = 2024-04-25T17:45:34.767764Z - 2024-04-25T17:44:54Z = 40.767764 s
```

`residual_dataset.csv` 第一行对应：

| 字段 | 数值 |
|---|---:|
| `observation_id` | 9424971 |
| `norad_id` | 42803 |
| `station_id` | 3299 |
| `t_rel_s` | 40.767764 |
| `t_abs_utc` | 2024-04-25T17:45:34.767764Z |
| `f_obs_hz` | 1623210713.396000 |
| `f_geo_fit_hz` | 1623210620.605000 |
| `residual_hz` | 92.791000 |

组会讲法：这一行不是 AI 算出来的孤立数字，而是 rffit 按 `j` 导出的 residual 与 normalized 观测点逐行校验对齐后得到的。

## 6. residual_analysis_summary 指标怎么计算

样本级文件：`bridge/out/9424971/analysis/residual_analysis_9424971.md`。

总表文件：`bridge/out/residual_analysis_summary.csv`。

脚本：`bridge/scripts/analyze_residual_dataset.py`。

它使用 `residual_dataset.csv` 中每行的 `t_rel_s` 和 `residual_hz`，先统计原 residual，再拟合一阶模型：

```text
residual_hz = b0 + k * (t_rel_s - t0) + e
t0 = mean(t_rel_s)
```

`9424971` 的一阶参数：

| 参数 | 数值 | 说明 |
|---|---:|---|
| `t0` | 147.693750 s | 该样本 `t_rel_s` 的均值 |
| `b0` | -0.000025 Hz | 中心化时间下的截距，接近 residual 均值 |
| `k` | -0.197808 Hz/s | 一阶慢漂移斜率 |

指标公式：

| 指标 | 公式 | 9424971 数值 | 说明 |
|---|---|---:|---|
| `N` | 行数 | 161 | 参与统计的 residual 点数 |
| `residual_mean_hz` | `mean(residual_hz)` | -0.000025 | 原 residual 均值 |
| `residual_std_hz` | `population_std(residual_hz)` | 35.157545 | 原 residual 总体标准差 |
| `residual_rms_hz` | `sqrt(mean(residual_hz^2))` | 35.157545 | 原 residual RMS |
| `residual_min_hz` | `min(residual_hz)` | -63.222000 | 最小 residual |
| `residual_max_hz` | `max(residual_hz)` | 92.791000 | 最大 residual |
| `residual_range_hz` | `max - min` | 156.013000 | residual 范围 |
| `linear_slope_hz_per_s` | 中心化一阶最小二乘斜率 | -0.197808 | 慢漂移项 |
| `detrended_std_hz` | `population_std(residual_hz - linear_fit)` | 32.889947 | 去掉一阶趋势后的 std |
| `improvement_ratio` | `(residual_std_hz - detrended_std_hz) / residual_std_hz` | 0.064498 | 去趋势改善比例 |

讲法重点：`9424971` 的 `improvement_ratio` 不大，说明它不是强线性漂移样本，更像弱漂移 / 近常数偏置样本；但它仍是 accepted，因为 RMS 低、点数充足、去趋势后噪声低。

## 7. detrended_residual_summary 指标怎么解释

样本级文件：`bridge/out/9424971/analysis/detrended_residual_analysis_9424971.md`。

逐点去趋势文件：`bridge/out/9424971/analysis/residual_dataset_detrended_9424971.csv`。

总表文件：`bridge/out/detrended_residual_summary.csv`。

脚本：`bridge/scripts/analyze_detrended_residual.py`。

它重新读取 `residual_dataset.csv`，重新拟合同一个中心化一阶模型，然后定义：

```text
detrended_residual_hz = residual_hz - fitted_linear_hz
```

第一行例子：

```text
residual_hz = 92.791000
fitted_linear_hz = 21.150780
detrended_residual_hz = 71.640220
```

`9424971` 的 detrended residual 统计：

| 指标 | 数值 | 含义 |
|---|---:|---|
| `detrended_mean_hz` | 0.000000 | 去趋势 residual 均值 |
| `detrended_std_hz` | 32.889947 | 去趋势 residual 总体标准差 |
| `detrended_rms_hz` | 32.889947 | 去趋势 residual RMS |
| `detrended_min_hz` | -58.556310 | 去趋势 residual 最小值 |
| `detrended_max_hz` | 71.640220 | 去趋势 residual 最大值 |
| `skewness` | 0.187593 | 分布偏度，接近 0 表示左右大致对称 |
| `excess_kurtosis` | -0.836978 | 超额峰度，负值表示比标准高斯更平/尾部更轻 |
| `normality_test_name` | Jarque-Bera | 使用偏度和峰度构造的正态性检验 |
| `JB statistic` | 5.643704 | JB 统计量，样本报告中给出 |
| `normality_p_value` | 0.059496 | 当前规则下判为“近似高斯” |
| `lag1_autocorr` | 0.961303 | 相邻点之间的线性相关很强 |
| `quadratic_improvement_ratio` | 0.546793 | 二阶项对一阶剩余结构仍有明显解释空间 |

quadratic improvement 的脚本定义是：

```text
before = std(detrended)
after = std(detrended - quadratic_fit)
quadratic_improvement_ratio = (before - after) / before
```

## 8. 为什么先做一阶去趋势再讨论高斯性

如果直接对原始 residual 做高斯性判断，会把“慢漂移结构”和“随机噪声形态”混在一起。当前研究要分三层看：

```text
样本级常数偏移：registered_frequency_offset_hz
慢漂移项：linear_slope_hz_per_s
去趋势后噪声项：detrended_residual_hz / detrended_std_hz
```

先做一阶去趋势，是为了把低阶时间结构从 residual 中拿掉，再观察剩余项的边际分布是否接近高斯。

但“边际分布接近高斯”不等于“白噪声”。对 `9424971`：

- `normality_p_value = 0.059496`，`gaussian_like_judgement = 近似高斯`，说明去趋势后残差的分布形状没有明显偏离高斯；
- `lag1_autocorr = 0.961303`，说明相邻 residual 点仍高度相关；
- `quadratic_improvement_ratio = 0.546793`，说明一阶之后仍有可被二阶项解释的时间结构。

所以组会中应这样讲：`9424971` 的去趋势 residual 在边际分布上近似高斯，但时间上不是白噪声，仍建议评估二阶模型。这两句话不矛盾。

## 9. offset 支线：fit_offset_summary.json 从哪里来

`bridge/out/9424971/fit_offset_summary.json` 来自：

```text
bridge/input/rffit_fitline_summary.csv
+ bridge/input/9424971/strf_ready.json:center_freq_hz
-> bridge/scripts/build_fit_offset_summary.py
```

`bridge/input/rffit_fitline_summary.csv` 是 offset 支线当前最原始归档表。按用户说明，它来自 rffit GUI 按 `f` 后终端输出的高精度拟合行，由人工复制整理成 CSV。

`9424971` 在 `rffit_fitline_summary.csv` 中的行是：

```text
9424971,42803,1623.196409,0.035,2024-04-25T17:47:15,9999,24115.530593,161
```

字段为：

```text
observation_id,norad_id,fitted_frequency_mhz,rms_khz,tca_utc,site_id,tle_epoch_yyddd,measurements
```

offset 计算：

| 项 | 数值 | 来源 / 公式 |
|---|---:|---|
| `fitted_frequency_mhz` | 1623.196409 | `rffit_fitline_summary.csv` |
| `fitted_frequency_hz` | 1623196409.0 | `1623.196409 * 1e6` |
| `reference_frequency_hz` | 1623192000.0 | `strf_ready.json:center_freq_hz` |
| `registered_frequency_offset_hz` | 4409.0 | `1623196409.0 - 1623192000.0` |
| `rms_khz` | 0.035 | `rffit_fitline_summary.csv` |
| `measurements` | 161 | `rffit_fitline_summary.csv` |

这个量的解释边界：

- 可以叫 registered frequency offset / effective constant frequency bias / 注册频偏 / 有效常数频率偏置；
- 它表示 rffit Frequency 拟合吸收掉的样本级整体频率平移；
- 不能叫 pure CFO truth、true CFO 或 CFO ground truth；
- 因为它可能混合接收机本振偏差、中心频率设置误差、图像标定误差，以及 TLE / 几何模型误差中被常数项吸收的部分。

## 10. residual 主线和 offset 支线是什么关系

两条线回答的是不同问题：

| 分支 | 核心量 | 回答的问题 |
|---|---|---|
| residual 主线 | `residual_hz`、`linear_slope_hz_per_s`、`detrended_std_hz` | 在 rffit 完成频率注册后，剩余误差随时间怎么变化 |
| offset 支线 | `registered_frequency_offset_hz` | rffit 为了让理论频率曲线对齐观测点，整体平移了多少 |

对 `9424971`，可以这样讲：

- offset 支线给出 `registered_frequency_offset_hz = 4409 Hz`，说明拟合频率相对 `center_freq_hz` 有一个几 kHz 量级的注册偏移；
- residual 主线给出 `residual_std_hz = 35.157545 Hz`、`detrended_std_hz = 32.889947 Hz`，说明注册之后剩余残差是几十 Hz 量级；
- 这两个量不是同一个层级：一个是样本级常数平移，一个是注册之后的逐点剩余误差结构。

因此不能说“offset 大就一定 residual 更乱”。Top10 联合图中也没有观察到 offset 与 `detrended_std_hz` 或 `linear_slope_hz_per_s` 的明显简单线性关系。

## 11. 老师可能追问与回答

### Q1：residual 是不是从 waterfall 图上直接算出来的？

不是。waterfall 图先经过轨迹提取和物理标定得到 physical CSV，再 bridge 到 rffit 输入文件。最终 residual 来自 rffit GUI 按 `j` 导出的 `residuals_rffit.dat`，不是直接从图像像素手算出来的。

### Q2：`residual_dataset.csv` 每一行是什么？

每一行对应 rffit 的一个测量点。它把 normalized CSV 中的时间和观测频率，与 rffit residual 文件中的 residual 对齐，得到 `f_obs_hz`、`f_geo_fit_hz` 和 `residual_hz`。

### Q3：为什么 normalized CSV 和 residuals_rffit.dat 可以对齐？

当前脚本按行对齐，但不是盲信行号。它要求两边行数一致，并用 MJD 容差 `1e-6 day` 和频率容差 `0.1 Hz` 校验；超出容差会报错。

### Q4：`f_geo_fit_hz` 是 rffit 直接导出的吗？

不是直接列在 residual 文件里。脚本用 `f_obs_hz - residual_hz` 反推得到。因此 residual 的符号方向是 `f_obs_hz - f_geo_fit_hz`。

### Q5：为什么 residual 均值接近 0？

因为 rffit 已经做了 Frequency 拟合，整体常数频率平移大多被注册掉了。剩下的 residual 更适合看慢漂移和噪声结构。

### Q6：为什么 `9424971` 的 improvement ratio 不大还算 accepted？

accepted 不是只看 improvement ratio。`9424971` 的 RMS 低、measurements 充足、去趋势后噪声较低，所以适合作为弱漂移 / 近常数偏置类型的主分析池样本。

### Q7：JB p-value 接近 0.05，是不是说明已经是白噪声？

不是。JB p-value 只看边际分布形状。`9424971` 的 `lag1_autocorr = 0.961303`，说明时间上仍然高度相关，所以不能说是白噪声。

### Q8：为什么还要看二阶改善？

一阶去趋势后如果仍有明显时间结构，二阶项是一个最小复杂度扩展。`9424971` 的 `quadratic_improvement_ratio = 0.546793`，说明二阶项可能解释一部分剩余结构，但是否作为默认模型要在 accepted 样本池上统一比较。

### Q9：registered_frequency_offset_hz 是 CFO 吗？

不能这样说。它是 registered offset / effective constant frequency bias，是 rffit 拟合吸收的整体频率平移。它可能包含 CFO，但也可能混入中心频率设置、图像标定、TLE/几何误差等常数项。

### Q10：这套数据为什么不是 AI 编出来的？

因为每一步都有文件来源：rffit GUI 按 `j` 导出的 `residuals_rffit.dat`、bridge 的 `normalized.csv`、脚本生成的 `residual_dataset.csv`、样本级分析报告、summary CSV，以及 offset 支线的人工终端整理表 `rffit_fitline_summary.csv` 和可复现脚本 `build_fit_offset_summary.py`。

## 12. 组会口径总结

可以用这段话收尾：

```text
以 9424971 为例，residual 主线不是从图上凭空估计的，而是从 rffit GUI 按 j 导出的 residuals_rffit.dat 出发，
与 bridge 生成的 normalized.csv 逐行校验对齐，形成 residual_dataset.csv。
后续 residual_std、linear_slope、detrended_std、JB p-value 和 lag1_autocorr 都是从这个标准数据集计算出来的。

offset 支线则来自 rffit 按 f 后终端输出的 fitted frequency，当前最原始归档表是 rffit_fitline_summary.csv。
registered_frequency_offset_hz = fitted_frequency_hz - strf_ready.json:center_freq_hz。
它是有效常数频率偏置，不是纯 CFO 真值。
```

