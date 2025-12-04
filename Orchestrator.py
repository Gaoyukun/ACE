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
    -R, --requirement   Goal (required for -i) or new instructions (for -r)
    --yolo              Enable YOLO mode [default: on]
    --no-yolo           Disable YOLO mode (require confirmation)
    -s, --step          Step mode: pause for feedback [default: on]
    --no-step           Disable step mode (run continuously)
    -b, --new-branch    Create a new branch for the task [default: off]
    --branch-prefix     Prefix for task branches (default: task)
    --max-iterations    Maximum iterations before stopping (default: 50)
    -h, --help          Show this help message

Examples:
    # Start a new project (YOLO + step mode enabled by default):
    python Orchestrator.py -i -d ./myproject -R "Build a REST API with user auth"

    # Resume an existing project:
    python Orchestrator.py -r -d ./myproject

    # Resume with new instructions (override/adjust goals):
    python Orchestrator.py -r -d ./myproject -R "新目标: 修复编译环境"

    # Run continuously without pausing:
    python Orchestrator.py -i -d ./myproject -R "Build API" --no-step

    # Require command confirmation:
    python Orchestrator.py -i -d ./myproject -R "Build API" --no-yolo

    # Create a new branch for the task:
    python Orchestrator.py -i -d ./myproject -R "Build API" -b
"""
import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
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

MAX_CODEX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.0f}s"


def invoke_codex(
    role: str,
    usr_cwd: Path,
    task: str,
    timeout: int = 1800,
    max_retries: int = MAX_CODEX_RETRIES,
    yolo: bool = False
) -> Tuple[str, Optional[str]]:
    """
    Invoke codex.py with a specific role and task, with automatic retry on failure.
    
    Returns:
        (output_text, session_id) - session_id may be None if not captured
    
    Raises:
        RuntimeError on codex failure after all retries exhausted
    """
    codex_script = SCRIPT_DIR / "tools" / "codex.py"
    
    cmd = [
        sys.executable,
        str(codex_script),
        "--role", role,
        "--usr-cwd", str(usr_cwd),
    ]
    if yolo:
        cmd.append("--yolo")
    cmd.append(task)
    
    Console.info(f"Running codex: role={role}")
    Console.info(f"Task: {task[:80]}{'...' if len(task) > 80 else ''}")
    
    last_error = None
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                Console.warn(f"Retry attempt {attempt}/{max_retries}...")
                time.sleep(RETRY_DELAY_SECONDS)
            
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
                last_error = RuntimeError(f"codex exited with code {process.returncode}")
                Console.error(f"Codex failed (exit {process.returncode})")
                continue  # Retry
            
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
            last_error = RuntimeError(f"codex timed out after {timeout}s")
            Console.error(f"Codex timeout ({timeout}s)")
            continue  # Retry
        
        except Exception as e:
            last_error = RuntimeError(f"codex error: {e}")
            Console.error(f"Codex error: {e}")
            continue  # Retry
    
    # All retries exhausted
    Console.error(f"Codex failed after {max_retries} attempts")
    raise last_error


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

def phase_init(usr_cwd: Path, requirement: Optional[str], branch_prefix: str, resume: bool = False, yolo: bool = False, new_branch: bool = False) -> Tuple[str, str, str]:
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
        if requirement:
            init_task += (
                f'\n\n**⚠️ 用户新指令:**\n{requirement}\n\n'
                f'请根据以上指令调整项目目标和任务规划。'
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
    
    output, session_id = invoke_codex("auditor", usr_cwd, init_task, yolo=yolo)
    
    if not session_id:
        Console.warn("No SESSION_ID captured from auditor init")
        session_id = "unknown"
    
    # Check task_id file
    task_id = read_task_id(usr_cwd)
    if not task_id:
        Console.fatal("Missing context/current_task_id.txt after auditor init")
    
    Console.success(f"Got task_id: {task_id}")
    
    # Optionally create new task branch
    if new_branch:
        base_branch = get_current_branch(usr_cwd)
        branch_name = f"{branch_prefix}/{task_id}"
        actual_branch = create_branch(usr_cwd, branch_name)
        Console.info(f"Created branch: {actual_branch} (from {base_branch})")
    else:
        actual_branch = get_current_branch(usr_cwd)
        Console.info(f"Using current branch: {actual_branch}")
    
    # No commit here - first commit happens after commander/executor/user_review in iter 1
    return task_id, actual_branch, session_id


def phase_commander(usr_cwd: Path, task_id: str, yolo: bool = False) -> str:
    """
    Commander phase: generate AI_Task_Brief_<task_id>.md
    
    Returns:
        commander_session_id
    """
    Console.phase(f"COMMANDER for Task: {task_id}", "commander")
    
    task = f"task_id: {task_id}"
    output, session_id = invoke_codex("commander", usr_cwd, task, yolo=yolo)
    
    if not session_id:
        Console.warn("No SESSION_ID from commander")
        session_id = "unknown"
    
    # Check brief file exists
    brief_path = f"context/AI_Task_Brief_{task_id}.md"
    if not file_exists(usr_cwd, brief_path):
        Console.fatal(f"Commander failed to generate {brief_path}")
    
    Console.success(f"Generated: {brief_path}")
    return session_id


def phase_executor(usr_cwd: Path, task_id: str, yolo: bool = False) -> str:
    """
    Executor phase: execute task and generate execution_Log_<task_id>.md
    
    Returns:
        executor_session_id
    """
    Console.phase(f"EXECUTOR for Task: {task_id}", "executor")
    
    task = f"task_id: {task_id}"
    output, session_id = invoke_codex("executor", usr_cwd, task, yolo=yolo)
    
    if not session_id:
        Console.warn("No SESSION_ID from executor")
        session_id = "unknown"
    
    # Check log file exists
    log_path = f"context/Execution_Log_{task_id}.md"
    if not file_exists(usr_cwd, log_path):
        Console.fatal(f"Executor failed to generate {log_path}")
    
    Console.success(f"Generated: {log_path}")
    return session_id


def phase_auditor_review(usr_cwd: Path, task_id: str, yolo: bool = False) -> str:
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
    
    # Check for user feedback from step mode
    feedback_file = usr_cwd / "context" / "user_feedback.txt"
    if feedback_file.exists():
        user_feedback = feedback_file.read_text(encoding="utf-8").strip()
        if user_feedback:
            task += (
                f"\n\n**⚠️ 用户反馈 (User Feedback):**\n"
                f"{user_feedback}\n\n"
                f"请在审查时考虑用户的反馈意见，并在下一轮任务中体现这些修改。"
            )
            Console.info(f"Including user feedback: {user_feedback[:50]}...")
        # Clear feedback file after reading
        feedback_file.unlink()
    
    output, session_id = invoke_codex("auditor", usr_cwd, task, yolo=yolo)
    
    if not session_id:
        Console.warn("No SESSION_ID from auditor review")
        session_id = "unknown"
    
    Console.success("Auditor review completed")
    return session_id


def commit_iteration(
    usr_cwd: Path,
    task_id: str,
    commander_sid: str,
    executor_sid: str
) -> Optional[str]:
    """Commit changes after commander and executor phases."""
    commit_msg = (
        f"task: {task_id}\n"
        f"commander_session_id: {commander_sid}\n"
        f"executor_session_id: {executor_sid}"
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

def prompt_user_feedback() -> Optional[str]:
    """
    Prompt user for feedback in step mode.
    
    Returns:
        User feedback string, or None if user wants to continue without feedback.
        Empty string means user pressed Enter without input (continue).
    """
    Console.step("Step mode: Iteration complete. Enter feedback or press Enter to continue:")
    print(f"{Console.CYAN}(Type 'q' to quit, or enter your feedback){Console.RESET}")
    try:
        feedback = input(f"{Console.YELLOW}> {Console.RESET}").strip()
        if feedback.lower() == 'q':
            return None  # Signal to quit
        return feedback
    except EOFError:
        return None


def run_orchestration(
    usr_cwd: Path,
    requirement: Optional[str],
    branch_prefix: str = "task",
    max_iterations: int = 50,
    resume: bool = False,
    yolo: bool = False,
    step: bool = False,
    new_branch: bool = False
):
    """
    Main orchestration loop.
    
    Runs the init phase, then iterates commander -> executor -> auditor
    until task_id becomes 'finish' or max iterations reached.
    
    If step=True, pauses after each iteration for user feedback.
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
    
    # Init phase: Auditor initializes project and sets first task_id
    init_aud_start = time.time()
    task_id, branch, init_auditor_sid = phase_init(usr_cwd, requirement, branch_prefix, resume, yolo, new_branch)
    init_aud_duration = time.time() - init_aud_start
    
    # Main loop: A -> C -> E -> user_review -> commit
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        Console.banner(f"ITERATION {iteration} - Task: {task_id}")
        iter_start = time.time()
        
        # Auditor (iteration 1 uses init timing)
        if iteration == 1:
            aud_duration = init_aud_duration
        else:
            aud_start = time.time()
            auditor_sid = phase_auditor_review(usr_cwd, task_id, yolo)
            aud_duration = time.time() - aud_start
            
            # Check for stop signals after auditor
            new_task_id = read_task_id(usr_cwd)
            if not new_task_id:
                Console.fatal("current_task_id.txt is missing or empty after auditor review")
            
            signal = new_task_id.lower()
            if signal == "finish":
                Console.done()
                Console.info(f"🎉 Project released in {iteration - 1} iteration(s)")
                Console.info(f"Branch: {branch}")
                return
            
            if signal == "abort":
                Console.aborted()
                Console.info(f"💀 Project killed after {iteration - 1} iteration(s)")
                Console.info(f"Branch: {branch}")
                Console.warn("Check Project_Roadmap.md for termination reason")
                sys.exit(1)
            
            if new_task_id != task_id:
                task_id = new_task_id
                Console.info(f"New task: {task_id}")
        
        # Commander
        cmd_start = time.time()
        commander_sid = phase_commander(usr_cwd, task_id, yolo)
        cmd_duration = time.time() - cmd_start
        
        # Executor
        exec_start = time.time()
        executor_sid = phase_executor(usr_cwd, task_id, yolo)
        exec_duration = time.time() - exec_start
        
        # Ensure all codex output is flushed before printing timing
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(0.5)  # Brief delay for any async output to complete
        
        # Print timing before user feedback
        Console.info("─" * 40)
        Console.info(f"⏱️  Auditor:   {format_duration(aud_duration)}")
        Console.info(f"⏱️  Commander: {format_duration(cmd_duration)}")
        Console.info(f"⏱️  Executor:  {format_duration(exec_duration)}")
        Console.info(f"⏱️  Total:     {format_duration(time.time() - iter_start)}")
        Console.info(f"🕐 Completed: {datetime.now().strftime('%y/%m/%d %H:%M:%S')}")
        Console.info("─" * 40)
        
        # Step mode: pause for user feedback before commit
        if step:
            user_feedback = prompt_user_feedback()
            if user_feedback is None:
                Console.info("User requested quit")
                return
            if user_feedback:
                # Store feedback for next auditor review
                feedback_file = usr_cwd / "context" / "user_feedback.txt"
                feedback_file.write_text(user_feedback, encoding="utf-8")
                Console.info(f"Feedback saved: {user_feedback[:50]}{'...' if len(user_feedback) > 50 else ''}")
        
        # Commit (after user feedback)
        commit_iteration(usr_cwd, task_id, commander_sid, executor_sid)
    
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
  # Start new project (YOLO + step mode on by default):
  python Orchestrator.py -i -d ./myproject -R "Build a REST API"
  
  # Resume existing project:
  python Orchestrator.py -r -d ./myproject
  
  # Run continuously without pausing:
  python Orchestrator.py -i -d ./myproject -R "Build API" --no-step
  
  # Create a new branch for the task:
  python Orchestrator.py -i -d ./myproject -R "Build API" -b
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
    
    parser.add_argument(
        "--yolo",
        action="store_true",
        default=True,
        help="Enable YOLO mode (auto-approve all codex commands) [default: True]"
    )
    parser.add_argument(
        "--no-yolo",
        action="store_false",
        dest="yolo",
        help="Disable YOLO mode (require confirmation for commands)"
    )
    
    parser.add_argument(
        "--step", "-s",
        action="store_true",
        default=True,
        help="Step mode: pause after each iteration for user feedback [default: True]"
    )
    parser.add_argument(
        "--no-step",
        action="store_false",
        dest="step",
        help="Disable step mode (run continuously)"
    )
    
    parser.add_argument(
        "--new-branch", "-b",
        action="store_true",
        default=False,
        help="Create a new branch for the task [default: False]"
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
            resume=args.resume,
            yolo=args.yolo,
            step=args.step,
            new_branch=args.new_branch
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
