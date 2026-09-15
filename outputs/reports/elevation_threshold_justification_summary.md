# 20° Elevation Threshold Justification Summary

## 1. 问题背景

老师反馈的核心问题是：`20°` 这个低仰角 / 中高仰角分界必须有实验故事，不能只是经验拍脑袋。本轮只复用已有 CSV 做统计汇总，不生成新的 attack observation，不重新设计 verifier，也不改变 b/k/noise 模型。

## 2. 方法

- 使用 `max_elevation_deg` 作为完整过境质量指标。
- 攻击侧读取 完整过境 / 扩展完整过境 / 过境质量感知攻击搜索 结果，并按最大仰角分桶统计接受率。
- 合法侧优先读取 `full_pass_quality_expanded_sequence_eval.csv`，统计不同最大仰角下 score-only 与 score+k gate 接受率。
- 可用性侧读取 300 目标可用性过境明细，在 `5/10/15/20/25/30/35/40°` 候选阈值下重算 7/14/30 天 覆盖率 与 首次合格过境等待时间。
- `20°` 在这里不是物理常数，而是当前 受控地面站 / 目标集合 / 攻击模型 下的经验分界和工程阈值。

## 3. 攻击侧结果

- 低仰角边界故事优先采用 `full_pass_quality_expanded_sequence_eval.csv`，因为该文件覆盖 10-20° 的 低仰角完整过境 样本。
- 高质量攻击搜索补充采用 `pass_quality_aware_attacker_search_sequence_eval.csv`，用于检查 20° 以上候选完整过境上的攻击误接受情况。
- p95、score+k 下，`<20°` 攻击样本接受数为 `50/160`，接受率 `31.25%`。
- p95、score+k 下，`>=20°` 攻击样本接受数为 `0/680`，接受率 `0.00%`。
- 在 `full_pass_quality_expanded_sequence_eval.csv` 中，当候选阈值设为 `20°`，qualified attack sequences = `680`，score-only accept rate = `0.00%`，score+k accept rate = `0.00%`，v3 accept rate = `NA`。
- 在 `pass_quality_aware_attacker_search_sequence_eval.csv` 中，`>=20°` qualified attack sequences = `12600`，score+k / v3 accept rate 分别为 `0.00%` / `0.00%`。
- 对比 `10°` / `15°` / `20°` / `30°`：p95 score+k qualified attack accept rate 分别为 `5.95%` / `3.55%` / `0.00%` / `0.00%`。
- 若某些细分 elevation bin 样本数低于 `--min-bin-count`，CSV 中已用 `low_sample_count` 标注，报告结论不对这些小样本 bin 过度外推。

## 4. 合法侧结果

- p95、`20-25°` 合法样本 score+k accept rate = `NA`，score-only accept rate = `NA`，样本数 `0`。
- p95、`25-30°` 合法样本 score+k accept rate = `90.00%`，样本数 `200`。
- 低仰角合法样本也可能通过 score/k gate，因此低仰角不应直接作为 `REJECT` 证据；更稳妥的协议语义是 `DEFER`：等待更高质量完整过境再认证。

## 5. 可用性侧结果

- 30 天、候选阈值 `10°`：覆盖率 = `300/300` (`100.00%`)，中位等待时间 = `3.60` h，p90 wait = `14.22` h，中位合格过境数 = `146.00`。
- 30 天、候选阈值 `20°`：覆盖率 = `300/300` (`100.00%`)，中位等待时间 = `5.46` h，p90 wait = `16.60` h，中位合格过境数 = `119.00`。
- 30 天、候选阈值 `30°`：覆盖率 = `300/300` (`100.00%`)，中位等待时间 = `6.40` h，p90 wait = `17.43` h，中位合格过境数 = `100.00`。
- 详细 7/14/30 天、各候选阈值结果见 `outputs/metrics/elevation_threshold_availability_tradeoff_300.csv`。

## 6. 为什么当前选择 20°

当前选择 `20°` 的理由不是它具有普适物理常数意义，而是它在本轮数据中同时满足三个工程条件：

1. 低于 `20°` 的区间保留了更多边界样本和攻击误接受风险，适合作为 `DEFER` 区间，而不是强接受候选完整过境。
2. 不低于 `20°` 后，当前 过境质量感知攻击搜索 主结果中的攻击误接受率明显下降或为 0，说明中高仰角完整过境更适合作为强接受候选。
3. 300 目标可用性审计 中，`20°` 仍保持良好可用性；相比把阈值提高到 `30°` 或更高，`20°` 是更偏保留可用性的最低安全阈值。

因此，`20°` 应表述为：在当前 受控地面站、当前 Starlink 目标集合、当前规则化轨道相似攻击模型与当前 残差分数加拟合参数检查验证器 结果下，一个安全性-可用性折中的初步 高质量完整过境阈值。

## 7. 局限性

- `20°` 不是通用物理常数；换地面站、换目标集合、换频段设置、换 pass finder 或换攻击模型，都需要重新校准。
- 当前主动频率补偿攻击尚未纳入该阈值分析。
- 部分 elevation bin 可能样本数有限，已在 CSV 中标注。
- 本轮复用已有结果，不重新生成轨道数据，因此结论边界受已有实验覆盖范围限制。

## 8. 后续工作

- 当前优先把 elevation threshold story 补完整，并用于组会解释 `20°` 的工程依据。
- 主动补偿攻击需要单独做文献调研和攻击能力建模。
- 后续可研究服务区中心补偿到边缘接收端失配的问题，再重新评估 elevation threshold 是否需要变化。

## 9. 输入缺失与替代说明

- 无关键输入缺失；缺失等价文件未影响本轮主统计。

## 10. 关键输出文件

- `outputs/metrics/elevation_threshold_attack_rate_by_bin.csv`
- `outputs/metrics/elevation_threshold_legit_rate_by_bin.csv`
- `outputs/metrics/elevation_threshold_safety_tradeoff.csv`
- `outputs/metrics/elevation_threshold_availability_tradeoff_300.csv`
- `outputs/figures/elevation_threshold_justification/`

_Generated at 2026-05-27 16:25:05 local time._

## 20°阈值的组会解释版本

1. `20°` 不是物理常数，而是当前实验条件下的经验工程阈值。
2. 在困难样本扩展完整过境分析集中，p95 下：
   - `<20°`：`50/160 = 31.25%`
   - `>=20°`：`0/680 = 0.00%`
3. 这说明低仰角完整过境保留明显条件误接受风险，而 `20°` 以上当前没有发现误接受样本。
4. 候选阈值分析显示，`10°` / `15°` 仍保留攻击误接受；从 `20°` 开始，当前数据中的攻击误接受率降为 0。
5. 300 目标可用性审计显示，`20°` 下 30 天覆盖率 = `300/300`，首次合格过境中位等待时间 = `5.46h`，p90 等待时间 = `16.60h`。
6. `30°` / `40°` 虽然也安全，但主要增加等待时间并减少可用过境数量：30° 中位等待时间 = `6.40h`，中位合格过境数 = `100`；40° 中位等待时间 = `7.05h`，中位合格过境数 = `87`。因此当前选择 `20°` 作为更保留可用性的最低安全折中点。
7. 局限性：这不是全局攻击成功率；结论依赖当前受控地面站、目标集合和规则化轨道相似攻击模型；后续若引入主动频率补偿攻击，需要重新校准阈值。

