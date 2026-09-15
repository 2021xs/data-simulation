# 老师可能追问与回答

## 1. residual 是不是从图上直接算的？

不是。图像轨迹先被桥接成 STRF/rffit 可用的观测点，rffit GUI 拟合后导出 residual 文件，后续脚本再把 GUI residual 与 normalized CSV 对齐形成 `residual_dataset.csv`。

## 2. residual_dataset.csv 每一行是什么意思？

每一行是一条 rffit 测量点对应的标准化记录，包含观测时间、观测频率、由 residual 反推的拟合频率，以及 `residual_hz`。

## 3. 为什么 residuals_rffit.dat 和 normalized.csv 可以按行对齐？

当前脚本以 rffit 导出的测量点序列和 bridge normalized 序列为依据，并用 MJD / 频率容差做一致性检查；这不是凭空拼接。

## 4. 为什么要按 `f`？

`f` 是 rffit 的 Frequency 拟合步骤，用来让理论频率曲线与观测频率点在常数频率项上对齐，之后导出的 residual 才更适合分析剩余漂移和噪声。

## 5. 按 `f` 会不会把 CFO 吸掉？

会吸收一个整体常数频率平移，但这个平移不等于纯 CFO；它也可能吸收参考频率设定、图像标定和几何模型误差中的常数部分。

## 6. registered_frequency_offset_hz 是不是 CFO？

不是严格意义的 CFO ground truth。更稳妥的说法是 registered offset 或 effective constant frequency bias。

## 7. 为什么先去趋势再看高斯分布？

原 residual 往往包含慢漂移，直接看分布会把趋势结构混进噪声统计。先去一阶趋势后再看分布，更接近分析短时噪声项。

## 8. Top10 为什么还要分 accepted / borderline / rejected？

Top10 是候选样本池，分层是分析使用优先级。不同样本的 residual 强度、去趋势效果、自相关和二阶改善空间不同，不能同等强度支撑主结论。

## 9. 为什么不直接对 Top10 全部平均？

直接平均会把稳定样本和异常/边界样本混在一起，掩盖模型适用条件。主结论先基于 accepted，borderline 再用于稳健性检查。

## 10. offset 大是否代表 residual 更乱？

当前 Top10 图表没有显示简单线性对应关系。offset、慢漂移和去趋势后噪声更适合分维度建模。

## 11. 下一步为什么要在 accepted 样本上做模型比较？

accepted 样本质量和可解释性更稳定，适合先建立基线模型和参数范围；之后再用 borderline 检查结论是否稳健。
