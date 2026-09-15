import unittest

import pandas as pd

from scripts.analyze_orbit_uncertainty_stage1c_residual_structure import (
    add_sensitivity_flags,
    build_satellite_summary,
    circular_difference,
    detect_episodes,
)


class Stage1CResidualStructureTests(unittest.TestCase):
    def test_circular_difference_avoids_wraparound_artifact(self):
        self.assertAlmostEqual(circular_difference(1.0, 359.0), 2.0)
        self.assertAlmostEqual(circular_difference(359.0, 1.0), -2.0)

    def test_top_rank_counts_use_ceil_and_do_not_drop_rows(self):
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1"] * 101,
            "position_error_norm_km": list(range(101)),
        })
        result = add_sensitivity_flags(frame)
        self.assertEqual(result["global_top1_count"], 2)
        self.assertEqual(result["global_top0_5_count"], 1)
        self.assertEqual(len(frame), 101)

    def test_satellite_summary_handles_t_component_without_attribute_collision(self):
        frame = pd.DataFrame({
            "NORAD_CAT_ID": [1, 1, 1],
            "object_name": ["TEST"] * 3,
            "evaluation_time": pd.date_range("2026-04-01", periods=3, freq="h", tz="UTC"),
            "position_error_norm_km": [1.0, 2.0, 3.0],
            "velocity_error_norm_km_s": [0.1, 0.2, 0.3],
            "element_age_seconds": [3600.0, 7200.0, 10800.0],
            "publication_age_seconds": [600.0, 1200.0, 1800.0],
            "element_age_hours": [1.0, 2.0, 3.0],
            "publication_age_hours": [1.0 / 6.0, 1.0 / 3.0, 0.5],
            "supgp_rms_km": [0.1, 0.2, 0.3],
            "dominant_component": ["T", "T", "R"],
            "is_global_top_1pct": [False, False, True],
            "is_within_satellite_top_1pct": [False, False, True],
        })
        summary = build_satellite_summary(frame)
        self.assertAlmostEqual(summary.loc[0, "T_dominant_proportion"], 2.0 / 3.0)

    def test_episode_rules_distinguish_isolated_and_persistent(self):
        times = pd.date_range("2026-04-01", periods=15, freq="2h", tz="UTC")
        values = [1, 2, 3, 200, 2, 3, 150, 160, 170, 180, 190, 200, 210, 220, 2]
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1"] * len(values),
            "evaluation_time": times,
            "position_error_norm_km": values,
            "velocity_error_norm_km_s": [value / 1000 for value in values],
            "ordinary_gp_id": [str(index) for index in range(len(values))],
        })
        frame["is_global_top_1pct"] = False
        frame.loc[3, "is_global_top_1pct"] = True
        frame.loc[6:13, "is_global_top_1pct"] = True
        episodes = detect_episodes(frame, {"pooled_p95_km": 100.0, "global_top1_threshold_km": 150.0})
        self.assertEqual(episodes[0]["pattern_code"], "A")
        self.assertEqual(episodes[1]["pattern_code"], "D")


if __name__ == "__main__":
    unittest.main()
