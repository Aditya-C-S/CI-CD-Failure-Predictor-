
from pathlib import Path
from code_parser.extractor import Extractor
import json

# Change this to the project folder you want to parse.
PROJECT_PATH = r"C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen"

project = Path(PROJECT_PATH)

if not project.is_dir():
    raise SystemExit(f"Project folder does not exist: {project}")

print(f"Parsing project: {project.resolve()}")

extractor = Extractor()
extractor.parse_directory(str(project))
graph = extractor.get_graph()

nodes = graph.get("nodes", [])
edges = graph.get("edges", [])

print("\n========== GRAPH SUMMARY ==========")
print(f"Nodes: {len(nodes)}")
print(f"Edges: {len(edges)}")

print("\n========== NODE TYPES ==========")
node_types = {}
for node in nodes:
    node_type = node.get("label", node.get("type", "Unknown"))
    node_types[node_type] = node_types.get(node_type, 0) + 1

for name, count in sorted(node_types.items()):
    print(f"{name}: {count}")

print("\n========== SAMPLE NODES ==========")
for node in nodes[:10]:
    print(json.dumps(node, indent=2, default=str))

print("\n========== SAMPLE EDGES ==========")
for edge in edges[:10]:
    print(json.dumps(edge, indent=2, default=str))

# Save the extracted graph so you can inspect it.
output_path = Path("parsed_graph.json")
output_path.write_text(
    json.dumps(graph, indent=2, default=str),
    encoding="utf-8"
)

print(f"\nFull graph saved to: {output_path.resolve()}")
