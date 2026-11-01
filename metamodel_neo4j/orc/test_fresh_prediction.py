#!/usr/bin/env python
"""Test fresh prediction for a single commit to diagnose feature extraction."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

owner = "DhruvHegde"
repo = "Voice_based-_Tic-Tac-Toe"
github_token = os.getenv("GITHUB_TOKEN")

# Use one of the test commits
target_sha = "0d02521bb73e94061031821a159d70a12e6c7e09"

print(f"Testing fresh prediction for {target_sha[:7]}")
print("-" * 60)

try:
    # Import after .env is loaded
    from src.adapters import MetadataAdapter
    
    adapter = MetadataAdapter(github_token)
    
    # Call predict (this should not use cache if we're calling fresh)
    print(f"Calling metadata_adapter.predict()...")
    result = adapter.predict(owner, repo, target_sha)
    
    print(f"\nResult:")
    print(f"  failure_probability: {result.get('failure_probability')}")
    print(f"  verdict: {result.get('verdict')}")
    print(f"  cache_status: {result.get('cache_status')}")
    
    # Show features
    features = result.get('features', {})
    print(f"\nFeatures ({len(features)} total):")
    for fname in sorted(features.keys()):
        print(f"  {fname}: {features[fname]}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
