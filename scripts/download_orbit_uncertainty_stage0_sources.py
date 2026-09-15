#!/usr/bin/env python
"""Acquire only the raw sources required by the orbit-uncertainty Stage-0 smoke.

Secrets are read from process environment variables and are never serialized.
CDSE access tokens remain in memory. Existing raw files are reused, not downloaded
again, unless their recorded product is absent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
CDSE_DOWNLOAD_BASE = "https://download.dataspace.copernicus.eu/odata/v1/Products"
SPACETRACK_LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
SPACETRACK_QUERY_BASE = "https://www.space-track.org/basicspacedata/query"
SENTINEL_1A_NORAD = "39634"

RAW_ROOT = Path("data/orbit_uncertainty_pilot/raw")
POEORB_DIR = RAW_ROOT / "sentinel_poeorb"
GP_DIR = RAW_ROOT / "spacetrack_gp"
METRICS_DIR = Path("outputs/metrics")
CANDIDATE_CSV = METRICS_DIR / "orbit_uncertainty_stage0_poeorb_candidates.csv"
SELECTION_CSV = METRICS_DIR / "orbit_uncertainty_stage0_poeorb_selection.csv"
MANIFEST_PATH = RAW_ROOT.parent / "download_manifest.json"


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name}=missing")
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def cdse_token(session: requests.Session) -> str:
    response = session.post(
        CDSE_TOKEN_URL,
        data={
            "client_id": "cdse-public",
            "username": required_env("CDSE_USERNAME"),
            "password": required_env("CDSE_PASSWORD"),
            "grant_type": "password",
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise SystemExit(f"CDSE token failed: HTTP {response.status_code}")
    token = response.json().get("access_token")
    if not token:
        raise SystemExit("CDSE token response did not contain access_token")
    return str(token)


def query_poeorb(session: requests.Session, token: str) -> list[dict[str, Any]]:
    params = {
        "$filter": "contains(Name,'S1A_OPER_AUX_POEORB')",
        "$orderby": "ContentDate/Start desc",
        "$top": "60",
        "$select": "Id,Name,ContentLength,ContentDate,PublicationDate",
    }
    response = session.get(
        CDSE_CATALOGUE_URL,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    )
    if response.status_code >= 400:
        raise SystemExit(f"CDSE catalogue failed: HTTP {response.status_code}")
    products = response.json().get("value", [])
    if not products:
        raise SystemExit("CDSE catalogue returned no Sentinel-1A AUX_POEORB products")
    return products


def product_row(product: dict[str, Any]) -> dict[str, Any]:
    content = product.get("ContentDate") or {}
    return {
        "product_type": "AUX_POEORB",
        "mission": "Sentinel-1A",
        "validity_start_utc": content.get("Start"),
        "validity_stop_utc": content.get("End"),
        "product_id": product.get("Id"),
        "original_filename": product.get("Name"),
        "file_size_bytes": product.get("ContentLength"),
        "publication_date_utc": product.get("PublicationDate"),
        "source": "Copernicus Data Space OData catalogue",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def choose_three_day_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: parse_utc(str(row["validity_start_utc"])))
    choices: list[tuple[float, datetime, list[dict[str, Any]]]] = []
    for index in range(len(ordered)):
        start = parse_utc(str(ordered[index]["validity_start_utc"]))
        stop = parse_utc(str(ordered[index]["validity_stop_utc"]))
        selected = [ordered[index]]
        for following in ordered[index + 1 :]:
            next_start = parse_utc(str(following["validity_start_utc"]))
            next_stop = parse_utc(str(following["validity_stop_utc"]))
            if next_start > stop:
                break
            selected.append(following)
            stop = max(stop, next_stop)
            duration_hours = (stop - start).total_seconds() / 3600.0
            if duration_hours >= 72.0:
                choices.append((duration_hours, start, selected.copy()))
                break
    if not choices:
        raise SystemExit("No continuous approximately three-day POEORB window found")
    # Prefer the smallest overshoot above 72 h, then the most recent window.
    choices.sort(key=lambda item: (item[0] - 72.0, -item[1].timestamp()))
    return choices[0][2]


def download_product(
    session: requests.Session, token: str, row: dict[str, Any]
) -> dict[str, Any]:
    POEORB_DIR.mkdir(parents=True, exist_ok=True)
    destination = POEORB_DIR / str(row["original_filename"])
    downloaded = False
    if not destination.exists():
        url = f"{CDSE_DOWNLOAD_BASE}({row['product_id']})/$value"
        with session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            stream=True,
            allow_redirects=True,
            timeout=180,
        ) as response:
            if response.status_code >= 400:
                raise SystemExit(
                    f"CDSE product download failed for {row['product_id']}: HTTP {response.status_code}"
                )
            temporary = destination.with_suffix(destination.suffix + ".part")
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            temporary.replace(destination)
        downloaded = True
    actual_size = destination.stat().st_size
    expected_size = int(row["file_size_bytes"])
    if actual_size != expected_size:
        raise SystemExit(
            f"POEORB size mismatch for {destination.name}: {actual_size} != {expected_size}"
        )
    return {
        **row,
        "raw_file_path": destination.as_posix(),
        "downloaded_this_run": downloaded,
        "download_time_utc": utc_now() if downloaded else None,
        "sha256": sha256(destination),
        "source_api": f"{CDSE_DOWNLOAD_BASE}(<product_id>)/$value",
    }


def spacetrack_gp_history(window_start: datetime, window_stop: datetime) -> dict[str, Any]:
    GP_DIR.mkdir(parents=True, exist_ok=True)
    query_start = (window_start - timedelta(days=3)).date().isoformat()
    query_stop = (window_stop + timedelta(days=1)).date().isoformat()
    raw_path = GP_DIR / f"sentinel1a_gp_history_{query_start.replace('-', '')}_{query_stop.replace('-', '')}.json"
    downloaded = False
    query_path = (
        f"/class/gp_history/NORAD_CAT_ID/{SENTINEL_1A_NORAD}"
        f"/EPOCH/{query_start}--{query_stop}"
        "/orderby/CREATION_DATE%20asc,EPOCH%20asc/format/json"
    )
    if not raw_path.exists():
        session = requests.Session()
        login = session.post(
            SPACETRACK_LOGIN_URL,
            data={
                "identity": required_env("SPACETRACK_USERNAME"),
                "password": required_env("SPACETRACK_PASSWORD"),
            },
            timeout=60,
        )
        if login.status_code >= 400:
            raise SystemExit(f"Space-Track login failed: HTTP {login.status_code}")
        response = session.get(SPACETRACK_QUERY_BASE + query_path, timeout=120)
        if response.status_code >= 400:
            raise SystemExit(f"Space-Track GP_HISTORY failed: HTTP {response.status_code}")
        try:
            records = response.json()
        except ValueError as exc:
            raise SystemExit("Space-Track GP_HISTORY returned non-JSON") from exc
        if not isinstance(records, list) or not records:
            raise SystemExit("Space-Track GP_HISTORY returned no Sentinel-1A records")
        raw_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        downloaded = True
    records = json.loads(raw_path.read_text(encoding="utf-8"))
    required = [
        "EPOCH",
        "CREATION_DATE",
        "NORAD_CAT_ID",
        "MEAN_MOTION",
        "ECCENTRICITY",
        "INCLINATION",
        "RA_OF_ASC_NODE",
        "ARG_OF_PERICENTER",
        "MEAN_ANOMALY",
        "BSTAR",
        "ELEMENT_SET_NO",
    ]
    missing = {key: sum(record.get(key) in (None, "") for record in records) for key in required}
    if any(missing.values()):
        raise SystemExit(f"Sentinel GP schema missing required values: {missing}")
    return {
        "source": "Space-Track GP_HISTORY",
        "source_api": "basicspacedata/query/class/gp_history",
        "query_parameters": {
            "NORAD_CAT_ID": SENTINEL_1A_NORAD,
            "EPOCH": f"{query_start}--{query_stop}",
            "format": "json",
        },
        "requested_time_range": {"start": query_start, "stop": query_stop},
        "raw_file_path": raw_path.as_posix(),
        "downloaded_this_run": downloaded,
        "download_time_utc": utc_now() if downloaded else None,
        "sha256": sha256(raw_path),
        "record_count": len(records),
        "object_ids": sorted({str(record["NORAD_CAT_ID"]) for record in records}),
        "schema_missing_counts": missing,
    }


def main() -> None:
    session = requests.Session()
    token = cdse_token(session)
    candidate_products = query_poeorb(session, token)
    candidate_rows = [product_row(product) for product in candidate_products]
    write_csv(CANDIDATE_CSV, candidate_rows)
    selection = choose_three_day_window(candidate_rows)
    write_csv(SELECTION_CSV, selection)
    downloaded_products = [download_product(session, token, row) for row in selection]
    start = min(parse_utc(str(row["validity_start_utc"])) for row in selection)
    stop = max(parse_utc(str(row["validity_stop_utc"])) for row in selection)
    gp_manifest = spacetrack_gp_history(start, stop)
    manifest = {
        "stage": "legitimate_orbit_uncertainty_stage0_source_acquisition",
        "created_at": utc_now(),
        "credentials": {
            "SPACETRACK_USERNAME": "configured",
            "SPACETRACK_PASSWORD": "configured",
            "CDSE_USERNAME": "configured",
            "CDSE_PASSWORD": "configured",
        },
        "token_persisted": False,
        "selected_poeorb_window": {
            "validity_start_utc": start.isoformat(),
            "validity_stop_utc": stop.isoformat(),
            "duration_hours": (stop - start).total_seconds() / 3600.0,
            "product_count": len(selection),
        },
        "poeorb_products": downloaded_products,
        "sentinel_gp_history": gp_manifest,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "poeorb_products": len(downloaded_products),
                "window_hours": manifest["selected_poeorb_window"]["duration_hours"],
                "gp_records": gp_manifest["record_count"],
                "manifest": MANIFEST_PATH.as_posix(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
