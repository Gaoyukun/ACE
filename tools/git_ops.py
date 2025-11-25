#!/usr/bin/env python3
"""
Git operations module for Orchestrator.
Provides atomic, testable git functions with proper error handling.
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


class GitError(Exception):
    """Git operation failed."""
    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


def _run_git(args: list, cwd: Path, check: bool = True) -> Tuple[int, str, str]:
    """
    Execute a git command.
    
    Returns:
        (returncode, stdout, stderr)
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        raise GitError(f"Git command timed out: {' '.join(cmd)}")
    except FileNotFoundError:
        raise GitError("git not found in PATH", returncode=127)


def get_current_branch(cwd: Path) -> str:
    """Get the current branch name."""
    code, out, err = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if code != 0:
        raise GitError(f"Failed to get current branch: {err}", code, err)
    return out


def branch_exists(cwd: Path, branch_name: str) -> bool:
    """Check if a branch exists."""
    code, out, err = _run_git(["rev-parse", "--verify", branch_name], cwd)
    return code == 0


def create_branch(cwd: Path, branch_name: str, base_branch: Optional[str] = None) -> str:
    """
    Create a new branch from the current or specified base branch.
    If branch exists, append a numeric suffix.
    
    Returns:
        The actual branch name created.
    """
    # Find unique branch name
    actual_name = branch_name
    suffix = 1
    while branch_exists(cwd, actual_name):
        actual_name = f"{branch_name}-{suffix}"
        suffix += 1
    
    # Create and checkout
    if base_branch:
        code, out, err = _run_git(["checkout", "-b", actual_name, base_branch], cwd)
    else:
        code, out, err = _run_git(["checkout", "-b", actual_name], cwd)
    
    if code != 0:
        raise GitError(f"Failed to create branch '{actual_name}': {err}", code, err)
    
    return actual_name


def stage_all(cwd: Path) -> None:
    """Stage all changes (git add -A)."""
    code, out, err = _run_git(["add", "-A"], cwd)
    if code != 0:
        raise GitError(f"Failed to stage changes: {err}", code, err)


def commit(cwd: Path, message: str, allow_empty: bool = False) -> Optional[str]:
    """
    Commit staged changes.
    
    Returns:
        Commit hash, or None if nothing to commit (when allow_empty=False).
    """
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    
    code, out, err = _run_git(args, cwd)
    
    # Nothing to commit is not an error
    if code != 0:
        if "nothing to commit" in err or "nothing to commit" in out:
            return None
        raise GitError(f"Failed to commit: {err}", code, err)
    
    # Get the commit hash
    code, hash_out, _ = _run_git(["rev-parse", "HEAD"], cwd)
    return hash_out if code == 0 else None


def stage_and_commit(cwd: Path, message: str) -> Optional[str]:
    """
    Stage all and commit.
    
    Returns:
        Commit hash, or None if nothing to commit.
    """
    stage_all(cwd)
    return commit(cwd, message)


def is_git_repo(cwd: Path) -> bool:
    """Check if the directory is inside a git repository."""
    code, out, err = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return code == 0 and out == "true"


def ensure_git_repo(cwd: Path) -> None:
    """Raise GitError if not inside a git repo."""
    if not is_git_repo(cwd):
        raise GitError(f"'{cwd}' is not inside a git repository")


def has_uncommitted_changes(cwd: Path) -> bool:
    """Check if there are uncommitted changes."""
    code, out, err = _run_git(["status", "--porcelain"], cwd)
    if code != 0:
        raise GitError(f"Failed to check status: {err}", code, err)
    return bool(out)


if __name__ == "__main__":
    # Quick self-test
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        
        # Init repo
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True)
        
        # Create initial commit
        (tmp / "README.md").write_text("# Test")
        stage_and_commit(tmp, "Initial commit")
        
        # Test functions
        assert is_git_repo(tmp), "Should be git repo"
        assert get_current_branch(tmp) in ("main", "master"), "Should be on main/master"
        
        # Create branch
        branch = create_branch(tmp, "task/test-001")
        assert branch == "task/test-001", f"Branch name mismatch: {branch}"
        
        # Create same branch again - should get suffix
        subprocess.run(["git", "checkout", "main"], cwd=tmp, capture_output=True, check=False)
        subprocess.run(["git", "checkout", "master"], cwd=tmp, capture_output=True, check=False)
        branch2 = create_branch(tmp, "task/test-001")
        assert branch2 == "task/test-001-1", f"Expected suffix: {branch2}"
        
        print("All git_ops tests passed!")
