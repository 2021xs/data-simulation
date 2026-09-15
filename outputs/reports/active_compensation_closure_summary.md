# 主动补偿攻击收口实验总结

生成时间：2026-06-09 18:48

## 1. 实验设置

本轮目标是收束主动补偿攻击在当前 Starlink controlled simulation、单公共补偿信号、完整窗口和现有 claimed-identity verifier 参数下的边界。实验继续使用 `controlled_starlink` 思路，不引入真实 SatNOGS Starlink observation replay，也不把 registered offset 表述为真实 CFO。

主要设置：

- residual-mode：`empirical`
- 单站 controlled-R / fine R：`R_km = 0, 1, 2, 5, 10, 20, 30, 40, 50`
- best-C single-station：`search_radius_km = 1, 2, 5, 10, 20, 50`
- best-C exclude-S：`exclude_center_radius_km = 0, 1, 2, 5`
- 双站站距：`50, 100, 200, 500 km`
- 双站攻击策略：`benign_A`, `target_S1`, `service_center`, `two_station_average`, `best_C_two_station`

实际运行说明：

- `python -m py_compile scripts/run_active_compensation_attack_first_pass.py scripts/run_best_C_active_compensation.py scripts/run_multi_receiver_active_compensation_first_pass.py` 通过。
- `best-C` 和 controlled-R 的 10 target x 10 attacker 全量刷新在当前机器上超过 20 分钟，未完成写出；本报告复用仓库中 2026-06-09 已生成的中等规模输出。
- 普通双站 benign/攻击对比已成功刷新为 `max-targets=5`, `max-attackers-per-target=10`。

主要输出文件：

- `outputs/metrics/controlled_R_fine_scan_summary.csv`
- `outputs/metrics/controlled_R_fine_scan_sequence_eval.csv`
- `outputs/metrics/best_C_single_station_summary.csv`
- `outputs/metrics/best_C_single_station_exclude_summary.csv`
- `outputs/metrics/best_C_single_station_exclude_eval.csv`
- `outputs/metrics/multi_receiver_summary.csv`
- `outputs/metrics/best_C_multi_receiver_summary.csv`
- `outputs/reports/active_compensation_closure_summary.md`

## 2. 单站结论

controlled-R / fine R 的 empirical 结果显示，R=0 仍体现单站精确对站补偿的理论上界：`p95_accept_count = 6/6`，score median 约 `26.78 Hz`。但 tri-state 中只有 `2/6` 为 ACCEPT，另有 `3/6` DEFER 和 `1/6` REJECT，说明质量/参数门控仍会影响最终判决。

当补偿参考点偏离真实站后，攻击效果快速下降：

| R_km | n | p95_accept_count | tri_ACCEPT | tri_DEFER | tri_REJECT | score_median_hz | score_p95_hz | delta_rmse_median_hz |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 6 | 6 | 2 | 3 | 1 | 26.78 | 31.02 | 0.00 |
| 1 | 48 | 6 | 0 | 2 | 46 | 39.36 | 65.76 | 123.91 |
| 2 | 48 | 4 | 0 | 0 | 48 | 66.08 | 119.54 | 247.77 |
| 5 | 48 | 0 | 0 | 0 | 48 | 155.23 | 289.35 | 619.43 |
| 10 | 48 | 0 | 0 | 0 | 48 | 307.00 | 575.27 | 1238.85 |
| 50 | 48 | 0 | 0 | 0 | 48 | 1529.14 | 2894.99 | 6193.11 |

best-C single-station 进一步确认了这个边界。允许候选网格包含真实站 S 时，所有 search radius 下最优 C 都回到 S，`best_accept_rate = 0.97`，score median 约 `27.11 Hz`。这不是新的攻击能力，而是单站精确对站补偿的上界复现。

排除真实站附近候选点后，接受率明显下降：

- `search_radius=1 km, exclude=1 km`：`best_accept_rate = 0.10`，score median `41.76 Hz`
- `search_radius=2 km, exclude=1/2 km`：`best_accept_rate = 0.05`，score median `69.76 Hz`
- `search_radius >= 5 km, exclude >= 1 km`：`best_accept_rate = 0.00`，score median 从 `164.69 Hz` 增至 `1576.45 Hz`

因此，在当前实验设置下，单站主动补偿攻击的主要风险来自精确对站补偿；当补偿参考点与真实验证站存在小范围偏差时，攻击效果快速下降。这里的 1/2/5 km 只是当前目标集合、候选集合、网格策略和 verifier 参数下的经验观察，不是普适安全边界。

## 3. 双站结论

普通双站实验成功刷新为 5 targets x 10 attackers，四个站距下每组 `n=50`。合法 `benign_A` 的 pairwise residual 维持在几十 Hz：

- 50 km：median `39.39 Hz`, p95 `45.24 Hz`, both_accept_rate `0.88`
- 100 km：median `39.34 Hz`, p95 `45.21 Hz`, both_accept_rate `0.80`
- 200 km：median `40.40 Hz`, p95 `44.89 Hz`, both_accept_rate `0.70`
- 500 km：median `39.07 Hz`, p95 `43.47 Hz`, both_accept_rate `0.86`

`benign_A` 在 100/200 km 的 both_accept_rate 有下降，但单站 score median 仍约 `27-29 Hz`，pairwise residual 仍为几十 Hz 量级。当前结果更像 station-specific 阈值、经验误差采样和质量门控共同造成的双站同时接受率波动，而不是 pairwise consistency 本身失效。

攻击样本的 pairwise residual 与合法样本明显分离：

- `service_center`：50 km median `3256.73 Hz`，100 km `6712.66 Hz`，200 km `14183.99 Hz`，500 km `39583.69 Hz`
- `target_S1`：pairwise residual 与 service_center 同量级；S1 可接近合法，但 S2 明显失败
- `two_station_average`：score gap 很小，但两站 score 同时升高，pairwise residual 仍为 kHz 到数万 Hz 量级

普通双站攻击策略在 50/100/200/500 km 下均未出现 `both_accept`。

best-C two-station 输出每个站距和搜索半径 `n=100`。结果同样没有 `both_accept`：

- 50 km：best objective median 约 `1.65 kHz`，pairwise residual median `3283.51 Hz`
- 100 km：best objective median 约 `3.41-3.49 kHz`，pairwise residual median `6763.78 Hz`
- 200 km：best objective median 约 `7.18-7.56 kHz`，pairwise residual median `14289.41 Hz`
- 500 km：best objective median 约 `20.60-22.19 kHz`，pairwise residual median `39808.35 Hz`

这说明 best-C 搜索比固定 service_center 更灵活，能在部分半径下降低两站最大 score 或压缩 score gap；但在单公共补偿信号假设下，它没有把攻击带回双站共同接受区。

## 4. 主动补偿攻击边界

本轮结果不说明主动补偿攻击不可能，也不说明多站一定安全。更准确的边界是：

在当前目标集合、攻击源集合、受控 station、完整窗口、经验 residual 模型、单公共补偿信号和现有 verifier 参数下，单站精确对站补偿存在理论上界风险；但固定参考点补偿、排除真实站的 best-C 单站搜索，以及双站公共 best-C 搜索都受到明显限制。

单站风险主要依赖攻击者是否知道并精确对准真实验证站。若攻击者只能在候选区域内搜索补偿参考点，且候选点被排除在真实站附近之外，当前样本中攻击效果明显下降。

双站下，一个公共补偿信号需要同时匹配两个空间分离接收站的几何 Doppler 差异。当前结果显示，合法双站 pairwise residual 是几十 Hz 量级，攻击双站 pairwise residual 是 kHz 到数万 Hz 量级，具有清晰区分度。

短窗口实验只作为收口说明：已有结果提示，局部时间段可能掩盖主动补偿残差，因此最终 ACCEPT 不应仅依赖短窗口；后续可作为窗口长度约束或多窗口一致性验证问题处理。

## 5. 后续方向建议

方向 A：多接收端一致性检测正式化。将 pairwise residual、station-specific fitted parameter consistency 和质量门控组合成明确的双站 verifier，而不是继续扩展 fixed-C 攻击网格。

方向 B：窗口长度感知验证策略。短窗口容易掩盖残差，应研究最小窗口长度、多窗口一致性和完整 pass 覆盖约束，避免把局部可拟合片段误判为完整身份一致。

方向 C：组合物理特征。保留 Doppler residual 主线，同时评估 amplitude、timing、multi-pass consistency 等辅助特征是否能补足单站精确补偿的理论上界风险。

## 6. 结论句

当前主动补偿路线可以收口为：单站精确对站补偿是理论风险上界；不知道精确站点时，best-C 搜索效果明显下降；在单公共补偿信号假设下，双站空间一致性对主动补偿攻击形成强约束，pairwise residual 对合法与攻击样本表现出明显区分度。后续更值得推进的是多接收端一致性检测、窗口长度约束和组合物理特征，而不是继续无限扩展 fixed-C 补偿攻击。
