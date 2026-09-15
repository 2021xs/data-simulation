from __future__ import annotations

import unittest

from scripts.adjudicate_orbit_uncertainty_stage1a_june_readiness import (
    classify_readiness,
    summarize_causal_rows,
)


def causal_row(
    norad: str,
    age_hours: float,
    *,
    candidates: int = 1,
    future: bool = False,
    epoch_after: bool = False,
    publication_age_hours: float = 1.0,
) -> dict[str, str]:
    return {
        "NORAD_CAT_ID": norad,
        "evaluation_time": "2026-06-01T00:00:00Z",
        "causal_candidate_count": str(candidates),
        "selected_gp_epoch": "2026-05-31T00:00:00Z",
        "selected_gp_creation_date": "2026-05-31T12:00:00Z",
        "gp_age_seconds": str(age_hours * 3600.0),
        "publication_age_seconds": str(publication_age_hours * 3600.0),
        "future_publication_used": str(future),
        "selected_gp_epoch_after_evaluation": str(epoch_after),
    }


class JuneReadinessAdjudicationTests(unittest.TestCase):
    def test_gt72_real_staleness_is_ready_with_label(self) -> None:
        rows = [causal_row("1", 12.0), causal_row("1", 73.0)]
        self.assertEqual(classify_readiness(rows), "READY_WITH_GT72H_STALENESS")
        summary = summarize_causal_rows(rows)
        self.assertEqual(summary["stage1b_canonical_eligible_rows"], 2)
        self.assertEqual(summary["stage1f_primary_confirmatory_rows"], 1)
        self.assertEqual(summary["stage1f_outside_support_rows"], 1)

    def test_frozen_36h_support_boundaries_are_exact(self) -> None:
        rows = [
            causal_row("1", 0.0),
            causal_row("1", 0.001),
            causal_row("1", 36.0),
            causal_row("1", 36.001),
        ]
        summary = summarize_causal_rows(rows)
        self.assertEqual(summary["stage1f_primary_confirmatory_rows"], 2)
        self.assertEqual(summary["stage1f_outside_support_rows"], 2)
        self.assertEqual(summary["nonpositive_element_age_rows"], 1)

    def test_missing_causal_support_blocks(self) -> None:
        rows = [causal_row("1", 12.0, candidates=0)]
        self.assertEqual(classify_readiness(rows), "BLOCKED_MISSING_CAUSAL_SUPPORT")
        self.assertEqual(summarize_causal_rows(rows)["stage1b_canonical_eligible_rows"], 0)

    def test_future_or_invalid_selection_blocks(self) -> None:
        future = [causal_row("1", 12.0, future=True)]
        negative = [causal_row("1", -1.0)]
        self.assertEqual(
            classify_readiness(future),
            "BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION",
        )
        self.assertEqual(
            classify_readiness(negative),
            "BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION",
        )

    def test_scientific_result_columns_are_rejected(self) -> None:
        row = causal_row("1", 12.0)
        row["ellipsoid_score"] = "0.5"
        with self.assertRaisesRegex(RuntimeError, "Scientific result fields are forbidden"):
            summarize_causal_rows([row])


if __name__ == "__main__":
    unittest.main()
