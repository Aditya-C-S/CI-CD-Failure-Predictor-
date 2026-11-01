# Phase 2: End-to-End Flow - Requested SHA to Verified Graph State

## Complete Flow Diagram

```
User Request
    │
    ├─ repo_id: "owner/repo"
    ├─ target_sha: "abc123def456..." (40 chars)
    └─ repo_path: "/path/to/repo"
    ↓
Orchestrator.process_commit()
    │
    ├─ Step 1: Run metadata predictor (38 features)
    │          ✓ Risk probability: 0.72
    │          ✓ Verdict: "SUSPICIOUS"
    │          ✓ SHAP drivers: {...}
    │
    ├─ Step 2: Synchronize graph (NEW: Phase 2 verification)
    │          → GraphAdapter.sync_to_sha(base_sha, target_sha)
    │
    └─ Step 3: If risk >= threshold, investigate
               → get_connected_files() for risky files
    ↓
GraphAdapter.sync_to_sha(base_sha, target_sha)
    ↓
    Phase 2A: Check Existing Graph State
    ├─ Call: client.get_sync_state(repo_id)
    ├─ Case 1: Returns None (initial ingestion)
    │          └─ Use parent_sha as base
    ├─ Case 2: Returns SyncState (incremental update)
    │          ├─ Check: existing["target_sha"] == base_sha
    │          ├─ Yes ✅ → Proceed with incremental
    │          └─ No ❌ → FAIL "Base SHA mismatch"
    └─ Case 3: Returns SyncState with commit_verified=False
               └─ FAIL "Graph state not verified"
    ↓
    Phase 2B: Call Graph Engine with Phase 2 Contract
    ├─ Call: update_graph_from_diff(repo_path, base_sha, target_sha, repo_id)
    │
    │ Graph Engine Processing:
    │ ├─ Verify working tree is clean
    │ ├─ Verify base_sha consistency (NEW)
    │ ├─ Checkout target_sha
    │ ├─ Parse files, extract AST
    │ ├─ Update Neo4j with repo_id isolation
    │ ├─ Create/update SyncState node
    │ └─ Return Dict with metadata (Phase 2)
    │
    └─ Result: {
        "status": "SUCCESS" | "NO_CHANGES" | "FAILED",
        "repo_id": "owner/repo",
        "target_sha": "abc123...",  ← PROOF: engine processed THIS commit
        "base_sha": "xyz789...",
        "commit_verified": True,     ← PROOF: commit safety verified
        "files_parsed": 5,
        "nodes_count": 47,
        "edges_count": 23,
        "synced_at": "2026-10-22T...",
        "error": None
    }
    ↓
    Phase 2C: Validate Engine Result (NEW VERIFICATION LAYER 1)
    ├─ Call: _validate_sync_result(result, target_sha)
    │
    │ Checks:
    │ ├─ result is not None ✅ PASS
    │ ├─ status in ["SUCCESS", "NO_CHANGES"] ✅ PASS
    │ ├─ result["repo_id"] == "owner/repo" ✅ PASS
    │ ├─ result["target_sha"] == "abc123..." (exact match) ✅ PASS
    │ └─ result["commit_verified"] == True ✅ PASS
    │
    ├─ If any check fails → FAIL with GraphSyncException
    ├─ If all pass → Continue to Layer 2
    └─ Log: "✓ Operation result validated"
    ↓
    Phase 2D: Verify Persisted Neo4j State (NEW VERIFICATION LAYER 2)
    ├─ Call: _verify_persisted_state(target_sha)
    │
    │ ├─ Query Neo4j: MATCH (s:SyncState {id: f"repo:{repo_id}:sync"}) RETURN s
    │ │
    │ │ Read SyncState: {
    │ │     "repo_id": "owner/repo",
    │ │     "target_sha": "abc123...",      ← PROOF: Neo4j knows THIS SHA
    │ │     "base_sha": "xyz789...",
    │ │     "commit_verified": True,        ← PROOF: Neo4j verified it
    │ │     "status": "SYNCED",             ← PROOF: Neo4j completed it
    │ │     "nodes_count": 47,
    │ │     "synced_at": 1719072000000,     ← PROOF: timestamp
    │ │     "synced_at_iso": "2026-10-22T..."
    │ │ }
    │ │
    │ ├─ Checks:
    │ ├─ SyncState is not None ✅ PASS (record exists)
    │ ├─ persisted["target_sha"] == "abc123..." ✅ PASS (exact match)
    │ ├─ persisted["commit_verified"] == True ✅ PASS (verified flag set)
    │ └─ persisted["status"] == "SYNCED" ✅ PASS (sync completed)
    │
    ├─ If any check fails → FAIL with GraphSyncException
    ├─ If all pass → Continue to Layer 3
    └─ Log: "✓ Persisted SyncState verified"
    ↓
    Phase 2E: Compute Diff for Investigation (Unchanged)
    ├─ Call: get_commit_diff(base_sha, target_sha, repo_path)
    ├─ Result: {
    │     "added": ["new_file.py"],
    │     "modified": ["existing.py"],
    │     "deleted": [],
    │     "renamed": [("old.py", "new.py")]
    │ }
    └─ Use for tracking changed files
    ↓
    Phase 2F: Record to ORC SQLite (ONLY IF ALL CHECKS PASS)
    ├─ Call: sync_state.verify_sync(repo_id, target_sha, sync_id, node_count)
    │
    │ This records to ORC's checkpoint database:
    │ {
    │     "repo_id": "owner/repo",
    │     "current_sha": "abc123...",
    │     "sync_id": "uuid-...",
    │     "verified_at": "2026-10-22T...",
    │     "updated_at": "2026-10-22T..."
    │ }
    │
    └─ Log: "✓ Provenance recorded to checkpoint DB"
    ↓
    Phase 2G: Return Proof Objects
    └─ Return: {
        "status": "SYNCHRONIZED",
        "base_sha": "xyz789...",
        "target_sha": "abc123...",
        "files_added": 1,
        "files_modified": 1,
        "files_deleted": 0,
        "files_renamed": 1,
        "changed_files": [
            "/abs/path/to/new_file.py",
            "/abs/path/to/existing.py"
        ],
        "engine_result": {          ← PROOF OBJECT 1
            "status": "SUCCESS",
            "repo_id": "owner/repo",
            "target_sha": "abc123...",
            "commit_verified": True,
            ...
        },
        "persisted_state": {        ← PROOF OBJECT 2
            "repo_id": "owner/repo",
            "target_sha": "abc123...",
            "commit_verified": True,
            "status": "SYNCED",
            ...
        }
    }
    ↓
Back to Orchestrator
    │
    ├─ Sync result: "SYNCHRONIZED" ✅
    ├─ Files to investigate: [new_file.py, existing.py]
    │
    ├─ Step 3: Check risk threshold
    │          If risk >= 0.50 → Investigate
    │          Else → Skip investigation
    │
    └─ Investigate (if risk threshold met):
        └─ get_connected_files(changed_files)
           ├─ Query: MATCH (origin:File {repo_id: "owner/repo"}) ...
           ├─ Traverse CALLS relationships
           ├─ Return connected files scoped to repo_id
           └─ Return as SuspiciousFile objects
    ↓
Return Final Result
├─ CommitPredictionResult {
│     repository_identity: "owner/repo",
│     target_sha: "abc123...",
│     failure_probability: 0.72,
│     verdict: "SUSPICIOUS",
│     graph_status: "SYNCHRONIZED",  ← VERIFIED via Phase 2
│     graph_files_changed: {
│         added: 1,
│         modified: 1,
│         deleted: 0,
│         renamed: 1
│     },
│     suspicious_files: [
│         SuspiciousFile(path="/abs/path/to/new_file.py", ...),
│         SuspiciousFile(path="/abs/path/to/existing.py", ...)
│     ],
│     features: {...},           ← 38 features from metadata predictor
│     processing_time_ms: 1234.5
│ }
└─ Returned to user/API
```

---

## Three-Layer Verification in Action

### Layer 1: Engine Result Validation
**Question**: Did the graph engine complete the operation?
**Answer**: Yes, engine returned Dict with commit_verified=True and target_sha matches

```
validate_sync_result(engine_result, target_sha):
    assert engine_result is not None
    assert engine_result["status"] in ["SUCCESS", "NO_CHANGES"]
    assert engine_result["repo_id"] == self.repo_id
    assert engine_result["target_sha"] == target_sha
    assert engine_result["commit_verified"] == True
    → If all pass, engine proof is valid ✅
```

### Layer 2: Persisted State Verification
**Question**: Is the committed proof stored in Neo4j?
**Answer**: Yes, SyncState exists with matching SHA and verified flag

```
verify_persisted_state(target_sha):
    persisted = client.get_sync_state(self.repo_id)
    assert persisted is not None
    assert persisted["target_sha"] == target_sha
    assert persisted["commit_verified"] == True
    assert persisted["status"] == "SYNCED"
    → If all pass, persistent proof is valid ✅
```

### Layer 3: ORC Checkpoint Recording
**Question**: Did ORC record this verification?
**Answer**: Yes, checkpoint saved only after Layer 1 & 2 pass

```
sync_state.verify_sync(repo_id, target_sha, sync_id, node_count):
    sql.INSERT INTO sync_state VALUES (
        repo_id,
        target_sha,           ← Only if Layers 1 & 2 passed
        sync_id,
        verified_at,
        updated_at
    )
    → Checkpoint recorded with timestamp ✅
```

---

## Failure Scenarios (All Fail-Closed)

### Scenario 1: Engine Returns None (Layer 1 Fails)
```
update_graph_from_diff() → None

_validate_sync_result(None, target_sha)
    → GraphSyncException: "Graph engine returned None"
    → STOP: do not record to SQLite
    → Orchestrator catches exception
    → Retry or fail gracefully
```

### Scenario 2: Engine Returns Wrong Target SHA (Layer 1 Fails)
```
update_graph_from_diff() → {
    status: "SUCCESS",
    repo_id: "owner/repo",
    target_sha: "WRONG_SHA",  ← ❌ Mismatch
    commit_verified: True
}

_validate_sync_result(result, "CORRECT_SHA")
    → GraphSyncException: "Target SHA mismatch"
    → STOP: do not record to SQLite
    → Retry or fail gracefully
```

### Scenario 3: SyncState Missing in Neo4j (Layer 2 Fails)
```
Engine completes successfully
ORC tries to verify persisted state

_verify_persisted_state(target_sha)
    client.get_sync_state() → None
    → GraphSyncException: "No SyncState found"
    → STOP: do not record to SQLite
    → Retry or fail gracefully
```

### Scenario 4: Base SHA Doesn't Match Graph (Before Sync)
```
Existing graph at SHA-A
Request sync with base SHA-B

sync_to_sha(base_B, target_C):
    existing = client.get_sync_state()  → {target_sha: SHA-A, ...}
    
    if existing["target_sha"] != base_B:  ← ❌ A ≠ B
        → GraphSyncException: "Base SHA mismatch"
        → STOP: do not call engine
        → Retry with correct base or fail gracefully
```

---

## Recovery from Partial Failures

### Scenario: Sync Failed, Checkpoint Not Saved

**If Phase 2C (engine validation) fails**:
- Engine result invalid
- ORC doesn't have proof to record
- SQLite NOT updated
- On retry: Re-read Neo4j state from scratch
  - If SyncState exists and valid → use it
  - If SyncState missing → retry sync

**If Phase 2D (persisted state verification) fails**:
- Engine completed but Neo4j's SyncState is missing/invalid
- ORC doesn't have proof to record
- SQLite NOT updated
- On retry: Re-check Neo4j
  - May show SyncState now exists (race condition resolved)
  - Or may need to retry engine call

**If Phase 2F (SQLite record) fails**:
- Layers 1 & 2 passed
- SQLite transaction failed
- On retry: ORC re-reads Neo4j state (now has SyncState)
  - Recognizes SHA already synced
  - Returns IDEMPOTENT or uses cached state

---

## Idempotent Re-Sync

### Scenario: Request Same SHA Twice

**First request**:
```
sync_to_sha(base, SHA-A)
→ Engine: SUCCESS, commit_verified=True
→ SyncState created in Neo4j: {target_sha: SHA-A, verified: True}
→ SQLite updated: current_sha = SHA-A
→ Return "SYNCHRONIZED"
```

**Second request (same SHA)**:
```
sync_to_sha(base, SHA-A)
→ Get existing: {target_sha: SHA-A, verified: True}
→ Call engine with base=SHA-A, target=SHA-A
→ Engine returns: {status: "NO_CHANGES", commit_verified: True}
→ Validate result: ✅ NO_CHANGES is valid status
→ Verify persisted: ✅ SyncState still valid
→ SQLite updated: current_sha = SHA-A (idempotent)
→ Return "SYNCHRONIZED" (same as first request)
```

---

## Isolation Between Repositories

### Scenario: Two Repos Syncing Simultaneously

**Repository 1: owner/repo1**
```
sync_to_sha(base1, SHA1)
→ get_sync_state("owner/repo1")  ← Repo-scoped query
→ update_graph_from_diff(..., repo_id="owner/repo1")
  ├─ Engine enforces repo_id isolation
  ├─ Only updates nodes with repo_id="owner/repo1"
  └─ Creates SyncState: id="repo:owner/repo1:sync"
→ Query Neo4j: MATCH (s:SyncState {id="repo:owner/repo1:sync"})
→ Record to SQLite: repo_id="owner/repo1"
```

**Repository 2: owner/repo2** (concurrent)
```
sync_to_sha(base2, SHA2)
→ get_sync_state("owner/repo2")  ← Different repo!
→ update_graph_from_diff(..., repo_id="owner/repo2")
  ├─ Engine enforces repo_id isolation
  ├─ Only updates nodes with repo_id="owner/repo2"
  └─ Creates SyncState: id="repo:owner/repo2:sync"
→ Query Neo4j: MATCH (s:SyncState {id="repo:owner/repo2:sync"})
→ Record to SQLite: repo_id="owner/repo2"
```

**Result**: Complete isolation, no cross-contamination ✅

---

## Summary: What Changed vs What's Preserved

### CHANGED (Phase 2):
- ✅ sync_to_sha() implementation (3 new verification layers)
- ✅ GraphAdapter validation methods (2 new)
- ✅ Return structure (added proof objects)
- ✅ Error handling (fail-closed, specific reasons)

### PRESERVED:
- ✅ Orchestrator flow (orchestration order unchanged)
- ✅ Metadata predictor (38 features, calibration, SHAP, verdict unchanged)
- ✅ Checkpoint flow (prediction → sync → investigation)
- ✅ Repository isolation (repo_id everywhere)
- ✅ graphdoc database targeting (safety maintained)
- ✅ Retry logic (reuses cache, re-reads Neo4j)

### RESULT:
End-to-end: Requested SHA → Verified Neo4j State ✅
Proof trail: Engine result + Persisted state + Timestamp
Isolation: Complete between repositories
Safety: Fail-closed on any validation failure

