# Orbit Uncertainty Stage-1E：heterogeneity / causal-regime assessment

状态：`STAGE1E_HETEROGENEITY_CAUSAL_REGIME_ASSESSMENT_COMPLETE`。模型冻结结论：`HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。

## 1. 输入与边界

- Stage-1B canonical dataset：5675行、20星；SHA保持`2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23`。
- primary support：`0 < element age <= 36 h`，共5662行；13行仅保留、不参与正式calibration。
- Stage-1C candidate episode只作为retrospective evaluation label；模型feature不使用SupGP disagreement、最终residual magnitude或future GP。
- SupGP RMS仅标记为`REFERENCE_ONLY` diagnostic，不进入M0–M4 operational candidates。

## 2. Satellite heterogeneity

重点对象的pooled P95诊断（完整数值见CSV）：

```json
{
  "60265": {
    "abs_delta_R_km": {
      "coverage": 0.9298245614035088,
      "excluded": 0.9601449275362319,
      "ratio": 2.498708787993998
    },
    "abs_delta_T_km": {
      "coverage": 0.887719298245614,
      "excluded": 0.9166666666666666,
      "ratio": 4.012614112817917
    },
    "abs_delta_N_km": {
      "coverage": 0.9614035087719298,
      "excluded": 0.9818840579710145,
      "ratio": 1.0042687729625943
    },
    "position_error_norm_km": {
      "coverage": 0.887719298245614,
      "excluded": 0.9166666666666666,
      "ratio": 4.015033992078867
    }
  },
  "48458": {
    "abs_delta_R_km": {
      "coverage": 0.9395017793594306,
      "excluded": 0.9460431654676259,
      "ratio": 1.361138834996436
    },
    "abs_delta_T_km": {
      "coverage": 0.9074733096085409,
      "excluded": 0.9172661870503597,
      "ratio": 2.9592175278499306
    },
    "abs_delta_N_km": {
      "coverage": 0.8790035587188612,
      "excluded": 0.8776978417266187,
      "ratio": 1.457616655477473
    },
    "position_error_norm_km": {
      "coverage": 0.9039145907473309,
      "excluded": 0.9136690647482014,
      "ratio": 2.958496675990328
    }
  },
  "48309": {
    "abs_delta_R_km": {
      "coverage": 0.9316546762589928,
      "excluded": 0.9923076923076923,
      "ratio": 3.3786384004123984
    },
    "abs_delta_T_km": {
      "coverage": 0.9100719424460432,
      "excluded": 0.9730769230769231,
      "ratio": 13.965481299494323
    },
    "abs_delta_N_km": {
      "coverage": 0.9136690647482014,
      "excluded": 0.9730769230769231,
      "ratio": 1.248215808892856
    },
    "position_error_norm_km": {
      "coverage": 0.9100719424460432,
      "excluded": 0.9730769230769231,
      "ratio": 13.959058421772776
    }
  }
}
```

该审计同时按freshness bin与FULL/episode-excluded视图区分稳定scale差异和episode集中效应；未删除canonical rows。

三个重点对象的freshness/publication行为：

|   NORAD |   element_age_median_h |   element_age_p90_h |   publication_age_median_h |   selected_gp_switches |
|--------:|-----------------------:|--------------------:|---------------------------:|-----------------------:|
|   60265 |                10.2481 |             20.6779 |                    3.65111 |                    103 |
|   48458 |                10.9281 |             21.9853 |                    3.74917 |                     94 |
|   48309 |                11.7746 |             23.7512 |                    3.62792 |                    106 |

pooled supported population的element-age median约`11.031 h`、publication-age median约`3.714 h`。60265与48458的freshness分布并未显著偏老，因此undercoverage不能主要归因于freshness-distribution shift。

- 60265：position P95 coverage从`88.772%`在episode-excluded diagnostic中恢复到`91.667%`，说明episode贡献明显，但恢复后仍低于95%，还存在satellite scale成分。
- 48458：从`90.391%`仅恢复到`91.367%`，且N分量没有恢复，主要表现为跨多个freshness bins的稳定satellite-specific scale/shape差异。
- 48309：从`91.007%`恢复到`97.308%`，undercoverage主要由已知连续candidate episode驱动。

## 3. Causal ordinary-GP regime features

特征包括publication age、selected-GP switch、距switch时间、上一发布间隔、GP epoch jump，以及当前GP相对上一已发布GP的mean motion/eccentricity/inclination/RAAN/argument of perigee/mean anomaly/BSTAR变化。所有feature严格由`CREATION_DATE <= evaluation_time`的ordinary GP构造。

时间块causal-logistic diagnostic：

| fold    |   candidate_n |   roc_auc |   average_precision |   candidate_recall_at_threshold |   precision_at_threshold |
|:--------|--------------:|----------:|--------------------:|--------------------------------:|-------------------------:|
| FORWARD |            34 |  0.507276 |           0.0159965 |                       0.0882353 |                0.0107914 |
| REVERSE |            16 |  0.655681 |           0.227482  |                       0.25      |                0.010929  |

最强单变量信号：

| feature                        |   candidate_median |   ordinary_median |   cliffs_delta |   oriented_auc |
|:-------------------------------|-------------------:|------------------:|---------------:|---------------:|
| abs_delta_raan_deg             |         0          |       0.6181      |      -0.300025 |       0.650012 |
| selected_bstar                 |        -0.00116069 |       0.000552546 |      -0.275984 |       0.637992 |
| hours_since_selected_gp_switch |         4.825      |       2.33333     |       0.274836 |       0.637418 |
| publication_age_hours          |         6.26111    |       3.68847     |       0.268881 |       0.63444  |
| selected_eccentricity          |         0.0002057  |       0.00013203  |       0.260745 |       0.630372 |

这些只是“是否存在input-side signal”的诊断，不是confirmed maneuver detector。

Forward AUC接近随机、reverse AUC仅中等，且P90 risk flag precision约1%。因此当前ordinary-GP causal features存在弱关联，但不能稳定、跨时段地 operationally separate Stage-1C candidate regimes。

## 4. Candidate models

- M0：pooled element-age curve。
- M1：M0 × partial-pooled publication-age stratum factor。
- M2：M0 × partial-pooled satellite scale。
- M3：M0 × causal-logistic risk-stratum factor。
- M4：M0 × satellite scale × causal-risk factor。
- M_RMS_DIAGNOSTIC：reference-only RMS quartile sensitivity，不具备operational eligibility。

FULL_SUPPORTED time-block model comparison：

| model   |   mean_abs_calibration_error_components |   per_satellite_mean_abs_calibration_error |   bidirectional_worst_satellite_component_p95_coverage |   special_satellite_position_p95_min_coverage |   p95_timeblock_asymmetry |   loso_component_calibration_error | meets_freeze_screen   |   selection_score |
|:--------|----------------------------------------:|-------------------------------------------:|-------------------------------------------------------:|----------------------------------------------:|--------------------------:|-----------------------------------:|:----------------------|------------------:|
| M4      |                               0.0220821 |                                  0.0578097 |                                               0.859712 |                                      0.918149 |                 0.0238777 |                          0.0372619 | False                 |          0.312059 |
| M3      |                               0.0217692 |                                  0.0523668 |                                               0.859649 |                                      0.859649 |                 0.0295813 |                          0.0357627 | False                 |          0.319854 |
| M2      |                               0.0231572 |                                  0.0562378 |                                               0.882562 |                                      0.921708 |                 0.0371304 |                          0.0373882 | False                 |          0.324942 |
| M1      |                               0.0248732 |                                  0.0546659 |                                               0.875445 |                                      0.875445 |                 0.0458101 |                          0.0376914 | False                 |          0.334069 |
| M0      |                               0.0261637 |                                  0.0552346 |                                               0.875445 |                                      0.875445 |                 0.0507367 |                          0.0374851 | False                 |          0.349994 |

按预先声明的简洁评分，best evaluated candidate=`M4`。M0 component error=`0.026164`，M4=`0.022082`；M0 time asymmetry=`0.050737`，M4=`0.023878`。

三个重点对象的bidirectional time-block position P95 coverage：

|   group_id |       M0 |       M1 |       M2 |       M3 |       M4 |
|-----------:|---------:|---------:|---------:|---------:|---------:|
|      48309 | 0.928058 | 0.92446  | 0.935252 | 0.910072 | 0.935252 |
|      48458 | 0.875445 | 0.875445 | 0.921708 | 0.893238 | 0.918149 |
|      60265 | 0.901754 | 0.898246 | 0.94386  | 0.859649 | 0.936842 |

M2的satellite scale能明显改善60265/48458，但它依赖同一卫星的历史training block，LOSO对未见卫星不能获得该scale；同时其整体per-satellite calibration error未优于M0。M3/M4减少time-block asymmetry，但causal classifier的跨时段识别能力弱，并伴随pinball或worst-component trade-off。因此简单scale可以部分修复已知卫星，但尚未形成同时满足shell transfer、time stability和所有RTN component coverage的冻结模型。

## 5. RMS diagnostic

RMS diagnostic相对M0的最大time-block coverage绝对变化=`0.074885`。它只反映reference-quality stratification可能造成的calibration bias；不会被用于ordinary-GP-only operational model或合法/攻击判别。

| group_id   |   m0_coverage |   rms_adjusted_coverage |
|:-----------|--------------:|------------------------:|
| RMS_Q1     |      0.954873 |                0.946757 |
| RMS_Q2     |      0.963863 |                0.951928 |
| RMS_Q3     |      0.953589 |                0.949362 |
| RMS_Q4     |      0.930194 |                0.941737 |

最高RMS quartile的M0 P95 coverage系统性偏低，但RMS-adjustment在不同target/time block中有时改善、有时恶化，最大变化并非稳定同向。结论是reference quality会影响calibration diagnostic，后续应单独传播；它仍不具备operational covariate资格。

## 6. Velocity parallel descriptive calibration

`componentwise_calibration.csv`保留了`|delta_v_R|/|delta_v_T|/|delta_v_N|`的M0 P90/P95 freshness curves，但本轮model selection只以position RTN为primary，未借此扩展为final full-state set。

## 7. 必答结论

1. 60265属于episode与稳定scale共同作用；48458主要是稳定satellite-specific component scale/shape；48309主要是连续candidate episode。三者均没有证据表明主要由freshness分布或publication cadence差异造成。
2. 简单partial-pooled satellite scale可改善已见卫星的T/position coverage，但不能稳定改善所有RTN分量、LOSO和worst-satellite表现。
3. Causal ordinary-GP features只有弱到中等retrospective association，尚无稳定的residual-independent regime separation。
4. M3/M4降低time-block asymmetry，但没有同时改善per-satellite error、worst component和pinball，因此不能将改善归因于已解决regime。
5. Publication age（M1）带来小幅time-block component-error/pinball改善，但没有修复48458/60265，且LOSO略退化，属于secondary增益而非稳定主增益。
6. RMS分层揭示reference-quality calibration bias，但方向不稳定且不可operationally获得，只能保留为REFERENCE_ONLY diagnostic。
7. 当前不存在满足全部冻结条件的简单component-wise operational model；结论保持`HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。

## 8. 结论边界

最终冻结状态由M0–M4在FULL_SUPPORTED与REGIME_EXCLUDED_SENSITIVITY上的LOSO、连续时间块、逐星和逐freshness-bin结果共同决定。即使某个模型改善平均coverage，也不会通过无限放大pooled envelope掩盖worst-satellite问题。本阶段不生成最终6D uncertainty set、不使用固定km sphere、不分析synthetic B。
