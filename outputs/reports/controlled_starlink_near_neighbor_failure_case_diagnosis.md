# Controlled Starlink Near-neighbor Failure Case Diagnosis

生成时间：2026-05-05 17:00

## 1. 诊断目的

本轮是 Stage 2.5 failure case diagnosis，用于复核 Stage 2 中的负 margin 是否真实可信。当前不是攻击实验，不是攻击成功率，不是 Starlink CFO truth，也不是真实 SatNOGS observation replay。

## 2. 被诊断样本

- sequence_id：`nn_stress_007851`
- target：`STARLINK-1008 / 44714`
- best wrong：`STARLINK-33818 / 63502`
- known neighbor：`STARLINK-35760 / 66274`
- error_model_variant：`frequency_scaled`
- sigma_multiplier：`10.0`
- partial_pass_window：`center_60s`
- scenario：`offset_plus_noise`
- candidate_limit：`1000`
- n_time_points：61
- window_duration_s：60.0
- sim_index：51
- random_seed：42

注意：当前磁盘上的 `matching_results.csv` 全局最小 margin 为 `-205.382989 Hz`。用户背景中提到的 `-543.926064 Hz` 在当前结果文件中不存在，因此本诊断以当前原始 CSV 为准。

## 3. score 复核结论

- true_score_rmse_hz from matcher：2003.204151
- true_score_rmse_hz recomputed：2003.204151
- best_wrong_score_rmse_hz from matcher：1797.821161
- best_wrong_score_rmse_hz recomputed：1797.821161
- known_neighbor_score_rmse_hz from matcher：2049.859853
- known_neighbor_score_rmse_hz recomputed：2049.859853
- margin_hz from matcher：-205.382989
- margin_hz recomputed：-205.382989
- known_neighbor_margin_hz recomputed：46.655702
- recomputed score 与 matcher 输出是否一致：是

best_wrong_score_rmse_hz 并不接近 0；当前最危险样本的 best wrong RMSE 约为 `1797.821161 Hz`。

## 4. 拟合参数

| role | candidate | NORAD | b_hat_hz | k_hat_hz_per_s | rmse_hz | residual_std_hz | delta_std_hz |
|---|---|---|---:|---:|---:|---:|---:|
| `true_44714` | `STARLINK-1008` | `44714` | 23527.779572 | 4.372217 | 2003.204151 | 2003.204151 | 2004.682747 |
| `best_wrong_63502` | `STARLINK-33818` | `63502` | 260818.578485 | -1079.634636 | 1797.821161 | 1797.821161 | 19093.756953 |
| `known_66274` | `STARLINK-35760` | `66274` | 4019.546931 | -459.717457 | 2049.859853 | 2049.859853 | 8349.692747 |

## 5. sanity check 结论

- NORAD 44714 / 63502 / 66274 在 1000-candidate library 中均存在，并且各自覆盖 `61` 个 full-pass/窗口时间点。
- duplicate NORAD-time rows：0
- rounded duplicate curve count：0
- stress sequence 与 candidate library 的 `t_rel_s` 是否对齐：True
- stress sequence 与 candidate library 的 `t_abs_utc` 是否对齐：True
- partial window：`center_60s`，duration=60.0s，n_time_points=61
- candidate library 是否混入 `f_sim_hz` 字段：False
- best wrong `f_geo_candidate_hz` 是否等于 `f_sim_hz`：False
- best wrong NORAD 是否等于 true target：False
- true candidate geometry 与 dataset 的 target geometry 是否一致：True

未发现时间错配、candidate library 混入 `f_sim_hz`、best wrong 与 true target 同 NORAD、或明显数据泄漏迹象。

## 6. 曲线级解释

本样本中 true target 的 residual RMSE 为 `2003.204151 Hz`，best wrong `STARLINK-33818 / 63502` 的 residual RMSE 为 `1797.821161 Hz`。在该短窗口和高噪声设置下，best wrong 的 `delta = f_sim - f_geo_candidate` 经 `b+k` 拟合后残差更小，因此出现负 margin。

known neighbor `66274` 的 RMSE 为 `2049.859853 Hz`，在当前样本中比 best wrong `63502` 更差。因此这条 failure case 的更危险候选是 `63502`，不是 66274。

## 7. 同类 setting 分布

- sequence_count：100
- wrong_count：86
- accuracy：0.140000
- min_margin_hz：-205.382989
- median_margin_hz：-13.557483
- mean_margin_hz：-21.690481
- p05_margin_hz：-63.795080
- margin < 0 数量：86
- best_wrong 为 64732 次数：20
- best_wrong 为 66274 次数：5

best_wrong 分布前 10：

| best_wrong_name | best_wrong_norad_id | count |
|---|---|---:|
| `STARLINK-34596` | `64732` | 20 |
| `STARLINK-34337` | `64223` | 8 |
| `STARLINK-34994` | `65924` | 7 |
| `STARLINK-33845` | `63495` | 7 |
| `STARLINK-34485` | `64684` | 6 |
| `STARLINK-2525` | `48482` | 6 |
| `STARLINK-35297` | `66010` | 5 |
| `STARLINK-35760` | `66274` | 5 |
| `STARLINK-33629` | `63388` | 5 |
| `STARLINK-32596` | `62316` | 3 |

## 8. 结论边界

未发现 bug 时，该 negative margin 可视为 controlled stress 条件下的真实 matcher failure case；它说明 partial window + high noise + large candidate library 会让 profile least-squares residual matcher 失稳。但这不能解释为真实攻击成功率，也不能解释为真实 Starlink CFO 分布。

## 9. 下一步建议

建议进入 partial-pass / time-alignment stress，并将 `STARLINK-33818 / 63502` 与 `STARLINK-35760 / 66274` 一起纳入后续 near-neighbor replay 设计。由于当前文件中的最危险候选不是 64732，后续应先固定当前结果文件版本，再决定攻击候选集合。
