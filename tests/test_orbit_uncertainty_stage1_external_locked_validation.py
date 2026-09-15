import unittest
from pathlib import Path

from scripts import run_orbit_uncertainty_stage1_external_202605_locked_validation as external


class Stage1ExternalLockedValidationPreflightTests(unittest.TestCase):
    def test_calibration_note_parsers(self):
        self.assertAlmostEqual(external.parse_fallback("partial pooling; fallback=1.234e-2"), 0.01234)
        self.assertEqual(
            external.parse_risk_cutpoints("risk probability cutpoints=(0.125, 0.875)"),
            (0.125, 0.875),
        )
        with self.assertRaises(ValueError):
            external.parse_fallback("no frozen fallback")
        with self.assertRaises(ValueError):
            external.parse_risk_cutpoints("no frozen cutpoints")

    def test_classifier_export_detects_incomplete_april_pipeline(self):
        association = [{
            "section": "full_fit_logistic_coefficient",
            "feature": "publication_age_hours",
            "standardized_logistic_coefficient": "0.1",
        }]
        gaps = external.classifier_export_gaps(association, serialized_candidates=[])
        self.assertEqual(
            gaps,
            [
                "logistic_intercept",
                "StandardScaler.mean_",
                "StandardScaler.scale_",
                "SimpleImputer.statistics_",
                "serialized_fitted_pipeline_or_equivalent_complete_parameter_record",
            ],
        )

    def test_frozen_artifacts_make_m0_m1_m2_ready_and_m3_m4_blocked(self):
        calibration = external.load_csv(external.APRIL_STAGE1E_CALIBRATION)
        association = external.load_csv(external.APRIL_STAGE1E_ASSOCIATION)
        rows, details = external.inspect_parameter_artifacts(calibration, association)
        by_model = {row["model"]: row for row in rows}

        for model in ("M0", "M0_DESCRIPTIVE", "M1", "M2"):
            self.assertEqual(by_model[model]["recoverability"], "READY")
        self.assertEqual(by_model["M3"]["recoverability"], "BLOCKED")
        self.assertEqual(by_model["M4"]["recoverability"], "BLOCKED")
        self.assertEqual(by_model["M1"]["parameter_count"], 48)
        self.assertEqual(by_model["M2"]["parameter_count"], 168)
        self.assertEqual(by_model["M3"]["parameter_count"], 48)
        self.assertEqual(by_model["M4"]["parameter_count"], 216)
        self.assertEqual(details["counts"]["classifier_coefficient_rows"], 16)
        self.assertTrue(details["classifier_coefficient_features_exact"])
        self.assertEqual(details["serialized_model_candidates"], [])

    def test_may_support_split_is_exact_and_retains_all_rows(self):
        support = external.audit_may_support()
        self.assertEqual(support["rows"], 6181)
        self.assertEqual(support["nominal_rows"], 6181)
        self.assertEqual(support["primary_external_validation_rows"], 6094)
        self.assertEqual(support["outside_april_calibrated_freshness_support_rows"], 87)

    def test_april_protection_and_may_stage1a_bindings_are_intact(self):
        may_manifest = external.load_json(external.MAY_STAGE1B_MANIFEST)
        inventory = external.load_april_protection_inventory(may_manifest)
        self.assertEqual(len(inventory), 81)
        for row in inventory:
            path = Path(row["path"])
            self.assertTrue(path.exists())
            self.assertEqual(external.sha256(path), row["sha256"])
            self.assertEqual(path.stat().st_size, row["size_bytes"])

        matched, audit = external.verify_bound_references(may_manifest["input_manifests"])
        self.assertTrue(matched)
        self.assertEqual(len(audit), 4)

    def test_blocked_report_is_valid_chinese_and_has_no_completion_claim(self):
        report = external.build_blocked_report(
            external.APRIL_DATASET_SHA,
            "119F2DAA3896476E120F010A436D0B250E404D41326B57FAABFEAA9F2F73EF3F",
            {
                "rows": 6181,
                "primary_external_validation_rows": 6094,
                "outside_april_calibrated_freshness_support_rows": 87,
            },
            81,
            4,
            16,
            ["logistic_intercept"],
        )
        self.assertIn("参数冻结预检报告", report)
        self.assertIn("MAY_LOCKED_EXTERNAL_VALIDATION_BLOCKED_APRIL_PARAMETER_PROVENANCE", report)
        self.assertIn("May-derived fitted parameter count=`0`", report)
        self.assertNotIn("状态：`MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE`", report)


if __name__ == "__main__":
    unittest.main()
