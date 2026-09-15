from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import acquire_orbit_uncertainty_stage1 as acquisition
from scripts.orbit_uncertainty_stage1_window import (
    FORMAL_DURATION_DAYS,
    FORMAL_START,
    FORMAL_STOP_EXCLUSIVE,
    GP_ACQUISITION_START,
    GP_ACQUISITION_STOP_EXCLUSIVE,
    LOOKBACK_HOURS,
    WINDOW_TAG,
)


class Stage1WindowTests(unittest.TestCase):
    def test_approved_april_window_is_shared_and_tagged(self) -> None:
        self.assertEqual(FORMAL_START, "2026-04-01T00:00:00Z")
        self.assertEqual(FORMAL_STOP_EXCLUSIVE, "2026-05-01T00:00:00Z")
        self.assertEqual(GP_ACQUISITION_START, "2026-03-29T00:00:00Z")
        self.assertEqual(GP_ACQUISITION_STOP_EXCLUSIVE, FORMAL_STOP_EXCLUSIVE)
        self.assertEqual(LOOKBACK_HOURS, 72.0)
        self.assertEqual(FORMAL_DURATION_DAYS, 30)
        self.assertEqual(WINDOW_TAG, "20260401_20260430")
        self.assertIn(WINDOW_TAG, acquisition.GP_INVENTORY_PATH.name)
        self.assertIn("20260329_20260501", acquisition.GP_RAW_PATH.name)

    def test_causal_selection_excludes_future_publication_and_keeps_tiebreaks(self) -> None:
        evaluation = datetime(2026, 4, 1, 1, tzinfo=timezone.utc)
        records = [
            {
                "GP_ID": "100",
                "EPOCH": "2026-03-31T22:00:00Z",
                "CREATION_DATE": "2026-04-01T00:10:00Z",
            },
            {
                "GP_ID": "101",
                "EPOCH": "2026-03-31T23:00:00Z",
                "CREATION_DATE": "2026-04-01T00:10:00Z",
            },
            {
                "GP_ID": "102",
                "EPOCH": "2026-03-31T23:00:00Z",
                "CREATION_DATE": "2026-04-01T00:10:00Z",
            },
            {
                "GP_ID": "999",
                "EPOCH": "2026-04-01T00:30:00Z",
                "CREATION_DATE": "2026-04-01T01:00:01Z",
            },
        ]
        selected, candidate_count = acquisition.select_causal_gp(records, evaluation)
        self.assertEqual(candidate_count, 3)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["GP_ID"], "102")
        self.assertEqual(len(records), 4)

    def test_explicit_may_runtime_configuration_uses_distinct_paths(self) -> None:
        original_selection = acquisition.SELECTION_PATH
        original_supgp = acquisition.SUPGP_RAW_DIR
        try:
            acquisition.configure_runtime(
                window_tag="20260501_20260531",
                formal_start="2026-05-01T00:00:00Z",
                formal_stop_exclusive="2026-06-01T00:00:00Z",
                gp_acquisition_start="2026-04-28T00:00:00Z",
                lookback_hours=72.0,
                selection_path=Path("selection.csv"),
                supgp_raw_dir=Path("may_supgp"),
            )
            self.assertEqual(acquisition.WINDOW_TAG, "20260501_20260531")
            self.assertIn("20260428_20260601", acquisition.GP_RAW_PATH.name)
            self.assertIn("20260501_20260531", acquisition.MANIFEST_PATH.name)
            self.assertEqual(acquisition.SUPGP_RAW_DIR, Path("may_supgp"))
        finally:
            acquisition.configure_runtime(
                window_tag=WINDOW_TAG,
                formal_start=FORMAL_START,
                formal_stop_exclusive=FORMAL_STOP_EXCLUSIVE,
                gp_acquisition_start=GP_ACQUISITION_START,
                lookback_hours=LOOKBACK_HOURS,
                selection_path=original_selection,
                supgp_raw_dir=original_supgp,
            )

    def test_causal_audit_keeps_element_and_publication_age_separate(self) -> None:
        gp_rows = [{
            "NORAD_CAT_ID": "44714",
            "GP_ID": "100",
            "EPOCH": "2026-04-30T20:00:00Z",
            "CREATION_DATE": "2026-04-30T23:00:00Z",
        }]
        supgp_rows = [{
            "NORAD_CAT_ID": "44714",
            "evaluation_time": "2026-05-01T00:00:00Z",
        }]
        details, summary = acquisition.audit_causal_support(
            gp_rows, supgp_rows, [{"NORAD_CAT_ID": "44714", "OBJECT_NAME": "TEST"}]
        )
        self.assertEqual(details[0]["gp_age_seconds"], 4 * 3600)
        self.assertEqual(details[0]["publication_age_seconds"], 1 * 3600)
        self.assertEqual(summary[0]["publication_age_seconds_median"], 1 * 3600)

    def test_quantile_is_linear_and_reproducible(self) -> None:
        self.assertEqual(acquisition.quantile([0.0, 10.0], 0.90), 9.0)
        self.assertEqual(acquisition.quantile([3.0], 0.95), 3.0)
        self.assertIsNone(acquisition.quantile([], 0.95))

    def test_reference_pause_is_descriptive_and_does_not_change_48h_gate(self) -> None:
        selection = [
            {"NORAD_CAT_ID": "1", "OBJECT_NAME": "A"},
            {"NORAD_CAT_ID": "2", "OBJECT_NAME": "B"},
        ]
        rows = [
            {"NORAD_CAT_ID": "1", "evaluation_time": "2026-05-01T00:00:00Z"},
            {"NORAD_CAT_ID": "1", "evaluation_time": "2026-05-01T20:00:00Z"},
            {"NORAD_CAT_ID": "2", "evaluation_time": "2026-05-01T01:00:00Z"},
            {"NORAD_CAT_ID": "2", "evaluation_time": "2026-05-01T19:00:00Z"},
        ]
        pause = acquisition.cohort_reference_gap_overlap(rows, selection)
        self.assertEqual(pause["max_simultaneous_satellites_between_records"], 2)
        self.assertEqual(pause["longest_all_cohort_between_record_interval_hours"], 18.0)
        self.assertFalse(pause["exceeds_frozen_48h_internal_gap_threshold"])

    def test_prior_day_element_epoch_does_not_false_fail_complete_ingestion(self) -> None:
        def row(gp_id: str, epoch: str, creation: str) -> dict[str, str]:
            item = {field: "1" for field in acquisition.REQUIRED_GP_FIELDS}
            item.update({
                "NORAD_CAT_ID": "44714",
                "OBJECT_NAME": "TEST",
                "GP_ID": gp_id,
                "EPOCH": epoch,
                "CREATION_DATE": creation,
            })
            return item

        rows = [
            row("1", "2026-03-31T12:00:00Z", "2026-03-31T18:00:00Z"),
            row("2", "2026-04-29T23:00:00Z", "2026-04-30T06:00:00Z"),
        ]
        audit = acquisition.audit_gp(
            rows, [{"NORAD_CAT_ID": "44714", "OBJECT_NAME": "TEST"}]
        )[0]
        self.assertFalse(audit["formal_epoch_max_reaches_last_day"])
        self.assertTrue(audit["ordinary_gp_complete"])


if __name__ == "__main__":
    unittest.main()
