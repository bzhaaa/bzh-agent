# MewCode Agent Loop Plan

## 架构概览

采用独立 `AgentRunner` 方案。现有 Provider 和工具执行层继续负责协议与单工具行为，在它们之上增加流式收集、工具调度和循环控制三层。

```text
CLI 组装
 ├─ Provider
 ├─ ToolRegistry / ToolExecutor
 ├─ ToolScheduler
 ├─ AgentRunner
 ├─ ChatSession
 └─ MewCodeApp
        │
        │ 用户输入、/plan、/do、取消
        ▼
   ChatSession
    ├─ 保存历史与 Plan Mode 状态
    ├─ 解析会话命令
    ├─ 提供本轮历史检查点提交入口
    └─ 创建 AgentRunRequest
              │
              ▼
         AgentRunner
          ├─ 控制 1..10 次迭代
          ├─ 判断正常完成与停止条件
          ├─ 维护本轮未知工具计数和 Token 累计
          └─ 产生 AgentEvent
              │
      ┌───────┴────────┐
      ▼                ▼
StreamCollector    ToolScheduler
 ├─ 消费 Provider 流  ├─ 按原顺序划分执行段
 ├─ 实时转发增量      ├─ 读工具段并发
 ├─ 收集完整响应      ├─ 副作用工具串行
 └─ 验证正常结束      └─ 保持结果原始顺序
      │                │
      └───────┬────────┘
              ▼
        下一次模型请求
```

各层职责：

1. **Provider 事件层。** OpenAI 与 Anthropic 继续解析各自流协议，但只产生供应商无关的底层事件，包括 thinking、文本、完整工具调用、Token 用量和正常结束。
2. **StreamCollector。** 每次模型请求创建一个收集器。它把 thinking 和文本立即转换为 Agent 事件，同时收集完整文本、工具调用和 Token 用量；只有看到合法结束事件后才提供完整响应。
3. **ToolScheduler。** 根据当前模式可用的工具集合执行一批调用。它只依赖工具注册中心、执行器和工具安全分类，不依赖 Provider、Session 或 TUI。
4. **AgentRunner。** 实现 ReAct 状态机。它使用收集器请求模型，使用调度器执行工具，通过历史提交接口保存完整检查点，并把所有过程转换为统一 Agent 事件。
5. **ChatSession。** 从现有“两次请求状态机”收缩为会话外观层，负责内存历史、Plan Mode 状态、`/plan`/`/do` 解析和检查点提交，不再包含工具循环细节。
6. **MewCodeApp。** 只消费 Agent 事件并更新 transcript、工具记录、模式标识和进度，不再根据工具数量或 Provider 异常决定是否继续。

取消改为显式的本轮取消控制，而不是直接把 TUI Worker 当成业务取消机制：

1. `Ctrl+C` 通知当前 Agent Run 取消。
2. 收集器取消正在等待的 Provider 流。
3. 调度器取消并回收所有未完成工具任务。
4. 命令工具继续执行既有进程组终止逻辑。
5. AgentRunner 产生 `cancelled` 停止事件后结束。
6. 应用退出等强制取消路径仍保留底层任务取消作为兜底清理。

历史通过 ChatSession 提供的检查点提交入口逐步保存。AgentRunner 不直接持有 UI，也不依赖历史具体存储方式，后续可以把内存历史替换为持久化实现。

## 核心数据结构

### ProviderEvent

现有 `StreamEvent` 拆成仅供 Provider 与收集器通信的 `ProviderEvent`，避免 TUI 直接消费协议层事件。

```python
class ProviderEventKind(StrEnum):
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOKEN_USAGE = "token_usage"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    kind: ProviderEventKind
    delta: str = ""
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
```

Provider 在正常流结束前最多产生一次归一化 Token 用量。未提供用量时不伪造事件，由收集器补成未知值。

### TokenUsage

```python
@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None

    @property
    def total_tokens(self) -> int | None: ...

    def accumulate(self, other: TokenUsage) -> TokenUsage: ...
```

任一累计项曾经未知，则该累计项保持未知。只有输入和输出都已知时才计算总 Token。

### AgentEvent

```python
class AgentMode(StrEnum):
    NORMAL = "normal"
    PLAN = "plan"


class AgentEventKind(StrEnum):
    MODE_CHANGED = "mode_changed"
    ITERATION_STARTED = "iteration_started"
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOKEN_USAGE = "token_usage"
    PROGRESS = "progress"
    STOPPED = "stopped"


class AgentStopReason(StrEnum):
    COMPLETED = "completed"
    ITERATION_LIMIT = "iteration_limit"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    INVALID_STREAM = "invalid_stream"
    NO_PLAN = "no_plan"
    INVALID_COMMAND = "invalid_command"
```

```python
@dataclass(frozen=True, slots=True)
class AgentProgress:
    phase: Literal[
        "requesting_model",
        "executing_tools",
        "checkpoint_committed",
    ]
    iteration: int
    completed_tools: int = 0
    total_tools: int = 0


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    request: TokenUsage
    cumulative: TokenUsage


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: AgentEventKind
    iteration: int = 0
    mode: AgentMode = AgentMode.NORMAL
    delta: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    usage: UsageSnapshot | None = None
    progress: AgentProgress | None = None
    stop_reason: AgentStopReason | None = None
```

每次运行恰好产生一个最终 `STOPPED` 事件。Provider 错误和无效流先在 Agent 层转换为脱敏停止事件，TUI 不再捕获 Provider 异常来决定业务状态。

### CollectedResponse 与 StreamCollector

```python
@dataclass(frozen=True, slots=True)
class CollectedResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage


class StreamCollector:
    def __init__(
        self,
        *,
        iteration: int,
        mode: AgentMode,
        control: AgentRunControl,
    ) -> None: ...

    async def consume(
        self,
        source: AsyncIterator[ProviderEvent],
    ) -> AsyncIterator[AgentEvent]: ...

    @property
    def response(self) -> CollectedResponse: ...
```

`consume()` 实时转发 thinking 和文本事件，同时收集完整响应。只有消费到唯一合法的 `DONE` 后才能读取 `response`；提前结束、重复结束或字段冲突均产生无效流错误。

### 工具执行策略与 ToolScheduler

```python
class ToolExecutionPolicy(StrEnum):
    PARALLEL_READ = "parallel_read"
    SERIAL_SIDE_EFFECT = "serial_side_effect"
```

工具策略固定为：

- `read_file`、`find_files`、`search_code`：`PARALLEL_READ`
- `write_file`、`edit_file`、`execute_command`：`SERIAL_SIDE_EFFECT`

```python
@dataclass(frozen=True, slots=True)
class ToolSegmentResult:
    calls: tuple[ToolCall, ...]
    results: tuple[ToolResult, ...]


class ToolScheduler:
    async def execute(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
        control: AgentRunControl,
    ) -> AsyncIterator[ToolSegmentResult]: ...
```

调度器逐段产生结果：并发读段全部结束后按原顺序返回，副作用段每次只含一个调用。Plan Mode 使用只包含三个读工具的注册中心视图，因此未开放工具会得到 `UNKNOWN_TOOL`，不会绕过模式边界执行。

### AgentRunControl

```python
class AgentRunControl:
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    async def wait_cancelled(self) -> None: ...
```

收集器和调度器同时等待当前工作与取消信号。取消发生时主动取消底层 Provider 读取或工具任务，完成清理后由 AgentRunner 产生停止事件。

### AgentRunner 与历史提交

```python
class HistorySink(Protocol):
    async def commit(
        self,
        messages: Sequence[ChatMessage],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    history: tuple[ChatMessage, ...]
    user_message: UserMessage
    mode: AgentMode
    max_iterations: int
    control: AgentRunControl
    history_sink: HistorySink


class AgentRunner:
    async def run(
        self,
        request: AgentRunRequest,
    ) -> AsyncIterator[AgentEvent]: ...
```

Runner 只接收历史快照、规范化用户消息、当前模式、取消控制和历史提交接口。它不持有 TUI 或 ChatSession。

### ChatSession

```python
class ChatSession:
    @property
    def history(self) -> tuple[ChatMessage, ...]: ...

    @property
    def mode(self) -> AgentMode: ...

    async def stream_reply(
        self,
        user_input: str,
    ) -> AsyncIterator[AgentEvent]: ...

    def cancel_current(self) -> None: ...
```

ChatSession 保存当前模式、可执行计划状态、当前运行的取消控制和内存历史。`/plan <任务>`、Plan 模式后续消息和 `/do` 被转换成明确的模型指令文本；TUI transcript 仍展示用户原始输入。

## 模块设计

### AgentRunner 循环

每次 `run()`：

1. 初始化迭代计数、连续未知工具计数和累计 Token。
2. 将历史快照与尚未提交的本轮用户消息组成请求上下文。
3. 产生迭代开始和请求进度事件。
4. 通过 Provider 与 StreamCollector 消费一次完整模型流。
5. 产生本次及累计 Token 用量事件。
6. 响应不含工具时，验证文字非空，提交用户消息和最终助手消息，产生 `STOPPED(COMPLETED)`。
7. 响应包含工具时，先产生调用事件，再由当前模式的 ToolScheduler 执行。
8. 收集全部结果并按调用顺序产生结果事件。
9. 提交用户消息、助手工具请求和全部工具结果。
10. 更新连续未知工具计数。
11. 连续两次均只包含未知工具时停止。
12. 第 10 次工具迭代完成后停止，不发起第 11 次请求。
13. 其他情况使用已提交历史进入下一次迭代。

Provider 错误和无效流由 Runner 转换成脱敏停止事件。普通工具失败不会停止循环。

### 历史检查点

一次工具检查点固定为：

```text
首次工具迭代：
UserMessage
AssistantMessage(text + tool_calls)
ToolResultMessage × N

后续工具迭代：
AssistantMessage(text + tool_calls)
ToolResultMessage × N
```

最终文字检查点为：

```text
首次直接回答：
UserMessage
AssistantMessage(final_text)

工具循环后的最终回答：
AssistantMessage(final_text)
```

工具批次必须获得每个调用的结果后才提交。

取消处理：

- 模型流中取消：当前响应不完整，直接丢弃，保留更早检查点。
- 工具执行中取消：保留已完成结果，为正在执行或尚未启动的调用生成 `CANCELLED` 结果，提交合法完整工具检查点后停止。
- 命令执行中取消：先终止进程组，再生成取消结果。
- 应用退出等强制任务取消：完成资源清理后继续向上传播。

### ToolScheduler 分段

注册中心增加只读子集能力：

```python
class ToolRegistry:
    def subset(self, names: Collection[str]) -> ToolRegistry: ...
```

CLI 从同一默认注册中心创建 Normal 六工具环境和 Plan 三个读工具环境。

分段算法按调用顺序单次扫描：

```text
连续 PARALLEL_READ → 一个并发段
SERIAL_SIDE_EFFECT → 一个单调用串行段
未知工具 → 一个立即失败的串行边界
```

```text
read A ─┐
read B ─┴─ 并发 → write C → read D ─┐
                              grep E ─┴─ 并发 → edit F
```

并发段使用 `asyncio` 任务组。普通工具失败被收集为结果，不取消同组任务；外部取消则取消整个任务组。每段输出和最终批次结果都恢复为原调用顺序。

Plan Mode 中未开放的工具由只读注册中心视为未知工具，因此不会执行。

### StreamCollector

收集器维护文本片段、完整工具调用、本次 Token 用量和结束状态：

- thinking/text：立即转发，文本同时加入缓冲。
- tool call：保存完整调用并转发，但在 `DONE` 前不得执行。
- usage：只接受一次并保存。
- done：验证唯一性并关闭收集。
- 提前结束、重复 done、缺少调用字段或结束原因冲突：拒绝生成完整响应。

取消控制与 Provider 下一事件并行等待；取消优先时关闭异步流并回收等待任务。

### Token 用量归一化

OpenAI 请求启用流式 usage 返回：

- `prompt_tokens` → 输入 Token。
- `completion_tokens` → 输出 Token。

Anthropic 从开始和结束事件收集：

- 普通输入、cache creation 和 cache read Token 合并为输入 Token。
- `output_tokens` → 输出 Token。

Provider 没有返回 usage 时，收集器生成未知用量。累计过程中任何缺失项都会使对应累计项保持未知。

### ChatSession 与 Plan Mode

ChatSession 解析：

- `/plan <任务>`：切换到 Plan，清除旧计划就绪状态，以只读规划指令包装任务后启动 Runner。
- Plan Mode 中普通消息：保持 Plan，以“继续调查并更新计划”的指令包装补充内容。
- `/do`：存在成功计划时切回 Normal、消费计划状态，并以“根据已完成计划开始执行”的指令启动 Runner。

精确的空 `/plan` 和无计划 `/do` 不调用 Provider，只产生本地停止事件。`/do` 开始后保持 Normal，执行失败或取消不会自动回到 Plan。

规划指令只写入模型历史，TUI transcript 显示用户原文。Plan Mode 中一次正常文字完成会把计划就绪状态设为真；失败或取消不会把未完成内容标记为计划。

### TUI 消费

- 每次迭代首次收到 thinking 或文本时创建该迭代的助手记录。
- 工具调用按事件顺序追加在对应助手文本之后。
- 工具结果通过调用 ID 更新对应记录。
- 下一迭代创建新的助手记录，保持“说明 → 工具 → 新说明”的视觉顺序。
- 模式、迭代、工具进度和累计 Token 显示在底部状态行。
- `STOPPED` 决定最后记录是完成、取消还是错误，并按需追加状态消息。
- `Ctrl+C` 先关闭命令确认框，再调用 `ChatSession.cancel_current()`，不直接取消正常业务 Worker。

## 模块交互

### 普通循环时序

```text
TUI              ChatSession        AgentRunner       Collector/Provider      Scheduler
 │ submit(text)       │                  │                    │                   │
 │───────────────────>│ create request   │                    │                   │
 │                    │─────────────────>│ iteration 1        │                   │
 │<──────────────────────────────────────│ ITERATION_STARTED  │                   │
 │                    │                  │──── stream ────────>│                   │
 │<──────────────────────────────────────── text/thinking ───│                   │
 │<──────────────────────────────────────── TOOL_CALL ───────│                   │
 │<──────────────────────────────────────│ TOKEN_USAGE        │                   │
 │                    │                  │───────────────────────────────────────>│
 │<──────────────────────────────────────────────────── TOOL_RESULT / PROGRESS ─│
 │                    │<─────────────────│ commit checkpoint  │                   │
 │<──────────────────────────────────────│ CHECKPOINT_COMMITTED                  │
 │                    │                  │ iteration 2        │                   │
 │                    │                  │──── stream ────────>│                   │
 │<──────────────────────────────────────── final text ──────│                   │
 │                    │<─────────────────│ commit final       │                   │
 │<──────────────────────────────────────│ STOPPED(COMPLETED) │                   │
```

单次工具迭代事件顺序：

```text
ITERATION_STARTED
PROGRESS(requesting_model)
THINKING_DELTA / TEXT_DELTA
TOOL_CALL
TOKEN_USAGE
PROGRESS(executing_tools)
TOOL_RESULT
PROGRESS(checkpoint_committed)
```

最终文字迭代不产生工具事件，提交最终助手消息后产生 `STOPPED(COMPLETED)`。

### Plan Mode 时序

```text
/plan 任务
  → MODE_CHANGED(PLAN)
  → 只读 Agent Loop
  → STOPPED(COMPLETED)，plan_ready = true
  → 普通补充仍在 Plan 中更新计划
  → /do
  → MODE_CHANGED(NORMAL)，消费 plan_ready
  → 全工具 Agent Loop
  → STOPPED(...)
```

新的 `/plan <任务>` 覆盖待执行计划状态，但不删除已有历史。无计划 `/do` 和空 `/plan` 只产生本地状态，不创建模型消息或 Token 用量。

### 停止状态机

| 停止原因 | 触发点 | 当前内容处理 | 历史处理 | 后续请求 |
|---|---|---|---|---|
| `COMPLETED` | 完整响应不含工具且文本非空 | 展示最终文字 | 提交最终消息 | 不再请求 |
| `ITERATION_LIMIT` | 第 10 次工具批次完成 | 展示上限状态 | 提交第 10 次工具检查点 | 禁止第 11 次 |
| `UNKNOWN_TOOL_LIMIT` | 连续第二轮只含未知工具 | 展示停止状态 | 提交第二轮错误结果检查点 | 不再请求 |
| `CANCELLED` | 用户取消 | 清理当前流或工具任务 | 保留旧检查点；工具阶段补齐取消结果 | 不再请求 |
| `PROVIDER_ERROR` | 认证、限流、连接或服务错误 | 展示脱敏错误 | 丢弃未完成响应 | 不重试 |
| `INVALID_STREAM` | 流提前结束、冲突或残缺 | 展示流错误 | 丢弃未完成响应，工具不执行 | 不重试 |
| `NO_PLAN` | 无成功计划时输入 `/do` | 显示本地提示 | 不改变历史 | 不请求 |
| `INVALID_COMMAND` | `/plan` 缺少任务 | 显示本地提示 | 不改变历史 | 不请求 |

每个模型请求即使失败，也产生一次 Token 用量事件；Provider 未提供的字段标记为未知。停止事件始终位于本次运行事件流末尾。

### 未知工具计数

- 所有调用都不在当前注册中心：计数加一。
- 至少一个调用有效：计数清零。
- 未知调用分别获得 `UNKNOWN_TOOL` 结果。
- 有效调用照常执行。
- Plan Mode 中未开放工具按未知调用处理。
- 第二次纯未知调用的错误结果先进入历史，随后停止。

### 取消竞争

1. 已得到完整 Provider `DONE` 的响应按完整响应处理。
2. 已返回 `ToolResult` 的工具保留实际结果。
3. 尚未返回结果的工具标记为 `CANCELLED`。
4. 尚未启动的后续执行段不启动并生成取消结果。
5. 取消后不启动新 Provider 请求。
6. 每次运行只产生一个 `STOPPED(CANCELLED)`。

外层任务被应用强制取消时优先完成资源清理；消费者已经终止时不保证投递最终事件。

## 文件组织

```text
src/mewcode/
├── agent/
│   ├── __init__.py      # Agent 公共入口
│   ├── control.py       # 显式取消信号
│   ├── events.py        # Agent 事件、模式、进度和停止原因
│   ├── collector.py     # Provider 流双路收集
│   ├── scheduler.py     # 工具分段与并发调度
│   └── runner.py        # ReAct 循环状态机
├── models.py            # 会话消息、ProviderEvent、TokenUsage
├── session.py           # 历史、Plan Mode 和命令解析
├── cli.py               # 运行环境组装
├── tui.py               # AgentEvent 展示
├── providers/
│   ├── base.py
│   ├── openai.py
│   └── anthropic.py
└── tools/
    ├── base.py
    ├── registry.py
    ├── read_file.py
    ├── find_files.py
    ├── search_code.py
    ├── write_file.py
    ├── edit_file.py
    └── execute_command.py
```

模块依赖：

```text
events/control
      ↑
collector   tools
      ↑       ↑
      runner ← scheduler
         ↑
       session
         ↑
         tui
```

### 自动化测试

```text
tests/agent/
├── test_collector.py
├── test_scheduler.py
└── test_runner.py

tests/test_session.py
tests/test_tui.py
tests/test_cli.py
tests/tools/test_executor.py
tests/providers/test_openai.py
tests/providers/test_anthropic.py
tests/e2e/mock_llm_server.py
```

- collector：双路转发、完整收集、无效流、取消。
- scheduler：分段、并发时序、结果顺序、普通失败、取消补齐。
- runner：循环、停止条件、Token 累计、检查点。
- session：Plan Mode 命令和历史状态。
- TUI：多迭代显示、模式状态、进度、取消和确认。
- Provider：多工具流和 Token usage。
- E2E：确定性多步任务、Plan/Do、并发与停止场景。

### 验收与总结文档

```text
spec.md
plan.md
task.md
checklist.md
docs/features/002-agent-loop.md
docs/features/002-claude-code-agent-loop.md
docs/features/README.md
```

`checklist.md` 在开发前生成，验收时记录实际结果。两份 002 文档只在功能验收完成后填写测试证据。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 循环归属 | 独立 `AgentRunner` | 避免 ChatSession 同时承担历史、循环、并发和 UI 状态 |
| 事件边界 | ProviderEvent 与 AgentEvent 分离 | Provider 只表达模型流，TUI 只理解完整 Agent 行为 |
| 事件传输 | 异步生成器，不增加 Queue | 天然支持背压和异常传播，无需 Actor 生命周期 |
| 流收集 | 每次请求一个有状态 Collector | 实时转发与完整响应收集共存 |
| 取消 | 显式取消控制，任务取消兜底 | 能投递停止事件并统一取消 Provider 与工具 |
| 工具安全性 | 工具声明固定执行策略 | 不根据模型参数猜测副作用 |
| 多工具调度 | 连续读段并发，副作用串行 | 保留模型顺序并获得安全并发 |
| 并发实现 | `asyncio` 任务组并跟踪任务结果 | 取消时可回收并补齐取消结果 |
| 结果顺序 | 始终等于调用顺序 | 保证双 Provider 历史确定 |
| 历史粒度 | 完整工具批次为检查点 | 每个助手工具调用都有对应结果 |
| 迭代上限 | 默认 10，内部可注入 | 满足安全兜底，不改 YAML |
| 未知工具 | 连续两轮纯未知后停止 | 允许一次自我纠正，避免无效循环 |
| Plan 边界 | 独立只读注册中心视图 | 未开放工具无法调度 |
| Plan 指令 | 包装为模型可见用户指令 | 不扩展两种 Provider 的 system message 契约 |
| `/do` | 消费最近成功计划并切回 Normal | 防止重复执行，模式明确 |
| Token 累计 | 缺失值向累计传播 | 不把部分统计伪装成准确总量 |
| 错误处理 | 可预期停止转换为事件 | TUI 不承担循环决策 |
| Provider 重试 | 不自动重试 | 避免重复副作用并遵守 Spec |
| TUI 记录 | 每次模型迭代独立记录 | 保持文本、工具和调整的真实顺序 |
| 文档证据 | 自动化 + tmux 后填写 002 | 只记录实际验收结果 |

## 关键权衡

- 慢事件消费者会降低 Provider 流读取速度，但避免无界事件缓冲。
- Plan 指令进入模型历史会使模型看到的文本与 TUI 原始命令不同，但保持协议简单。
- 工具执行中取消会补齐取消结果，因此历史比整批丢弃更完整；副作用仍不回滚。
- 只读注册中心是模式能力范围，不扩展成通用权限系统。
- 兼容端点不返回 usage 时显示未知，不做 tokenizer 估算。

## Spec 覆盖

| Spec 范围 | 设计归属 |
|---|---|
| F1-F6：循环与停止 | AgentRunner、AgentRunControl、停止状态机 |
| F7-F9：事件与双路收集 | ProviderEvent、AgentEvent、StreamCollector |
| F10-F13：多工具与确认 | ToolExecutionPolicy、ToolScheduler、ToolExecutor |
| F14-F18：Plan Mode | ChatSession、只读注册中心、模式事件 |
| F19：Token 用量 | 双 Provider、TokenUsage、AgentRunner 累计 |
| F20-F23：历史与快速路径 | HistorySink、检查点算法、AgentRunner |
| F24：双 Provider 一致性 | Provider 适配测试与共享领域场景 |
| N1-N16 | 单向依赖、有界异步执行、兼容测试、tmux 验收和双文档流程 |

技术设计没有未归属的 Spec 需求，模块依赖保持单向，Provider、调度器和 TUI 之间不存在循环依赖。
