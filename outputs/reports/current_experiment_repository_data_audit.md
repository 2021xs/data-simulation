# 当前实验进度与仓库数据上传审计

审计日期：2026-09-15

远程仓库：`2021xs/data-simulation`

审计性质：只读判定实验权威状态，随后仅调整 Git 跟踪范围；不删除、不重算、不改写实验数据。

## 1. 审计结论

当前项目不能再以 README 中较早的 Verifier v2 fine-sweep/hard-case 阶段作为最新进度。根据 `logs/work_log.md`、最终 manifest、冻结报告与实际 runner 依赖，当前状态分为两层：

1. 2026-09-07 的 joint-security 实验主线已经完成并冻结。orbit-uncertainty 模型优化和 Doppler pipeline 优化均已停止，R4 不需要执行，下一用途是论文和组会综合。
2. 2026-09-14 完成了独立的合法 A 公开轨道误差到 Doppler/OLS Stage-A。该实验没有修改 frozen joint-security population、production verifier、threshold 或 b/k gate。

Stage-A 覆盖 20 颗卫星、696 个 passes、2088 个 segments；April/May 为 exploratory，June 为 protocol 和 population 冻结后的 confirmatory。最终 verdict 为：

```text
GEOMETRY_EFFECT_DOMINATES_OR_INTERACTS_STRONGLY
```

Stage B 值得继续，建议关注 `delta_k, geometry`，但截至本次审计尚未执行。不能把 Stage-A 的增量轨道 disagreement 指标解释为合法卫星 false-reject rate，也不能把 SpaceX-E/SupGP reference 写成 ground truth。

## 2. 本次纳入 GitHub 的数据

### 2.1 Stage-A 当前实验数据

纳入 population、April/May exploratory、June confirmatory、最终合并 segments、freshness/geometry/correlation/replication summary，以及 population/protocol/final/protection manifests。

核心数据包括：

```text
outputs/datasets/orbit_error_to_doppler_legitimate_population.csv
outputs/datasets/orbit_error_to_doppler_legitimate_exploratory_segment_results.csv
outputs/datasets/orbit_error_to_doppler_legitimate_exploratory_timeseries.csv
outputs/datasets/orbit_error_to_doppler_legitimate_june_confirmatory_segment_results.csv
outputs/datasets/orbit_error_to_doppler_legitimate_june_confirmatory_timeseries.csv
outputs/datasets/legitimate_orbit_error_to_doppler_segments.csv
outputs/metrics/orbit_error_to_doppler_legitimate_*.csv
outputs/metrics/legitimate_orbit_error_*.csv
```

### 2.2 当前实验依赖的冻结数据

Stage-A 的保护审计绑定了旧 frozen joint-security 主线中的 52 项文件。为保证当前证据链可核验，本次纳入：

- Causal-A Doppler R2/R3 的 frozen population、observation rows、unit summary、randomness/spotcheck/correctness 数据；
- controlled-altitude、segment-local M2、same-pair multipass 三类 realization dataset；
- orbit-uncertainty final frozen parameters、evidence matrix、stopping criteria；
- orbit-distinct Doppler primary/family/rho99/direction/altitude/multipass/compensation/gate attribution；
- joint-security final authoritative numbers、claim evidence、limitations、terminology 与 figure/table inventory；
- active-compensation first-pass sequence evaluation。

这些文件不是重新启用旧实验，而是当前 Stage-A manifest protection closure 的冻结依赖。

### 2.3 原始和外部输入

Stage-A 直接使用的以下输入此前已经在 Git 中，本次继续保留：

- April/May/June ordinary public GP history；
- April/May/June SpaceX-E/SupGP reference records；
- April cohort satellite selection；
- 受控 station/frequency 逻辑、轨道传播代码和 Doppler/OLS 实现；
- 三个月 Stage-1B reference manifests。

## 3. 本次不上传的数据

仍留在本地、不纳入当前仓库的数据为：

- `archive_controlled_R_v1_3/` 等 archive；
- 文件名和 manifest 明确标记为 smoke 的输出；
- 已被 final/frozen 版本取代的中间 rerun、旧 blocker 和调试输出；
- 早期 single-target/multi-target、Verifier v2 fine sweep、hard-case、candidate library 等不在当前 Stage-A 依赖闭包中的大型生成数据；
- 可由现有输入和 runner 重建、且未被当前 authoritative manifest 引用的时序或候选库。

排除统计：83 个 dataset 文件，约 12395.22 MiB；605 个 metrics CSV，约 373.48 MiB。所有文件仍保留在本地，删除数量为 0。

“未上传”只表示不属于当前可复现实验证据链，不能自动解释为所有历史结果均科学无效；历史报告与图表仍保留用于研究脉络和审计。

## 4. 完整性与上传可行性

- 新纳入数据：54 个文件，281060060 bytes（268.039761 MiB）。
- 最大单文件：81.10 MiB。
- 大于或等于 100 MiB 的文件：0。
- Stage-A manifests 与 protected frozen bindings 的 SHA-256 检查：89 项通过，0 项失败。
- 没有重新运行 verifier v2、visibility diagnostic、orbit propagation、OLS science 或 Monte Carlo。
- 没有修改配置、threshold、seed、population 或实验数值。

机器可读范围记录见：

```text
outputs/metrics/current_experiment_repository_manifest.json
```

## 5. 当前下一步

如果继续科学实验，应先冻结 Stage-B 的 nominal legitimate b/k anchoring 语义和 geometry 分层协议，再决定是否执行 calibration。不能直接把 freshness-only threshold、production b/k gate 或 false-reject endpoint追加到 Stage-A。
