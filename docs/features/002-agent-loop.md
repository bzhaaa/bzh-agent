# MewCode Agent Loop 功能总结

Claude Code 对应能力的公开实现对照见 [002-claude-code-agent-loop.md](002-claude-code-agent-loop.md)。

## 本章目标

本章把上一阶段“一次工具后停止”的流程升级为自主 Agent Loop。用户只需提交一次任务，MewCode 会重复请求模型、执行工具、回灌结果并调整下一步，直到模型给出最终答复或命中明确停止条件。

对应实现提交：`4a45103 feat: 添加 Agent Loop 与 Plan Mode`。

## 用户可见行为

- 模型可以连续完成多个工具迭代，不再需要用户逐步输入“继续”。
- thinking 和普通文本仍按流实时显示；工具前说明文字不会误判为最终答复。
- 同一次模型响应可以包含多个工具调用。
- 相邻读工具并发执行，写文件、改文件和命令严格串行执行。
- 底部状态显示 Normal/Plan、当前迭代、工具进度和 Token 用量。
- 运行期间仍可滚动历史和编辑草稿，普通 Enter 不会启动第二个并发请求。
- `Ctrl+C` 可以取消模型流、工具批次、命令确认或运行中的命令，随后会话仍可继续。

## 循环与停止条件

每次 Provider 请求计为一次迭代，默认上限为 10。完整工具批次执行后立即提交历史检查点，再决定是否进入下一次请求。

| 停止原因 | 行为 |
|---|---|
| 模型完成 | 收到非空最终文字，提交答复并正常结束 |
| 迭代上限 | 第 10 批工具仍会执行并提交，但不会发起第 11 次请求 |
| 连续未知工具 | 连续两轮只请求未知工具时停止；任一有效工具会清零计数 |
| 用户取消 | 中止当前阶段，回收异步任务和命令进程组 |
| Provider 错误 | 显示脱敏错误，保留此前完整检查点 |
| 无效流 | 拒绝缺少结束、冲突事件、残缺调用或无效参数，不执行不完整工具 |

每次 Agent Run 只产生一个最终停止事件，停止后不会再出现工具、进度或新请求事件。

## 多工具调度

六个工具新增显式执行策略：

| 策略 | 工具 | 调度方式 |
|---|---|---|
| `parallel_read` | `read_file`、`find_files`、`search_code` | 相邻调用组成并发段 |
| `serial_side_effect` | `write_file`、`edit_file`、`execute_command` | 每个调用独占一个串行段 |

例如“读 A、读 B、写 C、读 D、搜 E、改 F”会形成四段：并发 A/B、串行 C、并发 D/E、串行 F。并发任务即使逆序完成，工具结果仍按模型原始调用顺序回灌。

普通工具错误只影响自身。取消发生时保留已完成结果，当前未完成及后续未启动调用补成结构化 `cancelled` 结果，因此历史中不会出现只有工具请求、没有对应结果的半个检查点。

## Plan Mode

- `/plan <任务>`：立即进入 Plan，启动只读调查循环。
- Plan 中只向模型暴露 `read_file`、`find_files`、`search_code`。
- Plan 完成后仍保持只读；普通补充消息会继续更新计划。
- `/do`：仅在最近一次规划成功后可用，切回 Normal 并恢复全部六个工具。
- 新规划会清除旧计划状态；空 `/plan`、无计划 `/do` 均在本地拒绝，不请求模型。

## 架构

```text
MewCodeApp
    │ 用户输入、/plan、/do、取消
    ▼
ChatSession
    │ 历史、模式、计划就绪状态
    ▼
AgentRunner
    ├─ StreamCollector ── ProviderEvent ── OpenAI / Anthropic
    ├─ ToolScheduler ──── ToolExecutor ─── 六个工具
    └─ HistorySink ────── 完整工具检查点
    │
    ▼
AgentEvent ── thinking、文本、工具、用量、进度、停止
```

- `src/mewcode/agent/events.py` 定义供应商无关的 Agent 事件、模式、进度和停止原因。
- `src/mewcode/agent/control.py` 提供幂等的显式取消信号和异步竞争清理。
- `src/mewcode/agent/collector.py` 一路实时转发增量，一路收集并校验完整响应。
- `src/mewcode/agent/scheduler.py` 实现分段、并发、顺序恢复和取消补齐。
- `src/mewcode/agent/runner.py` 实现 ReAct 循环、停止条件、Token 累计和检查点。
- `src/mewcode/session.py` 只管理历史、Plan/Do 状态及活动 Run，不再包含循环细节。
- `src/mewcode/tui.py` 只消费 `AgentEvent`，不解析 Provider 协议或决定循环。

Provider 层使用 `ProviderEvent`，界面层使用 `AgentEvent`，两者不再共用旧 `StreamEvent`。这让 Agent 可以在没有 TUI 的情况下独立运行和测试。

## 历史、Provider 与 Token

工具迭代以“助手工具请求 + 全部工具结果”为原子检查点。模型流在完成前被取消或损坏时，当前部分响应不写入历史；工具阶段取消则提交补齐后的合法检查点。thinking 只用于展示，不进入后续模型历史。

OpenAI 会重放 assistant `tool_calls` 与逐个 tool 消息；Anthropic 会重放 `tool_use` 和合并后的 `tool_result` 内容块。两种 Provider 都支持同批多调用和流式 JSON 参数拼接。

Token 用量按请求和整轮累计。OpenAI 读取 prompt/completion usage；Anthropic 还把 cache creation 与 cache read 计入输入用量。供应商没有返回的字段显示为“未知”，不会伪装成 0 或本地估算值。

## 配置与兼容性

YAML 配置没有新增字段，仍为 `name`、`protocol`、`model`、`base_url`、`api_key` 和可选 `thinking`。默认最大迭代次数由代码提供，测试或嵌入调用可以注入更小上限，不写入配置文件。

上一章的目录边界、唯一替换、原子写入、输出截断、逐命令确认和进程组终止规则全部保留。

## 自动化验证

最终回归实际输出：

```text
uv run pytest -q
122 passed in 12.62s

uv run ruff check .
All checks passed!

uv run ruff format --check .
45 files already formatted
```

`uv run python -m compileall -q src tests` 与 `git diff --check` 也以状态码 0 完成。自动化覆盖流式双路收集、全部停止原因、读并发与副作用串行、取消补齐、历史检查点、双协议重放、Plan/Do、TUI 状态和六工具安全回归。

## tmux 端到端验收

验收日期为 2026-07-25。测试使用本地构建的 tmux 3.5a，在独立项目 `/tmp/mew-agent-loop-e2e-20260725/project` 中启动真实 Textual TUI，并通过官方 OpenAI/Anthropic SDK 连接确定性的本地 SSE 服务。

实际请求日志 `/tmp/mew-agent-loop-e2e-20260725/requests.jsonl` 共 48 条：OpenAI 36 条、Anthropic 12 条。完成的场景包括：

- 两种 Provider 都用一次自然语言请求完成三批工具和最终答复。
- Plan 连续三次请求均只收到三个只读工具，`/do` 后恢复六工具并写入计划产物。
- 混合任务按“并发读、串行写、并发读、串行改”执行。
- 命令批准和拒绝都将结果回灌；仅批准命令产生标记文件。
- 模型流、并发读组、命令确认和含子进程的长命令均可取消。
- 连续未知工具精确请求 2 次；迭代上限请求 step 精确为 0-9；OpenAI 与 Anthropic 无效流均安全停止。
- 长模型流取消后可继续对话；静态 transcript 保留有界、脱敏的过程摘要。

磁盘证据：

```text
agent-loop.txt  1df8fe3523ea3ea8e28e30c9a9a11e7414fcebba4920766ca49fb07f15e6ac78
plan-result.txt 6dc4795b077bcab76cf584d052d4eb82a96d651e7f27bed3b693ce17c60ad444
generated.txt   f2c82decdd7181cf98945929a62598db7e6b477e11f6e0eb0ae97020eff151ad

approved-marker=present
rejected-marker=absent
confirmation-cancelled-marker=absent
```

长命令取消前记录的父 PID 31958、子 PID 31959 在取消后均不存在。tmux 实测还发现“已有部分文本时无效流原因没有进入 transcript”的问题；修复后界面会同时保留部分文本和“模型返回了无效的流式响应”，并已加入回归测试。

逐项证据见项目根目录的 `checklist.md`。

## 当前限制

- 上下文只保存在当前进程内，没有会话持久化、自动压缩或恢复。
- 没有通用权限系统；仍只有 Shell 命令逐次确认。
- 没有文件 checkpoint、diff 审批或撤销。
- 不支持 MCP、subagent、后台任务、Web 或 LSP 工具。
- 迭代上限按请求次数控制，尚无总 Token、总时间或总费用预算。
- Plan Mode 是严格三读工具子集，不运行任何探索命令。

下一阶段可以在稳定的 AgentEvent、检查点和调度边界上增加权限、上下文压缩或持久化，而无需把这些职责塞回 TUI。
