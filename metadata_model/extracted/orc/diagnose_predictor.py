#!/usr/bin/env python
"""Diagnostic script to investigate identical predictions across different commits."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Repository info
owner = "DhruvHegde"
repo = "Voice_based-_Tic-Tac-Toe"
repo_id = f"{owner}/{repo}"
github_token = os.getenv("GITHUB_TOKEN")

# Test commits
commits = [
    "bc95c8bede99362595460d84063834f49c840fdd",
    "0d02521bb73e94061031821a159d70a12e6c7e09",
    "da612b5d993c63c6f7f0f5c39b0dbb331ca0fbab",
    "1edfe40ae5d16a883eeeda58ca1ac0e00a9394b7",
    "f73c358583bd64898b080838b01303f83ae93d15",
]

from src.adapters import MetadataAdapter
from src.storage import CheckpointManager

print("=" * 80)
print("METADATA PREDICTOR DIAGNOSIS")
print("=" * 80)

# Check checkpoints first
print("\n[1] Checkpoint Status")
print("-" * 80)
cp_mgr = CheckpointManager()

for sha in commits:
    cp = cp_mgr.get(repo_id, sha)
    if cp:
        pred_result = cp.get("prediction_result", {})
        prob = pred_result.get("failure_probability", "N/A")
        verdict = pred_result.get("verdict", "N/A")
        print(f"✓ {sha[:7]}: cached = PREDICTION_COMPLETE, prob={prob:.4f}, verdict={verdict}")
    else:
        print(f"✗ {sha[:7]}: no checkpoint")

# Now try fresh predictions (will use cache from Metadata-Pipeline)
print("\n[2] Fresh Predictions")
print("-" * 80)

adapter = MetadataAdapter(github_token)

predictions = {}
for sha in commits:
    try:
        print(f"\nPredicting {sha[:7]}...")
        result = adapter.predict(owner, repo, sha)
        
        predictions[sha] = {
            "probability": result.get("failure_probability"),
            "verdict": result.get("verdict"),
            "features": result.get("features", {}),
            "cache_status": result.get("cache_status"),
            "shap_drivers": result.get("shap_drivers", {}),
        }
        
        prob = result.get("failure_probability", 0.0)
        verdict = result.get("verdict", "UNKNOWN")
        print(f"  → probability={prob:.4f}, verdict={verdict}")
        print(f"  → cache_status={result.get('cache_status')}")
        
        # Show first few SHAP drivers
        shap = result.get("shap_drivers", {})
        if shap.get("positive"):
            print(f"  → Top positive: {shap['positive'][:2]}")
        if shap.get("negative"):
            print(f"  → Top negative: {shap['negative'][:2]}")
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        predictions[sha] = None

# Compare probabilities
print("\n[3] Comparison")
print("-" * 80)

if all(p is not None for p in predictions.values()):
    probs = [p["probability"] for p in predictions.values()]
    verdicts = [p["verdict"] for p in predictions.values()]
    
    print(f"\nProbabilities:")
    for sha, pred in predictions.items():
        print(f"  {sha[:7]}: {pred['probability']:.6f}")
    
    print(f"\nVerdicts:")
    for sha, pred in predictions.items():
        print(f"  {sha[:7]}: {pred['verdict']}")
    
    if len(set(probs)) == 1:
        print(f"\n⚠ ALL PROBABILITIES IDENTICAL: {probs[0]:.6f}")
    else:
        print(f"\n✓ Probabilities differ:")
        for i, p in enumerate(set(probs)):
            print(f"  - {p:.6f}")
    
    if len(set(verdicts)) == 1:
        print(f"⚠ ALL VERDICTS IDENTICAL: {verdicts[0]}")
    else:
        print(f"✓ Verdicts differ:")
        for v in set(verdicts):
            print(f"  - {v}")

# Compare feature vectors
print("\n[4] Feature Analysis")
print("-" * 80)

if all(p is not None for p in predictions.values()):
    # Get first valid features dict to see schema
    first_features = predictions[commits[0]]["features"]
    print(f"Total features: {len(first_features)}")
    
    # Compare each feature
    feature_names = sorted(first_features.keys())
    identical_features = []
    varying_features = []
    
    for fname in feature_names:
        values = []
        for sha, pred in predictions.items():
            if pred is not None:
                values.append(pred["features"].get(fname))
        
        if len(set(str(v) for v in values)) == 1:
            identical_features.append((fname, values[0]))
        else:
            varying_features.append((fname, values))
    
    print(f"\nIdentical features ({len(identical_features)}):")
    for fname, value in identical_features[:5]:
        print(f"  - {fname}: {value}")
    if len(identical_features) > 5:
        print(f"  ... and {len(identical_features) - 5} more")
    
    print(f"\nVarying features ({len(varying_features)}):")
    for fname, values in varying_features[:10]:
        print(f"  - {fname}:")
        for sha, val in zip(commits, values):
            print(f"      {sha[:7]}: {val}")
    if len(varying_features) > 10:
        print(f"  ... and {len(varying_features) - 10} more")

print("\n" + "=" * 80)
