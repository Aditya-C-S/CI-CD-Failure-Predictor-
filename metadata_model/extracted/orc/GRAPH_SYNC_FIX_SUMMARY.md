# Graph-Sync Git Status Fix Summary

## Root Cause

When the graph working copy was created by cloning from a local filesystem path (`C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe`), git stored the local filesystem URL as the remote in `.git/config`:

```
[remote "origin"]
    url = C:\Users\DHRUV HEGDE\Desktop\Voice_based-_Tic-Tac-Toe
```

When the graph engine invoked `git status --porcelain -- <file_paths>` with changed files as arguments, git's path normalization could fail, especially when:
1. Git internal operations tried to verify objects through the local remote
2. Path calculations resulted in relative paths like `../../../Voice_based-_Tic-Tac-Toe/Tic-Tac-Toe.py` pointing outside the graph cache
3. Git rejected these "outside repository" paths with error: `fatal: ../../../Voice_based-_Tic-Tac-Toe/Tic-Tac-Toe.py: ... is outside repository`

## Error Message
```
git status failed in C:\Users\DHRUV HEGDE\Desktop\orc\.graph_cache\DhruvHegde__Voice_based-_Tic-Tac-Toe: 
fatal: ../../../Voice_based-_Tic-Tac-Toe/Tic-Tac-Toe.py: ... is outside repository
```

## Solution

**File Changed**: `src/adapters/graph_adapter.py`

**Location**: Function `_ensure_graph_working_copy_at_sha()`, after initial clone

**Fix**: Immediately replace the local filesystem remote URL with the GitHub URL after cloning.

### Code Change
After cloning from the local source repo (for speed), the function now:
1. Derives the GitHub URL from `repo_id` (owner/repo format)
2. Calls `git remote set-url origin <github_url>`
3. Falls back gracefully if the GitHub URL cannot be set (logs warning, keeps local remote)

This ensures:
- **Independent git working copy**: Remote points to GitHub, not the source repo directory
- **Proper path resolution**: Git's path calculations stay within the working copy boundaries
- **Performance retained**: Still clones from local source repo (fast), but with corrected remote
- **Fallback safety**: If GitHub derivation fails, local remote is still usable (though not ideal)

## Files Changed

### 1. `src/adapters/graph_adapter.py` (Modified)

**Lines added**: 65-75 (after initial clone)

```python
# CRITICAL: Replace local remote URL with GitHub remote to avoid git path issues
# When cloned from a local path, git stores the local filesystem URL.
# This can cause "is outside repository" errors when git tries to access the remote.
# We must update the remote to a proper remote URL (GitHub or fallback to local).
try:
    # Try to derive GitHub URL from repo_id (owner/repo)
    owner, repo = repo_id.split("/", 1)
    github_url = f"https://github.com/{owner}/{repo}.git"
    subprocess.run(
        f'git remote set-url origin "{github_url}"',
        cwd=graph_cache_dir,
        shell=True,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info(f"Configured remote origin to GitHub: {github_url}")
except Exception as e:
    logger.warning(f"Could not set GitHub remote for {repo_id}: {e}. Keeping local remote.")
```

## Verification

**Test File**: `tests/test_graph_git_status_fix.py`

**Test Results**: 7 PASSED

### Tests Cover:

1. **test_01_graph_cache_has_github_remote_not_local** ✓
   - Verifies remote URL is GitHub, not local filesystem
   - Checks that local path is NOT present in remote config

2. **test_02_git_status_succeeds_on_target_commit** ✓
   - Confirms `git status` works on target commit (0a8ef71)
   - Working tree should be clean after checkout

3. **test_03_check_working_tree_clean_with_changed_files** ✓
   - Critical test: reproduces exact scenario that caused original error
   - Calls `check_working_tree_clean()` with actual changed files (Tic-Tac-Toe.py)
   - Must NOT raise "is outside repository" error

4. **test_04_source_repository_unchanged_after_graph_ops** ✓
   - Verifies source repo HEAD not modified
   - Confirms source repo working tree remains clean
   - Ensures graph cache operations don't affect source

5. **test_05_graph_cache_head_matches_target_sha** ✓
   - Validates graph cache HEAD correctly positioned at target_sha
   - Ensures exact commit match required by graph engine

6. **test_06_graph_engine_callable_and_available** ✓
   - Confirms graph engine functions are importable from `graph-doc-gen-main`
   - Verifies maintenance.diff_agent and maintenance.git_utils available

7. **test_07_incremental_sync_from_base_to_target** ✓
   - Tests moving graph cache from base commit (b55166a) to target (0a8ef71)
   - Simulates incremental sync scenario

## Graph Engine Import Resolution

**Confirmed Graph Engine Project**: `C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main`

**Import Path in ORC**: 
```python
GRAPH_DOC_GEN_ROOT = Path(__file__).parent.parent.parent.parent / "graph-doc-gen-main"
sys.path.insert(0, str(GRAPH_DOC_GEN_ROOT))

from maintenance.diff_agent import update_graph_from_diff
from maintenance.git_utils import get_commit_diff
```

**Resolved Modules**:
- `maintenance.diff_agent.update_graph_from_diff()` ✓
- `maintenance.git_utils.check_working_tree_clean()` ✓
- `maintenance.git_utils.get_commit_diff()` ✓

## Database Safety

- **Target Database**: Neo4j `graphdoc` database
- **Legacy Database**: `neo4j` (untouched, unmodified)
- **Verification**: GraphAdapter._verify_database_target() confirms NEO4J_DATABASE=graphdoc before any mutations

## Remaining Limitations

None identified. The fix is minimal and focused:
- Does not modify model artifacts, feature schema, or prediction logic
- Does not alter metadata pipeline functionality
- Does not change graph engine behavior
- Works with both GitHub and local repositories (with fallback)
- No breaking changes to existing interfaces

## Test Execution

```bash
cd C:\Users\DHRUV HEGDE\Desktop\orc
python -m pytest tests/test_graph_git_status_fix.py -v
```

**Output**:
```
=================== 7 passed in 17.33s ==================
```

## Next Steps

Ready for full ORC assessment:
1. Run metadata prediction on target commits
2. Verify graph sync completes without "working-tree verification failed" errors
3. Confirm Neo4j `graphdoc` database receives updates
4. Verify legacy `neo4j` database remains untouched

### Full ORC Assessment Command
```bash
cd C:\Users\DHRUV HEGDE\Desktop\orc
python src/main.py DhruvHegde Voice_based-_Tic-Tac-Toe b55166ab666eaf439a7d37e93b583d7f0ad4f562 0a8ef71ada39cf54513f0b9741ce480db1a6d1ff
```

(Replace paths and SHAs as needed for your use case)
