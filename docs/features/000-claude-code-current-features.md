# Claude Code 终端对话基础实现对照

> 对应 MewCode 文档：[000-current-features.md](000-current-features.md)
>
> 资料核对日期：2026-07-25
> 资料范围：Anthropic 官方 Claude Code 文档

## 1. 阅读边界

Claude Code 是闭源产品。Anthropic 公开了产品行为、配置方式、工具契约和 Agent SDK，但没有公开终端客户端的完整源码。因此本文描述的是“官方公开的工作方式”，不是对其私有类、函数或模块的源码分析。

本文使用三种证据等级：

- **官方确认**：官方文档直接说明。
- **合理推断**：由公开交互行为或 API 形态推导。
- **未公开**：官方没有披露，不能确认。

## 2. 整体工作方式

**官方确认**：Claude Code 将自己定义为运行在终端中的 agentic harness。模型负责理解、推理和决定下一步；Claude Code 提供上下文管理、工具与执行环境。用户输入、模型回答、工具调用和工具结果共同构成一个可持续迭代的会话。

在只进行文本对话、不调用工具时，可以把公开流程概括为：

```text
终端输入
   ↓
Claude Code 会话与上下文管理
   ↓
Claude 模型请求
   ↓
增量回复与思考状态
   ↓
终端记录 + 本地会话记录
```

**未公开**：终端渲染器、网络客户端、事件总线和会话存储在 Claude Code 私有源码中的具体模块划分。

## 3. 终端交互界面

### 3.1 输入与历史

**官方确认**：Claude Code 的交互模式包含可编辑输入区、对话记录、命令历史和 transcript viewer。输入历史按工作目录保存；`Up`/`Down` 可以浏览历史，`Ctrl+R` 可以反向搜索。全屏渲染模式提供鼠标支持和单独的 transcript viewer。

Claude Code 的多行输入不是只绑定一种快捷键：

- `Option+Enter`：配置 Option/Alt 为 Meta 后换行。
- `Shift+Enter`：受支持终端中直接换行。
- `Ctrl+J`：无需终端配置即可换行。
- `\\` 后按 `Enter`：兼容所有终端的快速换行方式。

这与 MewCode 当前固定使用 `Alt+Enter` 的设计目标相同，但 Claude Code 为终端兼容性提供了更多入口。

### 3.2 中断与继续编辑

**官方确认**：`Esc` 可以立即停止当前回复或工具调用，已完成的工作仍保留；`Ctrl+C` 可以中断运行中的操作，空闲时用于清空输入或退出。用户也可以在 Claude 工作时输入补充指令，当前动作完成后模型会读到新指令并调整下一步。

MewCode 当前允许生成期间编辑草稿，但不允许提交，也没有输入队列。Claude Code 的“边运行边追加指令”已经进入 Agent 循环，能力范围更大。

### 3.3 流式展示

**官方确认**：Claude Code 会实时展示回复和 Shell 输出，并允许用户在回复中途打断；公开 Agent SDK 也提供文本和工具调用的实时流式输出接口。

**合理推断**：终端客户端持续消费模型流事件，并把文本、思考状态和工具状态增量更新到当前消息区域，而不是等待整个响应结束后再渲染。

**未公开**：Claude Code CLI 内部是否直接使用 SSE、如何合并文本片段、刷新频率、背压策略以及终端组件树。

## 4. 多轮会话与上下文

**官方确认**：Claude Code 会把每条消息、工具调用和工具结果写入 `~/.claude/projects/` 下的纯文本 JSONL 会话文件。`--continue`、`--resume` 和 `/resume` 可以继续旧会话；fork 会复制历史到新的 session ID，不改变原会话。

模型上下文不只是聊天历史，还包含：

- 当前会话中的用户消息、模型消息、文件内容和命令输出。
- 系统指令、`CLAUDE.md` 和已加载的 skill。
- 自动记忆 `MEMORY.md` 中受限大小的内容。
- 当前启用工具的定义；大规模 MCP 工具可按需加载。

上下文接近上限时，Claude Code 先清理较旧的工具输出，再自动压缩会话。用户也可以通过 `/compact` 指定压缩重点，通过 `/context` 查看空间占用。

相比之下，MewCode 000 阶段只在当前进程内保存完整成功轮次，没有持久化、恢复、fork、自动记忆或上下文压缩。

## 5. 模型、Provider 与扩展思考

### 5.1 模型来源

**官方确认**：Claude Code 面向 Claude 模型，可以连接 Anthropic API，也支持 Amazon Bedrock、Google Cloud 的 Agent Platform、Microsoft Foundry 和 Claude Platform on AWS。它还支持通过 `ANTHROPIC_BASE_URL` 接入 LLM gateway。

模型可以通过 `/model`、`--model`、`ANTHROPIC_MODEL` 或 settings 中的 `model` 选择。会话内切换模型后，下一次请求会重新读取完整历史，官方文档明确提示这会失去原有 prompt cache。

Claude Code 没有公开提供通用 OpenAI Chat Completions 协议后端。因此 MewCode 的 Anthropic/OpenAI 双协议统一 Provider 是本项目自己的兼容性设计，不能视为复刻 Claude Code。

### 5.2 Extended thinking

**官方确认**：Claude Code 可以通过 `Option+T` 或 `Alt+T` 在会话中切换 extended thinking；模型与 effort level 还可以通过模型配置和设置控制。

**合理推断**：Claude Code 把“是否启用思考”和“如何在 UI 展示思考状态”作为会话级能力处理，再转换为底层 Claude 请求参数。

**未公开**：CLI 私有网络层如何构造 thinking 参数、是否对所有 Provider 使用同一内部事件类型，以及 thinking 内容如何在本地 transcript 中序列化。

## 6. 配置与认证

**官方确认**：Claude Code 主要使用分层 `settings.json`、环境变量和 CLI 参数，而不是单一 YAML 文件。配置可以来自用户、项目、本地项目、组织策略和服务器托管设置，并按优先级合并或覆盖。认证支持 Claude 订阅、Anthropic Console/API 以及受支持的云 Provider。

MewCode 当前的 YAML profile 更小、更直接，适合原型阶段切换多个自定义端点；Claude Code 的配置系统则更关注个人、项目和企业策略的分层治理。

## 7. 错误、取消与恢复

**官方确认**：运行中的回复和工具可以取消，会话可以恢复；文件修改前会创建 checkpoint，用户可以 rewind。配置与运行问题还可通过 `/doctor`、错误参考和调试配置命令定位。

**未公开**：底层 SDK 异常到终端中文案的完整映射表、网络重试次数、超时退避和流断开后的内部状态机。

## 8. 对 MewCode 的直接启示

| 主题 | Claude Code | MewCode 当前状态 | 可借鉴方向 |
|---|---|---|---|
| 会话 | JSONL 持久化，可恢复和 fork | 仅进程内成功历史 | 引入 session ID、持久化和恢复 |
| 上下文 | 自动清理、压缩、记忆和按需工具 | 完整成功历史直接累积 | 增加 token 预算与压缩策略 |
| 输入 | 多种换行、历史搜索、运行中追加指令 | `Alt+Enter`，生成中仅编辑 | 先补跨终端快捷键，再设计 steer 队列 |
| 模型 | Claude 模型及多个受支持云 Provider | Anthropic 与 OpenAI 协议 | 保留统一 Provider，同时增加能力协商 |
| thinking | 会话内切换并与模型配置联动 | YAML 中静态布尔值 | 增加运行时开关和 Provider 能力检测 |
| 恢复 | checkpoint、rewind、resume | 失败轮次不提交历史 | 将会话事务与文件副作用恢复分开设计 |

## 9. 官方资料

- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Interactive mode](https://code.claude.com/docs/en/interactive-mode)
- [Manage sessions](https://code.claude.com/docs/en/sessions)
- [Explore the context window](https://code.claude.com/docs/en/context-window)
- [Model configuration](https://code.claude.com/docs/en/model-config)
- [Claude Code settings](https://code.claude.com/docs/en/settings)
- [Stream responses in real-time](https://code.claude.com/docs/en/agent-sdk/streaming-output)

以上资料只能证明公开行为和接口。涉及 CLI 私有源码的数据结构、模块名或算法时，应继续标记为“未公开”，不能以 Agent SDK 的实现替代 Claude Code CLI 的内部实现。
