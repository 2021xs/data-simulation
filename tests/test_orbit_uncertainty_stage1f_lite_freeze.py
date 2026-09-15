import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import run_orbit_uncertainty_stage1f_lite_freeze as stage1f


class Stage1FLiteFreezeTests(unittest.TestCase):
    def sample_frame(self, seed=4, n=600):
        rng = np.random.default_rng(seed)
        values = rng.multivariate_normal(
            [0.1, 1.0, -0.05],
            [[0.04, 0.08, 0.002], [0.08, 4.0, -0.03], [0.002, -0.03, 0.02]],
            size=n,
        )
        return pd.DataFrame({
            "NORAD_CAT_ID": np.repeat(["1", "2", "3"], n // 3),
            "delta_R_km": values[:, 0],
            "delta_T_km": values[:, 1],
            "delta_N_km": values[:, 2],
        })

    def test_freshness_bins_are_left_exclusive_right_inclusive(self):
        values = pd.Series([0.0, 0.1, 6.0, 6.0001, 9.0, 12.0, 18.0, 24.0, 36.0, 36.0001])
        result = stage1f.freshness_bin(values)
        observed = [None if pd.isna(value) else str(value) for value in result]
        self.assertEqual(observed, [None, "0-6 h", "0-6 h", "6-9 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h", None])

    def test_empirical_quantile_is_higher_order_statistic(self):
        values = np.arange(1.0, 11.0)
        self.assertEqual(stage1f.empirical_quantile(values, 0.95), 10.0)

    def test_box_uses_signed_median_mad_and_joint_max_score(self):
        frame = self.sample_frame()
        model = stage1f.fit_bin_model(frame, "JOINT_MAX_SCORE_BOX", "TEST")
        values = frame.loc[:, stage1f.POSITION_COLUMNS].to_numpy()
        expected_center = np.median(values, axis=0)
        expected_scale = stage1f.MAD_NORMALIZATION * np.median(np.abs(values - expected_center), axis=0)
        np.testing.assert_allclose(model.center, expected_center)
        np.testing.assert_allclose(model.scale, expected_scale)
        scores = np.max(np.abs(values - expected_center) / expected_scale, axis=1)
        np.testing.assert_allclose(model.score(values), scores)
        self.assertEqual(model.thresholds[0.99], np.quantile(scores, 0.99, method="higher"))

    def test_ellipsoid_uses_empirical_threshold_and_is_stable(self):
        frame = self.sample_frame()
        model = stage1f.fit_bin_model(frame, "ROBUST_EMPIRICAL_ELLIPSOID", "TEST")
        values = frame.loc[:, stage1f.POSITION_COLUMNS].to_numpy()
        scores = model.score(values)
        self.assertGreater(np.min(model.eigenvalues), 0.0)
        self.assertLess(model.condition_number, stage1f.ELLIPSOID_CONDITION_LIMIT)
        self.assertEqual(model.thresholds[0.95], np.quantile(scores, 0.95, method="higher"))

    def test_volume_formulas(self):
        frame = self.sample_frame()
        box = stage1f.fit_bin_model(frame, "JOINT_MAX_SCORE_BOX", "TEST")
        ellipse = stage1f.fit_bin_model(frame, "ROBUST_EMPIRICAL_ELLIPSOID", "TEST")
        expected_box = 8.0 * box.thresholds[0.99] ** 3 * np.prod(box.scale)
        expected_ellipse = (4.0 / 3.0) * np.pi * ellipse.thresholds[0.99] ** 1.5 * np.sqrt(ellipse.determinant)
        self.assertAlmostEqual(box.volume(0.99), expected_box)
        self.assertAlmostEqual(ellipse.volume(0.99), expected_ellipse)

    def test_reference_sensitivity_preserves_single_norad_column(self):
        frame = self.sample_frame()
        frame["row_uid"] = [f"row-{index}" for index in range(len(frame))]
        frame["month"] = "APRIL"
        frame["evaluation_time"] = pd.date_range("2026-04-01", periods=len(frame), freq="min", tz="UTC")
        frame["element_age_hours"] = 3.0
        frame["freshness_bin"] = stage1f.freshness_bin(frame.element_age_hours)
        frame["supgp_rms_km"] = np.linspace(0.1, 0.3, len(frame))
        model = stage1f.fit_bin_model(frame, "JOINT_MAX_SCORE_BOX", "0-6 h")
        result = stage1f.reference_sensitivity(frame, "JOINT_MAX_SCORE_BOX", {"0-6 h": model})
        self.assertEqual(len(result), 4)
        self.assertTrue(result.rms_operational_parameter_count.eq(0).all())

    def test_june_scan_does_not_open_files_and_flags_stage1_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1 = root / "data/orbit_uncertainty_stage1/raw/spacetrack_gp"
            stage1.mkdir(parents=True)
            candidate = stage1 / "spacetrack_gp_history_20260529_20260701_20sat_omm.json"
            candidate.write_bytes(b"must-not-be-parsed")
            result = stage1f.scan_june_blindness(root)
            self.assertTrue(result["june_stage1_scientific_data_present_before_freeze"])
            self.assertEqual(result["june_scientific_rows_read"], 0)
            self.assertEqual(len(result["suspicious_paths"]), 1)

    def test_candidate_set_is_exactly_two(self):
        self.assertEqual(stage1f.CANDIDATES, ("JOINT_MAX_SCORE_BOX", "ROBUST_EMPIRICAL_ELLIPSOID"))


if __name__ == "__main__":
    unittest.main()
