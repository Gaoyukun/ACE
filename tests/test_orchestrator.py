#!/usr/bin/env python3
"""Unit tests for Orchestrator.py module."""
import subprocess
import sys
from pathlib import Path
from unittest import mock

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import Orchestrator
from Orchestrator import Console, read_task_id, file_exists


class TestConsole:
    """Test Console output helpers."""
    
    def test_info_prints(self, capsys):
        Console.info("test message")
        captured = capsys.readouterr()
        assert "[INFO]" in captured.out
        assert "test message" in captured.out

    def test_success_prints(self, capsys):
        Console.success("done")
        captured = capsys.readouterr()
        assert "[OK]" in captured.out
        assert "done" in captured.out

    def test_warn_prints(self, capsys):
        Console.warn("warning")
        captured = capsys.readouterr()
        assert "[WARN]" in captured.out
        assert "warning" in captured.out

    def test_error_prints(self, capsys):
        Console.error("error message")
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out
        assert "error message" in captured.out

    def test_banner_prints(self, capsys):
        Console.banner("TEST BANNER")
        captured = capsys.readouterr()
        assert "TEST BANNER" in captured.out
        assert "=" in captured.out

    def test_phase_prints(self, capsys):
        Console.phase("INIT", "auditor")
        captured = capsys.readouterr()
        assert "INIT" in captured.out
        assert "auditor" in captured.out


class TestReadTaskId:
    def test_existing_file(self, tmp_path: Path):
        context = tmp_path / "context"
        context.mkdir()
        task_file = context / "current_task_id.txt"
        task_file.write_text("Task-001")
        
        result = read_task_id(tmp_path)
        assert result == "Task-001"

    def test_missing_file(self, tmp_path: Path):
        result = read_task_id(tmp_path)
        assert result is None

    def test_empty_file(self, tmp_path: Path):
        context = tmp_path / "context"
        context.mkdir()
        task_file = context / "current_task_id.txt"
        task_file.write_text("")
        
        result = read_task_id(tmp_path)
        assert result is None

    def test_whitespace_stripped(self, tmp_path: Path):
        context = tmp_path / "context"
        context.mkdir()
        task_file = context / "current_task_id.txt"
        task_file.write_text("  Task-002  \n")
        
        result = read_task_id(tmp_path)
        assert result == "Task-002"


class TestFileExists:
    def test_existing_file(self, tmp_path: Path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        assert file_exists(tmp_path, "test.txt") is True

    def test_missing_file(self, tmp_path: Path):
        assert file_exists(tmp_path, "nonexistent.txt") is False

    def test_nested_path(self, tmp_path: Path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "file.md").write_text("content")
        
        assert file_exists(tmp_path, "a/b/file.md") is True


class TestCLI:
    def test_help_works(self):
        result = subprocess.run(
            [sys.executable, "Orchestrator.py", "--help"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "--usr-cwd" in result.stdout
        assert "--requirement" in result.stdout
        assert "--branch-prefix" in result.stdout

    def test_missing_args_fails(self):
        result = subprocess.run(
            [sys.executable, "Orchestrator.py"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "required" in result.stderr.lower()


class TestInvokeCodex:
    def test_successful_invocation(self, tmp_path: Path):
        """Test that invoke_codex calls subprocess correctly."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Task completed\n---\nSESSION_ID: abc123"
        mock_result.stderr = ""
        
        with mock.patch.object(subprocess, 'run', return_value=mock_result) as mock_run:
            output, session_id = Orchestrator.invoke_codex(
                role="auditor",
                usr_cwd=tmp_path,
                task="test task"
            )
            
            assert session_id == "abc123"
            assert "Task completed" in output
            mock_run.assert_called_once()

    def test_failed_invocation_raises(self, tmp_path: Path):
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error occurred"
        
        with mock.patch.object(subprocess, 'run', return_value=mock_result):
            try:
                Orchestrator.invoke_codex(
                    role="commander",
                    usr_cwd=tmp_path,
                    task="test"
                )
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "exited with code 1" in str(e)

    def test_timeout_raises(self, tmp_path: Path):
        with mock.patch.object(
            subprocess, 'run',
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=10)
        ):
            try:
                Orchestrator.invoke_codex(
                    role="executor",
                    usr_cwd=tmp_path,
                    task="test",
                    timeout=10
                )
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "timed out" in str(e)


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        print("pytest not installed, running basic tests...")
        
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            
            # Test read_task_id
            assert read_task_id(tmp) is None
            context = tmp / "context"
            context.mkdir()
            (context / "current_task_id.txt").write_text("Test-001")
            assert read_task_id(tmp) == "Test-001"
            
            # Test file_exists
            (tmp / "exists.txt").write_text("x")
            assert file_exists(tmp, "exists.txt") is True
            assert file_exists(tmp, "nope.txt") is False
            
            print("Basic orchestrator tests passed!")
