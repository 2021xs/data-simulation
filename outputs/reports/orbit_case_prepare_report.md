# Orbit Simulation Case 准备报告

生成时间：2026-05-04 10:12

## 本轮目标

优先使用本地迁移文件，其次使用 SatNOGS Network API，准备真实 SatNOGS observation 条件下的 orbit simulation 配置。本轮不生成仿真数据，不做攻击场景。

## 尝试记录

- `9424971`: source=local_strf_ready, missing=['strf_ready.json'], note=本地优先路径未找到 strf_ready.json/catalog.tle
- `9424971`: source=satnogs_api, missing=[], note=

## 实际字段详情

### observation_id `9424971` / `satnogs_api`

- API / 文件实际字段：`archive_url, archived, center_frequency, client_metadata, client_version, demoddata, end, ground_station, id, max_altitude, norad_cat_id, observation_frequency, observer, payload, rise_azimuth, sat_id, set_azimuth, start, station_alt, station_lat, station_lng, station_name, status, tle0, tle1, tle2, tle_source, transmitter, transmitter_baud, transmitter_description, transmitter_downlink_drift, transmitter_downlink_high, transmitter_downlink_low, transmitter_invert, transmitter_mode, transmitter_status, transmitter_type, transmitter_unconfirmed, transmitter_updated, transmitter_uplink_drift, transmitter_uplink_high, transmitter_uplink_low, transmitter_uuid, vetted_datetime, vetted_status, vetted_user, waterfall, waterfall_status, waterfall_status_datetime, waterfall_status_user`
- station 字段来源：`observation_api`
- frequency 字段来源：`observation_frequency`
- TLE 字段来源：`satnogs_api`
- 是否调用 station API：`False`



## 最终配置摘要

- observation_id：`9424971`
- observation 条件来源：`satnogs_api`
- station 字段来源：见尝试记录；最终 station_id=`3299`，lat=52.21，lon=5.16，alt=14.0 m
- frequency 字段来源：见尝试记录；最终 center_freq_hz=`1623192000`
- TLE 字段来源：`satnogs_api`
- target：`IRIDIUM 113`
- NORAD ID：`42803`
- start/end：`2024-04-25T17:44:54Z` 至 `2024-04-25T17:49:35Z`
- duration_s：`281.0`
- 是否真正使用 SatNOGS observation 条件：是
- 是否使用 fallback：否
- 输出配置：`configs\orbit_simulation_cases.yaml`
- 备份文件：`configs\orbit_simulation_cases.yaml.bak_20260504_101201`


## 缺失字段或异常字段

若某次尝试的 `missing` 非空，表示该来源不能单独构成真实 observation 配置。API 返回字段名如与预期不同，以尝试记录中的 actual_fields 为准；本报告不编造字段。

## 边界说明

- `registered_frequency_offset_hz` 后续只作为 registered offset / effective constant frequency bias，不是 pure CFO truth；
- 如果 observation 条件来自 `satnogs_api` 或 `local_strf_ready`，后续生成报告应写明使用真实 SatNOGS observation 条件；
- 如果最终为 `fallback_manual`，必须写明本轮没有使用真实 SatNOGS observation 条件。
