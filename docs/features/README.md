# 功能文档约定

`docs/features/` 按功能阶段保存两类同编号文档：

1. **MewCode 功能总结**：记录本项目已经实现的行为、架构、测试证据和限制。
2. **Claude Code 实现对照**：记录 Claude Code 对应能力的公开实现方式、可观察行为，以及与 MewCode 的差异。

## 文档配对

| 编号 | 功能阶段 | MewCode 功能总结 | Claude Code 实现对照 |
|---|---|---|---|
| 000 | 终端纯对话基础 | [000-current-features.md](000-current-features.md) | [000-claude-code-current-features.md](000-claude-code-current-features.md) |
| 001 | 工具系统 | [001-tool-system.md](001-tool-system.md) | [001-claude-code-tool-system.md](001-claude-code-tool-system.md) |
| 002 | Agent Loop 与 Plan Mode | [002-agent-loop.md](002-agent-loop.md) | [002-claude-code-agent-loop.md](002-claude-code-agent-loop.md) |

## 后续新增规则

每完成一部分独立功能，同时新增两份文件：

```text
NNN-功能名称.md
NNN-claude-code-功能名称.md
```

MewCode 功能总结至少记录：

- 功能目标与用户可见行为。
- 架构、关键文件和重要设计决策。
- 配置、快捷键或兼容性变化。
- 自动化测试和 tmux 端到端验收的实际证据。
- 已知限制、后续边界和对应提交。

Claude Code 实现对照至少记录：

- Claude Code 对应能力的公开工作方式。
- 官方资料可以确认的行为。
- 根据 CLI 或公开 API 行为得到、但不能由源码确认的推断。
- Claude Code 未公开的内部实现细节。
- 与当前 MewCode 的关键差异及可借鉴方向。
- 资料链接和核对日期。

## 证据等级

Claude Code 的 CLI 源码没有公开。对照文档必须明确区分以下三种内容：

| 标记 | 含义 |
|---|---|
| **官方确认** | Anthropic 官方文档明确描述的产品行为或公开接口 |
| **合理推断** | 可以从 CLI、协议或公开 SDK 的行为推导，但没有公开源码佐证 |
| **未公开** | 无法确认其内部模块、数据结构、算法或具体实现 |

不得把“合理推断”写成 Claude Code 内部源码事实。Claude Code 更新频繁，对照文档应保留核对日期，并在后续功能阶段重新确认相关资料。
