# MewCode Textual 全屏 TUI Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `pyproject.toml` | 新增 Textual、移除 Prompt Toolkit |
| 更新 | `uv.lock` | 锁定新的依赖图 |
| 重写 | `src/mewcode/tui.py` | Textual App、控件、transcript、状态机和静态渲染 |
| 修改 | `src/mewcode/cli.py` | 运行 Textual App、接收 snapshot、退出后打印记录 |
| 重写 | `tests/test_tui.py` | Textual Pilot 布局、输入、滚动、worker 和退出测试 |
| 修改 | `tests/test_cli.py` | App 组装、静态 transcript 和 Provider 关闭测试 |
| 更新 | `checklist.md` | 执行并记录本次 UI 改造验收证据 |

Provider、config、models、session 及其既有测试不修改，作为接口兼容回归基线。

## T1：迁移运行时依赖

**文件：** `pyproject.toml`、`uv.lock`

**依赖：** 无

**步骤：**

1. 添加 `textual>=8.2,<9`。
2. 将 Rich 下限调整到 Textual 兼容的 `>=14.2,<15`。
3. 删除 `prompt-toolkit` 运行时依赖。
4. 运行 uv 重新生成锁文件，不升级无关的直接依赖范围。

**验证：** 运行 `uv sync --all-groups` 和 `uv run python -c "import textual; print(textual.__version__)"`，期望安装成功并输出 8.x；运行 `uv tree`，确认没有直接 Prompt Toolkit 依赖。

## T2：定义 UI transcript 模型

**文件：** `src/mewcode/tui.py`

**依赖：** T1

**步骤：**

1. 定义可变 `TranscriptEntry`，包含 role、content、thinking 和 state。
2. 定义不可变 `TranscriptSnapshot`，保存退出时的 entry 快照。
3. 提供 entry 的安全拷贝逻辑，避免 App 退出后 worker 或 widget 继续修改结果。
4. 不在 snapshot 中保存 composer 草稿或供应商敏感信息。

**验证：** 运行针对 transcript 默认值、状态与不可变 snapshot 的单元测试，期望全部通过。

## T3：实现消息 Widget

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T2

**步骤：**

1. 实现 `UserMessage`，渲染用户标签和纯文本内容。
2. 实现 `AssistantMessage`，包含可选 thinking 区和 Markdown 回答区。
3. 实现 `StatusMessage`，展示取消和脱敏错误状态。
4. 为 AssistantMessage 提供异步增量更新方法，只更新当前 widget，不创建重复消息。

**验证：** 使用 Textual headless App mount 三类消息，断言标签、thinking、Markdown 与状态文本可查询且内容正确。

## T4：实现 ConversationView 滚动策略

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T3

**步骤：**

1. 继承 `VerticalScroll` 作为历史容器，开启纵向 overflow 和鼠标滚动。
2. 实现 append entry/widget，并在更新前记录 `is_vertical_scroll_end`。
3. 仅当更新前在底部时，在 refresh 后调用 `scroll_end(animate=False)`。
4. 上滚时保留 `scroll_y`；滚回底部后恢复自动跟随。

**验证：** 用足够多的消息构造滚动区；Pilot 鼠标滚轮上滚后更新当前消息，断言 scroll_y 未跳到底；滚到底后再更新，断言跟随 max_scroll_y。

## T5：实现 ComposerTextArea 按键语义

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T1

**步骤：**

1. 继承 `TextArea`，关闭行号并启用软换行。
2. 捕获 `Enter`，阻止默认插入换行并调用 App 提交 action。
3. 捕获 `Alt+Enter`，在当前 cursor_location 调用 `insert("\n")`。
4. 确保 App 的高优先级 `Ctrl+C`、`Ctrl+D` 覆盖 TextArea 默认 copy/delete 行为。
5. 普通字符、方向键、删除、粘贴和焦点行为沿用 TextArea。

**验证：** Pilot 聚焦 composer，输入两段文字并按 Alt+Enter，断言 text 包含换行；按 Enter 触发一次提交且不插入额外换行。

## T6：实现输入框动态高度

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T5

**步骤：**

1. 监听 `TextArea.Changed`。
2. 以显式换行数计算逻辑行数，设置高度为 `min(max(lines, 1), 6)`。
3. 第七行起保持六行高，使用 TextArea 内部 scroll_y 浏览超出内容。
4. 清空或提交后恢复一行高度。

**验证：** 逐次 Alt+Enter 到七行，断言高度按 1-6 增长、第七行不增长且 max_scroll_y 可用；清空后恢复一行。

## T7：搭建 MewCodeApp 固定布局

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T4、T6

**步骤：**

1. 实现 `MewCodeApp` 的 compose，顺序 mount ConversationView、composer 容器、状态行。
2. CSS 将历史区设为 `height: 1fr`，输入区设为 `height: auto` 并固定底部。
3. 启动后聚焦 ComposerTextArea，标题/状态只显示 profile 与 model，不显示 base URL 或密钥。
4. 使用 Textual Resize 自动重排，不在代码中保存固定终端尺寸。

**验证：** 以 80x24、120x40 和窄尺寸运行 `run_test(size=...)`，断言 ConversationView 位于 composer 上方、composer 下边缘固定且组件矩形不重叠。

## T8：实现空闲提交与退出

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T7

**步骤：**

1. 实现 `action_submit`：空输入忽略，非空输入创建 user 与 streaming assistant entry 并清空 composer。
2. 精确匹配 `/exit` 时，在空闲状态生成 snapshot 并退出，不向 ChatSession 发请求。
3. 实现高优先级 Ctrl+D：只有空闲且 composer 为空时退出。
4. 非空草稿时 Ctrl+D 不删除字符、不退出。

**验证：** Pilot 覆盖空 Enter、普通提交、`/exit`、空 Ctrl+D 与非空 Ctrl+D；断言请求数、composer 内容和 App result 正确。

## T9：实现流式 reply worker

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T8

**步骤：**

1. 提交后通过 `run_worker(..., exclusive=True, group="reply")` 启动单个回复 worker。
2. worker 消费 `ChatSession.stream_reply()`，将 thinking/text 追加到当前 entry 并更新同一 AssistantMessage。
3. DONE 将 entry 标记 complete，不额外添加消息。
4. `finally` 清理当前 worker/widget 引用、恢复提交状态并重新聚焦 composer。

**验证：** 用逐步释放事件的 Provider，断言 transcript 始终只有一个 user 与一个 assistant entry，thinking/text 增量顺序正确，完成后 ChatSession 历史提交。

## T10：实现生成期间草稿编辑和提交禁用

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T9

**步骤：**

1. worker 运行时保持 composer enabled 和 focusable。
2. `action_submit` 在 `is_generating` 时直接返回，不读取或清空草稿。
3. 不创建第二 worker，不把草稿加入队列。
4. 回复完成后保留草稿原文与 cursor，并恢复 Enter 提交。

**验证：** 暂停第一个 Provider 流，输入下一条草稿并多次按 Enter，断言请求数仍为一且草稿不变；完成首轮后按 Enter，断言第二个请求才创建。

## T11：实现 Ctrl+C 取消与清空

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T10

**步骤：**

1. 生成中 Ctrl+C 取消 reply worker，并让 Provider 异步流关闭。
2. 将当前 entry 标记 cancelled，清除未完成 thinking/text 并显示取消状态。
3. ChatSession 保持取消前历史，不提交当前 user/assistant 轮次。
4. 空闲时 Ctrl+C 只清空 composer 并恢复一行高度，不改变 transcript。

**验证：** 在收到部分 delta 后 Ctrl+C，断言 worker 结束、history 未提交、entry 为 cancelled、草稿保留；空闲 Ctrl+C 仅清空草稿。

## T12：实现 ProviderError 恢复

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T10

**步骤：**

1. 在 worker 内捕获 ProviderError，不让异常逃逸到 Textual 日志。
2. 将 entry 标记 error，只展示统一错误字符串。
3. 保留生成期间编辑的草稿并恢复提交。
4. 确保失败轮次不进入 ChatSession 历史，下一轮可以成功。

**验证：** 分别注入 authentication、rate_limit、connection、server 错误，断言安全状态、草稿、history、worker 清理和下一轮恢复。

## T13：实现静态 transcript 输出

**文件：** `src/mewcode/tui.py`、`tests/test_tui.py`

**依赖：** T11、T12

**步骤：**

1. 实现 snapshot 构建，深拷贝当前 transcript，不包含 composer 草稿。
2. 实现 `render_static_transcript(snapshot, console)`，按顺序输出用户、thinking、回答、取消和错误。
3. Markdown 回答继续使用 Rich Markdown，thinking 用弱化样式。
4. 空 transcript 不输出多余内容。

**验证：** 使用内存 Console 验证所有 entry state 的静态输出；断言草稿、API key 和 base URL 不出现。

## T14：更新 CLI 与资源关闭

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`

**依赖：** T13

**步骤：**

1. 用 `MewCodeApp(...).run_async(mouse=True)` 替换旧 `MewCodeTUI.run()`。
2. App 返回后在普通终端调用静态 transcript 渲染器。
3. 保留启动配置错误状态码与安全输出。
4. 在 `finally` 中关闭 Provider；App 异常、正常退出和空记录都执行关闭。

**验证：** 注入 FakeApp/FakeProvider，断言 mouse 启用、snapshot 被打印、Provider 始终关闭；运行 `uv run mewcode --help` 状态码为 0。

## T15：删除旧 UI 路径并完成自动化回归

**文件：** 所有实现与测试文件

**依赖：** T14

**步骤：**

1. 删除旧 StreamRenderer、PromptSession、Rich Live 和信号处理循环。
2. 运行全部 Textual 与既有 Provider/config/session 测试。
3. 修复 pending worker、未关闭流、异步警告和不稳定时序断言。
4. 运行 Ruff lint、格式检查与依赖/源码扫描。

**验证：** 运行 `uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .`；运行 `rg 'PromptSession|prompt_toolkit|rich\.live' src tests pyproject.toml`，期望前三者状态码 0，扫描无匹配。

## T16：执行 tmux Textual 端到端验收

**文件：** `checklist.md`（只记录实际证据）

**依赖：** T15、已批准的 `checklist.md`

**步骤：**

1. 在 tmux 使用本地 OpenAI 兼容 SSE 端点启动全屏 MewCode，验证历史区上方、composer 固定底部。
2. 完成两轮对话；生成期间编辑下一条草稿并按 Enter，确认不排队，完成后再提交。
3. 用 Alt+Enter 生成多行草稿并验证 1-6 行增长；通过 tmux 鼠标滚轮事件上滚历史并验证不自动跳底。
4. 验证生成中 Ctrl+C、空闲 Ctrl+C、非空/空 Ctrl+D、`/exit`。
5. 退出后捕获普通终端输出，确认静态记录存在且未提交草稿不存在。
6. 使用本地 Anthropic SSE 端点验证 thinking 分区；有真实 API Key 时追加外部服务验收。

**验证：** `checklist.md` 的 UI 改造条目均有 tmux pane 或命令证据；任何失败修复后重跑相关自动化和端到端场景。

## 执行顺序

```text
T1 → T2 → T3 → T4 ─┐
      └────→ T5 → T6 ├→ T7 → T8 → T9 → T10 ─┬→ T11 ─┐
                     ┘                        └→ T12 ─┴→ T13 → T14 → T15 → T16
```

## 自检

- plan 中 transcript、消息组件、滚动容器、composer、App 状态机、CLI 与静态输出均有对应任务。
- 每个任务包含具体文件、依赖、步骤和可执行验证，没有占位符。
- 依赖图无环；T3/T4 与 T5/T6 可在 T2/T1 后独立推进，最终在 T7 汇合。
- Provider、配置和 ChatSession 不在文件改动清单内，并由 T15 完整回归保护。
- Textual UI 只有一个实现路径，Prompt Toolkit 删除由依赖和源码扫描双重验证。
