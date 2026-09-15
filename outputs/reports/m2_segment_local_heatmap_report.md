# M2 Segment-Local Heatmap Report

????? `heatmap_mode` ???????????????????????? fixed-C ????????? controlled segmented service-center compensation simulation????? Starlink beam scheduling / service cell binding / handover policy / ?????????

## 1. ????

- ?? `evaluation_scope=segment_local`?
- ?? `doppler_reference_mode=fixed_site_segment_center`?
- `heatmap_mode + segment_local` ???? `single-window`????? segment ?? evidence?
- ?? heatmap row ?? verifier ???? segment ? `t_rel / y_atk / f_geo_a / coverage_mask`?
- ?? segment ?? `F_A(t;C_i) / F_B(t;C_i) / F_A(t;S) / F_B(t;S)` ???? fixed-site Doppler ???????????
- `sequence_mode` ????

## 2. Targeted run ??

- attack_model: `M0`, `M2_block`
- receiver_mode: `heatmap_mode`
- evaluation_scope: `segment_local`
- doppler_reference_mode: `fixed_site_segment_center`
- R_cell_km: `100`
- alpha: `1.0`
- T_service_s: `60`
- rho: `0`, `0.5`, `1.0`
- phi_deg: `0`, `90`, `180`, `270`
- sample_group: `ordinary_similar`, `boundary_case`
- bk_mode: `current_bk`, `wide_bk`
- verification_strategy: `single-window`
- max_targets: `1`; ?? attacker: `1`; max_heatmap_segments: `3`

## 3. ????

- `rho=0` ?? S-C ???`0 m`?
- ????? segment ????????`0 s`???????`0 s`?
- coverage_valid_fraction ????`1`?coverage_gate_pass?`192/192`?

`rho=0` ??????

| attack_model   |   ('mean_abs_r_geo_hz', 'mean') |   ('mean_abs_r_geo_hz', 'max') |   ('rmse_r_geo_hz', 'mean') |   ('rmse_r_geo_hz', 'max') |   ('max_abs_r_geo_hz', 'mean') |   ('max_abs_r_geo_hz', 'max') |
|:---------------|--------------------------------:|-------------------------------:|----------------------------:|---------------------------:|-------------------------------:|------------------------------:|
| M0             |                     9.32323e-07 |                    9.32323e-07 |                 1.33352e-06 |                1.33352e-06 |                    1.90735e-06 |                   1.90735e-06 |
| M2_block       |                     1.05358e-06 |                    1.15803e-06 |                 1.41601e-06 |                1.48619e-06 |                    1.90735e-06 |                   1.90735e-06 |

## 4. ACCEPT / DEFER / REJECT

| attack_model   |   rho |   ACCEPT |   DEFER |   REJECT |   total |   false_accept_rate |
|:---------------|------:|---------:|--------:|---------:|--------:|--------------------:|
| M0             |   0   |       16 |       0 |        0 |      16 |            1        |
| M0             |   0.5 |        0 |       0 |       16 |      16 |            0        |
| M0             |   1   |        0 |       0 |       16 |      16 |            0        |
| M2_block       |   0   |       40 |       0 |        8 |      48 |            0.833333 |
| M2_block       |   0.5 |        0 |       0 |       48 |      48 |            0        |
| M2_block       |   1   |        0 |       0 |       48 |      48 |            0        |

## 5. ??

`rho=0` ??M2_block ???????????? `1e-6 Hz` ????? fixed-site Doppler ??????`S=C_i` ??????????M2_block ? `rho=0` ??? `40/48` ACCEPT??? `8/48` ? REJECT???? score gate ?????b/k/coverage gate ????

?? `rho` ? `0` ??? `0.5` ? `1.0`?M2_block ??????????? `83.33%` ?? `0%`??? segment-local differential Doppler mismatch ??????????????????????????????????

M0 ? M2 segment-local ???????????????? fixed-C ??????? M0 ?????? pass ??? C0?M2_block ??? 60s ?? block??? M2 ??? block ????????????score/b/k ????? M0 ?????

## 6. ????

- `outputs/datasets/m2_segment_local_heatmap_dataset.csv`
- `outputs/metrics/m2_segment_local_heatmap_summary.csv`
- `outputs/metrics/m2_segment_local_geo_residual_audit.csv`
- `outputs/reports/m2_segment_local_heatmap_report.md`
- `outputs/figures/m2_segment_local_heatmap/rho_accept_rate.png`
