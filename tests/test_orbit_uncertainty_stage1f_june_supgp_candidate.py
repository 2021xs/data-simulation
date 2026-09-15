from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.audit_orbit_uncertainty_stage1a_supgp import parse_utc
from scripts.audit_orbit_uncertainty_stage1f_june_supgp_candidate import (
    all_cohort_pauses,
    choose_window_decision,
)


def row(epoch: str) -> dict:
    parsed, explicit = parse_utc(epoch)
    return {"_epoch_dt": parsed, "_epoch_explicit_zone": explicit}


class JuneSupGPCandidateAuditTests(unittest.TestCase):
    def test_all_cohort_pause_detects_common_overlap(self) -> None:
        grouped = {
            "1": [row("2026-06-01T00:00:00Z"), row("2026-06-01T20:00:00Z")],
            "2": [row("2026-06-01T01:00:00Z"), row("2026-06-01T19:00:00Z")],
        }
        pauses = all_cohort_pauses(grouped, ["1", "2"])
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0]["pause_start"], "2026-06-01T01:00:00Z")
        self.assertEqual(pauses[0]["pause_end"], "2026-06-01T19:00:00Z")
        self.assertEqual(pauses[0]["duration_hours"], 18.0)
        self.assertFalse(pauses[0]["exceeds_frozen_48h_gate"])

    def test_window_decision_ready_is_acceptable(self) -> None:
        quality = [{"status": "READY"} for _ in range(20)]
        self.assertEqual(
            choose_window_decision(quality, True, True, True, 0, 0, False),
            ("A", "JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE"),
        )

    def test_window_decision_variant_is_local_issue(self) -> None:
        quality = [{"status": "READY"} for _ in range(20)]
        self.assertEqual(
            choose_window_decision(quality, True, True, True, 0, 1, False)[0],
            "B",
        )

    def test_window_decision_major_gap_is_unsuitable(self) -> None:
        quality = [{"status": "PARTIAL"} for _ in range(20)]
        self.assertEqual(
            choose_window_decision(quality, True, True, True, 0, 0, True)[0],
            "C",
        )


if __name__ == "__main__":
    unittest.main()
