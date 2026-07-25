# MewCode 工具系统 Plan

## 架构概览

保留现有 CLI、Textual TUI、ChatSession 和 Provider 分层，在它们之间加入供应商无关的工具领域层。注册中心只保存统一工具定义；OpenAI 与 Anthropic Provider 各自把定义和消息转换成原生 API 格式。

```text
CLI
 ├─ 固定 project_root = cwd.resolve()
 ├─ 创建六个 Tool → ToolRegistry → ToolExecutor
 ├─ 创建 Provider
 └─ 启动 MewCodeApp
          │
          │ stream_reply(user_input)
          ▼
      ChatSession
       ├─ 第一次 Provider.stream()
       │    ├─ 纯文本 → 完成并提交
       │    └─ ToolCall → 单调用校验
       │                    │
       │                    ▼
       │              ToolExecutor
       │               ├─ JSON/Schema 校验
       │               ├─ 命令确认回调 → TUI Modal
       │               ├─ 超时与取消
       │               └─ ToolResult
       │                    │
       └─ 回灌结果 → 第二次 Provider.stream()
                    ├─ 最终文本 → 整轮原子提交
                    └─ 再次 ToolCall → 限制状态，不执行、不提交
```

工具系统划分为四层：

1. **领域模型层。** 定义 `ToolDefinition`、`ToolCall`、`ToolResult`、结构化会话消息和统一流事件，不依赖 SDK、Textual 或具体工具。
2. **工具运行层。** `Tool` 接口描述单个工具；`ToolRegistry` 管理登记与查找；`ToolExecutor` 统一处理 JSON 解析、Pydantic Schema 校验、确认、超时、异常和结果序列化。
3. **协议适配层。** 两个 Provider 将统一工具定义、结构化历史和工具结果转换为各自 API 请求，并把流式工具调用碎片组装成统一 `ToolCall`。工具调用只有在流正常结束后才向上层产出。
4. **交互编排层。** `ChatSession` 负责“一次工具 + 一次最终答复”的事务状态机；TUI 只负责展示事件、弹出命令确认框和传回批准结果，不直接执行工具。

现有纯文本路径保持快速路径：模型没有请求工具时，只调用一次 Provider，行为与当前版本一致。

`ToolRegistry` 对外提供供应商无关的定义列表，真正的 OpenAI/Anthropic JSON 包装由各 Provider 完成，以同时满足注册中心集中管理和协议隔离要求。

## 核心数据结构

### ToolDefinition

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]
```

名称使用小写 snake_case。Schema 为 JSON Schema object，必须关闭未知字段；注册时验证名称、描述和 Schema 基本结构。

### ToolCall

```python
@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str
```

保存供应商给出的稳定调用 ID 和完整原始 JSON。Provider 只负责安全拼接，不在协议层执行工具或修正参数。

### ToolResult

```python
class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_JSON = "invalid_json"
    INVALID_ARGUMENTS = "invalid_arguments"
    PATH_OUTSIDE_ROOT = "path_outside_root"
    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_ENCODING = "invalid_encoding"
    NO_UNIQUE_MATCH = "no_unique_match"
    INVALID_PATTERN = "invalid_pattern"
    PERMISSION_DENIED = "permission_denied"
    USER_REJECTED = "user_rejected"
    MULTIPLE_TOOLS = "multiple_tools"
    TOOL_LIMIT_REACHED = "tool_limit_reached"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
```

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    success: bool
    content: dict[str, object]
    error_code: ToolErrorCode | None = None
    error_message: str | None = None
    truncated: bool = False

    def to_model_json(self) -> str: ...
```

`to_model_json()` 使用稳定键序列化，既供 Provider 回灌，也供 TUI 从同一结果生成摘要。错误正文统一限长，不含 traceback。

### ToolContext

```python
@dataclass(frozen=True, slots=True)
class ToolContext:
    project_root: Path
    approval_handler: ApprovalHandler
```

```python
@dataclass(frozen=True, slots=True)
class CommandApprovalRequest:
    command: str
    cwd: str
    timeout_seconds: float
```

```python
ApprovalHandler = Callable[
    [CommandApprovalRequest],
    Awaitable[bool],
]
```

执行器每次遇到需要确认的工具时调用一次 handler。测试可注入固定批准/拒绝函数；CLI 组装时使用一个可延迟绑定的 approval handler，`MewCodeApp` 启动后将其绑定到自身模态确认方法，工具层不依赖 Textual 类型。

### Tool 接口

```python
class Tool(Protocol):
    definition: ToolDefinition
    argument_model: type[BaseModel]
    requires_approval: bool

    async def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
    ) -> dict[str, object]: ...
```

工具实现只处理已校验参数和领域操作。未知工具、JSON/Schema 错误、批准、超时和异常转换由 `ToolExecutor` 负责。

### 结构化会话消息

将现有只有 `role + content` 的 `ChatMessage` 扩展为可表达工具轮次的供应商无关联合类型：

```python
@dataclass(frozen=True, slots=True)
class UserMessage:
    content: str

@dataclass(frozen=True, slots=True)
class AssistantMessage:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()

@dataclass(frozen=True, slots=True)
class ToolResultMessage:
    result: ToolResult

ChatMessage = UserMessage | AssistantMessage | ToolResultMessage
```

工具回合历史顺序固定为：

```text
UserMessage
AssistantMessage(tool_calls=(...))
ToolResultMessage
AssistantMessage(content=最终答复)
```

第一阶段工具调用前产生的普通文本若存在，保存在工具调用对应的 `AssistantMessage.content` 中；thinking 仍只用于 UI，不写入历史。元组既能表示正常的单调用，也能在多工具限制场景中完整重放所有被拒绝的调用。

### 统一流事件

```python
class StreamEventKind(StrEnum):
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    LIMIT_REACHED = "limit_reached"
    DONE = "done"
```

```python
@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: StreamEventKind
    delta: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
```

Provider 只产生 `THINKING_DELTA`、`TEXT_DELTA`、`TOOL_CALL` 和 `DONE`；`ChatSession` 在执行后补充 `TOOL_RESULT`，在第二次工具请求时补充 `LIMIT_REACHED`。

### TranscriptEntry 扩展

```python
TranscriptRole = Literal["user", "assistant", "tool", "status"]

@dataclass(slots=True)
class TranscriptEntry:
    role: TranscriptRole
    content: str = ""
    thinking: str = ""
    state: Literal[
        "streaming", "pending", "approved", "rejected",
        "complete", "cancelled", "error"
    ] = "complete"
    tool_name: str | None = None
```

UI 只保存有界摘要，不将完整命令输出复制进 transcript；完整且已截断到模型上限的结果保存在会话消息中。

## 模块设计

### 路径安全模块

职责：建立唯一的项目文件访问边界，供所有文件类工具复用。

```python
class ProjectPaths:
    def __init__(self, root: Path) -> None: ...
    def resolve_file(
        self,
        user_path: str,
        *,
        must_exist: bool,
    ) -> Path: ...
```

规则：

- 启动时将根目录解析为规范绝对路径。
- 工具参数统一使用相对项目根目录的路径。
- 拒绝空路径、项目外绝对路径和包含越界语义的路径。
- 对已有目标使用严格解析，检查最终路径是否仍在根目录内。
- 对待创建路径，解析最近的已有父目录，拒绝通过父目录符号链接越界。
- 不使用字符串前缀判断父子关系，而使用路径组成关系。
- 工具输出只返回相对路径，不暴露无关的本机绝对路径。

### 原子写入模块

职责：为写文件和改文件提供同目录原子替换。

```python
def atomic_write_text(path: Path, content: str) -> None: ...
```

流程：

1. 在目标目录创建临时文件。
2. 以 UTF-8 写入并刷新缓冲区。
3. 保留已有文件的权限位；新文件使用正常默认权限。
4. 使用原子替换提交。
5. 无论成功、失败或取消都清理未提交的临时文件。

该模块不提供备份和撤销。

### ToolRegistry

```python
class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None: ...
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def definitions(self) -> tuple[ToolDefinition, ...]: ...
```

职责：

- 验证并登记工具。
- 保持稳定的注册顺序。
- 拒绝重复名称。
- 暴露供应商无关的不可变工具定义。
- 不负责生成任何供应商原生 API 字典。

默认工厂创建并登记六个核心工具：

```python
def create_default_registry() -> ToolRegistry: ...
```

项目根目录只存在于 `ToolContext`，使同一组无状态工具定义可在不同临时项目中测试和复用。

### ToolExecutor

```python
class ToolExecutor:
    async def execute(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResult: ...
```

执行顺序：

1. 按名称查找工具。
2. 完整解析 `arguments_json`，根值必须是 object。
3. 使用工具的 Pydantic 参数模型校验，拒绝未知字段。
4. 将请求超时限制在工具允许的最大值内。
5. 若工具需要确认，构造本次确认请求并等待 handler。
6. 用户拒绝时直接返回 `USER_REJECTED`，不调用工具。
7. 在 `asyncio.timeout()` 中执行工具。
8. 将预期领域错误、超时和意外异常转换为统一结果。
9. 对模型结果 JSON 和用户可见摘要分别执行长度限制。

`CancelledError` 不转换为普通失败结果，而是在完成必要资源清理后继续向上传播，使 ChatSession 回滚本轮。

除命令工具使用参数中的超时外，文件与搜索工具使用执行器定义的固定超时。所有文件参数、单文件读取和搜索扫描均有字节上限；文件操作使用短小的同步临界区，搜索每处理一批文件主动让出事件循环。第一版不把不可中止的文件写入委派到后台线程，避免超时后遗留仍在修改文件的线程。

### ReadFileTool

参数：

```python
class ReadFileArguments(BaseModel):
    path: str
    start_line: int = 1
    line_count: int = 200
```

行为：

- 只读取普通 UTF-8 文本文件。
- 读取前检查文件大小上限，避免把无界文件载入内存。
- 行号从 1 开始。
- `line_count` 有最大值。
- 返回相对路径、实际行区间、带行号文本、总行数和截断状态。
- 空文件正常返回；起始行超过文件末尾属于无效范围。

### WriteFileTool

参数：

```python
class WriteFileArguments(BaseModel):
    path: str
    content: str
```

行为：

- 自动创建项目内父目录。
- `content` 有明确字节上限，超过时在写入前拒绝。
- 使用原子写入。
- 返回相对路径、操作类型 `created` 或 `overwritten`、写入字符数。
- 目标若为目录或越界符号链接则失败。

### EditFileTool

参数：

```python
class EditFileArguments(BaseModel):
    path: str
    old_text: str
    new_text: str
```

行为：

- `old_text` 不得为空。
- 目标文件及替换后内容均受文件字节上限约束。
- 读取完整 UTF-8 文本并统计非重叠匹配次数。
- 只有匹配次数恰好为 1 时执行一次替换并原子写回。
- 零次或多次匹配时返回 `NO_UNIQUE_MATCH`，并携带实际匹配次数，文件保持不变。
- 返回相对路径和替换前后字符数。

### ExecuteCommandTool

参数：

```python
class ExecuteCommandArguments(BaseModel):
    command: str
    timeout_seconds: float = 30
```

约束：

- `command` 非空，长度有限制。
- 超时下限 1 秒、默认 30 秒、最大 300 秒。
- 使用系统 Shell 执行完整命令，工作目录固定为项目根目录。
- 每次调用必须先经 `ApprovalHandler` 确认；确认内容与最终执行内容完全相同。
- 同时读取 stdout 和 stderr，分别限制字节数并标注截断。
- 正常退出和非零退出都属于“工具已成功执行”，`content` 中返回 `exit_code`；只有无法启动、超时等属于工具失败。
- 创建独立进程组。取消或超时时先终止整个进程组，等待短暂宽限期，仍未退出则强制杀死，随后回收进程。
- 第一版不解析或限制 Shell 命令内部访问的路径与网络。

返回示例：

```json
{
  "command": "uv run pytest -q",
  "cwd": ".",
  "exit_code": 0,
  "stdout": "48 passed ...",
  "stderr": "",
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

### FindFilesTool

参数：

```python
class FindFilesArguments(BaseModel):
    pattern: str
    max_results: int = 200
```

行为：

- pattern 使用相对根目录的 glob 语义，拒绝绝对和越界模式。
- 遍历时跳过 `.git`，并不递归进入符号链接目录。
- 只返回普通文件。
- 每个候选结果再次走规范路径边界校验。
- 返回相对 POSIX 路径，按字典序排序。
- 达到上限后停止并标注 `truncated`。

### SearchCodeTool

参数：

```python
class SearchCodeArguments(BaseModel):
    query: str
    regex: bool = False
    file_pattern: str = "**/*"
    max_results: int = 200
```

行为：

- 使用 Python 正则引擎；`regex=false` 时对 query 做字面量转义。
- 复用安全文件枚举逻辑，不依赖系统安装的 `rg`。
- 跳过 `.git`、符号链接目录、二进制和非 UTF-8 文件。
- 按相对路径、行号稳定排序。
- 返回 `path`、`line_number`、截断后的 `line`。
- 非法正则返回 `INVALID_PATTERN`；零匹配是成功结果。
- 达到匹配数上限或单行上限时分别标注截断。

### Provider 公共接口

```python
class LLMProvider(Protocol):
    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AsyncIterator[StreamEvent]: ...
```

Provider 同时承担两个协议边界：

1. 将统一 `ChatMessage` 联合类型转换成供应商原生消息。
2. 将 `ToolDefinition` 包装成供应商原生工具定义。

注册中心不提供 `to_openai()` 或 `to_anthropic()`，从而避免协议泄漏。

### OpenAIProvider

请求转换：

- `UserMessage` 转为 `{"role": "user", "content": ...}`。
- 普通 `AssistantMessage` 转为 assistant 文本消息。
- 含调用的 `AssistantMessage` 将 `tool_calls` 元组完整转为原生 `tool_calls` 数组，参数使用保存的原始 JSON。
- `ToolResultMessage` 转为 `{"role": "tool", "tool_call_id": ..., "content": result_json}`。
- 工具定义转为 `{"type": "function", "function": {"name", "description", "parameters"}}`。
- 有工具时设置 `tool_choice="auto"`。

流解析：

- 以 `choice.index` 校验只存在一个响应分支。
- 按 `tool_call.index` 分组，首次片段记录 id、type 和 name，后续片段只允许补充一致字段。
- 顺序追加 `function.arguments` 碎片。
- `finish_reason="tool_calls"` 时要求至少一个完整调用；`finish_reason="stop"` 时要求有文本。
- 流结束前不产出 `TOOL_CALL`，从而避免残缺调用被执行。
- 同批多个调用全部保留并交由 ChatSession 产生单工具限制结果。

### AnthropicProvider

请求转换：

- 连续的统一消息按 Anthropic `user` / `assistant` 角色构造内容块。
- 助手工具调用将 `tool_calls` 元组完整转为同一 assistant 消息中的多个 `tool_use` block。
- 工具结果使用下一条 `user` 消息中的 `tool_result` block，并设置 `is_error = not result.success`。
- 工具定义使用 `{"name", "description", "input_schema"}`。

流解析：

- `content_block_start` 遇到 `tool_use` 时记录 block index、id、name；SDK 提供的初始 `input` 必须为空 object，参数正文统一来自后续 JSON delta。
- `content_block_delta` 的 `input_json_delta.partial_json` 按 block index 拼接。
- 文本与 thinking 仍按现有方式增量上送。
- `content_block_stop` 封闭对应调用；`message_stop` 后统一验证。
- 多个 `tool_use` block 全部保留给 ChatSession 做限制处理。
- 缺 id/name、非空初始 input、重复 block index、结束前未封闭、JSON 无法完整解析或 stop reason 不一致均判为无效流。

### ChatSession 工具回合状态机

`ChatSession` 注入 Provider、ToolRegistry、ToolExecutor 和 ToolContext。公开入口仍为异步事件流：

```python
async def stream_reply(
    self,
    user_input: str,
) -> AsyncIterator[StreamEvent]: ...
```

TUI 创建 Session 时把命令批准能力绑定到 `ToolContext` 的 handler，因此会话接口无需依赖 Textual 类型。

状态流：

```text
START
  │
  ├─ 第一次响应为纯文本 + DONE
  │      └─ 原子提交 User + Assistant → COMPLETE
  │
  └─ 第一次响应包含 TOOL_CALL + DONE
         ├─ 调用数 > 1
         │    └─ 构造 MULTIPLE_TOOLS 结果，不执行
         │
         └─ 调用数 = 1
                └─ ToolExecutor.execute()
                       ├─ 成功
                       ├─ 可恢复错误
                       └─ 用户拒绝
                              │
                              ▼
             yield TOOL_RESULT
             构造候选历史：
             User + Assistant(tool_calls) + ToolResult(s)
                              │
                              ▼
                    第二次 Provider.stream()
                       ├─ 纯文本 + DONE
                       │    └─ 整轮原子提交 → COMPLETE
                       └─ 再次 TOOL_CALL
                            └─ yield LIMIT_REACHED
                               不执行、不发第三次请求、不提交本轮
```

关键事务规则：

- 第一次响应出现工具调用时，允许同时有前置文本，但不能把该文本提前提交。
- 多工具限制也作为 `ToolResultMessage` 回灌一次，让模型有机会生成最终解释。由于供应商协议要求结果与调用 ID 对应，分别为每个被拒绝的调用生成 `MULTIPLE_TOOLS` 结果，所有结果内容一致且没有工具被执行。
- 工具参数错误、未知工具、路径错误和用户拒绝都是可恢复结果，仍进入第二次模型请求。
- Provider 无效流、第二次再次调用工具、取消或最终文本为空时，整个候选轮次不进入 `_history`。
- 文件工具可能在最终答复失败前已完成副作用；UI 明确显示结果，但会话上下文仍回滚，且不自动撤销文件。
- 纯文本路径保持现有事务规则及一次 Provider 调用。
- Provider 接收的每次请求都带相同的工具定义，为后续 Agent Loop 保持契约稳定。

### TUI 工具展示

新增 `ToolMessage` widget，采用紧凑、非嵌套布局：

```text
工具  read_file
      src/mewcode/session.py
      完成 · 读取 43 行

工具  execute_command
      uv run pytest -q
      已拒绝
```

事件处理：

- `TOOL_CALL`：在当前助手消息后插入 pending 工具记录。
- `TOOL_RESULT`：更新对应记录为 complete/rejected/error，并显示有界摘要；多工具限制可更新多个 pending 记录。
- `LIMIT_REACHED`：追加状态消息，并将当前助手消息标记为 error。
- 第二次模型文本继续更新同一条 AssistantMessage，工具前的文本与最终文本之间保留清晰分隔，不创建重复的用户消息。
- transcript 保存工具名、调用摘要和结果摘要，不保存未显示的完整输出。

### CommandApprovalScreen

```python
class CommandApprovalScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "approve"),
        Binding("enter", "approve"),
        Binding("n", "reject"),
        Binding("escape", "reject"),
    ]
```

模态框展示：

- 标题“允许执行命令？”
- 完整命令，使用可滚动文本区，禁止编辑。
- 工作目录显示为项目根目录。
- 超时秒数。
- 明确的“执行”和“拒绝”按钮及键盘行为。

App 通过 `push_screen_wait()` 返回一次性布尔结果。模态期间 composer 草稿不变；关闭后焦点恢复输入框。确认请求被用户拒绝时返回 false，但整个 reply worker 被 `Ctrl+C` 取消时仍向上传播取消。

### 取消路径

- 模型流阶段：取消 reply worker，Provider 流在 `finally` 中关闭。
- 等待确认阶段：关闭模态框并取消本轮，不启动命令。
- 命令运行阶段：取消传递到工具，工具终止并回收整个进程组后重新抛出。
- 文件工具阶段：在线程或协程取消点前完成的原子替换不回滚。
- 所有取消路径都把 UI 工具记录标成 cancelled，并恢复 composer 与提交能力。

## 文件组织

```text
src/mewcode/
├── cli.py
├── models.py
├── errors.py
├── session.py
├── tui.py
├── providers/
│   ├── base.py
│   ├── openai.py
│   └── anthropic.py
└── tools/
    ├── __init__.py
    ├── base.py          # Tool、ToolDefinition、ToolContext、ToolResult
    ├── errors.py        # ToolError、ToolErrorCode
    ├── paths.py         # ProjectPaths、原子 UTF-8 写入
    ├── registry.py      # ToolRegistry、默认注册工厂
    ├── executor.py      # 参数校验、确认、超时、错误转换
    ├── read_file.py
    ├── write_file.py
    ├── edit_file.py
    ├── execute_command.py
    ├── find_files.py
    └── search_code.py

tests/
├── tools/
│   ├── test_paths.py
│   ├── test_file_tools.py
│   ├── test_search_tools.py
│   ├── test_execute_command.py
│   └── test_executor.py
├── providers/
│   ├── test_openai.py
│   └── test_anthropic.py
├── test_session.py
├── test_tui.py
└── test_cli.py

docs/features/
├── 000-current-features.md
└── 001-tool-system.md
```

`models.py` 保存跨 Provider 的消息和流事件；工具领域模型集中在 `tools/base.py`，避免 `models.py` 变成所有业务类型的集合。

## 模块交互

依赖方向保持单向：

```text
CLI → TUI / Session / Provider / Tools
TUI → Session / Models / Tool approval types
Session → Provider protocol / Models / ToolRegistry / ToolExecutor
Provider implementations → Provider protocol / Models / ToolDefinition
ToolExecutor → ToolRegistry / ToolContext / Tool errors
Core tools → Tool protocol / ProjectPaths
ProjectPaths → Python standard library
```

Provider 不依赖 Session 或 TUI；工具不依赖 Provider、Session 或 TUI；Session 不依赖任何供应商 SDK；TUI 不解析工具 JSON 或执行工具。

## 测试设计

### 工具与安全单元测试

- 临时项目目录验证普通路径、`..`、项目外绝对路径、文件符号链接和父目录符号链接。
- 读文件覆盖行范围、空文件、截断、目录、二进制和无效 UTF-8。
- 写文件覆盖父目录创建、新建、覆盖、权限保留和临时文件清理。
- 改文件覆盖唯一、零次、多次匹配及失败时字节不变。
- 查找文件覆盖 glob、排序、数量上限、`.git` 和符号链接跳过。
- 搜索覆盖字面量、正则、glob、非法正则、长行、二进制、非 UTF-8 和结果上限。
- 命令覆盖批准、拒绝、成功、非零退出、stdout/stderr 截断、启动失败、超时、取消和子进程回收。

### 注册与执行器测试

- 六个默认工具定义完整且 Schema 关闭未知字段。
- 重复名称和无效定义在注册时失败。
- 未知工具、无效 JSON、非 object JSON、缺字段、未知字段和类型错误映射到稳定错误码。
- approval handler 每次调用一次，拒绝时工具 execute 从未运行。
- 普通异常脱敏，`CancelledError` 保持取消语义。

### Provider 协议测试

OpenAI：

- 断言统一消息历史和工具定义转换为正确 Chat Completions 请求。
- 用官方 SDK 解析本地 SSE，覆盖分段 id/name/arguments、前置文本和 stop。
- 覆盖多 tool call index、字段冲突、残缺 JSON、错误 finish reason 和异常结束。

Anthropic：

- 断言统一历史转换成 `tool_use` / `tool_result` 内容块。
- 用官方 SDK 解析本地 SSE，覆盖 `content_block_start`、多段 `partial_json`、block stop 和 message stop。
- 覆盖多 block、重复 index、缺字段、残缺 JSON、未封闭 block 和异常结束。

### 会话与 TUI 测试

- 纯文本路径只调用 Provider 一次并保持旧历史形态。
- 成功工具回合恰好调用两次 Provider，并原子提交四条结构化消息。
- 工具错误、拒绝和多工具限制均回灌一次并允许最终文字答复。
- 第二次工具调用不执行、不发第三次请求且不提交半轮。
- 取消发生在首次流、确认、工具执行和第二次流时均回滚历史。
- Textual Pilot 验证工具记录更新、模态键盘操作、草稿保持、滚动跟随、Ctrl+C 和静态记录。
- 现有 48 项回归测试全部适配并继续通过。

### tmux 端到端验收

使用独立临时项目目录，避免修改 MewCode 源码。启动本地、确定性的 OpenAI 和 Anthropic SSE 测试服务，分别用真实 SDK 协议驱动以下对话：

1. 请求读取测试文件，观察工具请求、结果和最终答复。
2. 请求新建并唯一替换文件，退出后核对磁盘内容。
3. 请求查找文件和搜索内容，观察相对路径与行号。
4. 请求执行命令，分别用键盘批准和拒绝，确认只有批准分支产生副作用。
5. 请求多个工具和第二次工具，确认均不执行。
6. 生成或命令运行中按 `Ctrl+C`，确认恢复就绪且无残留进程。
7. 退出后检查静态 transcript，并逐项更新 checklist。

可用外部 API 时追加真实模型工具选择测试，但本地双协议端到端是完成条件，避免验收受第三方认证状态阻塞。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 工具参数验证 | 每工具 Pydantic 模型 | 已有依赖，可生成 JSON Schema，并统一拒绝未知字段 |
| 路径边界 | 解析后的 `Path` 组成关系 | 能防止字符串前缀、`..` 和符号链接绕过 |
| 文件提交 | 同目录临时文件 + 原子替换 | 避免部分写入，同时保持实现聚焦 |
| 内容搜索 | Python 文件遍历与正则 | 不产生未经确认的子进程，跨环境行为一致 |
| 命令执行 | 异步 Shell + 独立进程组 | 支持完整命令、并发读取输出、超时和整组终止 |
| 命令权限 | 每次 TUI 模态确认 | 符合用户选择，批准不跨调用复用 |
| 工具调用产出 | 流结束后统一 `TOOL_CALL` | 残缺或冲突碎片不会提前触发副作用 |
| 会话历史 | 供应商无关联合消息 | 可完整重放工具回合，并保持协议隔离 |
| 工具回合 | 最多两次 Provider 请求 | 满足本章单工具边界，为下一章 Agent Loop 留扩展点 |
| 事务提交 | 最终文字答复后整轮提交 | 后续请求不会看到半轮协议消息 |
| UI 展示 | transcript 仅存有界摘要 | 静态记录可读且不复制大量工具输出 |
| 输出限制 | 字节、行数、结果数多重上限 | 控制模型上下文、内存和终端布局风险 |

## 设计自检

### Spec 覆盖

| Spec 需求 | 设计归属 |
|---|---|
| F1-F2 | Tool 接口、ToolDefinition、ToolRegistry |
| F3-F4 | ToolContext、ProjectPaths |
| F5 | ReadFileTool、ProjectPaths、文件大小与行数上限 |
| F6 | WriteFileTool、父目录创建、原子写入 |
| F7 | EditFileTool、唯一匹配、原子写入 |
| F8-F9 | ExecuteCommandTool、ApprovalHandler、CommandApprovalScreen |
| F10-F11 | FindFilesTool、SearchCodeTool |
| F12-F13 | ToolExecutor、ToolResult、ToolErrorCode |
| F14 | TranscriptEntry、ToolMessage、静态 transcript |
| F15-F16 | OpenAIProvider、AnthropicProvider 流解析 |
| F17 | ChatSession 多工具校验、`tool_calls` 元组、MULTIPLE_TOOLS 结果 |
| F18 | ChatSession 两阶段状态机、工具结果回灌 |
| F19 | 第二次调用限制、LIMIT_REACHED、禁止第三次请求 |
| F20-F21 | 结构化历史、事务提交、取消路径 |
| F22 | 统一领域模型、双 Provider 契约与共享场景测试 |

### 接口完整性

- Tool、Registry、Executor、Provider 与 Session 的输入输出均已定义。
- 六个工具的参数、主要结果和错误语义均已定义。
- 命令确认从工具层到 TUI 的异步回调契约已定义。
- Provider 请求转换、流完成条件和历史重放格式已定义。

### 依赖与矛盾检查

- 依赖从 CLI/TUI/Session 指向领域和工具层，不存在工具反向依赖 UI 或 Provider 的环。
- 注册中心保持供应商无关，Provider 负责原生字典，符合协议隔离要求。
- 命令逐次确认但 Shell 本身不受路径沙箱限制，与 spec 的安全声明一致。
- 一个工具调用后仅允许一次最终模型请求；多调用全部拒绝；不存在隐式 Agent Loop。
- 文件副作用不随会话回滚，与 spec 的“不实现撤销”边界一致。
