# ACE - AI Collaboration Engine

三角色AI协作引擎：`auditor`/`commander`/`executor` 循环驱动任务完成，自动 git commit 记录每轮变更。

## 项目结构

```text
ACE/
├── Orchestrator.py      # 主编排脚本
├── tools/
│   ├── codex.py         # Codex CLI 封装
│   └── git_ops.py       # Git 操作封装
├── role/
│   ├── auditor.md       # 审计员角色定义
│   ├── commander.md     # 指挥官角色定义
│   └── executor.md      # 执行者角色定义
└── tests/               # 单元测试 (63个测试)
```

## 前置条件

- **Python 3.8+**
- **codex CLI** 在 PATH 中可执行
- 目标项目必须是 **git 仓库**

## 快速开始

```bash
python Orchestrator.py --usr-cwd <项目目录> --requirement "你的目标"
```

## CLI 选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--usr-cwd` | 目标项目目录 (必须是git仓库) | 必填 |
| `--requirement`, `-r` | 终极目标描述 | 必填 |
| `--branch-prefix` | 任务分支前缀 | `task` |
| `--max-iterations` | 最大迭代次数 | `50` |

## 工作流程

```text
┌─────────────────────────────────────────────────────────────┐
│  INIT: Auditor 初始化项目                                    │
│    → 创建 context/System_State_Snapshot.md                  │
│    → 创建 context/Project_Roadmap.md                        │
│    → 写入 context/current_task_id.txt                       │
│    → git checkout -b task/<task_id> && git commit           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  LOOP: 直到 current_task_id.txt == "finish"                 │
│                                                             │
│  1. Commander → 生成 AI_Task_Brief_<task_id>.md            │
│  2. Executor  → 执行并生成 execution_Log_<task_id>.md      │
│  3. Auditor   → 审核并更新 current_task_id.txt             │
│  4. Git       → commit 本轮所有变更                         │
└─────────────────────────────────────────────────────────────┘
```

## 输出示例

```text
============================================================
  ACE ORCHESTRATOR STARTING
============================================================

[INFO] Project: D:\Projects\demo
[INFO] Requirement: 构建REST API...

──────────────────────────────────────────────────
▶ INITIALIZATION [role: auditor]
──────────────────────────────────────────────────

[INFO] Running codex: role=auditor
[OK] Got initial task_id: Task-001
[OK] Initial commit: a1b2c3d4

============================================================
  ITERATION 1 - Task: Task-001
============================================================

──────────────────────────────────────────────────
▶ COMMANDER for Task: Task-001 [role: commander]
──────────────────────────────────────────────────

[OK] Generated: context/AI_Task_Brief_Task-001.md

...

════════════════════════════════════════════════════════════
  ✓ ALL TASKS COMPLETED
════════════════════════════════════════════════════════════
```

## 关键文件

| 文件 | 生成者 | 用途 |
|------|--------|------|
| `context/current_task_id.txt` | Auditor | 当前任务ID，`finish`表示完成 |
| `context/System_State_Snapshot.md` | Auditor | 系统状态快照 |
| `context/Project_Roadmap.md` | Auditor | 项目路线图 |
| `context/AI_Task_Brief_<id>.md` | Commander | 任务指令 |
| `context/execution_Log_<id>.md` | Executor | 执行日志 |

## 运行测试

```bash
python -m pytest tests/ -v
```

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| `codex command not found` | 确保 codex CLI 已安装并在 PATH |
| `not inside a git repository` | 在目标目录执行 `git init` |
| `Missing current_task_id.txt` | Auditor 初始化失败，检查 codex 输出 |
| git 锁文件错误 | 删除 `.git/index.lock` |
