# Orbit uncertainty Stage-1A：cohort 与 acquisition design

## 1. 状态与边界

状态：`DESIGN_COMPLETE_ACQUISITION_PENDING`。本轮选定20颗项目既有Starlink，冻结共同28天窗口和采集策略；没有提交CAPTCHA、没有下载正式历史SupGP/GP、没有计算residual或任何uncertainty threshold。

## 2. 最终cohort

最终对象为项目`controlled_starlink_20target`正式selection中的全部20颗，不加入项目外对象。角色设计为：{'nominal_candidate_pending_stage1b_audit': 17, 'nominal_anchor': 1, 'uncertain_control': 1, 'regime_change_control': 1}。其中65409沿用Stage-0的`nominal-looking`锚点，65410为`uncertain`控制，65411为`possible_regime_change`控制；其余17颗只是`nominal_candidate_pending_stage1b_audit`，不能在取得历史reference之前声称已稳定。

轨道代理范围：倾角53.1557–53.1625°，TLE mean-motion推导的平均高度代理472.542–474.574 km。对象确实集中在项目原有约53.16°、约473 km的单一窄shell；这是selection bias，也是当前论文对象边界，不为“多样性”强加其他shell。

本地ordinary GP cache只覆盖7/20颗（65409, 65410, 47749, 65411, 65693, 58380, 48458）且仅为3月上中旬的部分区间。其余对象不是“无GP”，而是`not_cached_stage1a`；完整28天coverage必须在Stage-1B acquisition后逐对象审核。

## 3. 共同28天窗口

CelesTrak人工请求日期为`2026-03-01`至`2026-03-28`，正式分析采用半开区间`[2026-03-01T00:00:00Z, 2026-03-29T00:00:00Z)`，恰为28天。该窗口包含项目正式TLE/pass日期2026-03-10、Stage-0成功SupGP区间2026-03-08至03-14，并与既有ordinary GP cache重叠。它不保证消除maneuver；regime变化必须单独标注。

## 4. Acquisition policy

- CelesTrak：一次CSV人工请求20颗。Stage-0密度19条/7天/星线性外推约76条/星、总计约1520条；仅为容量规划估计。
- Space-Track：优先GP_HISTORY OMM JSON；采集`2026-02-26T00:00:00Z`至`2026-03-29T00:00:00Z`，其中窗口前72小时为causal lookback。Stage-0 smoke的最大selected `gp_age`为27.03小时，72小时覆盖其2.6倍以上及多个典型更新周期。若仍无causal GP，则标记`causal_missing`，不使用未来记录。
- evaluation time固定为SupGP epoch；eligible ordinary GP满足`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID降序确定性选择。
- 以每条原生SupGP epoch作为reference observation，不插值成分钟级伪独立样本。如必须传播SupGP，显式保存`supgp_propagation_age_seconds`。

## 5. Regime、freshness与统计独立性

regime只设计三标签框架，不执行正式标注。`possible_regime_change`要求至少两类独立特征在时间上对齐；BSTAR单独跳变不构成maneuver证据。`gp_age_seconds`保持连续，0–6、6–12、12–24、24–48、>48小时只用于描述图表。

nominal主分析计划在coverage gate后分为12颗development/train、3颗calibration、3颗held-out satellite test；65410和65411作为evaluation-only控制。内层以`(satellite_id, ordinary_gp_record/propagation_arc, UTC day)`分组，整条传播arc不跨partition，禁止random row split。

## 6. 进入Stage-1B的条件

工程设计和人工请求清单已经就绪，但最终20颗能否全部保留仍取决于历史SupGP返回后的逐对象`DATA_SOURCE`、RMS、epoch coverage/gap及ordinary GP causal support审计。若不足20颗满足reference质量，按约定缩减cohort，不用低质量reference补齐。

CelesTrak官方人工请求入口：`https://celestrak.org/NORAD/archives/sup-request.php?FORMAT=csv`；官方SupGP查询/字段说明：`https://celestrak.org/NORAD/documentation/sup-gp-queries.php`。

## 7. 关键文件

- `outputs/metrics/orbit_uncertainty_stage1a_candidate_audit.csv`
- `outputs/metrics/orbit_uncertainty_stage1a_satellite_selection.csv`
- `outputs/reports/orbit_uncertainty_stage1a_celestrak_request.txt`
- `outputs/metrics/orbit_uncertainty_stage1a_spacetrack_acquisition_plan.csv`
- `outputs/metrics/orbit_uncertainty_stage1a_acquisition_manifest.json`
