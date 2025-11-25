#!/usr/bin/env python3
"""Unit tests for git_ops module."""
import subprocess
import sys
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.git_ops import (
    GitError,
    is_git_repo,
    get_current_branch,
    branch_exists,
    create_branch,
    stage_all,
    commit,
    stage_and_commit,
    has_uncommitted_changes,
    ensure_git_repo,
)


def init_test_repo(path: Path) -> None:
    """Initialize a git repo with basic config."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, capture_output=True)


def create_initial_commit(path: Path) -> None:
    """Create initial commit so branch operations work."""
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=path, capture_output=True, check=True)


class TestIsGitRepo:
    def test_valid_repo(self, tmp_path: Path):
        init_test_repo(tmp_path)
        assert is_git_repo(tmp_path) is True

    def test_non_repo(self, tmp_path: Path):
        assert is_git_repo(tmp_path) is False


class TestGetCurrentBranch:
    def test_default_branch(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        branch = get_current_branch(tmp_path)
        assert branch in ("main", "master")

    def test_custom_branch(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        subprocess.run(["git", "checkout", "-b", "feature-x"], cwd=tmp_path, capture_output=True)
        assert get_current_branch(tmp_path) == "feature-x"


class TestBranchExists:
    def test_existing_branch(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        branch = get_current_branch(tmp_path)
        assert branch_exists(tmp_path, branch) is True

    def test_nonexistent_branch(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        assert branch_exists(tmp_path, "nonexistent-branch-xyz") is False


class TestCreateBranch:
    def test_simple_create(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        result = create_branch(tmp_path, "task/test-001")
        assert result == "task/test-001"
        assert get_current_branch(tmp_path) == "task/test-001"

    def test_auto_suffix_on_conflict(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        
        # Create first branch
        create_branch(tmp_path, "task/dup")
        subprocess.run(["git", "checkout", "-"], cwd=tmp_path, capture_output=True)
        
        # Create again - should get suffix
        result = create_branch(tmp_path, "task/dup")
        assert result == "task/dup-1"


class TestStageAndCommit:
    def test_commit_changes(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        
        (tmp_path / "new_file.txt").write_text("content")
        hash_val = stage_and_commit(tmp_path, "Add new file")
        
        assert hash_val is not None
        assert len(hash_val) == 40  # SHA-1 hex

    def test_nothing_to_commit(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        
        result = stage_and_commit(tmp_path, "Empty commit")
        assert result is None


class TestHasUncommittedChanges:
    def test_clean_repo(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        assert has_uncommitted_changes(tmp_path) is False

    def test_dirty_repo(self, tmp_path: Path):
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        (tmp_path / "dirty.txt").write_text("uncommitted")
        assert has_uncommitted_changes(tmp_path) is True


class TestEnsureGitRepo:
    def test_valid_repo(self, tmp_path: Path):
        init_test_repo(tmp_path)
        ensure_git_repo(tmp_path)  # Should not raise

    def test_non_repo_raises(self, tmp_path: Path):
        try:
            ensure_git_repo(tmp_path)
            assert False, "Should have raised GitError"
        except GitError as e:
            assert "not inside a git repository" in str(e)


class TestIndexLockRecovery:
    """Test automatic index.lock cleanup."""
    
    def test_stage_with_stale_lock(self, tmp_path: Path):
        """Git operations should succeed even with stale index.lock."""
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        
        # Create a stale lock file
        lock_file = tmp_path / ".git" / "index.lock"
        lock_file.write_text("stale lock")
        assert lock_file.exists()
        
        # Stage should auto-clear lock and succeed
        (tmp_path / "new.txt").write_text("content")
        hash_val = stage_and_commit(tmp_path, "Should work despite lock")
        
        assert hash_val is not None
        assert not lock_file.exists()  # Lock should be cleared

    def test_commit_with_stale_lock(self, tmp_path: Path):
        """Commit should work after auto-clearing stale lock."""
        init_test_repo(tmp_path)
        create_initial_commit(tmp_path)
        
        (tmp_path / "file.txt").write_text("data")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
        
        # Create lock after staging
        lock_file = tmp_path / ".git" / "index.lock"
        lock_file.write_text("lock")
        
        # Import commit function
        from tools.git_ops import commit
        hash_val = commit(tmp_path, "Test commit")
        
        assert hash_val is not None


if __name__ == "__main__":
    # Run with pytest if available, otherwise basic execution
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        print("pytest not installed, running basic tests...")
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            
            # Test is_git_repo
            assert is_git_repo(tmp) is False
            init_test_repo(tmp)
            assert is_git_repo(tmp) is True
            create_initial_commit(tmp)
            
            # Test branch operations
            branch = get_current_branch(tmp)
            assert branch in ("main", "master")
            
            new_branch = create_branch(tmp, "task/basic-test")
            assert new_branch == "task/basic-test"
            
            # Test commit
            (tmp / "test.txt").write_text("hello")
            h = stage_and_commit(tmp, "test commit")
            assert h is not None and len(h) == 40
            
            print("All basic tests passed!")
