from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_orbit_uncertainty_stage1a_supgp import (
    REQUIRED_ORBITAL_FIELDS,
    audit_satellite,
    build_report,
    classify_status,
    cohort_gap_overlap_statistics,
    discover_and_read,
    duplicate_statistics,
    gap_hours,
    parse_utc,
    source_statistics,
)


def supgp_row(epoch: str, source: str = "SpaceX-E", rms: str = "0.3", mean_motion: str = "15.31") -> dict[str, str]:
    row = {
        "OBJECT_NAME": "STARLINK-TEST",
        "OBJECT_ID": "2020-001A",
        "EPOCH": epoch,
        "MEAN_MOTION": mean_motion,
        "ECCENTRICITY": ".0001",
        "INCLINATION": "53.16",
        "RA_OF_ASC_NODE": "180.0",
        "ARG_OF_PERICENTER": "90.0",
        "MEAN_ANOMALY": "270.0",
        "EPHEMERIS_TYPE": "0",
        "CLASSIFICATION_TYPE": "C",
        "NORAD_CAT_ID": "44714",
        "ELEMENT_SET_NO": "1",
        "REV_AT_EPOCH": "1",
        "BSTAR": ".1E-4",
        "MEAN_MOTION_DOT": ".1E-5",
        "MEAN_MOTION_DDOT": "0",
        "RMS": rms,
        "DATA_SOURCE": source,
    }
    assert set(REQUIRED_ORBITAL_FIELDS).issubset(row)
    return row


def annotate(rows: list[dict[str, str]]) -> list[dict]:
    result = []
    for index, row in enumerate(rows, start=2):
        item = dict(row)
        epoch, explicit = parse_utc(item["EPOCH"])
        item.update({
            "_raw_file": "fixture.csv",
            "_raw_row_number": index,
            "_raw_sequence": index - 2,
            "_epoch_dt": epoch,
            "_epoch_explicit_zone": explicit,
            "_epoch_error": "",
        })
        result.append(item)
    return result


class SupGPAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.stop = datetime(2026, 3, 29, tzinfo=timezone.utc)

    def test_parser_and_formal_window_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sat000044714.csv"
            rows = [
                supgp_row("2026-02-28T23:00:00.000000"),
                supgp_row("2026-03-01T01:00:00.000000"),
                supgp_row("2026-03-28T23:00:00.000000"),
                supgp_row("2026-03-29T00:00:00.000000"),
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            loaded, inventory, files, headers = discover_and_read(Path(temp))
            quality, _ = audit_satellite("44714", "STARLINK-TEST", loaded, self.start, self.stop, 24.0, 1000.0)
            self.assertEqual(len(files), 1)
            self.assertEqual(inventory[0]["row_count"], 4)
            self.assertIn("EPOCH", headers)
            self.assertEqual(quality["formal_window_record_count"], 2)
            self.assertEqual(quality["epoch_utc_assumed_from_schema_count"], 4)
            self.assertEqual(quality["status"], "READY")

    def test_duplicate_audit_preserves_exact_and_variant_records(self) -> None:
        rows = annotate([
            supgp_row("2026-03-10T00:00:00", rms="0.3"),
            supgp_row("2026-03-10T00:00:00", rms="0.3"),
            supgp_row("2026-03-10T00:00:00", rms="0.9", mean_motion="15.32"),
        ])
        stats, details = duplicate_statistics(rows)
        self.assertEqual(len(rows), 3)
        self.assertEqual(stats["duplicate_epoch_count"], 2)
        self.assertEqual(stats["exact_duplicate_record_count"], 1)
        self.assertEqual(stats["same_epoch_variant_group_count"], 1)
        self.assertEqual(stats["same_epoch_rms_variant_group_count"], 1)
        self.assertEqual(stats["same_epoch_element_variant_group_count"], 1)
        self.assertEqual(details[0]["handling"], "retained_all_raw_records_no_epoch_deduplication")

    def test_source_switch_statistics(self) -> None:
        rows = annotate([
            supgp_row("2026-03-10T00:00:00", source="SpaceX-E"),
            supgp_row("2026-03-10T08:00:00", source="Other"),
            supgp_row("2026-03-10T16:00:00", source="Other"),
        ])
        stats = source_statistics(rows)
        self.assertEqual(stats["distribution"]["SpaceX-E"], 1)
        self.assertEqual(stats["distribution"]["Other"], 2)
        self.assertEqual(len(stats["switch_epochs"]), 1)

    def test_gap_statistics_uses_unique_epochs(self) -> None:
        epochs = [
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, 8, tzinfo=timezone.utc),
            datetime(2026, 3, 3, 9, tzinfo=timezone.utc),
        ]
        gaps = gap_hours(epochs)
        self.assertEqual([item[2] for item in gaps], [8.0, 49.0])

    def test_status_classification_ready_partial_and_no_reference(self) -> None:
        common = dict(
            formal_count=2,
            propagation_ready_count=2,
            required_missing_count=0,
            required_invalid_count=0,
            init_errors=0,
            epoch_errors=0,
            missing_source=0,
            rms_missing_or_invalid=0,
            source_values=["SpaceX-E"],
            source_switch_count=0,
            first_epoch=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
            last_epoch=datetime(2026, 3, 28, 23, tzinfo=timezone.utc),
            formal_start=self.start,
            formal_stop=self.stop,
            boundary_tolerance_hours=24.0,
            large_internal_gap_count=0,
            same_epoch_variant_groups=0,
        )
        status, _ = classify_status(record_count=2, **common)
        self.assertEqual(status, "READY")
        partial = dict(common)
        partial["first_epoch"] = datetime(2026, 3, 8, tzinfo=timezone.utc)
        status, reasons = classify_status(record_count=2, **partial)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("起点" in reason for reason in reasons))
        empty = dict(common)
        empty.update(formal_count=0, propagation_ready_count=0)
        status, _ = classify_status(record_count=0, **empty)
        self.assertEqual(status, "NO_REFERENCE")

    def test_report_uses_internal_gap_reason_without_boundary_claim(self) -> None:
        rows = annotate([
            supgp_row("2026-03-01T01:00:00.000000"),
            supgp_row("2026-03-03T02:00:00.000000"),
            supgp_row("2026-03-28T23:00:00.000000"),
        ])
        quality, duplicates = audit_satellite(
            "44714", "STARLINK-TEST", rows, self.start, self.stop, 24.0, 48.0
        )
        report = build_report(
            [quality], [{"raw_file": "fixture.csv"}], duplicates,
            self.start, self.stop, 24.0, 48.0, [],
        )
        self.assertEqual(quality["status"], "PARTIAL")
        self.assertEqual(quality["start_boundary_gap_hours"], 1.0)
        self.assertEqual(quality["end_boundary_gap_hours"], 1.0)
        self.assertIn("存在超过既有 engineering large-gap rule 的内部时间缺口", report)
        self.assertIn("formal-window boundary incomplete=0/1", report)
        self.assertNotIn("formal-window boundary coverage incomplete", report)
        self.assertNotIn("返回数据从 3 月 8 日左右才开始", report)
        self.assertNotIn("缺少的是 3 月 1–7 日", report)

    def test_report_includes_same_epoch_variant_reason(self) -> None:
        rows = annotate([
            supgp_row("2026-03-01T01:00:00.000000", rms="0.3", mean_motion="15.31"),
            supgp_row("2026-03-10T00:00:00.000000", rms="0.3", mean_motion="15.31"),
            supgp_row("2026-03-10T00:00:00.000000", rms="0.9", mean_motion="15.32"),
            supgp_row("2026-03-28T23:00:00.000000", rms="0.3", mean_motion="15.31"),
        ])
        quality, duplicates = audit_satellite(
            "44714", "STARLINK-TEST", rows, self.start, self.stop, 24.0, 1000.0
        )
        report = build_report(
            [quality], [{"raw_file": "fixture.csv"}], duplicates,
            self.start, self.stop, 24.0, 1000.0, [],
        )
        self.assertEqual(quality["status"], "PARTIAL")
        self.assertEqual(quality["same_epoch_variant_group_count"], 1)
        self.assertIn("同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则", report)
        self.assertIn("same-epoch variant=1/1 颗、共 1 组", report)
        self.assertIn("exact duplicate excess records：0", report)
        self.assertIn(
            "当前 duplicate detail 记录 1 个 duplicate epoch group："
            "exact duplicate excess records=0，same-epoch variant groups=1",
            report,
        )
        self.assertNotIn("未来若出现同 epoch variant", report)

    def test_cohort_pause_is_reported_without_changing_gate(self) -> None:
        rows_a = annotate([
            supgp_row("2026-03-01T00:00:00"),
            supgp_row("2026-03-01T20:00:00"),
        ])
        rows_b = annotate([
            {**supgp_row("2026-03-01T01:00:00"), "NORAD_CAT_ID": "2"},
            {**supgp_row("2026-03-01T19:00:00"), "NORAD_CAT_ID": "2"},
        ])
        stats = cohort_gap_overlap_statistics(
            {"1": rows_a, "2": rows_b}, ["1", "2"], self.start, self.stop
        )
        self.assertEqual(stats["max_simultaneous_satellite_overlap"], 2)
        self.assertEqual(stats["longest_all_cohort_overlap_hours"], 18.0)
        self.assertFalse(stats["exceeds_frozen_48h_internal_gap_threshold"])


if __name__ == "__main__":
    unittest.main()
