# 当前阶段研究收尾草稿

生成时间：2026-06-12 17:30:33

## 1. 当前研究问题

Starlink / LEO Doppler residual claimed-identity verification：在受控 Starlink TLE、受控地面站和合成 residual 参数下，评估单站 Doppler residual claimed-identity verifier 对轨道相似样本、短窗口和固定参考点补偿模型的稳定性边界。

## 2. 已完成实验链条

1. baseline claimed-identity verifier
2. 轨道相似样本测试
3. 短窗口可靠性标定
4. window-aware evidence accumulation
5. hard-case / DEFER 诊断
6. fixed-reference compensation sanity check
7. fixed-reference extended sensitivity
8. original 50 km 口径复现
9. single-station b/k gate ablation
10. multi-station consistency first pass

## 3. 当前核心结论

- 单窗口不可靠，短窗口下更容易出现边界样本。
- 窗口累计能压低普通轨道相似样本的误接受。
- fixed-reference compensation 会显著增加单站验证压力。
- 高接受率主要集中在最难区分样本，不能外推到所有样本。
- b/k 是单站安全边界：no_bk 全拒，current_bk 接受率升高。
- 本轮多站一致性显示，single / dual / three current_bk 接受率分别约为 `0.4574` / `0.2939` / `0.2653`，多站 all-accept 明显降低接受率。

## 4. 当前不能过度声称的内容

- 不能说真实系统一定可被突破。
- 不能说 50 km 或 200 km 是通用安全边界。
- 不能把 hard-case 加权结果推广到所有样本。
- 不能把定位算法结果和参考点误差敏感性混为一谈。
- 当前都是离线仿真压力测试，不接入真实链路，不发射信号，不干扰通信系统。

## 5. 下一阶段建议

如果继续推进，建议优先做更系统的多站布局和站点间距扫描，并把多站可见性、窗口调度与 b/k-risk defer 统一到一个 verifier protocol 中。若多站可用性受限，则需要先研究多站观测窗口调度；若多站 residual 仍有残余接受，则应进一步强化 b/k-risk verifier 或引入更多物理一致性特征。
