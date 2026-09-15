from __future__ import annotations

import unittest

from scripts.audit_orbit_uncertainty_stage1a_gt72_completeness import (
    classify_missing_record,
)


class GT72CompletenessAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "evaluation_time": "2026-06-23T00:00:00Z",
            "selected_gp_epoch": "2026-06-19T12:00:00Z",
        }

    def test_causally_eligible_newer_record_is_class_a(self) -> None:
        row = {
            "EPOCH": "2026-06-21T00:00:00Z",
            "CREATION_DATE": "2026-06-22T00:00:00Z",
        }
        self.assertEqual(
            classify_missing_record(row, [self.case]),
            ("A_CAUSALLY_ELIGIBLE_NEWER_GP", 1, 1),
        )

    def test_future_publication_is_class_b(self) -> None:
        row = {
            "EPOCH": "2026-06-22T00:00:00Z",
            "CREATION_DATE": "2026-06-23T00:00:01Z",
        }
        self.assertEqual(
            classify_missing_record(row, [self.case]),
            ("B_PUBLISHED_ONLY_AFTER_AFFECTED_EVALUATIONS", 0, 0),
        )

    def test_causal_but_older_record_is_not_explanatory(self) -> None:
        row = {
            "EPOCH": "2026-06-18T00:00:00Z",
            "CREATION_DATE": "2026-06-20T00:00:00Z",
        }
        self.assertEqual(
            classify_missing_record(row, [self.case]),
            ("NONEXPLANATORY_CAUSAL_BUT_NOT_NEWER", 1, 0),
        )


if __name__ == "__main__":
    unittest.main()
