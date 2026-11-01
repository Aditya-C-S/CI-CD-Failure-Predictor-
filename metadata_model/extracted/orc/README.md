# Orchestrator: Metadata Pipeline + Graph-Doc-Gen Integration

A minimal integration layer that coordinates:
1. **Metadata-Pipeline**: LightGBM-based commit-risk prediction
2. **graph-doc-gen-main**: Code graph parsing and Neo4j integration

## Architecture

```
Orchestrator
├── MetadataAdapter (wraps PredictorService)
│   ├── Syncs repo cache
│   ├── Extracts 38 features
│   └── Runs prediction
├── GraphAdapter (wraps graph-doc-gen)
│   ├── Synchronizes graph to target commit
│   ├── Handles repository isolation
│   └── Queries for suspicious files
├── CheckpointManager (SQLite)
│   └── Durable state tracking
└── Result Model
    └── Unified output for all clients
```

## Quick Start

### Installation

```bash
# Clone orchestrator
cd orchestrator

# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and configure
cp .env.example .env
```

### Configuration

Edit `.env`:
```env
GITHUB_TOKEN=ghp_your_token
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=commits_graph
INVESTIGATION_THRESHOLD=0.50
```

### Running

```bash
# Basic usage
python -m src.main owner/repo <target_sha> --repo-path /path/to/repo

# With custom base commit
python -m src.main owner/repo <target_sha> --repo-path /path/to/repo --base-sha <base_sha>

# JSON output
python -m src.main owner/repo <target_sha> --repo-path /path/to/repo --json
```

## Features

- **Prediction**: Uses PredictorService with 38-feature schema
- **Graph Synchronization**: Always syncs graph to target commit, regardless of risk
- **Conditional Investigation**: Only investigates suspicious files if risk >= threshold
- **Repository Isolation**: Prevents graph data mixing across repos (via adapter)
- **Checkpoint Management**: SQLite-based durable state tracking
- **Retry Logic**: Exponential backoff for transient failures
- **Duplicate Detection**: Caches results by (repo_id, target_sha)

## Testing

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_orchestrator.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Project Structure

```
orchestrator/
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI entry point
│   ├── orchestrator.py         # Core orchestration logic
│   ├── adapters/
│   │   ├── metadata_adapter.py # Metadata-Pipeline bridge
│   │   └── graph_adapter.py    # graph-doc-gen bridge
│   ├── models/
│   │   └── result.py           # Unified result model
│   ├── storage/
│   │   └── checkpoint.py       # SQLite checkpoint management
│   └── errors/
│       └── exceptions.py       # Custom exceptions
├── tests/
│   ├── conftest.py             # Pytest fixtures
│   ├── test_orchestrator.py    # Main tests
│   └── test_checkpoint.py      # Checkpoint tests
├── .env.example
├── requirements.txt
└── README.md
```

## Key Interfaces

### MetadataAdapter

```python
adapter = MetadataAdapter(github_token)
result = adapter.predict(owner, repo, target_sha)
# Returns: {failure_probability, verdict, shap_drivers, features, ...}
```

### GraphAdapter

```python
adapter = GraphAdapter(repo_id, repo_path)
sync_result = adapter.sync_to_sha(base_sha, target_sha)
# Returns: {status, files_added, files_modified, files_deleted, ...}

suspicious_files = adapter.get_connected_files(changed_files)
# Returns: [SuspiciousFile(file_path, centrality_score, reasons), ...]
```

### Orchestrator

```python
orchestrator = Orchestrator(github_token, investigation_threshold=0.50)
result = orchestrator.process_commit(
    repo_id="owner/repo",
    target_sha="abc123...",
    repo_path="/path/to/repo",
)
# Returns: CommitPredictionResult
```

## Checkpoint State Machine

```
START
  ↓
[PREDICTION] → PREDICTION_COMPLETE
  ↓
[GRAPH SYNC] → (GRAPH_SYNC_FAILED ↔ retry) OR COMPLETE
  ↓
[INVESTIGATION] (if risk >= threshold)
  ↓
COMPLETE
```

- **PREDICTION_COMPLETE**: Prediction succeeded, graph sync not yet started
- **GRAPH_SYNC_FAILED**: Graph sync failed (safe to retry without re-predicting)
- **COMPLETE**: Both steps succeeded
- **FAILED**: Permanent failure (after max retries)

## Limitations & Future Work

1. **Repository Isolation**: Currently delegated to adapter layer; production should namespace node IDs in Neo4j
2. **Suspicious File Ranking**: Uses graph centrality only; embeddings not yet integrated
3. **No Cloud Services**: First version uses only local storage (SQLite) and existing project APIs
4. **No Distributed Queues**: Synchronous execution; suitable for CI/CD webhook triggers
5. **Graph Atomicity**: Depends on Neo4j transactions; orchestrator does not provide ACID guarantees

## Known Issues

- Graph adapter's `_apply_repo_isolation()` is a placeholder; production needs ID prefixing strategy
- No monitoring/alerting integration in this version
- Retry logic is basic; no circuit breaker yet

## Example End-to-End Flow

```bash
# 1. Ensure Neo4j is running
neo4j start

# 2. Configure .env
cp .env.example .env
# ... edit with real credentials ...

# 3. Run orchestrator
python -m src.main testowner/testrepo abc1234567890 --repo-path /tmp/test_repo --json > result.json

# 4. Check result
cat result.json
```

## References

- **Metadata-Pipeline**: `../Metadata-Pipeline-main/`
- **graph-doc-gen-main**: `../graph-doc-gen-main/`
