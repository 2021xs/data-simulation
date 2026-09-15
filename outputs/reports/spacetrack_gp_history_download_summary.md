# Space-Track GP_History Download Summary

Generated at: 2026-06-10T15:59:15

## 1. Download Purpose

Download multi-epoch GP/TLE history for selected Starlink NORAD IDs so that later TLE-to-TLE Doppler error calibration can use same-satellite historical records.

## 2. Query Date Range

- start_date: `2026-03-01`
- end_date: `2026-03-20`
- source: Space-Track `gp_history`
- login_success: `true`

Credentials were read from environment variables and are not written to this report.

## 3. Requested NORAD IDs

- requested_count: 7
- requested_ids: `65409, 65410, 65411, 47749, 48458, 58380, 65693`

## 4. Download Results

- NORAD IDs with data: 7
- NORAD IDs with >=2 epochs: 7
- epoch count range: 46 - 65
- median epochs per NORAD: 55.0

Top multi-epoch examples:

|   norad_id |   num_epochs | first_epoch                | last_epoch                 |   num_tle_records | download_status   | error_message   |   sgp4_parse_ok_records |
|-----------:|-------------:|:---------------------------|:---------------------------|------------------:|:------------------|:----------------|------------------------:|
|      65693 |           65 | 2026-03-01T03:25:48.357984 | 2026-03-19T23:45:14.807808 |                72 | ok                |                 |                      72 |
|      65411 |           64 | 2026-03-01T20:24:33.375456 | 2026-03-19T17:25:22.773792 |                68 | ok                |                 |                      68 |
|      65410 |           60 | 2026-03-01T00:29:24.350208 | 2026-03-19T22:00:00.999936 |                65 | ok                |                 |                      65 |
|      65409 |           55 | 2026-03-01T20:37:55.505280 | 2026-03-19T16:03:34.200576 |                61 | ok                |                 |                      61 |
|      47749 |           49 | 2026-03-01T12:01:04.767168 | 2026-03-19T22:00:00.999936 |                54 | ok                |                 |                      54 |
|      48458 |           47 | 2026-03-01T09:54:26.501472 | 2026-03-19T13:35:22.877664 |                55 | ok                |                 |                      55 |
|      58380 |           46 | 2026-03-01T02:47:05.194176 | 2026-03-19T22:00:00.999936 |                56 | ok                |                 |                      56 |

## 5. Output Files

- TLE: `data\tle\history\starlink_gp_history_20260301_20260320.tle`
- CSV: `data\tle\history\starlink_gp_history_20260301_20260320.csv`
- JSON: `data\tle\history\starlink_gp_history_20260301_20260320.json`
- Raw batch JSON: `data\tle\history\starlink_gp_history_20260301_20260320_raw_batches.json`
- Summary CSV: `outputs\metrics\spacetrack_gp_history_download_summary.csv`
- Report: `outputs\reports\spacetrack_gp_history_download_summary.md`

## 6. Rate Limit / Failures

Batch size: 25

Sleep between batches: 3.0 seconds

- No batch failures recorded.

## 7. Next Step

If `NORAD IDs with >=2 epochs` is greater than zero, rerun:

```bash
python scripts/run_tle_error_lower_bound_calibration.py --input-tle-history data\tle\history\starlink_gp_history_20260301_20260320.tle --max-sats 20 --window-duration-s 30 45 60 90 120 180 full --window-position first middle last best_error best_attack --delta-km 0.1 0.2 0.5 1 2 5 10 20 50 100 200 --perturb-direction along_pos along_neg --residual-mode empirical --overwrite
```

Do not compute or report tau_error from single-epoch records.
