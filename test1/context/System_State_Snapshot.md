# System State

## 架构概览
> 项目尚未包含代码；目标是建立 20 个独立 Python 脚本分别输出匹配编号的 "hello world N"。

## 核心结构
- context/：存放项目元数据（状态快照、路线图、任务编号）
- （暂无代码文件）

## Playbook
> 格式: `[id] 内容 (helpful:X, harmful:Y)`

### Best Practices
- [practice-001] 每个脚本的文件名与输出编号保持一致，便于检查 (helpful:1, harmful:0)

### Anti-Patterns  
- [anti-001] 在单个脚本中输出多个编号，违背独立脚本要求 (helpful:1, harmful:0)

### Techniques
- [tech-001] 使用 f-string 或字符串拼接确保输出精确匹配 "hello world N"（适用于创建编号脚本）

## 下轮注意
- 需要创建 20 个 Python 脚本，输出文本需精确匹配 "hello world {n}"，数字无前导零
- 先确定脚本命名规范，再批量生成与验证
