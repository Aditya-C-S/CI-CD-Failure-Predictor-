#!/usr/bin/env python3
"""Check Neo4j environment for integration testing."""

from neo4j import GraphDatabase
import sys

try:
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    with driver.session() as session:
        # Check total nodes
        result = session.run("MATCH (n) RETURN COUNT(n) as count")
        total = result.single().get("count")
        
        # Check node types
        result = session.run("""
            MATCH (n)
            RETURN labels(n)[0] as type, COUNT(*) as count
            GROUP BY type
        """)
        
        print("=" * 80)
        print("NEO4J ENVIRONMENT CHECK")
        print("=" * 80)
        print("✓ Neo4j connected")
        print(f"  Total nodes: {total}")
        print("\n  Node types:")
        for record in result:
            print(f"    {record.get('type')}: {record.get('count')}")
        
        # Check for test repositories
        result = session.run("""
            MATCH (n {repo_id: 'test/audit'})
            RETURN COUNT(n) as count
        """)
        test_audit = result.single().get("count") or 0
        print(f"\n  Nodes with repo_id='test/audit': {test_audit}")
        
        # Check for any repo_id values
        result = session.run("""
            MATCH (n)
            WHERE n.repo_id IS NOT NULL
            RETURN DISTINCT n.repo_id as repo_id
        """)
        
        repos = [record.get("repo_id") for record in result]
        if repos:
            print(f"\n  Repositories in database:")
            for repo in sorted(repos):
                print(f"    - {repo}")
        else:
            print(f"\n  No repositories with repo_id property found")
            
    driver.close()
    print("\n✓ Neo4j ready for integration testing")
    sys.exit(0)
    
except Exception as e:
    print(f"✗ Neo4j error: {e}")
    print("\nPrerequisites:")
    print("  - Neo4j must be running at localhost:7687")
    print("  - Credentials: neo4j / primehome")
    sys.exit(1)
