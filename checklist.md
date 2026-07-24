# MewCode Textual 全屏 TUI Checklist

> 每项必须以自动化命令、Textual Pilot 状态或 tmux pane 观察结果验证。实现前所有新 UI 条目保持未勾选；执行验收时记录实际结果，不以代码阅读替代运行证据。

## 依赖与迁移

- [x] **C1：Textual 依赖安装成功。**（证据：`uv sync --all-groups` 成功；Textual 版本 8.2.8）
- [x] **C2：旧 UI 依赖和代码已移除。**（证据：`uv tree` 仅显示 Textual/Rich；源码与 pyproject 扫描无 PromptSession、prompt_toolkit、rich.live）
- [x] **C3：既有非 UI 公共接口不变。**（证据：Provider、config、models、session 未改动且完整回归通过）

## 固定布局

- [x] **C4：标准终端布局正确。**（证据：80x24 Pilot region 断言通过；tmux 80x24/90x28 首屏捕获显示输入区固定底部）
- [x] **C5：宽屏与窄屏响应式布局正确。**（证据：120x40、44x16 Pilot 通过；tmux 从 80x24 缩到 52x16 后无重叠）
- [x] **C6：长历史与流式更新不移动输入框。**（证据：长 SSE tmux 捕获中 composer 持续位于底部；三种尺寸布局与流式测试通过）

## 消息与流式展示

- [x] **C7：用户、模型和状态消息可区分。**（证据：Textual DOM 内容测试及 tmux 用户边线、MewCode/thinking 标签捕获通过）
- [x] **C8：模型增量只更新同一消息。**（证据：逐段 thinking/text 测试断言 DOM 仅一个 AssistantMessage，最终内容无重复）
- [x] **C9：Thinking 与回答分区更新。**（证据：Pilot 交错事件通过；tmux Anthropic 本地 SSE 显示独立“思考”和回答区）
- [x] **C10：长 Markdown 可读且不重复。**（证据：本地 OpenAI SSE 的列表、代码块、长文本在 tmux 正常渲染）

## 历史滚动

- [x] **C11：底部状态自动跟随。**（证据：Pilot 断言更新后 `is_vertical_scroll_end` 为 true）
- [x] **C12：鼠标上滚后保持位置。**（证据：向 ConversationView 投递真实 MouseScrollUp，新增消息后 scroll_y 保持）
- [x] **C13：滚回底部恢复跟随。**（证据：Pilot 滚回底部后新增消息继续跟随）

## 输入框

- [x] **C14：Enter 提交且空输入忽略。**（证据：Pilot 请求数、transcript 与 composer 断言通过）
- [x] **C15：Alt+Enter 插入换行。**（证据：Pilot `alt+enter` 无请求并插入换行；tmux CSI-u `alt+enter` 实测两行且未提交）
- [x] **C16：输入框按 1–6 行增长。**（证据：Pilot 逐行断言 1-6，Ctrl+C 清空恢复一行）
- [x] **C17：第七行起内部滚动。**（证据：第七行后 logical_height 为 6 且 TextArea max_scroll_y 大于 0）

## 生成期间草稿

- [x] **C18：生成期间仍可编辑草稿。**（证据：BlockingProvider 生成中输入 `draft`，composer 文本保持可编辑）
- [x] **C19：生成期间 Enter 不提交或排队。**（证据：生成中连续 Enter 后请求数仍为 1、transcript 仍为 2、草稿不变）
- [x] **C20：回复完成后草稿保持并可提交。**（证据：释放 DONE 后 `draft` 保留，提交状态恢复）
- [x] **C21：生成期间 Ctrl+D 不退出。**（证据：BlockingProvider 运行时 Ctrl+D 后 App 仍运行、草稿不变）

## 取消、清空与错误

- [x] **C22：生成中 Ctrl+C 取消当前回复。**（证据：BlockingProvider/Pilot 断言 worker 结束、cancelled entry、内容替换与提交恢复；tmux 状态从“正在生成”恢复“就绪”）
- [x] **C23：取消轮次不进入上下文。**（证据：取消测试 ChatSession.history 为空，Provider 流收到 asyncio cancel）
- [x] **C24：空闲 Ctrl+C 只清空草稿。**（证据：Pilot 清空多行 composer 并恢复一行，App 保持运行）
- [x] **C25：Provider 错误安全恢复。**（证据：四类 ProviderError 均通过 Textual 测试；真实 Anthropic profile 认证失败显示脱敏错误并恢复就绪）
- [x] **C26：错误后下一轮可成功。**（证据：错误后保留 `next` 草稿并提交成功，ChatSession.history 正确）

## 退出与静态记录

- [x] **C27：空输入 Ctrl+D 退出。**（证据：Pilot 返回 TranscriptSnapshot；tmux 退出到 zsh）
- [x] **C28：非空输入 Ctrl+D 不退出。**（证据：Pilot 非空草稿 Ctrl+D 后 App 运行且文本不变）
- [x] **C29：`/exit` 正常退出且不发请求。**（证据：Pilot `/exit` 返回空 snapshot 且无 Provider 请求）
- [x] **C30：静态记录完整。**（证据：内存 Console 覆盖 user/thinking/answer/cancel/error；tmux 退出后保留真实 OpenAI 两轮与 Anthropic thinking 记录）
- [x] **C31：静态记录不包含草稿或敏感信息。**（证据：snapshot 深拷贝且不含 composer；静态输出测试无草稿或示例敏感值）

## 资源与回归

- [x] **C32：Textual 测试无残留异步资源。**（证据：48 项测试结束无 pending task、worker error 或未关闭流警告）
- [x] **C33：CLI 始终关闭 Provider。**（证据：FakeProvider 正常与 App 异常路径均断言 close 恰好一次）
- [x] **C34：完整自动化与静态检查通过。**（证据：`48 passed`；Ruff lint 全部通过；18 个文件格式检查通过）
- [x] **C35：CLI 帮助与配置错误行为保持。**（证据：`uv run mewcode --help` 状态码 0；既有配置错误测试通过）

## tmux 端到端

- [x] **C36：Textual 全屏布局在 tmux 中稳定。**（证据：80x24、90x28 捕获显示历史在上/composer 在底；52x16 缩放无重叠）
- [x] **C37：tmux 两轮流式对话与草稿通过。**（证据：本地 OpenAI 端点完成两轮并返回 `LIME`；生成中禁提交/草稿由确定性 Pilot 覆盖）
- [x] **C38：tmux 多行输入与鼠标滚动通过。**（证据：tmux CSI-u alt+enter 显示两行且未提交；1-7 行与真实 MouseScrollUp 的完整滚动策略由 Pilot 覆盖。tmux 默认需启用 extended-keys 才能转发 Alt 修饰符）
- [x] **C39：tmux 取消和退出键通过。**（证据：捕获到“正在生成”后 Ctrl+C 恢复“就绪”；Ctrl+D 退出；其余确定性状态由 Pilot 覆盖）
- [x] **C40：退出后静态记录留在普通终端。**（证据：shell-backed tmux capture-pane 包含真实 OpenAI 两轮、Anthropic thinking 和脱敏错误记录）
- [x] **C41：本地双协议端点通过。**（证据：官方 OpenAI/Anthropic SDK 分别解析本地 HTTP SSE；Textual tmux 显示 Markdown 与 thinking 分区）
- [ ] **C42：外部真实服务验收。**（部分证据：DeepSeek OpenAI profile 完成两轮真实对话并记住“青柠”；DeepSeek Anthropic profile 返回认证失败，未完成真实 thinking 验收）

## 完成条件

- [x] **C43：UI 改造验收完成。**（证据：C1-C41 全部通过；C42 的 OpenAI 侧通过、Anthropic 侧因当前配置认证失败如实保持未勾选）

## Spec 覆盖自检

| Spec 标准 | Checklist 条目 |
|-----------|----------------|
| AC1 | C4-C6、C36 |
| AC2 | C7、C8、C37 |
| AC3 | C6、C9、C41 |
| AC4 | C11-C13、C38 |
| AC5 | C15-C17、C38 |
| AC6 | C14 |
| AC7 | C18-C20、C37 |
| AC8 | C22、C23、C39 |
| AC9 | C24、C39 |
| AC10 | C21、C27-C29、C39 |
| AC11 | C25、C26 |
| AC12 | C30、C31、C40 |
| AC13 | C5、C6、C10 |
| AC14 | C3、C23、C25 |
| AC15 | C14-C29、C34 |
| AC16 | C32、C33、C34 |
| AC17 | C1、C2 |
| AC18 | C3、C9、C34、C35、C41、C42 |
| AC19 | C36-C42 |

每条 AC 均至少映射到一个可运行的自动化或 tmux 检查；内部文件或类型重命名不会改变行为验收判定。
