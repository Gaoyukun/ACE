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
import logging
import datetime
import traceback
from pathlib import Path
from typing import Optional

DEFAULT_WORKDIR = '.'
DEFAULT_TIMEOUT = 1800  # 2 hours in seconds
FORCE_KILL_DELAY = 5
SCRIPT_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_ROOT = SCRIPT_DIR.parent
ROLE_DIR = ORCHESTRATOR_ROOT / 'role'


# ANSI 颜色码
COLOR_RED = '\033[91m'
COLOR_YELLOW = '\033[93m'
COLOR_RESET = '\033[0m'

# 日志系统初始化
_logger: Optional[logging.Logger] = None
_log_file_path: Optional[Path] = None


def _init_logger(log_dir: Optional[Path] = None, console_only: bool = False):
    """Initialize logger with file and console handlers"""
    global _logger, _log_file_path
    
    if _logger is not None:
        return _logger
    
    _logger = logging.getLogger('ACE')
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()
    
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    
    # Console handler - 输出到 stderr
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    _logger.addHandler(console_handler)
    
    # 如果不是仅控制台模式，添加文件 handler
    if not console_only and log_dir is not None:
        _add_file_handler(log_dir)
    
    return _logger


def _add_file_handler(log_dir: Path):
    """Add file handler to existing logger"""
    global _log_file_path
    
    if _logger is None:
        return
    
    # 日志格式
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    _log_file_path = log_dir / 'ACE.log'
    
    file_handler = logging.FileHandler(_log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    _logger.addHandler(file_handler)


def set_log_dir(log_dir: Path):
    """Set log directory (adds file handler if not already added)"""
    global _log_file_path
    
    # 确保 logger 已初始化
    if _logger is None:
        _init_logger(log_dir)
        return
    
    # 检查是否已有文件 handler
    has_file_handler = any(
        isinstance(h, logging.FileHandler) for h in _logger.handlers
    )
    
    if not has_file_handler:
        _add_file_handler(log_dir)
        log_info(f"Log file: {_log_file_path}")


def get_logger() -> logging.Logger:
    """Get or create the ACE logger (console only until set_log_dir is called)"""
    if _logger is None:
        _init_logger(console_only=True)
    return _logger


def log_error(message: str):
    """输出错误信息"""
    get_logger().error(message)


def log_warn(message: str):
    """输出警告信息"""
    get_logger().warning(message)


def log_info(message: str):
    """输出信息"""
    get_logger().info(message)


def log_debug(message: str):
    """输出调试信息（仅写入文件）"""
    get_logger().debug(message)


def log_codex(message: str):
    """输出 codex 命令信息（红色）"""
    # Console 红色输出
    sys.stderr.write(f"{COLOR_RED}codex {message}{COLOR_RESET}\n")
    # 同时写入日志文件
    get_logger().info(f"CODEX_CMD: codex {message}")


def log_process_event(event_type: str, details: dict):
    """记录进程事件到日志文件（详细调试信息）"""
    log_debug(f"PROCESS_EVENT: {event_type} | {json.dumps(details, ensure_ascii=False)}")


def log_subprocess_error(cmd: list, returncode: int, stderr_output: str = ''):
    """记录子进程错误"""
    msg = f"SUBPROCESS_ERROR: cmd={cmd}, returncode={returncode}"
    if stderr_output:
        msg += f", stderr={stderr_output[:500]}"
    get_logger().error(msg)


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
    yolo = False

    args = sys.argv[1:]
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--yolo':
            yolo = True
            i += 1
            continue
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
            'role': role,
            'yolo': yolo
        }

    workdir = positional[1] if len(positional) > 1 else DEFAULT_WORKDIR
    usr_cwd = usr_cwd_override if usr_cwd_override is not None else workdir
    return {
        'mode': 'new',
        'task': positional[0],
        'usr_cwd': usr_cwd,
        'instructions': instructions,
        'role': role,
        'yolo': yolo
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

    if usr_cwd != '.':
        base_args.extend(['-C', usr_cwd])

    # instructions 通过 task 文本传递，不作为命令行参数

    # 添加 full-auto 模式（如果设置了环境变量或 --yolo 参数）
    if params.get('yolo'):
        base_args.append('--yolo')

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


def _cleanup_process(process: Optional[subprocess.Popen], terminate: bool = True):
    """确保子进程被正确终止并释放所有句柄"""
    if process is None:
        return
    
    try:
        # 关闭所有管道（释放句柄）
        if process.stdin:
            try:
                process.stdin.close()
            except Exception:
                pass
        if process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass
        if process.stderr:
            try:
                process.stderr.close()
            except Exception:
                pass
        
        if terminate:
            # 先尝试优雅终止
            process.terminate()
            try:
                process.wait(timeout=FORCE_KILL_DELAY)
                log_info(f"Process {process.pid} terminated gracefully")
            except subprocess.TimeoutExpired:
                # 强制杀死
                process.kill()
                process.wait(timeout=FORCE_KILL_DELAY)
                log_info(f"Process {process.pid} killed forcefully")
    except Exception as e:
        log_warn(f"Failed to cleanup process: {e}")


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
        log_codex(' '.join(codex_args))
        log_debug(f"Full command args: {codex_args}")
        
        # 完整显示实际任务内容（带颜色区分）- 输出到 stderr 以便实时显示
        MAGENTA = '\033[35m'
        CYAN = '\033[36m'
        RESET = '\033[0m'
        BOLD = '\033[1m'
        print(f"\n{MAGENTA}{'─' * 60}{RESET}", file=sys.stderr)
        print(f"{MAGENTA}{BOLD}📋 PROMPT TO CODEX:{RESET}", file=sys.stderr)
        print(f"{MAGENTA}{'─' * 60}{RESET}", file=sys.stderr)
        print(f"{CYAN}{task_text}{RESET}", file=sys.stderr)
        print(f"{MAGENTA}{'─' * 60}{RESET}\n", file=sys.stderr, flush=True)
        
        log_debug("Creating subprocess...")
        log_process_event("POPEN_START", {"args": codex_args, "use_stdin": use_stdin})
        
        process = subprocess.Popen(
            codex_args,
            stdin=subprocess.PIPE if use_stdin else None,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        
        log_info(f"Process started with PID: {process.pid}")
        log_process_event("POPEN_SUCCESS", {"pid": process.pid})

        # 如果使用 stdin 模式，写入任务到 stdin 并关闭
        if use_stdin and process.stdin is not None:
            process.stdin.write(task_text)
            process.stdin.flush()  # 强制刷新缓冲区，避免大任务死锁
            process.stdin.close()

        # 逐行解析 JSON 输出
        if process.stdout is None:
            log_error('Codex stdout pipe not available')
            sys.exit(1)

        log_info("Reading stdout...")
        verbose = os.environ.get('CODEX_VERBOSE', '').lower() in ('1', 'true', 'yes')

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            # 详细模式：打印原始JSON（截断）
            if verbose:
                display = line[:500] + '...' if len(line) > 500 else line
                log_info(f"RAW: {display}")

            try:
                event = json.loads(line)
                event_type = event.get('type', 'unknown')
                item = event.get('item', {})
                item_type = item.get('type', '')

                # 详细打印事件内容
                if event_type == 'thread.started':
                    log_info(f"Event: {event_type}")
                
                elif event_type == 'item.started':
                    log_info(f"Event: {event_type} ({item_type})")
                
                elif event_type == 'item.completed':
                    log_info(f"Event: {event_type} ({item_type})")
                    
                    # 打印命令执行详情
                    if item_type == 'command_execution':
                        cmd = item.get('command', '')
                        exit_code = item.get('exit_code', '')
                        # codex 使用 aggregated_output 字段存储命令输出
                        output = item.get('aggregated_output') or item.get('output') or ''
                        
                        if cmd:
                            cmd_display = cmd[:300] + '...' if len(cmd) > 300 else cmd
                            log_info(f"  CMD: {cmd_display}")
                        if exit_code is not None:
                            log_info(f"  EXIT: {exit_code}")
                        if output:
                            # 显示输出（截断过长内容）
                            output_lines = output.strip().split('\n')
                            if len(output_lines) > 10:
                                output_display = '\n'.join(output_lines[:10]) + f'\n... ({len(output_lines)-10} more lines)'
                            else:
                                output_display = output.strip()
                            if len(output_display) > 500:
                                output_display = output_display[:500] + '...'
                            log_info(f"  OUTPUT:\n{output_display}")
                    
                    # 打印 reasoning 详情
                    elif item_type == 'reasoning':
                        # 尝试获取思考内容（可能的字段名）
                        text = item.get('text') or item.get('content') or item.get('summary') or ''
                        if isinstance(text, list):
                            text = '\n'.join(str(t) for t in text)
                        if text:
                            # 显示前200字符
                            summary = text[:200].replace('\n', ' ').strip()
                            if len(text) > 200:
                                summary += '...'
                            log_info(f"  THINKING: {summary}")
                    
                    # 打印文件操作详情
                    elif item_type in ('file_write', 'file_change'):
                        filepath = item.get('path') or item.get('file') or ''
                        if filepath:
                            log_info(f"  WRITE: {filepath}")
                    
                    elif item_type == 'file_read':
                        filepath = item.get('path') or item.get('file') or ''
                        if filepath:
                            log_info(f"  READ: {filepath}")
                    
                    # 打印 agent_message 摘要
                    elif item_type == 'agent_message':
                        text = normalize_text(item.get('text'))
                        if text:
                            summary = text[:150].replace('\n', ' ')
                            if len(text) > 150:
                                summary += '...'
                            log_info(f"  MSG: {summary}")

                # 捕获 thread_id
                if event_type == 'thread.started':
                    thread_id = event.get('thread_id')

                # 捕获 agent_message
                if (event_type == 'item.completed' and item_type == 'agent_message'):
                    text = normalize_text(item.get('text'))
                    if text:
                        last_agent_message = text

            except json.JSONDecodeError:
                log_warn(f"Failed to parse line: {line}")

        # 等待进程结束并检查退出码
        returncode = process.wait(timeout=timeout_sec)
        
        # 释放管道句柄（进程已结束，不需要terminate）
        _cleanup_process(process, terminate=False)
        
        if returncode != 0:
            log_error(f'Codex exited with status {returncode}')
            sys.exit(returncode)

        if not last_agent_message:
            log_error('Codex completed without agent_message output')
            sys.exit(1)

        return last_agent_message, thread_id

    except subprocess.TimeoutExpired:
        log_error('Codex execution timeout')
        log_process_event("TIMEOUT", {"timeout_sec": timeout_sec})
        _cleanup_process(process)
        sys.exit(124)

    except FileNotFoundError as e:
        log_error(f"codex command not found in PATH: {e}")
        log_process_event("FILE_NOT_FOUND", {"error": str(e)})
        sys.exit(127)

    except OSError as e:
        # 捕获 Windows 进程创建错误 (0xc0000142 等)
        error_details = {
            "type": type(e).__name__,
            "errno": e.errno,
            "winerror": getattr(e, 'winerror', None),
            "strerror": e.strerror,
            "filename": getattr(e, 'filename', None),
            "message": str(e)
        }
        log_error(f"OS Error during process operation: {e}")
        log_process_event("OS_ERROR", error_details)
        _cleanup_process(process)
        sys.exit(1)

    except KeyboardInterrupt:
        log_error("Codex interrupted by user")
        log_process_event("KEYBOARD_INTERRUPT", {})
        _cleanup_process(process)
        sys.exit(130)

    except Exception as e:
        # 捕获所有其他异常（如 UnicodeDecodeError, BrokenPipeError 等）
        error_details = {
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        log_error(f"Unexpected error: {type(e).__name__}: {e}")
        log_process_event("UNEXPECTED_ERROR", error_details)
        _cleanup_process(process)
        sys.exit(1)


def main():
    log_info("Script started")
    params = parse_args()
    usr_cwd_path = resolve_usr_cwd(params.get('usr_cwd', DEFAULT_WORKDIR))
    params['usr_cwd'] = str(usr_cwd_path)
    
    # 设置日志目录为用户项目目录
    set_log_dir(usr_cwd_path)
    
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
