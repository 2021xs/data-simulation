请把当前图2和图3改成“组会简化版”，覆盖现有图片输出。目标是：图不要像论文附录诊断图，而要适合组会汇报，一张图只表达一个核心结论。

当前已有文件：

* scripts/plot_subpoint_failure_evidence.py
* scripts/plot_controlled_R_summary.py
* outputs/charts/figure2_subpoint_failure_evidence.png
* outputs/charts/figure2_subpoint_failure_evidence_notes.md
* outputs/charts/figure3_controlled_R_summary.png
* outputs/charts/figure3_controlled_R_summary_notes.md

请在现有脚本基础上修改并覆盖输出，不要改 verifier 和主实验逻辑。

---

## 一、图2改成“星下点补偿失败的代表性样本图”

### 1. 图2目标

图2只表达一个结论：

> 星下点 C(t) 是移动参考点，对固定验证站 S 来说会形成时变空间失配，因此星下点补偿不能稳定通过验证器。

### 2. 图2结构

请把原来的两联图改成单图，不再画左侧散点图。

保留代表性失败样本曲线，图中只展示：

1. 横轴：相对过境时间，单位秒；
2. 左轴：扣除 b/k 后的残差，单位 Hz；
3. 右轴：S 到 C(t) 的距离，单位 km。

不要再画 raw delta 曲线，避免信息过多。

图例用中文：

* “扣除 b/k 后残差”
* “S 到 C(t) 距离”

### 3. 代表性样本选择

仍然自动选择代表性 subpoint_A 失败样本，优先选择：

* subpoint_A 相比 none 原始几何差距有改善；
* 但验证器分数没有明显改善，甚至更差；
* tri-state 不是 ACCEPT；
* 曲线形态清楚。

如果当前脚本已有样本选择逻辑，可以沿用。

### 4. 图中文字

图标题改为：

```text
图2 星下点补偿导致时变空间失配
```

图内只保留一句核心标注：

```text
移动参考点 C(t) 先远后近再远，残差仍呈时变失配
```

不要在图里显示太多细节，例如：

* sequence_id
* target / attacker 编号
* delta_rmse
* 大段英文
* 大文本框

这些细节可以写到 notes 文件里。

### 5. 图2 notes

请在 notes 中保留统计结果和代表性样本信息，包括：

* 原始几何差距改善比例；
* 验证器分数改善比例；
* 原始改善但分数未改善比例；
* ACCEPT 数；
* DEFER 数；
* 代表性样本 sequence_id、target、attacker、score、tri_state；
* 为什么选择这个样本。

---

## 二、图3改成“受控 R 扫描核心趋势图”

### 1. 图3目标

图3只表达一个结论：

> 攻击者假想服务中心 C 与真实验证站 S 的偏差 R 增大后，攻击效果快速恶化；R=0 是 direct-S 上界，R=50 km 起当前样本全部拒绝。

### 2. 图3结构

请把原来的两联图改成单图，不再画 ACCEPT/DEFER/REJECT 堆叠柱。

只画：

* 横轴：补偿参考点距离 R，单位 km；
* 纵轴：验证器分数，单位 Hz；
* 曲线：score 中位数。

可选：如果不显得乱，可以用浅色阴影或误差棒展示 p95；如果影响简洁，就不要画 p95，只在 notes 中写。

### 3. 横轴必须改成离散类别轴

不要按真实数值线性缩放，因为 0、50、100、200 会挤在左边。

请把横轴改成等间距类别轴：

```text
0, 50, 100, 200, 500
```

组会图只保留到 500 km 即可。1000 和 2000 的结果可以写在 notes 中，不放图里。

### 4. 图中文字

图标题改为：

```text
图3 假想服务中心偏差使攻击效果快速下降
```

图内只保留两处标注：

```text
R=0：direct-S 上界
```

```text
R≥50 km：当前样本全部拒绝
```

不要放太多解释文字。

图例用中文：

* “验证器分数中位数”

如果画 p95，则图例用：

* “验证器分数中位数”
* “95 分位”

### 5. 图3 notes

请在 notes 中写清楚：

* R=0 等价于 C=S，即 direct-S 上界；
* R=50 km 起当前样本全部 REJECT；
* 这不是普适 50 km 安全边界，只是当前目标集合、攻击源集合、验证器参数和过境窗口下的观察；
* 1000/2000 km 没放入组会图，是因为它们对“近距离边界”解释帮助不大，且会拉伸横轴；
* 如有 p95 和判决统计，请写入 notes。

---

## 三、输出要求

请覆盖生成：

```text
outputs/charts/figure2_subpoint_failure_evidence.png
outputs/charts/figure2_subpoint_failure_evidence_notes.md
outputs/charts/figure3_controlled_R_summary.png
outputs/charts/figure3_controlled_R_summary_notes.md
```

请运行：

```bash
python -m py_compile scripts/plot_subpoint_failure_evidence.py
python -m py_compile scripts/plot_controlled_R_summary.py
python scripts/plot_subpoint_failure_evidence.py
python scripts/plot_controlled_R_summary.py
```

如果当前数据缺失导致图2无法生成，请不要重跑主实验，先汇报缺什么数据。
如果数据存在，请直接覆盖生成正式组会简化图。

---

## 四、最终汇报

完成后请给我：

1. 修改了哪些脚本；
2. 图2是否成功覆盖；
3. 图3是否成功覆盖；
4. 图2使用的代表性样本信息；
5. 图3实际绘制的 R 列表；
6. notes 中保留了哪些统计信息；
7. 如果遇到字段名不一致，说明你如何适配。
