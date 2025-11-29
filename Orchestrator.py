#!/usr/bin/env python3
"""
ACE Orchestrator - AI Collaboration Engine

Drives a three-role workflow (auditor/commander/executor) to complete tasks,
with git commits after each iteration until the task is finished or aborted.

Stop Signals (from auditor via current_task_id.txt):
    finish  - Project completed successfully (exit 0)
    abort   - Project terminated by auditor (exit 1)

Usage:
    python Orchestrator.py (-i | -r) -d <project_dir> [-R <requirement>]

Options:
    -i, --init          Initialize a new project (requires -R)
    -r, --resume        Resume an existing project
    -d, --usr-cwd       Path to project directory (must be a git repo)
    -R, --requirement   The ultimate goal / requirement (required for -i)
    --branch-prefix     Prefix for task branches (default: task)
    --max-iterations    Maximum iterations before stopping (default: 50)
    -h, --help          Show this help message

Examples:
    # Start a new project:
    python Orchestrator.py -i -d ./myproject -R "Build a REST API with user auth"

    # Resume an existing project:
    python Orchestrator.py -r -d ./myproject

    # With custom branch prefix:
    python Orchestrator.py -i -d ./myproject -R "Add login feature" --branch-prefix feature
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# Add tools to path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from tools.git_ops import (
    GitError,
    create_branch,
    ensure_git_repo,
    get_current_branch,
    stage_and_commit,
)
from tools.codex import set_log_dir

# ============================================================================
# Console Output Helpers
# ============================================================================

class Console:
    """Minimal colored console output for progress visibility."""
    
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    
    @classmethod
    def _print(cls, prefix: str, color: str, msg: str):
        print(f"{color}{prefix}{cls.RESET} {msg}", flush=True)
    
    @classmethod
    def info(cls, msg: str):
        cls._print("[INFO]", cls.BLUE, msg)
    
    @classmethod
    def step(cls, msg: str):
        cls._print("[STEP]", cls.CYAN + cls.BOLD, msg)
    
    @classmethod
    def success(cls, msg: str):
        cls._print("[OK]", cls.GREEN + cls.BOLD, msg)
    
    @classmethod
    def warn(cls, msg: str):
        cls._print("[WARN]", cls.YELLOW, msg)
    
    @classmethod
    def error(cls, msg: str):
        cls._print("[ERROR]", cls.RED + cls.BOLD, msg)
    
    @classmethod
    def fatal(cls, msg: str):
        cls._print("[FATAL]", cls.RED + cls.BOLD, msg)
        sys.exit(1)
    
    @classmethod
    def banner(cls, title: str):
        line = "=" * 60
        print(f"\n{cls.CYAN}{line}{cls.RESET}")
        print(f"{cls.CYAN}{cls.BOLD}  {title}{cls.RESET}")
        print(f"{cls.CYAN}{line}{cls.RESET}\n", flush=True)
    
    @classmethod
    def phase(cls, name: str, role: str):
        print(f"\n{cls.YELLOW}{'─' * 50}{cls.RESET}")
        print(f"{cls.YELLOW}{cls.BOLD}▶ {name}{cls.RESET} {cls.GRAY}[role: {role}]{cls.RESET}")
        print(f"{cls.YELLOW}{'─' * 50}{cls.RESET}\n", flush=True)
    
    @classmethod
    def done(cls):
        print(f"\n{cls.GREEN}{'═' * 60}{cls.RESET}")
        print(f"{cls.GREEN}{cls.BOLD}  ✓ ALL TASKS COMPLETED - PROJECT RELEASED{cls.RESET}")
        print(f"{cls.GREEN}{'═' * 60}{cls.RESET}\n", flush=True)
    
    @classmethod
    def aborted(cls):
        print(f"\n{cls.RED}{'═' * 60}{cls.RESET}")
        print(f"{cls.RED}{cls.BOLD}  ✗ PROJECT ABORTED - TERMINATED BY AUDITOR{cls.RESET}")
        print(f"{cls.RED}{'═' * 60}{cls.RESET}\n", flush=True)


# ============================================================================
# Codex Invocation
# ============================================================================

def invoke_codex(
    role: str,
    usr_cwd: Path,
    task: str,
    timeout: int = 1800
) -> Tuple[str, Optional[str]]:
    """
    Invoke codex.py with a specific role and task.
    
    Returns:
        (output_text, session_id) - session_id may be None if not captured
    
    Raises:
        RuntimeError on codex failure
    """
    codex_script = SCRIPT_DIR / "tools" / "codex.py"
    
    cmd = [
        sys.executable,
        str(codex_script),
        "--role", role,
        "--usr-cwd", str(usr_cwd),
        task
    ]
    
    Console.info(f"Running codex: role={role}")
    Console.info(f"Task: {task[:80]}{'...' if len(task) > 80 else ''}")
    
    try:
        # Use Popen to stream stderr in real-time while capturing stdout
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=None,  # stderr goes directly to console (real-time)
            text=True,
            cwd=str(SCRIPT_DIR)
        )
        
        stdout, _ = process.communicate(timeout=timeout)
        
        if process.returncode != 0:
            raise RuntimeError(f"codex exited with code {process.returncode}")
        
        output = stdout.strip()
        
        # Extract SESSION_ID from output
        session_id = None
        match = re.search(r'SESSION_ID:\s*(\S+)', output)
        if match:
            session_id = match.group(1)
            Console.info(f"Captured SESSION_ID: {session_id}")
        
        return output, session_id
        
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError(f"codex timed out after {timeout}s")


# ============================================================================
# File Helpers
# ============================================================================

def read_task_id(usr_cwd: Path) -> Optional[str]:
    """Read current_task_id.txt and return its content."""
    task_file = usr_cwd / "context" / "current_task_id.txt"
    if not task_file.exists():
        return None
    content = task_file.read_text(encoding="utf-8").strip()
    return content if content else None


def file_exists(usr_cwd: Path, relative_path: str) -> bool:
    """Check if a file exists under usr_cwd."""
    return (usr_cwd / relative_path).exists()


# ============================================================================
# Workflow Phases
# ============================================================================

def phase_init(usr_cwd: Path, requirement: Optional[str], branch_prefix: str, resume: bool = False) -> Tuple[str, str, str]:
    """
    Initialization phase:
    1. Call auditor to initialize/resume context files
    2. Read task_id
    3. Create task branch and commit
    
    Returns:
        (task_id, branch_name, auditor_session_id)
    """
    Console.phase("INITIALIZATION" if not resume else "RESUME", "auditor")
    
    if resume:
        # Resume mode: ask auditor to review existing context and continue
        init_task = (
            f'你是 Linus。这是一个已存在的项目，我们需要继续之前的工作。\n\n'
            f'请阅读 `./context/System_State_Snapshot.md` 和 `./context/Project_Roadmap.md`，\n'
            f'了解当前项目状态和进度。\n\n'
            f'然后检查 `./context/current_task_id.txt`，确认当前任务。\n'
            f'如果需要，更新 Snapshot 和 Roadmap，然后设置下一个要执行的 task_id。'
        )
    else:
        # Init mode: start fresh project
        init_task = (
            f'你是 Linus。这是我们的新项目。\n'
            f'**终极目标:** {requirement}\n\n'
            f'目前项目是空的。请初始化 `context/System_State_Snapshot.md`。\n'
            f'请基于终极目标，创建一个初步的 `context/Project_Roadmap.md`，'
            f'将目标拆解并指定第一个任务。'
        )
    
    output, session_id = invoke_codex("auditor", usr_cwd, init_task)
    
    if not session_id:
        Console.warn("No SESSION_ID captured from auditor init")
        session_id = "unknown"
    
    # Check task_id file
    task_id = read_task_id(usr_cwd)
    if not task_id:
        Console.fatal("Missing context/current_task_id.txt after auditor init")
    
    Console.success(f"Got task_id: {task_id}")
    
    # Always create new task branch (both init and resume)
    base_branch = get_current_branch(usr_cwd)
    branch_name = f"{branch_prefix}/{task_id}"
    actual_branch = create_branch(usr_cwd, branch_name)
    Console.info(f"Created branch: {actual_branch} (from {base_branch})")
    
    # Commit
    commit_msg = f"task {'resume' if resume else 'init'}. auditor_session_id:{session_id}"
    commit_hash = stage_and_commit(usr_cwd, commit_msg)
    if commit_hash:
        Console.success(f"{'Resume' if resume else 'Initial'} commit: {commit_hash[:8]}")
    else:
        Console.warn("Nothing to commit")
    
    return task_id, actual_branch, session_id


def phase_commander(usr_cwd: Path, task_id: str) -> str:
    """
    Commander phase: generate AI_Task_Brief_<task_id>.md
    
    Returns:
        commander_session_id
    """
    Console.phase(f"COMMANDER for Task: {task_id}", "commander")
    
    task = f"task_id: {task_id}"
    output, session_id = invoke_codex("commander", usr_cwd, task)
    
    if not session_id:
        Console.warn("No SESSION_ID from commander")
        session_id = "unknown"
    
    # Check brief file exists
    brief_path = f"context/AI_Task_Brief_{task_id}.md"
    if not file_exists(usr_cwd, brief_path):
        Console.fatal(f"Commander failed to generate {brief_path}")
    
    Console.success(f"Generated: {brief_path}")
    return session_id


def phase_executor(usr_cwd: Path, task_id: str) -> str:
    """
    Executor phase: execute task and generate execution_Log_<task_id>.md
    
    Returns:
        executor_session_id
    """
    Console.phase(f"EXECUTOR for Task: {task_id}", "executor")
    
    task = f"task_id: {task_id}"
    output, session_id = invoke_codex("executor", usr_cwd, task)
    
    if not session_id:
        Console.warn("No SESSION_ID from executor")
        session_id = "unknown"
    
    # Check log file exists
    log_path = f"context/Execution_Log_{task_id}.md"
    if not file_exists(usr_cwd, log_path):
        Console.fatal(f"Executor failed to generate {log_path}")
    
    Console.success(f"Generated: {log_path}")
    return session_id


def phase_auditor_review(usr_cwd: Path, task_id: str) -> str:
    """
    Auditor review phase: review execution log and update current_task_id
    
    Returns:
        auditor_session_id
    """
    Console.phase(f"AUDITOR REVIEW for Task: {task_id}", "auditor")
    
    task = (
        f"task_id: {task_id} 已被executor标记为完成。\n"
        f"请审查 `./context/Execution_Log_{task_id}.md`，\n"
        f"并更新 `./context/current_task_id.txt`。\n"
        f"如果所有任务完成，写入 `finish` 至 `./context/current_task_id.txt` 中。"
    )
    
    output, session_id = invoke_codex("auditor", usr_cwd, task)
    
    if not session_id:
        Console.warn("No SESSION_ID from auditor review")
        session_id = "unknown"
    
    Console.success("Auditor review completed")
    return session_id


def commit_iteration(
    usr_cwd: Path,
    task_id: str,
    commander_sid: str,
    executor_sid: str,
    auditor_sid: str
) -> Optional[str]:
    """Commit changes after one iteration."""
    commit_msg = (
        f"task: {task_id}\n"
        f"commander_session_id: {commander_sid}\n"
        f"executor_session_id: {executor_sid}\n"
        f"auditor_session_id: {auditor_sid}"
    )
    
    commit_hash = stage_and_commit(usr_cwd, commit_msg)
    if commit_hash:
        Console.success(f"Committed: {commit_hash[:8]}")
    else:
        Console.warn("Nothing to commit this iteration")
    
    return commit_hash


# ============================================================================
# Main Orchestration Loop
# ============================================================================

def run_orchestration(
    usr_cwd: Path,
    requirement: Optional[str],
    branch_prefix: str = "task",
    max_iterations: int = 50,
    resume: bool = False
):
    """
    Main orchestration loop.
    
    Runs the init phase, then iterates commander -> executor -> auditor
    until task_id becomes 'finish' or max iterations reached.
    """
    Console.banner("ACE ORCHESTRATOR STARTING")
    Console.info(f"Project: {usr_cwd}")
    Console.info(f"Mode: {'RESUME' if resume else 'INIT'}")
    
    # 设置日志目录为用户项目目录
    set_log_dir(usr_cwd)
    if requirement:
        Console.info(f"Requirement: {requirement[:100]}{'...' if len(requirement) > 100 else ''}")
    
    # Ensure git repo
    try:
        ensure_git_repo(usr_cwd)
    except GitError as e:
        Console.fatal(f"Git error: {e}")
    
    # Ensure context directory exists
    context_dir = usr_cwd / "context"
    context_dir.mkdir(exist_ok=True)
    
    # Init phase
    task_id, branch, init_auditor_sid = phase_init(usr_cwd, requirement, branch_prefix, resume)
    
    # Main loop
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        Console.banner(f"ITERATION {iteration} - Task: {task_id}")
        
        # Commander
        commander_sid = phase_commander(usr_cwd, task_id)
        
        # Executor
        executor_sid = phase_executor(usr_cwd, task_id)
        
        # Auditor review
        auditor_sid = phase_auditor_review(usr_cwd, task_id)
        
        # Commit
        commit_iteration(usr_cwd, task_id, commander_sid, executor_sid, auditor_sid)
        
        # Check completion
        new_task_id = read_task_id(usr_cwd)
        if not new_task_id:
            Console.fatal("current_task_id.txt is missing or empty after auditor review")
        
        # Check for stop signals
        signal = new_task_id.lower()
        if signal == "finish":
            Console.done()
            Console.info(f"🎉 Project released in {iteration} iteration(s)")
            Console.info(f"Branch: {branch}")
            return
        
        if signal == "abort":
            Console.aborted()
            Console.info(f"💀 Project killed after {iteration} iteration(s)")
            Console.info(f"Branch: {branch}")
            Console.warn("Check Project_Roadmap.md for termination reason")
            sys.exit(1)
        
        if new_task_id == task_id:
            Console.warn(f"Task ID unchanged ({task_id}), auditor may have stalled")
        
        task_id = new_task_id
        Console.info(f"Next task: {task_id}")
    
    Console.error(f"Max iterations ({max_iterations}) reached without completion")
    sys.exit(1)


# ============================================================================
# CLI
# ============================================================================

def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ACE Orchestrator - Drive AI collaboration to complete tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\nExamples:
  # Start new project:
  python Orchestrator.py -i -d ./myproject -R "Build a REST API"
  
  # Resume existing project:
  python Orchestrator.py -r -d ./myproject
        """
    )
    
    # Mode selection (mutually exclusive, required)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--init", "-i",
        action="store_true",
        help="Initialize a new project (requires --requirement)"
    )
    mode_group.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume an existing project (reads context files)"
    )
    
    parser.add_argument(
        "--usr-cwd", "-d",
        required=True,
        help="Path to the user project directory (must be a git repo)"
    )
    
    parser.add_argument(
        "--requirement", "-R",
        help="The ultimate goal / requirement (required for --init)"
    )
    
    parser.add_argument(
        "--branch-prefix",
        default="task",
        help="Prefix for task branches (default: task)"
    )
    
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        help="Maximum iterations before giving up (default: 50)"
    )
    
    args = parser.parse_args()
    
    # Validate: --init requires --requirement
    if args.init and not args.requirement:
        parser.error("--init requires --requirement")
    
    return args


def main():
    args = parse_cli_args()
    
    # Resolve and validate usr_cwd
    usr_cwd = Path(args.usr_cwd).expanduser().resolve()
    if not usr_cwd.exists():
        Console.fatal(f"Directory not found: {usr_cwd}")
    if not usr_cwd.is_dir():
        Console.fatal(f"Not a directory: {usr_cwd}")
    
    try:
        run_orchestration(
            usr_cwd=usr_cwd,
            requirement=args.requirement,
            branch_prefix=args.branch_prefix,
            max_iterations=args.max_iterations,
            resume=args.resume
        )
    except GitError as e:
        Console.fatal(f"Git error: {e}")
    except RuntimeError as e:
        Console.fatal(f"Runtime error: {e}")
    except KeyboardInterrupt:
        Console.error("Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
