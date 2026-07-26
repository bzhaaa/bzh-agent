# MewCode 结构化系统提示与缓存 Checklist

> 本清单在实现前保持未勾选。验收时必须先执行括号中的验证并观察实际输出，再勾选条目并追加脱敏证据。代码阅读、预期结果或“测试应该通过”不能代替运行证据。

## 结构化提示

- [x] **C1：七个固定模块完整且顺序确定。（AC1）**（验证：对相同输入连续构建两次稳定提示并比较原始 UTF-8 字节，期望内容完全一致；七个非空模块严格按身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出排列，模块间恰有一个空行） 证据：见 E1、E2。
- [x] **C2：非法模块不会产生不确定提示。（AC1）**（验证：分别输入重复名称、重复优先级、空正文和错误通道，期望每次得到明确构建错误且没有返回部分提示） 证据：见 E1、E2。
- [x] **C3：一次模型请求的四层内容可分别观察。（AC2）**（验证：捕获 Prompt Pipeline 输出，期望稳定 system、系统补充消息、工具定义、真实历史分别存在；改变环境或用户消息后只有动态补充与历史变化） 证据：见 E1、E2。
- [x] **C4：完整指令顺序固定。（AC2）**（验证：同时提供环境、自定义指令、两个 Skill 和长期记忆，期望模型观察顺序为七个固定模块、环境、自定义指令、按调用方顺序排列的 Skill、长期记忆） 证据：见 E1、E2。
- [x] **C5：空的可选模块被完全省略。（AC3）**（验证：分别传入 `None`、空字符串、空 Skill 集合及三项非空组合，期望空项不产生标签、标题或多余空行，非空项保持固定顺序） 证据：见 E1、E2。
- [x] **C6：动态内容被安全包裹和转义。（AC3、AC4）**（验证：可选内容中加入 `</system-reminder>`、`<tag>` 和多字节字符，期望最终只有一对有效 `<system-reminder>` 外层标签，调用方文本被转义且语义内容保留） 证据：见 E1、E2。
- [x] **C7：System Reminder 不污染持久历史。（AC4）**（验证：完成含多个工具迭代的请求后检查会话历史和退出 transcript，期望只含真实用户消息、助手消息和工具结果，不含标签、环境、模式约束或可选插槽正文） 证据：见 E1、E2。
- [x] **C8：程序化插槽无需改动其他请求层即可使用。（AC22）**（验证：仅通过会话级入口依次设置自定义指令、Skill 和记忆并发起请求，期望两种 Provider 都能收到固定顺序的动态内容，七模块顺序、Provider 接口和历史结构保持不变） 证据：见 E1、E2。

## 环境与提醒

- [x] **C9：环境补充包含全部规定字段。（AC5）**（验证：在普通 Git 项目中生成补充消息，期望可观察脱敏项目根目录、平台、Shell、当前日期、时区、Git 分支、dirty 布尔状态和当前 Agent 模式） 证据：见 E1、E2。
- [x] **C10：环境补充不泄露敏感或无界信息。（AC5）**（验证：在环境中设置可识别的假 API Key、用户名标记和多个 dirty 文件，期望补充消息及错误输出均不含环境变量值、用户名、Key、主机名或完整文件列表） 证据：见 E1、E2。
- [x] **C11：非 Git 与 detached HEAD 均可安全请求模型。（AC5）**（验证：分别在非仓库、detached HEAD、Git 不可用和 Git 查询失败的目录构建请求，期望请求继续完成；分支或 dirty 使用安全 unknown，detached 使用脱敏短提交标识） 证据：见 E1、E2。
- [x] **C12：Git 采集超时和取消会回收资源。（AC5）**（验证：制造超过 1 秒的 Git 查询并在另一次查询中取消 Agent Run，期望子进程被终止并等待回收、没有 pending task 或残留进程，普通超时降级后仍可请求模型） 证据：见 E1、E2。
- [x] **C13：模式提醒频率精确且按用户提交重置。（AC6）**（验证：捕获一次含 10 次模型请求的 Run，期望第 1、6 次为完整提醒，第 2-5、7-10 次为精简提醒；发送下一条用户消息后首轮重新为完整提醒） 证据：见 E1、E2。
- [x] **C14：Normal 和 Plan 的完整、精简提醒均保留关键边界。（AC6、AC7）**（验证：分别捕获两种模式的完整与精简内容，期望 Normal 强调继续执行、验证和先读后改，Plan 强调只读调查与计划，不出现相反模式授权） 证据：见 E1、E2。

## Plan/Do 与工具规则

- [x] **C15：`/plan` 保留真实用户任务并通过系统级位置约束模式。（AC7）**（验证：输入 `/plan 调查目标模块` 并捕获请求，期望历史中的 UserMessage 恰为“调查目标模块”，Plan 约束只出现在 system reminder，模型仅看到读文件、找文件和搜代码三个工具） 证据：见 E1、E2。
- [x] **C16：Plan 后续讨论保持真实正文和只读边界。（AC7）**（验证：规划完成后输入包含“直接修改”的普通补充，期望用户原文不被包装，模式仍为 Plan、只暴露三个读工具且磁盘没有副作用） 证据：见 E1、E2。
- [x] **C17：`/do` 使用 Normal 系统约束并恢复六工具。（AC7）**（验证：成功计划后输入 `/do`，期望真实 `/do` 消息进入历史，动态提醒切换为 Normal，六个工具全部可用并能依据已有计划继续执行） 证据：见 E1、E2。
- [x] **C18：无成功计划时 `/do` 不请求模型。（AC7）**（验证：在新会话、计划失败和计划取消后三种状态输入 `/do`，期望得到本地提示、Provider 请求数不增加、历史与模式状态合法） 证据：见 E1、E2。
- [x] **C19：全局规则和工具描述形成双重强化。（AC8）**（验证：读取稳定提示与六个实际工具定义，期望两处共同覆盖专用工具优先、搜索优先于 Shell、编辑已有文件前先读、唯一小范围修改和依据工具错误调整） 证据：见 E1、E2。
- [x] **C20：提示规则没有扩大编辑工具执行契约。（AC8）**（验证：不建立运行时读取记录而直接调用编辑工具，期望仍按原文唯一匹配规则执行；零匹配与多匹配仍返回原有结构化错误，而不是“尚未读取”拦截） 证据：见 E1、E2。
- [x] **C21：Normal 与 Plan 工具集合分别稳定。（AC9）**（验证：在相同模式连续构造多次请求并逐字段比较工具名称、顺序、描述和参数 Schema，期望 Normal 始终为同序六工具，Plan 始终为同序三工具，二者形成独立稳定集合） 证据：见 E1、E2。

## Provider 与缓存边界

- [x] **C22：Anthropic 稳定 system 使用原生缓存断点。（AC10）**（验证：捕获 Anthropic 请求，期望稳定七模块是带 `ephemeral` cache control 的 system text block，动态 reminder 是其后的普通 system block） 证据：见 E1、E2。
- [x] **C23：Anthropic 工具缓存断点位置合法。（AC10）**（验证：分别捕获 Normal 六工具和 Plan 三工具请求，期望仅各自最后一个工具带 `ephemeral` cache control；环境、模式、可选模块、历史和工具结果均位于稳定缓存边界之后或不带断点） 证据：见 E1、E2。
- [x] **C24：Anthropic 动态变化不改变稳定缓存内容。（AC10）**（验证：改变日期、Git dirty、模式提醒详细度和用户历史后比较请求，期望同一模式下稳定 system 与工具定义逐字段一致，只有断点后的内容变化） 证据：见 E1、E2。
- [x] **C25：OpenAI 请求保持稳定内容在前。（AC11）**（验证：捕获 OpenAI Chat Completions 请求，期望首条 system 为稳定七模块、第二条 system 为动态 reminder、其后才是真实历史；请求中不存在 `cache_control`） 证据：见 E1、E2。
- [x] **C26：OpenAI 动态变化不破坏稳定前缀。（AC11）**（验证：改变日期、Git 状态、用户消息和历史后重复捕获，期望首条 system 与相同模式的工具定义字节一致，动态 system 和历史按实际输入变化） 证据：见 E1、E2。
- [x] **C27：Anthropic 缓存用量被诚实归一化。（AC12）**（验证：分别输入缓存创建、缓存读取、零命中、字段缺失和非法负数字段，期望统一事件返回对应创建/读取值；缺失保持 unknown，非法流被拒绝，总输入按协议字段正确计算） 证据：见 E1、E2。
- [x] **C28：OpenAI 缓存用量被诚实归一化。（AC12）**（验证：分别输入 `cached_tokens` 正数、零、details 缺失和非法字段，期望缓存读取明细对应数值或 unknown，缓存创建始终 unknown，不根据总输入估算） 证据：见 E1、E2。
- [x] **C29：缓存明细不重复计入 Token 总量。（AC12、AC13）**（验证：构造包含输入、输出、缓存创建和读取的多请求事件，期望 total 仍仅为总输入加输出；四个字段独立累计，任一字段未知只影响对应累计字段） 证据：见 E1、E2。
- [x] **C30：缓存指标只存在于事件层。（AC13）**（验证：消费带缓存用量的 AgentEvent 并同时检查 TUI 状态、对话区域和退出 transcript，期望独立消费者能读取明细，但界面与静态记录不新增 cache 文本或数值） 证据：见 E1、E2。

## Agent 行为兼容

- [x] **C31：Anthropic extended thinking 与多工具循环正常。（AC14）**（验证：启用 thinking，执行至少两个工具迭代后返回最终文字，期望 thinking 实时可见、工具调用和结果完整、历史检查点合法、最终答复正常且 thinking 不进入后续模型历史） 证据：见 E1、E2。
- [x] **C32：OpenAI 多工具循环与历史重放正常。（AC14）**（验证：执行同领域的多工具任务，期望工具 JSON 碎片正确拼接、每轮检查点进入后续请求、最终答复完成且 system reminder 不进入历史） 证据：见 E1、E2。
- [x] **C33：提示构建阶段取消不会发起模型请求。（AC14）**（验证：阻塞环境采集后取消当前 Run，期望 Pipeline 和 Git 子任务均被回收、Provider 请求数为零、停止原因是取消且会话随后可继续） 证据：见 E1、E2。
- [x] **C34：流错误和工具阶段取消保持既有安全语义。（AC14）**（验证：分别制造无效模型流和工具执行中取消，期望部分模型响应不提交；已开始的完整工具批次获得真实或取消结果并形成合法检查点，不启动额外请求） 证据：见 E1、E2。
- [x] **C35：动态提示不会随 Agent 迭代进入历史并累积。（AC18）**（验证：运行 10 次模型请求并捕获每轮 Envelope 与最终历史，期望每轮恰有一个当轮 reminder，历史长度只因真实消息和工具检查点增长，不包含前轮 reminder） 证据：见 E1、E2。

## 边界、安全与兼容

- [x] **C36：可选内容的三层字节边界精确生效。（AC18）**（验证：分别在单项 16 KiB、可选合计 28 KiB 和完整 supplement 32 KiB 的边界上下构造 ASCII 与多字节输入，期望边界内成功，超出时得到包含限制与实际字节数的明确错误且不回显正文） 证据：见 E1、E2。
- [x] **C37：活动 Run 期间不能半途替换 Prompt Options。（AC18、AC22）**（验证：在模型请求进行中更新 Options，期望更新被拒绝且当前 Run 保持原快照；Run 结束后更新成功，非法更新失败时旧值保持不变） 证据：见 E1、E2。
- [x] **C38：原六字段 YAML 无需修改即可启动。（AC19）**（验证：分别使用现有 OpenAI 与 Anthropic profile 启动，期望不要求提示模板、缓存开关或新字段，thinking 配置保持原语义） 证据：见 E1、E2。
- [x] **C39：既有工具和交互边界没有回归。（AC19）**（验证：运行文件越界、符号链接、原子写入、唯一替换、命令确认、Alt+Enter、滚轮、草稿、错误脱敏和取消场景，期望行为与上一章验收一致） 证据：见 E1、E2。
- [x] **C40：协议专属字段不越过 Provider 边界。（AC19）**（验证：检查 Agent、Session 和 Prompt Pipeline 捕获对象，期望只出现供应商无关 Envelope 与 TokenUsage；Anthropic cache control 和 OpenAI details 仅在各自协议请求或解析测试中出现） 证据：见 E1、E2。

## 自动化质量检查

- [x] **C41：Prompt 与 Provider 自动化覆盖通过。（AC19）**（验证：运行 `uv run pytest -q tests/prompting tests/providers`，期望模块顺序、标签转义、提醒频率、环境容错、协议位置、缓存断点和缓存字段测试全部通过且不访问付费 API） 证据：见 E1。
- [x] **C42：Agent、Session、CLI 与 TUI 回归通过。（AC19）**（验证：运行 `uv run pytest -q tests/agent tests/test_session.py tests/test_cli.py tests/test_tui.py`，期望 Agent Loop、Plan/Do、取消、历史和缓存指标隔离全部通过） 证据：见 E2。
- [x] **C43：完整项目测试通过。（AC19）**（验证：运行 `uv run pytest -q`，期望全部测试通过，输出没有 pending task、未关闭流、worker error 或残留进程警告） 证据：见 E3。
- [x] **C44：静态检查、格式和构建通过。（AC19）**（验证：运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run python -m compileall -q src tests scripts`、`uv build` 和 `git diff --check`，期望全部退出码为 0，构建产物包含 prompting 包） 证据：见 E4。
- [x] **C45：缓存验证脚本有界且脱敏。（AC15、AC16、AC19）**（验证：运行脚本的本地假服务测试与 `--help`，期望请求次数有硬上限、缺失值显示 unknown、失败不开放式重试，输出不含 Key、提示正文或完整认证错误） 证据：见 E5。

## 真实缓存验证

- [ ] **C46：真实 Anthropic 首次请求产生缓存创建。（AC15）**（验证：使用真实 Anthropic profile 和生产稳定提示运行有界验证脚本，记录模型、请求序号和脱敏 Token；期望首次或明确的一次请求返回大于零的 cache creation input tokens） 证据：见 E6。
- [ ] **C47：真实 Anthropic 重复请求产生缓存读取。（AC15）**（验证：在同一次有界验证中重复相同稳定前缀，期望后续请求返回大于零的 cache read input tokens，请求总数不超过脚本上限且未添加 padding） 证据：见 E6。
- [x] **C48：真实 OpenAI 缓存结果按服务能力如实记录。（AC16）**（验证：使用真实 OpenAI profile 做同类有界重复请求；若返回 cached tokens 则记录实际数值，若不返回则记录 unknown 或当前服务不支持，不把缺失写成零命中且不影响其他条目判定） 证据：见 E6。

## 人工前后对比

- [x] **C49：人工评估输入可复现。（AC17）**（验证：检查评估文档，期望旧提示与新提示使用相同 Provider、模型、模式、项目夹具副本和六段固定任务文本，并记录日期与提交；不得用不同输入替代对比） 证据：见 E7。
- [x] **C50：六类行为均记录实际前后结果。（AC17）**（验证：逐项核对专用工具选择、编辑前读取、Plan 只读、安全边界、代码风格和输出简洁度，期望每项同时有旧提示与新提示的实际工具/文件/答复证据，不生成自动分数） 证据：见 E7。
- [x] **C51：人工结论区分事实、观察与判断。（AC17）**（验证：复核对比记录，期望工具序列和文件变化作为事实保存，质量判断以定性文字表达；失败、不变或不确定结果不被改写成通过） 证据：见 E7。

## tmux 端到端

- [x] **C52：OpenAI 协议下普通编码任务完整通过。（AC20）**（验证：在 tmux 中启动确定性 OpenAI SSE 服务和真实 MewCode TUI，输入一次真实自然语言修改请求，期望模型先读后改、使用专用工具、自动完成多轮循环并流式给出最终答复；用 pane、请求日志和磁盘内容交叉核对） 证据：见 E8。
- [x] **C53：Anthropic 协议下普通编码任务完整通过。（AC20）**（验证：在 tmux 中切换确定性 Anthropic SSE profile 执行同领域任务，期望 system 缓存断点合法、工具循环和最终答复正常，pane 中无 traceback 或隐藏提示正文） 证据：见 E8。
- [x] **C54：tmux 中 Plan/Do 完整流程通过。（AC20）**（验证：输入 `/plan <真实任务>` 并补充一次要求，期望仅出现读工具且磁盘不变；计划完成后输入 `/do`，期望切回 Normal、使用六工具执行计划并产生预期文件变化） 证据：见 E8。
- [x] **C55：tmux 中多轮继续与取消可靠。（AC20）**（验证：完成一次工具任务后发送后续问题，再分别在模型流和工具阶段取消，期望历史只重放完整检查点、取消后不启动额外请求且仍可继续提交） 证据：见 E9。
- [ ] **C56：tmux 中既有输入和确认交互无回归。（AC20）**（验证：在运行期间使用鼠标滚动、Alt+Enter 编辑多行草稿并触发命令确认，期望历史可滚动、换行不提交、批准/拒绝结果正确且界面元素无重叠） 证据：见 E9。
- [x] **C57：tmux 验收证据可复查且脱敏。（AC20）**（验证：使用 `tmux capture-pane` 保存普通任务与 Plan/Do 的实际输出，并核对服务请求记录和生成文件；期望证据包含 profile、pane 尺寸、工具顺序和最终状态，不含 API Key、用户名或完整隐藏提示） 证据：见 E8、E9。

## 文档与追溯

- [x] **C58：003 MewCode 功能总结完整。（AC21）**（验证：打开编号 003 功能文档，期望说明七模块、动态 reminder、环境边界、Provider 缓存、Token 用量、Plan/Do 迁移、已知限制和实际验收结果） 证据：见 E10。
- [x] **C59：003 Claude Code 对照文档可追溯。（AC21）**（验证：打开 Claude Code 对照文档，期望覆盖系统提示、缓存、环境注入、项目指令和模式约束，明确公开事实与推断并记录来源核对日期） 证据：见 E10。
- [x] **C60：目录和证据索引完整。（AC21）**（验证：检查功能目录与人工场景文档，期望编号 003 的两份功能文档和场景文档均可导航，并记录实现提交、自动化命令、tmux pane、真实缓存数值和人工对比位置） 证据：见 E10。

## 验收证据索引

- **E1：Prompt、环境、工具与 Provider。** 2026-07-26 实跑 `uv run pytest -q tests/prompting tests/providers`，结果 `39 passed in 1.20s`，退出码 0。实际覆盖七模块字节一致与非法输入、XML 转义和三层字节边界、环境脱敏/Git 容错/超时取消、第 1/6 次提醒、Options 插槽、Normal/Plan 工具稳定性、双协议 system 位置、Anthropic 断点、缓存字段合法性和 extended thinking 协议解析。
- **E2：Agent、Session、CLI 与 TUI。** 2026-07-26 实跑 `uv run pytest -q tests/agent tests/test_session.py tests/test_cli.py tests/test_tui.py`，结果 `70 passed in 11.90s`，退出码 0。实际覆盖 reminder 历史隔离、10 次循环、Prompt 构建取消、Plan/Do 真实用户正文、Options 活动 Run 边界、缓存事件隔离、工具/流取消、六字段 YAML、Alt+Enter 与 Escape+Enter、多行草稿、滚动容器和确认弹窗。
- **E3：完整回归。** 2026-07-26 最终实跑 `uv run pytest -q`，结果 `149 passed in 14.43s`，退出码 0；输出没有 pending task、未关闭流、worker error 或残留进程警告。
- **E4：静态检查与构建。** 2026-07-26 实跑 `uv run ruff check .`、`uv run ruff format --check .`、`uv run python -m compileall -q src tests scripts`、`uv build`、`git diff --check`，全部退出码 0；Ruff 输出 `All checks passed!`、格式输出 `57 files already formatted`，wheel 已列出 `mewcode/prompting/` 八个模块。
- **E5：缓存脚本边界。** 2026-07-26 实跑 `uv run pytest -q tests/test_cli.py -k prompt_cache`，结果 `1 passed, 6 deselected`；`verify_prompt_cache.py --help` 显示请求范围严格为 2-4。假 Provider 测试确认 unknown 和脱敏输出，失败不重试。
- **E6：真实缓存。** 2026-07-26，`deepseek-openai / deepseek-v4-pro` 有界两次请求：第 1 次 `cache_create=unknown, cache_read=0`，第 2 次 `cache_create=unknown, cache_read=1408`，C48 通过。`deepseek-anthropic / deepseek-v4-pro` 第 1 次即返回脱敏认证失败，没有真实 creation/read 字段；C46、C47 未通过，后续需修复该 profile 认证后原样重跑，不用假服务数值替代。
- **E7：人工前后对比。** 2026-07-26，在 `mew003-eval-s1` 至 `s6` 六个 120x40 tmux 会话中，用相同 `deepseek-openai / deepseek-v4-pro`、相同任务原文和独立夹具运行。S1/S3/S4/S6 磁盘逐字节不变，S2/S5 diff 仅含指定修改；实际工具序列、答复和定性判断记录于 `docs/evals/003-system-prompt-scenarios.md`，pane 保存于 `/tmp/mewcode-003-eval/s1-pane.txt` 至 `s6-pane.txt`。
- **E8：确定性 tmux 主流程。** 2026-07-26，tmux 3.7b 会话 `mew003-openai`、`mew003-anthropic`、`mew003-input` 和 `mew003-server` 连接真实 TUI 与确定性 SSE 服务。OpenAI 与 Anthropic 均完成 `read_file → edit_file → read_file → final`；Plan 请求仅有三读工具且磁盘不变，`/do` 恢复六工具并创建 `plan-result.txt`。`/tmp/mewcode-003-tmux/requests.log` 逐请求记录双 system、工具集合与 Anthropic 双 `ephemeral` 断点；pane 已保存为同目录下的 `mew003-*-pane.txt`。
- **E9：thinking、继续与取消 tmux。** 2026-07-26，`mew003-thinking` 在 `thinking: true` 下实时显示四段“正在分析”，同时完成三轮工具和最终答复；请求日志四轮均记录 `thinking=true` 与合法缓存断点。`mew003-cancel` 完成两轮连续对话，长模型流取消后再次读取成功；批准长命令后在工具阶段取消，父 PID 92453、子 PID 92454 的 `ps -p` 均退出 1，随后会话再次读取成功。pane 分别保存为 `mew003-thinking-pane.txt` 和 `mew003-cancel-pane.txt`。C56 未通过：命令确认已实测，但 tmux 注入 Alt+Enter 仍表现为提交，且鼠标滚轮没有可信的物理输入证据；保留自动化覆盖，不宣称 tmux 交互通过。
- **E10：文档与追溯。** 2026-07-26 实跑 `rg -n "003|结构化系统提示|Claude Code" docs/features/README.md docs/features/003-*.md` 与人工场景完整性搜索，退出码均为 0。`003-structured-system-prompt.md` 记录实现、自动化、tmux、真实缓存和限制；`003-claude-code-system-prompt.md` 按官方确认/合理推断/未公开区分证据并列出 4 个官方来源；README 已登记两份文档和场景入口。

当前结果：57/60 通过。未通过为 C46、C47、C56，均保留实际原因和后续重跑条件。

## 验收记录规则

执行验收时按以下规则更新本文件：

1. 每个条目先运行验证，再把 `[ ]` 改为 `[x]`；未通过项保持未勾选。
2. 在对应条目末尾追加“证据：实际命令/场景、关键输出、日期”，不要只写“通过”。
3. 自动化证据记录测试数量和退出码；tmux 证据记录会话名、pane 尺寸、关键观察和产物校验。
4. 真实缓存证据只记录 Provider、模型、请求次数和脱敏 Token 数值；不得记录 API Key 或完整提示正文。
5. 未通过项追加“预期、实际、修复或后续决定”，修复后必须重新运行原验证。

## Spec 覆盖索引

| Spec 验收标准 | Checklist 条目 |
|---|---|
| AC1 | C1-C2 |
| AC2 | C3-C4 |
| AC3 | C5-C6 |
| AC4 | C6-C7 |
| AC5 | C9-C12 |
| AC6 | C13-C14 |
| AC7 | C14-C18 |
| AC8 | C19-C20 |
| AC9 | C21 |
| AC10 | C22-C24 |
| AC11 | C25-C26 |
| AC12 | C27-C29 |
| AC13 | C29-C30 |
| AC14 | C31-C34 |
| AC15 | C45-C47 |
| AC16 | C45、C48 |
| AC17 | C49-C51 |
| AC18 | C35-C37 |
| AC19 | C38-C45 |
| AC20 | C52-C57 |
| AC21 | C58-C60 |
| AC22 | C8、C37 |
