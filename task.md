# MewCode 结构化系统提示与缓存 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/prompting/__init__.py` | 导出 Prompt Pipeline 公共 API |
| 新建 | `src/mewcode/prompting/errors.py` | 定义不泄露提示正文的构建错误 |
| 新建 | `src/mewcode/prompting/models.py` | 定义提示模块、可选项、环境快照、结构化提示和请求信封 |
| 新建 | `src/mewcode/prompting/sections.py` | 定义七个固定模块、优先级和稳定正文 |
| 新建 | `src/mewcode/prompting/builder.py` | 构建稳定提示与有界 `<system-reminder>` |
| 新建 | `src/mewcode/prompting/reminders.py` | 定义 Normal/Plan 完整与精简提醒及调度规则 |
| 新建 | `src/mewcode/prompting/environment.py` | 异步采集脱敏环境、分支和 dirty 状态 |
| 新建 | `src/mewcode/prompting/pipeline.py` | 为每次 Provider 请求构造 `PromptEnvelope` |
| 修改 | `src/mewcode/models.py` | 共享 `AgentMode`，扩展缓存 Token 用量字段 |
| 修改 | `src/mewcode/agent/events.py` | 从共享模型重新导出 `AgentMode` |
| 修改 | `src/mewcode/agent/collector.py` | 传播四字段 Token 用量和未知值 |
| 修改 | `src/mewcode/agent/runner.py` | 每轮构建 Envelope，接入提示构建取消与历史隔离 |
| 修改 | `src/mewcode/providers/base.py` | Provider 接口统一接收 `PromptEnvelope` |
| 修改 | `src/mewcode/providers/openai.py` | 映射双 system 消息并解析 `cached_tokens` |
| 修改 | `src/mewcode/providers/anthropic.py` | 映射 system/tool 缓存断点并解析缓存创建和读取用量 |
| 修改 | `src/mewcode/session.py` | 移除伪用户模式指令，管理 `PromptOptions` 快照 |
| 修改 | `src/mewcode/cli.py` | 组装稳定 Builder、环境采集器和 Prompt Pipeline |
| 修改 | `src/mewcode/tools/read_file.py` | 强调编辑已有文件前先读取 |
| 修改 | `src/mewcode/tools/write_file.py` | 强调覆盖前先读、小改优先编辑工具 |
| 修改 | `src/mewcode/tools/edit_file.py` | 强调先读、唯一匹配和小范围替换 |
| 修改 | `src/mewcode/tools/find_files.py` | 强调查找路径优先于 Shell |
| 修改 | `src/mewcode/tools/search_code.py` | 强调搜索内容优先于 Shell |
| 修改 | `src/mewcode/tools/execute_command.py` | 限定为专用工具无法完成的命令、测试和构建 |
| 新建 | `tests/prompting/test_builder.py` | 稳定模块、排序、标签、转义和长度边界测试 |
| 新建 | `tests/prompting/test_environment.py` | Git、非 Git、detached、脱敏、超时和取消测试 |
| 新建 | `tests/prompting/test_pipeline.py` | 提醒频率、可选插槽、稳定前缀和 Envelope 测试 |
| 修改 | `tests/agent/test_collector.py` | 四字段用量累计和缺失值测试 |
| 修改 | `tests/agent/test_runner.py` | Envelope、逐轮提醒、取消和历史隔离测试 |
| 修改 | `tests/providers/test_openai.py` | OpenAI system 顺序、工具稳定性和缓存用量测试 |
| 修改 | `tests/providers/test_anthropic.py` | Anthropic 缓存断点、thinking 和缓存用量测试 |
| 修改 | `tests/test_session.py` | Plan/Do 真实用户消息、Options 和活动 Run 边界测试 |
| 修改 | `tests/test_cli.py` | Prompt Pipeline 组装和旧配置兼容测试 |
| 修改 | `tests/test_tui.py` | 缓存明细不进入状态或 transcript 的回归测试 |
| 修改 | `tests/e2e/mock_llm_server.py` | 识别动态 system reminder 并返回确定性缓存字段 |
| 新建 | `tests/fixtures/prompt_eval/README.md` | 人工评估夹具说明和预期边界 |
| 新建 | `tests/fixtures/prompt_eval/src/sample.py` | 人工评估使用的最小待调查代码 |
| 新建 | `docs/evals/003-system-prompt-scenarios.md` | 固定场景、基线、新实现观察记录和对比表 |
| 新建 | `scripts/verify_prompt_cache.py` | 有界重复请求与脱敏缓存指标验证器 |
| 新建 | `docs/features/003-structured-system-prompt.md` | 本章 MewCode 功能总结与验收证据 |
| 新建 | `docs/features/003-claude-code-system-prompt.md` | Claude Code 对应机制的实现对照 |
| 修改 | `docs/features/README.md` | 登记 003 双文档和人工场景文档 |
| 修改 | `checklist.md` | 替换为本章验收项，并在开发后记录实际证据 |

## T1：建立人工评估夹具与固定场景

**文件：** `tests/fixtures/prompt_eval/README.md`、`tests/fixtures/prompt_eval/src/sample.py`、`docs/evals/003-system-prompt-scenarios.md`
**依赖：** 无

**步骤：**

1. 创建最小 Python 项目夹具，包含可搜索符号、可做精确小改的代码和不得越界访问的说明。
2. 固定六类任务文本：专用工具选择、编辑前读取、Plan 只读、安全边界、代码风格和输出简洁度。
3. 为每个场景记录固定模型、模式、工作目录、观察维度和实际结果栏，不设置自动分数。
4. 明确基线与新实现必须使用同一份夹具副本和相同任务文本。

**验证：** 运行 `rg -n "专用工具|编辑前读取|Plan|安全边界|代码风格|输出简洁" docs/evals/003-system-prompt-scenarios.md`，期望六类场景均存在且夹具路径可复制使用。

## T2：采集旧提示行为基线

**文件：** `docs/evals/003-system-prompt-scenarios.md`
**依赖：** T1

**步骤：**

1. 在修改实现前复制评估夹具到临时目录，并记录当前提交、Provider、模型和日期。
2. 使用当前 MewCode 对六个固定任务逐项运行，记录模型实际工具选择、调用顺序、文件变化和最终答复。
3. 对 Plan 场景确认当前模式提示仍作为用户内容发送，并记录只读表现。
4. 只记录脱敏结果，不写 API Key、完整主目录或认证错误正文。

**验证：** 检查场景文档的“旧提示基线”六行均有实际观察和可追溯运行信息，不得填写“预计”或“应该”。

## T3：迁移共享模式并扩展 Token 用量模型

**文件：** `src/mewcode/models.py`、`src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/agent/test_collector.py`
**依赖：** T2

**步骤：**

1. 将 `AgentMode` 移到共享 `models.py`，并由 Agent 包保持原公共导出。
2. 为 `TokenUsage` 增加可选的缓存创建和缓存读取字段，默认保持未知。
3. 保持 `total_tokens` 只计算总输入与输出，不重复加入缓存明细。
4. 让 `accumulate()` 对四个字段分别累计，未知仅向对应字段传播。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py -k usage`，期望旧两字段构造仍可用，缓存字段独立累计且总量语义不变。

## T4：定义 Prompt 领域模型与错误边界

**文件：** `src/mewcode/prompting/models.py`、`src/mewcode/prompting/errors.py`、`src/mewcode/prompting/__init__.py`、`tests/prompting/test_builder.py`
**依赖：** T3

**步骤：**

1. 定义 `PromptChannel`、`PromptSection`、`PromptOptions`、`EnvironmentSnapshot` 和 `ReminderDetail`。
2. 定义不可变的 `StructuredPrompt` 与 `PromptEnvelope`，消息和工具使用 tuple 冻结顺序。
3. 定义 `PromptBuildError`，错误信息只包含字段名、限制和实际字节数，不回显敏感正文。
4. 从 prompting 包入口导出计划约定的公共类型。

**验证：** 运行 `uv run pytest -q tests/prompting/test_builder.py -k "model or error"`，期望对象不可变、默认 Options 为空且错误不泄露输入正文。

## T5：实现七个固定模块与稳定组装

**文件：** `src/mewcode/prompting/sections.py`、`src/mewcode/prompting/builder.py`、`tests/prompting/test_builder.py`
**依赖：** T4

**步骤：**

1. 按 100 至 700 的固定优先级定义身份、系统约束、任务模式、动作执行、工具使用、语气风格和文本输出。
2. 保证每个模块非空，正文不包含日期、路径、Provider、模型或当前模式等动态值。
3. 实现 `StablePromptBuilder` 的名称、优先级、内容和 channel 校验。
4. 按优先级排序并用恰好一个空行连接；重复名称或优先级直接拒绝。
5. 在 Builder 实例内缓存构建结果，重复调用返回字节一致内容。

**验证：** 运行 `uv run pytest -q tests/prompting/test_builder.py -k "stable or section or priority"`，期望七模块顺序固定、间隔准确且非法模块均被拒绝。

## T6：实现有界的 System Reminder 构建

**文件：** `src/mewcode/prompting/builder.py`、`tests/prompting/test_builder.py`
**依赖：** T4

**步骤：**

1. 实现 `SupplementBuilder`，按环境、自定义指令、Skill、长期记忆顺序生成唯一 `<system-reminder>`。
2. 对所有动态文本执行 XML 文本转义，阻止调用方提前闭合标签。
3. 空可选项完全省略，Skill 保持调用方顺序并拒绝空白条目。
4. 执行单项 16 KiB、可选项合计 28 KiB、完整 supplement 32 KiB 的 UTF-8 字节边界校验。
5. 保证每次从输入重新生成，不把上轮 supplement 累积进本轮。

**验证：** 运行 `uv run pytest -q tests/prompting/test_builder.py -k "supplement or optional or limit or escape"`，期望标签顺序、转义、省略和三个长度边界全部正确。

## T7：实现模式提醒与第 1/6 次调度

**文件：** `src/mewcode/prompting/reminders.py`、`tests/prompting/test_pipeline.py`
**依赖：** T4

**步骤：**

1. 定义 Normal 与 Plan 的完整提醒，覆盖可用工具、执行边界、先读后改和计划只读约束。
2. 定义两种模式的精简提醒，保留当前模式最关键边界。
3. 实现无状态 `ReminderScheduler.detail_for()`，仅第 1、6 次返回 FULL。
4. 拒绝小于 1 的迭代号，避免静默产生错误频率。

**验证：** 运行 `uv run pytest -q tests/prompting/test_pipeline.py -k reminder`，期望 1 至 10 的序列为 `F C C C C F C C C C`，新 Run 从第 1 次重新开始。

## T8：实现脱敏环境与 Git 采集

**文件：** `src/mewcode/prompting/environment.py`、`tests/prompting/test_environment.py`
**依赖：** T4

**步骤：**

1. 异步采集脱敏项目根目录、平台、Shell、日期、时区和当前模式。
2. 用参数数组在固定工作目录查询 symbolic branch；detached HEAD 降级为带前缀的短提交标识。
3. 只用布尔值表达 dirty，不保留或输出改动文件列表。
4. 为 Git 子进程设置 1 秒超时和有界读取，超时或取消时终止并等待回收。
5. 在非 Git、Git 缺失、权限失败或 Shell 缺失时使用安全 unknown，且不暴露异常正文。

**验证：** 运行 `uv run pytest -q tests/prompting/test_environment.py`，期望普通仓库、dirty、detached、非仓库、超时和取消场景均通过且输出不含用户名或文件列表。

## T9：实现 Prompt Pipeline

**文件：** `src/mewcode/prompting/pipeline.py`、`src/mewcode/prompting/__init__.py`、`tests/prompting/test_pipeline.py`
**依赖：** T5、T6、T7、T8

**步骤：**

1. 注入稳定 Builder、环境采集器、提醒调度器和 Supplement Builder。
2. 每次请求异步刷新环境，并用 mode 与 iteration 选择提醒详细度。
3. 合并 `PromptOptions`，构造唯一 supplement，并冻结消息与工具顺序。
4. 返回不含任何供应商原生字段的 `PromptEnvelope`。
5. 验证日期、Git 和历史变化只改变动态部分，不改变稳定 system。

**验证：** 运行 `uv run pytest -q tests/prompting/test_pipeline.py`，期望完整指令顺序、稳定前缀、工具顺序和 Optional 插槽均符合 Plan。

## T10：双重强化六个工具描述

**文件：** `src/mewcode/tools/read_file.py`、`src/mewcode/tools/write_file.py`、`src/mewcode/tools/edit_file.py`、`src/mewcode/tools/find_files.py`、`src/mewcode/tools/search_code.py`、`src/mewcode/tools/execute_command.py`、`tests/tools/test_executor.py`
**依赖：** T5

**步骤：**

1. 更新六个 `ToolDefinition.description`，加入各自适用边界和优先级规则。
2. 在读、写、编辑工具中明确覆盖或编辑已有文件前先读取。
3. 在查找和搜索工具中明确优先于 Shell 的 `find`、`ls`、`grep`、`rg`。
4. 在命令工具中明确不替代专用读写改查工具。
5. 不修改工具名称、参数 Schema、执行逻辑、错误结构或注册顺序。

**验证：** 运行 `uv run pytest -q tests/tools/test_executor.py tests/tools/test_file_tools.py tests/tools/test_search_tools.py`，期望描述断言与原有工具行为全部通过。

## T11：迁移 Provider Envelope 接口与测试替身

**文件：** `src/mewcode/providers/base.py`、`tests/agent/test_runner.py`、`tests/test_session.py`、`tests/test_tui.py`
**依赖：** T4、T9

**步骤：**

1. 将 `LLMProvider.stream()` 改为只接收 `PromptEnvelope`。
2. 迁移 QueueProvider、BlockingProvider 等本地测试替身，直接保存请求信封供断言。
3. 删除旧 `stream(messages, tools)` 测试调用，不保留位置参数兼容层。
4. 为测试创建最小固定 Prompt Pipeline，避免测试依赖真实 Git 或系统时间。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py tests/test_session.py tests/test_tui.py --collect-only`，期望测试可收集且不存在旧 Provider 签名导致的导入错误。

## T12：实现 OpenAI 的提示和工具映射

**文件：** `src/mewcode/providers/openai.py`、`tests/providers/test_openai.py`
**依赖：** T11

**步骤：**

1. 将稳定 system、唯一动态 system reminder、真实历史按固定顺序映射为 Chat Completions messages。
2. 保持 User、Assistant、ToolResult 的既有协议转换和相邻历史语义。
3. 保持工具定义名称、顺序、描述和 Schema，不发送 `cache_control`。
4. 验证动态环境、日期和历史变化不改变首条稳定 system 内容。

**验证：** 运行 `uv run pytest -q tests/providers/test_openai.py -k "request or system or message or tool"`，期望两条 system 顺序正确、工具稳定且请求中没有 Anthropic 专属字段。

## T13：解析 OpenAI 缓存读取用量

**文件：** `src/mewcode/providers/openai.py`、`tests/providers/test_openai.py`
**依赖：** T3、T12

**步骤：**

1. 将 `prompt_tokens` 和 `completion_tokens` 保持映射为总输入、输出。
2. 将 `prompt_tokens_details.cached_tokens` 映射为缓存读取明细。
3. 将缓存创建保持未知，缺少 details 时缓存读取也保持未知。
4. 拒绝负数、布尔值或其他非法缓存字段，不进行总量推算。

**验证：** 运行 `uv run pytest -q tests/providers/test_openai.py -k "usage or cache"`，期望命中、零命中、缺失和非法字段四类流均得到明确结果。

## T14：实现 Anthropic 的 System 与工具缓存断点

**文件：** `src/mewcode/providers/anthropic.py`、`tests/providers/test_anthropic.py`
**依赖：** T11

**步骤：**

1. 把稳定 system 映射为带 ephemeral `cache_control` 的 text block。
2. 把动态 system reminder 映射为断点后的普通 text block。
3. 保持工具顺序，只给最后一个工具增加 ephemeral 缓存断点。
4. 保持空工具、Plan 三工具、Normal 六工具和 extended thinking 请求参数合法。
5. 确认动态 system block 不进入或改变历史角色合并。

**验证：** 运行 `uv run pytest -q tests/providers/test_anthropic.py -k "request or system or cache_control or thinking"`，期望稳定提示和最后工具带断点，动态内容与历史不带断点。

## T15：解析 Anthropic 缓存创建与读取用量

**文件：** `src/mewcode/providers/anthropic.py`、`tests/providers/test_anthropic.py`
**依赖：** T3、T14

**步骤：**

1. 分别读取普通输入、缓存创建、缓存读取和输出 Token，不使用默认零掩盖缺失字段。
2. 官方字段完整时将三个输入分类求和为统一总输入。
3. 兼容服务缺少缓存明细时保留明细未知，并沿用其普通输入总量。
4. 对每个已返回字段执行非负整数校验，非法值按无效流处理。
5. 保持 thinking、tool_use 和 stop reason 的原有解析行为。

**验证：** 运行 `uv run pytest -q tests/providers/test_anthropic.py -k "usage or cache or thinking"`，期望创建、读取、缺失、非法和 extended thinking 场景全部通过。

## T16：让 Collector 与事件层传播缓存明细

**文件：** `src/mewcode/agent/collector.py`、`src/mewcode/agent/events.py`、`tests/agent/test_collector.py`
**依赖：** T3、T13、T15

**步骤：**

1. Provider 未给 usage 时生成四字段均未知的 `TokenUsage`。
2. 保持单次 usage、重复 usage、缺失 DONE 等完整性校验。
3. 让 `UsageSnapshot.request` 与 `cumulative` 原样携带缓存创建和读取明细。
4. 不增加 AgentEvent 类型，不改变现有文本、thinking 和工具增量事件。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py`，期望四字段用量、未知传播、无效流和取消测试全部通过。

## T17：在 Runner 每次迭代构造 Envelope

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T9、T11、T16

**步骤：**

1. 为 `AgentRunner` 注入 `PromptPipeline`，为 `AgentRunRequest` 增加冻结的 `PromptOptions`。
2. 每轮按当前模式选择稳定顺序的工具定义，并构造包含 pending 用户消息的候选历史。
3. 使用项目根目录、mode 和 1-based iteration 调用 Pipeline，然后调用 `provider.stream(envelope)`。
4. 删除 `inspect.signature()` 和旧 Provider 兼容分支。
5. 保持工具检查点、迭代上限、未知工具和最终文字停止行为不变。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "envelope or loop or iteration or unknown"`，期望每轮请求都携带正确模式、工具集合和提醒序号。

## T18：实现提示构建取消与历史隔离

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T17

**步骤：**

1. 将 Pipeline 构建放入独立异步任务，并与 `AgentRunControl` 取消信号竞争。
2. 取消先发生时取消并回收 Pipeline，不调用 Provider。
3. 强制外层任务取消时继续传播 `CancelledError`。
4. 断言 stable system、system reminder、Options 和缓存元数据从不提交给 `HistorySink`。
5. 保持流中取消和工具执行取消的既有检查点语义。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "prompt_cancel or history or cancel"`，期望无 pending task 警告、取消时请求数正确且历史只含真实消息和工具结果。

## T19：迁移 Session 的 Plan/Do 与 PromptOptions

**文件：** `src/mewcode/session.py`、`tests/test_session.py`
**依赖：** T17

**步骤：**

1. 删除 `_plan_instruction()`、`_plan_followup()` 和 `_do_instruction()`。
2. `/plan <任务>` 和 Plan 中补充消息只把用户原文作为 `UserMessage`；`/do` 使用真实 `/do` 文本。
3. 保持 Plan 只读工具、空计划命令、无计划 `/do`、计划就绪和重置语义。
4. 在 Session 保存 `PromptOptions`，提供无活动 Run 时原子更新的程序化入口。
5. 创建每个 `AgentRunRequest` 时复制 Options；更新失败或活动 Run 时不改变原值。

**验证：** 运行 `uv run pytest -q tests/test_session.py`，期望历史中没有伪系统指令、Plan/Do 状态不回归且 Options 更新边界正确。

## T20：在 CLI 组装完整 Prompt Pipeline

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`
**依赖：** T8、T9、T17、T19

**步骤：**

1. 在项目根目录确定后创建 StablePromptBuilder、EnvironmentCollector、ReminderScheduler 和 PromptPipeline。
2. 将 Pipeline 注入 AgentRunner，Session 默认使用空 `PromptOptions`。
3. 保持 Provider 创建与关闭、命令确认延迟绑定、TUI 鼠标启动和异常处理不变。
4. 不增加 CLI 参数、YAML 字段或运行依赖。

**验证：** 运行 `uv run pytest -q tests/test_cli.py tests/test_config.py`，期望原六字段 profile 继续可用，应用组装包含 Prompt Pipeline 且 Provider 仍可靠关闭。

## T21：补齐 Prompt 与 Provider 集成覆盖

**文件：** `tests/prompting/test_builder.py`、`tests/prompting/test_environment.py`、`tests/prompting/test_pipeline.py`、`tests/providers/test_openai.py`、`tests/providers/test_anthropic.py`
**依赖：** T12、T13、T14、T15、T20

**步骤：**

1. 增加相同输入字节一致、完整指令顺序和可选模块空值测试。
2. 增加 Normal/Plan 工具集合各自稳定、动态变化不污染稳定前缀的测试。
3. 增加两种 Provider 的 system 位置、缓存边界和缓存字段缺失测试。
4. 增加非 Git、detached、长 Unicode 内容和 XML 伪闭合标签边界测试。

**验证：** 运行 `uv run pytest -q tests/prompting tests/providers`，期望提示与协议映射测试全部通过且不访问网络。

## T22：补齐 Agent、Session、CLI 与 TUI 回归覆盖

**文件：** `tests/agent/test_runner.py`、`tests/agent/test_collector.py`、`tests/test_session.py`、`tests/test_cli.py`、`tests/test_tui.py`
**依赖：** T16、T18、T19、T20

**步骤：**

1. 覆盖 10 次请求的第 1/6 次完整提醒和新用户提交后重置。
2. 覆盖 Plan/Do 的真实用户正文、三/六工具边界、无成功计划不调用模型。
3. 覆盖多工具循环、thinking、Provider 错误、无效流、提示构建取消和工具取消。
4. 断言缓存明细可从事件读取，但不进入 TUI Token 状态、对话记录或静态 transcript。

**验证：** 运行 `uv run pytest -q tests/agent tests/test_session.py tests/test_cli.py tests/test_tui.py`，期望 Agent Loop、Plan/Do、取消和 UI 行为全部通过。

## T23：扩展确定性 SSE 端到端服务

**文件：** `tests/e2e/mock_llm_server.py`
**依赖：** T12、T14、T19

**步骤：**

1. 从真实用户历史而不是 system reminder 识别任务和工具步骤。
2. 分别校验 OpenAI 双 system 消息与 Anthropic system blocks 的标签和顺序。
3. 记录工具名称、顺序与 `cache_control`，支持 Plan/Do 新消息语义。
4. 为 OpenAI 和 Anthropic 返回确定性的缓存创建、读取或 cached token 字段。
5. 保持现有多步工具、命令确认、取消和错误流场景可用。

**验证：** 运行 `uv run pytest -q tests/providers tests/test_session.py`，并以 `uv run python tests/e2e/mock_llm_server.py --help` 检查服务入口，期望无旧伪用户提示依赖。

## T24：实现有界真实缓存验证脚本

**文件：** `scripts/verify_prompt_cache.py`、`tests/test_cli.py`
**依赖：** T13、T15、T20

**步骤：**

1. 接收现有配置路径、profile 名和固定请求次数，不新增 YAML 字段。
2. 使用生产 Prompt Pipeline 和稳定工具定义重复同一短请求，不添加缓存 padding。
3. Anthropic 输出每次缓存创建、读取和总输入；OpenAI 输出 cached token 或 unknown。
4. 设置明确请求次数上限，失败即停止，不开放式重试。
5. 输出只包含 Provider、模型、请求序号和 Token 指标，不打印 API Key、提示正文或完整认证错误。

**验证：** 运行 `uv run pytest -q tests/test_cli.py -k prompt_cache` 和 `uv run python scripts/verify_prompt_cache.py --help`，期望请求次数严格有界、缺失字段显示 `unknown` 且输出不含配置密钥。

## T25：执行自动化质量检查

**文件：** 全部实现与测试文件
**依赖：** T21、T22、T23、T24

**步骤：**

1. 运行 Ruff 检查并修复本章引入的问题。
2. 运行完整 pytest，修复所有新旧回归。
3. 构建 wheel，确认新增 prompting 包被打包。
4. 检查代码和测试输出中没有硬编码 API Key、完整用户主目录或动态提示泄漏。

**验证：** 依次运行 `uv run ruff check .`、`uv run pytest -q`、`uv build`，期望全部退出码为 0。

## T26：使用 tmux 完成确定性端到端验收

**文件：** `checklist.md`
**依赖：** T23、T25，以及已批准的 `checklist.md`

**步骤：**

1. 在 tmux 中启动确定性 SSE 服务和真实 MewCode TUI。
2. 输入普通编码任务，观察专用工具选择、先读后改、多轮工具循环、流式文字和最终答复。
3. 输入 `/plan` 任务并在计划完成后输入 `/do`，观察三工具只读边界、模式切换和六工具执行。
4. 验证鼠标滚动、Alt+Enter、取消和命令确认等既有交互没有回归。
5. 保存脱敏的 pane 输出和生成文件证据，逐项写入 checklist 实际结果。

**验证：** 运行 `tmux capture-pane` 查看实际输出，并核对普通任务与 Plan/Do 产生的文件和工具记录；没有实际证据的条目不得标记通过。

## T27：执行真实 Provider 缓存验证

**文件：** `checklist.md`
**依赖：** T24、T25

**步骤：**

1. 使用已配置的真实 Anthropic profile 运行有界重复请求。
2. 记录模型、请求次数、首次缓存创建和后续缓存读取的脱敏数值证据。
3. 使用真实 OpenAI profile 做同类有界验证；有字段则记录数值，缺失则明确记为 unknown 或服务不支持。
4. 验证日志不含 API Key、完整提示正文和未脱敏认证信息。

**验证：** Anthropic 证据必须同时出现实际 cache creation 与 cache read；OpenAI 必须有实际 cached token 或明确 unknown 记录，且两者请求次数不超过脚本上限。

## T28：执行新提示人工对比

**文件：** `docs/evals/003-system-prompt-scenarios.md`、`checklist.md`
**依赖：** T25、T27

**步骤：**

1. 用与 T2 相同的 Provider、模型、任务文本和全新夹具副本运行六个场景。
2. 逐项记录实际工具选择、先读后改、Plan 只读、安全边界、代码风格和输出简洁度。
3. 与旧提示基线并排描述差异，不生成分数，不把主观判断写成自动结论。
4. 对任何失败或不确定项保留原始状态，并在 checklist 记录后续处理。

**验证：** 场景文档的“新提示结果”和“对比结论”六行均有实际证据，运行元数据与 T2 一致且无敏感信息。

## T29：生成 003 功能文档并完成验收记录

**文件：** `docs/features/003-structured-system-prompt.md`、`docs/features/003-claude-code-system-prompt.md`、`docs/features/README.md`、`checklist.md`
**依赖：** T26、T27、T28

**步骤：**

1. 总结 MewCode 的七模块提示、动态 reminder、Provider 缓存边界、用量事件和 Plan/Do 迁移。
2. 调研并记录 Claude Code 在系统提示、缓存、环境注入、项目指令和模式约束方面的对应实现；区分公开事实与推断并注明核对日期。
3. 在功能目录中登记编号 003 的两份文档和人工场景文档。
4. 将实现提交、自动化命令、tmux pane、真实缓存指标和人工对比结果逐项写入 checklist。
5. 对照 spec 的 AC1 至 AC22 复核覆盖，未通过项保持未勾选并记录实际原因。

**验证：** 运行 `rg -n "003|结构化系统提示|Claude Code" docs/features/README.md docs/features/003-*.md` 并逐项核对 `checklist.md`，期望所有结论均有实际证据可追溯。

## 执行顺序

```text
T1 → T2 → T3 → T4 ─┬→ T5 ─┬→ T10
                    ├→ T6  │
                    ├→ T7  ├→ T9 → T11 ─┬→ T12 → T13 ─┐
                    └→ T8 ─┘             └→ T14 → T15 ─┤
                                                       ├→ T16 → T17 → T18 ─┐
                                                       │                    ├→ T22 ─┐
                                                       └────────────────────┘       │
T17 → T19 → T20 → T21 ─────────────────────────────────────────────────────────────┤
T12 + T14 + T19 → T23 ──────────────────────────────────────────────────────────────┤
T13 + T15 + T20 → T24 ──────────────────────────────────────────────────────────────┤
                                                                                    ▼
                                                                                   T25
                                                                                ┌───┴───┐
                                                                                ▼       ▼
                                                                               T26     T27
                                                                                        ▼
                                                                               T2 ───→ T28
                                                                                └───┬───┘
                                                                                    ▼
                                                                                   T29
```

可并行边界：T5-T8 在 T4 后可分别实现；T12-T15 可按 Provider 分两组推进；T21-T24 在各自依赖满足后可交错执行。T2 必须在任何实现修改前完成，T26-T29 必须在自动化质量检查通过后执行。

## 自检

- Plan 中的 Prompt 模型、七模块、Builder、Reminder、Environment、Pipeline、Provider、Agent、Session、CLI、工具描述、验证脚本、人工评估和 003 文档均有对应任务。
- 每个任务都列出具体文件、依赖、步骤和可运行或可观察的验证方式。
- 依赖链无循环；旧提示基线明确位于实现前，真实缓存、tmux 和文档明确位于实现后。
- 函数名、类型名、长度边界、缓存语义和 Plan/Do 行为与已批准的 `plan.md` 一致。
- 本任务清单不修改 YAML 模型、TUI 展示、工具执行契约或其他“不做的事”。
