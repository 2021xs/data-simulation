import unittest

import numpy as np
import pandas as pd

from scripts import run_orbit_uncertainty_stage1f_lite_june_confirmatory_validation as confirm


class Stage1FLiteJuneConfirmatoryTests(unittest.TestCase):
    def test_freshness_bins_match_frozen_left_exclusive_right_inclusive_rule(self):
        values = pd.Series([0.0, 0.1, 6.0, 6.0001, 9.0, 12.0, 18.0, 24.0, 36.0, 36.0001])
        result = confirm.freshness_bin(values)
        observed = [None if pd.isna(value) else str(value) for value in result]
        self.assertEqual(observed, [None, "0-6 h", "0-6 h", "6-9 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h", None])

    def test_classification_boundaries_are_inclusive(self):
        score = np.array([1.0, 1.0001, 2.0, 2.0001])
        result = confirm.classify_score(score, np.full(4, 1.0), np.full(4, 2.0))
        self.assertEqual(result.tolist(), ["NOT_ORBIT_DISTINCT", "AMBIGUOUS", "AMBIGUOUS", "ORBIT_DISTINCT"])

    def test_ellipsoid_scoring_uses_frozen_center_and_covariance(self):
        frame = pd.DataFrame({
            "evaluation_time": pd.to_datetime(["2026-06-01T00:00:00Z"]),
            "NORAD_CAT_ID": ["1"], "freshness_bin": ["0-6 h"],
            "delta_R_km": [2.0], "delta_T_km": [4.0], "delta_N_km": [8.0],
        })
        covariance = np.diag([1.0, 4.0, 16.0])
        models = {"0-6 h": {"center": np.array([1.0, 2.0, 4.0]), "covariance": covariance, "precision": np.linalg.inv(covariance), "c95": 2.9, "c99": 3.0}}
        result = confirm.score_frozen_candidate(frame, confirm.PRIMARY, models)
        self.assertAlmostEqual(result.joint_score.iloc[0], 3.0)
        self.assertEqual(result.decision.iloc[0], "AMBIGUOUS")

    def test_box_scoring_uses_joint_max(self):
        frame = pd.DataFrame({
            "evaluation_time": pd.to_datetime(["2026-06-01T00:00:00Z"]),
            "NORAD_CAT_ID": ["1"], "freshness_bin": ["0-6 h"],
            "delta_R_km": [2.0], "delta_T_km": [6.0], "delta_N_km": [5.0],
        })
        models = {"0-6 h": {"center": np.array([1.0, 2.0, 3.0]), "scale": np.array([1.0, 2.0, 4.0]), "c95": 1.5, "c99": 2.5}}
        result = confirm.score_frozen_candidate(frame, confirm.SECONDARY, models)
        self.assertAlmostEqual(result.joint_score.iloc[0], 2.0)
        self.assertEqual(result.decision.iloc[0], "AMBIGUOUS")

    def test_cluster_bootstrap_is_deterministic_and_cluster_weighted(self):
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1", "1", "2"],
            "inside_p95": [True, False, True],
            "inside_p99": [True, True, False],
        })
        first = confirm.cluster_bootstrap(frame, 100, 7)
        second = confirm.cluster_bootstrap(frame, 100, 7)
        self.assertEqual(first, second)
        self.assertLessEqual(first["p99_ci_low"], first["p99_ci_high"])

    def test_episode_breaks_on_in_set_row_and_large_gap(self):
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1"] * 5,
            "evaluation_time": pd.to_datetime([
                "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "2026-06-01T02:00:00Z",
                "2026-06-01T03:00:00Z", "2026-06-01T10:00:00Z",
            ]),
            "inside_p99": [False, False, True, False, False],
            "inside_p95": [False] * 5,
            "joint_score": [3.0, 4.0, 0.0, 5.0, 6.0],
            "freshness_bin": ["0-6 h"] * 5,
        })
        result = confirm.continuous_episodes(frame, "U99")
        self.assertEqual(result.row_count.tolist(), [2, 1, 1])
        self.assertEqual(result.duration_hours.tolist(), [1.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
