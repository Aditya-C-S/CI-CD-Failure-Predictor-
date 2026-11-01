# graph-doc-gen – CI/CD Failure Prediction & Suspicious File Localization

Graph-based repository analysis using Neo4j, Tree-sitter, and Git integration.
This codebase has been refocused from general documentation generation into a
**CI/CD Failure Prediction and Suspicious File Localization** backbone.

## Overview

`graph-doc-gen` builds a navigable software-architecture graph from source code,
stores it in Neo4j, and incrementally updates it as developers commit changes.
A future LightGBM-based build-failure predictor will consume Git metadata and
trigger graph-based suspicious-file ranking when predicted failure risk exceeds a
configurable threshold.

Key capabilities (current phase):

- Parse Python, Java, and C/C++ source files into a structural graph (File, Class, Function nodes)
- Upload files, classes, functions, and `CONTAINS` / `CALLS` / `IMPORTS` relationships to Neo4j
- Detect added, modified, deleted, and renamed files between two Git commits via `get_commit_diff`
- Incrementally update the graph using Git diff and Continual Graph Learning (CGL)
- Export architecture diagrams as Mermaid, PlantUML, or Draw.io for project demos
- Leiden community detection available for future suspicious-module grouping

## Requirements

- Python 3.10+
- Neo4j database (local or AuraDB)
- `pip install -r requirements.txt`

## Recommended environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the repository root:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key   # optional – enables node embeddings for CGL
```

Notes:
- `GEMINI_API_KEY` is optional. When absent, node embeddings are disabled and the
  graph-building pipeline continues to work without them.
- `langchain-google-genai` is retained because `export --method langchain` uses it
  for LLM-assisted diagram generation. It is not required for the core graph pipeline.

## CLI commands

Use `python cli.py` followed by one of the commands below.

### 1. Parse source code into Neo4j

```bash
python cli.py parse /path/to/repo --clear
```

- Parses the target repository using Tree-sitter (Python, Java, C/C++)
- Extracts files, classes, functions, and structural edges
- Uploads the graph to Neo4j
- `--clear` wipes the existing database before uploading

### 2. Incremental update from Git diff

```bash
python cli.py update /path/to/repo
```

- Detects modified files via `git ls-files -mo`
- Re-parses changed source files using the two-pass Tree-sitter pipeline
- Applies Continual Graph Learning (BFS layering + hub centrality)
- Replaces the affected subgraph in Neo4j

### 3. Export diagram

```bash
python cli.py export --file architecture.mermaid --fmt mermaid --method static
```

Available options:
- `--fmt`: `mermaid`, `plantuml`, `drawio`
- `--method`: `static` (direct Neo4j query) or `langchain` (LLM-assisted; requires `GEMINI_API_KEY`)

### 4. Clear Neo4j database

```bash
python cli.py clear
```

Removes all graph nodes and relationships from the connected Neo4j instance.

## Project architecture

```
graph-doc-gen/
├── cli.py                      # CLI entry-point (parse, update, export, clear)
├── code_parser/
│   └── extractor.py            # Two-pass Tree-sitter parser
├── database/
│   └── neo4j_client.py         # Neo4j driver wrapper
├── enrichment/
│   ├── cgl.py                  # Continual Graph Learner (BFS layering, hub centrality, MMD)
│   └── clustering.py           # Leiden community detection (available for suspicious-module analysis)
├── maintenance/
│   ├── diff_agent.py           # Incremental graph updater (Git diff → CGL → Neo4j)
│   ├── export.py               # Diagram generation (Mermaid, PlantUML, Draw.io)
│   ├── git_utils.py            # get_commit_diff(base_sha, target_sha, cwd) helper
│   └── stats.py                # Optional timing/performance helpers
└── requirements.txt
```

## Removed in this phase

The following documentation-only features have been removed to keep the codebase
focused on graph construction and CI/CD analysis:

| Removed | Reason |
|---------|--------|
| `enrichment/llm_summarizer.py` | Groq-based cluster summarization – documentation only |
| `enrichment/readme_generator.py` | LangChain/Gemini README generator – documentation only |
| `mcp_server/` | MCP stdio server – not required for batch CI/CD workflow |
| `cli.py enrich` command | Depended on llm_summarizer |
| `cli.py generate_docs` command | Depended on readme_generator |
| `cli.py serve` command | Depended on mcp_server |
| `groq` dependency | Only used by llm_summarizer |
| `mcp` dependency | Only used by mcp_server |

## Upcoming phases

- **Phase 2**: LightGBM metadata-based CI/CD build-failure predictor (TravisTorrent features)
- **Phase 3**: Graph-based suspicious-file ranking triggered when predicted risk exceeds threshold
- **Phase 4**: Ranked output with connected modules, dependency paths, and ranking explanations

## Troubleshooting

- If `cli.py parse` fails with Neo4j authentication errors, check `NEO4J_USERNAME` and
  `NEO4J_PASSWORD` in your `.env`.
- If `GEMINI_API_KEY` is unset, the parser still runs – embeddings are disabled and a
  one-line info message is printed.
- `export --method langchain` requires `GEMINI_API_KEY` and will exit early without it.

