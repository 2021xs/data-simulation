import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import calibrate_orbit_uncertainty_stage1e_heterogeneity_regime as stage1e


class Stage1EHeterogeneityRegimeTests(unittest.TestCase):
    def model_fixture(self) -> pd.DataFrame:
        rows = []
        for sat_index, sat in enumerate(["1", "2", "3"]):
            for age in [1.0, 4.0, 7.0, 10.0, 14.0, 20.0, 26.0, 34.0]:
                scale = 1.0 + 0.15 * sat_index
                rows.append({
                    "NORAD_CAT_ID": sat,
                    "element_age_hours": age,
                    "publication_age_hours": max(0.1, age / 3.0),
                    "supgp_rms_km": 0.15 + 0.01 * sat_index,
                    "abs_delta_R_km": age * 0.05 * scale,
                    "abs_delta_T_km": age * scale,
                    "abs_delta_N_km": age * 0.03 * scale,
                    "position_error_norm_km": age * 1.01 * scale,
                    "abs_delta_v_R_km_s": age * 1e-3 * scale,
                    "abs_delta_v_T_km_s": age * 5e-5 * scale,
                    "abs_delta_v_N_km_s": age * 3e-5 * scale,
                    "is_stage1c_regime_candidate": bool(sat == "3" and age in [26.0, 34.0]),
                    "selected_gp_just_changed": int(age in [7.0, 26.0]),
                    "hours_since_selected_gp_switch": age % 7.0,
                    "previous_publication_interval_hours": 6.0,
                    "gp_epoch_jump_hours": 6.0,
                    "abs_delta_mean_motion": 0.001 * scale,
                    "abs_delta_eccentricity": 1e-5 * scale,
                    "abs_delta_inclination_deg": 0.001 * scale,
                    "abs_delta_raan_deg": 0.002 * scale,
                    "abs_delta_arg_perigee_deg": 0.01 * scale,
                    "abs_delta_mean_anomaly_deg": 0.01 * scale,
                    "abs_delta_bstar": 1e-5 * scale,
                    "selected_mean_motion": 15.3,
                    "selected_eccentricity": 0.0002,
                    "selected_inclination_deg": 53.1,
                    "selected_bstar": 0.001,
                })
        return pd.DataFrame(rows)

    def test_wrapped_delta_uses_short_angular_difference(self):
        self.assertAlmostEqual(stage1e.wrapped_delta(1.0, 359.0), 2.0)
        self.assertAlmostEqual(stage1e.wrapped_delta(359.0, 1.0), -2.0)

    def test_partial_pooling_factor_is_between_local_and_global(self):
        ratio = np.array([1.0] * 20 + [2.0] * 5)
        groups = ["A"] * 20 + ["B"] * 5
        factors, fallback = stage1e.estimate_group_factors(ratio, groups, 0.95)
        self.assertGreaterEqual(factors["B"], min(2.0, fallback) - 1e-12)
        self.assertLessEqual(factors["B"], max(2.0, fallback) + 1e-12)
        self.assertGreater(factors["B"], 0.0)

    def test_candidate_bundle_produces_all_models_and_positive_predictions(self):
        frame = self.model_fixture()
        bundle = stage1e.fit_candidate_bundle(frame, "abs_delta_T_km", 0.95)
        predictions = bundle.predict_all(frame)
        self.assertEqual(set(predictions), set(stage1e.MODEL_NAMES))
        for values in predictions.values():
            self.assertEqual(len(values), len(frame))
            self.assertTrue(np.isfinite(values).all())
            self.assertTrue((values > 0).all())

    def test_causal_feature_builder_never_uses_later_publication(self):
        raw = [
            {
                "NORAD_CAT_ID": "1", "GP_ID": "10", "EPOCH": "2026-04-01T00:00:00Z",
                "CREATION_DATE": "2026-04-01T01:00:00Z", "MEAN_MOTION": "15.3",
                "ECCENTRICITY": "0.0002", "INCLINATION": "53.1", "RA_OF_ASC_NODE": "10",
                "ARG_OF_PERICENTER": "20", "MEAN_ANOMALY": "30", "BSTAR": "0.001",
            },
            {
                "NORAD_CAT_ID": "1", "GP_ID": "11", "EPOCH": "2026-04-01T06:00:00Z",
                "CREATION_DATE": "2026-04-01T07:00:00Z", "MEAN_MOTION": "15.31",
                "ECCENTRICITY": "0.00021", "INCLINATION": "53.11", "RA_OF_ASC_NODE": "11",
                "ARG_OF_PERICENTER": "21", "MEAN_ANOMALY": "31", "BSTAR": "0.0011",
            },
        ]
        frame = pd.DataFrame({
            "NORAD_CAT_ID": ["1"],
            "evaluation_time": [pd.Timestamp("2026-04-01T05:00:00Z")],
            "ordinary_gp_id": ["10"],
            "is_stage1c_regime_candidate": [False],
            "stage1c_episode_id": [""],
        })
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ordinary.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with patch.object(stage1e, "ORDINARY_RAW_PATH", path):
                features, audit = stage1e.build_causal_features(frame)
        self.assertEqual(features.iloc[0].selected_gp_id, "10")
        self.assertEqual(features.iloc[0].causal_candidate_count, 1)
        self.assertEqual(audit["selected_future_publication"], 0)
        self.assertEqual(audit["feature_future_gp_access"], 0)

    def test_rms_candidate_is_explicitly_non_operational(self):
        frame = self.model_fixture()
        calibration = stage1e.build_full_calibration(frame)
        rms = calibration.loc[calibration.model == "M_RMS_DIAGNOSTIC"]
        self.assertFalse(rms.empty)
        self.assertTrue((rms.covariate_role == "REFERENCE_ONLY").all())
        self.assertNotIn("M_RMS_DIAGNOSTIC", stage1e.OPERATIONAL_MODELS)


if __name__ == "__main__":
    unittest.main()
