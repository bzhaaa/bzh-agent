# MewCode Agent Loop Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/agent/__init__.py` | 导出 Agent 公共 API |
| 新建 | `src/mewcode/agent/control.py` | 显式取消控制 |
| 新建 | `src/mewcode/agent/events.py` | Agent 模式、事件、进度和停止原因 |
| 新建 | `src/mewcode/agent/collector.py` | Provider 流双路收集 |
| 新建 | `src/mewcode/agent/scheduler.py` | 多工具分段、并发和取消补齐 |
| 新建 | `src/mewcode/agent/runner.py` | ReAct 循环和历史检查点 |
| 修改 | `src/mewcode/models.py` | ProviderEvent、TokenUsage 和会话消息 |
| 修改 | `src/mewcode/providers/base.py` | ProviderEvent 流契约 |
| 修改 | `src/mewcode/providers/openai.py` | OpenAI usage 与多工具流 |
| 修改 | `src/mewcode/providers/anthropic.py` | Anthropic usage 与多工具流 |
| 修改 | `src/mewcode/tools/base.py` | 工具执行策略 |
| 修改 | `src/mewcode/tools/registry.py` | 工具策略校验和只读子集 |
| 修改 | `src/mewcode/tools/read_file.py` | 声明只读并发策略 |
| 修改 | `src/mewcode/tools/find_files.py` | 声明只读并发策略 |
| 修改 | `src/mewcode/tools/search_code.py` | 声明只读并发策略 |
| 修改 | `src/mewcode/tools/write_file.py` | 声明副作用串行策略 |
| 修改 | `src/mewcode/tools/edit_file.py` | 声明副作用串行策略 |
| 修改 | `src/mewcode/tools/execute_command.py` | 声明副作用串行策略并保持取消清理 |
| 修改 | `src/mewcode/tools/__init__.py` | 导出策略和调度所需类型 |
| 修改 | `src/mewcode/session.py` | Plan Mode、历史状态和 Runner 外观 |
| 修改 | `src/mewcode/cli.py` | Normal/Plan 环境组装 |
| 修改 | `src/mewcode/tui.py` | AgentEvent、多迭代记录、进度和取消 |
| 新建 | `tests/agent/test_collector.py` | 事件、用量、收集和取消测试 |
| 新建 | `tests/agent/test_scheduler.py` | 分段、并发、顺序和取消测试 |
| 新建 | `tests/agent/test_runner.py` | 循环、停止和检查点测试 |
| 修改 | `tests/tools/test_executor.py` | 策略、子集和工具兼容测试 |
| 修改 | `tests/providers/test_openai.py` | OpenAI usage、多调用及历史测试 |
| 修改 | `tests/providers/test_anthropic.py` | Anthropic usage、多调用及历史测试 |
| 修改 | `tests/test_session.py` | Plan/Do、历史和取消测试 |
| 修改 | `tests/test_tui.py` | 多迭代、状态、取消和 Modal 测试 |
| 修改 | `tests/test_cli.py` | Agent 运行环境组装与关闭测试 |
| 修改 | `tests/e2e/mock_llm_server.py` | 多步循环、Plan/Do、usage 和停止假流 |
| 修改 | `checklist.md` | Agent Loop 验收清单与实际证据 |
| 新建 | `docs/features/002-agent-loop.md` | MewCode Agent Loop 功能总结 |
| 新建 | `docs/features/002-claude-code-agent-loop.md` | Claude Code 对应实现对照 |
| 修改 | `docs/features/README.md` | 登记 002 双文档 |

## T1：定义 Provider 与 Agent 事件模型

**文件：** `src/mewcode/models.py`、`src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/agent/test_collector.py`
**依赖：** 无

**步骤：**

1. 定义 `TokenUsage`，实现总量计算和未知值传播的累计规则。
2. 定义 `ProviderEventKind` 与 `ProviderEvent`。
3. 定义 `AgentMode`、`AgentEventKind`、`AgentStopReason`、`AgentProgress`、`UsageSnapshot` 和 `AgentEvent`。
4. 为迁移期保留最小兼容别名，避免尚未修改的 Provider 和 TUI 同时失效。
5. 从 Agent 包入口导出公共类型。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py -k "usage or event"`，期望已知总量正确、任一未知项向累计传播，并能构造所有事件种类。

## T2：实现显式取消控制

**文件：** `src/mewcode/agent/control.py`、`tests/agent/test_collector.py`
**依赖：** T1

**步骤：**

1. 使用单次置位的异步信号实现 `AgentRunControl`。
2. 实现同步查询、幂等取消和异步等待取消。
3. 增加工作完成与取消信号竞争的辅助逻辑，确保未胜出的等待任务被回收。
4. 覆盖取消先发生、工作先完成和重复取消。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py -k control`，期望无 pending task 警告且三种竞争结果稳定。

## T3：为工具增加执行策略和只读子集

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/registry.py`、六个工具模块、`src/mewcode/tools/__init__.py`、`tests/tools/test_executor.py`
**依赖：** 无

**步骤：**

1. 定义 `ToolExecutionPolicy` 并加入 Tool Protocol。
2. 三个读类工具声明 `PARALLEL_READ`。
3. 三个副作用工具声明 `SERIAL_SIDE_EFFECT`。
4. 注册时校验策略，拒绝缺少或非法策略的工具。
5. 实现 `ToolRegistry.subset()`，保持原注册顺序并拒绝不存在的配置名称。
6. 验证默认注册中心与只读子集包含预期工具。

**验证：** 运行 `uv run pytest -q tests/tools/test_executor.py -k "policy or subset or registry"`，期望六个策略正确且只读子集恰含三个工具。

## T4：实现流式双路收集成功路径

**文件：** `src/mewcode/agent/collector.py`、`tests/agent/test_collector.py`
**依赖：** T1、T2

**步骤：**

1. 实现逐个消费 Provider 事件的收集器。
2. thinking 与文本到达时立即转成 Agent 增量事件。
3. 同时累计完整文本、工具调用和本次 Token 用量。
4. 仅在唯一 `DONE` 后开放 `CollectedResponse`。
5. Provider 未给 usage 时生成输入、输出均未知的结果。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py -k "stream or complete"`，期望增量在流结束前可见，最终响应内容和调用顺序完整。

## T5：实现收集器无效流与取消

**文件：** `src/mewcode/agent/collector.py`、`tests/agent/test_collector.py`
**依赖：** T4

**步骤：**

1. 拒绝缺少 `DONE`、重复 `DONE`、重复 usage 和结束后的额外事件。
2. 拒绝缺少必要载荷的文本、工具或用量事件。
3. 让 Provider 下一事件读取与取消信号竞争。
4. 取消时关闭异步流，取消未完成读取并等待清理。
5. 强制外层任务取消时继续向上传播 `CancelledError`。

**验证：** 运行 `uv run pytest -q tests/agent/test_collector.py`，期望所有损坏流被拒绝且取消测试无未关闭异步生成器。

## T6：迁移 OpenAI Provider 并解析 Token 用量

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/providers/openai.py`、`tests/providers/test_openai.py`
**依赖：** T1

**步骤：**

1. Provider Protocol 改为产生 `ProviderEvent`。
2. OpenAI 流请求启用 usage chunk。
3. 允许无 choices 的最终 usage chunk，同时保留 finish reason 校验。
4. 把 `prompt_tokens`、`completion_tokens` 转成 `TokenUsage`。
5. 保持多工具参数按 index 拼接并在正常结束后按 index 输出。
6. 覆盖有 usage、无 usage、多个工具和异常流。

**验证：** 运行 `uv run pytest -q tests/providers/test_openai.py`，期望纯文本、工具、usage 与现有错误映射全部通过。

## T7：迁移 Anthropic Provider 并解析 Token 用量

**文件：** `src/mewcode/providers/anthropic.py`、`tests/providers/test_anthropic.py`
**依赖：** T1

**步骤：**

1. 将现有事件输出迁移为 `ProviderEvent`。
2. 从 message start 收集普通输入、cache creation 和 cache read Token。
3. 从 message delta 收集输出 Token。
4. 在正常结束前产生一次归一化 usage。
5. 保持 thinking、多个 tool block、JSON 碎片和 stop reason 校验。
6. 覆盖 usage 字段部分缺失及多个工具块。

**验证：** 运行 `uv run pytest -q tests/providers/test_anthropic.py`，期望 thinking、工具、usage 和错误映射全部通过。

## T8：实现工具调用分段

**文件：** `src/mewcode/agent/scheduler.py`、`tests/agent/test_scheduler.py`
**依赖：** T2、T3

**步骤：**

1. 按当前注册中心查询每个调用的工具与策略。
2. 把相邻只读调用合并为并发段。
3. 把副作用调用分别划为单调用串行段。
4. 把未知工具作为立即失败的顺序边界。
5. 保留调用 ID 和原索引供结果恢复。

**验证：** 运行 `uv run pytest -q tests/agent/test_scheduler.py -k segment`，期望示例“读、读、写、读、搜、改”得到四个顺序正确的执行段。

## T9：实现并发执行、错误隔离和结果排序

**文件：** `src/mewcode/agent/scheduler.py`、`tests/agent/test_scheduler.py`
**依赖：** T8

**步骤：**

1. 并发启动同一读段中的执行器调用。
2. 副作用段等待前段结束后单独执行。
3. 普通失败保留为 ToolResult，不取消同段其他工具。
4. 每段结束时按原索引返回结果。
5. 使用可控 Event 和时间戳测试真实重叠与严格串行。

**验证：** 运行 `uv run pytest -q tests/agent/test_scheduler.py -k "parallel or serial or order or failure"`，期望读任务确实重叠、副作用不重叠、结果顺序稳定。

## T10：实现调度取消和结果补齐

**文件：** `src/mewcode/agent/scheduler.py`、`tests/agent/test_scheduler.py`
**依赖：** T9

**步骤：**

1. 执行段与取消信号并行等待。
2. 取消时回收当前段所有未完成任务。
3. 保留取消前已经返回的真实结果。
4. 为当前未完成和后续未启动调用生成 `CANCELLED` 结果。
5. 验证命令执行器收到任务取消并完成资源清理。

**验证：** 运行 `uv run pytest -q tests/agent/test_scheduler.py -k cancel` 和 `uv run pytest -q tests/tools/test_execute_command.py -k cancel`，期望每个调用都有结果且无残留任务或进程。

## T11：实现 Runner 纯文本快速路径

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T4、T6、T7、T9

**步骤：**

1. 定义 `HistorySink`、`AgentRunRequest` 和默认 10 次上限。
2. 发出 iteration、requesting 和文本事件。
3. 首次响应不含工具时提交用户与助手消息。
4. 产生唯一 `STOPPED(COMPLETED)`。
5. 拒绝正常结束但没有文字和工具的响应。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "text or empty"`，期望纯文本只请求一次并提交两条历史。

## T12：实现多迭代工具循环与检查点

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T10、T11

**步骤：**

1. 把完整工具响应交给当前模式调度器。
2. 转发工具调用、执行进度和结果事件。
3. 首次工具批次提交用户、助手调用和全部结果。
4. 后续批次只追加助手调用与结果。
5. 使用新历史继续请求，直到最终文字。
6. 保存工具调用前的普通文本但不误判为最终答复。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "loop or checkpoint or prefixed_text"`，期望三步工具任务自动结束且每次 Provider 请求历史合法。

## T13：实现迭代与未知工具停止

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T12

**步骤：**

1. 每次 Provider 请求递增一次迭代计数。
2. 第 10 次工具结果提交后产生迭代上限停止，不发起第 11 次请求。
3. 根据当前模式注册中心判断一次响应是否纯未知。
4. 第一次纯未知回灌错误并继续，第二次纯未知提交后停止。
5. 同批出现任一有效工具时清零连续计数。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "iteration_limit or unknown"`，期望请求数和停止原因精确。

## T14：实现 Runner 错误与取消停止

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T5、T10、T12

**步骤：**

1. 把 ProviderError 转成脱敏 `PROVIDER_ERROR` 停止事件。
2. 把收集完整性错误转成 `INVALID_STREAM`。
3. 模型流取消时丢弃当前响应并保留旧检查点。
4. 工具执行取消时提交补齐后的完整工具检查点。
5. 保证每条停止路径只产生一个最终事件且不启动新请求。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "error or cancel or invalid"`，期望历史、事件和请求数符合停止表。

## T15：实现 Token 累计与结构化进度

**文件：** `src/mewcode/agent/runner.py`、`tests/agent/test_runner.py`
**依赖：** T12

**步骤：**

1. 每次 Provider 请求结束后产生 request/cumulative usage。
2. 对缺失 usage 产生未知值并传播到累计结果。
3. 在请求、工具执行和检查点提交阶段产生结构化进度。
4. Provider 失败时仍产生本次未知或已知用量事件，再产生停止事件。

**验证：** 运行 `uv run pytest -q tests/agent/test_runner.py -k "usage or progress"`，期望事件顺序和累计值与 Plan 一致。

## T16：实现 Session 的 Plan/Do 命令状态

**文件：** `src/mewcode/session.py`、`tests/test_session.py`
**依赖：** T13、T14、T15

**步骤：**

1. 将 ChatSession 改为历史与模式外观层并实现 HistorySink。
2. 解析非空 `/plan <任务>`，切换 Plan、清除旧计划状态并包装只读规划指令。
3. Plan 中普通输入包装为计划补充指令并保持只读模式。
4. 成功完成 Plan 运行后设置计划就绪。
5. `/do` 消费计划状态、切换 Normal 并包装执行指令。
6. 空 `/plan` 和无计划 `/do` 产生本地停止事件且不请求 Provider。

**验证：** 运行 `uv run pytest -q tests/test_session.py -k "plan or do or mode"`，期望工具定义范围、模式事件、模型消息和请求次数正确。

## T17：实现 Session 历史延续与取消入口

**文件：** `src/mewcode/session.py`、`tests/test_session.py`
**依赖：** T16

**步骤：**

1. 为每次运行创建并登记独立 AgentRunControl。
2. `cancel_current()` 幂等通知当前运行。
3. Runner 结束后清除当前控制，不影响下一轮。
4. 验证流错误和取消后旧检查点保留，下一条消息能继续。
5. 验证同时只允许一个活动运行。

**验证：** 运行 `uv run pytest -q tests/test_session.py -k "history or cancel or active"`，期望中途停止后历史可重放且下一轮成功。

## T18：组装 Normal 与 Plan 运行环境

**文件：** `src/mewcode/cli.py`、`src/mewcode/agent/__init__.py`、`tests/test_cli.py`
**依赖：** T3、T17

**步骤：**

1. 从默认注册中心创建全工具和只读子注册中心。
2. 分别创建执行器与 ToolScheduler。
3. 用两个运行环境、Provider 和 ToolContext 创建 AgentRunner。
4. 用 Runner 创建 ChatSession 并保留命令确认延迟绑定。
5. 验证正常、异常和取消退出时 Provider 只关闭一次。

**验证：** 运行 `uv run pytest -q tests/test_cli.py` 和 `uv run mewcode --help`，期望配置字段、帮助输出和资源关闭行为不变。

## T19：重构 TUI 的多迭代记录

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T17

**步骤：**

1. 把事件消费从 Provider StreamEvent 切换为 AgentEvent。
2. 每次迭代首次 thinking/text 时创建独立助手记录。
3. 工具调用按事件时序追加，工具结果按调用 ID 更新。
4. 允许纯工具迭代不生成空助手卡片。
5. 最终文字、工具前文字和后续迭代保持真实显示顺序。

**验证：** 运行 `uv run pytest -q tests/test_tui.py -k "iteration or tool_events or streams"`，期望 transcript 顺序为“用户、说明、工具、调整、最终答复”。

## T20：展示模式、进度、Token 和停止原因

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T19

**步骤：**

1. 根据 MODE_CHANGED 显示 Normal 或 Plan。
2. 根据 iteration/progress 显示当前 1-10 轮和工具完成数。
3. 根据 UsageSnapshot 显示累计输入、输出和总 Token，未知值显示明确占位。
4. 为完成、上限、未知工具、Provider 错误、无效流、无计划和无效命令映射稳定中文状态。
5. 保证状态文本有界且静态 transcript 保留必要停止信息。

**验证：** 运行 `uv run pytest -q tests/test_tui.py -k "mode or progress or usage or stopped"`，期望底部状态和 transcript 与事件一致。

## T21：接入显式取消并保持命令确认

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T10、T17、T20

**步骤：**

1. 生成中 `Ctrl+C` 先关闭活动命令 Modal。
2. 调用 `ChatSession.cancel_current()`，让正常 Worker 消费 cancelled 停止事件。
3. 应用退出或 Worker 异常时保留强制 cancel 兜底。
4. 更新所有 pending 工具记录为真实结果或取消状态。
5. 验证草稿、焦点、滚动和再次提交能力保持。

**验证：** 运行 `uv run pytest -q tests/test_tui.py -k "cancel or approval or draft"`，期望取消路径无 worker error，命令确认仍逐次生效。

## T22：验证双 Provider 多迭代历史重放

**文件：** `tests/providers/test_openai.py`、`tests/providers/test_anthropic.py`、`tests/test_session.py`
**依赖：** T7、T17

**步骤：**

1. 构造含文本、同批多个工具、多个结果和后续最终答复的领域历史。
2. 验证 OpenAI 转成 assistant tool_calls 与逐个 tool 消息。
3. 验证 Anthropic 转成 tool_use 与合并后的 tool_result user block。
4. 验证取消或流错误后留下的检查点仍能被两种 Provider 转换。
5. 验证 thinking 不进入后续历史。

**验证：** 运行 `uv run pytest -q tests/providers tests/test_session.py`，期望双协议载荷顺序合法且共享领域场景一致。

## T23：清理旧单工具状态机与兼容别名

**文件：** `src/mewcode/models.py`、`src/mewcode/session.py`、`src/mewcode/tui.py`、相关测试
**依赖：** T18、T19、T20、T21、T22

**步骤：**

1. 删除 `LIMIT_REACHED` 和旧两阶段会话分支。
2. 删除迁移期 StreamEvent 兼容别名和旧测试假事件。
3. 搜索所有旧事件与“每回合一个工具”文案并迁移。
4. 确认生产代码只有 Provider 消费 ProviderEvent，TUI 只消费 AgentEvent。
5. 运行导入和类型路径检查，清理未使用符号。

**验证：** 运行 `rg "StreamEvent|LIMIT_REACHED|每个用户回合只允许一个工具" src tests`，期望无旧实现引用；随后运行完整测试。

## T24：扩展本地 SSE 端到端服务

**文件：** `tests/e2e/mock_llm_server.py`
**依赖：** T22

**步骤：**

1. 让服务按对话请求和工具结果确定性选择下一步。
2. 增加至少三步的读、搜、写/改和最终答复链。
3. 增加同批多个读工具、混合副作用工具和 usage 返回。
4. 增加 Plan 只读调查与 `/do` 执行分支。
5. 增加连续未知工具、10 次上限、流错误和长命令取消场景。
6. 记录每次请求的协议、工具定义、消息和时间，供验收核对并发与请求数。

**验证：** 启动本地服务并用两种官方 SDK 各请求一次多步场景，期望 SSE 可解析、usage 可见且请求日志完整。

## T25：执行完整自动化和静态检查

**文件：** 全部实现与测试文件
**依赖：** T23、T24

**步骤：**

1. 运行完整 pytest，修复失败和异步资源警告。
2. 运行 Ruff lint 与格式检查。
3. 运行 compileall 与 `git diff --check`。
4. 检查测试输出无 pending task、未关闭流、worker error 或残留子进程。
5. 核对 YAML 配置文件未新增字段。

**验证：** `uv run pytest -q`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run python -m compileall -q src tests` 和 `git diff --check` 全部状态码为 0。

## T26：执行 tmux 端到端场景

**文件：** `checklist.md`、临时 E2E 项目与日志
**依赖：** T24、T25、已批准 checklist.md

**步骤：**

1. 在 tmux 中分别使用 OpenAI 与 Anthropic 本地 SSE profile 启动 MewCode。
2. 输入真实自然语言三步任务，观察无需催促完成工具循环和最终答复。
3. 验证同批读工具并发、副作用工具串行及命令批准/拒绝。
4. 运行 `/plan <任务>`，确认只读计划，再输入 `/do` 验证执行。
5. 分别触发取消、连续未知工具、10 次上限和流错误。
6. 对照 checklist 逐项记录 pane 输出、请求日志、文件哈希和进程状态。

**验证：** checklist 中每个端到端条目都有实际证据；未通过项先修复并重跑，不以代码检查代替。

## T27：生成 MewCode 功能总结

**文件：** `docs/features/002-agent-loop.md`
**依赖：** T25、T26

**步骤：**

1. 记录本章用户可见行为、Agent 循环、Plan Mode 和停止条件。
2. 记录事件、Collector、Scheduler、Runner 与 Session 架构。
3. 写入实际自动化命令输出和 tmux 证据。
4. 记录配置不变、命令确认延续和当前限制。
5. 写入对应实现提交哈希。

**验证：** 检查文档没有预期冒充实际结果，所有测试数字、提交和证据可从仓库或 checklist 追溯。

## T28：生成 Claude Code Agent Loop 对照

**文件：** `docs/features/002-claude-code-agent-loop.md`、`docs/features/README.md`
**依赖：** T27

**步骤：**

1. 核对 Anthropic 官方 Claude Code 工作机制、工具、权限、Plan 和会话资料。
2. 按“官方确认 / 合理推断 / 未公开”区分公开行为与私有实现。
3. 对照循环深度、多工具、取消、上下文、权限和 Plan Mode。
4. 不把 Agent SDK 结构写成 Claude Code CLI 私有源码事实。
5. 在 README 中登记 002 双文档。

**验证：** 本地 Markdown 链接检查和 `git diff --check` 通过；所有外部资料来自 Anthropic 官方页面并标注核对日期。

## 提交检查点

进入开发阶段后按以下逻辑组提交，仅包含对应任务文件，不夹带无关改动：

1. **文档基线：** 已批准的 spec、plan、task、checklist，以及此前已完成的 000/001 双文档约定。
2. **事件与 Provider：** T1-T7。
3. **调度与 Agent Loop：** T8-T15。
4. **Session、CLI 与 TUI：** T16-T23。
5. **E2E 与回归：** T24-T26。
6. **功能总结：** T27-T28。

## 执行顺序

```text
T1 → T2 → T4 → T5 ─┐
 │                   ├→ T11 → T12 → T13 → T14 → T15 ─┐
 ├→ T6 ──────────────┤                                 │
 └→ T7 ──────────────┘                                 ├→ T16 → T17 → T18
                                                      │                │
T3 → T8 → T9 → T10 ──────────────────────────────────┘                │
                                                                       ├→ T19 → T20 → T21
                                                                       └→ T22
T18-T22 → T23 → T24 → T25 → T26 → T27 → T28
```

T6 与 T7 可并行；T4/T5 与 T3 可并行；T19-T21 在 T17 后顺序执行，T22 可与 T19-T21 并行。
