"""src/prediction/provenance.py

Metadata provenance tracking, classification, and completeness analysis
for the 38-feature commit risk LightGBM model.
Ensures transparent lineage without altering the 38-feature model input contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ProvenanceCategory(str, Enum):
    """Origin categories for commit and repository metadata features."""
    GIT_EXTRACTED = "git_extracted"          # Directly measured from commit diff/tree
    STATIC_ANALYSIS = "static_analysis"      # Measured via AST/source code inspection
    GITHUB_API = "github_api"                # Fetched from GitHub REST/GraphQL API
    CI_HISTORY = "ci_history"                # Measured from prior CI build outcomes
    DERIVED = "derived"                      # Mathematically derived from other features
    SCENARIO_PRESET = "scenario_preset"      # Injected from benchmark scenario preset
    DEFAULT_VALUE = "default_value"          # Imputed zero/neutral default (unavailable)


# Canonical 38-feature ordering required by trained LightGBM model
CANONICAL_FEATURE_ORDER: List[str] = [
    "gh_is_pr",
    "gh_lang_java",
    "gh_lang_python",
    "gh_lang_ruby",
    "git_prev_commit_resolution_status_merge_found",
    "git_prev_commit_resolution_status_no_previous_build",
    "gh_num_issue_comments",
    "gh_num_commit_comments",
    "gh_num_pr_comments",
    "log_team_size",
    "log_built_commits",
    "gh_repo_age",
    "gh_repo_num_commits",
    "tr_build_number",
    "gh_sloc",
    "git_diff_src_churn",
    "git_diff_test_churn",
    "gh_diff_files_added",
    "gh_diff_files_deleted",
    "gh_diff_files_modified",
    "gh_diff_tests_added",
    "gh_diff_tests_deleted",
    "gh_diff_src_files",
    "gh_diff_doc_files",
    "gh_diff_other_files",
    "gh_num_commits_on_files_touched",
    "gh_test_lines_per_kloc",
    "gh_test_cases_per_kloc",
    "gh_asserts_cases_per_kloc",
    "gh_by_core_team_member",
    "total_files_changed",
    "code_churn_density",
    "test_to_src_churn_ratio",
    "has_previous_build",
    "gh_pr_created_at_year",
    "gh_pr_created_at_month",
    "pr_dayofweek",
    "git_merged_with_present",
]

# Baseline expected category mappings for genuine repository observation
CANONICAL_CATEGORY_SPEC: Dict[str, ProvenanceCategory] = {
    # Git commit diff metrics
    "git_diff_src_churn": ProvenanceCategory.GIT_EXTRACTED,
    "git_diff_test_churn": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_files_added": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_files_deleted": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_files_modified": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_tests_added": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_tests_deleted": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_src_files": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_doc_files": ProvenanceCategory.GIT_EXTRACTED,
    "gh_diff_other_files": ProvenanceCategory.GIT_EXTRACTED,
    "total_files_changed": ProvenanceCategory.GIT_EXTRACTED,
    "gh_lang_java": ProvenanceCategory.GIT_EXTRACTED,
    "gh_lang_python": ProvenanceCategory.GIT_EXTRACTED,
    "gh_lang_ruby": ProvenanceCategory.GIT_EXTRACTED,
    "gh_num_commits_on_files_touched": ProvenanceCategory.GIT_EXTRACTED,
    "gh_repo_num_commits": ProvenanceCategory.GIT_EXTRACTED,
    "gh_repo_age": ProvenanceCategory.GIT_EXTRACTED,
    "git_merged_with_present": ProvenanceCategory.GIT_EXTRACTED,
    # Derived ratios
    "code_churn_density": ProvenanceCategory.DERIVED,
    "test_to_src_churn_ratio": ProvenanceCategory.DERIVED,
    # Static workspace analysis
    "gh_sloc": ProvenanceCategory.STATIC_ANALYSIS,
    "gh_test_lines_per_kloc": ProvenanceCategory.STATIC_ANALYSIS,
    "gh_test_cases_per_kloc": ProvenanceCategory.STATIC_ANALYSIS,
    "gh_asserts_cases_per_kloc": ProvenanceCategory.STATIC_ANALYSIS,
    # GitHub API / PR activity
    "gh_is_pr": ProvenanceCategory.GITHUB_API,
    "gh_num_issue_comments": ProvenanceCategory.GITHUB_API,
    "gh_num_commit_comments": ProvenanceCategory.GITHUB_API,
    "gh_num_pr_comments": ProvenanceCategory.GITHUB_API,
    "log_team_size": ProvenanceCategory.GITHUB_API,
    "gh_by_core_team_member": ProvenanceCategory.GITHUB_API,
    "gh_pr_created_at_year": ProvenanceCategory.GITHUB_API,
    "gh_pr_created_at_month": ProvenanceCategory.GITHUB_API,
    "pr_dayofweek": ProvenanceCategory.GITHUB_API,
    # CI history
    "tr_build_number": ProvenanceCategory.CI_HISTORY,
    "log_built_commits": ProvenanceCategory.CI_HISTORY,
    "has_previous_build": ProvenanceCategory.CI_HISTORY,
    "git_prev_commit_resolution_status_merge_found": ProvenanceCategory.CI_HISTORY,
    "git_prev_commit_resolution_status_no_previous_build": ProvenanceCategory.CI_HISTORY,
}


@dataclass
class FeatureProvenance:
    """Individual provenance descriptor for a single metadata feature."""
    feature_name: str
    value: Any
    source_category: str
    is_real_evidence: bool
    is_preset_or_default: bool
    missing_status: bool
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetadataCompleteness:
    """Quantitative completeness assessment for the 38-feature vector."""
    total_features: int = 38
    observed_features: int = 0
    derived_features: int = 0
    preset_features: int = 0
    default_features: int = 0
    missing_features: int = 0
    completeness_pct: float = 0.0
    summary_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_metadata_provenance(
    features: Dict[str, Any],
    source_hints: Optional[Dict[str, str]] = None,
    scenario_preset_name: Optional[str] = None,
) -> Tuple[Dict[str, FeatureProvenance], MetadataCompleteness]:
    """
    Examine a 38-feature dictionary, classify each feature's source,
    and compute authentic completeness metrics without inflating derived features.

    Args:
        features: Key-value dictionary containing 38 features.
        source_hints: Optional mapping of feature_name -> hint (e.g. 'derived_from_git', 'preset').
        scenario_preset_name: If features were assembled from a preset, its name.

    Returns:
        Tuple of (provenance_by_feature, completeness_report)
    """
    hints = source_hints or {}
    provenance_map: Dict[str, FeatureProvenance] = {}

    observed_count = 0
    derived_count = 0
    preset_count = 0
    default_count = 0
    missing_count = 0

    for col in CANONICAL_FEATURE_ORDER:
        val = features.get(col)
        hint = hints.get(col, "").lower()

        # Check explicit hints first
        if "derived_from_git" in hint or "git" in hint:
            if col in ("code_churn_density", "test_to_src_churn_ratio"):
                cat = ProvenanceCategory.DERIVED
                is_real = True
                is_preset = False
                is_missing = False
                derived_count += 1
                desc = "Calculated directly from commit git churn measurements"
            else:
                cat = ProvenanceCategory.GIT_EXTRACTED
                is_real = True
                is_preset = False
                is_missing = False
                observed_count += 1
                desc = "Extracted directly from git commit diff and log"
        elif "static" in hint or "workspace" in hint:
            cat = ProvenanceCategory.STATIC_ANALYSIS
            is_real = True
            is_preset = False
            is_missing = False
            observed_count += 1
            desc = "Scanned directly from codebase AST and source files"
        elif "github" in hint:
            cat = ProvenanceCategory.GITHUB_API
            is_real = True
            is_preset = False
            is_missing = False
            observed_count += 1
            desc = "Retrieved from GitHub repository and PR API"
        elif "ci" in hint or "travis" in hint or "workflow" in hint:
            cat = ProvenanceCategory.CI_HISTORY
            is_real = True
            is_preset = False
            is_missing = False
            observed_count += 1
            desc = "Retrieved from prior CI build history"
        elif "preset" in hint or scenario_preset_name:
            cat = ProvenanceCategory.SCENARIO_PRESET
            is_real = False
            is_preset = True
            is_missing = False
            preset_count += 1
            desc = f"Populated from benchmark scenario baseline ({scenario_preset_name or 'preset'})"
        elif "zero" in hint or "default" in hint or val is None:
            cat = ProvenanceCategory.DEFAULT_VALUE
            is_real = False
            is_preset = True
            is_missing = True
            default_count += 1
            missing_count += 1
            desc = "Neutral default zero assigned; real telemetry unavailable"
        else:
            # Fallback based on canonical spec if value is non-zero
            base_cat = CANONICAL_CATEGORY_SPEC.get(col, ProvenanceCategory.DEFAULT_VALUE)
            if base_cat == ProvenanceCategory.DERIVED:
                cat = ProvenanceCategory.DERIVED
                is_real = bool(val is not None and val != 0)
                is_preset = not is_real
                is_missing = not is_real
                if is_real:
                    derived_count += 1
                else:
                    default_count += 1
                    missing_count += 1
                desc = "Derived ratio computed from churn features"
            else:
                if val is None or val == 0.0 or val == 0:
                    cat = ProvenanceCategory.DEFAULT_VALUE
                    is_real = False
                    is_preset = True
                    is_missing = True
                    default_count += 1
                    missing_count += 1
                    desc = "Neutral default zero assigned; real telemetry unavailable"
                else:
                    cat = base_cat
                    is_real = True
                    is_preset = False
                    is_missing = False
                    observed_count += 1
                    desc = f"Identified via {base_cat.value}"

        provenance_map[col] = FeatureProvenance(
            feature_name=col,
            value=val,
            source_category=cat.value,
            is_real_evidence=is_real,
            is_preset_or_default=is_preset,
            missing_status=is_missing,
            description=desc,
        )

    # Calculate authentic completeness percentage:
    # Only independent observed features count toward completeness (denominator = 38).
    # Derived features are reported separately so as not to artificially inflate coverage.
    total = len(CANONICAL_FEATURE_ORDER)
    completeness_pct = round((observed_count / total) * 100.0, 1)

    summary = (
        f"{observed_count}/{total} real features ({completeness_pct}% completeness); "
        f"{derived_count} derived; {preset_count} scenario baseline; {default_count} defaults."
    )

    completeness = MetadataCompleteness(
        total_features=total,
        observed_features=observed_count,
        derived_features=derived_count,
        preset_features=preset_count,
        default_features=default_count,
        missing_features=missing_count,
        completeness_pct=completeness_pct,
        summary_text=summary,
    )

    return provenance_map, completeness


def get_canonical_provenance_spec() -> Dict[str, Any]:
    """Return documentation specification for all 38 features and their expected sources."""
    categories: Dict[str, List[str]] = {}
    for col, cat in CANONICAL_CATEGORY_SPEC.items():
        categories.setdefault(cat.value, []).append(col)

    return {
        "total_features": len(CANONICAL_FEATURE_ORDER),
        "feature_order": CANONICAL_FEATURE_ORDER,
        "categories": categories,
        "features": {
            col: {
                "name": col,
                "canonical_category": CANONICAL_CATEGORY_SPEC[col].value,
                "is_derived": CANONICAL_CATEGORY_SPEC[col] == ProvenanceCategory.DERIVED,
                "is_observed_measurement": CANONICAL_CATEGORY_SPEC[col] != ProvenanceCategory.DERIVED,
            }
            for col in CANONICAL_FEATURE_ORDER
        },
    }
