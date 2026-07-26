# 功能文档约定

`docs/features/` 按功能阶段保存 MewCode 功能总结，记录本项目已经实现的行为、架构、测试证据和限制。

## 历史文档

编号 000-003 曾同时生成 Claude Code 实现对照。这些文件作为历史资料保留，后续功能不再新增或更新对比文档。

| 编号 | 功能阶段 | MewCode 功能总结 | Claude Code 实现对照 |
|---|---|---|---|
| 000 | 终端纯对话基础 | [000-current-features.md](000-current-features.md) | [000-claude-code-current-features.md](000-claude-code-current-features.md) |
| 001 | 工具系统 | [001-tool-system.md](001-tool-system.md) | [001-claude-code-tool-system.md](001-claude-code-tool-system.md) |
| 002 | Agent Loop 与 Plan Mode | [002-agent-loop.md](002-agent-loop.md) | [002-claude-code-agent-loop.md](002-claude-code-agent-loop.md) |
| 003 | 结构化系统提示与缓存 | [003-structured-system-prompt.md](003-structured-system-prompt.md) | [003-claude-code-system-prompt.md](003-claude-code-system-prompt.md) |

编号 003 的固定人工前后对比见 [003-system-prompt-scenarios.md](../evals/003-system-prompt-scenarios.md)。

## 后续新增规则

每完成一部分独立功能，只新增一份 MewCode 功能总结：

```text
NNN-功能名称.md
```

MewCode 功能总结至少记录：

- 功能目标与用户可见行为。
- 架构、关键文件和重要设计决策。
- 配置、快捷键或兼容性变化。
- 自动化测试和 tmux 端到端验收的实际证据。
- 已知限制、后续边界和对应提交。
