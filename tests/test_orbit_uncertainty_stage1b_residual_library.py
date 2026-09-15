import unittest
from argparse import Namespace
from datetime import datetime, timezone

import numpy as np

import scripts.run_orbit_uncertainty_stage1b_residual_library as stage1b

residual_components = stage1b.residual_components
selection_tie_break = stage1b.selection_tie_break
freshness_bin_label = stage1b.freshness_bin_label


class Stage1BResidualLibraryTests(unittest.TestCase):
    def tearDown(self):
        stage1b.configure_runtime(self.runtime_args())

    @staticmethod
    def runtime_args(**overrides):
        values = {
            "window_tag": stage1b.DEFAULT_WINDOW_TAG,
            "formal_start": stage1b.DEFAULT_FORMAL_START,
            "formal_stop": stage1b.DEFAULT_FORMAL_STOP_EXCLUSIVE,
            "expected_formal_rows": 5675,
            "supgp_dir": stage1b.APRIL_SUPGP_DIR.as_posix(),
            "design_manifest": None,
            "acquisition_manifest": None,
            "reference_manifest": None,
            "reference_quality": None,
            "causal_audit": None,
            "cohort_selection": None,
            "readiness_adjudication_manifest": None,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_selection_tie_break_reports_deterministic_level(self):
        evaluation = datetime(2026, 4, 2, tzinfo=timezone.utc)
        records = [
            {"CREATION_DATE": "2026-04-01T10:00:00Z", "EPOCH": "2026-04-01T08:00:00Z", "GP_ID": "10"},
            {"CREATION_DATE": "2026-04-01T10:00:00Z", "EPOCH": "2026-04-01T09:00:00Z", "GP_ID": "11"},
        ]
        self.assertEqual(selection_tie_break(records, evaluation), "LATEST_CREATION_DATE_THEN_EPOCH")
        records.append({"CREATION_DATE": "2026-04-01T10:00:00Z", "EPOCH": "2026-04-01T09:00:00Z", "GP_ID": "12"})
        self.assertEqual(selection_tie_break(records, evaluation), "LATEST_CREATION_DATE_THEN_EPOCH_THEN_GP_ID")

    def test_residual_components_reconstruct_cartesian_norms(self):
        reference_position = np.array([7000.0, 100.0, -20.0])
        reference_velocity = np.array([-0.1, 7.5, 0.8])
        ordinary_position = reference_position + np.array([1.2, -3.4, 0.8])
        ordinary_velocity = reference_velocity + np.array([0.001, -0.002, 0.003])
        values = residual_components(
            ordinary_position,
            ordinary_velocity,
            reference_position,
            reference_velocity,
        )
        self.assertLess(values["rtn_orthonormality_error"], 1e-12)
        self.assertLess(values["position_reconstruction_error"], 1e-12)
        self.assertLess(values["velocity_reconstruction_error"], 1e-12)
        self.assertTrue(np.isfinite(values["dr_rtn"]).all())
        self.assertTrue(np.isfinite(values["dv_rtn"]).all())
        self.assertLess(values["rtn_R_unit_norm_error"], 1e-12)
        self.assertLess(values["rtn_T_unit_norm_error"], 1e-12)
        self.assertLess(values["rtn_N_unit_norm_error"], 1e-12)
        self.assertLess(abs(values["rtn_R_dot_T"]), 1e-12)
        self.assertLess(abs(values["rtn_R_dot_N"]), 1e-12)
        self.assertLess(abs(values["rtn_T_dot_N"]), 1e-12)
        self.assertLess(values["rtn_right_handedness_error"], 1e-12)
        np.testing.assert_allclose(values["dr"], ordinary_position - reference_position)
        np.testing.assert_allclose(values["dv"], ordinary_velocity - reference_velocity)

    def test_may_window_parameterization_changes_only_runtime_context(self):
        stage1b.configure_runtime(self.runtime_args(
            window_tag="20260501_20260531",
            formal_start="2026-05-01T00:00:00Z",
            formal_stop="2026-06-01T00:00:00Z",
            expected_formal_rows=6181,
            supgp_dir="data/orbit_uncertainty_stage1/respecialdatarequest (4)",
        ))
        self.assertEqual(stage1b.WINDOW_TAG, "20260501_20260531")
        self.assertEqual(stage1b.FORMAL_INTERVAL, "[2026-05-01T00:00:00Z, 2026-06-01T00:00:00Z)")
        self.assertEqual(stage1b.EXPECTED_FORMAL_ROWS, 6181)
        self.assertEqual(
            stage1b.DATASET_PATH.as_posix(),
            "outputs/datasets/orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv",
        )
        self.assertIsNone(stage1b.DESIGN_MANIFEST)

    def test_june_runtime_binds_readiness_without_changing_output_convention(self):
        stage1b.configure_runtime(self.runtime_args(
            window_tag="20260601_20260630",
            formal_start="2026-06-01T00:00:00Z",
            formal_stop="2026-07-01T00:00:00Z",
            expected_formal_rows=5927,
            supgp_dir="data/orbit_uncertainty_stage1/june",
            readiness_adjudication_manifest="outputs/metrics/orbit_uncertainty_stage1_june_readiness_protocol_adjudication_manifest.json",
        ))
        self.assertEqual(stage1b.EXPECTED_FORMAL_ROWS, 5927)
        self.assertEqual(
            stage1b.READINESS_ADJUDICATION_MANIFEST.as_posix(),
            "outputs/metrics/orbit_uncertainty_stage1_june_readiness_protocol_adjudication_manifest.json",
        )
        self.assertEqual(
            stage1b.DATASET_PATH.as_posix(),
            "outputs/datasets/orbit_uncertainty_stage1b_20260601_20260630_rtn_residual_library.csv",
        )

    def test_frozen_freshness_bin_boundaries(self):
        self.assertEqual(freshness_bin_label(0.0), "OUTSIDE_SUPPORT")
        self.assertEqual(freshness_bin_label(6.0), "0-6h")
        self.assertEqual(freshness_bin_label(6.0001), "6-9h")
        self.assertEqual(freshness_bin_label(36.0), "24-36h")
        self.assertEqual(freshness_bin_label(36.0001), "OUTSIDE_SUPPORT")

    def test_canonical_schema_has_readiness_metadata_and_no_stage1f_scores(self):
        for field in (
            "element_age_hours",
            "publication_age_hours",
            "stage1f_support_status",
            "within_stage1f_support",
            "engineering_staleness_gt72h",
        ):
            self.assertIn(field, stage1b.DATASET_FIELDS)
        for forbidden in (
            "ellipsoid_score",
            "box_score",
            "p95_coverage",
            "p99_coverage",
            "orbit_distinct_classification",
        ):
            self.assertNotIn(forbidden, stage1b.DATASET_FIELDS)


if __name__ == "__main__":
    unittest.main()
