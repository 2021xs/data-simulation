# Fit Offset 支线数据血缘与可复现说明

## 1. 这份文件解决什么问题

本文件说明 `registered_frequency_offset_hz` 是怎样从 rffit 终端拟合结果表一步步生成的。

当前 offset 支线的最原始归档文件是：

```text
bridge/input/rffit_fitline_summary.csv
```

按用户说明，这个文件是从 rffit GUI 按 `f` 拟合后终端输出中复制并整理出来的表。它不是 residual 主线脚本推导出来的，也不是 AI 编出来的。

新增复现脚本是：

```text
bridge/scripts/build_fit_offset_summary.py
```

它负责把：

```text
bridge/input/rffit_fitline_summary.csv
+ bridge/input/<obs_id>/strf_ready.json:center_freq_hz
```

重新生成：

```text
bridge/out/fit_offset_summary.csv
bridge/out/<obs_id>/fit_offset_summary.json
```

## 2. 输入文件

### 2.1 `bridge/input/rffit_fitline_summary.csv`

当前字段是：

```text
observation_id
norad_id
fitted_frequency_mhz
rms_khz
tca_utc
site_id
tle_epoch_yyddd
measurements
```

字段含义：

| 字段 | 含义 |
|---|---|
| `observation_id` | SatNOGS observation id |
| `norad_id` | 卫星 NORAD 编号 |
| `fitted_frequency_mhz` | rffit 按 `f` 后终端输出的拟合频率，单位 MHz |
| `rms_khz` | rffit 拟合后的 rms，单位 kHz |
| `tca_utc` | rffit 输出的 TCA 时间 |
| `site_id` | STRF 侧站点编号 |
| `tle_epoch_yyddd` | TLE epoch |
| `measurements` | 参与拟合的点数 |

当前没有单独字段：

```text
raw_terminal_line
source_note
fit_time
```

但这不影响从该表复现 offset summary。它只是说明完整未整理 stdout 文本没有另存为逐样本日志。

### 2.2 `bridge/input/<obs_id>/strf_ready.json`

当前真实参考频率字段名是：

```text
center_freq_hz
```

例如 `9424971` 中：

```text
"center_freq_hz": 1623192000
```

脚本只使用这个字段作为参考频率。如果缺少 `center_freq_hz`，脚本会报错，不会猜其他字段。

## 3. 输出文件

主输出：

```text
bridge/out/fit_offset_summary.csv
```

每个样本的 JSON：

```text
bridge/out/<obs_id>/fit_offset_summary.json
```

如果脚本复现结果和已有 `fit_offset_summary.csv` 不一致，脚本不会直接覆盖旧表，而会生成：

```text
bridge/out/fit_offset_summary_reproduced.csv
bridge/out/fit_offset_summary_diff.md
```

本轮实际运行结果：10 个样本成功复现，和现有 `fit_offset_summary.csv` 一致，没有生成 diff 报告。

## 4. 字段级血缘表

| 输出字段 | 来源文件 | 来源字段 | 计算公式 | 单位 | 说明 |
|---|---|---|---|---|---|
| `observation_id` | `bridge/input/rffit_fitline_summary.csv` | `observation_id` | 直接复制，并与 `strf_ready.json:observation_id` 校验 | id | 防止样本错配 |
| `norad_id` | `bridge/input/rffit_fitline_summary.csv` | `norad_id` | 直接复制 | id | 卫星编号 |
| `site_id` | `bridge/input/rffit_fitline_summary.csv` | `site_id` | 直接复制 | STRF site id | 当前为 `9999` |
| `fitted_frequency_mhz` | `bridge/input/rffit_fitline_summary.csv` | `fitted_frequency_mhz` | 直接复制 | MHz | rffit 按 `f` 后的拟合频率 |
| `fitted_frequency_hz` | `bridge/input/rffit_fitline_summary.csv` | `fitted_frequency_mhz` | `fitted_frequency_mhz * 1e6` | Hz | MHz 转 Hz |
| `reference_frequency_hz` | `bridge/input/<obs_id>/strf_ready.json` | `center_freq_hz` | 直接复制 | Hz | 参考中心频率 |
| `registered_frequency_offset_hz` | fitline CSV + `strf_ready.json` | `fitted_frequency_mhz`, `center_freq_hz` | `fitted_frequency_hz - reference_frequency_hz` | Hz | 注册频偏 / 有效常数频率偏置 |
| `rms_khz` | `bridge/input/rffit_fitline_summary.csv` | `rms_khz` | 直接复制 | kHz | rffit 拟合质量指标 |
| `measurements` | `bridge/input/rffit_fitline_summary.csv` | `measurements` | 直接复制 | count | 参与拟合点数 |
| `tca_utc` | `bridge/input/rffit_fitline_summary.csv` | `tca_utc` | 直接复制 | UTC | rffit 输出时间 |
| `reference_frequency_source` | 脚本生成 | `center_freq_hz` | 固定写为 `bridge/input/<obs_id>/strf_ready.json:center_freq_hz` | text | 明确参考频率来源 |
| `offset_interpretation` | 脚本生成 | 无 | 固定写为 `registered_frequency_offset_hz` | text | 防止误写成 CFO 真值 |

## 5. 9424971 手工复核

| 项 | 数值 | 来源 / 公式 |
|---|---:|---|
| `fitted_frequency_mhz` | 1623.196409 | `bridge/input/rffit_fitline_summary.csv` |
| `fitted_frequency_hz` | 1623196409.0 | `1623.196409 * 1e6` |
| `reference_frequency_hz` | 1623192000.0 | `bridge/input/9424971/strf_ready.json:center_freq_hz` |
| `registered_frequency_offset_hz` | 4409.0 | `1623196409.0 - 1623192000.0` |
| 与输出是否一致 | 是 | `bridge/out/fit_offset_summary.csv` |

## 6. 物理解释边界

`registered_frequency_offset_hz` 表示 rffit 拟合后的频率相对于 metadata 中 `center_freq_hz` 的整体平移量。

适合称为：

```text
registered frequency offset
effective constant frequency bias
注册频偏
有效常数频率偏置
```

不应称为：

```text
true CFO
CFO ground truth
纯 CFO 真值
```

因为它可能混合：

- 接收机本振偏差；
- 中心频率设定误差；
- waterfall 图像频率标定误差；
- TLE / 轨道 / 几何模型误差中被常数项吸收的部分；
- 其他系统性常数频率偏置。

## 7. 当前仍建议补充什么

当前 offset 支线已经具备：

```text
rffit 终端复制整理表
-> 可复现脚本
-> fit_offset_summary.csv
```

如果后续要进一步增强审计力度，可以额外保存每个样本完整的 rffit stdout 日志。但这属于额外归档材料，不改变当前 `rffit_fitline_summary.csv` 作为 offset 支线最原始记录表的地位。
