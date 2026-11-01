"""Verify live Neo4j connection, authentication, and database name."""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv("metadata_model/extracted/orc/.env")

uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USERNAME", "neo4j")
pwd = os.getenv("NEO4J_PASSWORD")
db = os.getenv("NEO4J_DATABASE", "graphdoc")

print(f"Connecting to URI: {uri}")
print(f"User: {user}")
print(f"Target database: {db}")

driver = GraphDatabase.driver(uri, auth=(user, pwd))
driver.verify_connectivity()
print("[OK] Bolt connectivity verified")

with driver.session(database=db) as session:
    res = session.run("CALL db.info() YIELD name RETURN name")
    row = res.single()
    db_name = row["name"] if row else "unknown"
    print(f"[OK] Connected to database: {db_name}")
    assert db_name == "graphdoc", f"Expected 'graphdoc', but got '{db_name}'"

    # Verify query execution
    res2 = session.run("SHOW CONSTRAINTS")
    constraints = [r.data() for r in res2]
    print(f"[OK] Constraints query executed successfully (Count: {len(constraints)})")

driver.close()
print("[OK] All connection checks passed!")
