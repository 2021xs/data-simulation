# Export Manifest

This manifest records where each file in `export_for_simulation_project/` came from and how it should be used in the new simulation / baseline / attack-evaluation project.

No rffit, residual export, tiering, or simulation-generation script was rerun for this package. Files were copied from existing analysis products unless marked as package documentation.

## Package Documentation

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `README.md` | Created for this export package | Entry-point explanation and interpretation boundaries. |
| `MANIFEST.md` | Created for this export package | File provenance and intended use map. |

## Config

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `configs/simulation_parameter_config.yaml` | `bridge/out/simulation_parameter_config.yaml` | Frozen parameter config for `b + k*(t-t0) + noise` simulation scenarios. |

## Residual Datasets

Accepted samples are the default source pool for main simulation-parameter calibration and baseline sanity checks.

| Export path | Source path | Tier | New-project purpose |
| --- | --- | --- | --- |
| `data/source_residual_datasets/accepted/8535896/residual_dataset.csv` | `bridge/out/8535896/residual_dataset.csv` | accepted | Main reference residual sample. |
| `data/source_residual_datasets/accepted/8641460/residual_dataset.csv` | `bridge/out/8641460/residual_dataset.csv` | accepted | Main reference residual sample. |
| `data/source_residual_datasets/accepted/8707816/residual_dataset.csv` | `bridge/out/8707816/residual_dataset.csv` | accepted | Main reference residual sample. |
| `data/source_residual_datasets/accepted/8733468/residual_dataset.csv` | `bridge/out/8733468/residual_dataset.csv` | accepted | Main reference residual sample; includes stronger positive drift endpoint. |
| `data/source_residual_datasets/accepted/9424971/residual_dataset.csv` | `bridge/out/9424971/residual_dataset.csv` | accepted | Main reference residual sample; useful as a cleaner example case. |

Borderline samples are optional robustness-check inputs, not default main-pool samples.

| Export path | Source path | Tier | New-project purpose |
| --- | --- | --- | --- |
| `data/source_residual_datasets/borderline/8493026/residual_dataset.csv` | `bridge/out/8493026/residual_dataset.csv` | borderline | Extended-range / robustness reference. |
| `data/source_residual_datasets/borderline/8788317/residual_dataset.csv` | `bridge/out/8788317/residual_dataset.csv` | borderline | Extended-range / robustness reference. |
| `data/source_residual_datasets/borderline/8814142/residual_dataset.csv` | `bridge/out/8814142/residual_dataset.csv` | borderline | Extended-range / robustness reference. |
| `data/source_residual_datasets/borderline/9462382/residual_dataset.csv` | `bridge/out/9462382/residual_dataset.csv` | borderline | Extended-range / robustness reference; expands negative drift and offset range. |

Rejected samples are anomaly / stress references only.

| Export path | Source path | Tier | New-project purpose |
| --- | --- | --- | --- |
| `data/source_residual_datasets/rejected/8823291/residual_dataset.csv` | `bridge/out/8823291/residual_dataset.csv` | rejected | Stress/anomaly reference; do not use as default main-pool data. |

## Metadata Tables

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `data/metadata/master_sample_summary.csv` | `bridge/out/master_sample_summary.csv` | Joint Top10 table with tier, offset, residual, detrended, and model-comparison fields. |
| `data/metadata/sample_tiering_review.csv` | `bridge/out/sample_tiering_review.csv` | Accepted / borderline / rejected tier labels and review notes. |
| `data/metadata/residual_analysis_summary.csv` | `bridge/out/residual_analysis_summary.csv` | Residual-mainline per-sample summary. |
| `data/metadata/detrended_residual_summary.csv` | `bridge/out/detrended_residual_summary.csv` | Detrended residual metrics including noise scale and temporal-structure hints. |
| `data/metadata/fit_offset_summary.csv` | `bridge/out/fit_offset_summary.csv` | Registered frequency offset branch summary. |
| `data/metadata/simulation_parameter_range_review.csv` | `bridge/out/simulation_parameter_range_review.csv` | Accepted / accepted+borderline / Top10 / rejected parameter statistics. |
| `data/metadata/simulation_parameter_config_table.csv` | `bridge/out/simulation_parameter_config_table.csv` | Main / extended / stress range table for simulation config. |
| `data/metadata/simulation_parameter_recommendations.csv` | `bridge/out/simulation_parameter_recommendations.csv` | Previous accepted-pool recommendation table retained for traceability. |

## Parameter-Range Documents

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `data/parameter_ranges/simulation_parameter_range_review.md` | `bridge/out/simulation_parameter_range_review.md` | Compact parameter statistics table. |
| `data/parameter_ranges/simulation_parameter_config_table.md` | `bridge/out/simulation_parameter_config_table.md` | Human-readable main / extended / stress config table. |
| `data/parameter_ranges/simulation_parameter_recommendations.md` | `bridge/out/simulation_parameter_recommendations.md` | Previous recommendation table retained for comparison and audit. |

## Data Lineage

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `docs/data_lineage/data_lineage_from_rffit_gui_to_analysis_zh.md` | `docs/data_lineage_from_rffit_gui_to_analysis_zh.md` | Chinese data-lineage explanation from rffit GUI export to analysis products. |
| `docs/data_lineage/fit_offset_lineage_and_reproduction_zh.md` | `docs/fit_offset_lineage_and_reproduction_zh.md` | Chinese registered-offset branch provenance and reproduction notes. |

## Reports

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `docs/reports/simulation_parameter_range_review.md` | `codex_workspace/reports/simulation_parameter_range_review.md` | Full Chinese report explaining parameter meanings, tier usage, range choices, and YAML use. |
| `docs/reports/simulation_parameter_recommendations.md` | `codex_workspace/reports/simulation_parameter_recommendations.md` | Earlier accepted-only parameter recommendation report. |
| `docs/reports/accepted_model_comparison.md` | `codex_workspace/reports/accepted_model_comparison.md` | Accepted-pool constant / linear / quadratic model comparison. |

## Group Meeting / Defense Materials

| Export path | Source path | New-project purpose |
| --- | --- | --- |
| `docs/group_meeting_stage5_assets/README.md` | `codex_workspace/reports/group_meeting_stage5_assets/README.md` | Index for stage-5 explanation assets. |
| `docs/group_meeting_stage5_assets/teacher_qa_for_stage5.md` | `codex_workspace/reports/group_meeting_stage5_assets/teacher_qa_for_stage5.md` | Q&A backup for explanations and defense. |
| `docs/group_meeting_stage5_assets/example_9424971_lineage_and_metrics.md` | `codex_workspace/reports/group_meeting_stage5_assets/example_9424971_lineage_and_metrics.md` | Single-sample explanation for residual data chain, metrics, and offset interpretation. |

## Optional File Not Found

| Requested path | Status | Handling |
| --- | --- | --- |
| `codex_workspace/reports/group_meeting_stage5_assets/example_9424971_slide_block.md` | Not found in source repository | Not copied and not fabricated. Use `example_9424971_lineage_and_metrics.md` as the available single-sample explanation material. |

## Recommended First Steps In The New Project

1. Load `configs/simulation_parameter_config.yaml`.
2. Implement scenario selection using `clean`, `offset_only`, `offset_plus_noise`, and `offset_linear_noise`.
3. Use `main_range` for primary simulation data, `extended_range` for robustness checks, and `stress_range` only for anomaly / stress experiments.
4. Build the first residual-minimum matching baseline against simulated and source residual traces.
5. Add attack scenarios after the baseline path is reproducible.

Keep `registered_frequency_offset_hz` named and explained as registered offset / effective constant frequency bias, not as pure CFO ground truth.
