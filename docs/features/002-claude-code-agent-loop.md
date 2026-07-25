# Claude Code Agent Loop 实现对照

> 对应 MewCode 文档：[002-agent-loop.md](002-agent-loop.md)
>
> 资料核对日期：2026-07-25
> 资料范围：Anthropic 官方 Claude Code 文档

## 1. 阅读边界

Claude Code 的完整 CLI 源码没有公开。官方资料足以确认 Agent 循环、Plan Mode、中断、上下文管理和 checkpoint 的产品行为，但不足以确认内部类、事件类型、并发调度器或状态机。因此本文严格使用“官方确认 / 合理推断 / 未公开”三种证据等级。

## 2. Agent 循环

**官方确认**：Claude Code 把工作过程描述为持续交织的三个阶段：收集上下文、采取行动、验证结果。Claude 会读取和搜索代码、修改文件、执行命令与测试，再根据工具结果决定下一步。这个循环可以串联几十个动作，并在验证失败后调整方向。

```text
用户任务
   ↓
收集上下文
   ↓
采取行动
   ↓
验证结果
   ├─ 继续调查或修正
   └─ 给出最终答复
```

**合理推断**：CLI 内部必然有某种循环控制，把完整工具结果加入下一次模型请求并判断是否继续。这是公开行为所要求的最小机制。

**未公开**：循环是否由一个独立 Runner 类实现、每次模型请求如何编号、默认是否存在固定迭代上限，以及所有停止原因的内部枚举。

MewCode 002 明确实现了独立 `AgentRunner`，并把 10 次迭代上限、连续两轮未知工具、取消、Provider 错误和无效流写成可测试的停止契约。这是 MewCode 自己的架构，不能反推 Claude Code 采用相同结构。

## 3. 工具结果与多步纠偏

**官方确认**：工具调用结果会回到 Claude 的上下文中，影响下一步决策。Claude 会根据搜索、编辑和测试结果继续调用工具，遇到错误时重读、换工具或修改方案。

**合理推断**：普通工具失败必须以模型可理解的结果表示，否则模型无法基于失败原因纠偏；一条工具调用也必须与其结果建立稳定关联。

**未公开**：Claude Code 是否使用统一 `{ok, error_code, data}` 结构、何时提交历史检查点，以及模型流失败时是否采用与 MewCode 相同的“丢弃当前部分响应”事务边界。

MewCode 为每次完整工具批次立即提交检查点，取消时补齐所有调用结果。这样后续 OpenAI 或 Anthropic 请求永远不会看到缺少 tool result 的半个历史。

## 4. 同批工具与并发调度

**官方确认**：Claude Code 可以在一次任务中调用多个工具，工具结果会继续驱动循环。官方文档也展示了并行使用工具和 subagent 的能力。

**合理推断**：相互独立的只读操作适合并行，存在副作用或依赖关系的操作需要更保守的顺序控制。

**未公开**：Claude Code CLI 对同一次模型响应中的多个内置工具如何分组；是否按“相邻读并发、副作用单独串行”分段；完成结果是否由索引排序；取消时如何补齐尚未启动的调用。

MewCode 的分段算法是本项目的显式选择。它只并发三个读工具，所有写、改、命令都严格串行，优先保证可解释的磁盘顺序。

## 5. Plan Mode

**官方确认**：Claude Code 的 Plan Mode 用于先研究代码库并形成计划，不直接修改源码。当前官方文档说明它可以读取文件、搜索和分析代码；某些探索命令可能在安全分类器允许后执行。计划完成后，用户可以批准执行、逐项审查或继续规划；批准后 Claude 退出 Plan Mode 并开始实施。

**合理推断**：Plan Mode 会改变当前可执行动作的权限策略，而不仅仅是在 prompt 中提醒模型“不要修改”。

**未公开**：Claude Code 是否为 Plan Mode 建立单独的工具注册中心、计划就绪状态如何保存、批准选项的内部状态机，以及分类器的实现与规则。

MewCode 002 采用更窄的固定边界：`/plan` 只暴露 Read/Glob/Grep 对应的三个工具，不允许运行任何命令；`/do` 只消费最近一次成功计划。它没有 Claude Code 的交互式批准选项或探索命令分类器。

## 6. 中断与运行中取消

**官方确认**：用户可以随时中断 Claude Code。当前快捷键文档说明 Esc 会停止 Claude，并取消正在运行的工具调用。权限确认也可以拒绝，Claude 会根据拒绝结果调整。

**合理推断**：停止不能只隐藏 UI；CLI 需要把取消传递到活动模型流和工具进程，否则会继续产生副作用或输出。

**未公开**：取消信号采用何种异步原语、并发调用取消时已完成结果是否保留、Shell 子进程树的具体回收算法，以及停止事件是否只有一个。

MewCode 使用显式 `AgentRunControl`，并让 Provider 读取、调度任务和 Shell 进程组共同响应取消。工具阶段仍会提交完整的取消结果检查点，模型流阶段则丢弃未完成响应。

## 7. 上下文管理

**官方确认**：Claude Code 接近上下文窗口上限时会先清理较旧的工具输出，再压缩会话；用户也可以用 `/compact` 主动压缩、用 `/clear` 开始新会话。subagent 使用独立上下文，因此可以把大量探索输出隔离在主会话之外。

**合理推断**：自动循环必须同时管理“工作是否完成”和“上下文是否仍可容纳下一步”，否则长任务会被工具输出淹没。

**未公开**：自动压缩的精确阈值、摘要 prompt、工具输出淘汰算法和 Token 预算调度实现。

MewCode 当前只累计并展示 Token 用量，没有自动压缩、输出清理或 subagent 上下文。10 次迭代上限是安全兜底，不等价于上下文管理。

## 8. Checkpoint 与恢复

**官方确认**：Claude Code 在每个用户 prompt 前捕获代码状态，并保留最近 100 个 checkpoint。checkpoint 只跟踪 Claude 通过文件编辑工具直接做出的更改，不跟踪 Bash 命令修改、手工编辑或外部副作用。用户可以 rewind 对话、代码或两者。

**合理推断**：Claude Code 的对话持久化、文件 checkpoint 和 Agent 循环历史是相互关联但独立的机制。

**未公开**：文件快照的具体存储格式、增量算法、清理策略，以及工具批次中何时写入会话 JSONL。

MewCode 所说的“历史检查点”只保证模型消息和工具结果合法，不保存文件旧版本，也不能撤销命令副作用。两个项目在这里使用了相近词汇，但能力不同。

## 9. 事件流与 Token

**官方确认**：Claude Code 和 Agent SDK 可以流式展示文本、thinking 与工具活动；CLI 会显示上下文和用量相关状态。

**合理推断**：协议事件需要先归一化，界面才能统一展示不同内容类型和工具状态。

**未公开**：Claude Code 是否区分 ProviderEvent 与 AgentEvent、是否使用双路收集器、内部 Token 未知值如何传播，以及事件消费者能否完全脱离 TUI。

MewCode 通过两层事件和 `StreamCollector` 明确分离协议、循环与 UI，并对 usage 缺失坚持显示未知。这是公开、可测试的本项目契约。

## 10. 关键差异

| 主题 | Claude Code | MewCode 002 |
|---|---|---|
| 循环 | 可连续采取和验证大量动作 | 默认最多 10 次模型请求 |
| 停止条件 | 用户可中断，内部完整规则未公开 | 完成、上限、未知工具、取消、Provider/流错误均显式 |
| 工具范围 | 文件、Shell、Web、LSP、MCP、subagent 等 | 六个本地核心工具 |
| 同批调度 | 支持并行能力，内部分段未公开 | 相邻三类读工具并发，副作用严格串行 |
| Plan | 研究、计划、交互式批准，可允许部分探索命令 | 固定三读工具，`/do` 执行最近成功计划 |
| 权限 | 多模式、规则、策略、hooks、sandbox | 只有 Shell 逐次确认 |
| 上下文 | 自动清理和压缩、`/compact`、subagent 隔离 | 内存历史，无压缩 |
| 恢复 | 会话持久化、代码 checkpoint、rewind | 模型历史检查点，无文件撤销 |
| 事件 | 产品行为可见，内部类型未公开 | ProviderEvent / AgentEvent 明确分层 |

## 11. 可借鉴方向

1. 把当前固定 Plan 工具子集扩展为通用权限策略，而不是继续增加模式特例。
2. 增加上下文预算、旧工具输出清理和显式压缩，避免只依赖迭代上限。
3. 把模型历史检查点与文件 checkpoint 分开实现，并明确不可逆 Shell 副作用。
4. 为长命令和大输出增加后台任务与按需读取，避免阻塞主循环。
5. 在保持事件层解耦的前提下增加 subagent，让探索使用独立上下文。

## 12. 官方资料

- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Permission modes](https://code.claude.com/docs/en/permission-modes)
- [Context windows](https://code.claude.com/docs/en/context-window)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing)
- [Tools reference](https://code.claude.com/docs/en/tools-reference)
- [Manage sessions](https://code.claude.com/docs/en/sessions)

这些资料可以确认 Claude Code 的用户可见契约，但不能证明其私有 CLI 使用 MewCode 的 Runner、Collector、Scheduler、事件类型或并发分段算法。
