# Claude Code 工具系统实现对照

> 对应 MewCode 文档：[001-tool-system.md](001-tool-system.md)
>
> 资料核对日期：2026-07-25
> 资料范围：Anthropic 官方 Claude Code 文档

## 1. 阅读边界

Claude Code 的完整 CLI 源码没有公开。官方文档公开了工具名称、行为、权限、Agent 循环和会话结果，但没有公开内部 Tool 基类、注册中心、JSON 拼接器或调度器源码。本文因此只把官方资料明确描述的内容写成事实。

## 2. Agent 循环

**官方确认**：Claude Code 把一次任务概括为三个交织的阶段：收集上下文、采取行动、验证结果。模型使用工具读取文件、搜索代码、修改内容和运行测试；每次工具结果都会回到循环中，成为下一步决策的上下文。模型可以连续执行几十个动作，并根据新结果纠正方向。

```text
用户任务
   ↓
模型选择文本回复或工具
   ↓
权限判断与工具执行
   ↓
工具结果回灌会话
   ↓
模型继续判断
   ├─ 调用下一个工具
   └─ 生成最终答复
```

MewCode 001 阶段只实现这个循环的一个受限切片：第一阶段最多接受一个工具，执行后只允许一次最终答复请求。Claude Code 已经是自动循环，不存在这一章的“两次请求后强制停止”限制。

## 3. 六个核心工具的对应关系

| MewCode | Claude Code | 官方公开行为与主要差异 |
|---|---|---|
| `read_file` | `Read` | 读取文件；工作目录内默认无需确认，目录外需权限。Claude Code 还会跟踪是否完整读取，以决定能否编辑 |
| `write_file` | `Write` | 创建或覆盖文件，默认需要权限；MewCode 当前写文件不弹确认 |
| `edit_file` | `Edit` | 都使用精确原文替换并要求唯一匹配；Claude Code 还支持显式 `replace_all`，并包含 read-before-edit 检查 |
| `find_files` | `Glob` | 按模式查找文件，工作目录内默认无需确认 |
| `search_code` | `Grep` | 搜索文件内容并支持正则；工作目录内默认无需确认 |
| `execute_command` | `Bash` / `PowerShell` | 执行终端命令，默认需要权限；Claude Code 支持前台、后台任务和更完整的 Shell 环境管理 |

Claude Code 还公开了 Web、LSP、MCP、subagent、计划、任务清单、提问等工具。MewCode 当前的六工具集合是它最核心的文件、搜索和命令能力子集。

## 4. 工具定义、注册与模型选择

**官方确认**：Claude Code 为内置工具提供稳定名称和参数行为。这些名称同时用于权限规则、CLI 的 allowed/disallowed tools、hook matcher、skill 和 subagent 工具列表。自定义工具通过 MCP 接入；大量 MCP 工具可以先只暴露名称，再由 `ToolSearch` 按需加载定义。

**合理推断**：Claude Code 在发起模型请求前，把当前可用工具转换为模型 API 接受的名称、描述和参数 Schema；收到模型工具调用后，再按名称路由到对应执行器。这与 MewCode 的 `Tool` + `ToolRegistry` 边界相似。

**未公开**：Claude Code 是否存在单一 Tool 接口、注册中心使用何种容器、Schema 的内部类型，以及内置工具与 MCP 工具是否共用同一执行基类。

## 5. 流式工具调用与结果回灌

**官方确认**：工具执行结果会反馈给模型并驱动下一步；Claude Code 与 Agent SDK 支持文本和工具调用的实时流式输出。会话 JSONL 会保存消息、工具调用和工具结果。

**合理推断**：对于底层 Claude Messages API 的流式 tool use，客户端需要等参数内容完整并通过校验后才能安全执行工具。执行结果随后以模型可识别的 tool result 内容回灌。

**未公开**：Claude Code CLI 是否逐片拼接 `input_json_delta`、何时做 JSON 解析、无效片段如何恢复，以及内部统一事件模型。MewCode 已明确实现并测试参数碎片拼接，但不能据此反推 Claude Code 使用相同代码结构。

## 6. 编辑文件

**官方确认**：Claude Code 的 `Edit` 使用 `old_string` 和 `new_string` 做精确字符串替换，不使用正则或模糊匹配。默认情况下必须满足：

1. 文件已按规则被读取，且不是不完整的 partial view。
2. `old_string` 与当前文件内容精确匹配。
3. `old_string` 只出现一次；若要替换多处，必须显式设置 `replace_all`。

如果文件在读取后被外部修改，只要旧字符串仍能在当前内容中精确且唯一匹配，编辑仍可执行，结果会提示存在其他更改。匹配失败或不唯一时，Claude 会重新读取并尝试提供更多上下文。

MewCode 的 `edit_file` 同样坚持唯一精确匹配，但当前没有 read-before-edit 状态、`replace_all` 或外部并发修改提示。这说明唯一替换不是临时限制，而是一条值得保留的安全基线。

## 7. Shell 执行、超时与输出

**官方确认**：Claude Code 的 `Bash` 每次调用运行在独立进程中。主会话内的工作目录变更可以在允许目录范围内延续到后续命令，环境变量则不会自动延续。Shell 启动配置中的 alias、function 和 shell option 会在会话开始时被捕获并应用。

命令默认超时为两分钟，模型可以请求最长十分钟；管理员可通过环境变量调整默认值和上限。默认输出上限为 30,000 字符，超出后完整输出写入会话目录文件，并把文件路径和头部预览返回给模型。长任务可以转为后台任务，模型随后读取输出文件或通过任务接口管理它。

MewCode 当前始终从固定项目根目录执行，捕获有界 stdout/stderr，超时后终止进程组，不保留完整溢出输出，也没有后台任务。Claude Code 的“截断预览 + 完整结果落盘”值得在未来长命令支持中借鉴。

## 8. 权限与安全边界

**官方确认**：Claude Code 的默认模式允许项目内 `Read`、`Grep` 和 `Glob`，而 `Edit`、`Write`、`Bash` 通常需要确认。权限系统还提供：

- `default`、`acceptEdits`、`plan`、`auto`、`dontAsk` 和 `bypassPermissions` 等模式。
- 按工具与参数匹配的 allow、ask 和 deny 规则。
- 用户、项目、组织和托管策略等不同配置层级。
- protected paths，避免仓库状态和 Claude 自身配置被意外修改。
- 可选 Bash sandbox，对文件系统和网络做操作系统级隔离。
- hooks，在工具调用前后执行校验、阻止或自动化动作。
- 文件 checkpoint，在修改前保存内容以支持 rewind。

MewCode 当前只对 `execute_command` 逐次确认；文件工具依赖项目根目录边界、符号链接检查和原子写入，没有权限模式、规则、sandbox 或 checkpoint。特别要注意，两者都不能把“用户批准 Shell 命令”视为沙箱：没有 OS 级隔离时，子进程仍可能访问项目外资源。

## 9. 错误处理与自动修正

**官方确认**：Claude Code 会把工具结果返回给模型，模型据此继续搜索、重读、扩大精确匹配上下文或改用其他工具。`Edit` 对未读取、匹配不到和多重匹配有明确拒绝路径；`Bash` 对超时、后台化和输出溢出有明确结果提示。

**合理推断**：工具失败在 Agent 循环中被表示为模型可读的结果，而不是让整个终端进程因普通工具错误而崩溃。

**未公开**：所有内置工具是否共享统一的 `{ok, error_code, message, data}` 结果结构，以及异常分类、重试次数和 traceback 脱敏的内部实现。MewCode 的结构化 `ToolResult` 是本项目自己的明确契约。

## 10. 会话与副作用恢复

**官方确认**：Claude Code 会把消息、工具调用和结果持续写入本地 JSONL；文件修改前会建立 checkpoint。rewind 可以恢复文件或对话，但远程 API、数据库、部署等外部副作用无法 checkpoint，因此这类动作仍需要更谨慎的权限控制。

MewCode 当前采用“整轮成功后一次性提交模型历史”的会话事务，但工具已经产生的文件或命令副作用不会回滚。未来增加 Agent Loop 时，可以借鉴 Claude Code，把“对话持久化”“文件 checkpoint”“不可逆外部副作用权限”拆成三个独立机制。

## 11. 关键差异

| 主题 | Claude Code | MewCode 001 |
|---|---|---|
| 循环深度 | 可连续调用并验证，支持几十步 | 每回合最多一个工具 |
| 工具范围 | 文件、搜索、Shell、Web、LSP、MCP、subagent 等 | 六个本地核心工具 |
| 权限 | 多模式、细粒度规则、策略层级、sandbox | Shell 逐次确认 |
| 编辑 | 精确唯一匹配、read-before-edit、可 replace all | 精确唯一匹配 |
| 命令 | 前后台任务、输出落盘、cwd 延续 | 固定 cwd、有界捕获、超时终止 |
| 历史 | JSONL 持久化，工具过程可恢复 | 成功整轮保存在内存 |
| 文件恢复 | checkpoint 与 rewind | 原子写入，无撤销 |
| 扩展 | MCP、skills、hooks、subagents | 固定注册中心 |

## 12. 对下一阶段的直接启示

MewCode 增加 Agent Loop 时，最值得优先复用和补强的是：

1. 保留统一工具结果，让失败自然回到模型，而不是在 Session 中写工具特例。
2. 把“最大迭代次数、用户取消、连续工具调用和最终答复”做成清晰状态机。
3. 给每轮循环设置 token、时间和工具次数预算，避免无限自循环。
4. 在允许连续编辑前增加 checkpoint 或最小可恢复快照。
5. 将权限判断从 `execute_command` 特例提升为所有工具共用的策略层。
6. 对大输出采用有界预览，并保留可按需读取的完整结果。

## 13. 官方资料

- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Tools reference](https://code.claude.com/docs/en/tools-reference)
- [Choose a permission mode](https://code.claude.com/docs/en/permission-modes)
- [Configure permissions](https://code.claude.com/docs/en/permissions)
- [Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing)
- [Stream responses in real-time](https://code.claude.com/docs/en/agent-sdk/streaming-output)

这些资料足以确认 Claude Code 的产品契约，但不足以确认其私有源码结构。后续文档应继续沿用“官方确认 / 合理推断 / 未公开”的标记。
