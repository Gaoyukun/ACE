#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
CODEX_SCRIPT = SCRIPT_DIR / 'tools' / 'codex.py'
SESSION_RE = re.compile(r"SESSION_ID:\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
BRIEF_PREFIX = "AI_Task_Brief_"
EXEC_LOG_PREFIX = "execution_Log_"


def info(message: str):
    print(f"[INFO] {message}")


def warn(message: str):
    print(f"[WARN] {message}")


def fail(message: str, code: int = 1):
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(code)


def parse_cli():
    parser = argparse.ArgumentParser(
        description="Orchestrate codex roles to drive a task loop."
    )
    parser.add_argument("--usr-cwd", required=True, help="Target user workspace.")
    parser.add_argument("--requirement", required=True, help="Ultimate goal text.")
    parser.add_argument(
        "--branch-prefix",
        default="task",
        help="Prefix for new task branches (default: task).",
    )
    return parser.parse_args()


def resolve_usr_cwd(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    path = path if path.is_absolute() else (Path.cwd() / path)
    path = path.resolve()
    if not path.exists():
        fail(f"usr_cwd not found: {path}")
    if not path.is_dir():
        fail(f"usr_cwd is not a directory: {path}")
    return path


def ensure_codex_script():
    if not CODEX_SCRIPT.exists():
        fail(f"codex script missing: {CODEX_SCRIPT}")


def run_command(cmd, cwd: Path, label: str, allow_fail: bool = False) -> subprocess.CompletedProcess:
    printable = " ".join(str(part) for part in cmd)
    info(f"{label}: {printable}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        if not allow_fail:
            warn(f"{label} exited with code {result.returncode}")
            fail(f"{label} output:\n{result.stdout}", result.returncode or 1)
    return result


def extract_session_id(output: str) -> str:
    match = SESSION_RE.search(output)
    if not match:
        fail("SESSION_ID not found in codex output")
    return match.group(1)


def print_block(title: str, body: str):
    body = (body or "").strip()
    if not body:
        return
    print(f"--- {title} ---")
    print(body)
    print(f"--- end {title} ---")


def run_codex(role: str, command: str, usr_cwd: Path) -> Tuple[str, str]:
    cmd = [
        sys.executable,
        str(CODEX_SCRIPT),
        "--usr-cwd",
        str(usr_cwd),
        "--role",
        role,
        command,
    ]
    result = run_command(cmd, SCRIPT_DIR, f"codex[{role}]")
    output = result.stdout or ""
    print_block(f"codex[{role}] output", output)
    session_id = extract_session_id(output)
    info(f"codex[{role}] session: {session_id}")
    return session_id, output


def context_root(usr_cwd: Path) -> Path:
    for name in ("context", "contex"):
        candidate = usr_cwd / name
        if candidate.exists():
            return candidate
    return usr_cwd / "context"


def read_current_task_id(usr_cwd: Path) -> str:
    ctx_dir = context_root(usr_cwd)
    path = ctx_dir / "current_task_id.txt"
    if not path.exists():
        fail(f"Missing current_task_id.txt at {path}")
    task_id = path.read_text(encoding="utf-8").strip()
    if not task_id:
        fail(f"current_task_id.txt is empty at {path}")
    return task_id


def locate_context_artifact(prefix: str, task_id: str, usr_cwd: Path) -> Path:
    ctx_dir = context_root(usr_cwd)
    variants = [
        ctx_dir / f"{prefix}{task_id}.md",
        ctx_dir / f"{prefix}{task_id.replace('/', '_').replace('\\', '_')}.md",
    ]
    for path in variants:
        if path.exists():
            return path
    fail(
        f"Expected artifact for task {task_id} not found. Checked: "
        + ", ".join(str(p) for p in variants)
    )
    return variants[0]


def ensure_git_repo(usr_cwd: Path):
    result = run_command(
        ["git", "rev-parse", "--is-inside-work-tree"], usr_cwd, "git repo check", allow_fail=True
    )
    if result.returncode != 0 or (result.stdout or "").strip() != "true":
        fail(f"{usr_cwd} is not a git repository")


def current_branch(usr_cwd: Path) -> str:
    result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], usr_cwd, "git branch name"
    )
    branch = (result.stdout or "").strip()
    if not branch:
        fail("Unable to determine current git branch")
    return branch


def branch_exists(name: str, usr_cwd: Path) -> bool:
    result = run_command(
        ["git", "rev-parse", "--verify", f"refs/heads/{name}"],
        usr_cwd,
        f"git check branch {name}",
        allow_fail=True,
    )
    return result.returncode == 0


def sanitize_branch_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    safe = safe.strip("-") or "task"
    return safe[:48]


def allocate_branch_name(base: str, usr_cwd: Path) -> str:
    candidate = base
    counter = 1
    while branch_exists(candidate, usr_cwd):
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def create_task_branch(task_id: str, usr_cwd: Path, prefix: str) -> str:
    base_branch = current_branch(usr_cwd)
    task_component = sanitize_branch_component(task_id)
    raw_name = f"{prefix}/{task_component}" if prefix else task_component
    branch_name = allocate_branch_name(raw_name, usr_cwd)
    run_command(["git", "checkout", "-b", branch_name, base_branch], usr_cwd, "git create branch")
    info(f"Branch created: {branch_name} (from {base_branch})")
    return branch_name


def commit_all(usr_cwd: Path, message: str):
    run_command(["git", "add", "--all"], usr_cwd, "git add")
    status = run_command(["git", "status", "--porcelain"], usr_cwd, "git status")
    if not (status.stdout or "").strip():
        warn("No changes to commit; skipping commit.")
        return
    run_command(["git", "commit", "-m", message], usr_cwd, "git commit")


def build_init_prompt(requirement: str) -> str:
    return (
        f"你是 Linus。这是我们的新项目。 **终极目标:** {requirement}. 目前项目是空的。"
        "请初始化 `context\\System_State_Snapshot.md`。 "
        "请基于终极目标，创建一个初步的 `context\\Project_Roadmap.md`，将目标拆解并指定第一个任务。 "
        "务必写入 `context\\current_task_id.txt`，记录当前任务的 task_id。"
    )


def main():
    args = parse_cli()
    usr_cwd = resolve_usr_cwd(args.usr_cwd)
    ensure_codex_script()
    ensure_git_repo(usr_cwd)

    info(f"Workspace: {usr_cwd}")
    info(f"Requirement: {args.requirement}")

    init_prompt = build_init_prompt(args.requirement)
    auditor_session_id, _ = run_codex("auditor", init_prompt, usr_cwd)

    task_id = read_current_task_id(usr_cwd)
    info(f"Initial task_id: {task_id}")

    create_task_branch(task_id, usr_cwd, args.branch_prefix)
    commit_all(usr_cwd, f"task init. auditor_session_id:[{auditor_session_id}]")

    current = task_id
    while True:
        commander_session_id, _ = run_codex("commander", f"task_id: {current}", usr_cwd)
        brief_path = locate_context_artifact(BRIEF_PREFIX, current, usr_cwd)
        info(f"Commander produced brief at {brief_path}")

        executor_session_id, _ = run_codex("executor", f"task_id: {current}", usr_cwd)
        log_path = locate_context_artifact(EXEC_LOG_PREFIX, current, usr_cwd)
        info(f"Executor log located at {log_path}")

        auditor_prompt = (
            f"task_id: {current} 已被executor标记为完成, 请审查`./context/{log_path.name}`, "
            "并更新`./context/current_task_id.txt`, 如果任务完成, 写入`finish`至`./context/current_task_id.txt`中."
        )
        auditor_session_id, _ = run_codex("auditor", auditor_prompt, usr_cwd)

        next_task_id = read_current_task_id(usr_cwd)
        if next_task_id.strip().lower() == "finish":
            info("All tasks completed. Exiting.")
            break

        commit_message = (
            f"task: [{current}].\n"
            f"commander_session_id:[{commander_session_id}]\n"
            f"auditor_session_id:[{auditor_session_id}]\n"
            f"executor_session_id:[{executor_session_id}]"
        )
        commit_all(usr_cwd, commit_message)
        current = next_task_id


if __name__ == "__main__":
    main()
