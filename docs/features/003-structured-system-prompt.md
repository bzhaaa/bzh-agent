# MewCode 结构化系统提示与缓存功能总结

Claude Code 对应能力的公开实现对照见 [003-claude-code-system-prompt.md](003-claude-code-system-prompt.md)，固定人工场景见 [../evals/003-system-prompt-scenarios.md](../evals/003-system-prompt-scenarios.md)。

## 本章目标

本章把原来的三行全局指令升级为结构化 Prompt Pipeline：稳定规则进入可复用前缀，环境、模式和会话级补充指令按请求动态注入，Agent 与 Provider 只通过供应商无关的 `PromptEnvelope` 交互。

对应实现提交：

- `f2bf324 feat: 添加结构化提示核心管线`
- `33fd9bf feat: 接入提示信封与缓存用量`
- `08ddf49 test: 覆盖结构化提示缓存与端到端协议`
- `8bf797f chore: 固定提示评估夹具格式`
- `4c554f5 fix: 兼容终端换行按键序列`

## 稳定提示结构

稳定 system 由七个非空模块组成，优先级固定，模块间恰有一个空行：

1. 身份：MewCode 的角色和交付目标。
2. 系统约束：事实边界、敏感信息和项目访问边界。
3. 任务模式：Normal 与 Plan 的职责。
4. 动作执行：调查、聚焦修改、验证和失败调整。
5. 工具使用：专用工具优先、先读后改和精确编辑。
6. 语气风格：中文、直接、协作和诚实表达不确定性。
7. 文本输出：结果优先，并给出必要证据。

`StablePromptBuilder` 在创建时校验名称、优先级、正文和通道，随后缓存字节稳定的结果。重复名称、重复优先级、空正文或动态通道都会在请求前得到不回显正文的 `PromptBuildError`。

## 动态 System Reminder

每次 Provider 请求都重新生成唯一的 `<system-reminder>`，其中包含脱敏项目根、平台、Shell、日期、时区、Git 分支、dirty 布尔值、Agent 模式和当轮模式提醒。Git 不可用、非仓库、detached HEAD、超时或权限失败均安全降级，不输出环境变量、用户名、主机名或 dirty 文件列表。

动态插槽按固定顺序支持自定义指令、已激活 Skill 和长期记忆。所有调用方文本经过 XML 转义；单项、可选项合计和完整 supplement 分别受 16 KiB、28 KiB、32 KiB 的 UTF-8 字节边界约束。插槽只通过会话级 `PromptOptions` 更新，活动 Run 使用冻结快照，不能半途替换。

Normal 和 Plan 都有完整与精简提醒。一次 Run 的第 1、6 次模型请求使用完整提醒，其余使用精简提醒；下一条真实用户消息会重新从第 1 次开始。Reminder 不进入持久历史或退出 transcript，因此不会随工具循环累积。

## Plan/Do 与工具规则

`/plan <任务>`、Plan 后续补充和 `/do` 现在只把用户真实正文写入历史，不再构造伪装的用户级系统指令。模式约束位于当轮 system reminder：Plan 只暴露三个读工具，Normal 恢复六工具。

六个工具描述与稳定提示双重强调边界：路径查找和内容搜索优先于 Shell，编辑已有文件前先读，小改使用唯一精确替换，命令工具只用于专用工具不能完成的测试、构建或命令任务。工具名称、Schema、注册顺序和原有执行契约没有改变。

## Provider 缓存映射

`PromptEnvelope` 冻结 stable system、动态 supplement、真实历史和工具定义，Provider 层负责最后一公里映射：

| 协议 | 请求布局 | 缓存用量 |
|---|---|---|
| OpenAI | 首条 stable system、第二条动态 system、随后真实历史；不发送 Anthropic 字段 | 读取 `prompt_tokens_details.cached_tokens`，创建量保持 unknown |
| Anthropic | stable system text block 带 `ephemeral`，动态 block 位于其后；仅最后一个工具带 `ephemeral` | 分别解析普通输入、cache creation、cache read 和输出 |

`TokenUsage` 的缓存创建与读取字段均为可选值。总 Token 仍只等于总输入加输出，缓存明细不会重复计入；字段缺失保持 unknown，非法负数或布尔值会使流失败。缓存明细只在事件层传播，TUI 和静态 transcript 没有新增内部指标文本。

## 架构与关键文件

```text
ChatSession
    │ 真实历史、模式、PromptOptions 快照
    ▼
AgentRunner
    │ 每轮 mode + iteration + tools
    ▼
PromptPipeline
    ├─ StablePromptBuilder
    ├─ EnvironmentCollector
    ├─ ReminderScheduler
    └─ SupplementBuilder
    │
    ▼
PromptEnvelope ──→ OpenAIProvider / AnthropicProvider
```

- `src/mewcode/prompting/`：领域模型、七模块、构建器、提醒、环境和 Pipeline。
- `src/mewcode/agent/runner.py`：每轮构建信封，并在提示构建取消时阻止 Provider 请求。
- `src/mewcode/providers/`：协议映射、缓存断点和用量归一化。
- `src/mewcode/session.py`：真实 Plan/Do 历史和会话级 Options 原子更新。
- `scripts/verify_prompt_cache.py`：2 至 4 次有界真实请求，只输出脱敏 Token 指标。

## 自动化验证

2026-07-26 的最终实现回归：

```text
uv run pytest -q
149 passed in 14.43s

uv run ruff check .
All checks passed!

uv run ruff format --check .
57 files already formatted

uv run python -m compileall -q src tests scripts
uv build
git diff --check
```

后三项退出码均为 0，wheel 已确认包含 `mewcode/prompting/` 的八个模块。

## tmux 端到端验收

系统没有预装 tmux，因此在隔离环境安装并使用 `/tmp/mewcode-tmux-env/bin/tmux` 3.7b。确定性 SSE 服务和真实 Textual TUI 的实测结果：

- OpenAI 会话完成 `read_file → edit_file → read_file`，`generated.txt` 从 `alpha` 变为 `beta`。
- Anthropic 会话完成相同的先读后改循环；请求中 stable system 和最后工具均带 `ephemeral`。
- `thinking: true` 的 Anthropic 会话实时显示四段思考，同时完成三轮工具和最终答复。
- Plan 只暴露三个读工具且磁盘不变；`/do` 恢复六工具并创建 `plan-result.txt`。
- 假服务返回的 OpenAI 后续缓存读取为 8；Anthropic 首轮创建为 12、后续读取为 10。
- 另一会话完成两轮继续、模型流取消和长命令工具取消；父子进程均回收，取消后仍可继续读取。
- 请求结构记录保存在 `/tmp/mewcode-003-tmux/requests.log`，会话为 `mew003-server`、`mew003-openai`、`mew003-anthropic` 和 `mew003-input`。

人工对比另在六个 120x40 tmux 会话中连接真实 `deepseek-openai / deepseek-v4-pro`。六个场景均保存静态 pane；Plan、越界和只读场景磁盘不变，两个编辑场景的 diff 仅含任务要求的修改。

## 真实缓存验证

有界脚本各发出两次请求，实际结果如下：

```text
deepseek-openai / deepseek-v4-pro
request 1: cache_create=unknown, cache_read=0
request 2: cache_create=unknown, cache_read=1408

deepseek-anthropic / deepseek-v4-pro
认证失败，未得到真实 cache creation 或 cache read 字段
```

OpenAI 兼容服务的第二次请求实际命中 1408 个缓存 Token。Anthropic profile 的失败被保留为未通过验收项，不用确定性假服务数值替代真实服务证据。

## 配置与兼容性

YAML 没有新增字段，原 `name`、`protocol`、`model`、`base_url`、`api_key` 和可选 `thinking` profile 可直接启动。缓存布局由 Provider 自动决定，不增加模板或缓存开关。

## 当前限制

- 尚未加载项目级指令文件；自定义指令、Skill 和长期记忆只有程序化入口。
- 没有自动记忆、MCP、上下文压缩或自动化提示质量评分。
- 真实 Anthropic profile 当前认证失败，真实缓存创建与读取尚未验收。
- tmux 注入 `Alt+Enter` 无法可靠等价模拟物理终端按键；单元测试覆盖 `alt+enter` 和 `Escape + Enter`，但该项不记为 tmux 实测通过。
- 人工场景中输出简洁度没有明显改善；稳定提示不能保证模型每次都采用同一工具序列或文字长度。

逐项证据和未通过项见项目根目录的 `checklist.md`；最终为 57/60，通过项之外保留真实 Anthropic 缓存两项和 tmux 物理输入一项未通过。
