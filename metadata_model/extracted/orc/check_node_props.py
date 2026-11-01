from neo4j import GraphDatabase
import sys

print("Connecting to Neo4j...", flush=True)
try:
    driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'primehome'))
    print("Connected!", flush=True)
    with driver.session() as session:
        # Get File node properties
        print("Querying File nodes...", flush=True)
        result = session.run('''
            MATCH (f:File)
            RETURN keys(f) as props
            LIMIT 1
        ''')
        record = result.single()
        print(f"Record: {record}", flush=True)
        if record:
            props = sorted(record.get('props', []))
            print('File node properties:', props, flush=True)
            print('Has repo_id:', 'repo_id' in props, flush=True)
        else:
            print("No File records", flush=True)
        
        # Get Function node properties
        print("Querying Function nodes...", flush=True)
        result = session.run('''
            MATCH (fn:Function)
            RETURN keys(fn) as props
            LIMIT 1
        ''')
        record = result.single()
        if record:
            props = sorted(record.get('props', []))
            print('Function node properties:', props, flush=True)
            print('Has repo_id:', 'repo_id' in props, flush=True)
        else:
            print("No Function records", flush=True)

    driver.close()
    print("Done", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)
    import traceback
    traceback.print_exc()
