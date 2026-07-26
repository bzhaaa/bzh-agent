# MewCode 结构化系统提示与缓存 Plan

## 架构概览

采用独立 Prompt Pipeline。AgentRunner 在每次模型请求前构造供应商无关的请求信封，Provider 只负责协议映射。

```text
CLI 组装
 ├─ StablePromptBuilder
 ├─ EnvironmentCollector
 ├─ ReminderScheduler
 ├─ AgentRunner
 └─ OpenAI / Anthropic Provider
             │
             ▼
用户提交 → ChatSession
             │ 真实用户任务、模式状态、可选插槽
             ▼
         AgentRunner
             │ 每次迭代
             ├─ 选择 Normal / Plan 工具集合
             ├─ 读取当前环境快照
             ├─ 生成完整或精简 system-reminder
             └─ 构造 PromptEnvelope
                    ├─ stable_system
                    ├─ system_supplements
                    ├─ tools
                    └─ history + pending user message
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          AnthropicProvider          OpenAIProvider
          ├─ 显式 cache_control       ├─ 稳定 system 前缀
          ├─ system content blocks    ├─ 动态 system 消息
          └─ cache create/read        └─ cached_tokens
                 │                         │
                 └────────────┬────────────┘
                              ▼
                      ProviderEvent / AgentEvent
```

各层职责：

1. **稳定提示构建层。** 保存七个固定模块及其优先级，启动时构建字节稳定的系统提示。它不读取环境、模式、历史或 Provider 配置。
2. **环境采集层。** 每次 Provider 请求前生成有界快照，包括脱敏项目路径、平台、Shell、日期时区、Git 分支和 dirty 布尔状态。Git 不可用时返回安全的 unknown，不阻塞请求。
3. **动态提醒层。** 根据当前模式和 Agent 迭代号生成完整或精简模式约束，再按“环境、自定义指令、Skill、记忆”顺序包装成一个 `<system-reminder>`。提醒仅存在于当前请求。
4. **请求信封层。** 把稳定提示、动态提醒、当前模式工具定义和真实历史组合为不可变请求对象。AgentRunner 不再分别向 Provider 传 `messages` 和 `tools`。
5. **Provider 映射层。** Anthropic 将稳定提示、动态提醒和工具缓存点映射到原生 content blocks；OpenAI 将其映射为稳定 system 消息、动态 system 消息和工具列表。协议专属缓存字段不向上泄漏。
6. **用量归一化层。** 保留现有输入、输出 Token 语义，并增加缓存创建与缓存读取明细。缓存明细不重复计入总 Token，避免破坏当前 TUI 的总量显示。
7. **会话边界。** ChatSession 只保存真实用户消息、助手消息和工具结果。`/plan` 保存用户任务正文，`/do` 保存用户的执行意图；环境和模式提醒永远不提交历史。

## 核心数据结构

### AgentMode

`AgentMode` 从 `agent/events.py` 移到共享的 `models.py`，Agent 包继续重新导出，现有调用方无需改变导入方式。Prompt 层由此只依赖共享领域模型，不反向依赖 Agent 包。

### PromptSection

```python
class PromptChannel(StrEnum):
    STABLE = "stable"
    SUPPLEMENT = "supplement"


@dataclass(frozen=True, slots=True)
class PromptSection:
    name: str
    priority: int
    content: str
    channel: PromptChannel
```

固定优先级：

```text
100  identity
200  system_constraints
300  task_mode
400  action_execution
500  tool_usage
600  tone_style
700  text_output
800  environment
900  custom_instructions
1000 active_skills
1100 long_term_memory
```

按 priority 升序排列。名称或优先级重复时拒绝组装，避免不确定顺序。未来插入模块可以使用中间优先级，不需要修改拼装算法。

### PromptOptions

```python
@dataclass(frozen=True, slots=True)
class PromptOptions:
    custom_instructions: str | None = None
    active_skills: tuple[str, ...] = ()
    long_term_memory: str | None = None
```

- Skill 保留调用方给出的顺序。
- 每个可选部分最多 16 KiB UTF-8。
- 可选内容合计最多 28 KiB，为环境、模式和标签保留 4 KiB。
- 完整补充消息最多 32 KiB UTF-8。
- 超限或仅含空白的 Skill 条目抛出 `PromptBuildError`；空的可选模块直接跳过。
- CLI 默认构造全空 Options。

### EnvironmentSnapshot

```python
@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    project_root: str
    platform: str
    shell: str
    current_date: str
    timezone: str
    git_branch: str
    git_dirty: bool | None
    mode: AgentMode
```

`project_root` 将用户主目录前缀显示为 `~`。`git_dirty=None` 表示非 Git 项目或无法确定，不保存文件列表。

### ReminderDetail

```python
class ReminderDetail(StrEnum):
    FULL = "full"
    COMPACT = "compact"


class ReminderScheduler:
    def detail_for(self, iteration: int) -> ReminderDetail:
        # 1、6 为 FULL；其余为 COMPACT
        ...
```

计数直接使用 AgentRunner 现有的 1-based iteration，因此每次用户提交自动重置。

### StructuredPrompt

```python
@dataclass(frozen=True, slots=True)
class StructuredPrompt:
    stable_system: str
    supplements: tuple[str, ...]
```

- `stable_system` 是七个固定模块按空行连接的结果。
- 当前版本只产生一个 supplement，使用 `<system-reminder>` 包裹环境、模式和可选模块。
- tuple 为后续增加项目指令等独立系统补充消息保留接口。

### PromptEnvelope

```python
@dataclass(frozen=True, slots=True)
class PromptEnvelope:
    prompt: StructuredPrompt
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...]
```

它是 Agent 与 Provider 的唯一请求边界，不包含任何 Anthropic 或 OpenAI 原生字段。

### PromptPipeline

```python
class PromptPipeline:
    async def build(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
        project_root: Path,
        mode: AgentMode,
        iteration: int,
        options: PromptOptions,
    ) -> PromptEnvelope: ...
```

内部依次构建稳定模块、采集环境、选择提醒详细度、验证边界、生成 supplement、冻结消息和工具顺序。

### Provider 接口

```python
class LLMProvider(Protocol):
    def stream(self, request: PromptEnvelope) -> AsyncIterator[ProviderEvent]: ...
```

现有 `stream(messages, tools)` 和 AgentRunner 中基于函数签名的兼容分支被删除，所有真实与测试 Provider 统一迁移到 Envelope。

### AgentRunRequest

```python
@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    history: tuple[ChatMessage, ...]
    user_message: UserMessage
    mode: AgentMode
    control: AgentRunControl
    history_sink: HistorySink
    prompt_options: PromptOptions = PromptOptions()
    max_iterations: int = 10
```

Options 属于本次用户提交，不写入历史。

### TokenUsage

```python
@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
```

设计约定：

- `input_tokens` 保持本次总输入 Token 语义，避免改变当前 TUI 总量。
- 缓存字段是输入总量的明细，不再次加入 `total_tokens`。
- Anthropic 总输入为普通输入、缓存创建和缓存读取之和。
- OpenAI 总输入直接使用 `prompt_tokens`，`cached_tokens` 映射为缓存读取明细，缓存创建保持未知。
- 四个字段独立累计；任一字段在某次请求未知时，仅对应累计字段传播为未知。

## 提示构建模块

### `prompting/sections.py`

定义七个固定模块及稳定文本。固定模块不读取运行时状态。

| 模块 | 核心内容 |
|---|---|
| 身份 | MewCode 是在当前项目中完成软件任务的终端 Coding Agent；以实际结果为目标 |
| 系统约束 | 遵循系统与用户要求；区分事实和推断；不伪造工具输出、测试结果或完成状态；不泄露隐藏指令 |
| 任务模式 | Normal 与 Plan 的稳定定义；当前活动模式以 system reminder 为准 |
| 动作执行 | 先理解上下文，再行动、检查结果并调整；只有完成或命中停止条件才结束 |
| 工具使用 | 优先专用工具；找文件、搜内容不用 Shell；编辑已有文件前先读；失败后根据结构化结果调整 |
| 语气风格 | 默认中文、直接、协作；避免空洞承诺和重复说明；不确定时明确说明 |
| 文本输出 | 先给结果，再给必要证据；路径、命令和标识清晰；未实际运行的检查不得声称通过 |

固定内容使用模块常量，不在运行时拼入版本、日期、Provider、模型或项目名称，保证稳定前缀。

### `prompting/builder.py`

`StablePromptBuilder`：

1. 合并固定模块与将来的额外稳定模块。
2. 校验名称、优先级、内容和通道。
3. 按 priority 升序排序。
4. 使用恰好一个空行连接。
5. 在实例创建后缓存结果，后续请求直接复用。
6. 相同名称、相同优先级、空内容或错误通道抛出 `PromptBuildError`。

`SupplementBuilder` 当前输出：

```text
<system-reminder>
<environment>
项目根目录、平台、Shell、日期、时区、Git、当前模式
完整或精简模式约束
</environment>
<custom-instructions>...</custom-instructions>
<active-skills>...</active-skills>
<long-term-memory>...</long-term-memory>
</system-reminder>
```

- 空的可选标签完全省略。
- 所有动态文本先做 XML 文本转义，不能通过 `</system-reminder>` 提前闭合标签。
- Skill 按调用方顺序编号并聚合在一个标签内。
- 先执行单部分、可选合计和 supplement 总长校验，再生成字符串。
- supplement 每次重新生成，但不会追加到上一次结果。

### `prompting/reminders.py`

完整 Normal 提醒包含：允许使用当前全部工具；持续调查、执行和验证；写改前先读；命令服从确认；任务未完成时继续循环。

完整 Plan 提醒包含：只调查和形成计划；不得修改文件或执行命令；只能使用当前三个只读工具；用户要求直接执行时仍保持 Plan。

精简提醒：

- Normal：`当前为 Normal Mode；继续执行并验证，编辑已有文件前先读取。`
- Plan：`当前为 Plan Mode；保持只读，只调查并更新计划。`

`ReminderScheduler` 只根据 iteration 返回 FULL 或 COMPACT，不保存跨 Run 状态。

### `prompting/environment.py`

`EnvironmentCollector.collect()` 每次请求执行：

- 项目路径位于用户主目录下时用 `~` 替换主目录前缀。
- 平台来自标准平台信息，不包含主机名。
- Shell 只读取允许的 Shell 路径来源，不枚举环境变量。
- 日期和时区使用当前本地时区，格式稳定。
- Git 分支优先取 symbolic branch；detached HEAD 使用有前缀的短提交标识。
- dirty 只记录布尔值，不保存状态输出或文件名。
- Git 子进程使用参数数组、固定项目目录、1 秒超时和有界读取。
- Git 不存在、超时、非仓库或权限失败时返回 unknown，不向模型暴露异常正文。

### `prompting/pipeline.py`

`PromptPipeline.build()`：

1. 获取已经缓存的 stable system。
2. 异步采集当前环境。
3. 根据 mode 与 iteration 选择模式提醒。
4. 合并并验证 `PromptOptions`。
5. 构建唯一的 system reminder。
6. 冻结 messages 与 tools，返回 `PromptEnvelope`。

该模块不访问 Provider，不修改历史，也不保存 API Key。

## Agent、Provider 与工具集成

### `agent/runner.py`

`AgentRunner` 新增 `PromptPipeline` 依赖。每次迭代：

1. 选择当前 Normal 或 Plan Scheduler。
2. 生成候选历史，包含尚未提交的真实用户消息。
3. 从 Scheduler 取得稳定顺序的工具定义。
4. 调用 Prompt Pipeline 构造 Envelope。
5. 调用 `provider.stream(envelope)`。
6. 沿用现有 Collector、工具调度、检查点和停止条件。

删除基于 `inspect.signature()` 的旧 Provider 兼容分支。提示补充消息只存在于 Envelope，不加入 candidate、checkpoint 或 HistorySink。`PromptOptions` 在一次 Agent Run 开始时冻结。

### `session.py`

移除 `_plan_instruction()`、`_plan_followup()` 和 `_do_instruction()`。

| 输入 | 历史中的真实 UserMessage | 系统补充消息 |
|---|---|---|
| `/plan 调查模块` | `调查模块` | 完整 Plan 约束 |
| Plan 中普通补充 | 用户原文 | Plan 完整或精简约束 |
| `/do` | `/do` | 完整 Normal 约束 |
| Normal 普通输入 | 用户原文 | Normal 完整或精简约束 |

`/plan` 空任务、无计划 `/do`、计划就绪和新规划清理旧状态的行为不变。

Session 保存当前 `PromptOptions`，提供只允许在没有活动 Run 时调用的程序化更新入口。每次创建 `AgentRunRequest` 时复制当前 Options。

### `providers/anthropic.py`

System 映射：

```python
system = [
    {
        "type": "text",
        "text": envelope.prompt.stable_system,
        "cache_control": {"type": "ephemeral"},
    },
    {
        "type": "text",
        "text": envelope.prompt.supplements[0],
    },
]
```

工具保持原顺序，并在最后一个工具上增加 `cache_control: {"type": "ephemeral"}`。Normal 六工具和 Plan 三工具各自形成稳定缓存版本。使用默认 ephemeral TTL，不新增配置或主动保活。

历史继续转换为 Anthropic `user`、`assistant`、`tool_use` 和 `tool_result`，动态 system block 不参与相邻角色合并。Extended thinking 参数和流解析保持原样。

用量解析：

- `input_tokens` 读取普通输入。
- `cache_creation_input_tokens` 和 `cache_read_input_tokens` 不再用默认 0 掩盖缺失字段。
- 对官方返回的已知三个输入分类求和，作为统一总输入。
- 兼容服务缺少缓存明细时，保留明细未知，并沿用其 `input_tokens` 作为总输入。
- 所有已返回值必须是非负整数，否则按无效流停止。

### `providers/openai.py`

请求消息顺序：

```text
system: stable_system
system: <system-reminder>...</system-reminder>
历史与当前真实用户消息
```

使用 `system` 而不是 `developer`，保持 Chat Completions 和现有兼容服务范围。工具定义仍位于请求的 `tools` 字段，不发送 `cache_control`。

用量映射：

```text
prompt_tokens                         → input_tokens
completion_tokens                     → output_tokens
prompt_tokens_details.cached_tokens   → cache_read_input_tokens
无对应字段                            → cache_creation_input_tokens = unknown
```

`cached_tokens` 是 `prompt_tokens` 的明细，不再次计入总量。兼容服务缺少 `prompt_tokens_details` 时缓存读取保持未知。

### `models.py` 与事件累计

- `total_tokens` 仍只计算 `input_tokens + output_tokens`。
- `accumulate()` 对四个字段分别累计并独立传播未知。
- `StreamCollector` 缺失 usage 时生成四字段均未知。
- `UsageSnapshot` 和 AgentEvent 不增加事件类型。
- TUI 继续只读取 `total_tokens`，不展示缓存字段。

### 六个工具描述

只修改描述，不修改参数 Schema 或执行逻辑：

- `read_file`：编辑已有文件前的必经读取工具。
- `write_file`：只用于新建或完整覆盖；覆盖前先读，小范围变化优先 `edit_file`。
- `edit_file`：先用 `read_file` 获取当前精确原文，只提交唯一、小范围替换。
- `find_files`：查找路径时优先于 Shell 的 `find`、`ls`。
- `search_code`：搜索内容时优先于 Shell 的 `grep`、`rg`。
- `execute_command`：只用于专用工具不能完成的命令、测试或构建，不替代读写改查工具。

Registry 保持现有注册顺序，Plan 子集逻辑不变。

### `cli.py`

CLI 在项目根目录确定后组装 StablePromptBuilder、EnvironmentCollector、ReminderScheduler、PromptPipeline、AgentRunner 和 ChatSession。无新增命令行参数或 YAML 字段。Provider 关闭、命令确认延迟绑定和 TUI 启动流程不变。

## 模块交互

### 普通 Agent Run

```text
用户输入
  ↓
ChatSession 创建真实 UserMessage + PromptOptions 快照
  ↓
AgentRunner iteration 1
  ├─ candidate = 已提交历史 + pending user
  ├─ tools = Normal 六工具
  ├─ PromptPipeline 采集环境并生成 FULL reminder
  ├─ 构造 PromptEnvelope
  └─ Provider 发起请求
         ↓
    文本或工具调用
         ├─ 最终文本 → 提交真实用户消息与助手消息
         └─ 工具调用 → 执行、提交工具检查点
                              ↓
                     iteration 2
                     重新采集环境
                     生成 COMPACT reminder
                     历史只包含真实消息和工具结果
```

第 6 次请求重新使用 FULL reminder。每次请求重新构建 supplement，但 stable system 和同模式 tools 使用同一稳定对象与顺序。

### Plan/Do

```text
/plan 调查模块
  ↓
Session: mode=PLAN, plan_ready=False
  ↓
UserMessage("调查模块")
  + FULL Plan system-reminder
  + 三个只读工具
  ↓
调查循环完成，真实计划答复进入历史，plan_ready=True
  ↓
/do
  ↓
Session: mode=NORMAL, plan_ready=False
  ↓
UserMessage("/do")
  + FULL Normal system-reminder
  + 六个工具
  ↓
根据已有计划执行
```

Plan 中的普通补充保持用户原文。启动新规划或规划失败时，旧计划就绪状态仍清除。

### Anthropic 缓存边界

```text
稳定工具定义（最后一个工具 cache breakpoint）
稳定七模块 system（cache breakpoint）
动态 system-reminder（不缓存）
真实历史与当前用户消息
```

同一模式的后续请求只改变断点后的内容。Plan 与 Normal 因工具集合不同形成两个独立稳定前缀，不跨模式共享工具缓存。

### OpenAI 自动缓存边界

```text
稳定 system
动态 system-reminder
真实历史与当前用户消息
稳定 tools
```

MewCode 只保证请求内容与顺序稳定，不推断服务端内部序列化顺序。动态内容变化后，是否命中及命中长度以 `cached_tokens` 实际返回为准。

### 用量事件

```text
Provider 原生 usage
  ↓
TokenUsage(input, output, cache_creation, cache_read)
  ↓
StreamCollector
  ↓
UsageSnapshot(request, cumulative)
  ↓
AgentEvent.TOKEN_USAGE
```

四个字段分别校验和累计。TUI 仍只读取 `total_tokens`，独立测试或缓存验证器读取缓存明细。

### 边界校验

`PromptOptions` 在 Session 创建或程序化更新时立即验证。更新时若已有活动 Run 则拒绝，失败不修改原有 Options。默认 CLI 路径不会在 Agent 循环中遇到用户可触发的 PromptBuildError。

### 环境任务与取消

AgentRunner 把 `PromptPipeline.build()` 放入独立异步任务，并使用现有 `AgentRunControl` 与其竞争：

- 取消先发生时取消 Pipeline，不发起 Provider 请求。
- Git 子进程收到任务取消或 1 秒超时时终止并等待回收。
- 环境采集普通失败时返回 unknown，继续请求。
- 强制 Worker 取消时 `CancelledError` 继续向上传播。

### 历史不污染

七模块 system、system reminder、环境、模式约束、可选插槽和缓存元数据均不传给 HistorySink。HistorySink 只接收 `UserMessage`、`AssistantMessage` 和 `ToolResultMessage`。

## 文件组织

```text
mew/
├── src/mewcode/
│   ├── prompting/
│   │   ├── __init__.py
│   │   ├── errors.py
│   │   ├── models.py
│   │   ├── sections.py
│   │   ├── builder.py
│   │   ├── reminders.py
│   │   ├── environment.py
│   │   └── pipeline.py
│   ├── agent/runner.py
│   ├── providers/{base.py,anthropic.py,openai.py}
│   ├── tools/{read_file.py,write_file.py,edit_file.py,find_files.py,search_code.py,execute_command.py}
│   ├── models.py
│   ├── session.py
│   └── cli.py
├── scripts/verify_prompt_cache.py
├── tests/
│   ├── prompting/{test_builder.py,test_environment.py,test_pipeline.py}
│   ├── fixtures/prompt_eval/{README.md,src/sample.py}
│   ├── agent/test_runner.py
│   ├── providers/{test_anthropic.py,test_openai.py}
│   ├── e2e/mock_llm_server.py
│   ├── test_session.py
│   ├── test_cli.py
│   └── test_tui.py
├── docs/
│   ├── evals/003-system-prompt-scenarios.md
│   └── features/
│       ├── 003-structured-system-prompt.md
│       ├── 003-claude-code-system-prompt.md
│       └── README.md
├── spec.md
├── plan.md
├── task.md
└── checklist.md
```

新增文件职责：

| 文件 | 职责 |
|---|---|
| `prompting/models.py` | Section、Options、环境快照、提醒详细度、结构化提示和 Envelope |
| `prompting/sections.py` | 七个固定模块、优先级和稳定正文 |
| `prompting/builder.py` | 排序、校验、空行连接、XML 转义和长度限制 |
| `prompting/reminders.py` | Normal/Plan 完整与精简提醒及第 1/6 次调度 |
| `prompting/environment.py` | 有界、脱敏、可取消的环境和 Git 采集 |
| `prompting/pipeline.py` | 组装一次完整 PromptEnvelope |
| `prompting/errors.py` | 有界且不泄露内容的 PromptBuildError |
| `verify_prompt_cache.py` | 使用指定 profile 发起固定次数请求，输出脱敏缓存指标 |
| `003-system-prompt-scenarios.md` | 六类人工对比任务、固定输入、观察维度和记录表 |
| `tests/fixtures/prompt_eval/` | 可复制到临时目录的最小人工评估项目 |

修改文件职责：

| 文件 | 改动 |
|---|---|
| `models.py` | 共享 AgentMode；TokenUsage 增加缓存字段 |
| `providers/base.py` | Provider 接口改为接收 PromptEnvelope |
| `providers/anthropic.py` | system blocks、工具缓存点及缓存 usage |
| `providers/openai.py` | 双 system 消息及 cached_tokens |
| `agent/runner.py` | 每次迭代构造 Envelope，并让提示构建参与取消竞争 |
| `session.py` | 移除伪用户模式指令，管理 PromptOptions |
| `cli.py` | 组装 Prompt Pipeline |
| 六个工具模块 | 强化稳定 description，不改 Schema 和执行逻辑 |
| Provider/Agent/Session/CLI 测试 | 迁移新请求边界并验证缓存与历史 |
| `mock_llm_server.py` | 记录 system、cache_control、工具和缓存用量 |
| `test_tui.py` | 确认缓存明细不进入 UI，既有状态不回归 |
| `docs/features/README.md` | 登记 003 双文档 |
| `checklist.md` | 写入自动化、真实缓存、人工对比和 tmux 实证 |

`pyproject.toml` 不新增运行依赖，也不修改 YAML 配置模型。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Agent 与 Provider 边界 | 不可变 PromptEnvelope | 缓存、动态提醒和历史不靠位置约定或 Provider 重复推断 |
| 模块排序 | 显式数值优先级，重复即拒绝 | 顺序确定，也允许以后插入新模块 |
| 稳定提示生命周期 | Builder 实例内只构建一次 | 避免环境或迭代状态污染缓存前缀 |
| 动态消息数量 | 当前每次请求恰好一个 system reminder | 避免兼容服务对多个动态 system 消息行为不一致 |
| 标签安全 | XML 文本转义 | 自定义内容无法伪造闭合标签或改变模块边界 |
| 环境刷新 | 每次 Provider 请求重新采集 | 工具执行后 Git dirty 状态及时变化，但不进入稳定前缀 |
| Git 读取 | 参数数组、1 秒超时、有界输出 | 不经 Shell，不保存文件列表，不无限阻塞 |
| PromptOptions 更新 | 无活动 Run 时原子替换 | 一次 Run 内提示一致，失败不留下半更新状态 |
| Anthropic 缓存 | 最后工具和稳定 system 各设 ephemeral breakpoint | 分别覆盖稳定工具和七模块提示 |
| Anthropic TTL | 协议默认 ephemeral | 不增加配置、保活请求或供应商策略表面 |
| OpenAI 缓存 | 自动 Prompt Cache | Chat Completions 没有相同的显式断点契约 |
| OpenAI 系统角色 | 两条 `system` | 保持当前 Chat Completions 和兼容服务范围 |
| Plan/Normal 工具缓存 | 两套独立稳定前缀 | 不为缓存向 Plan 暴露副作用工具 |
| 输入 Token 语义 | Provider 总输入，缓存作为明细 | 不破坏 total_tokens、TUI 和累计，也不重复计数 |
| 缺失缓存字段 | `None` 并独立传播 | 区分零命中与服务未提供数据 |
| 可选内容边界 | 单项 16 KiB、可选 28 KiB、总计 32 KiB | 阻止无界增长并为环境标签留空间 |
| 提示构建取消 | Runner 包装 Pipeline 任务 | Prompt 层不依赖 AgentRunControl，避免循环导入 |
| 环境失败 | 降级为 unknown | 环境信息不是模型请求的前置条件 |
| 工具规则 | 只强化描述 | 符合提高遵守率目标，不扩大执行契约 |
| 自动化测试 | 假 Provider、假 usage、临时 Git | 稳定、无费用、无网络依赖 |
| 真实缓存验证 | 独立脚本、固定请求数、不打印正文 | 控制费用并保护密钥 |
| 缓存门槛 | 验证生产提示，不添加 padding | 不能用测试填充制造命中 |
| OpenAI 实测 | 命中则记录，缺失则 unknown | 兼容服务差异不阻塞整体验收 |
| 人工质量评估 | 固定夹具与记录表，不评分 | 保持为定性评估，不提前引入自动评估系统 |

## Spec 覆盖检查

| 需求范围 | 设计归属 |
|---|---|
| F1、F2、F3、F4、F5 | PromptSection、固定 sections、Builder、PromptOptions |
| F6、F7、F8、F9 | SupplementBuilder、ReminderScheduler、EnvironmentSnapshot、Session |
| F10、F11、F12 | 固定工具模块、六个 ToolDefinition、稳定 Registry |
| F13、F14 | Anthropic/OpenAI Provider 映射 |
| F15、F16 | TokenUsage、ProviderEvent、UsageSnapshot |
| F17 | Envelope 历史转换、thinking 与 Agent Loop 回归 |
| F18 | 有界真实缓存验证脚本 |
| F19 | 固定人工场景文档与夹具 |
| N1、N2、N3、N4、N5 | 分层依赖、稳定前缀、边界校验、敏感信息和协议隔离 |
| N6、N7、N8、N9、N10 | 缺失值、环境容错、配置兼容、行为回归和自动化测试 |
| N11、N12、N13、N14、N15 | 真实缓存成本、人工评估、tmux、003 文档和扩展插槽 |

模块依赖保持单向：

```text
prompting → models + tools 类型
providers → prompting + models + tools
agent → prompting + providers + tools
session → agent + prompting
cli → 组装全部组件
tui → session + AgentEvent
```

`prompting` 不导入 Session、Provider、Runner 或 TUI，避免循环依赖。
