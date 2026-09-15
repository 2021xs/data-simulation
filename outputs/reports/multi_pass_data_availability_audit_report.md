# 多过境数据可用性审计报告

## 1. 审计目的与边界

本轮只审计同一物理目标—非目标卫星 pair 的多过境数据可用性，不运行正式 verifier，不生成 observation realization，也不改变 sequence mode、阈值、calibration 口径、轨道传播、fixed-site Doppler 或服务段定义。正式语义保持 `T_service_s=60`、`segment_local`、`fixed_site_segment_center`、`single-window`。

严格区分两类可用 pass：`different_date_tle` 使用仓库已有 Space-Track GP history 中不同日期的真实 TLE 记录；`same_tle_different_pass` 使用主 TLE 在不同绝对时间自动搜索到的过境。没有把 `same_pass_different_segment` 计为跨过境。

## 2. TLE 与 candidate library 现状

- 主 TLE：9818 颗卫星，NORAD 内 epoch 数均为 1；全文件不同 epoch 数为 7855。
- 历史 TLE：7 颗卫星，306 个不同 epoch，7 颗具有至少 2 个 epoch。
- 历史范围：2026-03-01T00:29:24.350208Z 至 2026-03-19T23:45:14.807808Z。
- candidate library manifest：20 个目标；每个目标 pass 数范围 1–1。该 1 GB library 对每个候选重复目标时间网格，且自身没有 `pass_id/elevation_deg`；本审计使用与其配套的正式 selection table 统计 pass 元数据，并校验 library 的目标、候选、绝对时间和几何频率表头。
- 主 TLE 自动搜索：从 2026-03-10T00:00:00Z 起 7 天，elevation mask=10°，scan step=5.0s。

## 3. 当前 20 个 physical pair 的可用性

| physical_pair_id   |   candidate_library_target_pass_count |   same_tle_valid_pass_count |   different_date_tle_valid_pass_count | best_available_pass_source_type   | has_at_least_3_passes   |
|:-------------------|--------------------------------------:|----------------------------:|--------------------------------------:|:----------------------------------|:------------------------|
| 44714->47749       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 44714->65409       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 44714->65410       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 44714->65421       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 44714->65686       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 65409->47383       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65409->47749       |                                     1 |                          35 |                                    88 | different_date_tle                | True                    |
| 65409->48309       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65409->65686       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65410->45230       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65410->47749       |                                     1 |                          35 |                                    88 | different_date_tle                | True                    |
| 65410->65421       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65410->65686       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65421->47749       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65421->65686       |                                     1 |                          35 |                                     0 | same_tle_different_pass           | True                    |
| 65686->44714       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 65686->47749       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 65686->65409       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 65686->65410       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |
| 65686->65421       |                                     1 |                          34 |                                     0 | same_tle_different_pass           | True                    |

结论：2/20 个 pair 可由 `different_date_tle` 提供至少 3 个有效 pass；20/20 个 pair 可由 `same_tle_different_pass` 提供至少 3 个有效 pass；按来源优先级选择后共 20/20 个 pair 可进入至少 3-pass 分析。

## 4. 传播、服务区、服务段与 calibration 复用

pass 搜索直接复用 `audit_target_pass_quality_availability.find_all_passes`，其 elevation 定义与现有 Skyfield pipeline 一致。每个新 pass 用现有 `compute_subpoint_series` 和 `center_track('M2_block', T_service_s=60)` 试构造服务段；有效 pass 至少包含一个完整 60 秒段。验证站为受控 station，服务中心仍由当前 pass 的目标星下点构造。

现有 `calibration_for_trel` 只依赖当前 pass 的 `t_rel`、正式经验参数范围和固定 seed，不依赖旧 candidate library 的特定绝对时间，因此函数可复用；正式实验仍需对每个 geometry-pass 固定 calibration，并进行 current/wide 同拟合审计。

## 5. 缺失 pair / 限制

| physical_pair_id   | missing_data_scope   | blocks_formal_experiment   | missing_reason                      |
|:-------------------|:---------------------|:---------------------------|:------------------------------------|
| 44714->47749       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 44714->65409       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 44714->65410       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 44714->65421       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 44714->65686       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65409->47383       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65409->48309       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65409->65686       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65410->45230       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65410->65421       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65410->65686       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65421->47749       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65421->65686       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65686->44714       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65686->47749       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65686->65409       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65686->65410       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |
| 65686->65421       | different_date_tle   | False                      | different-date TLE valid passes=0<3 |

历史 GP 文件只覆盖 7 个 NORAD ID，因此绝大多数当前 pair 暂不能做 `different_date_tle` 主结论。`same_tle_different_pass` 可以支持机制重复性实验，但只验证同一轨道元素快照传播到不同过境，结论等级低于不同日期真实 TLE。SGP4 外推窗口限制为主 epoch 附近 7 天；没有伪造或平移旧 pass。

## 6. 正确性审计

| check                                   | passed   | observed                                                                                                                                                                                                                                                                                                                                                                                                         | expected                                                                   |
|:----------------------------------------|:---------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------------------------------------------------------------------------|
| pass主键唯一                            | True     | 0                                                                                                                                                                                                                                                                                                                                                                                                                | 0                                                                          |
| same-TLE pass绝对时间真实不同           | True     | {"44714->47749": 35, "44714->65409": 35, "44714->65410": 35, "44714->65421": 35, "44714->65686": 35, "65409->47383": 35, "65409->47749": 35, "65409->48309": 35, "65409->65686": 35, "65410->45230": 35, "65410->47749": 35, "65410->65421": 35, "65410->65686": 35, "65421->47749": 35, "65421->65686": 35, "65686->44714": 34, "65686->47749": 34, "65686->65409": 34, "65686->65410": 34, "65686->65421": 34} | ">=3 unique starts per pair"                                               |
| pass不是同一服务段重复命名              | True     | {"duplicates": 0, "segment_named_passes": 0}                                                                                                                                                                                                                                                                                                                                                                     | {"duplicates": 0, "segment_named_passes": 0}                               |
| different-date TLE epoch记录完整        | True     | "True"                                                                                                                                                                                                                                                                                                                                                                                                           | true                                                                       |
| pair目标和非目标轨道均可传播            | True     | "True"                                                                                                                                                                                                                                                                                                                                                                                                           | true                                                                       |
| pass满足旧elevation和60秒服务段条件     | True     | {"valid_passes": 866, "all_service_reusable": true}                                                                                                                                                                                                                                                                                                                                                              | {"valid_passes": ">0", "all_service_reusable": true}                       |
| 正式实验语义未改变                      | True     | {"mode": "controlled_starlink", "observation_id": null, "T_service_s": 60.0}                                                                                                                                                                                                                                                                                                                                     | {"mode": "controlled_starlink", "observation_id": null, "T_service_s": 60} |
| 未使用伪造TLE且历史数据来自本地下载文件 | True     | {"history_records": 393, "history_file": "data\\tle\\history\\starlink_gp_history_20260301_20260320.csv"}                                                                                                                                                                                                                                                                                                        | "existing local history file"                                              |
| 旧正式输入SHA-256未改变                 | True     | {"selected_conditions": true, "selection_table": true, "tle_file": true, "orbit_config": true, "parameter_config": true}                                                                                                                                                                                                                                                                                         | "all true"                                                                 |
| 20个物理pair已完整建账                  | True     | {"source_pairs": 20, "inventory_pairs": 20}                                                                                                                                                                                                                                                                                                                                                                      | 20                                                                         |
| 不同pass来源类型未混淆                  | True     | ["different_date_tle", "same_tle_different_pass"]                                                                                                                                                                                                                                                                                                                                                                | ["different_date_tle", "same_tle_different_pass"]                          |

审计通过 11/11。失败项数：0。任何失败时不得进入正式实验。

## 7. 是否足以进入正式实验

**数据足以进入正式 smoke/confirmation 实验实现。**

可行时，正式 pair 选择应优先使用具备 `different_date_tle` 的 pair，再补充 `same_tle_different_pass`；报告必须分层呈现，不能把后者写成不同日期 TLE 验证。当前审计只判定数据与公共函数可用，不提前给出跨 pass 风险结论。
