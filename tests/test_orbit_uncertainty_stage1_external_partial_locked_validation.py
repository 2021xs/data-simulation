import unittest

import numpy as np
import pandas as pd

from scripts import run_orbit_uncertainty_stage1_external_202605_partial_locked_validation as partial


class Stage1ExternalPartialLockedValidationTests(unittest.TestCase):
    def test_m0_grid_inversion_recovers_frozen_piecewise_linear_knots(self):
        knots = np.array([0.5, 1.2, 1.8, 3.0, 4.2, 7.5])
        grid = partial.interpolation_matrix(partial.M0_GRID_H, partial.M0_KNOTS_H) @ knots
        recovered, error = partial.reconstruct_m0_knots(grid)
        np.testing.assert_allclose(recovered, knots, rtol=0.0, atol=1e-14)
        self.assertLessEqual(error, 1e-14)

    def test_publication_strata_preserve_april_right_inclusive_boundaries(self):
        values = pd.Series([0.0, 3.0, 3.0001, 6.0, 6.0001, 12.0, 12.0001, 24.0, 24.0001])
        self.assertEqual(
            partial.publication_stratum(values).tolist(),
            [
                "PUB_0_3", "PUB_0_3", "PUB_3_6", "PUB_3_6", "PUB_6_12",
                "PUB_6_12", "PUB_12_24", "PUB_12_24", "PUB_GT24",
            ],
        )

    def test_april_frozen_m0_m1_m2_are_complete(self):
        calibration = pd.read_csv(partial.APRIL_CALIBRATION)
        candidates, details = partial.load_frozen_candidates(calibration)
        self.assertEqual(len(candidates), 8)
        self.assertEqual(len(details["m2_satellites"]), 20)
        self.assertLessEqual(details["m0_grid_reconstruction_max_abs_error_km"], 1e-12)
        for candidate in candidates.values():
            self.assertEqual(set(candidate.m1_factors), set(partial.PUBLICATION_GROUPS))
            self.assertEqual(len(candidate.m2_factors), 20)

    def test_may_support_split_is_exact(self):
        primary, outside, support = partial.load_may()
        self.assertEqual(len(primary), 6094)
        self.assertEqual(len(outside), 87)
        self.assertEqual(support["rows_removed"], 0)
        self.assertTrue((primary.element_age_hours > 0.0).all())
        self.assertTrue((primary.element_age_hours <= 36.0).all())
        self.assertTrue((outside.element_age_hours > 36.0).all())

    def test_prediction_models_are_only_m0_m1_m2_and_use_no_may_fit(self):
        calibration = pd.read_csv(partial.APRIL_CALIBRATION)
        candidates, _ = partial.load_frozen_candidates(calibration)
        primary, _, _ = partial.load_may()
        sample = primary.iloc[:10]
        candidate = candidates[("abs_delta_T_km", 0.95)]
        for model in partial.MODELS:
            predicted = candidate.predict(sample, model)
            self.assertEqual(len(predicted), len(sample))
            self.assertTrue(np.isfinite(predicted).all())
            self.assertTrue((predicted > 0.0).all())
        with self.assertRaises(ValueError):
            candidate.predict(sample, "M3")
        with self.assertRaises(ValueError):
            candidate.predict(sample, "M4")


if __name__ == "__main__":
    unittest.main()
