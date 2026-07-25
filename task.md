# MewCode 工具系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/models.py` | 结构化会话消息、工具调用和统一流事件 |
| 修改 | `src/mewcode/errors.py` | 保留 Provider 错误并接入工具层错误边界 |
| 修改 | `src/mewcode/providers/base.py` | 扩展 Provider 工具定义参数 |
| 修改 | `src/mewcode/providers/openai.py` | OpenAI 工具定义、历史和流式调用适配 |
| 修改 | `src/mewcode/providers/anthropic.py` | Anthropic 工具定义、历史和流式调用适配 |
| 修改 | `src/mewcode/session.py` | 单工具、两阶段 Provider 请求和事务历史 |
| 修改 | `src/mewcode/tui.py` | 工具消息、命令确认 Modal、取消和静态记录 |
| 修改 | `src/mewcode/cli.py` | 固定项目根目录并组装工具系统 |
| 新建 | `src/mewcode/tools/__init__.py` | 导出工具公共 API 和默认工厂 |
| 新建 | `src/mewcode/tools/base.py` | Tool 协议、定义、上下文、结果和批准请求 |
| 新建 | `src/mewcode/tools/errors.py` | 工具领域错误与稳定错误码 |
| 新建 | `src/mewcode/tools/paths.py` | 项目路径安全、文件枚举和原子写入 |
| 新建 | `src/mewcode/tools/registry.py` | 注册、查找和默认六工具集合 |
| 新建 | `src/mewcode/tools/executor.py` | JSON/Schema 校验、批准、超时和错误转换 |
| 新建 | `src/mewcode/tools/read_file.py` | UTF-8 文本按行读取 |
| 新建 | `src/mewcode/tools/write_file.py` | 创建与原子覆盖文件 |
| 新建 | `src/mewcode/tools/edit_file.py` | 唯一原文匹配替换 |
| 新建 | `src/mewcode/tools/execute_command.py` | 异步 Shell 与进程组清理 |
| 新建 | `src/mewcode/tools/find_files.py` | 安全 glob 文件查找 |
| 新建 | `src/mewcode/tools/search_code.py` | 文本/正则内容搜索 |
| 新建 | `tests/tools/test_paths.py` | 路径越界、符号链接和原子写入测试 |
| 新建 | `tests/tools/test_file_tools.py` | 读、写、改文件测试 |
| 新建 | `tests/tools/test_search_tools.py` | 查找与搜索测试 |
| 新建 | `tests/tools/test_execute_command.py` | 命令结果、超时、取消和进程回收测试 |
| 新建 | `tests/tools/test_executor.py` | Registry、参数校验、批准和错误转换测试 |
| 修改 | `tests/providers/test_openai.py` | OpenAI 工具协议与流碎片测试 |
| 修改 | `tests/providers/test_anthropic.py` | Anthropic 工具协议与流碎片测试 |
| 修改 | `tests/test_session.py` | 工具回合状态机与事务历史测试 |
| 修改 | `tests/test_tui.py` | 工具 UI、确认 Modal、草稿和取消测试 |
| 修改 | `tests/test_cli.py` | 项目根目录、工具组装与资源清理测试 |
| 修改 | `checklist.md` | 记录逐项自动化和 tmux 实际证据 |
| 新建 | `docs/features/001-tool-system.md` | 本章完成后的功能总结 |

## T1：定义工具领域模型

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/errors.py`、`src/mewcode/models.py`
**依赖：** 无

**步骤：**

1. 定义 `ToolDefinition`、`ToolCall`、`ToolResult`、`ToolContext` 和 `CommandApprovalRequest`。
2. 定义 `ApprovalHandler` 与 `Tool` Protocol。
3. 定义稳定的 `ToolErrorCode` 和携带安全详情的 `ToolError`。
4. 为 `ToolResult` 实现稳定、有界的模型 JSON 序列化和用户摘要入口。
5. 把会话消息改为 `UserMessage`、`AssistantMessage(tool_calls=...)`、`ToolResultMessage` 联合类型。
6. 扩展 `StreamEventKind` 和 `StreamEvent`，保持纯文本事件构造简洁。

**验证：** 运行 `uv run python -m compileall -q src/mewcode`，并用小型导入脚本构造三种消息、一个工具调用和成功/失败结果，期望序列化字段稳定且不包含异常对象。

## T2：实现项目路径安全

**文件：** `src/mewcode/tools/paths.py`、`tests/tools/test_paths.py`
**依赖：** T1

**步骤：**

1. 实现根目录规范化和相对路径参数检查。
2. 实现已有文件严格解析及根目录组成关系检查。
3. 实现待创建路径的最近已有父目录解析，拒绝父目录符号链接越界。
4. 实现安全相对 POSIX 路径转换。
5. 实现跳过 `.git` 和符号链接目录的稳定文件枚举。
6. 覆盖普通路径、空路径、`..`、项目外绝对路径、文件链接和父目录链接测试。

**验证：** `uv run pytest -q tests/tools/test_paths.py -k path` 通过，所有越界样例均返回 `PATH_OUTSIDE_ROOT` 且不暴露项目外文件内容。

## T3：实现原子 UTF-8 写入

**文件：** `src/mewcode/tools/paths.py`、`tests/tools/test_paths.py`
**依赖：** T2

**步骤：**

1. 在目标同目录创建临时文件并以 UTF-8 写入。
2. 刷新数据并在覆盖时保留目标权限位。
3. 使用原子替换提交目标。
4. 在写入、替换或取消异常路径清理临时文件。
5. 测试新建、覆盖、权限保留和模拟提交失败。

**验证：** `uv run pytest -q tests/tools/test_paths.py -k atomic` 通过；失败测试中原文件字节不变且目录无临时残留。

## T4：实现读文件工具

**文件：** `src/mewcode/tools/read_file.py`、`tests/tools/test_file_tools.py`
**依赖：** T1、T2

**步骤：**

1. 定义禁止未知字段的 `ReadFileArguments` 及 JSON Schema。
2. 校验文件存在、类型和大小上限。
3. 按 UTF-8 解码，按 1-based 起始行和限制行数输出带行号内容。
4. 返回总行数、实际区间和截断状态。
5. 覆盖空文件、范围越界、目录、二进制、非 UTF-8 和大文件。

**验证：** `uv run pytest -q tests/tools/test_file_tools.py -k read` 通过，成功和每类错误均得到预期结构。

## T5：实现写文件工具

**文件：** `src/mewcode/tools/write_file.py`、`tests/tools/test_file_tools.py`
**依赖：** T1、T2、T3

**步骤：**

1. 定义 `WriteFileArguments` 并限制路径及内容字节数。
2. 安全创建项目内缺失父目录。
3. 使用原子写入创建或覆盖目标。
4. 返回 `created`/`overwritten`、相对路径和字符/字节数。
5. 覆盖目录目标、越界链接、过大内容和写入失败。

**验证：** `uv run pytest -q tests/tools/test_file_tools.py -k write` 通过，磁盘内容与操作类型一致。

## T6：实现唯一匹配改文件工具

**文件：** `src/mewcode/tools/edit_file.py`、`tests/tools/test_file_tools.py`
**依赖：** T1、T2、T3

**步骤：**

1. 定义 `EditFileArguments`，禁止空 `old_text` 和未知字段。
2. 安全读取目标 UTF-8 文本并检查大小。
3. 统计非重叠匹配次数，只允许恰好一次。
4. 原子写回一次替换后的内容并检查结果大小。
5. 零次和多次匹配返回实际次数，不修改原文件。

**验证：** `uv run pytest -q tests/tools/test_file_tools.py -k edit` 通过，失败样例前后文件 SHA-256 一致。

## T7：实现安全文件查找

**文件：** `src/mewcode/tools/find_files.py`、`tests/tools/test_search_tools.py`
**依赖：** T1、T2

**步骤：**

1. 定义 `FindFilesArguments`，限制 pattern 和 `max_results`。
2. 校验相对 glob 模式，拒绝绝对与越界语义。
3. 使用安全文件枚举匹配普通文件。
4. 按相对 POSIX 路径排序，结果达到上限时标注截断。
5. 覆盖 `.git`、符号链接目录、无匹配和非法模式。

**验证：** `uv run pytest -q tests/tools/test_search_tools.py -k find` 通过，输出顺序稳定且无越界路径。

## T8：实现代码内容搜索

**文件：** `src/mewcode/tools/search_code.py`、`tests/tools/test_search_tools.py`
**依赖：** T1、T2、T7

**步骤：**

1. 定义 `SearchCodeArguments`，限制 query、file pattern 和结果数。
2. 支持字面量查询和 Python 正则，非法正则映射为 `INVALID_PATTERN`。
3. 复用安全文件枚举，跳过二进制、非 UTF-8 和越界链接。
4. 返回相对路径、1-based 行号与有界匹配行。
5. 每批扫描主动让出事件循环，达到匹配上限立即停止并标注截断。
6. 覆盖 glob 过滤、零匹配、长行和稳定排序。

**验证：** `uv run pytest -q tests/tools/test_search_tools.py -k search` 通过，非法或跳过文件不会让工具崩溃。

## T9：实现异步命令工具

**文件：** `src/mewcode/tools/execute_command.py`、`tests/tools/test_execute_command.py`
**依赖：** T1

**步骤：**

1. 定义 `ExecuteCommandArguments` 的命令长度和 1-300 秒范围。
2. 使用系统 Shell、项目根目录和独立进程组启动命令。
3. 并发读取 stdout/stderr，分别按字节截断并持续排空管道。
4. 返回命令、相对 cwd、退出码和两个输出截断标志。
5. 超时或取消时终止进程组，宽限期后强制杀死并回收。
6. 覆盖成功、非零退出、双通道大输出、超时、取消和子进程终止。

**验证：** `uv run pytest -q tests/tools/test_execute_command.py` 通过；测试结束后记录的父/子 PID 均不存在。

## T10：实现注册中心与默认工具集合

**文件：** `src/mewcode/tools/registry.py`、`src/mewcode/tools/__init__.py`、`tests/tools/test_executor.py`
**依赖：** T4-T9

**步骤：**

1. 实现稳定顺序注册、按名查询和不可变定义列表。
2. 校验工具名、非空描述、object Schema 和 `additionalProperties=false`。
3. 重复或无效定义在注册时立即报错。
4. 创建默认 Registry，按固定顺序登记六个核心工具。
5. 从包入口导出领域类型、Registry、Executor 和默认工厂。

**验证：** `uv run pytest -q tests/tools/test_executor.py -k registry` 通过，默认工具名集合与六项需求完全一致。

## T11：实现统一工具执行器

**文件：** `src/mewcode/tools/executor.py`、`tests/tools/test_executor.py`
**依赖：** T1、T10

**步骤：**

1. 按名查找工具并完整解析 JSON object。
2. 使用工具参数模型拒绝缺字段、未知字段和类型错误。
3. 为需要批准的工具构造一次性 `CommandApprovalRequest`。
4. 拒绝时返回 `USER_REJECTED` 且不调用工具。
5. 对执行施加工具超时，并转换预期 ToolError、Timeout 和意外异常。
6. 保持 `CancelledError` 向上传播，限制错误信息和模型 JSON 长度。
7. 确保确认展示的命令、cwd、超时与实际执行参数一致。

**验证：** `uv run pytest -q tests/tools/test_executor.py` 通过，未知工具、JSON、Schema、拒绝、超时和异常均映射到稳定结果。

## T12：扩展 Provider 公共契约

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/models.py`、现有 Provider 测试假对象
**依赖：** T1

**步骤：**

1. 为 `LLMProvider.stream()` 增加默认空工具定义参数。
2. 将现有测试 Provider 改为接收并记录工具定义。
3. 更新纯文本消息断言以使用结构化联合消息。
4. 保持不传工具时的调用方式和流事件行为兼容。

**验证：** `uv run pytest -q tests/test_session.py tests/test_tui.py tests/test_cli.py` 至少通过纯文本相关用例，调用次数与原行为一致。

## T13：实现 OpenAI 工具协议适配

**文件：** `src/mewcode/providers/openai.py`、`tests/providers/test_openai.py`
**依赖：** T1、T12

**步骤：**

1. 将三种统一历史消息转换为 Chat Completions 消息。
2. 将统一工具定义包装为 function tools，并在非空时设置 auto 选择。
3. 按 choice 和 tool call index 累积 id、type、name 与参数碎片。
4. 检查字段冲突、finish reason、完整 JSON 和流正常结束。
5. 流完成后按 index 顺序产生所有 `TOOL_CALL`，再产生 `DONE`。
6. 保留普通文本、错误映射和流关闭逻辑。
7. 使用官方 SDK 解析本地 SSE 验证真实碎片格式。

**验证：** `uv run pytest -q tests/providers/test_openai.py` 通过，覆盖单调用、多调用、残缺/冲突流和完整历史重放。

## T14：实现 Anthropic 工具协议适配

**文件：** `src/mewcode/providers/anthropic.py`、`tests/providers/test_anthropic.py`
**依赖：** T1、T12

**步骤：**

1. 将结构化历史转换为 Anthropic 内容块并正确合并角色消息。
2. 将统一工具定义转换为 Anthropic `input_schema` 格式。
3. 按 block index 处理 `tool_use` start、`input_json_delta` 和 block stop。
4. 校验空初始 input、id/name、重复 index、JSON 完整性和 message stop。
5. 流完成后按 block index 产生所有 `TOOL_CALL`，再产生 `DONE`。
6. 保留 thinking/text 增量、token 参数和错误映射。
7. 使用官方 SDK 解析本地 SSE 验证真实事件格式。

**验证：** `uv run pytest -q tests/providers/test_anthropic.py` 通过，覆盖单调用、多调用、残缺/冲突流、thinking 和历史重放。

## T15：实现纯文本与单工具会话编排

**文件：** `src/mewcode/session.py`、`tests/test_session.py`
**依赖：** T10-T14

**步骤：**

1. 向 Session 注入 Registry、Executor 和 ToolContext。
2. 抽取一次 Provider 响应的收集与完整性校验逻辑。
3. 保留纯文本一次请求、最终完成后原子提交的路径。
4. 收集第一次响应的前置文本与工具调用。
5. 单调用时执行工具，逐个产生 `TOOL_CALL` 和 `TOOL_RESULT` 事件。
6. 将调用和结果构造成候选历史，发起恰好一次最终答复请求。
7. 最终文本正常完成后一次性提交四类结构化消息。

**验证：** `uv run pytest -q tests/test_session.py -k 'plain or successful_tool or tool_error or rejected'` 通过；Provider 调用次数分别严格为 1 或 2。

## T16：实现多工具和连续调用限制

**文件：** `src/mewcode/session.py`、`tests/test_session.py`
**依赖：** T15

**步骤：**

1. 第一次同批多调用时不执行任何工具。
2. 为每个原生调用 ID 构造一致的 `MULTIPLE_TOOLS` 结果并完整回灌。
3. 允许第二次 Provider 请求生成文字解释。
4. 第二次出现任意工具调用时产生 `LIMIT_REACHED`，不执行、不请求第三次。
5. 多工具限制成功得到最终文本时可提交完整可重放历史；连续调用限制不提交半轮。

**验证：** `uv run pytest -q tests/test_session.py -k 'multiple or limit'` 通过，执行计数为 0，Provider 调用数不超过 2。

## T17：实现会话取消与事务回滚

**文件：** `src/mewcode/session.py`、`tests/test_session.py`、`tests/tools/test_execute_command.py`
**依赖：** T15、T16

**步骤：**

1. 覆盖首次模型流、批准等待、工具运行和第二次模型流四个取消点。
2. 确保取消不提交候选历史。
3. 确保命令进程组完成清理后才让取消离开工具层。
4. 验证已完成文件副作用不回滚，但历史仍保持原值。
5. Provider 无效流和空最终文本同样回滚整个候选轮次。

**验证：** `uv run pytest -q tests/test_session.py tests/tools/test_execute_command.py -k 'cancel or invalid or rollback'` 通过，无 pending task 或残留进程警告。

## T18：增加 TUI 工具消息组件

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T1、T15、T16

**步骤：**

1. 扩展 Transcript role/state 和 snapshot 深拷贝。
2. 实现紧凑的 `ToolMessage`，展示工具名、调用摘要和结果摘要。
3. `TOOL_CALL` 时添加 pending 记录，`TOOL_RESULT` 时按调用 ID 更新对应记录。
4. `LIMIT_REACHED` 时增加明确状态并结束当前助手消息。
5. 第二次模型文本继续更新本轮助手消息，不重复用户消息。
6. 保持条件自动跟随和生成中草稿行为。

**验证：** `uv run pytest -q tests/test_tui.py -k 'tool or stream or scroll'` 通过，流式更新不新增重复消息。

## T19：实现命令确认 Modal

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T11、T18

**步骤：**

1. 实现 `CommandApprovalScreen`，完整展示命令、项目 cwd 和超时。
2. 实现 `Y`/`Enter` 批准、`N`/`Esc` 拒绝及可点击按钮。
3. 把 App 的异步批准方法绑定到 Session 使用的 handler。
4. Modal 打开和关闭期间保留 composer 草稿并恢复焦点。
5. `Ctrl+C` 取消回复时关闭 Modal 并传播取消，而不是生成普通拒绝。

**验证：** `uv run pytest -q tests/test_tui.py -k 'approval or command or draft'` 通过，批准和拒绝每次只生效一次。

## T20：完成 TUI 取消与静态记录

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T17-T19

**步骤：**

1. 取消首次流、工具执行和最终流时更新助手及工具记录状态。
2. 恢复 composer、提交能力和状态行，不丢草稿。
3. 静态 transcript 输出工具名、调用/结果摘要、批准/拒绝和限制状态。
4. 不输出完整隐藏结果、被截断尾部、API Key 或环境变量值。
5. 覆盖退出 snapshot 不包含未提交草稿。

**验证：** `uv run pytest -q tests/test_tui.py` 通过，无 worker error、pending task 或敏感文本泄露。

## T21：组装 CLI 项目根目录与工具系统

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`
**依赖：** T10、T11、T15、T19

**步骤：**

1. 在 `run_app` 开始时固定 `Path.cwd().resolve()` 为项目根目录。
2. 创建默认 Registry、ToolExecutor 和可绑定的批准 handler。
3. 构造 ToolContext、ChatSession 与 MewCodeApp，并完成 handler 绑定。
4. 保持 Provider 在所有退出与异常路径中恰好关闭一次。
5. 测试从不同 cwd 启动时工具只访问对应根目录。

**验证：** `uv run pytest -q tests/test_cli.py` 通过；帮助、配置错误和 Provider 清理回归不变。

## T22：执行完整自动化回归

**文件：** 全部源码与测试
**依赖：** T1-T21

**步骤：**

1. 运行完整 pytest，修复所有新增与旧测试失败。
2. 运行 Ruff lint 和格式检查。
3. 运行 `compileall` 和敏感信息/遗留接口扫描。
4. 检查测试结束无 pending task、未关闭流或子进程。
5. 核对六个工具全部被 Registry 使用，新增公开接口均有真实调用方。

**验证：** `uv run pytest -q`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run python -m compileall -q src tests` 均以状态码 0 结束。

## T23：准备双协议 tmux 验收环境

**文件：** 测试辅助脚本或临时验收目录，不把密钥写入仓库
**依赖：** T13、T14、T21、T22

**步骤：**

1. 创建独立临时项目及测试文件，避免修改 MewCode 源码。
2. 启动确定性的本地 OpenAI 与 Anthropic SSE 服务，使用官方 SDK 协议。
3. 创建仅指向本地服务的临时 YAML profile，不含真实密钥。
4. 在 tmux 中从临时项目目录启动 MewCode。
5. 记录 tmux 版本、终端尺寸和必要的 extended keys 设置。

**验证：** 两个 profile 均能进入 TUI 并完成一次纯文本流式回复，项目根目录显示/行为指向临时项目。

## T24：执行文件与搜索工具 tmux 验收

**文件：** `checklist.md`
**依赖：** T23

**步骤：**

1. 用真实对话依次触发读文件、写文件、改文件、找文件和搜内容。
2. 观察工具请求、执行摘要、结果回灌和最终答复。
3. 从 tmux 外核对新建和修改后的磁盘字节内容。
4. 尝试项目外路径和越界符号链接，确认拒绝且外部文件不变。
5. 分别在 OpenAI 与 Anthropic profile 重复核心场景并记录证据。

**验证：** checklist 对应项目写入实际命令、观察结果和文件校验值，所有文件类场景通过。

## T25：执行命令、限制与取消 tmux 验收

**文件：** `checklist.md`
**依赖：** T23

**步骤：**

1. 触发命令工具并用键盘批准，确认命令副作用和最终答复。
2. 再次触发命令并拒绝，确认进程未启动且结果回灌。
3. 触发同批多个工具和最终阶段第二个工具，确认都不执行。
4. 在长命令运行中按 `Ctrl+C`，确认进程组终止、历史回滚和 TUI 恢复。
5. 退出 TUI，检查普通终端静态 transcript 包含有界工具状态。
6. 在 OpenAI 与 Anthropic profile 重复关键协议场景。

**验证：** checklist 记录批准/拒绝、PID/副作用检查、Provider 请求次数及退出 transcript 的实际证据。

## T26：生成工具系统功能总结

**文件：** `docs/features/001-tool-system.md`
**依赖：** T22、T24、T25

**步骤：**

1. 记录本章目标和六个用户可用工具。
2. 记录安全边界、命令确认和单工具回合语义。
3. 记录核心架构、文件、Provider 协议和 TUI 交互。
4. 引用实际自动化与 tmux 验收结果，并如实列出未通过项。
5. 记录当前限制和下一章 Agent Loop 边界。
6. 填写最终对应提交哈希，不覆盖 `000-current-features.md`。

**验证：** 文档无 TBD/TODO，所有“已通过”结论均能追溯到 checklist 实际证据。

## 执行顺序

```text
T1
├─ T2 → T3 ─┬─ T5
│           └─ T6
├─ T4
├─ T7 → T8
├─ T9
└─ T12 ─┬─ T13
        └─ T14

T4-T9 → T10 → T11
T10-T14 → T15 → T16 → T17
T15-T16 → T18 → T19 → T20
T10/T11/T15/T19 → T21
T1-T21 → T22 → T23 → T24/T25 → T26
```

## 任务自检

- Plan 中每个模块均至少对应一个实现任务：领域模型 T1、路径/原子写入 T2-T3、六工具 T4-T9、Registry/Executor T10-T11、Provider T12-T14、Session T15-T17、TUI T18-T20、CLI T21。
- 每个任务均列出具体文件、依赖、步骤和可运行验证命令。
- 任务依赖单向，不存在循环；Provider 与工具任务可在公共领域模型完成后并行。
- 自动化回归、双协议 tmux 验收、checklist 证据和增量功能总结均有独立收尾任务。
- 类型名、方法签名和错误语义与已批准 `plan.md` 一致，不引入 Agent Loop、并行工具或未批准权限。
