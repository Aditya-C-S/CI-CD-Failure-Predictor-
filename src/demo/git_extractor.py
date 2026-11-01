"""src/demo/git_extractor.py

Safe, repository-agnostic Git and Commit metadata feature extractor.
Extracts genuine commit diff statistics, language flags, and change scope,
overlaying them onto documented benchmark scenario presets for historical metrics.
Explicitly tracks feature lineage and provenance without fabricating values.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("demo.git_extractor")

SRC_EXTS = {".py", ".java", ".rb", ".c", ".cpp", ".cc", ".h", ".js", ".ts", ".go", ".rs"}
TEST_PATTERNS = ["test", "tests", "spec", "specs", "check"]
DOC_EXTS = {".md", ".rst", ".txt", ".pdf", ".docx", ".html"}

# Pre-Build 38 Canonical Features Schema
CANONICAL_FEATURES = [
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

# Documented benchmark scenarios for historical/CI context
SCENARIO_PRESETS: Dict[str, Dict[str, Any]] = {
    "clean": {
        "name": "Clean Nominal Commit (Core Author, Active Tests, Mature Repo)",
        "description": "Nominal day-to-day commit with high testing ratio, core author, and established build history.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 1,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 2,
        "gh_num_commit_comments": 0,
        "gh_num_pr_comments": 2,
        "log_team_size": 2.2,
        "log_built_commits": 5.4,
        "gh_repo_age": 950,
        "gh_repo_num_commits": 1200,
        "tr_build_number": 350,
        "gh_sloc": 28000,
        "git_diff_src_churn": 15,
        "git_diff_test_churn": 25,
        "gh_diff_files_added": 0,
        "gh_diff_files_deleted": 0,
        "gh_diff_files_modified": 2,
        "gh_diff_tests_added": 2,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 1,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 0,
        "gh_num_commits_on_files_touched": 8,
        "gh_test_lines_per_kloc": 140.0,
        "gh_test_cases_per_kloc": 10.0,
        "gh_asserts_cases_per_kloc": 32.0,
        "gh_by_core_team_member": 1,
        "total_files_changed": 2,
        "code_churn_density": 7.5,
        "test_to_src_churn_ratio": 1.66,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 3,
        "git_merged_with_present": 0,
    },
    "dependency": {
        "name": "Dependency Failure PR (Package Lock Conflict, Zero Test Churn)",
        "description": "Dependency and package descriptor updates without accompanying test coverage updates.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 0,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 14,
        "gh_num_commit_comments": 3,
        "gh_num_pr_comments": 12,
        "log_team_size": 1.0,
        "log_built_commits": 6.8,
        "gh_repo_age": 450,
        "gh_repo_num_commits": 1250,
        "tr_build_number": 120,
        "gh_sloc": 45000,
        "git_diff_src_churn": 280,
        "git_diff_test_churn": 0,
        "gh_diff_files_added": 2,
        "gh_diff_files_deleted": 1,
        "gh_diff_files_modified": 5,
        "gh_diff_tests_added": 0,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 4,
        "gh_diff_doc_files": 0,
        "gh_diff_other_files": 3,
        "gh_num_commits_on_files_touched": 42,
        "gh_test_lines_per_kloc": 45.0,
        "gh_test_cases_per_kloc": 3.2,
        "gh_asserts_cases_per_kloc": 8.5,
        "gh_by_core_team_member": 0,
        "total_files_changed": 5,
        "code_churn_density": 56.0,
        "test_to_src_churn_ratio": 0.0,
        "has_previous_build": 0,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 4,
        "git_merged_with_present": 0,
    },
    "pytest": {
        "name": "Pytest / Test Failure PR (Test Assertion Deletions, Churn Mismatch)",
        "description": "Severe imbalance between source modifications and test assertions with deleted test fixtures.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 0,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 14,
        "gh_num_commit_comments": 3,
        "gh_num_pr_comments": 12,
        "log_team_size": 4.0,
        "log_built_commits": 6.8,
        "gh_repo_age": 450,
        "gh_repo_num_commits": 1250,
        "tr_build_number": 340,
        "gh_sloc": 45000,
        "git_diff_src_churn": 250,
        "git_diff_test_churn": 15,
        "gh_diff_files_added": 4,
        "gh_diff_files_deleted": 2,
        "gh_diff_files_modified": 7,
        "gh_diff_tests_added": 0,
        "gh_diff_tests_deleted": 3,
        "gh_diff_src_files": 7,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 2,
        "gh_num_commits_on_files_touched": 42,
        "gh_test_lines_per_kloc": 45.0,
        "gh_test_cases_per_kloc": 3.2,
        "gh_asserts_cases_per_kloc": 8.5,
        "gh_by_core_team_member": 0,
        "total_files_changed": 9,
        "code_churn_density": 27.7,
        "test_to_src_churn_ratio": 0.06,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 4,
        "git_merged_with_present": 0,
    },
    "syntax": {
        "name": "Syntax Error PR (High Churn Density, Unverified Logic)",
        "description": "High code churn density in critical modules by external author, elevating risk of syntax errors.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 0,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 14,
        "gh_num_commit_comments": 3,
        "gh_num_pr_comments": 12,
        "log_team_size": 3.5,
        "log_built_commits": 6.8,
        "gh_repo_age": 450,
        "gh_repo_num_commits": 1250,
        "tr_build_number": 340,
        "gh_sloc": 45000,
        "git_diff_src_churn": 200,
        "git_diff_test_churn": 0,
        "gh_diff_files_added": 1,
        "gh_diff_files_deleted": 0,
        "gh_diff_files_modified": 3,
        "gh_diff_tests_added": 0,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 3,
        "gh_diff_doc_files": 0,
        "gh_diff_other_files": 1,
        "gh_num_commits_on_files_touched": 42,
        "gh_test_lines_per_kloc": 45.0,
        "gh_test_cases_per_kloc": 3.2,
        "gh_asserts_cases_per_kloc": 8.5,
        "gh_by_core_team_member": 0,
        "total_files_changed": 4,
        "code_churn_density": 45.0,
        "test_to_src_churn_ratio": 0.0,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 4,
        "git_merged_with_present": 0,
    },
    "high_risk": {
        "name": "High-Risk PR (Large Churn, External Contributor, Test Deletions)",
        "description": "High failure probability expected due to massive source churn, external author, and deleted test assertions.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 0,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 14,
        "gh_num_commit_comments": 3,
        "gh_num_pr_comments": 12,
        "log_team_size": 3.5,
        "log_built_commits": 6.8,
        "gh_repo_age": 450,
        "gh_repo_num_commits": 1250,
        "tr_build_number": 340,
        "gh_sloc": 45000,
        "git_diff_src_churn": 850,
        "git_diff_test_churn": 0,
        "gh_diff_files_added": 8,
        "gh_diff_files_deleted": 5,
        "gh_diff_files_modified": 11,
        "gh_diff_tests_added": 0,
        "gh_diff_tests_deleted": 2,
        "gh_diff_src_files": 16,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 7,
        "gh_num_commits_on_files_touched": 42,
        "gh_test_lines_per_kloc": 45.0,
        "gh_test_cases_per_kloc": 3.2,
        "gh_asserts_cases_per_kloc": 8.5,
        "gh_by_core_team_member": 0,
        "total_files_changed": 24,
        "code_churn_density": 35.4,
        "test_to_src_churn_ratio": 0.0,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 4,
        "git_merged_with_present": 0,
    },
    "standard_gate": {
        "name": "Standard Gate PR (Moderate Refactor, Core Author, Stable CI)",
        "description": "Standard risk distribution typical of regular day-to-day team PRs.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 1,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 4,
        "gh_num_commit_comments": 1,
        "gh_num_pr_comments": 5,
        "log_team_size": 2.2,
        "log_built_commits": 5.4,
        "gh_repo_age": 750,
        "gh_repo_num_commits": 820,
        "tr_build_number": 190,
        "gh_sloc": 28000,
        "git_diff_src_churn": 140,
        "git_diff_test_churn": 45,
        "gh_diff_files_added": 1,
        "gh_diff_files_deleted": 0,
        "gh_diff_files_modified": 4,
        "gh_diff_tests_added": 1,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 3,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 1,
        "gh_num_commits_on_files_touched": 15,
        "gh_test_lines_per_kloc": 110.0,
        "gh_test_cases_per_kloc": 7.5,
        "gh_asserts_cases_per_kloc": 22.0,
        "gh_by_core_team_member": 1,
        "total_files_changed": 5,
        "code_churn_density": 28.0,
        "test_to_src_churn_ratio": 0.32,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 3,
        "git_merged_with_present": 0,
    },
    "fast_track": {
        "name": "Fast-Track PR (Documentation / High Test Ratio / Senior Author)",
        "description": "Very low risk commit eligible for immediate fast-tracking through CI gates.",
        "gh_is_pr": 1,
        "gh_lang_python": 1,
        "gh_lang_java": 0,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 1,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 1,
        "gh_num_commit_comments": 0,
        "gh_num_pr_comments": 2,
        "log_team_size": 2.0,
        "log_built_commits": 6.5,
        "gh_repo_age": 1200,
        "gh_repo_num_commits": 2400,
        "tr_build_number": 880,
        "gh_sloc": 65000,
        "git_diff_src_churn": 18,
        "git_diff_test_churn": 35,
        "gh_diff_files_added": 0,
        "gh_diff_files_deleted": 0,
        "gh_diff_files_modified": 2,
        "gh_diff_tests_added": 1,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 1,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 0,
        "gh_num_commits_on_files_touched": 8,
        "gh_test_lines_per_kloc": 180.0,
        "gh_test_cases_per_kloc": 12.0,
        "gh_asserts_cases_per_kloc": 45.0,
        "gh_by_core_team_member": 1,
        "total_files_changed": 2,
        "code_churn_density": 9.0,
        "test_to_src_churn_ratio": 1.94,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 2,
        "git_merged_with_present": 0,
    },
    "legacy_subsystem": {
        "name": "Legacy Subsystem PR (Java Core, Deep Dependency Churn)",
        "description": "Multi-module refactor in legacy infrastructure requiring elevated gating verification.",
        "gh_is_pr": 1,
        "gh_lang_python": 0,
        "gh_lang_java": 1,
        "gh_lang_ruby": 0,
        "git_prev_commit_resolution_status_merge_found": 0,
        "git_prev_commit_resolution_status_no_previous_build": 0,
        "gh_num_issue_comments": 8,
        "gh_num_commit_comments": 4,
        "gh_num_pr_comments": 9,
        "log_team_size": 4.1,
        "log_built_commits": 7.2,
        "gh_repo_age": 1600,
        "gh_repo_num_commits": 3500,
        "tr_build_number": 1200,
        "gh_sloc": 120000,
        "git_diff_src_churn": 480,
        "git_diff_test_churn": 60,
        "gh_diff_files_added": 3,
        "gh_diff_files_deleted": 2,
        "gh_diff_files_modified": 9,
        "gh_diff_tests_added": 1,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 11,
        "gh_diff_doc_files": 1,
        "gh_diff_other_files": 2,
        "gh_num_commits_on_files_touched": 35,
        "gh_test_lines_per_kloc": 75.0,
        "gh_test_cases_per_kloc": 4.8,
        "gh_asserts_cases_per_kloc": 14.0,
        "gh_by_core_team_member": 1,
        "total_files_changed": 14,
        "code_churn_density": 34.2,
        "test_to_src_churn_ratio": 0.125,
        "has_previous_build": 1,
        "gh_pr_created_at_year": 2026,
        "gh_pr_created_at_month": 10,
        "pr_dayofweek": 5,
        "git_merged_with_present": 0,
    },
}


class GitMetadataExtractor:
    """Safe inspection of local or remote Git repositories."""

    @staticmethod
    def run_git(cmd: str, cwd: Optional[Path] = None) -> Tuple[bool, str]:
        """Execute git command safely without throwing exceptions."""
        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                shell=True,
                timeout=15,
            )
            return res.returncode == 0, res.stdout.strip()
        except Exception as e:
            logger.warning("Git command failed '%s': %s", cmd, e)
            return False, ""

    @classmethod
    def is_git_repo(cls, path: Path) -> bool:
        success, out = cls.run_git("git rev-parse --is-inside-work-tree", cwd=path)
        return success and out.lower() == "true"

    @classmethod
    def get_commit_info(cls, repo_path: Path, commit_sha: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve commit metadata: author, timestamp, branch, commit message."""
        if not cls.is_git_repo(repo_path):
            return {
                "available": False,
                "commit_sha": commit_sha or "HEAD",
                "author": "demo-author",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Demo simulated commit",
                "branch": "main",
            }

        ref = commit_sha if commit_sha else "HEAD"
        cmd = f'git log -1 --format="%H%x09%an%x09%aI%x09%s" {ref}'
        ok, out = cls.run_git(cmd, cwd=repo_path)
        if ok and out:
            parts = out.split("\t")
            sha = parts[0] if len(parts) > 0 else ref
            author = parts[1] if len(parts) > 1 else "Unknown"
            ts = parts[2] if len(parts) > 2 else datetime.now(timezone.utc).isoformat()
            msg = parts[3] if len(parts) > 3 else ""

            # Check branch
            _, branch_out = cls.run_git("git rev-parse --abbrev-ref HEAD", cwd=repo_path)
            branch = branch_out or "main"

            return {
                "available": True,
                "commit_sha": sha,
                "author": author,
                "timestamp": ts,
                "message": msg,
                "branch": branch,
            }
        return {
            "available": False,
            "commit_sha": ref,
            "author": "demo-author",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Local commit",
            "branch": "main",
        }

    @classmethod
    def extract_diff_metrics(
        cls, repo_path: Path, commit_sha: Optional[str] = None
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Extract genuine diff features from the commit or uncommitted working copy.
        Returns (derived_features, changed_files).
        """
        derived: Dict[str, Any] = {}
        changed_files: List[str] = []

        if not cls.is_git_repo(repo_path):
            return {}, []

        ref = commit_sha if commit_sha else "HEAD"
        # Get numstat
        ok, numstat = cls.run_git(f"git show --numstat --format= {ref}", cwd=repo_path)
        if not ok or not numstat:
            # Try diff against HEAD~1
            ok, numstat = cls.run_git("git diff HEAD~1 --numstat", cwd=repo_path)

        # Get name status for file addition/deletion
        ok_status, name_status = cls.run_git(f"git show --name-status --format= {ref}", cwd=repo_path)
        if not ok_status or not name_status:
            _, name_status = cls.run_git("git diff HEAD~1 --name-status", cwd=repo_path)

        src_churn = 0
        test_churn = 0
        files_added = 0
        files_deleted = 0
        files_modified = 0
        src_files = 0
        doc_files = 0
        other_files = 0
        tests_added = 0
        tests_deleted = 0

        languages_seen = {"python": 0, "java": 0, "ruby": 0}

        file_statuses: Dict[str, str] = {}
        for line in name_status.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status_code = parts[0][0]  # 'A', 'M', 'D', 'R'
                filepath = parts[-1]
                file_statuses[filepath] = status_code

        for line in numstat.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added_str, deleted_str, path = parts[0], parts[1], parts[2]
            added = int(added_str) if added_str.isdigit() else 0
            deleted = int(deleted_str) if deleted_str.isdigit() else 0
            churn = added + deleted

            changed_files.append(path)
            ext = Path(path).suffix.lower()
            lower_path = path.lower()
            is_test = any(tp in lower_path for tp in TEST_PATTERNS)

            status = file_statuses.get(path, "M")
            if status == "A":
                files_added += 1
                if is_test:
                    tests_added += 1
            elif status == "D":
                files_deleted += 1
                if is_test:
                    tests_deleted += 1
            else:
                files_modified += 1

            if ext in SRC_EXTS:
                src_churn += churn
                src_files += 1
                if ext == ".py":
                    languages_seen["python"] = 1
                elif ext == ".java":
                    languages_seen["java"] = 1
                elif ext == ".rb":
                    languages_seen["ruby"] = 1
            elif ext in DOC_EXTS:
                doc_files += 1
            else:
                other_files += 1

            if is_test:
                test_churn += churn

        total_files = len(changed_files)
        churn_density = round(src_churn / max(1, total_files), 2)
        test_ratio = round(test_churn / max(1, src_churn), 4)

        now = datetime.now(timezone.utc)
        derived["git_diff_src_churn"] = src_churn
        derived["git_diff_test_churn"] = test_churn
        derived["gh_diff_files_added"] = files_added
        derived["gh_diff_files_deleted"] = files_deleted
        derived["gh_diff_files_modified"] = files_modified
        derived["total_files_changed"] = total_files
        derived["gh_diff_tests_added"] = tests_added
        derived["gh_diff_tests_deleted"] = tests_deleted
        derived["gh_diff_src_files"] = src_files
        derived["gh_diff_doc_files"] = doc_files
        derived["gh_diff_other_files"] = other_files
        derived["code_churn_density"] = churn_density
        derived["test_to_src_churn_ratio"] = test_ratio
        derived["gh_lang_python"] = languages_seen["python"]
        derived["gh_lang_java"] = languages_seen["java"]
        derived["gh_lang_ruby"] = languages_seen["ruby"]
        derived["gh_pr_created_at_year"] = now.year
        derived["gh_pr_created_at_month"] = now.month
        derived["pr_dayofweek"] = now.weekday() + 1

        return derived, changed_files

    @classmethod
    def assemble_features_with_lineage(
        cls,
        repo_path: Optional[Path] = None,
        commit_sha: Optional[str] = None,
        scenario_preset_name: str = "standard_gate",
        is_pr: bool = True,
        manual_override_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Assemble the complete 38-feature vector.
        Explicitly identifies:
          - 'derived': values calculated from git
          - 'scenario_defaults': values supplied by benchmark preset
          - 'feature_sources': label for each feature
          - 'features_analyzed': final 38-feature dictionary passed to the model
        """
        preset_key = scenario_preset_name if scenario_preset_name in SCENARIO_PRESETS else "standard_gate"
        preset = dict(SCENARIO_PRESETS[preset_key])

        derived_metrics: Dict[str, Any] = {}
        changed_files: List[str] = []

        if repo_path and repo_path.exists():
            derived_metrics, changed_files = cls.extract_diff_metrics(repo_path, commit_sha)

        feature_sources: Dict[str, str] = {}
        final_features: Dict[str, Any] = {}

        for col in CANONICAL_FEATURES:
            if manual_override_features and col in manual_override_features and manual_override_features[col] is not None:
                final_features[col] = manual_override_features[col]
                feature_sources[col] = "manual_override"
            elif col in derived_metrics:
                final_features[col] = derived_metrics[col]
                feature_sources[col] = "derived_from_git"
            elif col == "gh_is_pr":
                final_features[col] = 1 if is_pr else 0
                feature_sources[col] = "user_input"
            elif col in preset:
                final_features[col] = preset[col]
                feature_sources[col] = f"demo_scenario_preset ({preset_key})"
            else:
                final_features[col] = 0.0
                feature_sources[col] = "schema_default_zero"

        from src.prediction.provenance import evaluate_metadata_provenance
        prov_map, completeness = evaluate_metadata_provenance(
            features=final_features,
            source_hints=feature_sources,
            scenario_preset_name=preset_key,
        )

        return {
            "features_analyzed": final_features,
            "feature_sources": feature_sources,
            "provenance": {k: v.to_dict() for k, v in prov_map.items()},
            "completeness": completeness.to_dict(),
            "derived_metrics": derived_metrics,
            "scenario_preset": preset_key,
            "scenario_metadata": {
                "name": preset.get("name", preset_key),
                "description": preset.get("description", ""),
            },
            "changed_files": changed_files,
        }
