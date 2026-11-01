"""CLI entry point for orchestrator."""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv

from .orchestrator import Orchestrator
from .errors import OrchestratorException


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded .env from {env_path}")
    
    # Required
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN not set in environment")
        sys.exit(1)
    
    # Optional with defaults
    investigation_threshold = float(os.getenv("INVESTIGATION_THRESHOLD", "0.50"))
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    retry_backoff = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.0"))
    
    return {
        "github_token": github_token,
        "investigation_threshold": investigation_threshold,
        "max_retries": max_retries,
        "retry_backoff_seconds": retry_backoff,
    }


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Orchestrator: Metadata prediction + graph synchronization + risk investigation"
    )
    parser.add_argument(
        "repo_id",
        help="Repository identity (owner/repo)",
    )
    parser.add_argument(
        "target_sha",
        help="Target commit SHA",
    )
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Path to local repository (default: current directory)",
    )
    parser.add_argument(
        "--base-sha",
        default=None,
        help="Base commit SHA for graph diff (default: target_sha~1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config()
    
    # Initialize orchestrator
    orchestrator = Orchestrator(
        github_token=config["github_token"],
        investigation_threshold=config["investigation_threshold"],
        max_retries=config["max_retries"],
        retry_backoff_seconds=config["retry_backoff_seconds"],
    )
    
    try:
        # Process commit
        result = orchestrator.process_commit(
            repo_id=args.repo_id,
            target_sha=args.target_sha,
            repo_path=args.repo_path,
            base_sha=args.base_sha,
        )
        
        # Output result
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print_result(result)
        
        return 0
    
    except OrchestratorException as e:
        logger.error(f"Orchestration failed: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


def print_result(result):
    """Pretty-print result."""
    print("\n" + "=" * 70)
    print(f"ORCHESTRATOR RESULT: {result.repository_identity}@{result.target_sha[:7]}")
    print("=" * 70)
    
    print(f"\n[PREDICTION]")
    print(f"  Failure Probability: {result.failure_probability:.2%}")
    print(f"  Verdict: {result.verdict}")
    print(f"  Latency: {result.processing_time_ms:.0f}ms")
    
    if result.shap_drivers:
        print(f"\n[SHAP DRIVERS]")
        if result.shap_drivers.get("positive"):
            print("  Risk Factors (pushing UP):")
            for name, val in result.shap_drivers["positive"][:3]:
                print(f"    + {name}: {val:+.4f}")
        if result.shap_drivers.get("negative"):
            print("  Mitigating Factors (pushing DOWN):")
            for name, val in result.shap_drivers["negative"][:3]:
                print(f"    - {name}: {val:+.4f}")
    
    print(f"\n[GRAPH SYNC]")
    print(f"  Status: {result.graph_status.value}")
    if result.graph_files_changed:
        print(f"  Files Added: {result.graph_files_changed.get('added', 0)}")
        print(f"  Files Modified: {result.graph_files_changed.get('modified', 0)}")
        print(f"  Files Deleted: {result.graph_files_changed.get('deleted', 0)}")
        print(f"  Files Renamed: {result.graph_files_changed.get('renamed', 0)}")
    
    if result.suspicious_files:
        print(f"\n[SUSPICIOUS FILES] ({len(result.suspicious_files)} found)")
        for i, sf in enumerate(result.suspicious_files[:5], 1):
            print(f"  {i}. {sf.file_path} (score: {sf.centrality_score:.2f})")
            for reason in sf.reasons:
                print(f"     • {reason}")
    else:
        print(f"\n[SUSPICIOUS FILES]")
        print(f"  None (risk is below investigation threshold or already cached)")
    
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    sys.exit(main())
