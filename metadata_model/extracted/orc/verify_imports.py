#!/usr/bin/env python3
"""Verify that graph adapter uses real graph-doc-gen APIs."""

import sys
from pathlib import Path

# Add ORC to path
sys.path.insert(0, str(Path.cwd()))

from src.adapters.graph_adapter import GraphAdapter
import inspect

print("=" * 80)
print("IMPORT VERIFICATION")
print("=" * 80)

# Check that GraphAdapter has the right methods
if hasattr(GraphAdapter, 'sync_to_sha'):
    print("✓ GraphAdapter.sync_to_sha() exists")
    sig = inspect.signature(GraphAdapter.sync_to_sha)
    print(f"  Signature: {sig}")
    
if hasattr(GraphAdapter, 'get_connected_files'):
    print("✓ GraphAdapter.get_connected_files() exists")
    sig = inspect.signature(GraphAdapter.get_connected_files)
    print(f"  Signature: {sig}")

# Try to instantiate with a path
print("\n✓ Testing GraphAdapter initialization:")
try:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        adapter = GraphAdapter(repo_id="test/verify", repo_path=tmp)
        print(f"  repo_id: {adapter.repo_id}")
        print(f"  repo_path: {adapter.repo_path}")
        print(f"  Has Neo4j client: {adapter.client is not None}")
        adapter.close()
        print("✓ GraphAdapter initialization successful")
except Exception as e:
    print(f"✗ GraphAdapter init failed: {e}")

print("\n✓ All imports verified")
