#!/usr/bin/env python
"""Diagnose if sync_repo_cache is actually checking out different commits."""

import subprocess
import sys
from pathlib import Path

# Find the cache directory used by Metadata-Pipeline
METADATA_PIPELINE_ROOT = Path('.').resolve().parent / 'Metadata-Pipeline-main'
sys.path.insert(0, str(METADATA_PIPELINE_ROOT))

from Metadata_Extractor.core.git_engine import REPO_CACHE_ROOT

owner = "DhruvHegde"
repo = "Voice_based-_Tic-Tac-Toe"
cache_dir = REPO_CACHE_ROOT / f"{owner}__{repo}"

commits = [
    "bc95c8bede99362595460d84063834f49c840fdd",
    "0d02521bb73e94061031821a159d70a12e6c7e09",
    "da612b5d993c63c6f7f0f5c39b0dbb331ca0fbab",
    "1edfe40ae5d16a883eeeda58ca1ac0e00a9394b7",
    "f73c358583bd64898b080838b01303f83ae93d15",
]

print(f"Cache directory: {cache_dir}")
print(f"Exists: {cache_dir.exists()}")
print("\n" + "=" * 80)

if cache_dir.exists():
    print("CHECKING OUT DIFFERENT COMMITS AND VERIFYING STATE:\n")
    
    for sha in commits:
        print(f"Checking out {sha[:7]}...")
        
        # Checkout the commit
        result = subprocess.run(
            f'git checkout --quiet --force "{sha}"',
            cwd=cache_dir,
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"  ✗ Checkout FAILED: {result.stderr}")
            continue
        
        # Clean untracked files
        subprocess.run(
            'git clean --quiet -fd',
            cwd=cache_dir,
            shell=True,
            capture_output=True
        )
        
        # Get current HEAD commit
        head_result = subprocess.run(
            'git rev-parse HEAD',
            cwd=cache_dir,
            shell=True,
            capture_output=True,
            text=True
        )
        
        current_sha = head_result.stdout.strip()
        
        if current_sha == sha:
            print(f"  ✓ Successfully checked out {sha[:7]}")
        else:
            print(f"  ✗ Mismatch! Expected {sha[:7]}, but HEAD is {current_sha[:7]}")
        
        # List files to see if they changed
        result = subprocess.run(
            'git ls-tree -r HEAD --name-only | wc -l',
            cwd=cache_dir,
            shell=True,
            capture_output=True,
            text=True
        )
        
        file_count = result.stdout.strip()
        print(f"    Files in this commit: {file_count}")
        
        # Show a few files
        result = subprocess.run(
            'git ls-tree -r HEAD --name-only | head -3',
            cwd=cache_dir,
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            print(f"    First files:")
            for line in result.stdout.strip().split('\n'):
                print(f"      - {line}")

else:
    print("Cache directory doesn't exist yet. Run a prediction first to create it.")
