import subprocess
import os
from typing import Dict, List, Tuple, Optional


class CommitProvenanceError(ValueError):
    """Base exception for commit provenance verification failures."""
    pass


class WorkingTreeDirtyError(CommitProvenanceError):
    """Raised when relevant working-tree files have uncommitted modifications or untracked changes."""
    def __init__(self, dirty_files: List[str], cwd: str = ""):
        self.dirty_files = dirty_files
        self.cwd = cwd
        super().__init__(
            f"Working-tree verification failed: uncommitted changes detected in {len(dirty_files)} "
            f"relevant file(s) in '{cwd or '.'}': {', '.join(dirty_files[:10])}"
            + ("..." if len(dirty_files) > 10 else "")
            + ". Fail closed: uncommitted changes must not enter the graph."
        )


class CommitMismatchError(CommitProvenanceError):
    """Raised when HEAD does not match the requested target commit SHA."""
    def __init__(self, head_sha: str, target_sha: str):
        self.head_sha = head_sha
        self.target_sha = target_sha
        super().__init__(
            f"Working-tree verification failed: HEAD commit '{head_sha}' does not match "
            f"target_sha '{target_sha}'. In Option 1 (Strict Working-Tree Verification), the working "
            f"tree HEAD must be checked out to the exact target commit before graph mutation."
        )


class BaseCommitMismatchError(CommitProvenanceError):
    """Raised when the graph's existing synchronization state does not match the requested base_sha."""
    def __init__(self, current_graph_sha: Optional[str], requested_base_sha: str, repo_id: str):
        self.current_graph_sha = current_graph_sha
        self.requested_base_sha = requested_base_sha
        self.repo_id = repo_id
        if current_graph_sha is None:
            msg = (
                f"Incremental synchronization rejected for repo '{repo_id}': no prior verified "
                f"SyncState exists. An incremental update from '{requested_base_sha}' requires the "
                f"graph to already be synchronized at that base commit. Perform initial ingestion first."
            )
        else:
            msg = (
                f"Incremental synchronization rejected for repo '{repo_id}': graph is currently at "
                f"commit '{current_graph_sha}', which does not match requested base_sha '{requested_base_sha}'. "
                f"Applying a diff on a mismatched base would corrupt the graph."
            )
        super().__init__(msg)


def is_git_repository(cwd: str) -> bool:
    """Check whether cwd is a valid git repository work tree."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except Exception:
        return False


def resolve_commit_sha(sha: str, cwd: str) -> str:
    """
    Resolve a commit reference (SHA prefix, HEAD, tag, etc.) to a canonical 40-character commit hash.
    Raises ValueError / CommitProvenanceError if the reference cannot be resolved to a valid commit object.
    """
    if not sha or not sha.strip():
        raise CommitProvenanceError("Commit reference cannot be empty.")
    
    clean_sha = sha.strip()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{clean_sha}^{{commit}}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise CommitProvenanceError(
                f"Invalid commit reference: Cannot resolve Git reference '{clean_sha}' to a canonical commit in '{cwd}'."
            )
        resolved = res.stdout.strip()
        if len(resolved) != 40 or not all(c in "0123456789abcdefABCDEF" for c in resolved):
            raise CommitProvenanceError(
                f"Resolved Git reference '{clean_sha}' produced invalid hash format: '{resolved}'."
            )
        return resolved.lower()
    except subprocess.SubprocessError as e:
        raise CommitProvenanceError(f"Git command failed while resolving '{clean_sha}': {e}") from e


def get_head_commit_sha(cwd: str) -> str:
    """Get canonical 40-character commit hash of HEAD."""
    return resolve_commit_sha("HEAD", cwd)


def check_working_tree_clean(cwd: str, file_paths: Optional[List[str]] = None) -> bool:
    """
    Verify that relevant working-tree files are clean (no uncommitted or untracked changes).
    
    If file_paths is specified and non-empty, checks only those specific files.
    If file_paths is None or empty, checks entire working tree status.
    
    Raises WorkingTreeDirtyError if uncommitted changes are detected.
    Returns True if clean.
    """
    cmd = ["git", "status", "--porcelain"]
    if file_paths:
        # Normalize relative paths for git status
        norm_paths = []
        for fp in file_paths:
            rel = os.path.relpath(os.path.join(cwd, fp), cwd).replace("\\", "/")
            norm_paths.append(rel)
        cmd.extend(["--"] + norm_paths)
    
    res = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise CommitProvenanceError(
            f"git status failed in '{cwd}': {res.stderr.strip()}"
        )
    
    dirty_lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if dirty_lines:
        dirty_files = []
        for line in dirty_lines:
            # git status --porcelain formats: 'XY filename' or 'R  orig -> new'
            parts = line[2:].strip().split(" -> ")
            dirty_files.append(parts[-1])
        raise WorkingTreeDirtyError(dirty_files=dirty_files, cwd=cwd)
    
    return True


def get_commit_diff(base_sha: str, target_sha: str, cwd: str) -> Dict[str, List]:
    """Return a dictionary describing the diff between two commits.

    The returned dict has the keys ``added``, ``modified``, ``deleted`` and
    ``renamed``. ``renamed`` is a list of ``(old_path, new_path)`` tuples.

    The implementation uses ``git diff --name-status -M`` which reports a
    one‑letter status code per line (A, M, D, Rxxx). ``-M`` enables rename
    detection (the default 50 % similarity threshold is sufficient for most
    CI scenarios).

    Parameters
    ----------
    base_sha: str
        The base commit SHA (e.g. ``HEAD~1``).
    target_sha: str
        The target commit SHA (e.g. ``HEAD``).
    cwd: str
        The repository root directory.
    """
    result = subprocess.run(
        ["git", "diff", "--name-status", "-M", f"{base_sha}..{target_sha}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    changes: Dict[str, List] = {
        "added": [],
        "modified": [],
        "deleted": [],
        "renamed": [],
    }
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status == "A":
            changes["added"].append(parts[1])
        elif status == "M":
            changes["modified"].append(parts[1])
        elif status == "D":
            changes["deleted"].append(parts[1])
        elif status.startswith("R"):
            # Rename entries have two paths: old and new
            old_path, new_path = parts[1], parts[2]
            changes["renamed"].append((old_path, new_path))
        else:
            # Unexpected status – treat conservatively as modified
            changes["modified"].append(parts[-1])
    return changes
