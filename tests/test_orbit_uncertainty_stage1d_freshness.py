import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import calibrate_orbit_uncertainty_stage1d_freshness as stage1d
from scripts.calibrate_orbit_uncertainty_stage1d_freshness import (
    VIEW_FULL,
    build_views,
    calibration_bin,
    fit_conditional_quantile_model,
    satellite_cluster_rate_ci,
    wilson_interval,
)


class Stage1DFreshnessCalibrationTests(unittest.TestCase):
    def fixture(self) -> pd.DataFrame:
        rows = []
        for sat_index, norad in enumerate(["1", "2", "3"]):
            for age in [1.0, 4.0, 7.0, 10.0, 14.0, 20.0, 26.0, 34.0, 37.0]:
                rows.append({
                    "NORAD_CAT_ID": norad,
                    "element_age_hours": age,
                    "position_error_norm_km": age * (1.0 + 0.1 * sat_index),
                    "freshness_support_status": (
                        "WITHIN_CALIBRATED_FRESHNESS_SUPPORT" if 0.0 < age <= 36.0
                        else "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT"
                    ),
                    "is_stage1c_regime_candidate": bool(norad == "1" and age == 14.0),
                })
        return pd.DataFrame(rows)

    def test_support_views_keep_full_and_exclude_only_candidate_for_sensitivity(self):
        frame = self.fixture()
        views = build_views(frame)
        self.assertEqual(len(views[VIEW_FULL]), 24)
        self.assertEqual(len(views[VIEW_FULL]) - len(views["REGIME_EXCLUDED_SENSITIVITY"]), 1)
        self.assertEqual(len(frame), 27)

    def test_calibration_bins_use_right_inclusive_support(self):
        ages = pd.Series([0.1, 6.0, 6.1, 9.0, 35.9, 36.0])
        labels = calibration_bin(ages).astype(str).tolist()
        self.assertEqual(labels, ["0-6 h", "0-6 h", "6-9 h", "6-9 h", "24-36 h", "24-36 h"])

    def test_model_is_monotone_and_non_crossing(self):
        frame = self.fixture()
        supported = build_views(frame)[VIEW_FULL]
        model = fit_conditional_quantile_model(
            supported, "element_age_hours", "position_error_norm_km", [0.50, 0.90, 0.95]
        )
        grid = np.array([0.1, 3.0, 6.0, 12.0, 24.0, 36.0])
        predictions = {quantile: model.predict(grid, quantile) for quantile in [0.50, 0.90, 0.95]}
        for values in predictions.values():
            self.assertTrue(np.all(np.diff(values) >= -1e-12))
        self.assertTrue(np.all(predictions[0.50] <= predictions[0.90]))
        self.assertTrue(np.all(predictions[0.90] <= predictions[0.95]))
        with self.assertRaises(ValueError):
            model.predict(np.array([36.1]), 0.95)

    def test_wilson_interval_contains_observed_rate(self):
        low, high = wilson_interval(95, 100)
        self.assertLessEqual(low, 0.95)
        self.assertGreaterEqual(high, 0.95)

    def test_vectorized_satellite_cluster_ci_is_deterministic(self):
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1"] * 4 + ["2"] * 4 + ["3"] * 4,
            "covered": [True] * 4 + [True, True, False, False] + [False] * 4,
        })
        first = satellite_cluster_rate_ci(frame, "covered", reps=500, seed=19)
        second = satellite_cluster_rate_ci(frame, "covered", reps=500, seed=19)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first[0], 0.0)
        self.assertLessEqual(first[1], 1.0)

    def test_position_plot_handles_quantile_named_column(self):
        frame = pd.DataFrame({
            "element_age_hours": [1.0, 3.0, 6.0, 12.0, 24.0, 35.0],
            "position_error_norm_km": [1.0, 1.5, 2.0, 3.0, 5.0, 8.0],
        })
        rows = []
        for quantile, scale in [(0.50, 1.0), (0.90, 2.0), (0.95, 3.0)]:
            for age in [0.0, 6.0, 12.0, 24.0, 36.0]:
                rows.append({
                    "view": VIEW_FULL,
                    "conditioning_variable": "element_age_seconds",
                    "response": "position_error_norm_km",
                    "quantile": quantile,
                    "evaluation_age_h": age,
                    "prediction": scale + age / 10.0,
                })
        with TemporaryDirectory() as directory:
            output = Path(directory) / "plot.png"
            with patch.object(stage1d, "POSITION_FIGURE", output):
                stage1d.plot_position(frame, pd.DataFrame(rows))
            self.assertTrue(output.exists())

    def test_satellite_coverage_plot_tolerates_roundoff_at_interval_edges(self):
        rows = []
        for norad, coverage in [("1", 0.95), ("2", 0.90)]:
            rows.append({
                "view": VIEW_FULL,
                "quantile": 0.95,
                "NORAD_CAT_ID": norad,
                "loso_coverage": coverage,
                "loso_wilson_low": coverage + 1e-16,
                "loso_wilson_high": min(1.0, coverage + 0.03),
            })
        with TemporaryDirectory() as directory:
            output = Path(directory) / "coverage.png"
            with patch.object(stage1d, "SATELLITE_FIGURE", output):
                stage1d.plot_satellite_coverage(pd.DataFrame(rows))
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
