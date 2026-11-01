#!/usr/bin/env python3
"""Test all prerequisites for end-to-end execution."""

import sys
from pathlib import Path

# Setup paths
METADATA_PIPELINE_ROOT = Path(__file__).parent.parent / "Metadata-Pipeline-main"
GRAPH_DOC_GEN_ROOT = Path(__file__).parent.parent / "graph-doc-gen-main"
ORC_ROOT = Path(__file__).parent

sys.path.insert(0, str(METADATA_PIPELINE_ROOT))
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT))
sys.path.insert(0, str(ORC_ROOT))

print("=" * 70)
print("PREREQUISITE CHECK FOR END-TO-END EXECUTION")
print("=" * 70)

# Test 1: PredictorService
print("\n[1/5] Testing PredictorService initialization...")
try:
    from Inference_Engine.predictor_service import PredictorService
    predictor = PredictorService()
    print("    ✅ PredictorService loaded successfully")
except Exception as e:
    print(f"    ❌ FAILED: {e}")
    sys.exit(1)

# Test 2: Neo4j Connection
print("\n[2/5] Testing Neo4j connection...")
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) as count")
        count = result.single()[0]
    driver.close()
    print(f"    ✅ Neo4j connected. Nodes in DB: {count}")
except Exception as e:
    print(f"    ❌ FAILED: {e}")
    sys.exit(1)

# Test 3: Graph-Doc-Gen Extractor
print("\n[3/5] Testing graph-doc-gen Extractor...")
try:
    from code_parser.extractor import Extractor
    from database.neo4j_client import Neo4jClient
    client = Neo4jClient()
    extractor = Extractor(neo4j_client=client)
    print("    ✅ Extractor initialized successfully")
    client.close()
except Exception as e:
    print(f"    ❌ FAILED: {e}")
    sys.exit(1)

# Test 4: Metadata feature extraction
print("\n[4/5] Testing metadata feature extraction utilities...")
try:
    from Metadata_Extractor.core.git_engine import get_churn_metrics, get_repo_git_metrics
    from Metadata_Extractor.core.static_analyzer import analyze_workspace
    print("    ✅ Feature extraction modules importable")
except Exception as e:
    print(f"    ❌ FAILED: {e}")
    sys.exit(1)

# Test 5: GitHub token
print("\n[5/5] Checking GitHub token availability...")
import os
token = os.getenv("GITHUB_TOKEN")
if token:
    print(f"    ✅ GitHub token found (length: {len(token)})")
else:
    print(f"    ⚠️  No GITHUB_TOKEN env variable. Will need for GitHub metadata extraction.")

print("\n" + "=" * 70)
print("SUMMARY: All core components available")
print("BLOCKER: GitHub token required for full metadata extraction")
print("=" * 70)
