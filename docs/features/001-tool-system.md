# MewCode 工具系统功能总结

## 本章目标

本章把 MewCode 从纯对话助手扩展为可以在单个用户回合中调用一次本地工具的 Coding Agent。模型可以读取、创建和修改项目文件，查找文件、搜索内容，并在用户逐次确认后执行 Shell 命令；工具结果会回灌给模型，由模型生成最终文字答复。

对应实现提交：`33e1c05 feat: 添加 MewCode 工具系统`。

## 用户可用工具

| 工具 | 行为 |
|---|---|
| `read_file` | 按 1-based 行号读取项目内 UTF-8 文本，返回区间、总行数和截断状态 |
| `write_file` | 自动创建项目内父目录，新建或原子覆盖 UTF-8 文本文件 |
| `edit_file` | 仅在原文恰好匹配一次时原子替换；零次或多次匹配均不修改 |
| `find_files` | 按相对 glob 查找普通文件，排序并限制结果数 |
| `search_code` | 支持字面量、正则及 glob 过滤，返回相对路径、行号和匹配行 |
| `execute_command` | 在项目根目录运行 Shell 命令，捕获退出码和有界 stdout/stderr |

模型直接回答文字时仍只请求一次 API，不会为了工具系统增加额外请求。

## 安全边界

- 启动 MewCode 时将当前工作目录解析并固定为项目根目录。
- 文件类工具拒绝 `..`、项目外绝对路径及解析后越界的文件或目录符号链接。
- 文件输出只使用项目相对路径，不向模型泄露无关的本机路径。
- 写文件和改文件使用同目录临时文件加原子替换；失败时旧文件保持不变并清理临时文件。
- 文件、搜索、命令输出、错误正文和 UI 摘要均有明确上限，截断会被标注。
- 工具参数由禁止未知字段的 Pydantic 模型校验；未知工具、无效 JSON、参数错误、超时和异常都转换为结构化结果。
- TUI 不展示 traceback、配置 API Key 或环境变量内容。

Shell 命令是边界内的例外：用户批准后，命令本身仍可以访问项目外路径、网络和当前账号可访问的系统资源。本章不提供 Shell 沙箱、白名单或权限降级。

## 命令确认

每次 `execute_command` 都显示 Textual Modal，完整列出命令、项目工作目录和超时，批准不会复用于下一次调用。

- `Y` 或 `Enter`：批准执行。
- `N` 或 `Esc`：拒绝执行。
- Modal 中的执行和拒绝按钮也可点击。
- 确认期间输入草稿保持不变，关闭后焦点回到输入框。
- 确认等待或命令执行期间按 `Ctrl+C` 会取消本轮；运行中的整个进程组会被终止并回收。

## 单工具回合语义

一次成功工具回合最多发起两次 Provider 请求：

1. 第一次请求由模型选择零个或一个工具。
2. MewCode 执行、拒绝或生成结构化工具错误。
3. 工具请求和结果按供应商原生格式回灌。
4. 第二次请求只生成最终文字答复。
5. 最终文字正常完成后，整轮历史一次性提交。

同批请求两个或更多工具时，所有工具都不执行，每个原生调用 ID 都会得到 `multiple_tools` 结果。第二次请求若再次调用工具，该调用不执行，也不会发起第三次请求；UI 会显示本章不支持连续调用。

历史使用供应商无关的用户消息、助手工具请求、工具结果和最终答复模型。取消、无效流、空最终答复及连续调用限制都不会留下半轮历史。已经完成的文件副作用不会随会话回滚。

## 架构

```text
CLI
 ├─ project_root + ToolContext
 ├─ ToolRegistry（六个工具定义）
 ├─ ToolExecutor（校验、确认、超时、错误隔离）
 └─ ChatSession
      ├─ Provider 第一次流
      ├─ 单工具执行 / 多工具拒绝
      └─ Provider 最终答复流
```

- `src/mewcode/tools/base.py` 定义工具、调用、结果、上下文和确认请求。
- `src/mewcode/tools/paths.py` 集中实现项目路径边界与原子写入。
- `src/mewcode/tools/registry.py` 管理稳定注册顺序和默认六工具集合。
- `src/mewcode/tools/executor.py` 统一处理查找、JSON、Schema、确认、超时和异常。
- `src/mewcode/providers/openai.py` 适配 Chat Completions function tools 与流式参数碎片。
- `src/mewcode/providers/anthropic.py` 适配 Messages `tool_use` / `tool_result` 和 `input_json_delta`。
- `src/mewcode/session.py` 实现两阶段事务状态机。
- `src/mewcode/tui.py` 展示工具状态、命令 Modal、取消结果和静态记录。

工具层不依赖 Provider、Session 或 TUI；Provider 不执行工具；TUI 不解析工具 JSON。

## Provider 支持

OpenAI 与 Anthropic 都会在流正常结束、调用 ID、名称和 JSON 参数完整后才产生统一 `ToolCall`。残缺、冲突、未封闭或异常结束的工具流不会触发副作用。

OpenAI 保存并重放完整 `tool_calls` 数组和对应 tool 消息；Anthropic 保存并重放 `tool_use` 与合并后的 `tool_result` user 内容块。Claude 的 thinking 增量继续只供 UI 展示，不写入会话历史。

配置格式没有变化，仍使用 YAML 的 `name`、`protocol`、`model`、`base_url`、`api_key` 和可选 `thinking` 字段。

## 自动化验证

最终实际运行结果：

```text
uv run pytest -q
97 passed in 12.18s

uv run ruff check .
All checks passed!

uv run ruff format --check .
36 files already formatted
```

`uv run python -m compileall -q src tests` 与 `git diff --check` 也以状态码 0 完成。测试覆盖六工具、目录穿越和符号链接、原子写入、唯一替换、参数校验、命令确认、输出截断、进程组终止、双协议参数碎片、历史重放、单工具编排、取消事务及 Textual 交互。

## tmux 端到端验收

验收使用从官方源码本地构建的 tmux 3.5a，100x32 pane，启用 mouse 与 extended keys。MewCode 从独立临时项目 `/tmp/mewcode-e2e-20260725/project` 启动，通过官方 OpenAI/Anthropic SDK 连接确定性的本地 SSE 服务，未使用仓库或真实 API Key 作为测试数据。

实际完成的自然语言场景包括：

- 两种 Provider 的纯文本流式回答、文件读取和命令确认。
- 新建、覆盖、唯一修改、零匹配和多匹配；失败前后 SHA-256 保持一致。
- glob 查找与内容搜索，结果与临时项目磁盘事实一致。
- `../outside.txt` 和越界符号链接均被拒绝，外部文件哈希保持不变。
- `Y`/`Enter` 批准后产生预期命令副作用，`N`/`Esc` 拒绝后无副作用。
- 同批两个工具全部不执行，第二阶段再次调用不执行且没有第三次请求。
- 确认框中取消不启动命令；长命令运行中取消后父 PID 20047、子 PID 20048 均不存在。
- 退出全屏界面后，普通终端保留 complete、rejected、error、cancelled 等有界工具摘要。

本地服务日志记录 52 次 API 请求，其中 OpenAI 39 次、Anthropic 13 次。tmux 实测还发现并修复了两个自动化首轮未捕获的问题：最终答复一度显示在工具记录上方，以及 Modal 焦点导致 `Enter` 错误拒绝。两项均添加回归测试并重新执行对应 tmux 场景。

详细逐项证据见项目根目录的 `checklist.md`。

## 当前限制

- 每个用户回合最多执行一个工具，不支持自动 Agent Loop、并行工具或工具重试。
- 工具结果回灌后只允许一次最终答复请求。
- 不提供文件 diff 审批、撤销、备份或跨文件事务。
- 不支持二进制编辑、非 UTF-8 自动探测或编码转换。
- 不提供命令沙箱、白名单、容器隔离或网络限制。
- 不实现 MCP、插件市场、Git 自动提交、会话持久化或跨进程恢复。
- 继续使用 OpenAI Chat Completions，不支持 Responses API。

下一阶段可以在现有统一 Tool、Registry、Executor 和结构化历史之上增加 Agent Loop，无需改变六个核心工具的执行契约。
