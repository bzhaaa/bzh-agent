# MewCode 现有功能总结

> 文档编号：000  
> 对应版本：0.1.0  
> 基线提交：`b5a40bf9b4658392d71b0e504d8cacd416910f97`  
> 总结日期：2026-07-24

## 1. 当前定位

MewCode 是一个使用 Python 3.11+ 实现的终端 AI 助手。目前完成的是“纯对话 MVP”：用户可以在全屏终端界面中与大模型进行流式、多轮对话，但尚不具备工具调用、文件读取、代码编辑或 Shell 执行等 Coding Agent 能力。

## 2. 用户可用功能

### 2.1 全屏终端对话界面

- 使用 Textual 构建全屏 TUI，上方为对话历史，下方为固定输入区。
- 历史消息增长时输入区位置保持不变，终端尺寸变化时自动重排。
- 用户消息、MewCode 回复、Claude thinking 和错误状态具有独立展示样式。
- 模型输出以 Markdown 渲染，支持中文、列表、代码块等常见内容。
- 退出全屏界面后，会在普通终端中打印本次已展示的静态对话记录。

### 2.2 输入与快捷键

- `Enter`：空闲时提交非空消息。
- `Alt+Enter`：插入换行，不提交消息。
- 输入框从一行自动增长到最多六行，超过后在输入框内部滚动。
- `Ctrl+C`：生成中取消当前回复；空闲时清空草稿。
- `Ctrl+D`：仅在空闲且输入为空时退出。
- `/exit`：空闲时退出，不向模型发送请求。

### 2.3 流式回复与滚动

- 模型增量到达后持续更新同一条回复，不等待完整回答结束。
- Claude thinking 与最终回答分别流式更新。
- 历史区支持鼠标滚轮：位于底部时自动跟随新内容，上滚查看旧消息后停止自动跟随，滚回底部后恢复。
- 生成期间输入框保持可编辑，可以提前准备下一条草稿。
- 生成期间按 `Enter` 不提交、不清空，也不会建立请求队列。

### 2.4 多轮会话

- 当前进程内保存成功完成的用户消息和模型回答。
- 后续请求携带完整的成功历史，使模型能够记住前文。
- 失败、取消或缺少完整结束事件的轮次不会进入模型上下文。
- 会话当前不持久化，退出后不会恢复旧对话。

## 3. 模型供应商能力

### 3.1 统一 Provider 层

TUI 和会话层只依赖统一的 `LLMProvider` 接口及三类流事件：

- `thinking_delta`：思考增量。
- `text_delta`：回答文本增量。
- `done`：本轮正常完成。

供应商请求参数、SDK 事件和错误映射均封装在各自 Provider 中，为后续增加新协议保留了扩展边界。

### 3.2 OpenAI 协议

- 使用 OpenAI 官方异步 SDK。
- 调用 Chat Completions API，并启用流式响应。
- 支持自定义 `base_url`，可连接兼容 OpenAI 协议的服务。
- 当前不支持 OpenAI Responses API，也不支持 OpenAI thinking。

### 3.3 Anthropic 协议

- 使用 Anthropic 官方异步 SDK。
- 调用 Messages API，并消费流式事件。
- 支持自定义 `base_url`。
- `thinking: true` 时启用 extended thinking，并分开展示 thinking 与最终文本。
- 普通输出上限为 4096 tokens；thinking 模式总输出上限为 8192 tokens，thinking 预算为 4096 tokens。

## 4. 配置能力

- 默认读取 `~/.config/mewcode/config.yaml`。
- `--config PATH` 可以指定其他 YAML 配置文件。
- `--profile NAME` 可以覆盖配置中的默认 profile。
- 一个 YAML 文件可以配置多个 profile，并指定 `default`。
- 每个 profile 包含 `name`、`protocol`、`model`、`base_url`、`api_key`，以及可选的 `thinking`。
- `api_key` 可直接填写，也可使用完整的 `${ENV_VAR}` 环境变量引用。
- 配置会校验字段完整性、未知字段、重复名称、默认项、URL、协议和 thinking 兼容性。
- 配置错误在发起请求前返回简洁中文信息，退出码为 2，不显示 traceback 或密钥。

配置示例：

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

## 5. 错误与资源处理

- 统一区分认证失败、限流、连接失败、服务端失败和无效流。
- UI 只展示脱敏后的中文错误，不输出底层异常和 API Key。
- 错误或取消后恢复输入和提交能力，生成期间编辑的下一条草稿不会丢失。
- CLI 在正常退出和异常路径中都会关闭 Provider SDK 客户端。
- Provider 流、Textual worker 和终端备用屏幕均有清理路径。

## 6. 当前架构

```text
CLI
 ├─ 加载并校验 YAML 配置
 ├─ 按 profile 创建 Provider
 └─ 启动 MewCodeApp
        ├─ ConversationView：历史展示与滚动
        ├─ ComposerTextArea：输入和快捷键
        └─ 单一回复 Worker
                ↓
           ChatSession
                ↓
       统一 LLMProvider 接口
          ├─ OpenAIProvider
          └─ AnthropicProvider
```

UI transcript 与 `ChatSession.history` 相互独立：前者记录用户实际看到的成功、取消和错误状态；后者只保存完整成功轮次。这是当前会话一致性的关键设计。

## 7. 启动方式

```bash
cd /Users/bzh/code/mew
uv run mewcode
```

选择其他 profile：

```bash
uv run mewcode --profile PROFILE_NAME
```

查看命令行帮助：

```bash
uv run mewcode --help
```

在 tmux 中使用 `Alt+Enter` 时，终端需要正确转发 Alt 修饰符；测试环境曾使用 tmux extended keys 配置验证该行为。

## 8. 测试与验收现状

- 自动化测试共 48 项，覆盖配置、Provider、会话、CLI 和 Textual TUI。
- Ruff lint 与格式检查已通过。
- 已通过本地 OpenAI/Anthropic HTTP SSE、官方 SDK 解析和 tmux 端到端场景。
- DeepSeek OpenAI profile 已完成真实两轮对话，并验证模型记住前文关键词“青柠”。
- `checklist.md` 当前记录为 42/43：唯一未完整通过的是外部 Anthropic thinking 真实服务验收，原因是现有 `deepseek-anthropic` 配置返回认证失败。

## 9. 当前明确不包含的功能

- Tool use、函数调用和 MCP。
- 文件读取、搜索、写入和代码编辑。
- Shell 命令执行与权限控制。
- Agent 循环、任务规划和自动迭代。
- 并行模型请求或待发送队列。
- 会话持久化、恢复、命名和切换。
- 消息编辑、删除、重新生成和分支对话。
- 附件、图片、语音等多模态输入。
- Windows 原生终端支持。

## 10. 后续总结文档约定

后续每完成一部分独立功能，在 `docs/features/` 下新增一份编号递增的总结文档，不覆盖历史文档。建议命名格式：

```text
001-功能名称.md
002-功能名称.md
003-功能名称.md
```

每份文档至少记录：功能目标、用户可见行为、架构与关键文件、配置或快捷键、测试与 tmux 验收证据、限制与后续边界，以及对应提交哈希。
