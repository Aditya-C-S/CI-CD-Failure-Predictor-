### Commands Available

# 1. Parse Directory into Neo4j
python cli.py parse /path/to/project/ --clear

# 2. Enrich the Graph with GROQ Summaries
python cli.py enrich

# 3. Incrementally Update (Git Diffs) with Continual Graph Learning
python cli.py update /path/to/project/

# 4. Generate the System Architecture README
python cli.py generate-docs --file /path/to/README.md

# 5. Export Architecture Diagrams (Supports mermaid (default), plantuml, drawio)
python cli.py export --fmt mermaid --file /path/to/architecture.mermaid
python cli.py export --fmt plantuml --file /path/to/architecture.puml
python cli.py export --fmt drawio --file /path/to/architecture.drawio.xml
python cli.py export --method static     # Deterministic approach
python cli.py export --method langchain  # LLM-based approach

# 6. Serve over MCP Protocol
python cli.py serve