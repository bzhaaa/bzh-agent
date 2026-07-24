# MewCode Textual 全屏 TUI Plan

## 架构概览

保留现有配置、Provider、统一流事件和 ChatSession，只替换终端展示层。CLI 完成配置和 Provider 组装后运行 `MewCodeApp`；Textual App 负责固定布局、输入事件、流式 worker 和 UI transcript。App 退出时返回静态 transcript，由 CLI 在备用屏幕恢复后通过 Rich Console 打印。

```text
CLI → Config → Provider → ChatSession
 │                            ↑
 └→ MewCodeApp ─→ reply worker┘
       ├─ ConversationView（上方、鼠标滚动）
       └─ ComposerTextArea（下方、1-6 行）
                 │
退出 result ← TranscriptSnapshot ← UI transcript
      ↓
CLI 在普通终端打印静态记录并关闭 Provider
```

## 技术栈

- 保留 Python 3.11、uv、Pydantic、PyYAML、Anthropic/OpenAI 官方 SDK、pytest 与 Ruff。
- 新增 `textual>=8.2,<9`，使用其 `App`、`VerticalScroll`、`TextArea`、`Markdown`、worker 和测试 Pilot。
- 保留 `rich>=14.2,<15` 作为 Textual 依赖及退出后的静态输出组件。
- 删除 `prompt-toolkit` 依赖和全部 `PromptSession`/`Rich Live` 代码。
- `MewCodeApp.run_async(mouse=True)` 进入备用屏幕并启用鼠标事件；Textual 自动处理终端 Resize。

## 核心 UI 类型

### TranscriptEntry

```python
@dataclass(slots=True)
class TranscriptEntry:
    role: Literal["user", "assistant", "status"]
    content: str = ""
    thinking: str = ""
    state: Literal["streaming", "complete", "cancelled", "error"] = "complete"
```

UI transcript 独立于 `ChatSession.history`：提交后立即添加 user 与 streaming assistant；成功后标记 complete；取消或错误保留可观测状态但 ChatSession 仍回滚。该列表是界面唯一展示数据源，也是退出静态记录的来源。

### TranscriptSnapshot

```python
@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    entries: tuple[TranscriptEntry, ...]
```

App 退出时以 snapshot 作为 `App.exit(result=...)` 的返回值。snapshot 不含输入框当前草稿。

### ComposerTextArea

继承 Textual `TextArea`，关闭行号、固定软换行行为，并在 `on_key` 中提供确定的按键语义：

- `Enter`：阻止默认换行并向 App 发出提交动作。
- `Alt+Enter`：调用 `insert("\n")`，不提交。
- 普通编辑键沿用 TextArea 行为。
- App 的高优先级 `Ctrl+C`/`Ctrl+D` binding 覆盖 TextArea 默认 copy/delete-right binding。

监听 `TextArea.Changed`，按逻辑行数计算 `min(max(line_count, 1), 6)`，同步设置组件高度；超过六行后保留高度并使用 TextArea 内部垂直滚动。高度只取显式换行数，不因软换行产生不可预测跳动。

### ConversationView

继承 `VerticalScroll`，内部按顺序 mount `UserMessage`、`AssistantMessage` 和 `StatusMessage` widget。AssistantMessage 包含可选 thinking `Static` 和回答 `Markdown`，流事件通过 `Markdown.update()` 更新现有 widget。

每次 mount/update 前读取 `is_vertical_scroll_end`；仅原先位于底部时，在下一次 refresh 后调用 `scroll_end(animate=False)`。鼠标滚轮使用 VerticalScroll 原生处理；用户上滚后属性为 false，因此不会被新增量抢回底部。

## MewCodeApp 状态机

App 维护 `is_generating`、`reply_worker`、当前 assistant widget/entry 与 transcript。

### 提交

1. `Enter` 触发 `action_submit`。
2. 若 `is_generating` 为 true，直接返回，输入文本保持不变。
3. 去除外围空白后为空则返回；等于 `/exit` 时仅在空闲状态退出。
4. 创建 user entry 和 streaming assistant entry，清空 composer，将 `is_generating` 设为 true。
5. 通过 Textual `run_worker(..., exclusive=True, group="reply")` 消费 `ChatSession.stream_reply()`。

### 流式回复

- `THINKING_DELTA` 追加到当前 entry.thinking 并更新 thinking widget。
- `TEXT_DELTA` 追加到 entry.content 并 await `Markdown.update()`。
- `DONE` 后将 entry 标为 complete。
- worker `finally` 恢复 `is_generating=false`，保留生成期间编辑的草稿并重新聚焦 composer。

### 取消与错误

- 生成中 `Ctrl+C` 调用 `reply_worker.cancel()`；entry 标为 cancelled，清除未完成内容并显示“已取消当前回复”，ChatSession 因异步取消不提交本轮。
- 空闲时 `Ctrl+C` 使用 `composer.load_text("")` 清空草稿。
- ProviderError 被 worker 捕获并将 entry 标为 error，只显示统一脱敏消息；不修改草稿。
- 所有路径都清除当前 worker/widget 引用，不让 worker 异常逃逸到 Textual 日志。

### 退出

- `Ctrl+D` 高优先级 action 仅在 `not is_generating and not composer.text` 时退出。
- `/exit` 仅作为空闲时的提交命令退出。
- 退出使用 `App.exit(TranscriptSnapshot(...))`；生成期间禁止退出，因此不存在退出时悬挂回复 worker。
- CLI `await app.run_async(mouse=True)` 后获得 snapshot，先让备用屏幕恢复，再用 `render_static_transcript()` 输出用户、thinking、回答、取消与错误状态，最后在 `finally` 关闭 Provider SDK 客户端。

## 布局与样式

Textual CSS 使用纵向布局：`ConversationView { height: 1fr; overflow-y: auto; }`，底部 composer 容器 `height: auto`，TextArea 高度由 1-6 行 reactive 更新。输入区使用上边框与状态行区分，不用浮动卡片或嵌套面板。消息宽度为容器宽度，用户标签、thinking 和 MewCode 标签采用克制的不同样式；窄终端依靠 Textual 重排，不设固定列宽。

## 模块与文件变更

- `src/mewcode/tui.py`：用 Textual App、widgets、transcript 与静态渲染器完全替换旧行内 TUI；不保留兼容分支。
- `src/mewcode/cli.py`：改为 await Textual App，退出后打印 snapshot；Provider 创建、错误码和关闭语义不变。
- `pyproject.toml`/`uv.lock`：添加 Textual、删除 Prompt Toolkit、锁定兼容依赖。
- `tests/test_tui.py`：改用 `App.run_test()` 与 Pilot，覆盖尺寸、按键、滚动、worker、退出结果；`tests/test_cli.py` 更新 App 和静态输出衔接测试。
- Provider、config、models、session 的公开接口和实现不修改；既有测试必须继续通过。

## 测试设计

- **布局：** 以 80x24、120x40 和窄终端运行 headless App，断言历史区在 composer 上方、composer 底部固定且无重叠。
- **输入：** Pilot 输入文本，验证 Enter 提交、Alt+Enter 插入换行、1-6 行增长与第 7 行内部滚动。
- **生成状态：** 使用可控异步 Provider 暂停流；生成中继续编辑并按 Enter，断言无第二请求且草稿保留；释放流后再提交成功。
- **流式消息：** 逐个释放 thinking/text 事件，断言同一 AssistantMessage 更新且 transcript 不新增重复项。
- **滚动：** 创建足够多历史消息，用 Pilot 鼠标滚轮上滚，记录 scroll_y；流式更新后位置不变，滚到底后新增量跟随。
- **取消/错误：** Ctrl+C 取消 worker，断言历史回滚、entry 状态与草稿；四类 ProviderError 均显示安全文本并恢复提交。
- **退出：** 验证空草稿 Ctrl+D 和 `/exit` 返回 snapshot；非空/生成中 Ctrl+D 不退出；snapshot 不含草稿。
- **静态记录：** Rich 内存 Console 验证用户、thinking、回答、取消/错误状态输出，密钥与草稿不输出。
- **回归：** 完整 pytest、Ruff、依赖扫描和 `rg 'PromptSession|prompt_toolkit|rich.live' src tests pyproject.toml` 均通过。
- **tmux：** 使用本地 SSE 端点完成布局、生成中草稿、Alt+Enter、取消、鼠标滚动和退出后记录；有外部 API Key 时追加真实服务两轮验证。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| TUI 框架 | Textual 8.x | 原生支持固定布局、鼠标滚动、TextArea、Markdown、worker 和测试 Pilot |
| UI 历史 | 独立 transcript | 允许展示取消/错误，同时保持 ChatSession 只保存完整轮次 |
| 输入提交 | 自定义 TextArea key handler | 精确实现 Enter 提交和 Alt+Enter 换行，不依赖终端 shell 行编辑 |
| 生成并发 | 单个 exclusive worker | 草稿可编辑但不排队、不并行，状态清晰 |
| 自动跟随 | 更新前检查滚动底部 | 不打断用户查看旧消息，回到底部自动恢复 |
| 输入高度 | 逻辑行数 1-6 | 行为可预测、易测试，超限由控件内部滚动 |
| 退出记录 | App result + CLI 静态渲染 | 备用屏幕恢复后仍可查看/复制本次会话 |

## 设计自检

- AC1-AC13 均由 Textual widget、状态机或静态 transcript 明确负责；AC14 保持 ChatSession 与 Provider 边界；AC15-AC19 有对应测试路径。
- TUI 只依赖 ChatSession 和统一事件，Provider/配置不依赖 Textual，无新增依赖环。
- 生成期间提交、退出均被状态机拒绝；取消、错误和成功在 `finally` 中统一恢复 composer。
- 旧 Prompt Toolkit 路径被完整移除，不存在双 UI 行为分叉。
