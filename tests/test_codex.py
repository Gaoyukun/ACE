#!/usr/bin/env python3
"""Unit tests for codex.py module."""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import tools.codex as codex


class TestNormalizeText:
    def test_string_passthrough(self):
        assert codex.normalize_text("hello") == "hello"

    def test_list_join(self):
        assert codex.normalize_text(["a", "b", "c"]) == "abc"

    def test_none_for_invalid(self):
        assert codex.normalize_text(123) is None
        assert codex.normalize_text(None) is None


class TestShouldStreamViaStdin:
    def test_piped_true(self):
        assert codex.should_stream_via_stdin("short", piped=True) is True

    def test_newline_triggers(self):
        assert codex.should_stream_via_stdin("line1\nline2", piped=False) is True

    def test_backslash_triggers(self):
        assert codex.should_stream_via_stdin("path\\to\\file", piped=False) is True

    def test_long_text_triggers(self):
        long_text = "x" * 801
        assert codex.should_stream_via_stdin(long_text, piped=False) is True

    def test_short_simple_text_false(self):
        assert codex.should_stream_via_stdin("simple task", piped=False) is False


class TestResolveUsrCwd:
    def test_valid_directory(self, tmp_path: Path):
        result = codex.resolve_usr_cwd(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_relative_path(self, tmp_path: Path):
        # Create a subdir
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        # Change to tmp_path and resolve relative
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = codex.resolve_usr_cwd("subdir")
            assert result == subdir.resolve()
        finally:
            os.chdir(original_cwd)

    def test_nonexistent_exits(self, tmp_path: Path):
        with mock.patch.object(sys, 'exit', side_effect=SystemExit(1)) as mock_exit:
            try:
                codex.resolve_usr_cwd(str(tmp_path / "nonexistent"))
            except SystemExit:
                pass
            mock_exit.assert_called_with(1)

    def test_file_not_dir_exits(self, tmp_path: Path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        
        with mock.patch.object(sys, 'exit', side_effect=SystemExit(1)) as mock_exit:
            try:
                codex.resolve_usr_cwd(str(file_path))
            except SystemExit:
                pass
            mock_exit.assert_called_with(1)


class TestApplyRoleFile:
    def test_valid_role_copies_file(self, tmp_path: Path):
        # Create role directory and file
        role_dir = tmp_path / "role"
        role_dir.mkdir()
        role_file = role_dir / "testrole.md"
        role_file.write_text("# Test Role Content")
        
        usr_cwd = tmp_path / "project"
        usr_cwd.mkdir()
        
        # Patch ROLE_DIR
        with mock.patch.object(codex, 'ROLE_DIR', role_dir):
            codex.apply_role_file("testrole", usr_cwd)
        
        agents_file = usr_cwd / "AGENTS.md"
        assert agents_file.exists()
        assert agents_file.read_text() == "# Test Role Content"

    def test_case_insensitive_role(self, tmp_path: Path):
        role_dir = tmp_path / "role"
        role_dir.mkdir()
        (role_dir / "auditor.md").write_text("auditor content")
        
        usr_cwd = tmp_path / "project"
        usr_cwd.mkdir()
        
        with mock.patch.object(codex, 'ROLE_DIR', role_dir):
            codex.apply_role_file("AUDITOR", usr_cwd)
        
        assert (usr_cwd / "AGENTS.md").read_text() == "auditor content"

    def test_none_role_does_nothing(self, tmp_path: Path):
        codex.apply_role_file(None, tmp_path)
        assert not (tmp_path / "AGENTS.md").exists()

    def test_missing_role_exits(self, tmp_path: Path):
        role_dir = tmp_path / "role"
        role_dir.mkdir()
        
        with mock.patch.object(codex, 'ROLE_DIR', role_dir):
            with mock.patch.object(sys, 'exit', side_effect=SystemExit(1)) as mock_exit:
                try:
                    codex.apply_role_file("nonexistent", tmp_path)
                except SystemExit:
                    pass
                mock_exit.assert_called_with(1)


class TestParseArgs:
    def test_simple_task(self):
        with mock.patch.object(sys, 'argv', ['codex.py', 'do something']):
            result = codex.parse_args()
            assert result['mode'] == 'new'
            assert result['task'] == 'do something'
            assert result['role'] is None

    def test_task_with_role(self):
        with mock.patch.object(sys, 'argv', ['codex.py', '--role', 'auditor', 'task text']):
            result = codex.parse_args()
            assert result['role'] == 'auditor'
            assert result['task'] == 'task text'

    def test_task_with_usr_cwd(self):
        with mock.patch.object(sys, 'argv', ['codex.py', '--usr-cwd', '/some/path', 'task']):
            result = codex.parse_args()
            assert result['usr_cwd'] == '/some/path'

    def test_resume_mode(self):
        with mock.patch.object(sys, 'argv', ['codex.py', 'resume', 'session123', 'continue task']):
            result = codex.parse_args()
            assert result['mode'] == 'resume'
            assert result['session_id'] == 'session123'
            assert result['task'] == 'continue task'

    def test_combined_options(self):
        with mock.patch.object(sys, 'argv', [
            'codex.py', 
            '--role', 'executor',
            '--usr-cwd', '/project',
            '-i', 'rules.md',
            'execute task'
        ]):
            result = codex.parse_args()
            assert result['role'] == 'executor'
            assert result['usr_cwd'] == '/project'
            assert result['instructions'] == 'rules.md'
            assert result['task'] == 'execute task'

    def test_no_task_exits(self):
        with mock.patch.object(sys, 'argv', ['codex.py']):
            with mock.patch.object(sys, 'exit', side_effect=SystemExit(1)) as mock_exit:
                try:
                    codex.parse_args()
                except SystemExit:
                    pass
                mock_exit.assert_called_with(1)


class TestBuildCodexArgs:
    def test_new_mode_simple(self):
        params = {'mode': 'new', 'usr_cwd': '.', 'task': 'test'}
        args = codex.build_codex_args(params, 'test')
        assert 'codex' in args
        assert 'e' in args
        assert '--json' in args
        assert 'test' in args

    def test_new_mode_with_cwd(self):
        params = {'mode': 'new', 'usr_cwd': '/some/path', 'task': 'test'}
        args = codex.build_codex_args(params, 'test')
        assert '-C' in args
        assert '/some/path' in args

    def test_resume_mode(self):
        params = {'mode': 'resume', 'usr_cwd': '.', 'session_id': 'abc123', 'task': 'continue'}
        args = codex.build_codex_args(params, 'continue')
        assert 'resume' in args
        assert 'abc123' in args
        assert '--skip-git-repo-check' in args

    def test_stdin_mode(self):
        params = {'mode': 'new', 'usr_cwd': '.', 'task': 'long task'}
        args = codex.build_codex_args(params, '-')
        assert args[-1] == '-'

    def test_full_auto_mode(self):
        with mock.patch.dict(os.environ, {'CODEX_FULL_AUTO': '1'}):
            params = {'mode': 'new', 'usr_cwd': '.', 'task': 'test'}
            args = codex.build_codex_args(params, 'test')
            assert '--full-auto' in args


class TestResolveTimeout:
    def test_default_timeout(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove CODEX_TIMEOUT if exists
            os.environ.pop('CODEX_TIMEOUT', None)
            assert codex.resolve_timeout() == codex.DEFAULT_TIMEOUT

    def test_custom_timeout_seconds(self):
        with mock.patch.dict(os.environ, {'CODEX_TIMEOUT': '300'}):
            assert codex.resolve_timeout() == 300

    def test_milliseconds_conversion(self):
        with mock.patch.dict(os.environ, {'CODEX_TIMEOUT': '60000'}):
            assert codex.resolve_timeout() == 60  # 60000ms -> 60s

    def test_invalid_timeout_fallback(self):
        with mock.patch.dict(os.environ, {'CODEX_TIMEOUT': 'invalid'}):
            assert codex.resolve_timeout() == codex.DEFAULT_TIMEOUT


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        print("pytest not installed, running basic validation...")
        
        # Basic tests without pytest
        # TestNormalizeText
        assert codex.normalize_text("hello") == "hello"
        assert codex.normalize_text(["a", "b"]) == "ab"
        assert codex.normalize_text(123) is None
        
        # TestShouldStreamViaStdin
        assert codex.should_stream_via_stdin("x", piped=True) is True
        assert codex.should_stream_via_stdin("a\nb", piped=False) is True
        assert codex.should_stream_via_stdin("short", piped=False) is False
        
        print("Basic codex.py tests passed!")
