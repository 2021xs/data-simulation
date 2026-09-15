# Doppler verifier module boundary note

## 1. Why split the system into two modules

本轮把当前 Doppler-only residual verifier 实验明确拆成两个逻辑模块：

1. attack observation builder / observation builder
2. claimed identity verifier

这个拆分的核心原因是：攻击源或攻击卫星不会把自己的轨道参数提交给验证器。验证器实际看到的是一条带时间戳的观测频率曲线 `y(t)`、一个声称身份 A、A 的理论 Doppler reference `f_geo_A(t)`，以及 A 的接受阈值 `threshold_A`。

因此，攻击轨道 B、same-plane altitude offset、same-plane phase offset 等参数只属于观测曲线构造阶段。它们用于生成地面站在认证窗口中可能看到的 `y_B(t)`，但不是 verifier 的输入。verifier 只回答一个问题：这条观测曲线是否可以被接受为 claimed target A？

## 2. Attack observation builder

当前 baseline 是：

```text
single-station
+ single-pass full-window
+ controlled Starlink Ku-band frequency
+ rule-based orbit-similar attack source
```

攻击观测曲线构造器负责在 claimed target A 的 pass 时间网格 `t_i` 上生成攻击源 B 的观测曲线：

```text
y_B(t_i) = f_geo_B(t_i) + b_B + k_B(t_i - t0) + noise
```

其中：

- `f_geo_B(t_i)` 是攻击源 B 在 A 的同一个认证窗口和地面站条件下的几何 Doppler 曲线。
- `b_B/k_B/noise` 是观测链路和建模过程中的工程级 effective residual 项。
- `b_B/k_B/noise` 不被解释为攻击源可精确控制的主动频率补偿变量。
- 对攻击样本，输出中的 `f_geo_source_hz` 表示 `f_geo_B(t_i)`，不是 `f_geo_A(t_i)`。

当前脚本中对应的代码边界是：

- `build_legitimate_observation(...)`
- `build_attack_observation(...)`
- `synthetic_same_plane_geo(...)`

其中 `synthetic_same_plane_geo(...)` 使用目标 A 的 mid-pass ECI 状态构造受控 same-plane circular-orbit approximation。`same_plane_altitude_offset` 主要改变轨道半径；`same_plane_phase_offset` 改变沿轨相位/时间偏移。它们是受控近似，不是完整真实 TLE 攻击轨道设计。

## 3. Claimed identity verifier

claimed identity verifier 的输入是：

```text
y(t)
claimed target A
f_geo_A(t)
threshold_A_95 / threshold_A_99
```

它计算：

```text
delta_A(t_i) = y(t_i) - f_geo_A(t_i)
delta_A(t_i) ~= b_hat + k_hat(t_i - t0) + residual_i
score_A = RMSE(residual_i)
```

然后判断：

```text
accepted_95 = score_A <= threshold_A_95
accepted_99 = score_A <= threshold_A_99
```

当前脚本中对应的代码边界是：

- `verify_claimed_identity(...)`
- `fit_bias_and_slope(...)`

`verify_claimed_identity(...)` 不读取攻击轨道 B 的参数，不使用 `f_geo_source_hz` 作为 claimed reference。对攻击样本，它必须计算：

```text
y_B(t_i) - f_geo_A(t_i)
```

而不是：

```text
y_B(t_i) - f_geo_B(t_i)
```

## 4. Protocol-dependent observation output

攻击观测曲线构造器输出什么形式的数据，取决于验证器采用什么认证协议。

当前协议是：

```text
single-station + single-pass full-window
```

因此当前输出是一条完整 pass 的 `y_B(t_i)`。

后续协议可以扩展为：

- 随机子窗口：输出多个子窗口的 `y_B(t_i)`。
- 多次 pass：输出多个 pass 的 `y_B,p(t_i)`。
- 多地面站联合：输出多个地面站各自的 `y_B,s(t_i)`。
- 多站多 pass：输出按 station/pass 分组的观测曲线集合。

这些协议变化应优先体现在 observation builder 输出结构上，而不是让 verifier 直接接收攻击轨道参数。

## 5. Current experiment scope

当前实验只覆盖：

- single-station
- single-pass full-window
- score-only verifier
- per-target threshold
- rule-based orbit-similar attack source
- same-plane altitude offset
- same-plane phase offset
- no real-time orbital maneuver
- no active frequency compensation
- controlled simulation, not real-world RF attack success rate

当前 false accept 结果应解释为：在当前 controlled station / full-pass window / same-plane approximate attack source / score-only verifier 设置下，`score_A <= threshold_A` 的受控仿真比例。它不是现实世界攻击成功率。

## 6. Why this matters

这个拆分可以避免后续实验解释中的几类混淆：

- 把攻击轨道 B 当成 verifier 输入。
- 把攻击源 B 相对 B 自己计算 score，变成“B 像不像自己”的自证循环。
- 误把攻击观测曲线写成 `f_geo_A(t) + b + k + noise`。
- 混淆当前规则化轨道相似攻击和后续主动频率轨迹伪造攻击。
- 混淆观测链路 effective residual 参数和攻击源可控频率补偿参数。

重构后的主脚本保持原实验口径不变，但代码路径更清楚：

```text
build observation y(t)
-> verify y(t) as claimed target A
-> compare score_A with threshold_A
```

回归运行使用独立 `_module_boundary_regression` 输出，未覆盖旧 canonical 输出。回归统计保持一致：

- attack sequences = `2000`
- `same_plane_altitude_offset` = `1000`
- `same_plane_phase_offset` = `1000`
- threshold_95 false accept = `3/2000`
- threshold_99 false accept = `3/2000`
- false accept 全部来自 `same_plane_altitude_offset / delta_h_-5km`
- false accept 样本 `k_hat_hz_s` 范围约为 `-3.317347` 到 `-3.222806` Hz/s
