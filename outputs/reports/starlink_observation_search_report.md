# Starlink SatNOGS Observation 搜索报告

生成时间：2026-05-04 14:34

## 本轮目标

从 `data/tle/starlink_tle.txt` 中抽取前 50 个 Starlink NORAD，调用 SatNOGS Network observations API，寻找真实 Starlink observation。不能使用 `9424971`，不能使用非 Starlink observation。

## 搜索结果

未找到字段完整的真实 Starlink SatNOGS observation。

- API 尝试次数：150
- 保存候选数：0
- 字段完整候选数：0

## API 尝试摘要

```text
https://network.satnogs.org/api/observations/?norad_cat_id=44714&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44714&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44714&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44718&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44718&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44718&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44723&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44723&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44723&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44724&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44724&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44724&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44725&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44725&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44725&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44736&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44736&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44736&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44741&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44741&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44741&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44744&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44744&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44744&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44747&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44747&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44747&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44748&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44748&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44748&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44751&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44751&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44751&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44752&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44752&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44752&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44753&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44753&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44753&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44758&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44758&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44758&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44768&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44768&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44768&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44771&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44771&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44771&vetted_status=good&limit=25 -> 0
https://network.satnogs.org/api/observations/?norad_cat_id=44772&limit=25 -> 0
https://network.satnogs.org/api/observations/?satellite__norad_cat_id=44772&limit=25 -> 25
https://network.satnogs.org/api/observations/?norad_cat_id=44772&vetted_status=good&limit=25 -> 0
ERROR {'norad_cat_id': 44961, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3385 seconds."}
ERROR {'satellite__norad_cat_id': 44961, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3384 seconds."}
ERROR {'norad_cat_id': 44961, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3383 seconds."}
ERROR {'norad_cat_id': 44968, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3382 seconds."}
ERROR {'satellite__norad_cat_id': 44968, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3381 seconds."}
ERROR {'norad_cat_id': 44968, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3380 seconds."}
ERROR {'norad_cat_id': 44941, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3379 seconds."}
ERROR {'satellite__norad_cat_id': 44941, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3378 seconds."}
ERROR {'norad_cat_id': 44941, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3378 seconds."}
ERROR {'norad_cat_id': 58705, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3377 seconds."}
ERROR {'satellite__norad_cat_id': 58705, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3375 seconds."}
ERROR {'norad_cat_id': 58705, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3374 seconds."}
ERROR {'norad_cat_id': 58706, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3374 seconds."}
ERROR {'satellite__norad_cat_id': 58706, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3372 seconds."}
ERROR {'norad_cat_id': 58706, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3371 seconds."}
ERROR {'norad_cat_id': 58709, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3370 seconds."}
ERROR {'satellite__norad_cat_id': 58709, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3370 seconds."}
ERROR {'norad_cat_id': 58709, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3369 seconds."}
ERROR {'norad_cat_id': 58707, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3368 seconds."}
ERROR {'satellite__norad_cat_id': 58707, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3367 seconds."}
ERROR {'norad_cat_id': 58707, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3366 seconds."}
ERROR {'norad_cat_id': 58710, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3365 seconds."}
ERROR {'satellite__norad_cat_id': 58710, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3364 seconds."}
ERROR {'norad_cat_id': 58710, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3364 seconds."}
ERROR {'norad_cat_id': 58708, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3363 seconds."}
ERROR {'satellite__norad_cat_id': 58708, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3362 seconds."}
ERROR {'norad_cat_id': 58708, 'vetted_status': 'good', 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3361 seconds."}
ERROR {'norad_cat_id': 60727, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3360 seconds."}
ERROR {'satellite__norad_cat_id': 60727, 'limit': 25}: 429: {"detail":"Request was throttled. Expected available in 3359 seconds."}
```

## 边界说明

如果候选列表为空或没有完整候选，说明本轮不能生成真实 Starlink SatNOGS observation 条件数据；脚本不会编造 observation，也不会 fallback 到 fixed station。
