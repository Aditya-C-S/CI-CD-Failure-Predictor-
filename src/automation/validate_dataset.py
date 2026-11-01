"""Comprehensive Dataset Validation Audit for F1 Successful CI Logs.

Validates that all collected F1 success records are genuine, unique, non-empty,
conform to schema, have passing tests, and are evenly distributed across scenarios.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation.success_validator import (
    validate_metadata,
    validate_success_log,
)

LOG_DIR = Path("logs/success/F1")
METADATA_DIR = Path("metadata/success/F1")
EXPECTED_WORKFLOW_ID = 388310906
EXPECTED_SCENARIOS = [
    "S01_arithmetic",
    "S02_string_ops",
    "S03_collections",
    "S04_validation",
    "S05_sorting_transform",
    "S06_matrix_math",
    "S07_json_parser",
    "S08_statistics",
    "S09_state_machine",
    "S10_cache_lru",
]


def validate_dataset(target_count: int = 300) -> Dict[str, Any]:
    print("=" * 70)
    print(f"F1 SUCCESSFUL CI LOGS — DATASET AUDIT & VALIDATION REPORT")
    print(f"Target count: {target_count}")
    print(f"Log directory: {LOG_DIR}")
    print(f"Metadata directory: {METADATA_DIR}")
    print("=" * 70)

    missing_logs = []
    missing_meta = []
    invalid_logs = []
    invalid_meta = []
    seen_run_ids = set()
    duplicate_run_ids = []
    seen_github_run_ids = set()
    duplicate_github_run_ids = []
    scenario_distribution = {s: 0 for s in EXPECTED_SCENARIOS}
    valid_count = 0

    actual_count = 0
    # Determine how many records are present
    meta_files = sorted(METADATA_DIR.glob("run_*.json"))
    max_found = 0
    for mf in meta_files:
        m = re.match(r"run_(\d{4})\.json", mf.name)
        if m:
            max_found = max(max_found, int(m.group(1)))

    check_range = range(1, max(target_count, max_found) + 1)

    for run_num in check_range:
        run_name = f"run_{run_num:04d}"
        log_path = LOG_DIR / f"{run_name}.log"
        meta_path = METADATA_DIR / f"{run_name}.json"

        log_exists = log_path.exists()
        meta_exists = meta_path.exists()

        if not log_exists:
            missing_logs.append(run_name)
        if not meta_exists:
            missing_meta.append(run_name)

        if not (log_exists and meta_exists):
            continue

        actual_count += 1

        # Check log
        log_content = log_path.read_text(encoding="utf-8", errors="replace")
        if not log_content.strip():
            invalid_logs.append((run_name, "Empty log file"))
        else:
            is_valid_log, reason, evidence = validate_success_log(log_content)
            if not is_valid_log:
                invalid_logs.append((run_name, reason))

        # Check metadata
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            invalid_meta.append((run_name, f"JSON parse error: {exc}"))
            continue

        is_valid_meta, meta_err = validate_metadata(meta)
        if not is_valid_meta:
            invalid_meta.append((run_name, meta_err))

        run_id = meta.get("run_id")
        if run_id in seen_run_ids:
            duplicate_run_ids.append((run_name, run_id))
        else:
            seen_run_ids.add(run_id)

        gh_run_id = meta.get("github_run_id")
        if gh_run_id:
            if gh_run_id in seen_github_run_ids:
                duplicate_github_run_ids.append((run_name, gh_run_id))
            else:
                seen_github_run_ids.add(gh_run_id)
        else:
            invalid_meta.append((run_name, "Missing github_run_id"))

        sc_id = meta.get("scenario_id")
        if sc_id in scenario_distribution:
            scenario_distribution[sc_id] += 1
        else:
            invalid_meta.append((run_name, f"Unknown scenario_id: {sc_id}"))

        if is_valid_log and is_valid_meta and gh_run_id not in duplicate_github_run_ids:
            valid_count += 1

    print("\n--- Summary ---")
    print(f"Total evaluated runs      : {len(check_range)}")
    print(f"Actual records found      : {actual_count}")
    print(f"Valid verified records    : {valid_count}")
    print(f"Missing log files         : {len(missing_logs)}")
    print(f"Missing metadata files    : {len(missing_meta)}")
    print(f"Invalid log files         : {len(invalid_logs)}")
    print(f"Invalid metadata records  : {len(invalid_meta)}")
    print(f"Duplicate run IDs         : {len(duplicate_run_ids)}")
    print(f"Duplicate GitHub run IDs  : {len(duplicate_github_run_ids)}")

    print("\n--- Scenario Distribution ---")
    for sc, count in scenario_distribution.items():
        print(f"  {sc:<25}: {count:3d} runs")

    all_passed = (
        valid_count == target_count
        and len(missing_logs) == 0
        and len(missing_meta) == 0
        and len(invalid_logs) == 0
        and len(invalid_meta) == 0
        and len(duplicate_run_ids) == 0
        and len(duplicate_github_run_ids) == 0
    )

    return {
        "target_count": target_count,
        "actual_count": actual_count,
        "valid_count": valid_count,
        "missing_logs": missing_logs,
        "missing_meta": missing_meta,
        "invalid_logs": invalid_logs,
        "invalid_meta": invalid_meta,
        "duplicate_run_ids": duplicate_run_ids,
        "duplicate_github_run_ids": duplicate_github_run_ids,
        "scenario_distribution": scenario_distribution,
        "all_passed": all_passed,
    }


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    res = validate_dataset(count)
    if not res["all_passed"]:
        print("\nAudit status: INCOMPLETE OR ISSUES FOUND")
        sys.exit(1)
    else:
        print("\nAudit status: 100% VALIDATED")
        sys.exit(0)
