# System State

## 架构概览
> 已确定命名规范 `hello_world_<N>.py`，并提供示例脚本 `hello_world_1.py` 输出匹配的 "hello world 1" 作为模板。

## 核心结构
- context/：存放项目元数据（状态快照、路线图、任务编号）
- hello_world_1.py：示例脚本，打印 `hello world 1`

## Playbook
> 格式: `[id] 内容 (helpful:X, harmful:Y)`

### Best Practices
- [practice-001] 每个脚本的文件名与输出编号保持一致，脚本主入口仅输出对应编号一行，便于检查与批量执行 (helpful:2, harmful:0)
- [practice-002] 在验证阶段检查文件名中的编号与输出编号一致，防止批量生成时的编号错配 (helpful:0, harmful:0)

### Anti-Patterns  
- [anti-001] 在单个脚本中输出多个编号，违背独立脚本要求 (helpful:2, harmful:0)

### Techniques
- [tech-001] 使用 f-string 或字符串拼接确保输出精确匹配 "hello world N"（适用于创建编号脚本） (helpful:1, harmful:0)

## 下轮注意
- 持续使用命名规范 `hello_world_<N>.py`，每个脚本仅输出一行 `hello world <N>`，数字无前导零
- 批量生成时准备批量校验：运行全部脚本并比对文件名编号与输出编号保持一致
