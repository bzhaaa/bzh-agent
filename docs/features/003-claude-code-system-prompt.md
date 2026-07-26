# Claude Code 系统提示与缓存实现对照

> 对应 MewCode 文档：[003-structured-system-prompt.md](003-structured-system-prompt.md)
>
> 资料核对日期：2026-07-26
> 资料范围：Anthropic 官方 Claude Code 文档

## 1. 阅读边界

Claude Code 的完整 CLI 源码没有公开。2026-07 的官方文档已经公开了请求分层、缓存失效条件、动态 system context、CLAUDE.md 加载位置和 Plan Mode 的产品行为，但没有公开内部模块、类、函数或完整默认提示正文。本文只把官方文字标为“官方确认”，协议与行为要求能支持但源码未证实的内容标为“合理推断”，其余标为“未公开”。

## 2. 请求分层与系统提示

**官方确认**：Claude Code 每次请求都会重发 system prompt、项目上下文、历史消息、工具结果和新消息。为了前缀缓存，它把很少变化的内容放在前面，公开分层为 system prompt、project context、conversation。system prompt 包含核心指令、工具定义和输出风格；project context 包含 CLAUDE.md 和 auto memory；conversation 包含消息、回复和工具结果。

**官方确认**：CLI 提供 `--system-prompt`、`--system-prompt-file`、`--append-system-prompt` 和 `--append-system-prompt-file`。替换与追加只作用于当前调用，项目惯例推荐写入 CLAUDE.md。

**未公开**：默认 system prompt 的完整正文、是否像 MewCode 一样恰好拆成七个模块、模块优先级以及内部 Builder 数据结构。

MewCode 003 把七模块、排序、间隔和错误边界写成公开测试契约；这是本项目的可维护性选择，不代表 Claude Code 的源码结构。

## 3. Prompt Cache 组织

**官方确认**：Claude Code 自动管理 Prompt Cache。缓存按请求开头的精确 prefix 匹配，前缀中任意变化会让其后的内容重算。Claude Code 将低变化内容前置，普通新消息只追加到末尾，因此可读取上一轮缓存。

**官方确认**：工具定义位于 system prompt 层，工具集合变化可能使缓存失效；Skills、commands 和 Plan Mode 指令作为 conversation message 追加，从而保留已有缓存前缀。项目根 CLAUDE.md 和输出风格在会话开始时读取，中途修改不会立即生效，也不会破坏当前缓存。

**官方确认**：Claude Code 能观测 `cache_creation_input_tokens` 与 `cache_read_input_tokens`。缓存有 5 分钟和 1 小时 TTL，产品会依据认证方式选择；缓存实际存放位置取决于 Anthropic API、Bedrock、Google Cloud、Foundry 或自定义 gateway。

**未公开**：具体请求里放置了多少个 cache breakpoint、每个内置工具 block 的原生字段，以及不同版本的完整 breakpoint 选择算法。

MewCode 当前在 Anthropic 请求中给 stable system 和最后一个工具设置 `ephemeral`，OpenAI 路径依赖服务端自动前缀缓存。这一固定布局比 Claude Code 公开行为更窄，也更容易测试。

## 4. 动态环境注入

**官方确认**：Claude Code 的 system prompt 嵌入工作目录、平台、Shell、操作系统版本和 auto-memory 路径；Git 分支与近期提交的启动快照也会影响跨会话缓存。官方还说明文件被外部修改时会追加 `<system-reminder>`，提醒 Claude 需要时重新读取。

**官方确认**：`--exclude-dynamic-system-prompt-sections` 可以把工作目录、环境信息、memory 路径和 Git 仓库标记等每机器动态段，从 system prompt 移到第一条用户消息，以提升多机器脚本任务的缓存复用。

**合理推断**：Claude Code 必须在请求前采集并脱敏这些环境事实；公开资料没有说明采集器边界、Git 超时、取消回收和 XML 转义算法。

MewCode 每轮异步刷新日期、分支和 dirty 布尔值，并把动态内容放入独立 system reminder；它不输出 OS 版本、近期提交或 auto-memory 路径。MewCode 当前的动态 system 会牺牲跨目录缓存共享，但避免把环境伪装成真实用户正文。

## 5. 项目指令与记忆

**官方确认**：CLAUDE.md 是持久项目指令。组织、用户、项目和本地文件按层级加载；工作目录上方的文件在启动时完整加载，子目录文件在 Claude 读取相应目录时按需加载。官方明确指出 CLAUDE.md 内容位于 system prompt 之后的 user message，而不是默认 system prompt 本身，因此它是上下文指导，不是硬权限。

**官方确认**：Auto memory 默认开启，每个仓库有独立目录；`MEMORY.md` 的前 200 行或 25 KiB 会在每次对话开始时加载，topic 文件按需读取。CLAUDE.md 和 memory 都可通过 `/memory` 查看，`/context` 可确认实际加载文件。

**未公开**：CLAUDE.md、rules、memory 和其他动态内容在内部如何统一建模，以及加载后是否存在与 MewCode `PromptOptions` 等价的冻结快照。

MewCode 003 只预留自定义指令、Skill 和长期记忆的程序化插槽，尚未读取项目文件，也没有自动记忆。因此它具备注入边界，但不具备 Claude Code 的完整指令发现和持久化能力。

## 6. Plan Mode 与模式约束

**官方确认**：Plan Mode 用于在修改磁盘前调查并提出计划；Claude 可以读取和分析文件，但在用户批准前不编辑。可以通过 `--permission-mode plan` 启动，也可在会话中用 Shift+Tab 切换。

**官方确认**：普通权限模式切换不改变 system prompt 或工具定义，因此通常缓存安全。官方缓存文档说明 Plan Mode 指令作为 conversation message 追加；若使用会在计划和执行阶段切换模型的设置，则模型变化仍会建立新缓存。

**合理推断**：Plan 的只读保证不能只依赖语言指令，还需要客户端权限或工具执行层约束。内部审批状态机和安全分类规则没有公开。

MewCode 采用更窄的机制：Plan 只向模型暴露三个读工具，并以 system reminder 注入模式边界；`/do` 恢复六工具。两者都让模式不污染稳定前缀，但 Claude Code 使用 conversation message，MewCode 使用动态 system message。

## 7. 关键差异

| 主题 | Claude Code | MewCode 003 |
|---|---|---|
| 默认提示 | 完整正文和内部模块未公开 | 七模块、顺序和字节稳定性公开可测 |
| 请求分层 | system → project context → conversation | stable system → system reminder → history |
| 项目指令 | CLAUDE.md 以 user message 注入，多层级和按需加载 | 尚不读项目文件，只有程序化插槽 |
| Auto memory | 仓库级持久记忆，启动加载有明确上限 | 只有未持久化的长期记忆字符串入口 |
| 动态环境 | 默认位于 system；脚本模式可移到首条用户消息 | 每轮唯一动态 system reminder |
| 工具缓存 | 工具层、延迟加载和例外策略较完整 | Anthropic 仅最后工具设断点 |
| Plan 指令 | conversation message，权限模式控制 | system reminder，加固定三读工具集合 |
| 缓存观测 | 创建/读取 Token、TTL 和组织监控 | 统一事件字段和有界验证脚本 |

## 8. 可借鉴方向

1. 增加项目级 AGENTS.md/CLAUDE.md 发现、层级和按目录加载，并明确它们是软指令还是硬策略。
2. 将动态机器信息从稳定 system 中隔离，继续保证同项目请求前缀稳定；面向批处理时允许进一步排除每机器字段。
3. 在工具数量增长后引入延迟工具加载，避免工具集合变化频繁破坏缓存。
4. 增加 auto memory 与按需 topic 文件，但保持大小上限、可审计和用户可编辑。
5. 公开展示真实 cache creation/read，而不是只把指标留在内部事件层。

## 9. 官方资料

- [How Claude Code uses prompt caching](https://code.claude.com/docs/en/prompt-caching)
- [How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Common workflows: Plan before editing](https://code.claude.com/docs/en/common-workflows#plan-before-editing)
- [CLI reference: System prompt flags](https://code.claude.com/docs/en/cli-reference#system-prompt-flags)

这些资料可以确认产品请求层次、缓存行为、环境字段、项目指令位置和 Plan Mode 用户契约，但不能证明 Claude Code 使用 MewCode 的七模块、`PromptEnvelope`、提醒频率、长度边界或 Provider 映射实现。
