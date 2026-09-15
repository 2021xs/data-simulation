# AGENTS.md

## 1. 项目定位

本项目位于：

```text
D:/Project/data-simulation/
```

本项目当前用于研究：

> 基于公开 SatNOGS waterfall / STRF rffit 链路提取出的工程级有效频偏参数，结合真实 Starlink TLE、受控地面站和合理 Starlink 频段，构造 controlled orbit-based simulation dataset，并评估多普勒残差方法在 Starlink 近邻匹配、拒绝式身份认证和轨道相似攻击下的稳定性与边界。

当前主线已经从早期的 residual matcher baseline 推进到：

```text
Starlink controlled simulation
→ residual matcher
→ claimed-identity verifier
→ attack observation builder
→ score-only verifier 初测
→ verifier v2: score + fitted-parameter sanity gate + visibility/timing diagnostic
```

当前研究主线不是：

```text
高精度定轨
真实 Starlink SatNOGS observation replay
纯 CFO ground truth 反演
STK / MATLAB 高保真联合仿真
主动补偿攻击完整仿真
多站联合认证完整系统
```

前期 SatNOGS / STRF 工作的作用是提供 effective residual 参数来源；当前 Starlink 阶段的作用是用真实 Starlink TLE 构造受控多目标、多候选、多攻击场景的验证实验。

---

## 2. 核心频偏模型

默认有效频偏模型为：

```text
f_obs(t) = f_geo(t) + b + k(t - t0) + noise
```

其中：

```text
f_geo(t)  : 几何 Doppler / 几何频率基线
b         : effective constant frequency bias / registered frequency offset
k         : linear slow drift, unit = Hz/s
noise     : detrended residual disturbance, first-order Gaussian approximation
```

字段对应关系：

```text
b      = registered_frequency_offset_hz
k      = linear_slope_hz_per_s
sigma  = detrended_std_hz
```

当前主范围约为：

```text
registered_frequency_offset_hz / b:
  main_range: [3179.0, 3728.0] Hz
  typical: 3365.0 Hz

linear_slope_hz_per_s / k:
  main_range: [-1.110156, -0.197808] Hz/s
  typical: -0.768749 Hz/s

detrended_std_hz / sigma:
  main_range: [23.215, 32.890] Hz
  typical: 30.882 Hz
```

必须注意：

- `registered_frequency_offset_hz` 不能写成 `true CFO`、`pure CFO`、`CFO ground truth`。
- 更合适的表述是 `registered offset`、`effective constant frequency bias`、`effective frequency offset`。
- `noise ~ N(0, sigma^2)` 只是第一版工程近似，不代表严格白噪声。
- TLE 误差、站点时钟误差、图像提取误差、标定残差、模型残差等当前统一视作 effective residual / model error 的一部分，除非后续单独建模。
- 当前 baseline 中合法卫星 A 和攻击源 B 都叠加同一类经验误差模型，这是第一版公平基线；不要把 b/k/noise 写成攻击源精确可控变量。

---

## 3. 阶段边界与数据来源

### 3.1 前期 SatNOGS / STRF 阶段

前期真实观测链路为：

```text
SatNOGS waterfall PNG
→ track extraction / calibration
→ track_physical.csv
→ STRF-compatible rffit input
→ rffit GUI: s / f / j
→ residuals_rffit.dat
→ residual_dataset.csv
→ residual_analysis_summary.csv
→ detrended_residual_summary.csv
→ fit_offset_summary.csv
→ master_sample_summary.csv
```

前期筛选出的 Top10 样本包括：

```text
8493026
8535896
8641460
8707816
8733468
8788317
8814142
8823291
9424971
9462382
```

样本分层：

```text
accepted:
  8535896
  8641460
  8707816
  8733468
  9424971

borderline:
  8493026
  8788317
  8814142
  9462382

rejected:
  8823291
```

accepted 样本用于主参数统计；borderline 用于扩展验证；rejected 用于异常或 stress reference。

### 3.2 9424971 的定位

`9424971` 只是前期 SatNOGS / STRF residual 参数提取阶段的高质量样本。

它不参与当前 Starlink controlled simulation 的 observation 设置。

禁止写：

```text
observation_id = 9424971
target = STARLINK-1008
```

当前 Starlink 仿真应保持：

```text
mode = controlled_starlink
observation_id = null
```

如果未来启用真实 SatNOGS Starlink observation replay，则必须满足：

```text
mode = satnogs_observation
observation.norad_id == tle.target_norad_id
```

否则必须停止运行。

### 3.3 当前 Starlink 阶段

当前 Starlink 阶段使用：

```text
真实 Starlink TLE
+ controlled station
+ controlled frequency
+ automatic pass search
```

不是：

```text
真实 SatNOGS Starlink observation replay
```

真实 SatNOGS Starlink observation 后续可以作为 external validation，但不能阻塞当前主线。

---

## 4. 已完成实验状态

### 4.1 早期 pipeline / matcher baseline

已完成：

```text
输入审计
fitted-baseline dataset
fitted-baseline matcher
controlled Starlink single-target baseline
controlled Starlink multi-target baseline
Ku-band frequency variant baseline
near-neighbor / partial-window stress test
```

早期 baseline 只能说明 controlled pipeline 和 matcher sanity check 跑通，不得表述为真实 Starlink observation 已验证或系统已经安全。

### 4.2 从 matcher 到 verifier 的模块边界

当前系统已明确拆分为两个模块。

#### 模块 1：Attack observation builder

职责：生成合法或攻击观测曲线。

相关函数示例：

```text
build_legitimate_observation(...)
build_attack_observation(...)
```

对于攻击样本：

```text
f_geo_source_hz = f_geo_B(t)
y_B(t) = f_geo_B(t) + b_B + k_B(t - t0) + noise
```

这里的 b/k/noise 来自经验误差模型，不视为攻击源精确可控变量。

#### 模块 2：Claimed identity verifier

职责：只判断一条观测曲线是否可以被接受为 claimed target A。

相关函数示例：

```text
verify_claimed_identity(...)
```

它只接收：

```text
y(t)
claimed target A 的 f_geo_A(t)
threshold_A
```

验证器计算：

```text
delta_A(t) = y(t) - f_geo_A(t)
delta_A(t) ≈ b_hat + k_hat(t - t0)
score_A = residual RMSE
```

验证器不会使用 B 的轨道参数，也不会拿 `f_geo_B(t)` 作为 claimed reference。

---

## 5. 5.19 已汇报的 score-only verifier baseline

截至 2026-05-19，已经完成并汇报：

```text
从 Starlink 多普勒残差匹配到拒绝式身份认证：
验证器设计与轨道相似攻击初测
```

已汇报内容包括：

```text
residual matcher → claimed-identity verifier
score-only threshold verifier
attack observation builder / claimed identity verifier 模块边界
single-pass full-window 最小攻击闭环
规则化轨道相似攻击初测
```

当前认证协议：

```text
单站 + 单次完整过境窗口
```

具体含义：

```text
每颗目标 A 选定一个代表性完整 pass
A 的合法样本在这个 pass 时间网格上生成
攻击轨道 B 也在 A 的同一个 pass 时间网格上生成观测曲线
B 声称自己是 A
验证器计算 score_A(B)
```

合法校准规模：

```text
目标卫星数 = 20
合法序列数 = 1000
时序数据行数 = 359900
窗口 = 单次完整过境窗口
误差模型 = main_range
阈值 = 每颗目标卫星独立 p95 / p99
```

攻击实验规模：

```text
攻击序列数 = 2000
时序数据行数 = 719800
same_plane_altitude_offset = 1000
same_plane_phase_offset = 1000
窗口 = 单次完整过境窗口
误差模型 = main_range
```

score-only 结果：

```text
threshold_95 false accept = 3 / 2000 = 0.15%
threshold_99 false accept = 3 / 2000 = 0.15%

same_plane_phase_offset false accept = 0
same_plane_altitude_offset false accept = 3

全部 false accept 来自 same_plane_altitude_offset / delta_h_-5km
false accept k_hat ≈ -3.22 到 -3.32 Hz/s
```

而前期 accepted 主分析池的合法 k 主范围为：

```text
k main_range = [-1.110156, -0.197808] Hz/s
```

当前结论边界：

```text
score-only verifier 能拒绝绝大多数规则化轨道相似攻击；
但只看 residual score 仍不够；
少量 false accept 依赖异常 k_hat 吸收几何差异；
下一阶段必须加入 fitted-parameter sanity gate，并补充 visibility / timing diagnostic。
```

不要再把下一轮任务写成“继续证明 verifier 是什么”。下一轮重点是分析 score-only verifier 的边界并升级 verifier v2。

---

## 6. 当前最重要的下一阶段

当前下一阶段为：

```text
Verifier v2: score threshold + fitted-parameter sanity gate + visibility/timing diagnostic
```

核心问题：

```text
score-only verifier 的边界在哪里？
攻击样本是否可以利用异常 b_hat / k_hat 吸收轨道几何差异？
加入 fitted-parameter sanity gate 后，能否过滤原 3 个 false accepts？
是否会明显误伤合法样本？
visibility / timing 诊断是否支持后续加入前置可见性约束？
```

本阶段不要平均用力。优先顺序：

```text
1. 复现 / 整理 score-only baseline 结果
2. 输出 per-sequence evaluation CSV
3. 实现 score + k_hat / b_hat sanity gate 消融
4. 输出 false accept 明细，检查原 3 个 false accepts 是否被拒绝
5. 补 attack visibility / timing diagnostic
6. 生成组会用图和 verifier_v2_summary.md
```

暂时不要作为主任务：

```text
完整 multi-pass 大规模实验
完整多地面站联合认证
主动频率补偿攻击 u(t) 仿真
约束轨道集合最坏情况搜索
随机子窗口认证完整协议
```

这些作为后续方向保留。

---

## 7. Verifier v2 gate 设计约定

不得破坏原 score-only 逻辑。新增 gate 应作为后处理判决或独立 verifier v2 实验输出。

### 7.1 `score_only`

```text
accepted = score <= threshold
```

### 7.2 `score_plus_global_k_gate`

```text
accepted = score <= threshold AND k_hat in global_k_range
```

默认 global_k_range：

```text
[-1.110156, -0.197808] Hz/s
```

如果工程中已有更正式的 main_range 配置或文件，应优先读取现有配置，并在结果中记录来源。

### 7.3 `score_plus_global_bk_gate`

```text
accepted = score <= threshold
           AND b_hat in global_b_range
           AND k_hat in global_k_range
```

默认 global_b_range 可来自：

```text
registered_frequency_offset_hz main_range = [3179.0, 3728.0] Hz
```

如果工程中找不到 b main_range，不得臆造；应跳过 b gate 或标记为 unavailable，并在 summary 中说明。

### 7.4 `score_plus_per_target_k_quantile_gate`

对每个 target A，用合法样本的 `k_hat` 分布计算 per-target k 范围。

推荐同时输出两版：

```text
[p01, p99]
[p05, p95]
```

判决：

```text
accepted = score <= threshold AND k_hat in target_k_range
```

### 7.5 `score_plus_per_target_bk_quantile_gate`

对每个 target A，用合法样本的 `b_hat` 和 `k_hat` 分布计算 per-target b/k 范围。

判决：

```text
accepted = score <= threshold
           AND b_hat in target_b_range
           AND k_hat in target_k_range
```

如果 b_hat 分布不可用，应说明并输出可用的 k-only 结果。

### 7.6 gate 结果必须回答

```text
score-only 的 3 个 false accepts 是否被 global k gate 拒绝？
是否被 per-target k gate 拒绝？
如果没有被拒绝，原因是什么？
attack false accept rate 从多少变成多少？
legit accept rate 损失多少？
```

---

## 8. Visibility / timing diagnostic 约定

本阶段先做 diagnostic，不要默认作为强 gate。

对每条 attack sequence，尽量输出：

```text
A_window_start_utc
A_window_end_utc
B_visible_fraction_in_A_window
A_B_visibility_overlap_fraction
B_first_visible_utc
B_last_visible_utc
pass_start_offset_s = B_first_visible_utc - A_window_start_utc
pass_end_offset_s = B_last_visible_utc - A_window_end_utc
B_min_elevation_deg_in_A_window
B_max_elevation_deg_in_A_window
B_mean_elevation_deg_in_A_window
```

要求：

- 优先复用现有 station、TLE、SGP4、elevation 计算函数。
- 不要重写一套与项目其他脚本不一致的轨道传播逻辑。
- 如果暂时无法获取完整可见窗口，至少计算 B 在 A 时间网格上的 elevation，并基于 `elevation > 0` 或项目已有 elevation mask 统计 visible fraction。
- 对缺失字段不要静默失败；输出 warning，并在 summary markdown 中说明哪些字段成功、哪些暂不可用。

相位偏移攻击特别需要检查：

```text
B 的可见窗口是否相对 A 前移或后移
B 在 A 的认证窗口内 visible fraction 是否合理
A_B visibility overlap 是否明显下降
```

---

## 9. 当前攻击场景分层

### 第一层：规则化轨道相似发射源

假设存在一个处在攻击轨道 B 上的发射源。B 由 A 的轨道按预设规则扰动得到，例如高度偏移或相位偏移。攻击源不实时调轨，也不主动调频。

当前实验属于这一层。

### 第二层：约束轨道集合中的最坏情况搜索

不是说攻击卫星在 pass 内快速调轨，而是从安全评估角度，在给定约束范围内搜索更危险的 B，例如在高度、相位、倾角、轨道面扰动范围内寻找使 `score_A(B)` 最低的轨道参数组合。

它回答：

```text
在允许的相似轨道范围内，是否存在某些 B 特别容易进入 A 的合法接受域？
```

这可代表攻击方有能力选择某个已有轨道资源，或长期设计接近目标的轨道，但不能表述成“攻击卫星在认证时自主快速调整轨道”。

### 第三层：主动频率轨迹伪造攻击源

攻击源不仅处在某条 B 轨道上，还能主动调节发射频率，使地面站看到的频率轨迹更接近 A。

公式：

```text
f_attack_B(t) = f_geo_B(t) + u(t) + b_env + k_env(t - t0) + noise
```

其中 `u(t)` 是主动频率补偿。

这部分是后续方向，不是当前 verifier v2 实验主任务。

---

## 10. 老师反馈方向：主动补偿与多接收端空间一致性

老师重点讨论了主动频率补偿攻击，认为可以作为后续研究重点。

关键观点：

```text
卫星服务的是一个覆盖区域，不是单个点。
覆盖区域内可能有很多地面站 / 接收端。
攻击源即使能主动补偿，也可能很难选定到底补偿给谁。
```

单站情况下：

```text
f_attack_B(t) = f_geo_B(t) + u(t) + b_env + k_env(t - t0) + noise
```

多接收端情况下：

```text
f_attack_B,s(t) = f_geo_B,s(t) + u(t) + b_env,s + k_env,s(t - t0) + noise_s
```

对于每个站点，理想补偿应为：

```text
u_s(t) = f_geo_A,s(t) - f_geo_B,s(t)
```

不同站点的 `u_s(t)` 通常不完全一致：

```text
u_1(t) ≠ u_2(t) ≠ u_3(t)
```

如果攻击源只有一个统一发射频率补偿 `u(t)`，它可能能骗过某个地面站，但不一定能同时骗过覆盖范围内多个地面站。

后续可以表述为：

```text
主动补偿攻击下的多接收端空间一致性约束
```

这部分可写入后续计划，但当前不要强行实现完整实验。

---

## 11. 目录结构约定

当前项目目录应使用：

```text
data-simulation/
├─ AGENTS.md
├─ README.md
├─ configs/
│  ├─ simulation_parameter_config.yaml
│  └─ orbit_simulation_cases.yaml
├─ data/
│  ├─ tle/
│  │  └─ starlink_tle.txt
│  ├─ source_residual_datasets/
│  │  ├─ accepted/
│  │  ├─ borderline/
│  │  └─ rejected/
│  └─ metadata/
├─ scripts/
├─ outputs/
│  ├─ datasets/
│  ├─ reports/
│  ├─ metrics/
│  ├─ plots/
│  └─ figures/
└─ logs/
   └─ work_log.md
```

如果目录不存在，脚本可以自动创建。

禁止覆盖原始输入数据。

旧 baseline 输出不得删除；新实验输出必须使用带有清晰 stage / variant 的文件名。

---

## 12. Verifier v2 输出文件约定

新增实验优先新增脚本，不要破坏旧脚本。

推荐脚本名：

```text
scripts/evaluate_verifier_v2_gates.py
scripts/diagnose_attack_visibility_timing.py
scripts/plot_verifier_v2_results.py
```

推荐输出：

```text
outputs/metrics/verifier_v2_per_sequence_evaluation.csv
outputs/metrics/verifier_v2_gate_ablation.csv
outputs/metrics/verifier_v2_false_accepts_detail.csv
outputs/metrics/attack_visibility_timing_diagnostic.csv
outputs/metrics/attack_visibility_timing_summary.csv
outputs/reports/verifier_v2_summary.md
outputs/figures/verifier_v2/
```

### 12.1 per-sequence evaluation 字段

至少包含：

```text
sequence_id
target_sat_id
target_name
claimed_sat_id
claimed_name
true_source_sat_id
true_source_name
sample_type              # legit / attack
attack_type
attack_param
threshold_type           # p95 / p99
score
threshold
accepted_score_only
b_hat
k_hat
num_points
window_start_utc
window_end_utc
```

### 12.2 gate ablation 字段

至少包含：

```text
threshold_type
gate_name
sample_group             # legit / attack / attack_type
total_sequences
accepted_sequences
rejected_sequences
false_accepts_for_attack
false_accept_rate_for_attack
legit_accept_rate
notes
```

### 12.3 false accepts detail 字段

至少包含：

```text
sequence_id
target
attack_source
attack_type
attack_param
score
threshold
b_hat
k_hat
accepted_score_only
accepted_score_plus_global_k
accepted_score_plus_per_target_k
accepted_score_plus_global_bk
accepted_score_plus_per_target_bk
rejection_reason_for_each_gate
```

### 12.4 visibility diagnostic 输出

输出：

```text
outputs/metrics/attack_visibility_timing_diagnostic.csv
outputs/metrics/attack_visibility_timing_summary.csv
```

summary 至少包含：

```text
attack_type
attack_param
total_sequences
mean_visible_fraction
median_visible_fraction
mean_overlap_fraction
median_overlap_fraction
mean_pass_start_offset_s
mean_pass_end_offset_s
min_B_max_elevation_deg
median_B_max_elevation_deg
max_B_max_elevation_deg
false_accept_count_score_only
false_accept_count_after_best_gate
```

---

## 13. 图表输出约定

组会用图保存到：

```text
outputs/figures/verifier_v2/
```

至少生成：

```text
score_distribution_legit_vs_attack.png
k_hat_distribution_with_false_accepts.png
gate_ablation_bar.png
visibility_by_attack_type.png
```

图表要求：

- 标题、坐标轴、legend 清楚。
- 适合直接放入组会 PPT 或飞书文档。
- 如果每颗卫星 threshold 不同，score 图优先画 `normalized_score = score / threshold`。
- k_hat 图要标出 global_k_range 和原 score-only false accepts 的 k_hat 位置。
- gate ablation 图要展示不同 gate 下 attack false accepts 数量；合法接受率可另画或在图中标注。

---

## 14. 语言与命名规范

- 研究说明、阶段报告、README 正文、work log 使用中文。
- 代码变量名、字段名、文件名、CLI 参数使用英文。
- 同一概念必须使用稳定字段名，避免混用。

优先字段名：

```text
sequence_id
target_name
target_norad_id
claimed_name
claimed_norad_id
source_name
source_norad_id
sample_type
attack_type
attack_param
threshold_type
score
threshold
normalized_score
accepted_score_only
accepted_by_gate
b_hat_hz
k_hat_hz_per_s
residual_rmse_hz
num_points
window_start_utc
window_end_utc
A_window_start_utc
A_window_end_utc
B_visible_fraction_in_A_window
A_B_visibility_overlap_fraction
pass_start_offset_s
pass_end_offset_s
B_min_elevation_deg_in_A_window
B_max_elevation_deg_in_A_window
B_mean_elevation_deg_in_A_window
random_seed
config_version
```

避免含糊字段名：

```text
cfo
true_cfo
pure_cfo
real_cfo
offset
freq
noise
score
```

如果历史脚本已有这些字段，新增报告时必须解释其含义，后续新代码尽量使用更明确字段名。

---

## 15. 输入数据约定

### 15.1 参数配置

参数配置文件：

```text
configs/simulation_parameter_config.yaml
```

应包含：

```text
registered_frequency_offset_hz
linear_slope_hz_per_s
detrended_std_hz
main_range
extended_range
stress_range
typical
```

### 15.2 TLE

Starlink TLE 文件：

```text
data/tle/starlink_tle.txt
```

脚本应检查：

```text
文件存在
TLE 三行结构合法
target_norad_id 能在 TLE 文件中找到
candidate 数量满足实验需求
```

### 15.3 station

当前 controlled station：

```text
lat = 52.2100
lon = 5.1600
alt = 14 m
```

这个 station 是 controlled experiment station，不是默认真实 Starlink SatNOGS observation station。

### 15.4 frequency

历史 baseline 可能使用：

```text
center_freq_hz = 1623192000
```

Starlink Ku-band 变体使用：

```text
simulation_center_freq_hz = 11325000000
```

候选几何库必须按当前 `simulation_center_freq_hz` 重新计算 Doppler Hz，不能复用错误频率下的 candidate library。

---

## 16. 脚本与命令行规范

脚本必须支持命令行参数。

推荐参数风格：

```bash
python scripts/evaluate_verifier_v2_gates.py \
  --input-dir outputs/metrics \
  --output-dir outputs/metrics \
  --threshold-type p95 \
  --global-k-min -1.110156 \
  --global-k-max -0.197808 \
  --per-target-quantile 0.01 0.99
```

脚本必须：

- 检查输入文件是否存在。
- 检查必要字段是否存在。
- 检查 `mode` 是否符合当前实验。
- 检查 `observation_id` 是否与 mode 一致。
- 检查 target NORAD 是否存在于 TLE。
- 检查 candidate / claimed target reference 是否正确。
- 检查 threshold 类型和来源。
- 检查随机 seed 是否记录。
- 输出清晰错误信息。
- 不静默吞错。
- 默认不覆盖已有结果。
- 写入生成摘要报告或 manifest。

如果运行失败，必须保留错误信息并在日志中说明，不能只写“失败”。

---

## 17. 报告规范

所有报告使用中文正文。

`outputs/reports/verifier_v2_summary.md` 至少包括：

1. 实验目的。
2. 输入数据来源。
3. 复现 baseline：legit sequences 数量、attack sequences 数量、score-only false accepts 数量和来源。
4. gate 设计：score only、global k、global b/k、per-target k、per-target b/k。
5. gate 消融结果：合法接受率、攻击误接受率、原 3 个 false accepts 是否被过滤。
6. visibility / timing diagnostic：高度偏移攻击与相位偏移攻击的可见性差异。
7. 当前可用于组会的结论。
8. 生成的关键文件列表。
9. 局限和下一步计划。

推荐结论句式：

```text
score-only verifier 的主要边界来自拟合自由度过大；少量攻击样本可以依赖异常 k_hat 吸收轨道几何差异。
加入 fitted-parameter sanity gate 后，可以进一步降低轨道相似攻击的误接受风险。
visibility / timing diagnostic 表明，可见窗口一致性适合作为后续 verifier 的前置约束。
```

不得写：

```text
证明 CFO 真值范围
证明攻击一定成功
证明攻击不可能
证明 Starlink Ku-band 真实 CFO 分布
证明噪声是严格高斯白噪声
证明真实 Starlink SatNOGS observation 已复现
系统已经安全
0.15% 是真实世界攻击成功率
```

---

## 18. 日志规范

每次任务结束必须追加：

```text
logs/work_log.md
```

禁止覆盖旧日志。

日志格式：

```markdown
## YYYY-MM-DD HH:MM - <任务名>

### A. 本轮目标
...

### B. 实际操作
...

### C. 新增/修改文件
...

### D. 运行命令
...

### E. 结果摘要
...

### F. 问题与下一步
...
```

日志必须记录：

```text
是否修改配置
是否修改脚本
是否生成新 dataset / metrics / figures / report
是否运行 verifier v2 gate evaluation
是否运行 visibility diagnostic
是否有跳过、异常、失败
关键结果数值
下一步建议
```

---

## 19. 实验顺序约定

当前推荐执行顺序：

### Stage 0. 已完成 baseline 回顾

- 输入审计。
- fitted-baseline dataset。
- fitted-baseline matcher。
- controlled Starlink single-target dataset。
- controlled Starlink multi-target baseline。
- Ku-band frequency variant baseline。
- near-neighbor / partial-window stress test。
- score-only claimed-identity verifier 初测。
- attack observation builder / claimed identity verifier 模块边界重构。

### Stage 1. Verifier v2 gate ablation

当前优先任务。

内容：

```text
复现 / 读取 score-only baseline
生成 per-sequence evaluation CSV
提取所有合法样本和攻击样本的 b_hat / k_hat
比较 score only、global k、global b/k、per-target k、per-target b/k
统计 legit accept rate 和 attack false accept rate
检查原 3 个 false accepts 是否被拒绝
```

### Stage 2. Visibility / timing diagnostic

内容：

```text
计算 B 在 A 认证窗口内的 elevation / visible fraction
统计 A_B visibility overlap
统计 pass_start_offset_s / pass_end_offset_s
按 attack_type / attack_param 汇总
```

### Stage 3. Verifier v2 report and figures

内容：

```text
生成 verifier_v2_summary.md
生成 score / k_hat / gate ablation / visibility 图
追加 logs/work_log.md
```

### Stage 4. Multi-pass validation

后续任务。

目标：

```text
每颗 target 多个 pass
每个 pass 单独校准 threshold
检查阈值和误接受结果是否随过境几何变化稳定
```

### Stage 5. Multi-station / active compensation direction

后续研究方向。

目标：

```text
主动补偿攻击下的多接收端空间一致性约束
比较不同站点理想补偿 u_s(t) 是否一致
评估统一 u(t) 同时骗过多个接收端的难度
```

---

## 20. 验证清单

每轮实验完成前，必须检查：

```text
[ ] 是否使用 controlled_starlink mode
[ ] observation_id 是否为 null
[ ] 是否没有混用 9424971 和 Starlink target
[ ] TLE target 是否存在
[ ] claimed target reference 是否正确
[ ] verifier 是否只使用 y(t)、claimed A、f_geo_A(t)、threshold_A
[ ] verifier 是否没有使用 B 的轨道参数作为判决输入
[ ] score-only baseline 是否可复现或差异已说明
[ ] per-sequence evaluation 是否包含 b_hat / k_hat
[ ] gate ablation 是否同时报告 legit accept rate 和 attack false accept rate
[ ] 原 3 个 false accepts 的新 gate 判决是否单独列出
[ ] visibility diagnostic 缺失字段是否有 warning
[ ] 输出 CSV 是否带表头
[ ] 图表是否保存到 outputs/figures/verifier_v2/
[ ] verifier_v2_summary.md 是否生成
[ ] logs/work_log.md 是否追加记录
[ ] 报告是否写明结论边界
```

---

## 21. 重要禁止事项

禁止：

1. 把 `registered_frequency_offset_hz` 写成 pure CFO truth。
2. 把 `frequency_scaled` 写成真实 Starlink Ku-band CFO 分布。
3. 把 `detrended_std_hz` 写成严格白噪声。
4. 把 `9424971` 写成当前 Starlink observation。
5. 把前期 SatNOGS 参数直接说成 Starlink 真值。
6. 把 controlled baseline accuracy = 1 解释成攻击不可能。
7. 把 3/2000 解释成真实世界攻击成功率。
8. 把 b/k/noise 写成攻击源精确可控参数。
9. 在 verifier 判决中使用 B 的轨道参数。
10. 没有 seed 就生成随机数据。
11. 没有 manifest / summary 就输出 dataset 或 metrics。
12. 覆盖原始输入数据。
13. 覆盖旧 baseline 输出。
14. 覆盖 `logs/work_log.md`。
15. 跳过 baseline 直接宣称 verifier v2 有效。
16. 在当前阶段把主动补偿、多站联合、最坏情况搜索作为必须完成主任务。

---

## 22. 推荐表述

可以写：

```text
前期已从公开 SatNOGS / STRF 样本中提取出工程级 effective residual 参数结构。
当前 Starlink 阶段使用真实 Starlink TLE、受控 station 和受控 frequency 生成 controlled orbit-based dataset。
当前 matcher 是候选轨道条件下的 b+k profile least-squares Doppler matcher。
claimed-identity verifier 不再输出最像哪颗卫星，而是判断观测曲线是否可接受为其声称目标 A。
score-only verifier 已经跑通 single-pass full-window 最小攻击闭环。
当前下一步是加入 fitted-parameter sanity gate，并补充 visibility / timing diagnostic。
```

不能写：

```text
我们得到了 Starlink 的真实 CFO。
frequency_scaled 就是 Starlink Ku-band CFO 真值。
9424971 是 Starlink observation。
accuracy = 1 证明攻击无效。
当前已经验证真实 Starlink SatNOGS observation。
系统已经安全。
0.15% 就是真实攻击成功率。
```

---

## 23. 当前一句话总结

本项目当前阶段的目标是：

> 在已经跑通 Starlink single-pass full-window score-only claimed-identity verifier 的基础上，围绕 3/2000 false accepts 暴露出的异常 fitted k 问题，升级 verifier v2，完成 score + fitted-parameter sanity gate 消融和 visibility / timing diagnostic，为下一次组会提供可复现的 CSV、图表和阶段性结论。