# 仿真参数范围审查与配置冻结

## 1. 本次统计目的

本轮目标是在不重新运行 rffit、不重新导出 residual、也不重新分层的前提下，基于现有 Top10 分析结果冻结后续 CFO / 频偏仿真所需的三层工程参数范围。
这里的冻结含义是形成一版可复用的配置入口，而不是声称这些范围已经是物理真值或全场景最终边界。

默认工程模型为：

```text
f_obs(t) = f_geo(t) + b + k*(t-t0) + noise
```

## 2. 三类参数含义

- `b`：对应 `registered_frequency_offset_hz`，表示注册频偏 / 有效常数频率偏置。
- `k`：对应 `linear_slope_hz_per_s`，表示 residual 随时间的一阶慢漂移斜率。
- `sigma`：对应 `detrended_std_hz`，表示去掉一阶线性趋势后的 residual 标准差，可作为第一版高斯噪声尺度近似。

## 3. 分层使用方式

- accepted 主分析池：`8535896, 8641460, 8707816, 8733468, 9424971`，用于 main_range 和 typical_value。
- borderline 扩展池：`8493026, 8788317, 8814142, 9462382`，不进入默认 main_range，用于 extended_range / robustness check。
- rejected 异常参考：`8823291`，不参与默认参数统计，只进入 stress/anomaly 说明。

本轮读取的 `sample_tiering_review.csv` 与预期名单一致：5 个 accepted、4 个 borderline、1 个 rejected。

## 4. accepted 主范围结果

- `b` accepted 全范围为 `1980.000 ~ 4409.000 Hz`，median 为 `3365.000 Hz`；main_range 沿用上一版 accepted IQR 推荐 `[3179.0, 3728.0] Hz`。
- `k` accepted 全范围为 `-1.110156 ~ 4.037490 Hz/s`，median 为 `-0.768749 Hz/s`；main_range 沿用负漂移核心推荐 `[-1.110156, -0.197808] Hz/s`。
- `sigma` accepted 全范围为 `10.917 ~ 39.456 Hz`，median 为 `30.882 Hz`；main_range 沿用 accepted 中部推荐 `[23.215, 32.890] Hz`。

## 5. extended / stress 范围结果

- extended_range 使用 accepted + borderline 的全范围，适合做鲁棒性检查；stress_range 使用 Top10 全范围，并把 rejected 样本只作为异常边界参考。
- `b` extended 上端从 accepted 的 `4409 Hz` 扩到 `4692 Hz`，stress_range 与 Top10 全范围一致，为 `1980.000 ~ 4692.000 Hz`。
- `k` extended 下端因 borderline 样本扩到 `-4.052513 Hz/s`；Top10 stress_range 为 `-4.052513 ~ 4.037490 Hz/s`。
- `sigma` extended 上端因 borderline 样本扩到 `55.951 Hz`；rejected `8823291` 将 stress 上端推到 `84.073 Hz`。

## 6. 为什么 registered offset 不能叫 pure CFO

`registered_frequency_offset_hz` 来自 rffit 拟合频率相对 `strf_ready.json:center_freq_hz` 的整体平移。这个量可能混入中心频率设定误差、频率注册过程吸收的常数项、TLE / 轨道模型误差中的常数成分以及观测链路中的其他偏置。因此它适合写成 registered offset 或 effective constant frequency bias，不能写成 true CFO / CFO ground truth。

## 7. 为什么摄动/TLE 误差当前并入 noise/model error

当前 Top10 数据来自公开 waterfall 和既有 rffit/bridge 链路，尚未建立逐项拆分卫星摄动、TLE 误差、站点误差和接收机误差的独立可观测约束。为了避免把不可分辨项硬拆成本轮结论，本阶段统一把未解释结构放入 residual noise / model error，后续如果有更强 metadata 或仿真控制变量，再单独建模。

## 8. 为什么二阶不进入默认模型

accepted 样本上二阶项在部分样本中有额外收益，但收益不完全一致；同时本轮目标是冻结第一版可解释、可控的仿真参数，默认模型保留 `b + k*(t-t0) + noise` 更稳妥。二阶项适合作为 extension_only，用于后续检查线性模型后仍残留明显时间结构的样本。

## 9. 如何基于 YAML 生成仿真数据集

后续生成器应读取 `bridge/out/simulation_parameter_config.yaml`，先选择 `scenarios` 中的实验场景，再按 `parameters` 中的 `main_range` 生成主实验，按 `extended_range` 做鲁棒性实验，按 `stress_range` 做异常/边界压力实验。第一版 noise 可按高斯近似采样 `N(0, sigma^2)`，但报告中应保留“非严格白噪声”的限定，并在后续版本考虑时间相关噪声或模型误差项。

## 10. 输出入口

- 范围统计表：`bridge/out/simulation_parameter_range_review.csv`
- 推荐配置表：`bridge/out/simulation_parameter_config_table.csv`
- YAML 配置：`bridge/out/simulation_parameter_config.yaml`
