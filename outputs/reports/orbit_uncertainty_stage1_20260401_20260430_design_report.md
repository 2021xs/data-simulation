# Orbit uncertainty Stage-1A：cohort 与 acquisition design

## 1. 状态与边界

状态：`APRIL_DESIGN_FROZEN`。本轮冻结项目既有20颗Starlink的30天 April formal window与72 h causal lookback。当前 April SupGP 已到位并绑定provenance；本脚本不下载SupGP/GP，不计算residual或任何uncertainty threshold。

## 2. 最终cohort

最终对象为项目`controlled_starlink_20target`正式selection中的全部20颗，不加入项目外对象。角色设计为：{'nominal_candidate_pending_stage1b_audit': 17, 'nominal_anchor': 1, 'uncertain_control': 1, 'regime_change_control': 1}。其中65409沿用Stage-0的`nominal-looking`锚点，65410为`uncertain`控制，65411为`possible_regime_change`控制；其余17颗只是`nominal_candidate_pending_stage1b_audit`，不能在取得历史reference之前声称已稳定。

轨道代理范围：倾角53.1557–53.1625°，TLE mean-motion推导的平均高度代理472.542–474.574 km。对象确实集中在项目原有约53.16°、约473 km的单一窄shell；这是selection bias，也是当前论文对象边界，不为“多样性”强加其他shell。

旧本地ordinary GP cache只覆盖7/20颗（65409, 65410, 47749, 65411, 65693, 58380, 48458）且仅为March部分区间，不作为 April formal acquisition。April ordinary GP必须按新窗口另行获取并审核。

## 3. 共同30天窗口

CelesTrak人工请求日期为`2026-04-01`至`2026-04-30`，正式分析采用半开区间`[2026-04-01T00:00:00Z, 2026-05-01T00:00:00Z)`，恰为30天。窗口迁移仅依据reference availability/integrity：当前20颗均覆盖30/30 UTC日，且read-only gate simulation为20/20 READY。未使用RMS大小、residual或uncertainty结果挑选月份。

## 4. Acquisition policy

- CelesTrak：April CSV已到位，当前20 files / 5675 records / 20/20 satellites；逐文件SHA保存于design manifest。
- Space-Track：优先GP_HISTORY OMM JSON；采集`2026-03-29T00:00:00Z`至`2026-05-01T00:00:00Z`，其中窗口前72小时为causal lookback。Stage-0 smoke的最大selected `gp_age`为27.03小时，72小时覆盖其2.6倍以上及多个典型更新周期。若仍无causal GP，则标记`causal_missing`，不使用未来记录。
- evaluation time固定为SupGP epoch；eligible ordinary GP满足`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID降序确定性选择。
- 以每条原生SupGP epoch作为reference observation，不插值成分钟级伪独立样本。如必须传播SupGP，显式保存`supgp_propagation_age_seconds`。

## 5. Regime、freshness与统计独立性

regime只设计三标签框架，不执行正式标注。`possible_regime_change`要求至少两类独立特征在时间上对齐；BSTAR单独跳变不构成maneuver证据。`gp_age_seconds`保持连续，0–6、6–12、12–24、24–48、>48小时只用于描述图表。

nominal主分析计划在coverage gate后分为12颗development/train、3颗calibration、3颗held-out satellite test；65410和65411作为evaluation-only控制。内层以`(satellite_id, ordinary_gp_record/propagation_arc, UTC day)`分组，整条传播arc不跨partition，禁止random row split。

## 6. 进入Stage-1B的条件

April SupGP availability已读取绑定；进入Stage-1B前仍必须完成 April ordinary GP acquisition、全SupGP epoch causal support audit和正式SupGP reference-quality gate。任一环节不足时停在Stage-1A，不用later GP、插值或其他reference补齐。

CelesTrak官方人工请求入口：`https://celestrak.org/NORAD/archives/sup-request.php?FORMAT=csv`；官方SupGP查询/字段说明：`https://celestrak.org/NORAD/documentation/sup-gp-queries.php`。

## 7. 关键文件

- `outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_candidate_audit.csv`
- `outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv`
- `outputs/reports/orbit_uncertainty_stage1_20260401_20260430_celestrak_request.txt`
- `outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_spacetrack_acquisition_plan.csv`
- `outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_design_manifest.json`
