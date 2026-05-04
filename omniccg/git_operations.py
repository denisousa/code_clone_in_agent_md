import os
from pathlib import Path
from git import Repo
from omniccg.utils import safe_rmtree
from omniccg.prints_operations import printInfo, printWarning
from typing import Union
import subprocess
import requests

def get_last_merged_pr_commit(repo: str, github_token: str):
    url = f"https://api.github.com/repos/{repo}/pulls"
    
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    params = {
        "state": "closed",
        "sort": "updated",
        "direction": "desc",
        "per_page": 50
    }

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    pull_requests = response.json()

    for pr in pull_requests:
        if pr.get("merged_at"):
            merge_commit_sha = pr.get("merge_commit_sha")
            pr_number = pr.get("number")
            return merge_commit_sha, pr_number

    return None, None

def clean_git_locks(repo_path: Union[str, Path]) -> None:
    """Remove Git lock files that may prevent operations."""
    repo_path = Path(repo_path)
    git_dir = repo_path / '.git'
    
    if not git_dir.exists():
        return
    
    # Common Git lock files
    lock_files = [
        git_dir / 'index.lock',
        git_dir / 'HEAD.lock',
        git_dir / 'config.lock',
        git_dir / 'shallow.lock',
    ]
    
    for lock_file in lock_files:
        if lock_file.exists():
            try:
                lock_file.unlink()
                print(f"Removed lock file: {lock_file}")
            except Exception as e:
                print(f"Warning: Could not remove lock file {lock_file}: {e}")
    
    # Check refs directory for lock files
    refs_dir = git_dir / 'refs'
    if refs_dir.exists():
        for lock_file in refs_dir.rglob('*.lock'):
            try:
                lock_file.unlink()
                print(f"Removed lock file: {lock_file}")
            except Exception as e:
                print(f"Warning: Could not remove lock file {lock_file}: {e}")


def SetupRepo(ctx: "Context"):
    git_url, paths = ctx.git_url, ctx.paths

    print("Setting up local directory for git repository " + git_url)

    repo_git_dir = os.path.join(paths.repo_dir, ".git")

    if os.path.isdir(repo_git_dir):
        # Open with GitPython and fetch/pull safely (cross‑platform)
        repo = Repo(paths.repo_dir)
        try:
            # Clean Git locks before operations
            clean_git_locks(paths.repo_dir)
            
            # Fetch all remotes
            for remote in repo.remotes:
                remote.fetch(prune=True)
            # Try fast-forward pull on active branch (if not detached)
            if not repo.head.is_detached:
                try:
                    repo.git.pull("--ff-only")
                except Exception:
                    printInfo("Pull --ff-only skipped (non-FF or no upstream). Fetched refs only.")
            else:
                printInfo("Detached HEAD or no branch; fetched refs only.")
        except Exception as e:
            printWarning(f"Git fetch/pull encountered an issue: {e}")
        return

    # Not a git repo but folder exists → clean it
    if os.path.isdir(paths.repo_dir):
        clean_git_locks(paths.repo_dir)
        safe_rmtree(paths.repo_dir)

    # Clone fresh (GitPython)
    os.makedirs(paths.ws_dir, exist_ok=True)
    Repo.clone_from(git_url, paths.repo_dir)
    print(" Repository setup complete.\n")

def GitFecth(commit, ctx, hash_index, logging):
    repo_path = ctx.paths.repo_dir
    # Fetch the base commit
    print(f"  Fetch out commit {commit} ...")
    try:
        subprocess.run(["git", "fetch", "origin", commit], cwd=repo_path, check=True)
        print(f"  ✔ Checked out to commit {commit}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Project: {ctx.git_url} | Index: {hash_index} | Function: 'GitFecth' | Error: {e}")
        printWarning(f"Git fetch/pull encountered an issue: {e}")


def GitCheckout(commit, ctx, hash_index, logging):
    repo_path = ctx.paths.repo_dir

    # Checkout the base commit
    print(f"  Checking out commit {commit} ...")
    try:
        subprocess.run(["git", "checkout", commit], cwd=repo_path, check=True)
        print(f"  ✔ Checked out to commit {commit}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Project: {ctx.git_url} | Index: {hash_index} | Function: 'GitCheckout' | Error: {e}")
        printWarning(f"Git checkout encountered an issue: {e} | commit {commit}")