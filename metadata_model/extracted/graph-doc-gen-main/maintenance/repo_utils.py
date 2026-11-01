import os
import subprocess
import re
from urllib.parse import urlparse


def resolve_repo_id(repo_path: str, repo_id: str = None) -> str:
    """
    Resolves a deterministic, stable repository identifier.
    
    Resolution Precedence:
    1. Explicitly supplied `repo_id` parameter (if non-empty).
    2. Environment variable `REPO_ID` (if set and non-empty).
    3. Git remote 'origin' URL parsed into 'owner/repo' (for cloned/remote repositories).
    4. Local git top-level directory name as 'local:<dir_name>'.
    5. Fallback: normalized directory name as 'local:<folder_name>'.
    """
    if repo_id and repo_id.strip():
        return repo_id.strip()

    env_repo = os.getenv("REPO_ID")
    if env_repo and env_repo.strip():
        return env_repo.strip()

    abs_path = os.path.abspath(repo_path) if repo_path else os.getcwd()

    # Attempt to detect Git remote origin URL
    try:
        remote_res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=abs_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if remote_res.returncode == 0 and remote_res.stdout.strip():
            raw_url = remote_res.stdout.strip()
            parsed = parse_remote_url(raw_url)
            if parsed:
                return parsed
    except Exception:
        pass

    # Attempt to get Git top-level root directory name
    try:
        toplevel_res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=abs_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if toplevel_res.returncode == 0 and toplevel_res.stdout.strip():
            root_dir = toplevel_res.stdout.strip()
            name = os.path.basename(os.path.normpath(root_dir))
            if name:
                return f"local:{name}"
    except Exception:
        pass

    # Fallback to local directory basename
    dir_name = os.path.basename(os.path.normpath(abs_path))
    return f"local:{dir_name or 'default'}"


def parse_remote_url(url: str) -> str | None:
    """
    Extracts 'owner/repo' from HTTP/HTTPS/SSH Git remote URLs.
    Example:
      'https://github.com/pallets/flask.git' -> 'pallets/flask'
      'git@github.com:torvalds/linux.git' -> 'torvalds/linux'
    """
    clean_url = url.strip()
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # SSH format: git@github.com:owner/repo
    ssh_match = re.match(r"^git@[^:]+:(.+)$", clean_url)
    if ssh_match:
        return ssh_match.group(1).strip("/")

    # HTTP/HTTPS format
    try:
        parsed = urlparse(clean_url)
        path = parsed.path.strip("/")
        if path:
            return path
    except Exception:
        pass

    return None
