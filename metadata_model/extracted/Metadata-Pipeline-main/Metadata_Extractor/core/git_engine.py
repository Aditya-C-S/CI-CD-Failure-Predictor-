import subprocess
import os
import re
import time
import shutil
import stat
from datetime import datetime
from pathlib import Path

SRC_EXTS = {'.py', '.java', '.rb', '.c', '.cpp', '.js', '.ts', '.go', '.rs'}
DOC_EXTS = {'.md', '.rst', '.txt', '.pdf', '.docx', '.html'}

# Root cache directory
REPO_CACHE_ROOT = Path(__file__).parent.parent.parent / ".repo_cache"
REPO_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

# Configuration for recovery attempts
MAX_RECOVERY_ATTEMPTS = 1  # Allow one full cache reset on first failure


def _handle_remove_readonly(func, path, exc_info):
    """Error handler for shutil.rmtree to handle Windows read-only files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _run_git_checked(cmd, cwd, description="git operation"):
    """
    Run a git command and return (success, stdout).
    Unlike run_git(), this captures the exit code to detect failures.
    
    Args:
        cmd: Git command to run (shell string)
        cwd: Working directory
        description: Human-readable description for error messages
    
    Returns:
        tuple: (success: bool, output: str)
            success=True if exit code 0, output=stdout stripped
            success=False if non-zero exit, output=empty string
    """
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=True)
    if res.returncode != 0:
        return False, ""
    return True, res.stdout.strip()


def _resolve_commit_in_source_repo(owner: str, repo: str, commit_sha: str) -> bool:
    """
    Check if a commit exists in the source repository (not the cache).
    This allows analyzing local-only commits that haven't been pushed to GitHub.
    
    Args:
        owner: Repository owner
        repo: Repository name
        commit_sha: Commit SHA to verify
    
    Returns:
        True if the commit exists locally, False otherwise
    """
    # This is a utility to check if a commit is available in the user's local repo
    # It doesn't modify anything, just checks availability
    # The source repo is at a known location relative to the ORC workspace
    orc_root = Path(__file__).parent.parent.parent.parent
    source_repo_path = orc_root.parent / repo
    
    if not source_repo_path.exists():
        return False
    
    # Try to resolve the commit in the source repo
    success, _ = _run_git_checked(
        f'git rev-parse {commit_sha}',
        source_repo_path,
        f"resolve {commit_sha} in source repo"
    )
    return success


def _verify_commit_checked_out(repo_path: str, requested_sha: str) -> bool:
    """
    Verify that the repository's HEAD is at the requested commit.
    
    Args:
        repo_path: Path to the git repository
        requested_sha: The SHA that should be checked out
    
    Returns:
        True if HEAD == requested_sha, False otherwise
    """
    success, head_sha = _run_git_checked(
        'git rev-parse HEAD',
        repo_path,
        "verify HEAD"
    )
    if not success:
        return False
    
    # Handle both full SHA and abbreviated forms
    return head_sha.startswith(requested_sha) or requested_sha.startswith(head_sha)


def _checkout_commit(repo_path: str, commit_sha: str) -> bool:
    """
    Attempt to checkout a specific commit.
    
    Args:
        repo_path: Path to the git repository
        commit_sha: Commit SHA to checkout
    
    Returns:
        True if checkout succeeded and HEAD matches, False otherwise
    """
    # Attempt checkout
    success, _ = _run_git_checked(
        f'git checkout --quiet --force "{commit_sha}"',
        repo_path,
        f"checkout {commit_sha}"
    )
    if not success:
        return False
    
    # Clean untracked files
    _run_git_checked(
        'git clean --quiet -fd',
        repo_path,
        "clean untracked files"
    )
    
    # Verify the checkout worked
    return _verify_commit_checked_out(repo_path, commit_sha)


def sync_repo_cache(owner: str, repo: str, commit_sha: str = None, token: str = None,
                    source_repo_path: str = None) -> tuple[str, str]:
    """
    Synchronize a persistent local Git cache for the given repository.
    
    If a specific commit_sha is requested and doesn't exist in the cache or remote,
    attempts to use it from the source_repo_path if available. Raises an error if
    the commit cannot be resolved anywhere.
    
    Args:
        owner: Repository owner
        repo: Repository name
        commit_sha: Optional specific commit to checkout
        token: Optional GitHub token for authenticated access
        source_repo_path: Optional path to source repository for local-only commits
    
    Returns:
        tuple: (cache_dir_path, cache_status) where cache_status is "hit" or "miss"
    
    Raises:
        RuntimeError: If commit_sha is requested but cannot be resolved
    """
    cache_dir = REPO_CACHE_ROOT / f"{owner}__{repo}"
    cache_git_dir = cache_dir / ".git"
    
    # Build authenticated clone URL if token provided
    repo_url = f"https://github.com/{owner}/{repo}.git"
    if token:
        repo_url = f"https://{token}@github.com/{owner}/{repo}.git"
    
    start_time = time.time()
    recovery_attempted = False
    
    # Track whether we're attempting recovery to avoid infinite loops
    if not cache_git_dir.exists():
        # Path A: Cache Miss (First Run for a Repo)
        print(f"[EXTRACT] Cache miss – Cloning {owner}/{repo} into persistent cache...")
        if cache_dir.exists():
            shutil.rmtree(cache_dir, onerror=_handle_remove_readonly)
        
        try:
            subprocess.run(
                f'git clone --quiet "{repo_url}" "{cache_dir}"',
                shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to clone {owner}/{repo}: {e}")
        
        cache_status = "miss"
    else:
        # Path B: Cache Hit (Subsequent Runs / Commits)
        print(f"[EXTRACT] Cache hit – Fetching latest delta for {owner}/{repo}...")
        cache_status = "hit"
        
        # Fetch from remote
        fetch_success, _ = _run_git_checked(
            'git fetch --quiet --all --prune',
            cache_dir,
            "fetch from remote"
        )
        
        if not fetch_success:
            print(f"[EXTRACT] WARNING: Fetch from remote failed, will attempt recovery...")
            recovery_attempted = True
    
    # Now attempt to checkout the requested commit if specified
    if commit_sha:
        checkout_success = _checkout_commit(cache_dir, commit_sha)
        
        if not checkout_success:
            # Checkout failed - first check if it's because the commit doesn't exist
            # Try to determine if this is a transient error or a missing commit
            
            # If we haven't attempted recovery yet, try one recovery:
            # wipe cache and do a fresh clone
            if not recovery_attempted and cache_status == "hit":
                print(f"[EXTRACT] WARNING: Checkout of {commit_sha} failed on cache hit, "
                      f"attempting one recovery: wiping cache and fresh clone...")
                
                try:
                    shutil.rmtree(cache_dir, onerror=_handle_remove_readonly)
                except Exception as e:
                    print(f"[EXTRACT] WARNING: Failed to wipe cache: {e}")
                
                # Fresh clone
                try:
                    subprocess.run(
                        f'git clone --quiet "{repo_url}" "{cache_dir}"',
                        shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    cache_status = "miss"
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"Recovery: fresh clone of {owner}/{repo} failed: {e}")
                
                # Try checkout again
                checkout_success = _checkout_commit(cache_dir, commit_sha)
            
            # If still not successful, check if the commit is available in the source repo
            if not checkout_success:
                if source_repo_path and os.path.isdir(source_repo_path):
                    # Source repo is available - check if commit is there
                    source_success, _ = _run_git_checked(
                        f'git rev-parse {commit_sha}',
                        source_repo_path,
                        f"check if {commit_sha} exists in source"
                    )
                    if source_success:
                        # Commit exists in source repo but not in cache/remote
                        # Use the source repository directly for local-only commits
                        print(f"[EXTRACT] Local-only commit detected: {commit_sha} exists in source repo")
                        print(f"[EXTRACT] Using source repository directly: {source_repo_path}")
                        
                        # Verify the commit is actually checked out in source repo
                        # (or at least resolvable)
                        src_verify, _ = _run_git_checked(
                            f'git rev-parse {commit_sha}',
                            source_repo_path,
                            f"verify {commit_sha} in source"
                        )
                        if src_verify:
                            # Successfully use source repo for feature extraction
                            elapsed = time.time() - start_time
                            print(f"[EXTRACT] Git sync completed in {elapsed:.2f}s (source repo for local commit)")
                            return source_repo_path, "source"
                
                # Commit doesn't exist anywhere we can reach
                raise RuntimeError(
                    f"Cannot resolve commit {commit_sha} in {owner}/{repo}. "
                    f"The commit was not found in remote {repo_url} or local cache. "
                    f"Verify the commit SHA is correct and has been pushed to GitHub."
                )
    else:
        # No specific commit requested - checkout remote default branch HEAD
        default_branch_output = subprocess.run(
            'git symbolic-ref refs/remotes/origin/HEAD',
            cwd=cache_dir, shell=True, capture_output=True, text=True
        )
        if default_branch_output.returncode == 0:
            default_branch = default_branch_output.stdout.strip().split('/')[-1]
        else:
            # Fallback: try to get from remote show
            remote_show = subprocess.run(
                'git remote show origin',
                cwd=cache_dir, shell=True, capture_output=True, text=True
            )
            default_branch = "main"
            for line in remote_show.stdout.splitlines():
                if "HEAD branch" in line:
                    default_branch = line.split(":")[-1].strip()
                    break
        
        subprocess.run(
            f'git checkout --quiet --force origin/{default_branch}',
            cwd=cache_dir, shell=True, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            'git reset --quiet --hard',
            cwd=cache_dir, shell=True, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            'git clean --quiet -fd',
            cwd=cache_dir, shell=True, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    
    elapsed = time.time() - start_time
    print(f"[EXTRACT] Git sync completed in {elapsed:.2f}s (cache {cache_status})")
    return str(cache_dir), cache_status


def run_git(cmd, cwd):
    """
    Run a git command and return stdout (ignoring exit code).
    
    WARNING: This function masks command failures. Use _run_git_checked() when
    you need to detect if a git command failed.
    
    Returns:
        stdout.strip() regardless of exit code
    """
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=True)
    return res.stdout.strip()


def get_churn_metrics(repo_path: str, commit_sha: str) -> dict:
    metrics = {
        "total_files_changed": 0,
        "code_churn_density": 0.0,
        "git_diff_src_churn": 0,
        "git_diff_test_churn": 0,
        "test_to_src_churn_ratio": 0.0,
        "gh_diff_files_added": 0,
        "gh_diff_files_deleted": 0,
        "gh_diff_files_modified": 0,
        "gh_diff_tests_added": 0,
        "gh_diff_tests_deleted": 0,
        "gh_diff_src_files": 0,
        "gh_diff_doc_files": 0,
        "gh_diff_other_files": 0,
        "gh_num_commits_on_files_touched": 0
    }
    # NOTE: use "~1" rather than "^" – under shell=True on Windows the caret is
    # cmd.exe's escape char and gets stripped, so "sha^" resolves back to "sha".
    parent = run_git(f"git rev-parse {commit_sha}~1", repo_path)
    
    # Detect if parent lookup failed (contains "fatal" error message)
    if parent and "fatal" not in parent and parent != commit_sha:
        diff_target = f"{parent} {commit_sha}"
    else:
        # Root commit: diff against the empty tree so the initial import counts as churn.
        empty_tree = run_git("git hash-object -t tree /dev/null", repo_path)
        diff_target = f"{empty_tree} {commit_sha}" if empty_tree else commit_sha
    
    numstat = run_git(f"git diff --numstat {diff_target}", repo_path)
    namestat = run_git(f"git diff --name-status {diff_target}", repo_path)
    
    # If numstat is empty and we expected data, this might be a "git diff" failure
    # Check if commit_sha exists to distinguish between "no changes" and "bad commit"
    if not numstat:
        # Try to verify the commit exists
        success, _ = _run_git_checked(
            f"git rev-parse {commit_sha}",
            repo_path,
            f"verify {commit_sha}"
        )
        if not success:
            raise RuntimeError(
                f"Commit {commit_sha} not found in repository {repo_path}. "
                f"Cannot extract churn metrics."
            )
        # Otherwise, it's OK - commit exists but has no changes
    
    total_added = 0
    total_deleted = 0
    files_touched = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            add_str, del_str, fpath = parts[0], parts[1], parts[2]
            added = int(add_str) if add_str.isdigit() else 0
            deleted = int(del_str) if del_str.isdigit() else 0
            total_added += added
            total_deleted += deleted
            files_touched.append(fpath)
            ext = os.path.splitext(fpath)[1].lower()
            is_test = "test" in fpath.lower()
            if is_test:
                metrics["gh_diff_tests_added"] += added
                metrics["gh_diff_tests_deleted"] += deleted
                metrics["git_diff_test_churn"] += (added + deleted)
            elif ext in SRC_EXTS:
                metrics["git_diff_src_churn"] += (added + deleted)
                metrics["gh_diff_src_files"] += 1
            elif ext in DOC_EXTS:
                metrics["gh_diff_doc_files"] += 1
            else:
                metrics["gh_diff_other_files"] += 1
    for line in namestat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]
            if status == 'A':
                metrics["gh_diff_files_added"] += 1
            elif status == 'D':
                metrics["gh_diff_files_deleted"] += 1
            elif status == 'M':
                metrics["gh_diff_files_modified"] += 1
    metrics["total_files_changed"] = len(files_touched)
    if metrics["total_files_changed"] > 0:
        metrics["code_churn_density"] = round((total_added + total_deleted) / metrics["total_files_changed"], 2)
    if metrics["git_diff_src_churn"] > 0:
        metrics["test_to_src_churn_ratio"] = round(
            metrics["git_diff_test_churn"] / metrics["git_diff_src_churn"], 2
        )
    commits_touched = 0
    for f in files_touched[:10]:
        c_count = run_git(f"git rev-list --count {commit_sha} -- \"{f}\"", repo_path)
        if c_count.isdigit():
            commits_touched += int(c_count)
    metrics["gh_num_commits_on_files_touched"] = commits_touched
    return metrics


def get_repo_git_metrics(repo_path: str, commit_sha: str) -> dict:
    metrics = {}
    total_commits = run_git(f"git rev-list --count {commit_sha}", repo_path)
    metrics["gh_repo_num_commits"] = int(total_commits) if total_commits.isdigit() else 1
    branch = run_git("git rev-parse --abbrev-ref HEAD", repo_path)
    metrics["git_branch"] = branch if branch else "main"
    parents = run_git(f"git log --pretty=%P -n 1 {commit_sha}", repo_path).split()
    metrics["git_merged_with"] = parents[1] if len(parents) > 1 else ""
    metrics["git_merged_with_present"] = 1 if len(parents) > 1 else 0
    metrics["gh_num_commits_in_push"] = 1
    metrics["gh_commits_in_push"] = commit_sha
    first_commit_date = run_git("git log --reverse --format=%ad --date=iso", repo_path).splitlines()
    target_commit_date = run_git(f"git log -1 --format=%ad --date=iso {commit_sha}", repo_path)
    if first_commit_date and target_commit_date:
        try:
            d_first = datetime.fromisoformat(first_commit_date[0].split("+")[0].strip())
            d_target = datetime.fromisoformat(target_commit_date.split("+")[0].strip())
            metrics["gh_first_commit_created_at_year"] = d_first.year
            metrics["gh_first_commit_created_at_month"] = d_first.month
            metrics["gh_repo_age"] = (d_target - d_first).days
        except Exception:
            metrics["gh_first_commit_created_at_year"] = 2026
            metrics["gh_first_commit_created_at_month"] = 1
            metrics["gh_repo_age"] = 0
    else:
        metrics["gh_first_commit_created_at_year"] = 2026
        metrics["gh_first_commit_created_at_month"] = 1
        metrics["gh_repo_age"] = 0
    return metrics
