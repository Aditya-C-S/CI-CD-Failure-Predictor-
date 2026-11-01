#!/usr/bin/env python3
"""Check Neo4j status and content."""

from neo4j import GraphDatabase

try:
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "primehome"))
    with driver.session() as session:
        # Check if Neo4j is running
        result = session.run("MATCH (n) RETURN COUNT(n) as count")
        count = result.single().get("count")
        print(f"✓ Neo4j is running")
        print(f"  Total nodes in database: {count}")
        
        # Check for File nodes
        result = session.run("MATCH (f:File) RETURN COUNT(f) as count")
        file_count = result.single().get("count") or 0
        print(f"  File nodes: {file_count}")
        
        # Check for Function nodes
        result = session.run("MATCH (fn:Function) RETURN COUNT(fn) as count")
        func_count = result.single().get("count") or 0
        print(f"  Function nodes: {func_count}")
        
        # Check for repo_id properties
        result = session.run("MATCH (n {repo_id: 'test/audit'}) RETURN COUNT(n) as count")
        test_audit_count = result.single().get("count") or 0
        print(f"  Nodes with repo_id='test/audit': {test_audit_count}")
        
    driver.close()
    print("\n✓ Neo4j is accessible")
except Exception as e:
    print(f"✗ Neo4j connection failed: {e}")
    print("  Ensure Neo4j is running at localhost:7687")
