# System State

## 架构概览
> 20 个 `hello_world_<N>.py` 脚本已按编号就位并通过最终批量验证，项目收尾完成。

## 核心结构
- context/：存放项目元数据（状态快照、路线图、任务编号、执行与反思日志）
- hello_world_1.py...hello_world_20.py：每个脚本独立打印对应的 `hello world <N>`，最终验证通过

## Playbook
> 格式: `[id] 内容 (helpful:X, harmful:Y)`

### Best Practices
- [practice-001] 文件名与输出编号保持一致；复制模板时同步更新输出和 docstring/注释中的编号，入口仅输出对应编号一行 (helpful:4, harmful:0)
- [practice-002] 在验证阶段批量运行脚本并比对文件名编号与输出编号一致，发现偏差立即停止修正 (helpful:2, harmful:0)
- [practice-new] 批量生成相似脚本时保留可复用的批量验证脚本，记录期望与实际输出便于回归 (helpful:1, harmful:0)

### Anti-Patterns  
- [anti-001] 在单个脚本中输出多个编号，违背独立脚本要求 (helpful:4, harmful:0)

### Techniques
- [tech-001] 使用 f-string 或字符串拼接确保输出精确匹配 "hello world N"（适用于创建编号脚本） (helpful:1, harmful:0)

## 下轮注意
- 如需扩展或新增编号，保持命名规范与单行输出，并同步更新注释与验证范围
- 继续复用批量验证脚本，确保文件存在性、输出与编号匹配后再发布
