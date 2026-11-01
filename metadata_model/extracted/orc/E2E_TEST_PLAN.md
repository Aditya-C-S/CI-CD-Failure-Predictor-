# End-to-End Integration Test Plan

## Objective
Run the actual Metadata-Pipeline feature extractor, LightGBM model, and graph-doc-gen Neo4j synchronization on a real test repository commit to verify integration correctness.

## Critical Constraint: GitHub API Dependency

### Finding
The Metadata-Pipeline feature extraction extracts 39 features (38 predictive + 1 label):
- **18 features** require ONLY local Git history + workspace static analysis (can work without GitHub)
- **21 features** require GitHub API authentication to generate correct values
- **CRITICAL: The prediction target label `target_binary` depends on GitHub Actions API**

### Fallback Behavior (Silent Defaults)
If GitHub API is unavailable (no `gh cli` auth):
- All GitHub-dependent features default to **0** or empty string
- `target_binary` defaults to **0** (assumed PASS)
- No error is raised; pipeline produces a complete 39-feature row
- Model makes predictions based on artificially degraded data

### Decision for This Test
**Proceed with local-only execution AND document the limitation:**
1. Extract all 39 features using local Git + workspace analysis
2. Acknowledge that GitHub-dependent features (especially `target_binary`) will be defaulted
3. Run actual model with knowledge that it's using incomplete data
4. This is still valuable: proves the pipeline runs end-to-end without crashes

## Test Repository Selection

**Repository**: `c:\Users\DHRUV HEGDE\Desktop\dependency-error-repo`
- **Git URL**: https://github.com/DhruvHegde/dependency-error-repo.git
- **Repo ID**: `DhruvHegde/dependency-error-repo`
- **Target commit SHA**: `396184b8566debf2f302fe411f9e9816f73b76ee` (HEAD)
- **Commit message**: "Success dataset F1 run 0300 attempt 0302: tifffile==2024.5.22"
- **Repository is small and self-contained** ✓

## Neo4j Test Environment

**Existing production database**: 37 nodes
**Test strategy**: Create isolated test graph within same Neo4j instance
- Use separate database or node prefix to avoid data contamination
- Verify graph updates don't affect existing 37 nodes
- Clean up after test

## Execution Plan

### Phase 1: Setup Unified Python Environment
1. Create `.venv` in `orc` directory
2. Install all dependencies from both projects:
   - Metadata-Pipeline: `lightgbm`, `scikit-learn`, `joblib`, `shap`, `pandas`, `numpy`
   - graph-doc-gen: `neo4j==5.25.0`, `langchain-neo4j==0.1.1`
   - orc: requests, python-dotenv
3. Verify imports succeed

### Phase 2: Verify Feature Extraction
1. Run feature extraction on test commit
2. Verify all 39 features are produced
3. Document actual values (especially defaults from GitHub-dependent features)
4. Verify 38-feature schema is intact

### Phase 3: Run Model Prediction
1. Load trained LightGBM model
2. Pass 38 features (exclude label column) to model
3. Capture probability, verdict, SHAP drivers
4. Record output

### Phase 4: Synchronize Graph
1. Establish isolated Neo4j database/namespace
2. Run graph synchronization for target commit
3. Verify graph nodes represent the target SHA
4. Query for changed files
5. If risk >= 50%, query for connected files

### Phase 5: Recovery Test (Simulated)
1. Simulate graph sync failure
2. Verify checkpoint state machine doesn't mark COMPLETE
3. Retry and recover
4. Verify prediction was cached (not re-extracted)

### Phase 6: Report Evidence
Capture and report:
- Exact command to run pipeline
- Actual feature values (all 39)
- Model prediction result (probability, verdict, top SHAP drivers)
- Graph synchronization result (status, changed files count)
- Connected files results (if investigation ran)
- Checkpoint state progression
- Any warnings or errors
- Which components ran for real vs. defaulted

## Success Criteria

✅ Feature extraction completes without errors
✅ Model produces a probability score and verdict
✅ Graph synchronization succeeds for target commit
✅ Neo4j query returns changed files
✅ If risk >= 50%, investigation queries succeed
✅ No crashes or unhandled exceptions
✅ Actual model, extractor, and Neo4j involved (not mocked)
✅ Checkpoint state machine behaves correctly
✅ Can explain any defaulted values and limitations

## Known Limitations

⚠️ GitHub Actions API unavailable → `target_binary` = 0 (assumed PASS)
⚠️ GitHub REST API unavailable → 10 metadata features default to 0 / ""
⚠️ Model was trained with real CI data; predictions may be biased without it
⚠️ No PR metadata available locally
⚠️ Test repository must already exist and be cloned

## No Mocking, No Fabrication

- Will NOT mock the feature extractor
- Will NOT mock the LightGBM model
- Will NOT mock Neo4j calls
- Will NOT fabricate GitHub data
- Will accept all defaults silently as the real pipeline does
- Will document exactly what defaulted and why
