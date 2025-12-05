# AI_Task_Brief_Task-001.md

## 1. 🎯 核心目标 (Objective)
> **Context:** 基于 Snapshot System_State_Snapshot.md (Evolving) | **Task ID:** Task-001  
> **一句话目标:** 约定 `scripts/hello_##.py`（两位编号）的命名与独立存放目录，编写并验证脚本 1-5，每个脚本仅打印匹配编号的 `hello world N`。

## 2. 📚 Playbook 引用 (Referenced Bullets)
> **以下 Bullets 必须在本次任务中遵守:**

### Must Apply (必须应用)
| Bullet ID | 类型 | 内容 | 应用方式 |
|-----------|------|------|---------|
| _暂无_ | - | 当前 Playbook 无可用条目 | 按 Snapshot 硬性约束执行 |

### May Reference (可参考)
| Bullet ID | 类型 | 内容 | 适用场景 |
|-----------|------|------|---------|
| _暂无_ | - | 当前 Playbook 无可用条目 | - |

## 3. 🧠 架构设计规范 (The "Good Taste" Spec)
*(在此处定义数据结构，而不是逻辑流程)*

- **数据变更 (Data Structure Changes):**
    - 目录: `scripts/`，仅包含独立脚本文件，无子目录、无共享模块。
    - 文件命名: `hello_XX.py`，`XX` 为零填充两位编号（01-20），文件名与输出编号一一对应，无特殊前缀或别名。
    - 脚本内容形态:
      ```python
      # hello_01.py
      MESSAGE: str = "hello world 1"
      if __name__ == "__main__":
          print(MESSAGE)
      ```
      - 仅一个常量 `MESSAGE`（字符串），无可变全局、无额外函数。
      - `print` 直接使用 `MESSAGE`，不拼接、不格式化，避免条件分支。
- **接口定义 (Signatures):**
    - CLI 入口: `python scripts/hello_XX.py`（输出单行 `hello world N`），无返回值、无参数。

## 4. 🔨 原子执行步骤 (Atomic Implementation Steps)
*(把任务拆解为单细胞生物都能看懂的指令)*

### Step 1: 准备数据 (Prepare Data)
- [目录]: 创建 `scripts/`，确保不存在除脚本外的文件。
- [命名约定]: 建立 `hello_XX.py`（两位编号）模式，后续所有脚本遵守该模式。

### Step 2: 核心逻辑 (Core Logic)
- [文件]: 新增 `hello_01.py` 至 `hello_05.py`，各文件内容仅包含常量 `MESSAGE` 与 `print(MESSAGE)` 的主入口。
- **伪代码 (Pseudo-code):**
  ```python
  MESSAGE = "hello world N"  # N 固定为文件编号
  if __name__ == "__main__":
      print(MESSAGE)
  ```

### Step 3: 接口暴露 (Public Interface)
- 通过 CLI 运行验证：`python scripts/hello_01.py` ... `python scripts/hello_05.py`，输出必须严格等于对应 `MESSAGE`，无额外空格或换行差异。

## 5. ✅ 验收标准 (Definition of Done)

- [ ] `scripts/` 目录存在，包含 `hello_01.py`...`hello_05.py`，命名符合两位编号约定。
- [ ] 每个脚本仅打印一行 `hello world N`，无额外输出或依赖。
- [ ] 运行 5 个脚本的输出均与编号匹配，人工或脚本验证通过。
- [ ] 未引入共享模块、条件分支或跨文件调用，保持脚本独立性。
- [ ] Snapshot 硬性约束得到满足；无 Playbook Bullet 违背。
