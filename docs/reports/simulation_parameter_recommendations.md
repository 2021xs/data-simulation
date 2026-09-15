# Simulation Parameter Recommendations Report

## 当前支持的仿真骨架

- 基于 accepted 主分析池，当前默认更支持：

```text
f_obs(t) = f_geo(t) + b + k (t - t0) + noise
```

- 原因是 accepted 样本上的正式模型比较已经说明：常数模型不够，一阶模型应作为默认基线。
- 二阶项在部分 accepted 样本上确实能带来额外收益，但收益不完全一致，因此当前更适合作为扩展模型，而不是统一默认项。

## 参数建议解释

- `registered_frequency_offset_hz`：主范围建议 [3179.0, 3728.0] Hz，扩展范围建议 [1980.0, 4409.0] Hz，典型值建议 3365.0 Hz。主范围偏向 accepted 样本中部代表区间，扩展范围保留 accepted 全范围。
- `linear_slope_hz_per_s`：主范围建议 [-1.110156, -0.197808] Hz/s，扩展范围建议 [-1.110156, 4.037490] Hz/s，典型值暂以 -0.768749 Hz/s 作为负漂移核心代表值，但不建议把该参数压成单一值。原因是分布明显不对称，accepted 样本里既有负漂移核心，也有正向强漂移端点。
- `detrended_std_hz`：主范围建议 [23.215, 32.890] Hz，扩展范围建议 [10.917, 39.456] Hz，典型值建议 30.882 Hz。主范围更代表 accepted 样本的大多数噪声落点。

## 为什么这样分主范围 / 扩展范围

- 主范围：优先服务主实验，应更偏向 accepted 样本的核心代表区间，而不是把边缘值一开始就并入默认设置。
- 扩展范围：用于鲁棒性实验与边界压力测试，因此更接近 accepted 样本全范围。
- 这种分法的目的是先让主实验更稳定可解释，再逐步检验模型在更宽参数区间下是否依然稳健。

## 后续仿真的分层使用建议

- 主实验：优先使用三项参数的 `recommended_main_range`，并以一阶骨架 `b + k(t-t0) + noise` 为默认方案。
- 鲁棒性实验：放宽到 `recommended_extended_range`，检验常数偏移、慢漂移和噪声同时放宽后模型表现是否稳定。
- 边界压力测试：重点对 `linear_slope_hz_per_s` 的强正漂移端和 `registered_frequency_offset_hz` / `detrended_std_hz` 的 accepted 边缘值做组合压力测试。

## 模型与参数的对应关系

- 常数项 `b`：对应 `registered_frequency_offset_hz`，应解释为工程有效常数频移候选，而不是纯 CFO 真值。
- 一阶项 `k`：对应 `linear_slope_hz_per_s`，是当前 accepted 主分析池最值得保留的慢漂移项。
- 噪声项 `noise`：当前用 `detrended_std_hz` 约束其量级最合理。
- 二阶扩展：当前更适合在 `8535896, 8641460, 8733468, 9424971` 这类样本对应的扩展实验中评估；`8707816` 更适合作为一阶基线稳健样本。

## 再次说明

- `registered_frequency_offset_hz` 是 registered / effective constant frequency bias 候选量。
- 它不能直接写成纯 CFO 真值，因为其中仍可能混入中心频率设定误差、轨道/TLE 误差以及其他被拟合吸收的常数项。
