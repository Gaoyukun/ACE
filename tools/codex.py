#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""
Codex CLI wrapper with cross-platform support and session management.
**FIXED**: Auto-detect long inputs and use stdin mode to avoid shell argument issues.

Usage:
    New session:  uv run codex.py "task" [workdir] [--instructions path/to/rules.md] [--role auditor] [--usr-cwd DIR]
    Resume:       uv run codex.py --role auditor --usr-cwd DIR resume <session_id> "task"
    Alternative:  python3 codex.py "task" [--role auditor]
    Direct exec:  ./codex.py "task" [--usr-cwd DIR]

Role handling: -role/--role copies <orchestrator>/role/<name>.md to <usr_cwd>/AGENTS.md before invoking codex.
usr_cwd: falls back to positional workdir (or '.') when --usr-cwd is not provided.

    Model configuration: Set CODEX_MODEL environment variable (default: gpt-5.1-codex)
"""
import subprocess
import json
import sys
import os
import shutil
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = os.environ.get('CODEX_MODEL', 'gpt-5.1-codex')
DEFAULT_WORKDIR = '.'
DEFAULT_TIMEOUT = 1800  # 2 hours in seconds
FORCE_KILL_DELAY = 5
SCRIPT_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_ROOT = SCRIPT_DIR.parent
ROLE_DIR = ORCHESTRATOR_ROOT / 'role'


def log_error(message: str):
    """输出错误信息到 stderr"""
    sys.stderr.write(f"ERROR: {message}\n")


def log_warn(message: str):
    """输出警告信息到 stderr"""
    sys.stderr.write(f"WARN: {message}\n")


def log_info(message: str):
    """输出信息到 stderr"""
    sys.stderr.write(f"INFO: {message}\n")


def resolve_timeout() -> int:
    """解析超时配置（秒）"""
    raw = os.environ.get('CODEX_TIMEOUT', '')
    if not raw:
        return DEFAULT_TIMEOUT

    try:
        parsed = int(raw)
        if parsed <= 0:
            log_warn(f"Invalid CODEX_TIMEOUT '{raw}', falling back to {DEFAULT_TIMEOUT}s")
            return DEFAULT_TIMEOUT
        # 环境变量是毫秒，转换为秒
        return parsed // 1000 if parsed > 10000 else parsed
    except ValueError:
        log_warn(f"Invalid CODEX_TIMEOUT '{raw}', falling back to {DEFAULT_TIMEOUT}s")
        return DEFAULT_TIMEOUT


def normalize_text(text) -> Optional[str]:
    """规范化文本：字符串或字符串数组"""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        return ''.join(text)
    return None


def parse_args():
    """解析命令行参数，支持 role 与 usr_cwd"""
    if len(sys.argv) < 2:
        log_error('Task required')
        sys.exit(1)

    instructions = None
    role = None
    usr_cwd_override: Optional[str] = None

    args = sys.argv[1:]
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('--instructions', '-i'):
            if i + 1 >= len(args):
                log_error('--instructions requires a path argument')
                sys.exit(1)
            instructions = args[i + 1]
            i += 2
            continue
        if arg in ('--role', '-role'):
            if i + 1 >= len(args):
                log_error('-role/--role requires a value')
                sys.exit(1)
            role = args[i + 1]
            i += 2
            continue
        if arg in ('--usr-cwd', '--usr_cwd'):
            if i + 1 >= len(args):
                log_error('--usr-cwd requires a path')
                sys.exit(1)
            usr_cwd_override = args[i + 1]
            i += 2
            continue

        positional.append(arg)
        i += 1

    if not positional:
        log_error('Task required')
        sys.exit(1)

    # 检测是否为 resume 模式
    if positional[0] == 'resume':
        if len(positional) < 3:
            log_error('Resume mode requires: resume <session_id> <task>')
            sys.exit(1)
        workdir = positional[3] if len(positional) > 3 else DEFAULT_WORKDIR
        usr_cwd = usr_cwd_override if usr_cwd_override is not None else workdir
        return {
            'mode': 'resume',
            'session_id': positional[1],
            'task': positional[2],
            'usr_cwd': usr_cwd,
            'instructions': instructions,
            'role': role
        }

    workdir = positional[1] if len(positional) > 1 else DEFAULT_WORKDIR
    usr_cwd = usr_cwd_override if usr_cwd_override is not None else workdir
    return {
        'mode': 'new',
        'task': positional[0],
        'usr_cwd': usr_cwd,
        'instructions': instructions,
        'role': role
    }


def resolve_usr_cwd(path_str: str) -> Path:
    """规范化并校验 usr_cwd"""
    path = Path(path_str).expanduser()
    path = path if path.is_absolute() else (Path.cwd() / path)
    path = path.resolve()
    if not path.exists():
        log_error(f"usr_cwd not found: {path}")
        sys.exit(1)
    if not path.is_dir():
        log_error(f"usr_cwd is not a directory: {path}")
        sys.exit(1)
    return path


def apply_role_file(role: Optional[str], usr_cwd_path: Path):
    """将 role 下的 md 复制为目标目录的 AGENTS.md"""
    if not role:
        return

    role_name = role.strip().lower()
    if not role_name:
        log_error("Role value is empty")
        sys.exit(1)

    role_path = ROLE_DIR / f"{role_name}.md"
    if not role_path.exists():
        log_error(f"Role file not found: {role_path}")
        sys.exit(1)

    target_path = usr_cwd_path / 'AGENTS.md'
    try:
        shutil.copyfile(role_path, target_path)
    except Exception as exc:
        log_error(f"Failed to copy role file to {target_path}: {exc}")
        sys.exit(1)

    log_info(f"Applied role '{role_name}' to {target_path}")


def read_piped_task() -> Optional[str]:
    """
    从 stdin 读取任务文本：
    - 如果 stdin 是管道（非 tty）且存在内容，返回读取到的字符串
    - 否则返回 None
    """
    import select

    stdin = sys.stdin
    if stdin is None or stdin.isatty():
        log_info("Stdin is tty or None, skipping pipe read")
        return None

    # 使用 select 检查是否有数据可读（0 秒超时，非阻塞）
    readable, _, _ = select.select([stdin], [], [], 0)
    if not readable:
        log_info("No data available on stdin")
        return None

    log_info("Reading from stdin pipe...")
    data = stdin.read()
    if not data:
        log_info("Stdin pipe returned empty data")
        return None

    log_info(f"Read {len(data)} bytes from stdin pipe")
    return data


def should_stream_via_stdin(task_text: str, piped: bool) -> bool:
    """
    判定是否通过 stdin 传递任务：
    - 有管道输入
    - 文本包含换行
    - 文本包含反斜杠
    - 文本长度 > 800
    """
    if piped:
        return True
    if '\n' in task_text:
        return True
    if '\\' in task_text:
        return True
    if len(task_text) > 800:
        return True
    return False


def build_codex_args(params: dict, target_arg: str) -> list:
    """
    构建 codex CLI 参数

    Args:
        params: 参数字典
        target_arg: 最终传递给 codex 的参数（'-' 或具体 task 文本）
    """
    usr_cwd = params.get('usr_cwd', DEFAULT_WORKDIR)

    if params['mode'] == 'resume':
        base_args = [
            'codex', 'e',
            '--skip-git-repo-check',
            '--json',
        ]
        if usr_cwd != '.':
            base_args.extend(['-C', usr_cwd])
        base_args.extend([
            'resume',
            params['session_id'],
            target_arg
        ])
        return base_args

    base_args = [
        'codex', 'e',
        '--json',
    ]

    # 添加可选参数
    if os.environ.get('CODEX_MODEL'):
        base_args.extend(['-m', DEFAULT_MODEL])

    if usr_cwd != '.':
        base_args.extend(['-C', usr_cwd])

    # instructions 通过 task 文本传递，不作为命令行参数

    # 添加 full-auto 模式（如果设置了环境变量）
    if os.environ.get('CODEX_FULL_AUTO'):
        base_args.append('--full-auto')

    base_args.append(target_arg)
    return base_args


def find_codex_executable() -> str:
    """
    查找 codex 可执行文件的完整路径。
    在 Windows 上，shutil.which 会自动解析 .cmd/.bat/.exe 扩展名。
    """
    codex_path = shutil.which('codex')
    if codex_path:
        return codex_path
    # 回退到直接使用 'codex'，让后续报错处理
    return 'codex'


def run_codex_process(codex_args, task_text: str, use_stdin: bool, timeout_sec: int):
    """
    启动 codex 子进程，处理 stdin / JSON 行输出和错误，成功时返回 (last_agent_message, thread_id)。
    失败路径上负责日志和退出码。
    """
    thread_id: Optional[str] = None
    last_agent_message: Optional[str] = None
    process: Optional[subprocess.Popen] = None

    # 解析 codex 完整路径（Windows 兼容）
    codex_path = find_codex_executable()
    codex_args = [codex_path] + codex_args[1:]  # 替换第一个参数
    log_info(f"Resolved codex path: {codex_path}")

    try:
        # 启动 codex 子进程（文本模式管道）
        log_info(f"Starting codex with args: {' '.join(codex_args[:5])}...")
        process = subprocess.Popen(
            codex_args,
            stdin=subprocess.PIPE if use_stdin else None,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        log_info(f"Process started with PID: {process.pid}")

        # 如果使用 stdin 模式，写入任务到 stdin 并关闭
        if use_stdin and process.stdin is not None:
            log_info(f"Writing {len(task_text)} chars to stdin...")
            process.stdin.write(task_text)
            process.stdin.flush()  # 强制刷新缓冲区，避免大任务死锁
            process.stdin.close()
            log_info("Stdin closed")

        # 逐行解析 JSON 输出
        if process.stdout is None:
            log_error('Codex stdout pipe not available')
            sys.exit(1)

        log_info("Reading stdout...")

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
                event_type = event.get('type', 'unknown')

                # 打印事件类型作为进度提示
                if event_type == 'thread.started':
                    log_info(f"Event: {event_type}")
                elif event_type == 'item.started':
                    item_type = event.get('item', {}).get('type', '')
                    log_info(f"Event: {event_type} ({item_type})")
                elif event_type == 'item.completed':
                    item_type = event.get('item', {}).get('type', '')
                    log_info(f"Event: {event_type} ({item_type})")

                # 捕获 thread_id
                if event_type == 'thread.started':
                    thread_id = event.get('thread_id')

                # 捕获 agent_message
                if (event_type == 'item.completed' and
                    event.get('item', {}).get('type') == 'agent_message'):
                    text = normalize_text(event['item'].get('text'))
                    if text:
                        last_agent_message = text

            except json.JSONDecodeError:
                log_warn(f"Failed to parse line: {line}")

        # 等待进程结束并检查退出码
        returncode = process.wait(timeout=timeout_sec)
        if returncode != 0:
            log_error(f'Codex exited with status {returncode}')
            sys.exit(returncode)

        if not last_agent_message:
            log_error('Codex completed without agent_message output')
            sys.exit(1)

        return last_agent_message, thread_id

    except subprocess.TimeoutExpired:
        log_error('Codex execution timeout')
        if process is not None:
            process.kill()
            try:
                process.wait(timeout=FORCE_KILL_DELAY)
            except subprocess.TimeoutExpired:
                pass
        sys.exit(124)

    except FileNotFoundError:
        log_error("codex command not found in PATH")
        sys.exit(127)

    except KeyboardInterrupt:
        log_error("Codex interrupted by user")
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=FORCE_KILL_DELAY)
            except subprocess.TimeoutExpired:
                process.kill()
        sys.exit(130)


def main():
    log_info("Script started")
    params = parse_args()
    usr_cwd_path = resolve_usr_cwd(params.get('usr_cwd', DEFAULT_WORKDIR))
    params['usr_cwd'] = str(usr_cwd_path)
    log_info(
        f"Parsed args: mode={params['mode']}, task_len={len(params['task'])}, "
        f"usr_cwd={usr_cwd_path}, role={params.get('role') or 'none'}"
    )
    timeout_sec = resolve_timeout()
    log_info(f"Timeout: {timeout_sec}s")

    apply_role_file(params.get('role'), usr_cwd_path)

    piped_task = read_piped_task()
    piped = piped_task is not None
    task_text = piped_task if piped else params['task']

    # 如果有 instructions 文件，读取并拼接到任务前面
    if params.get('instructions'):
        try:
            instr_path = Path(params['instructions']).expanduser()
            with open(instr_path, 'r', encoding='utf-8') as f:
                instructions_content = f.read().strip()
            task_text = f"<instructions>\n{instructions_content}\n</instructions>\n\n{task_text}"
            log_info(f"Loaded instructions from: {instr_path}")
        except Exception as e:
            log_error(f"Failed to read instructions file: {e}")
            sys.exit(1)

    use_stdin = should_stream_via_stdin(task_text, piped)

    if use_stdin:
        reasons = []
        if piped:
            reasons.append('piped input')
        if '\n' in task_text:
            reasons.append('newline')
        if '\\' in task_text:
            reasons.append('backslash')
        if len(task_text) > 800:
            reasons.append('length>800')

        if reasons:
            log_warn(f"Using stdin mode for task due to: {', '.join(reasons)}")

    target_arg = '-' if use_stdin else params['task']
    codex_args = build_codex_args(params, target_arg)

    log_info(f"codex running in {params['usr_cwd']} (mode={params['mode']})...")

    last_agent_message, thread_id = run_codex_process(
        codex_args=codex_args,
        task_text=task_text,
        use_stdin=use_stdin,
        timeout_sec=timeout_sec,
    )

    # 输出 agent_message
    sys.stdout.write(f"{last_agent_message}\n")

    # 输出 session_id（如果存在）
    if thread_id:
        sys.stdout.write(f"\n---\nSESSION_ID: {thread_id}\n")

    sys.exit(0)


if __name__ == '__main__':
    main()
