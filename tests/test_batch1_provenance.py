"""tests/test_batch1_provenance.py

Batch 1 Unit & Verification Tests: 38-Feature Metadata Provenance & Completeness
Verifies:
1. Canonical 38-feature classification across 5 provenance categories.
2. Isolation of derived features (code_churn_density, test_to_src_churn_ratio) to prevent inflation.
3. Quantitative completeness calculation (e.g. 16 real features -> 42.1%).
4. Exact reproduction of the 24.12% failure probability from demo run e74c2e.
"""

import unittest
from src.prediction.provenance import (
    ProvenanceCategory,
    evaluate_metadata_provenance,
    get_canonical_provenance_spec,
    CANONICAL_FEATURE_ORDER,
)
from src.prediction.metadata_service import MetadataService


class TestBatch1MetadataProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = MetadataService.get_instance()

    def test_canonical_provenance_spec(self):
        """Verify the 38-feature taxonomy specification is complete and categorized."""
        spec = get_canonical_provenance_spec()
        self.assertEqual(spec["total_features"], 38)
        self.assertEqual(len(spec["feature_order"]), 38)
        self.assertIn("categories", spec)
        self.assertIn("features", spec)

        # Check key category assignments
        features = spec["features"]
        self.assertEqual(features["git_diff_src_churn"]["canonical_category"], ProvenanceCategory.GIT_EXTRACTED.value)
        self.assertEqual(features["code_churn_density"]["canonical_category"], ProvenanceCategory.DERIVED.value)
        self.assertTrue(features["code_churn_density"]["is_derived"])
        self.assertFalse(features["code_churn_density"]["is_observed_measurement"])
        self.assertEqual(features["gh_sloc"]["canonical_category"], ProvenanceCategory.STATIC_ANALYSIS.value)
        self.assertEqual(features["gh_is_pr"]["canonical_category"], ProvenanceCategory.GITHUB_API.value)
        self.assertEqual(features["tr_build_number"]["canonical_category"], ProvenanceCategory.CI_HISTORY.value)

    def test_derived_feature_isolation_prevents_inflation(self):
        """Verify derived features do not count as independent observed features in completeness."""
        # Provide only git churn and derived metrics
        features = {
            "git_diff_src_churn": 140,
            "git_diff_test_churn": 20,
            "total_files_changed": 4,
            "code_churn_density": 35.0,        # derived
            "test_to_src_churn_ratio": 0.1429,  # derived
        }
        hints = {
            "git_diff_src_churn": "derived_from_git",
            "git_diff_test_churn": "derived_from_git",
            "total_files_changed": "derived_from_git",
            "code_churn_density": "derived_from_git",
            "test_to_src_churn_ratio": "derived_from_git",
        }

        prov_map, completeness = evaluate_metadata_provenance(features, source_hints=hints)

        self.assertEqual(completeness.total_features, 38)
        self.assertEqual(completeness.observed_features, 3)  # Only the 3 raw measurements
        self.assertEqual(completeness.derived_features, 2)   # The 2 calculated ratios
        # Completeness should be 3 / 38 = 7.9%
        self.assertAlmostEqual(completeness.completeness_pct, 7.9, places=1)
        self.assertTrue(prov_map["code_churn_density"].is_preset_or_default is False)
        self.assertEqual(prov_map["code_churn_density"].source_category, ProvenanceCategory.DERIVED.value)

    def test_demo_run_feature_lineage_and_completeness(self):
        """Verify 16 Git-measured features yield 42.1% authentic completeness."""
        # 16 features from demo run
        features = {col: 0.0 for col in CANONICAL_FEATURE_ORDER}
        git_measured = [
            "git_diff_src_churn", "git_diff_test_churn", "gh_diff_files_added",
            "gh_diff_files_deleted", "gh_diff_files_modified", "total_files_changed",
            "gh_diff_tests_added", "gh_diff_tests_deleted", "gh_diff_src_files",
            "gh_diff_doc_files", "gh_diff_other_files", "gh_lang_python",
            "gh_lang_java", "gh_lang_ruby", "gh_pr_created_at_year", "gh_pr_created_at_month"
        ]
        hints = {}
        for f in git_measured:
            features[f] = 1.0
            hints[f] = "derived_from_git"

        # Plus 2 derived features
        features["code_churn_density"] = 10.0
        features["test_to_src_churn_ratio"] = 0.2
        hints["code_churn_density"] = "derived_from_git"
        hints["test_to_src_churn_ratio"] = "derived_from_git"

        _, completeness = evaluate_metadata_provenance(features, source_hints=hints)
        self.assertEqual(completeness.observed_features, 16)
        self.assertEqual(completeness.derived_features, 2)
        # 16 / 38 = 42.1%
        self.assertAlmostEqual(completeness.completeness_pct, 42.1, places=1)

    def test_reproduce_demo_run_24_12_pct(self):
        """
        Verify exact reproduction of the 24.12% failure probability from demo run e74c2e
        on demo-order-service commit e66c1180...
        """
        demo_run_features = {
            "gh_is_pr": 1.0,
            "gh_lang_java": 0.0,
            "gh_lang_python": 1.0,
            "gh_lang_ruby": 0.0,
            "git_prev_commit_resolution_status_merge_found": 0.0,
            "git_prev_commit_resolution_status_no_previous_build": 0.0,
            "gh_num_issue_comments": 14.0,
            "gh_num_commit_comments": 3.0,
            "gh_num_pr_comments": 12.0,
            "log_team_size": 3.5,
            "log_built_commits": 6.8,
            "gh_repo_age": 450.0,
            "gh_repo_num_commits": 1250.0,
            "tr_build_number": 340.0,
            "gh_sloc": 45000.0,
            "git_diff_src_churn": 70.0,
            "git_diff_test_churn": 70.0,
            "gh_diff_files_added": 0.0,
            "gh_diff_files_deleted": 0.0,
            "gh_diff_files_modified": 2.0,
            "gh_diff_tests_added": 0.0,
            "gh_diff_tests_deleted": 0.0,
            "gh_diff_src_files": 1.0,
            "gh_diff_doc_files": 0.0,
            "gh_diff_other_files": 1.0,
            "gh_num_commits_on_files_touched": 42.0,
            "gh_test_lines_per_kloc": 45.0,
            "gh_test_cases_per_kloc": 3.2,
            "gh_asserts_cases_per_kloc": 8.5,
            "gh_by_core_team_member": 0.0,
            "total_files_changed": 2.0,
            "code_churn_density": 35.0,
            "test_to_src_churn_ratio": 1.0,
            "has_previous_build": 1.0,
            "gh_pr_created_at_year": 2026.0,
            "gh_pr_created_at_month": 10.0,
            "pr_dayofweek": 5.0,
            "git_merged_with_present": 0.0,
        }

        pred = self.service.predict(demo_run_features)
        # Expected calibrated failure probability is 24.12%
        self.assertAlmostEqual(pred["failure_probability_pct"], 24.12, delta=0.05)
        self.assertEqual(pred["verdict"], "FAST-TRACK")
        # Check SHAP drivers are populated
        self.assertIn("positive", pred["shap_drivers"])
        self.assertIn("negative", pred["shap_drivers"])
        self.assertGreater(len(pred["shap_drivers"]["positive"]), 0)


if __name__ == "__main__":
    unittest.main()
