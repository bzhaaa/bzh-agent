# MewCode 纯对话 MVP Spec

## 背景

MewCode 是一个 Python 终端 AI 编程助手。当前版本已经支持 Anthropic 与 OpenAI 协议、SSE 流式回复、Claude extended thinking、YAML 多 profile 和进程内多轮会话，但界面仍以行内输入和终端滚动输出为主。回复增长时输入位置会下移，长对话不便浏览。

本次改造将界面升级为类似 Claude Code 的全屏 TUI：历史对话占据上方主要区域，多行输入框始终固定在底部。Provider、配置格式、会话语义和流式协议保持不变。

## 目标

- 使用 Textual 提供稳定的全屏终端布局。
- 上方展示可用鼠标滚轮浏览的历史对话，下方固定多行输入框。
- 流式增量只更新当前模型消息，不移动输入框或复制历史消息。
- 输入框默认一行，最多自动增长到六行，超过后内部滚动。
- 生成期间允许编辑下一条草稿，但禁止提交且不建立请求队列。
- 保留取消、错误恢复、多轮上下文和 Claude thinking 分区展示能力。
- 退出全屏界面后，在普通终端打印本次会话的静态记录。
- 使用 Textual 自动化测试与 tmux 端到端测试完成验收。

## 功能需求

- **F1：全屏布局。** `mewcode` 启动后进入全屏 TUI。历史对话区位于上方并占据剩余空间，输入区固定在底部，不随回复增长移动。
- **F2：历史消息展示。** 用户问题、模型 thinking、模型回答和状态/错误信息按发生顺序显示，用户与 MewCode 消息有清晰视觉区分。
- **F3：流式更新。** `thinking_delta` 和 `text_delta` 只更新当前模型消息，不重复创建消息或重排已有历史。
- **F4：历史滚动。** 历史区支持鼠标滚轮。用户位于底部时，新内容自动跟随；向上浏览后停止跟随；滚回底部后恢复跟随。
- **F5：动态多行输入。** 输入框默认一行，使用 `Alt+Enter` 插入换行后逐行增长，最多六行；超过六行后高度固定并在输入框内部滚动。
- **F6：提交行为。** 空闲时按 `Enter` 提交完整输入并清空输入框；空输入不创建消息或请求。
- **F7：生成期间编辑。** 模型生成期间输入框保持聚焦、可编辑；按 `Enter` 不提交、不清空，也不建立请求队列。生成完成、失败或取消后恢复提交。
- **F8：取消与清空。** 生成期间按 `Ctrl+C` 取消当前回复并恢复提交；被取消轮次不进入 ChatSession 历史。空闲时按 `Ctrl+C` 只清空当前草稿。
- **F9：退出行为。** 空闲且输入为空时，`Ctrl+D` 或提交 `/exit` 退出。输入非空或生成期间按 `Ctrl+D` 不退出。
- **F10：错误恢复。** Provider 请求失败后，当前消息显示简洁、脱敏的错误状态；下一条草稿保持不变，提交能力恢复。
- **F11：退出后静态记录。** 退出全屏界面后，在普通终端打印本次已展示的用户消息、thinking、模型回答及必要的取消/错误状态；未提交草稿不打印。
- **F12：终端响应式适配。** 终端尺寸变化时历史区和输入区自动重新布局，输入区仍固定在底部，内容不重叠或越界。
- **F13：多轮对话。** 当前进程内保存已成功完成的用户消息和模型最终回答，并在后续请求中传递完整历史；退出后不恢复旧会话。
- **F14：多供应商支持。** `anthropic` 使用 Anthropic Messages API，`openai` 使用 OpenAI Chat Completions API，两者向上层提供一致的流事件。
- **F15：多 Profile 配置。** YAML 包含 default 和 profiles；每个 profile 包含 `name`、`protocol`、`model`、`base_url`、`api_key` 和可选 `thinking`。
- **F16：配置选择与校验。** 默认读取 `~/.config/mewcode/config.yaml`；`--config` 覆盖路径，`--profile` 覆盖默认项；无效配置在请求前明确报错。
- **F17：Extended Thinking。** Anthropic 的 `thinking: true` 启用 thinking；thinking 和最终回答分别流式显示。普通输出上限 4096，thinking 总输出上限 8192、预算 4096；OpenAI 不允许 thinking。
- **F18：Provider 可扩展性。** TUI 和 ChatSession 只依赖统一 Provider 接口与流事件，不识别供应商请求或 SSE 格式。

## 配置格式

```yaml
default: claude-main
profiles:
  - name: claude-main
    protocol: anthropic
    model: claude-model-id
    base_url: https://api.anthropic.com
    api_key: ${ANTHROPIC_API_KEY}
    thinking: true
  - name: openai-main
    protocol: openai
    model: openai-model-id
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
```

`base_url` 是 SDK 使用的 API 前缀，MewCode 不猜测或改写版本前缀。`api_key` 接受完整的 `${ENV_VAR}` 引用或直接字符串。

## 非功能需求

- **N1：交互响应。** 键盘输入、鼠标滚动和焦点切换即时响应；模型增量到达后立即更新对应消息。
- **N2：布局稳定。** 历史增长、Markdown 重排、输入框增高和终端缩放不得造成输入框跳动、重叠或内容越界。
- **N3：滚动稳定。** 用户查看旧消息时新增内容不得抢占滚动位置；位于底部时持续跟随最新内容。
- **N4：草稿安全。** 生成、失败和取消期间不得丢失下一条草稿；只有成功提交或空闲时主动按 `Ctrl+C` 才清空。
- **N5：会话一致性。** UI 展示状态与 ChatSession 提交状态分离；未完成、失败和取消消息不得进入后续模型上下文。
- **N6：协议隔离。** 供应商请求、认证与事件解析只存在于对应 Provider 内。
- **N7：配置安全。** 密钥不得出现在日志、错误或 UI 中；环境变量缺失时只显示变量名。
- **N8：错误可理解性。** 面向用户的错误说明失败阶段和修复方向，默认不显示 traceback。
- **N9：终端兼容性。** 支持 UTF-8、ANSI 颜色和鼠标事件的 Unix 类终端，并在 tmux 中运行；Windows 原生终端不在范围内。
- **N10：可测试性。** 使用 Textual `run_test()`/Pilot 覆盖布局、按键、滚动、流式更新、取消、错误恢复和退出；自动化测试不依赖付费 API。
- **N11：架构边界。** Provider、配置和 ChatSession 的公开接口保持不变；Textual 类型不进入 Provider 或会话层。
- **N12：资源清理。** 退出、取消和错误时清理回复任务、Provider 流及 Textual worker，不留下 pending task 或终端残态。
- **N13：依赖收敛。** 使用 Textual 自带的 Rich/Markdown 能力，移除 Prompt Toolkit，不维护两套交互框架。

## 不做的事

- 不改变 Provider 公开接口、供应商协议或 YAML 配置格式。
- 不新增 tool use、MCP、文件操作、代码编辑或 shell 执行。
- 不支持并行模型请求或待发送消息队列。
- 不持久化、命名、列出、恢复或切换历史会话。
- 不实现消息编辑、删除、重新生成或分支对话。
- 不实现 Markdown 选择模式、全文搜索或导出功能。
- 不增加可配置主题、快捷键映射或布局设置。
- 不实现附件、图片、语音等多模态输入。
- 不支持鼠标点击提交；提交仍使用键盘。
- 不保证缺少鼠标事件的终端可以滚动历史区。
- 不改变 token 上限、thinking 预算、自动重试策略、错误分类或密钥处理规则。
- 不支持 OpenAI Responses API，也不为 OpenAI 模拟 extended thinking。

## 验收标准

- **AC1（F1、F12）：** 启动后历史区占据上方剩余空间，输入框固定于底部；终端缩放后无重叠或越界。
- **AC2（F2、F3）：** 用户消息提交后立即出现；模型增量持续更新同一条回复，不产生重复消息。
- **AC3（F3、F17）：** thinking 开启时，思考和回答分区增量更新，输入框位置不变。
- **AC4（F4）：** 鼠标滚轮能浏览历史；底部自动跟随，上滚后保持位置，滚回底部后恢复跟随。
- **AC5（F5）：** 输入框从一行增长到最多六行；超过六行后高度不变且内部可滚动。
- **AC6（F6）：** 空闲时 `Enter` 提交非空输入并清空；空内容不产生消息或请求。
- **AC7（F7、N4）：** 生成期间可编辑草稿，`Enter` 不提交、不清空、不排队；结束后草稿保持并可提交。
- **AC8（F8）：** 生成期间 `Ctrl+C` 取消请求并恢复提交，取消轮次不进入后续模型上下文。
- **AC9（F8）：** 空闲时 `Ctrl+C` 清空草稿，不退出也不删除历史。
- **AC10（F9）：** 空闲且输入为空时 `Ctrl+D` 和 `/exit` 退出；输入非空或生成时 `Ctrl+D` 不退出。
- **AC11（F10、N4）：** 认证、限流、连接或服务端错误显示脱敏状态，草稿不变且恢复提交。
- **AC12（F11）：** 退出后普通终端保留已展示的用户、thinking、回答及必要状态；未提交草稿不出现。
- **AC13（N2）：** 长 Markdown、列表、中文和代码块流式更新时，历史可读，输入区不跳动、不遮挡、不重复。
- **AC14（N5、N11）：** 取消/失败 UI 消息不进入 ChatSession；Provider、配置与 ChatSession 公共接口不变。
- **AC15（N10）：** Textual 自动化测试覆盖提交、`Alt+Enter`、动态高度、生成中编辑、禁止提交、滚动跟随、取消、错误和退出。
- **AC16（N12）：** 退出、取消及错误测试结束后无 pending task、未关闭流或残留 worker。
- **AC17（N13）：** 运行时依赖包含 Textual，不含 Prompt Toolkit；代码中无旧 `PromptSession` 或 Rich Live 输入循环。
- **AC18（F13-F18）：** 既有多轮、双 Provider、配置、thinking 参数和安全测试继续通过。
- **AC19（端到端）：** 在 tmux 中完成两轮流式对话，验证底部固定输入、生成期间编辑草稿、鼠标滚动、`Alt+Enter`、取消和退出后静态记录。
