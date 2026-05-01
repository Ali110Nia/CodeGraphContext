from codegraphcontext.core.database_kuzu import KuzuDBManager
import time

mgr = KuzuDBManager()
conn = mgr.get_driver().session()

# Create dummy file
conn.run("MERGE (f:File {path: $file_path})", file_path="test.py")
conn.run("MERGE (n:Function {uid: '123', name: 'myfunc', path: 'test.py', line_number: 1})")

batch = [{"name": "myfunc", "line_number": 1}]
query = """
UNWIND $batch AS row
MATCH (f:File {path: $file_path})
MATCH (n:Function {name: row.name, path: $file_path, line_number: row.line_number})
MERGE (f)-[:CONTAINS]->(n)
"""
try:
    conn.run(query, batch=batch, file_path="test.py")
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")

