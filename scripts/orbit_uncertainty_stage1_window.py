"""Shared formal-window definition for the Orbit Uncertainty Stage-1 pilot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


FORMAL_START = "2026-04-01T00:00:00Z"
FORMAL_STOP_EXCLUSIVE = "2026-05-01T00:00:00Z"
GP_ACQUISITION_START = "2026-03-29T00:00:00Z"
GP_ACQUISITION_STOP_EXCLUSIVE = FORMAL_STOP_EXCLUSIVE
LOOKBACK_HOURS = 72.0
WINDOW_TAG = "20260401_20260430"

START_DATE = "2026-04-01"
STOP_DATE = "2026-04-30"
FORMAL_INTERVAL = f"[{FORMAL_START}, {FORMAL_STOP_EXCLUSIVE})"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.rstrip("Z") + "+00:00").astimezone(timezone.utc)


FORMAL_START_DT = _parse_utc(FORMAL_START)
FORMAL_STOP_EXCLUSIVE_DT = _parse_utc(FORMAL_STOP_EXCLUSIVE)
GP_ACQUISITION_START_DT = _parse_utc(GP_ACQUISITION_START)
FORMAL_DURATION_DAYS = int((FORMAL_STOP_EXCLUSIVE_DT - FORMAL_START_DT).total_seconds() / 86400)

if FORMAL_STOP_EXCLUSIVE_DT <= FORMAL_START_DT:
    raise ValueError("Stage-1 formal stop must be later than formal start")
if GP_ACQUISITION_START_DT != FORMAL_START_DT - timedelta(hours=LOOKBACK_HOURS):
    raise ValueError("Stage-1 ordinary-GP acquisition start must equal formal start minus lookback")
if GP_ACQUISITION_STOP_EXCLUSIVE != FORMAL_STOP_EXCLUSIVE:
    raise ValueError("Stage-1 ordinary-GP acquisition stop must equal formal stop")
if WINDOW_TAG != f"{START_DATE.replace('-', '')}_{STOP_DATE.replace('-', '')}":
    raise ValueError("Stage-1 window tag does not match the approved inclusive date labels")
