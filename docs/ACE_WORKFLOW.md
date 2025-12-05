# ACE Workflow: Generator-Reflector-Curator 架构

## 概述

本文档描述了基于斯坦福 ACE 论文的 Generator-Reflector-Curator 三角色模式在本项目中的工程化实现。

## 核心问题

在多轮对话的软件开发场景中，我们面临以下挑战：

1. **上下文丢失**: 随着对话轮次增加，早期的关键决策和经验容易被遗忘
2. **知识碎片化**: 每次迭代产生的经验教训没有被系统性地积累
3. **重复犯错**: 相同的错误在不同任务中反复出现
4. **无 Ground Truth**: 与学术场景不同，我们没有标准答案可供对比

## 解决方案：四角色协作

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator Loop                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐    ┌───────────┐    ┌───────────┐             │
│  │ Auditor  │───▶│ Commander │───▶│ Generator │             │
│  │ (Curator)│    │           │    │           │             │
│  └────▲─────┘    └───────────┘    └─────┬─────┘             │
│       │                                  │                   │
│       │         ┌───────────┐           │                   │
│       └─────────│ Reflector │◀──────────┘                   │
│                 └───────────┘                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 角色职责

| 角色 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **Auditor** | 项目管理 + Curator | Execution_Log, Reflection | Snapshot (含Playbook), Roadmap, task_id |
| **Commander** | 任务规划 + Bullet提取 | Snapshot (含Playbook), Roadmap | AI_Task_Brief (含引用的Bullets) |
| **Generator** | 代码生成 | Task_Brief, Snapshot | Execution_Log (含使用的Bullets) |
| **Reflector** | 执行反思 | Execution_Log, Task_Brief, Snapshot | Reflection (含Bullet Tags) |

> **注意:** Playbook 是 `System_State_Snapshot.md` 的 Section 4，不是独立文件。Commander 负责从 Snapshot 中提取相关 Bullets 并写入 Task_Brief，Generator 主要依赖 Task_Brief 中已提取的 Bullets。

## Playbook 机制

### 什么是 Playbook？

Playbook 是一个结构化的经验知识库，存储在 `System_State_Snapshot.md` 中。它包含：

- **Best Practices**: 被证明有效的做法
- **Anti-Patterns**: 应该避免的做法
- **Techniques**: 特定场景下的技巧
- **Lessons Learned**: 综合性的经验教训

### Bullet ID 命名规范

```
[category]-[5位数字]

Categories:
- practice: 最佳实践
- anti: 反模式
- tech: 技巧
- lesson: 经验教训
- arch: 架构约束
- style: 代码风格
```

### Bullet 生命周期

```
1. Generator 引用 Bullet → 记录在 Execution_Log
2. Reflector 评估 Bullet → 标记为 helpful/harmful/neutral
3. Auditor/Curator 更新 Bullet → 调整统计数据或执行 ADD/UPDATE/DELETE
```

## 无 Ground Truth 的反思机制

由于我们没有标准答案，Reflector 基于以下证据进行评估：

1. **验收标准 (DoD)**: Commander 定义的预期目标
2. **执行证据**: 编译日志、测试结果、运行时输出
3. **环境反馈**: 错误信息、警告、异常

### 评估逻辑

```
IF 所有 DoD 项都有证据支持 THEN SUCCESS
ELSE IF 部分 DoD 项有证据支持 THEN PARTIAL
ELSE FAILURE
```

## 上下文演进

### 关键信息传递

每轮迭代结束时，Reflector 会识别 "Must Carry Forward" 信息：

- 关键决策和约束
- 未完成的工作
- 用户反馈要点
- 架构变化

这些信息会被 Auditor 整合到 Snapshot 的 `上下文传递` 部分。

### Token 预算管理

Playbook 有 Token 预算限制。当接近预算时：

1. 删除 harmful 标签最多的条目
2. 合并相似条目
3. 精简描述
4. 归档低频使用的条目

## 工作流时序

```
Iteration N:
  1. Auditor: 审查上一轮结果，更新 Playbook，设置 task_id
  2. Commander: 读取 Playbook，生成 Task_Brief
  3. Generator: 引用 Playbook，执行任务，生成 Execution_Log
  4. Reflector: 分析结果，标注 Bullets，生成 Reflection
  5. [User Feedback]: 可选的用户反馈
  6. Git Commit
  
Iteration N+1:
  1. Auditor: 读取 Reflection，执行 Curator 操作...
```

## 与原 ACE 论文的差异

| 方面 | ACE 论文 | 本实现 |
|------|---------|--------|
| 场景 | 单次问答 | 多轮迭代开发 |
| Ground Truth | 有 | 无 |
| Playbook | 独立知识库 | 集成在 Snapshot 中 |
| Curator | 独立角色 | 合并到 Auditor |
| 反思依据 | GT 对比 | DoD + 执行证据 |

## 文件结构

```
context/
├── System_State_Snapshot.md    # 系统状态 + Playbook
├── Project_Roadmap.md          # 项目路线图
├── current_task_id.txt         # 当前任务 ID
├── AI_Task_Brief_[task_id].md  # 任务指令书
├── Execution_Log_[task_id].md  # 执行日志
├── Reflection_[task_id].md     # 反思报告
└── user_feedback.txt           # 用户反馈 (临时)

role/
├── auditor.md      # Auditor + Curator 角色定义
├── commander.md    # Commander 角色定义
├── generator.md    # Generator 角色定义
└── reflector.md    # Reflector 角色定义
```
