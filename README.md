# Codex Loop Prompt Architect

`codex-loop-prompt-architect` 是一个只面向 Codex macOS App 的 skill。它把
不成熟、信息不完整或容易断停的需求，转换成一个可直接发送给控制线程的
Controller Pack Markdown 文件，并另外告诉用户怎么启动、怎么回查、可能卡
在哪里、预计需要多久。

它负责设计 loop，不负责直接实现 PRD 或修改目标项目。

本文统一把 Codex App 界面里看到的 chat/task 称为“任务”。工具参数仍使用
`threadId`，因为它是恢复和发消息时唯一可靠的任务身份；标题、分支名、
`pendingWorktreeId`、`clientThreadId` 和 subagent 的 `agent_id` 都不能替代它。

## Standard 和 Adaptive

这个 skill 现在有两条相互独立的选择轴：

- 输出详略：`compact`、`full`、`minimal_patch`。
- 运行策略：`standard`、`adaptive`。

`standard` 是现有高可靠固定 Goal Queue，适合目标明确、1 至 3 个 Goal、通常
半天内能收敛的工作。旧输入默认 Standard，原有两个示例保持字节级兼容。

`adaptive` 适合超过 3 个里程碑、验收可能随证据变化、需要真实浏览器/本机权限/
设备验证，或预计超过半天的项目。它保留 Standard 的全部安全闸，并增加：

- canonical milestone roadmap 和唯一 Active milestone。
- 原生 Controller Goal，工具不可用时诚实降级为 emulated milestone。
- CODE_REVIEW 后先完成必要的本机验证，再独立执行 ROADMAP_AUDIT；最终候选再做 FINAL_AUDIT。
- `.codex-loop/GOALS.md` 人类可读路线图和可选静态 dashboard。
- Goal turn 与 heartbeat 共用 fenced `controller_lease`；每次动作必须带 epoch、
  不可复用 lease id、owner、`ROUTE_ONE_TRANSITION` 和可信时间的完整 claim，旧回合
  无法重复派发。
- Goal turn 和 heartbeat 还共用一个有上限的 routing-turn 计数，原生 Goal 续跑不能
  绕过 `max_wakeups`。
- Future Goal Queue 只负责路由；每个 Goal 还必须在 canonical state 中有完整、不可变、
  带 SHA-256 的可执行定义。
- Pack 内嵌闭合 canonical authorization envelope；State-Writer 自己计算路径、权限、
  预算、connector、副作用、证据、claim、生产和 secrets 是否越界。
- 三类审查和 Local Verifier 都先经过独立 PREPARED/SENT outbox，并且只能绑定 Goal
  ledger 中最新的 Worker PASS artifact。
- 只在需要时创建真实 Local Verifier 任务。
- 子代理默认关闭；只有显式声明授权上限、全程次数、重试和输入范围后，才允许最多
  两个深度为 1 的一次性只读子代理。当前确定性路由每个 lease 串行执行一个，
  它们不能替代正式任务。

两种策略的用户启动方式完全相同：获得一份 Controller Pack，把它发给一个控制
任务，后续由 Controller 自动创建和调度。

设计参考：[Loop Engineering](https://addyosmani.com/blog/loop-engineering/)、
[OpenAI Long-running work](https://learn.chatgpt.com/docs/long-running-work) 和
[OpenAI Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)。
本 skill 只使用当前 Codex App 实际暴露的 Goal/task/automation 工具字段；UI 中存在
但工具未暴露的暂停、恢复、编辑或清除能力不会被伪装成可编程操作。

## 它解决什么问题

普通提示词通常只有一个大目标：

```text
把这个 PRD 完整做出来，自动测试，没问题就继续。
```

直接把这种提示词交给多线程 Codex，常见结果是：

- 控制线程自己改代码。
- 创建内部 sub-agent，而不是真实 Codex App 项目线程。
- 子线程跑到普通对话区，没有归入目标工作区。
- Reviewer 在实现完成前先审查，或者根本看不到 Worker worktree。
- `REVIEW_PASS` 后只报告状态，没有派发下一步。
- heartbeat 在 Worker 仍然运行时把 NOOP 当成终点。
- State-Writer 尚未写完状态，Controller 已经派发下一 Goal。
- 同一份 Worker 报告被 heartbeat 重复读取，造成重复 review 或重复任务。
- 依赖下载短暂波动后立刻停下来找用户。
- 真实模型调用没有预算，跑到后半程才停在成本闸。
- 用户不知道该看哪个线程、哪个状态文件或哪一条事件。
- 初始计划已经被新证据推翻，Controller 仍机械执行旧 Goal Queue。

这个 skill 生成的 loop 通过以下机制处理这些问题：

- 真实 Codex App 项目线程和稳定 `threadId`。
- dependency-ordered Goal Queue。
- 每次派发都有 `goal_id` 和唯一 `dispatch_id`。
- transactional dispatch outbox 防止发送成功但状态未落盘后重复派发。
- Adaptive 派发摘要由确定性 runtime 生成和校验，不再让 Controller/Reviewer 手工替换字符串。
- State-Writer compare-and-swap 状态版本与事件幂等。
- State-Writer ACK 后才能 review、repair 或进入下一 Goal。
- Worker active 时使用 `WAITING_ACTIVE`，heartbeat 不会关闭或重复派发。
- worktree Worker 使用同目录 Reviewer，或提供可验证的绝对 worktree 路径。
- 每个 Goal 独立声明 commit、PR、push、merge、deploy 和外部写入权限。
- 有超时、无进展 watchdog、退避和总耗时上限的下载重试梯队。
- 每个 Goal 审查，加一次最终完整 diff 审查。
- `.codex-loop/` 状态、事件、分诊和报告审计面。
- Adaptive 下的 Roadmap Audit、单 Active milestone、Local Verifier 和计划重估。
- Adaptive 审查 ACK 绑定 review kind、milestone、roadmap version、dispatch、
  已完成 Worker dispatch/report、artifact 和前序报告；没有 Worker PASS 证据不能先审查。
- 路线图、封闭 Future Goal Queue、Goal 定义/执行 ledger、投影和旧 PREPARED 派发撤销
  一次原子更新；旧派发已经 SENT/IN_PROGRESS 时拒绝改版。
- 最后一个 milestone 必须经过独立 FINAL_AUDIT 和 FINALIZE_LOOP 状态 ACK，
  不能用普通 RoadmapRevision 直接变成完成，也不能把未执行的队列批量标记完成。

## 输出什么

日常 Compact Mode 输出两份内容：

1. `<project>-codex-loop-controller-pack.md`
   - 发给控制线程的唯一材料。
   - 包含 Controller、Worker、Reviewer、State-Writer、Goal Queue、First
     Goal、heartbeat、状态协议、审查门和停止条件。
2. 最终使用方法
   - 留给用户阅读，不发给控制线程。
   - 包含运行卡点、时间预估、工作区准备、启动步骤、回查方法和人工介入状态。

Adaptive 输出仍然只有这两份材料。Controller Pack 内会额外包含里程碑、Goal
Mode、controller lease、Roadmap Audit、Local Verifier、只读子代理和 dashboard
协议；用户不需要拆分或手动转发这些内部段落。

Full Mode 还会实际生成：

- L1-L12 诊断表。
- Loop Integrity Score。
- changelog。
- flow map。
- 正常、阻塞、幂等、active heartbeat 和压缩上下文测试目标。
- 最终下一步。

`--mode full` 不再只输出“请补充 Full Mode”的提示文字。

## 仓库结构

```text
loop-skill/
├── .github/workflows/test.yml
├── codex-loop-prompt-architect/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   │   ├── loop-contract.md
│   │   ├── adaptive-loop-contract.md
│   │   ├── adaptive-state.schema.json
│   │   └── adaptive-mutation.schema.json
│   └── scripts/
│       ├── loop_prompt_scaffold.py
│       ├── validate_skill.py
│       ├── adaptive_state_runtime.py
│       └── loop_architect/
│           ├── schema.py
│           ├── validation.py
│           ├── forecast.py
│           ├── protocol_model.py
│           ├── state_runtime.py
│           ├── standard_renderer.py
│           └── adaptive_renderer.py
├── requirements-test.txt
├── examples/
│   ├── 01-passkey-login-input.json
│   ├── 01-passkey-login-controller-pack.md
│   ├── 01-passkey-login-usage.md
│   ├── 02-daily-ci-triage-input.json
│   ├── 02-daily-ci-triage-controller-pack.md
│   ├── 02-daily-ci-triage-usage.md
│   ├── 03-adaptive-passkey-input.json
│   ├── 03-adaptive-passkey-controller-pack.md
│   └── 03-adaptive-passkey-usage.md
├── tests/
│   ├── test_loop_prompt_scaffold.py
│   ├── test_adaptive_loop.py
│   ├── test_adaptive_protocol_model.py
│   ├── test_adaptive_state_runtime.py
│   ├── test_adaptive_fuzz.py
│   └── test_public_schema.py
├── scripts/install.sh
├── LICENSE
└── README.md
```

只有 `codex-loop-prompt-architect/` 会安装到 Codex skills 目录。README、
examples、tests 和发行安装脚本保留在仓库中。

## 安装到 Codex macOS App

推荐使用安装脚本：

```bash
git clone https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
python3 -m pip install -r requirements-test.txt
./scripts/install.sh
```

Adaptive 的确定性状态运行时使用 `jsonschema` 做 Draft 2020-12 校验；安装脚本会在
复制 skill 前检查该依赖和两份 schema。缺失时安装会明确失败，不会安装一个只能靠
自然语言手写状态的残缺版本。只使用 Standard 的用户也建议按上面的完整步骤安装，
避免以后切换 Adaptive 时才发现运行时缺失。

默认安装位置：

```text
${CODEX_HOME:-$HOME/.codex}/skills/codex-loop-prompt-architect
```

安装脚本会先执行：

- 无缓存 Python 语法检查。
- 最小语义校验与 Full Mode 生成 smoke。
- Codex `quick_validate.py`，如果本机提供。
- staging copy。
- staging 中的 `__pycache__`/`.pyc` 清理。
- 原子替换和失败回滚。

旧版本备份放在：

```text
${CODEX_HOME:-$HOME/.codex}/skill-backups/codex-loop-prompt-architect/
```

旧安装器遗留在 `skills/codex-loop-prompt-architect.backup.*` 的目录会自动
迁移到上述备份位置，避免 Codex 把每个 backup 都扫描成一个同名 skill。

安装后新建一个 Codex App 聊天。skill 未出现时重启 Codex App，使其重新
扫描本地 skills。

手动安装只建议用于排障：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R codex-loop-prompt-architect \
  "${CODEX_HOME:-$HOME/.codex}/skills/codex-loop-prompt-architect"
```

手动复制前应自行备份并清理旧目录，避免残留文件混入新版本。

## 最简单的调用方法

日常只需要这样说：

```text
Use $codex-loop-prompt-architect：loop 化下面这个需求；信息不足先问我，不要直接输出完整版。

[你的需求]
```

带 PRD 时：

```text
Use $codex-loop-prompt-architect：loop 化这个 PRD；信息不足先问。

目标工作区：/Users/you/Documents/my-project
PRD 路径：/Users/you/Documents/my-project/docs/PRD.md
需求：完整实现 P0 + P1，并完成本地验证和浏览器 smoke。
```

长期或会根据证据改计划时：

```text
Use $codex-loop-prompt-architect：把下面需求做成 Adaptive loop；信息不够先问。

目标工作区：/Users/you/Documents/my-project
资料路径：/Users/you/Documents/my-project/docs/PRD.md
要求：持续实现、审查和本机浏览器验证；允许在原授权范围内根据新证据调整后续里程碑。
```

skill 会明确告诉你最终选择了 `standard` 还是 `adaptive`，以及原因。输出模式
`compact/full` 只控制文档详略，不会偷偷改变运行策略。
`minimal_patch` 只用于“已有 Controller Pack 的局部修复”，由 skill 直接输出补丁；
它不会从零生成整份 Pack，因此 scaffold CLI 的 `--mode` 只接受 `compact/full`。

不要只把 PRD 附在当前聊天里然后假设子线程能看到。`create_thread` 和
`send_message_to_thread` 不会自动继承 Controller-only 附件。最稳妥的方式
是把资料放到目标工作区的 `docs/`，或者提供子线程可读的绝对路径。
结构化输入中的 repo 必须是绝对路径；canonical state/triage 必须位于该 repo
的 `.codex-loop/` 下，写入 scope 不能含 `..` 或指向 repo 外。源资料写成明确
绝对/工作区相对路径、`http(s)` URL，或自包含任务专用的 `SELF_CONTAINED`。
复杂 glob 的上下级关系采用保守校验：`src/**` 可容纳更窄路径；无法证明包含关系
的两个不同 wildcard scope 会被拒绝，避免 `*` 跨目录放宽权限。
`.codex-loop/**` 是 State-Writer 专用 control-plane scope，不能放进产品
Worker 或 Goal 的写入范围。
纯 read-only/no-diff loop 可以把 `allowed` 写成空数组；只要存在
`workspace_write` Worker，global `allowed` 就必须是非空且可验证的 repo 内路径。

## 生成前会确认什么

信息不足时，skill 必须先反问一到三个最关键问题。以下信息在生成
ready-to-send loop 前必须明确：

- 目标和可验证的验收标准。
- Codex Project 名称和本地根目录。
- 目标 repo 是项目子目录时，分别给出 `project_root` 和 `repo`；前者用于把所有
  正式任务挂到同一个 Codex Project，后者是实际工作目录。
- `repo_mode`。
- 现有 Git 项目的 base/target branch。
- PRD、截图、PDF、数据集等源文件路径。
- Worker 分工、权限和路径所有权。
- Standard/Adaptive 运行策略；Adaptive 必须给出原因、结构化输入 `role_kind`、
  初始 milestones 和唯一 Active milestone。
- Adaptive 的输入 `role_kind` 是 bootstrap 角色。运行时 THREAD identity 同时保存
  `bootstrap_role_kind` 与确定性的 `formal_role_kind`：
  `implementation|triage|explorer -> WORKER`、`code_reviewer -> REVIEWER`、
  `local_verifier -> LOCAL_VERIFIER`；绝不根据任务标题猜测。每个 Adaptive Goal
  还把 `worker_role_kind` 写入不可变定义和 payload；即使都属于 formal WORKER，
  implementation、triage、explorer 也不能互相代派。
- 自动补入的 Reviewer、State-Writer、Local Verifier 会确定性避让用户角色名；
  注入后 role identity 和 thread placeholder 仍必须全局唯一。
- 禁止路径、secrets、数据和副作用。
- 多 Worker/多阶段任务的 Goal Queue。
- validation commands。
- evidence layer 和 claim boundary。
- durable state 位置。
- review policy。
- heartbeat、wake、idle、每 Goal 修复轮数、retry 和 hard-stop 上限。
- connector 和 worktree 策略。
- Adaptive 的 Local Verifier 和 dashboard 策略；若启用子代理，必须明确
  `delegation_policy`、`max_read_only_subagents`、
  `max_read_only_subagent_runs`、`subagent_retry_limit` 和
  `subagent_input_policy`。
- 真实 LLM/API/`codex exec` 的预算或 deferred policy。
- deploy、merge、迁移、生产写入等动作是否预授权。

`TBD`、`TODO`、`unknown`、`待定`、`稍后补充`、`?` 等占位值不算
已补齐信息；objective、claim、branch、approval、validation、acceptance、
source path 或 Goal 里仍有这些值时，脚本拒绝生成可投递 pack。

skill 不应该要求普通用户判断当前 Codex App 是否暴露
`create_thread/read_thread/automation_update`。这是 Controller 启动时应当
自行探测的运行条件。

## 三种 repo_mode

### `existing_git`

用于已经是 Git 仓库的项目。Controller 在创建 worktree 前必须记录：

- git root。
- `git status --short`。
- 当前 branch 和 HEAD/base SHA。
- remotes。
- `git worktree list`。
- 用户原有的 dirty/untracked 文件。

目标实现分支不等于已存在的 worktree starting branch。只有验证存在的
base ref 才能用于 `startingState.type="branch"`。
目标分支与 base 不同时，第一个写入 Goal 必须授权 `branch_create=true`；这是
允许在需要时创建，不是要求已存在分支再创建一次。
只提供一个 `branch` 且不提供 `base_branch/target_branch` 时，脚本把它视为
已经存在并要继续使用的分支，不会误要求创建权限。

### `new_git`

用于空白目录或尚未初始化 Git 的新项目。第一阶段应创建 local Worker，
不能先运行 `git show-ref`，也不能直接从不存在的 branch 创建 worktree。
只有 Goal 明确允许时，Worker 才初始化 Git 或创建第一条分支。
这两个动作分别由阶段权限 `git_init` 和 `branch_create` 控制，不能从
`commit=true` 或目标 branch 名称中推断。
`new_git` 的第一个写入 Goal 缺少任一权限时，脚本拒绝生成可投递 pack；若任务
永远不需要 Git，应选择 `non_git`。

### `non_git`

用于不需要 Git 的本地任务。branch/ref/worktree 字段是
`NOT_APPLICABLE`，线程使用 local 环境。审查身份改用 before/after 文件 manifest、
内容 SHA-256 和 `diff_sha256`，不能伪造 Git SHA。

## 自动 loop 如何启动

用户只创建一个控制任务：

把 Controller Pack 发给控制任务，就表示已明确授权它在 pack 的任务数量上限内
创建、恢复、发消息和归档所声明的子任务，并创建/更新/暂停唯一 heartbeat；不必
再次询问。这不授权 deploy、merge、push、密钥、生产写入或 Controller 改代码。

1. 在 Codex App 左侧选择目标项目工作区。
2. 在这个项目下面新建“控制任务”。
3. 把生成的 Controller Pack `.md` 文件发给它。
4. Controller 调用 `list_projects` 得到 `projectId`，并计算 pack/loop/bootstrap 标记。
   若当前控制任务 ID 不可读，LOOP_ID 使用
   `SHA-256(projectId + canonical repo + PACK_SHA256)` 的确定性 fallback，不能
   随机生成。
5. Controller 运行 repo-mode-specific preflight。
6. Controller 先用 `list_threads` 恢复或创建唯一 State-Writer，初始化状态并等 ACK；
   Adaptive 再用 `PREPARE_OUTBOX(kind=THREAD)` 恢复或创建当前 Worker。
7. 不预创建 Reviewer。Worker 报告已持久化且存在可审 artifact 后，再按需创建
   同 checkout Reviewer；worktree Reviewer 优先使用同目录线程。
8. 每个后续 `create_thread/fork_thread` 都先登记 project id、`PROJECT_TASK`、显式
   role、environment、bootstrap marker 和完整 prompt digest。Adaptive marker 固定为
   `LOOP_ID|ROLE_KIND|PACK_SHA256`，其中 `ROLE_KIND` 必须逐字取自角色 Prompt 的
   `Role Kind:`，不能把 `state_writer` 猜成 `state-writer` 或按标题转换。成功回读
   必须逐字段一致，再执行 `MARK_OUTBOX_SENT` 和 `ACK_OUTBOX`；ACKED 结果才把真实
   threadId 登记到 `thread_registry`，不能按标题猜。
9. Adaptive Controller 先写 `PREPARE_OUTBOX(kind=AUTOMATION)`；按“项目名 + loop_id”、目标线程、
   rrule、无尾换行的 LF-normalized prompt 及其 digest 检查已有 automation。只有没有精确匹配时才创建，再把
   同一 outbox 写成 SENT 并以真实 automation id/status ACKED。
10. Adaptive Controller 解析 `PAYLOAD_MATERIALIZATION_SPEC`，把所有 `MATERIALIZE_*`
    整值替换为正确 JSON 类型，再调用 runtime `--payload-materialize`。只有
    `PAYLOAD_MATERIALIZED` 可进入 `PREPARE_OUTBOX(kind=DISPATCH)`；Standard 仍按原模板物化。
11. Controller 把 runtime 返回的 `transport_text` 原样发送；确认目标任务收到后写入
    `MARK_OUTBOX_SENT`；只有绑定严格 JSON Worker 报告的 `ACK_OUTBOX` 才关闭该派发。
12. Standard 后续按 Worker -> state ACK -> Reviewer -> state ACK -> 下一 Goal 循环。
    Adaptive 则按 Worker -> CODE_REVIEW ACK -> 必要的 Local Verifier ACK ->
    ROADMAP_AUDIT ACK -> GOALS/dashboard ACK -> Controller Goal 切换 -> 下一 Goal。
13. Adaptive 最后一个 milestone 先得到 `ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`，
    再把 `FINAL_AUDIT` 发给同一 Reviewer；`FINALIZE_LOOP` 只准备终态外部动作，
    Controller 完成精确 Goal、暂停精确 heartbeat 后还要发送证据绑定的
    `ACK_FINALIZATION`。只有 `FINALIZATION_ACKED` 才闭环。Standard 仍按原有
    最终审查流程收尾。

`FINAL_REVIEW_PASS` 到达 `LOOP_COMPLETE`；只有限制项明确、受证据边界约束且
没有未解决 required fix 时，`FINAL_REVIEW_PASS_WITH_LIMITATION` 才能到达
`LOOP_COMPLETE_WITH_LIMITATION`。有限通过不能被静默升级为完整通过。

自动模式必须使用真实项目线程：

```text
create_thread(
  prompt=BOOTSTRAP_PROMPT,
  target={type:"project", projectId:PROJECT_ID, environment:{type:"local"}}
)
```

这里的 `BOOTSTRAP_PROMPT` 是生成器给该角色的完整 Prompt 原文，再加确定性 marker 和
`BOOTSTRAP_ONLY`，必须逐字作为 initial prompt 发送。不能缩成“去读某个文件/标题/行号”、
摘录、摘要或 loader 指令。prompt digest 必须是这些 UTF-8 字节的完整小写
`sha256:<64 hex>`；32 位截断值不合格。状态尚未初始化时若创建错了，当前 loop identity
应记为 `E2E_PROTOCOL_VIOLATION` 并停止，不能给错误任务发 Adaptive
`STATE_MUTATION`，也不能偷偷
再建一个替代任务。

`create_thread` 成功后，任务索引可能短暂尚未同步，所以第一次 `read_thread` 返回
not found 不能直接判失败。Adaptive Controller 会保留返回的同一个 `threadId`，按
1、2、4、8、16 秒重读并核对 marker，期间绝不补建第二个任务。只有读到实际内容且
身份不匹配才是 `E2E_PROTOCOL_VIOLATION`；全窗口仍不可见则记录
`THREAD_IDENTITY_PROPAGATION_TIMEOUT`，等待后续按原 id/marker 恢复。

这个 31 秒窗口只判断“返回的任务 id 能否读取”。如果任务实体已经可读、项目和目录也
匹配，但初始转次仍是空的 `active/pending`，它属于 `WAITING_BOOTSTRAP_ACTIVE`；若明确
是额度或临时服务容量，则是 `WAITING_QUOTA_RECOVERY`。Controller 必须继续复用同一
`threadId` 轮询，不能把它算 idle、不能结束 loop、不能补建，也不能在完整 prompt/marker
和 READY 回报可核验前初始化状态。只有已结束或报错的转次仍无法核验 bootstrap，才记
`THREAD_BOOTSTRAP_FAILED`。

控制任务还必须先解析自己的真实 `threadId`。Codex 委派消息里的 `source_thread_id`
表示上游父任务，不是当前控制任务；不能把它写成 lease owner。Controller 会按 Pack
摘要、目标目录、项目和启动消息核对最近任务，只接受唯一匹配项。无法唯一解析时在创建
State-Writer 前停为 `CONTROLLER_THREAD_ID_UNRESOLVED`。canonical `thread_registry`
同时登记 Controller 与 State-Writer，后续租约、Goal、heartbeat 和恢复读取都绑定同一个
真实 Controller `threadId`，确定性 LOOP_ID fallback 不能替代它。

worktree 环境则把 `target.environment` 设为
`{type:"worktree", startingState:{type:"branch", branchName:VERIFIED_BASE_BRANCH}}`。
某些 App build 会先返回 `pendingWorktreeId`，另一些返回 `clientThreadId`；两者都只是
排队身份，必须通过任务列表核对项目、目录和 bootstrap marker 后解析成真实
`threadId`，才能登记或派发。

以下都不能充当正式 Codex App Loop Worker/Reviewer/State-Writer/Local Verifier：

- `multi_agent_v1.spawn_agent`
- `agent_type`
- `fork_context`
- `agentId`
- “创建智能体”

缺少真实线程工具时，Controller 输出 `THREAD_TOOLS_UNAVAILABLE`，然后由
用户决定是否进入手动降级。

子代理默认 `disabled`。只有 Adaptive 输入明确提供非关闭策略、并发上限、全程
运行上限、单项重试上限和可暴露输入范围时，Pack 才会授权最多两个一次性只读
子代理做代码搜索、日志归类、测试失败初筛或摘要。它们的 `agent_id` 不写入正式 `thread_registry`，
不能写文件、审批、派发、改路线图、调用付费/外部服务，也不能替代上面的正式任务。
每次 sidecar 必须先经过 `DELEGATION` outbox PREPARED，再实际 spawn 一次并记为 SENT；
State-Writer 只有在同一 ACK 事务中归档严格 `application/json` 报告且真实 SHA-256
等于 `report_digest` 时才写成 ACKED。只有 `COMPLETED + ACKED` 的结果能成为证据，
`INTERRUPTED/DROPPED` 只保留诊断记录；缺少
subagent 工具不会阻塞正式 loop。
调用前读取当前实际暴露的 subagent 工具 schema：只使用其中存在的参数；不能把
另一个 App 版本的工具名、`agent_type/fork_context` 或其他字段硬塞进当前调用。

这份授权只属于 Controller。State-Writer、实现 Worker、Reviewer 和 Local Verifier
必须直接完成自己的正式职责，禁止再创建子代理，也禁止创建、fork 或给其他正式任务
发消息；sidecar 自身也不能继续委派。正式角色无法直接完成时，应把准确 blocker
证据交回 Controller，不能靠嵌套委派绕过并发、审查或寿命上限。

任务完成后的收纳使用
`set_thread_archived(threadId=..., archived=true)`；归档不是删除，必须晚于报告和
状态 ACK。

## heartbeat 的准确行为

heartbeat 只负责让当前一次 loop 自推进，不等于永久 daily/weekly cron。用户若
还要长期 recurring automation，skill 必须另外确认 schedule、workspace、独立
self-contained prompt、local/worktree 环境、启停条件和预算，再输出单独 cron
模板；不能把一句“每天跑”静默塞进 heartbeat。

默认创建参数：

```text
automation_update(
  mode="create",
  kind="heartbeat",
  destination="thread",
  status="ACTIVE",
  rrule="FREQ=MINUTELY;INTERVAL=15",
  name=HEARTBEAT_AUTOMATION_NAME,
  prompt=HEARTBEAT_PROMPT
)
```

生成的 Controller Pack 会内嵌完整 `HEARTBEAT_PROMPT_BEGIN/END` 文本，Controller
必须原样作为 `prompt` 参数，不再临场概括。`HEARTBEAT_AUTOMATION_NAME` 是
“项目名 + loop_id”的确定性名称。

默认预算：

- 每 15 分钟一次。
- 最多 192 次，总计约 48 小时。
- 没有 inflight/queue 时，连续 8 次 idle 才允许暂停。
- Worker 连续 60 分钟无进展才进入 stale 检查。

Worker 正在运行且仍有进展时：

- 记录 `WAITING_ACTIVE`。
- 保持 heartbeat ACTIVE。
- 不增加 idle 计数。
- 不重复派发 Goal。
- 不把 NOOP 当终点。

Standard 中，每次 heartbeat 唤醒先处理遗留状态请求，再用
`automation_id + next wake_count` 生成稳定 wake event，经 State-Writer CAS
写入一次 `HEARTBEAT_WAKE` 并等待 ACK。重复唤醒不能把同一次 wake 计数两遍。

Adaptive 中，Goal Mode 自己续跑和 heartbeat 唤醒可能接近同时发生。两者都以
`ACQUIRE_LEASE` 作为唯一的计数 wake 和路由入口；不存在额外的
`ROUTING_TURN_STARTED` 或 `HEARTBEAT_WAKE` mutation。运行时在同一 CAS 中校验
`routing_turn_id`、`event_id`、`max_wakeups` 并获取 `controller_lease`，之后才允许
派发、审查、Goal 工具或路线图动作。租约带单调
递增的 `lease_epoch`、不可重复使用的 lease id、routing turn、owner kind、owner
task/turn、获取/过期时间和固定 `ROUTE_ONE_TRANSITION`。初始化、routing-turn 计数和
acquire/takeover 之外，每个状态请求及外部动作 outbox 都必须带
`lease_epoch + lease_id + owner_kind + owner identity + intended_transition` 的完整
claim 和可信 `observed_at`；只带 epoch、用途不符、已过期或已消费都无效。拿不到租约
只记录 `WAITING_CONTROLLER_LEASE`，不发消息。过期接管必须有精确 owner 任务的
`read_thread` 证据，再以 CAS 消费旧 id 并增加 epoch。一次租约只保留一个受围栏
route action：一个 native Goal 动作、一个外部 outbox、一次 `ROADMAP_REVISION`、
`FINALIZE_LOOP` 或 `STOP_LOOP`。终态 ACK/CAS 消费该 lease id；后续动作必须重新获取计数后的新租约。
接管/续租也只能重绑这一个未完成 route，不能把 Goal 与 dispatch 打包恢复。

每个动作都必须提供本次可信 `observed_at`，不能沿用启动时的旧时钟。State-Writer 在
修改前先校验 event/request id 和完整输入；失败时回滚状态、outbox、计数和 lease，
不能出现“报错但已经消费租约”。若某个已经 PREPARED/SENT 的外部 outbox 在执行期间
发生合法过期接管，新 routing turn 使用全新的 lease id，并在同一 CAS 中只把那一个
immutable route 重新绑定到新 claim，避免永久 pending deadlock。路线图 proposal 本身
不是 outbox，也不存在虚构的 `ROADMAP_CHANGE_PREPARED` 状态。
如果仍是同一个活跃 Controller turn，只是事务耗时接近或超过 TTL，则使用
`SAME_OWNER_LEASE_RENEWED`：提供 `ACTIVE_SAME_OWNER` 证据、保留 routing turn、换新
lease id/epoch，并且只重绑匹配的未完成记录；它可以跨越同一条 `PREPARED/SENT/ACKED`
长任务记录，但只轮换路由授权，不改变 payload、target、dispatch/report 身份或状态，也不
重新发送外部动作。不可变 payload digest 继续绑定原始 dispatch claim；canonical outbox
只轮换当前 lease claim，transaction journal
记录 old/new claim。canonical claim、owner 或 route 不匹配，以及多条活动记录不明确时必须
拒绝；不能伪造 `STALE`。失败的身份/时间探测
不能推进逻辑时钟；PREPARED 发送必须继续使用记录内的 claim，接管或续租需先原子重绑
并占用恢复动作。仍有 PREPARED route、Goal create/update 事务或 pending 路线图时，
租约不能释放。
续租和接管证据都必须是 mutation artifact 中唯一匹配的 `application/json` 文件；
解析后的对象必须与 mutation 内除 path/digest 外的 owner evidence 字段逐项完全相同，
不能用普通文本、摘要或只匹配 threadId 的文件代替。
每个 routing turn 同时绑定最初的 `event_id`。精确重放不改变计数、ledger、版本或预算；
把同一 event id 换绑到另一 turn 会在任何修改前被拒绝。

Worker、Reviewer、Local Verifier 派发都必须带 canonical `payload_digest` 和包含
`routing_turn_id` 的完整 claim。Controller 在其他字段全部按正确 JSON 类型物化后，把
`dispatch_payload_digest` 保持为字面量 `PAYLOAD_DIGEST_PLACEHOLDER`，将严格 JSON 交给
`adaptive_state_runtime.py --payload-materialize`。只使用 runtime 返回的 digest，并把返回的
`transport_text` 原样作为消息正文。接收方把收到的精确 `codexDelegation.input` 原样交给
`--root <absolute repo root> --payload-verify`，只有同时匹配 canonical SENT outbox、
pre-PREPARE snapshot、lease route、目标任务和 Goal/review/local 身份后返回的
`PAYLOAD_VERIFIED` 才能执行；内部 `PAYLOAD_BYTES_VERIFIED` 只证明字节和摘要，不能执行。
任何一方都不得手工替换子串、保留
`sha256:` 前缀、添加尖括号、重新序列化正文，或对 UI/XML wrapper 做哈希。
信封中的 bounded state snapshot 固定在 `PREPARE_OUTBOX` 之前；PREPARE 和 SENT 本身会
让最新 state_version 增加。接收方应验证匹配 outbox 的
`prepared_state_version == snapshot.state_version + 1`、状态为 SENT 且 roadmap/Goal/
lease/target/payload/definition identity 未变化，不能因为最新版本更高就误判 snapshot 过期。
`non_git` 报告中的 `current_branch`、`base_sha`、`head_sha` 必须是字面量
`NOT_APPLICABLE`，不能用 `null` 或空值；`changed_files` 一律使用 repo 相对 POSIX 路径。

Adaptive Worker、Reviewer、Local Verifier 的最终回报必须是单个 strict JSON 对象，不能带
Markdown fence 或尾随说明；其中 `report_digest` 固定写
`PENDING_CONTROLLER_ARCHIVE`。Controller 校验字段和重复 key 后，用 sorted-key、compact、
`ensure_ascii=false`、无尾换行的 UTF-8 JSON 归档，并把真实文件 SHA-256 交给
State-Writer。正式 DISPATCH、ASSURANCE、LOCAL 的 `ACK_OUTBOX.result` 只包含
`status`、归档后的 `report_digest` 和 `artifact_digest`，并附加唯一同 digest 的
`application/json` 工件。runtime 会在 ACK 前解析严格 JSON，把顶层 dispatch、Goal、
milestone、roadmap、目标任务、payload、artifact、decision 和来源身份与当前 SENT
outbox 逐项绑定；`RECORD_REVIEW` 再校验一次同一报告。Reviewer 必须在顶层重复
`source_worker_dispatch_id`、`source_worker_report_digest`、`worker_thread_id` 和
`source_artifact_digest`，只写在 `state_change_request`、finding 或 evidence 中不算。
缺字段、错摘要、重复 key、非有限数字、非 canonical JSON 或未绑定工件都会整笔零副作用
拒绝，并保持 outbox 为 SENT。
`RECORD_REVIEW` 的 decision、report digest、artifact digest 还必须与先前 ACK 完全
一致；每个 COMPLETED assurance outbox 必须一对一对应同身份的 assurance ledger。
如果两者矛盾，runtime 会在任何新 mutation 前拒绝 canonical state。
升级中的旧 loop 只有一种兼容路径：已经 ACKED 且 `result` 恰好为 null/空对象的
assurance，可在 `RECORD_REVIEW` 中从 typed mutation 推导三字段并对同一报告完整复验后
原子补齐；任何非空但错误的 result 都不会被自动“修好”。

同一时间最多一个写入型 execution Worker。State-Writer 可串行写状态；Reviewer
只在有可审 artifact 时短期并存，不预创建未来阶段线程。
`max_child_threads` 是整个 loop 生命周期总上限：不含 Controller，但已归档任务
仍计数；达到上限时复用现有任务或停止 `THREAD_BUDGET_EXHAUSTED`，不能继续堆线程。
runtime 同时限制一个正式/bootstrap role key 只能注册一个任务，以及一个 loop 只能有
一个未取消的业务 heartbeat。THREAD/AUTOMATION/GOAL 的 ACK 必须附带一份严格 JSON
`CODEX_TOOL_RESULT` 工件，绑定 outbox kind/id、payload digest、target id 和完整工具返回；
emulated Goal 则使用 `GOAL_TOOL_UNAVAILABLE`，不能靠自然语言声称外部动作成功。

默认所有顺序写入 Goal 共享一条 integration worktree。角色不变时复用同一
Worker；确实需要更换写入角色时，只能在前一 Writer idle 且报告/状态 ACK 后，
按需调用 `fork_thread(threadId=PRIOR_WRITER_THREAD_ID,
environment={type:"same-directory"})`，再发送新角色的完整 bootstrap prompt。
只有 Goal Queue 明确给出 promotion/merge 计划和权限时，才允许分叉写入 worktree，
否则停止 `WORKTREE_INTEGRATION_PLAN_MISSING`。
运行时允许的 worktree 必须位于 canonical repo 下，或位于初始化授权中显式列出的
`control_plane_limits.allowed_external_worktree_roots` 下；Codex App 自己创建的外部
worktree 不能仅因不在 repo 子目录而误判，但任意其他绝对路径仍会零副作用拒绝。

已完成且不会复用的 Worker/Reviewer 在报告和状态 ACK 后通过
`set_thread_archived(..., archived=true)` 归档；不能归档 active、未 ACK 或仍需
修复的任务，State-Writer 必须保留到最终状态 ACK。

heartbeat 只有在以下情况暂停：

- `LOOP_COMPLETE` 等终态已经写入并 ACK。
- `STOP_LOOP_APPLIED` 已把真实硬阻塞写成 `LOOP_BLOCKED`；Controller 必须在同一回合暂停业务 heartbeat，不能等下一次 heartbeat 自己来暂停。
- 没有 inflight/queue，且 idle 预算耗尽。
- 总 wake 预算耗尽并已记录 `HEARTBEAT_BUDGET_EXHAUSTED`。

终态顺序固定为：`FINALIZE_LOOP` CAS 已 ACK并产生 `finalization_outbox=PREPARED` ->
原生 Controller Goal 已完成或如实记录 emulated 终态 ->
`automation_update(..., status="PAUSED")` 成功 -> Controller 将精确 Goal/automation
观察分别写入两个不同的 `application/json` artifact；解析后必须严格等于
`{"goal_id": <canonical id>, "status": "COMPLETE"}` 与
`{"automation_id": <canonical id>, "status": "PAUSED"}`。随后发送
`ACK_FINALIZATION` -> 运行时写入
`finalization_receipt` 和 `FINALIZATION_ACKED`。只有这个证据闭环和最终报告都完成后，才可以删除
这个已经无用的 automation；不能先删除再用文字声称它曾经暂停。临时 blocker 只暂停
同一个 automation id，恢复时仍更新它，禁止创建第二个。

真实不可恢复 blocker 使用独立 `STOP_LOOP`，不是 `FINALIZE_LOOP`，也不是报告里的临时
状态名。连续三个自然 Goal turn 必须各自在 observation-only `RELEASE_LEASE` 事务中归档
不可变观察并保持非终态；每次都要求 `route_action=null`、
`release_reason_code=HARD_BLOCK_OBSERVATION_ONLY`，且 artifact 的 archived state version
等于该 turn 的完成版本。不能在 STOP 请求中附带或回填任何一轮。运行时只在这三个已经
完成的最近连续 Goal turn 都有不同 artifact，且 blocker code、fingerprint、Controller Goal
identity 完全一致时，才允许下一个独立 Goal turn 执行 STOP_LOOP。少于三次、重复、非连续、
带路由动作、晚归档或伪造 turn id 都整笔零副作用拒绝。合格请求还要求一个绑定这三个
先前 turn id 的 aggregate strict JSON blocker report，关闭未完成 outbox 后把 Active milestone
标为 BLOCKED、未来 milestone 标为 SUPERSEDED，并准备 Goal/heartbeat 收尾。
业务 heartbeat 必须在这个独立 STOP 回合 PAUSED，并在同一回合调用
`update_goal(status="blocked")`；禁止为了凑次数制造空唤醒。随后用 Goal=BLOCKED
与 automation=PAUSED 两份独立 JSON 观察执行 `ACK_FINALIZATION`，全程不得删除 heartbeat。

Controller Pack 创建的是当前业务 loop 的唯一 heartbeat。发布恢复 supervisor、人工
设置的 watchdog 或长期 cron 属于外部运行层，不得冒充这个业务 heartbeat，也不得
共享它的 automation identity。

Adaptive outbox 使用固定生命周期：Worker/Local 为
`PREPARED -> SENT -> COMPLETED`；Assurance 为
`PREPARED -> SENT -> ACKED -> RECORD_REVIEW -> COMPLETED`；原生 Goal、Automation、
Thread、Delegation 为 `PREPARED -> SENT -> ACKED`；emulated Goal 从 PREPARED 直接
ACKED，不能伪造 SENT。所有 kind 只有 `PREPARED -> CANCELLED` 这一条安全取消分支，
SENT 后不得取消。`IDEMPOTENT_REPLAY` 是成功的零变化响应，不是持久状态。

如果 `automation_update` 不可用，自动模式在 First Goal 前停止
`AUTOMATION_TOOLS_UNAVAILABLE`，不能在没有 heartbeat 的情况下假装自动 loop。
若创建后落盘前中断，Controller 从 `$CODEX_HOME/automations/*/automation.toml`
按确定性名称和 prompt digest 认领已有 heartbeat，而不是再创建一个。

## Goal Queue 和幂等状态

每个 Goal 必须有：

- `goal_id`。
- 每次尝试唯一的 `dispatch_id`。
- 真实目标 `threadId`。
- objective、acceptance、validation、scope。
- dependencies 和 `dispatch_when`。
- side-effect permission matrix。
- evidence、claim 和 stop conditions。

多角色任务必须提供 Goal Queue。例如 CI 分诊：

```text
CI-T1: triage -> TRIAGE_ACTIONABLE 或 TRIAGE_NO_ACTION
CI-R1: implementation -> 仅在 CI-T1 为 TRIAGE_ACTIONABLE 时解锁
FINAL_AUDIT: 队列结束后的完整审查
```

State-Writer 使用：

- `state_version`。
- `state_request_id`。
- `event_id`。
- `expected_state_version`。
- `dispatch_outbox`，包含 payload digest、目标 threadId 和发送阶段。

在 Adaptive 中，Controller 只生成 schema 校验过的类型化 mutation 请求；
State-Writer 只调用随 skill 安装的确定性状态运行时并转发其结构化 JSON 结果。它不再
自行阅读自然语言后手工重写整份 `LOOP_STATE.md`、事件文件或 transaction journal。
运行时对 canonical 项目根目录的稳定目录文件描述符持有进程级 `flock`，不依赖可删除、
可替换的 lock 文件；它负责 JSON Schema、CAS、请求/事件幂等、
临时文件与 `fsync`、原子 rename、PREPARED/APPLIED 恢复、lease、outbox、artifact
归档、`ROADMAP_REVISION`、`FINALIZE_LOOP` 和 `ACK_FINALIZATION`；同时从 canonical
state 原子派生 `GOALS.md` 和条件 dashboard。任何拒绝必须保持 state、events、
journal、outbox、投影和外部动作计数零副作用。
普通 mutation 遇到更早的未完成事务时只返回 `RECOVERY_REQUIRED`，不会顺手修改
任何文件；State-Writer 必须先显式运行同一 runtime 的 `--recover`，转发恢复结果并
重读 canonical state，之后才能提交下一项 mutation。

返回值：

- `STATE_WRITE_APPLIED`：成功写入并增加版本。
- `STATE_WRITE_ALREADY_APPLIED`：重复事件，幂等跳过。
- `STATE_VERSION_CONFLICT`：版本冲突，没有写入。

Controller 未拿到 ACK 前，不能同时发送 review、repair 或下一 Goal。

首次启动时，不存在的 canonical state 视为 version 0；只有
`LOOP_INITIALIZED + expected_state_version=0` 可以创建 version 1。已有状态必须
恢复，不能覆盖。运行期 request/event/dispatch id 只允许字母数字、点、下划线和
连字符，禁止把路径或报告文本拼进 transaction/report 文件名。

`LOOP_STATE.md` 的 canonical 部分是
`STATE_JSON_BEGIN/STATE_JSON_END` 之间唯一的严格 JSON object；所有 schema key
必须存在，顶层未知 key 拒绝。`LOOP_EVENTS.jsonl` 每行只能有一个完整 JSON
object，不能写 Markdown fence 或多行记录。这样 heartbeat 和 State-Writer
恢复时不依赖自由格式文本猜状态。

Adaptive 启动顺序更严格：先用确定性 marker 恢复或创建唯一 State-Writer；然后一次
`LOOP_INITIALIZED` 写入完整 Adaptive schema、canonical authorization envelope、
pack/loop/State-Writer 身份、初始
milestones、不可变 Goal 定义注册表、封闭队列、空 outbox/ledger、估时和 GOALS 投影
元数据。授权包和 Goal 注册表必须把 Pack 两个 JSON fence 内的对象原样解析进 mutation，
不能发送 `COPY/TODO` 或文字引用让 State-Writer 猜；canonical digest 统一为小写
`sha256:<64 hex>`，只有 Goal marker 使用裸 64 位十六进制。ACK 后先记一次共享
routing turn，再获取 startup lease。Worker、heartbeat、Controller Goal 和 First
Goal 的 outbox 都必须在该 lease 下依次写入并 ACK。除创建这个 pre-state
State-Writer 外，不能在状态和租约准备好前先建其他任务或 automation。

non-git 或未提交 new_git 的产品 before/after digest 只覆盖获批产品 scope；
`.codex-loop`、声明过的原有无关文件和 cache 从产品 digest 排除，但必须输出
exclusion manifest 供 FINAL_AUDIT 单独检查，避免状态写入制造假产品 diff。

Goal 派发采用 transactional outbox：

1. 选择本身为 `READY` 且依赖已完成的 Goal，从 `goal_definition_registry` 物化，生成
   唯一 `dispatch_id`、稳定 payload digest，并绑定真实目标 `threadId` 和 Goal 定义
   digest。
2. 发送 `PREPARE_OUTBOX(kind=DISPATCH)` 并等待 State-Writer ACK；同一 Goal/roadmap
   revision 只允许一个 Worker `PREPARED/SENT` 派发。
3. 向真实目标 threadId 发送一次。
4. 发送 `MARK_OUTBOX_SENT`；Worker 返回后，以绑定严格 JSON 报告的
   `ACK_OUTBOX` 关闭派发。
5. heartbeat 恢复到 PREPARED 状态时，必须同时匹配 `dispatch_id + payload digest +
   target threadId + Goal definition digest`，再完整查询目标任务；只有确认未送达才重发。Worker 收到重复
   `dispatch_id` 时返回既有报告，不能重做。

Worker PASS 后该 Goal 不再可派发。只有绑定同一 Worker report/artifact 的
`REVIEW_NEEDS_REPAIR` 已写入并 ACK，才会产生一次受预算限制的 repair authorization。
`goal_execution_ledger[goal_id].attempts` 超过首次执行加
`repair_policy.max_repair_attempts_per_goal` 后，runtime 必须拒绝为
`REPAIR_BUDGET_EXHAUSTED`，换任务不能清零。

每个 Goal 还必须物化一份有界 canonical state 快照，至少包含 state version、
repo/worktree、依赖、审批/预算切片、重试计数、原有脏文件和 claim/evidence 边界。
只给 worktree Worker 一个 `.codex-loop/LOOP_STATE.md` 路径不算自包含。

## Adaptive 路线图如何工作

### Goal Queue 不是路线图

Adaptive 仍使用原子 Goal Queue 执行工作，但项目路线图存放在 canonical state 的
`milestones` 中。当前已 ACK 的队列顺序在下一次合法 Roadmap Audit 前有效；审计
可以在原授权范围内新增、修改、重排未来 milestone，或标记不再需要的 milestone
为 `SUPERSEDED`。已完成/正在执行的 dispatch、Goal ID 和证据历史不能改写。

每个 milestone 至少包含：

- `milestone_id`、outcome 和 current scope。
- decisions、known blockers 和 required evidence。
- status、dependencies 和 Goal/report references。

非终态必须恰好一个 `ACTIVE`。初始 Active milestone 至少有一个无依赖、可立即派发
的 Goal；First Goal 从这个集合按输入顺序确定，不从整个 Goal 数组盲取第一项。
初始化 Queue 还必须逐一包含所有 ACTIVE/PLANNED milestone 的非退休 Goal 定义，不能
只给每个 milestone 放一个代表项；每个 scope 在派发前再次拒绝 `..`、URL、
`.codex-loop` 和目录穿越。
每个 Future Goal Queue entry 只有 `goal_id`、`milestone_id`、
`roadmap_version`、`status=READY|PLANNED` 和 `depends_on`；未知依赖、环、退休 ID
复用、跨 milestone 重绑，以及 Active milestone 没有依赖已满足的 READY Goal 都会
被拒绝。
一个 milestone 可以有多个依赖排序的 Goal；完成当前 Goal 后，只要 milestone 仍为
ACTIVE，就可以解锁同阶段的下一个 READY Goal。只有要把 milestone 标为 COMPLETE 时，
未执行 sibling Goal 才会阻止路线图变更。

Queue entry 不是完整任务。每个 id 必须同时指向 `goal_definition_registry` 中的不可变
定义，至少包含 Worker role、objective、success criteria、validation、write scope、
phase permissions、dependencies、dispatch condition 和完整 SHA-256 template digest。
Roadmap Audit 新增 Goal 时必须给出完整定义；旧 Goal 的定义不能借“重新规划”修改。

### `.codex-loop/GOALS.md`

`LOOP_STATE.md` 是唯一真相源；`GOALS.md` 是 State-Writer 根据它生成的中文可读
路线图。文件带 `state_version`、`roadmap_version`、`roadmap_sha256` 和时间戳。
人工直接编辑 `GOALS.md` 不会修改状态；发现版本/digest 不一致时，State-Writer
从 canonical state 重建它。

### Controller Goal Mode

Controller milestone Goal 与发给 Worker 的执行信封是两件事：Standard 兼容旧
`/goal` 文本，Adaptive 使用不会与 App 命令冲突的 `WORKER_DISPATCH`。

- Controller Goal：当前唯一 Active milestone 的长期结果和完成条件。
- Worker Dispatch Goal：带 `goal_id`、`dispatch_id`、路径、验证和权限的原子任务。

工具可用时，Controller 先获取 fenced lease，再 `get_goal`。创建的 Goal objective
末尾带稳定 marker：
`[CODEX_LOOP_MILESTONE loop_id=<LOOP_ID> pack_sha256=<64位SHA256> milestone_id=<ID> objective_sha256=<64位SHA256>]`。
marker 必须是最后一行，后面不能再有文字。调用工具前先写
`PREPARE_OUTBOX(kind=GOAL, action=CREATE)`。只有真实工具返回的 objective marker 与 canonical
`controller_goal` 或精确 PREPARED/SENT/ACKED GOAL outbox 同时匹配时才恢复；marker 单独出现
不算恢复授权，loop/pack 不同直接冲突；
这个检查也适用于工具返回 `complete` 的 Goal；transition ACK 不能替一个 marker
不匹配的 completed Goal 绕过身份验证。
匹配的 blocked Goal 也只能进入恢复/阻塞处理，不能创建第二个 Goal。不能假设 Goal
工具会返回自定义 `milestone_id` 或 `objective_digest` 字段。没有未完成 Goal 才
`create_goal`。原生路径使用 `PREPARED -> 调用一次 -> SENT -> ACKED`。工具不可用时
附加一份不可变 JSON 观察，直接把 PREPARED outbox ACK 为
`EMULATED_SINGLE_ACTIVE_MILESTONE`；不会写 SENT，也不会声称已调用原生 Goal Mode。
原生 Goal ACK 的观察必须是严格 JSON `CODEX_TOOL_RESULT`，完整绑定 outbox、payload、
target 和工具返回；emulated 路径使用严格 `GOAL_TOOL_UNAVAILABLE` 观察。
程序化工具只按实际能力创建、读取和标记 complete/blocked；不会虚构 UI 的暂停、
恢复、编辑或清除参数。
完成或阻塞旧 Goal 也不是直接调用：先写入绑定旧 Goal、目标状态、roadmap version、
payload digest 和 lease 的 GOAL UPDATE outbox。原生路径调用一次后写 SENT/ACKED；
emulated 路径带 JSON transition 观察直接 ACK PREPARED。只有跨 milestone 的已应用
`ROADMAP_REVISION` 证明旧 milestone 的所有 Goal 都 COMPLETE/RETIRED，或
`FINALIZE_LOOP`/`STOP_LOOP` 已准备精确收尾目标时，才允许完成旧 Controller Goal；同一
milestone 的 sibling 不得提前关闭它。ACK 后才能替换 canonical mapping、创建下一 Goal
或暂停 heartbeat。
runtime 会拒绝 Controller Goal 缺失、非 ACTIVE/EMULATED，或 milestone 与待派发
Worker Goal 不一致的 DISPATCH。`ROADMAP_REVISION` 若切换 Active milestone，会返回
`COMPLETE_CURRENT_CONTROLLER_GOAL`：完成并 ACK 旧 Goal，再创建并 ACK 新 Goal；若只
解锁同 milestone sibling，则返回 `PREPARE_NEXT_GOAL_OUTBOX` 并保留原 Goal。之后才能
派发下一 Worker；`FINALIZE_LOOP` 同样检查最终 Goal 绑定。

只有单独的 `controller_goal_token_budget` 会传给 `create_goal(token_budget=...)`。
全局 `token_cap` 属于整个 loop 的计量预算，不会在每个 milestone 重复发放。

### CODE_REVIEW、ROADMAP_AUDIT 和 FINAL_AUDIT

三者复用同一个真实只读 Reviewer 任务，但使用独立 dispatch、报告和状态 ACK：

- `CODE_REVIEW`：检查准确 worktree/diff、缺陷、安全和测试缺口。
- `ROADMAP_AUDIT`：检查 milestone 是否真的完成、证据要求是否仍成立、下一阶段
  是否仍正确，以及是否需要新增/重排/废弃未来 milestone。
- `FINAL_AUDIT`：只在最后候选上检查完整 Git/non_git 集成 artifact、全部验证、
  禁止产物、状态/事件一致性、审批和 claim boundary。

每次审查先写入精确 `assurance_dispatch_outbox` PREPARED，等待该 PREPARE mutation ACK 后发送一次，再写 SENT；
发送 ACK 必须使用该 PREPARED 记录内的 lease claim；跨 lease 要先做显式恢复重绑。
Reviewer 返回后，Controller 先 canonicalize 并归档报告，再以三字段 formal result 做
`ACK_OUTBOX`；runtime 验证成功后才从 SENT 进入 ACKED，随后独立 `RECORD_REVIEW`
进入 COMPLETED。没有匹配 SENT outbox 的报告不能 ACK。`REVIEW_ARTIFACT_UNAVAILABLE` 可被状态层 ACK，
但只是非 PASS blocker。`REVIEW_PASS_WITH_LIMITATION` 只有在限制项明确、受证据边界
约束且没有 unresolved required fix 时才是 CODE_REVIEW typed pass；限制必须保留到
后续审查和最终 claim，不能静默升级为完整 `REVIEW_PASS`。`CODE_REVIEW` 只能引用 Goal ledger 中最新的、
已经 State-Writer ACK 的 Worker PASS dispatch，并同时匹配 Worker report digest、Goal、
milestone、roadmap version 和 artifact；修复产生新 artifact 后，旧审查链永久失效。
即使修复前后 artifact digest 相同，也必须按当前 Worker dispatch/report 选择新审查，
不能复用旧 PASS。
三次 Adaptive `REVIEW_DISPATCH` 是
closed tagged union，ACK 身份固定为 `review_kind + milestone_id + roadmap_version +
review_dispatch_id + source Worker dispatch/report + source artifact digest + 前序报告/本机验证身份`。
任何字段变化都会让旧 ACK 失效；纯只读/no-diff milestone 也要以
`artifact_kind=NO_DIFF` 完成 CODE_REVIEW，再独立做 ROADMAP_AUDIT 和最终审查。

非最终 `ROADMAP_AUDIT_PASS` 或 `ROADMAP_CHANGE_PROPOSED` 报告都带一个封闭的
`roadmap_proposal` 及 canonical digest。提案绑定 proposal/audit id、base roadmap version、
typed operations、next Goal、理由、`within_authorized_envelope`，以及完整 proposed
milestones、future Goal Queue、Goal definitions、authorization envelope、estimate 的组件
digest；报告另行绑定 source Worker/code/local identity 和不可变 artifact。State-Writer
重新计算组件 digest、typed operation diff 与 canonical authorization check，
Controller/Reviewer 提供的布尔值和 digest 只作断言。`ROADMAP_AUDIT_PASS` 必须为 in-envelope；
`ROADMAP_CHANGE_PROPOSED` 必须为 out-of-envelope 并只进入
`ROADMAP_CHANGE_REQUIRES_APPROVAL`。operation 只允许 `ADD_MILESTONE`、
`UPDATE_MILESTONE`、`REORDER_FUTURE_MILESTONES`、`SUPERSEDE_MILESTONE`，没有
小写别名。应用前 State-Writer 会重新核对当前 code/local/audit identity；提案后新增的
Local Verifier FAIL/BLOCKED 会让提案失效。Controller 必须先让每个旧版本 PREPARED
Worker、Assurance 或 Local outbox 分别完成 `CANCEL_OUTBOX` 事务和 ACK，再用新 lease
提交 `ROADMAP_REVISION`。修订本身不会暗中取消 outbox；只要还存在 PREPARED、SENT、
ACKED-assurance 或 in-progress 记录就拒绝。清空这些活动记录后，State-Writer 才在一次
CAS 事务里同步更新 exact audited milestones、future Goal Queue、Goal definitions/execution
ledger、roadmap version、估时和 GOALS/dashboard digest。
扩大 objective、路径、预算、
connector、副作用、生产权限或 claim 时，状态是
`ROADMAP_CHANGE_REQUIRES_APPROVAL`，不会先改计划再问用户。

最后一个 milestone 的 Roadmap Audit 返回
`ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`，不能直接把 RoadmapRevision 写成终态。Controller
先发送 FINAL_AUDIT；报告 ACK 后，State-Writer 用独立 `FINALIZE_LOOP` CAS 对照完整
Goal registry、execution ledger 和 queue，验证所有非退休/非 superseded 必需 Goal
确实执行，只完成最后一个有完整证据链的 Goal/milestone，再退休/清空已解决
队列、刷新投影并准备 finalization outbox。未执行 Goal，或仍有 PREPARED/SENT/IN_PROGRESS 的 Worker、
审查、本机验证 outbox，都会阻止完成。只有这个 ACK 返回后，才完成
Controller Goal 和暂停 heartbeat；再把两项外部动作的精确观察 artifact 发给
`ACK_FINALIZATION`。只有运行时返回 `FINALIZATION_ACKED` 才是闭环终态。

### Local Verifier

只有真实浏览器登录、本机凭证、macOS 权限、扩展、Xcode/simulator、真机或硬件等
checkout 无法证明的行为才创建 Local Verifier。它始终是同一 Codex Project 下
可回查的真实任务，不是子代理。

Local Verifier 只能在同一 artifact 的 CODE_REVIEW ACK 后派发；同样先经过独立
`local_verification_outbox` PREPARED/SENT。报告必须绑定准确
artifact identity、milestone、roadmap version、Goal ID、local dispatch ID、真实目标
threadId、report digest、完整 lease claim 和稳定 `verification_id`，包含 PASS/FAIL/
BLOCKED、步骤、预期/实际结果、脱敏截图或日志、复现和下一动作。FAIL 回到 Worker
修复后必须复测同一个 verification id；artifact digest 改变时旧 CODE_REVIEW ACK
失效，需先审修复后的 artifact 再复测，不能凭 Worker 说“已修复”就进入下一阶段。
Worker FAIL/BLOCKED、`REVIEW_NEEDS_REPAIR`、Local Verifier FAIL、`ROADMAP_AUDIT_NEEDS_REPAIR`、
`FINAL_REVIEW_NEEDS_REPAIR` 共用同一个按 Goal 计数的修复预算，不能通过更换失败阶段
重置次数。

`ROADMAP_AUDIT` 报告 ACK 本身就是持久化结构化提案。Controller 校验授权范围后，使用未执行其他动作的
独立 lease 发送一次 `ROADMAP_REVISION` CAS；当前 lease 若已派发 Worker、审查或原生 Goal，
必须先完成该动作，再开启新的计数 routing turn。

### 静态 dashboard

milestone 多于 3 个、max 估时超过默认 12 小时或用户明确要求时，State-Writer
生成 `.codex-loop/progress-dashboard.html`。它只显示 canonical state、GOALS、
证据、blocker、decision、估时和待用户事项；不含脚本、表单、外部资源或修改按钮。
它与 canonical state、GOALS 在同一原子事务中重建；读取时若嵌入的 state/roadmap
version 或 digest 与 canonical state 不一致，应按 recovery 诊断，不能把 dashboard
当成第二个状态源。

### 用户看到的状态

状态真正变化后，Controller 只输出：

```text
What's done
What's next
Any blockers
```

内部 JSON、事务恢复和长日志只在用户要求诊断时展开。每次 Roadmap Audit 后，
`estimate_history` 都会更新 min/typical/max、置信度、假设和不计入的外部等待时间。

## worktree 审查

Reviewer 必须看到 Worker 的真实代码，而不是只看文字摘要。
任何 `workspace_write` Goal 都不能把 review 关闭；脚本会拒绝
`review not required`。Standard 的纯只读、无 diff loop 可以按策略省略代码审查；
Adaptive 为了保证每个 milestone 的 Roadmap Audit 证据链，仍发送
`artifact_kind=NO_DIFF` 的 CODE_REVIEW。

local Worker：

- Reviewer 可在相同项目 checkout 中读取代码。
- Git 工作的审查信封带 base/head SHA、完整 patch 和 `diff_sha256`；Standard 可保留
  `/review`，Adaptive 使用 `REVIEW_DISPATCH`。
- `non_git` 或尚未提交的 `new_git` 使用 before/after manifest 与 snapshot
  SHA-256；不可用 Git SHA 写 `NOT_APPLICABLE`。

worktree Worker：

- 优先使用真实 Codex App
  `fork_thread(threadId=WORKER_THREAD_ID, environment={type:"same-directory"})`。
- 如果同目录 fork 不可用，Reviewer 必须能读取绝对 worktree 路径，并拿到
  base SHA、head SHA、changed files、`diff_sha256` 和完整 patch/diff。
- 任何一项无法证明时输出 `REVIEW_ARTIFACT_UNAVAILABLE`，不能只根据 Worker
  摘要给 `REVIEW_PASS`。

每个 Goal 的 diff 需要审查。Adaptive 的最后候选还要对完整 Git base-to-head 或
`non_git` baseline-to-current snapshot diff 向同一 Reviewer 运行 tagged FINAL_AUDIT，
随后等待独立 FINALIZE_LOOP ACK、外部 Goal/heartbeat 收敛和 ACK_FINALIZATION。

## 下载和依赖重试

默认瞬时依赖重试包含四种预算：

- 首次失败后最多 10 次重试，总计最多 11 次尝试。
- 180 分钟总耗时，足以容纳初始尝试和 10 次有界重试。
- 每次尝试 12 分钟硬超时。
- 每次 6 分钟无进展 watchdog。
- 每次退避最多 5 分钟，且必须受剩余总预算约束。

策略顺序：

1. 原命令、明确 timeout、完整日志。
2. 遵守 `Retry-After`，否则指数退避加 jitter。
3. package-manager retry/fetch 参数和降低并发。
4. 工具原生支持的断点续传、range/chunked 下载、预取或 package store warming。
5. allowlist 内的公开备用源，并记录完整性证据。
6. 只清理项目内、由本轮产生的部分残留。
7. browser/native package 官方支持的下载 host。

不能因为重试而删除已有 tracked lockfile。只有本轮产生的 untracked partial
lockfile 且 Goal 明确拥有它时才允许删除。禁止清理全局 cache、永久修改全局
registry、引入私有凭证或未经批准的付费镜像。

## 成本和审批

以下执行需要明确预算或 policy：

- `codex exec`。
- 真实 LLM/API/provider 调用。
- 模型评分 smoke。
- Token、调用次数或美元计量服务。

可用边界：

- 正数 `cost_cap_usd`。
- 正数 `call_cap`。
- 正数 `token_cap`。
- 明确且有边界的 `metered_runtime_policy`，例如 deferred/local-only，或写出
  最大调用/请求次数、token 或美元。

这些是 loop 全局的计量边界。只有另行提供的正整数
`controller_goal_token_budget` 才会传给当前 milestone 的原生 Goal；不能把全局
`token_cap` 复制给每个 Goal。

`unlimited`、`尽量跑完`、`自行控制成本` 等无上限表达不是有效 policy。
只限制“运行几小时/几天”也不能约束花费，因此不能单独作为付费调用授权。

目标里出现 `fake`、`mock`、`placeholder` 不等于成本授权或 deferred policy。
中文“真实大模型调用、付费模型评分、计量调用”等同样会触发成本闸。

审批写进 `approval_ledger`。已经明确预授权的本地代码和测试不应反复询问；
生产 deploy、merge、secrets、用户数据删除、迁移、真实外部写入和超证据声明
仍需对应范围的授权。

## 怎么回查 loop

### 看任务

- 控制任务：Goal Queue、真实 threadId、dispatch_id、状态 ACK、下一动作；Adaptive
  还看 Active milestone、Controller Goal 和 lease。
- 实现任务：worktree、base/head SHA、changed files、diff summary、验证 exit code。
- 审查任务：CODE_REVIEW 的 file/line findings，以及独立 ROADMAP_AUDIT 报告。
- Local Verifier：verification id、准确 artifact、步骤、截图/日志和 PASS/FAIL/BLOCKED。
- 状态任务：类型化 mutation、运行时 JSON 状态码、event/request id、state/roadmap
  version、transaction journal 和证据路径；不应看到它手工拼接整份 canonical JSON。

### 看文件

- `.codex-loop/LOOP_STATE.md`
  - 当前状态版本、Goal Queue、thread-creation/automation/dispatch outbox、
    inflight dispatch、线程登记、预算和审批 ledger；Adaptive 还包含
    `controller_pack_identity`、`artifact_ledger`、finalization outbox/receipt。
- `.codex-loop/LOOP_EVENTS.jsonl`
  - 每次派发、ACK、重试、审查和停止的 append-only 流水。
- `.codex-loop/TRIAGE.md`
  - 分诊发现、证据、`TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION` 和后续 Goal。
- `.codex-loop/reports/`
  - Worker、CODE_REVIEW、ROADMAP_AUDIT、Local Verifier 和 FINAL_AUDIT 报告。
- `.codex-loop/GOALS.md`（Adaptive）
  - 当前 Active milestone、后续路线、证据要求、blocker、decision、最近改计划原因。
- `.codex-loop/progress-dashboard.html`（Adaptive 条件触发）
  - 只读静态进度页；嵌入 state/roadmap version 和 digest，发现不一致时回到
    canonical state 与 transaction journal 诊断。
- `.codex-loop/transactions/`
  - 确定性状态运行时按 `state_request_id` 保存的 `PREPARED/APPLIED` 恢复日志，
    用于补齐中断事务，不是第二份状态源。
- `.codex-loop/sources/CONTROLLER_PACK.md`
  - 初始化时归档的精确 pack 快照和对应 `PACK_SHA256`；heartbeat 优先读它，
    避免长对话压缩后依赖不完整聊天摘要。
- Codex Automation 卡片
  - automation id、ACTIVE/PAUSED、rrule、目标线程和运行次数。

### 正常推进信号

- Worker active 时 Controller 报告 `WAITING_ACTIVE`，业务 heartbeat 仍保持 ACTIVE；
  active SENT outbox 不会为这条观察额外写入虚构 mutation。
- Worker/review/local 运行超过 lease TTL 时，同一 Controller 先以
  `ACTIVE_SAME_OWNER` 证据续租并原子重绑原 `SENT` 记录；不得重发 dispatch。
- Worker 报告后先出现 `STATE_WRITE_APPLIED`，然后才发送审查信封。
- Reviewer 通过后先写状态 ACK，再派发恰好一个新 Goal。
- Adaptive 中，CODE_REVIEW ACK 后先完成必要 Local Verifier 和 ROADMAP_AUDIT，
  应用前再次核对三组身份，GOALS 投影 ACK 后才切换唯一 Active milestone。
- 新 Goal 依次出现 DISPATCH outbox `PREPARED`、消息送达、`SENT` 和报告绑定的
  `COMPLETED`；恢复时不会
  生成第二个 dispatch。
- 依赖波动时先出现带 attempt/timeout/backoff 的
  `RUNTIME_DEPENDENCY_RETRYING`。
- 队列结束后依次出现 FINAL_AUDIT、FINALIZE_LOOP PREPARED、Goal 完成、业务 heartbeat
  PAUSED、`ACK_FINALIZATION` 和 `FINALIZATION_ACKED`。

### 异常信号

- `MATERIALIZE_*` 运行时 token 未替换就发给 Worker。
- 相同 `dispatch_id` 被执行两次。
- State-Writer 尚未 ACK，Controller 已派发下一任务。
- Reviewer 只看 Worker 摘要，不知道 worktree/base/head SHA。
- Worker active 时 heartbeat 被暂停或创建重复 Worker。
- event log 缺失、版本倒退或 event id 重复。
- Adaptive State-Writer 绕过确定性运行时，直接手工覆盖 `LOOP_STATE.md` 或 JSONL。
- Adaptive 中出现两个 Active milestone、Goal turn 与 heartbeat 同时持有 lease、
  CODE_REVIEW 没有对应 Worker PASS 报告、Goal 通过后被直接重派、路线图覆盖
  SENT/IN_PROGRESS 工作、CODE_REVIEW 后跳过 ROADMAP_AUDIT、dashboard 投影身份与
  canonical state 不一致，或 FINALIZE_LOOP 后没有证据绑定的 ACK_FINALIZATION。
- 用户已经给了有效预算，却因为另一个可选 cap 是 UNSPECIFIED 而停下。

## 需要用户介入的状态

- 工作区/资料/线程工具：`MISSING_PROJECT_WORKSPACE`、
  `MISSING_SOURCE_ARTIFACT`、`THREAD_TOOLS_UNAVAILABLE`、
  `THREAD_BUDGET_EXHAUSTED`、`AUTOMATION_TOOLS_UNAVAILABLE`、
  `AUTOMATION_IDENTITY_UNRESOLVED`、`MISSING_CONNECTOR`。
- Git/worktree/review：`DIRTY_WORKTREE_CONFLICT`、
  `WORKTREE_BOOTSTRAP_BLOCKED`、`THREAD_IDENTITY_UNRESOLVED`、
  `REVIEW_ARTIFACT_UNAVAILABLE`、`WORKTREE_INTEGRATION_PLAN_MISSING`、
  `PATH_SCOPE_ESCAPE`。
- 成本/审批：`BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、
  `AWAITING_HUMAN_APPROVAL`、`PHASE_PERMISSION_CONFLICT`。
- 验证/状态/自动化：`RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、
  `REPAIR_BUDGET_EXHAUSTED`、无法自动调和的 `STATE_VERSION_CONFLICT`、
  `HARD_BLOCK`。
- Standard heartbeat：`HEARTBEAT_BUDGET_EXHAUSTED`、
  `HEARTBEAT_IDLE_BUDGET_EXHAUSTED`。
- Adaptive 路线图/Goal：`ROADMAP_CHANGE_REQUIRES_APPROVAL`、
  `CONTROLLER_GOAL_CONFLICT`、`ROUTING_BUDGET_EXHAUSTED`、需要人工环境的
  `LOCAL_VERIFICATION_BLOCKED`。

`WAITING_CONTROLLER_LEASE` 和可选 `SUBAGENT_TOOLS_UNAVAILABLE` 默认不是人工门：
前者等待现有路由回合释放，后者直接回退到 Controller/Reviewer 自己完成只读工作。

表中的 `STOP` 不是“报一句话后放着不管”：Controller 必须先把精确 blocker 写入
状态并等 ACK，再暂停已有 heartbeat。你补充了正好解决该 blocker 的证据或批准后，
Controller 更新 ledger、清除该 blocker，并重新激活同一个 automation id；不能
新建第二个 heartbeat，也不能把一次批准扩大到其他阶段。

`OBSERVABILITY_GAP` 默认由 Controller 和 State-Writer自动调和，不应直接变成
人工审批；只有状态冲突无法根据 thread/report/event 证据解决时才询问用户。

## 脚本化生成

推荐先准备 JSON 输入。可以查看 schema：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --print-schema
```

检查输入：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --check-only
```

生成文件：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --controller-pack-output ./passkey-codex-loop-controller-pack.md \
  --user-guide-output ./passkey-codex-loop-usage.md
```

Full Mode：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --mode full \
  --controller-pack-output ./passkey-codex-loop-controller-pack-full.md \
  --user-guide-output ./passkey-codex-loop-usage-full.md
```

Adaptive Mode 由输入中的 `coordination_mode: "adaptive"` 选择，与 `--mode full`
是否启用无关。Adaptive 还必须提供 `adaptive_reason`、结构化 `milestones`、每个
Worker 的 `role_kind`，以及每个 Goal 的 `milestone_id`。完整输入见第三个案例。
`project_root` 可选，省略时等于 `repo`；提供时 `repo` 必须位于该项目根目录内。
子代理字段省略时默认关闭；启用时授权上限最多 2、深度固定 1，并必须同时提供全程
运行次数、重试次数和输入暴露范围。当前确定性路由每个 lease 串行执行一个 sidecar，
这个上限不是“同时并发两个”的承诺。

`--user-guide-output` 需要同时提供 `--controller-pack-output`；输入、Pack 和使用
方法三个路径必须不同，避免生成器覆盖源 JSON 或另一个输出。

输入不完整时脚本默认拒绝生成。只有明确需要不可投递草稿时才使用：

```bash
--allow-draft
```

草稿文件以 `NON_DISPATCHABLE_DRAFT` 开头，最终使用方法也会明确写“不要发送”。
JSON 顶层或嵌套对象出现重复 key 时会直接作为 input error 拒绝，避免后一个值
静默覆盖权限、review 或预算配置。

## 三个案例

### Passkey 登录

- 输入：[examples/01-passkey-login-input.json](examples/01-passkey-login-input.json)
- Controller Pack：[examples/01-passkey-login-controller-pack.md](examples/01-passkey-login-controller-pack.md)
- 使用方法：[examples/01-passkey-login-usage.md](examples/01-passkey-login-usage.md)

展示单实现 Worker、自动 Reviewer/State-Writer、auth 本地代码预授权、worktree
同目录审查和最终完整审查。

### Daily CI Triage

- 输入：[examples/02-daily-ci-triage-input.json](examples/02-daily-ci-triage-input.json)
- Controller Pack：[examples/02-daily-ci-triage-controller-pack.md](examples/02-daily-ci-triage-controller-pack.md)
- 使用方法：[examples/02-daily-ci-triage-usage.md](examples/02-daily-ci-triage-usage.md)

展示 `CI-T1` read-only triage、`TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION`、条件解锁
`CI-R1`、一个实现 worktree 和最终审查。

### Adaptive Passkey

- 输入：[examples/03-adaptive-passkey-input.json](examples/03-adaptive-passkey-input.json)
- Controller Pack：[examples/03-adaptive-passkey-controller-pack.md](examples/03-adaptive-passkey-controller-pack.md)
- 使用方法：[examples/03-adaptive-passkey-usage.md](examples/03-adaptive-passkey-usage.md)

展示四个 milestone、唯一 Active milestone、原生/emulated Controller Goal、
完整 controller lease claim、同一 Reviewer 的 CODE_REVIEW + ROADMAP_AUDIT +
FINAL_AUDIT、独立 FINALIZE_LOOP、Local Verifier、
最多两个只读子代理的授权上限（当前串行路由）、GOALS 投影、静态 dashboard 和每轮时间重估。

重新生成：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --controller-pack-output examples/01-passkey-login-controller-pack.md \
  --user-guide-output examples/01-passkey-login-usage.md

python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/02-daily-ci-triage-input.json \
  --controller-pack-output examples/02-daily-ci-triage-controller-pack.md \
  --user-guide-output examples/02-daily-ci-triage-usage.md

python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/03-adaptive-passkey-input.json \
  --mode full \
  --controller-pack-output examples/03-adaptive-passkey-controller-pack.md \
  --user-guide-output examples/03-adaptive-passkey-usage.md
```

## 本地校验

运行全部语义回归：

```bash
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -v

# 发布门：生成器畸形输入与运行时随机状态序列各跑 5000 轮
ADAPTIVE_FUZZ_CASES=5000 ADAPTIVE_STATE_FUZZ_CASES=5000 \
  python3 -m unittest discover -s tests -q
```

运行 skill 与脚本校验：

```bash
python3 -m compileall -q codex-loop-prompt-architect/scripts

python3 codex-loop-prompt-architect/scripts/validate_skill.py

bash -n scripts/install.sh
```

如果当前 Codex 安装还提供 system `quick_validate.py`，安装脚本会额外运行；
它不存在时不会阻止安装，因为仓库自带 validator 已覆盖 frontmatter、目录、
metadata、脚本编译和 schema 输出检查。

当前回归套件共 265 项；保留并扩展 Standard/CLI 基线，并新增 Adaptive schema、显式
`role_kind`、单 Active milestone、fenced Goal/heartbeat lease、路线图/Goal Queue
原子 CAS、artifact/version-bound 审查 ACK、授权范围、
Local Verifier 修复后复测、review/local outbox、canonical authorization envelope、
共享 Goal/heartbeat routing budget、Worker FAIL/BLOCKED 有界修复、路线图独立 lease、
原子失败回滚、takeover 恢复、跨 TTL 的同 owner `SENT` Worker 续租且不重发、create 后任务索引短暂不可见及 active/额度排队的同 id 恢复、Controller 父/自身任务身份隔离、subagent ACK、
dashboard 触发、Goal 工具降级、runtime 派发 payload codec、formal report 顶层来源身份、
canonical JSON、三字段 ACK result、报告/outbox/ledger 精确绑定和零副作用拒绝、跨 milestone Controller Goal 切换、同 milestone sibling 复用、STOP_LOOP 与终态组合一致性测试。独立审查后的回归还覆盖稳定目录锁与首次初始化/清理竞态、dashboard 事件排序及 evidence/decision 展示、外部 Codex worktree 白名单、任务/角色/heartbeat 单例预算、严格工具结果观察、out-of-envelope 路线图审批分流、独立 PREPARED 取消，以及三个先前观察回合后只能由新 GOAL_TURN 执行的 STOP。
原 Standard 覆盖还包括中文/英文成本检测、否定语义、provider 文档误报、
`fake/mock` 成本绕过、无限/零/模糊预算、schema 类型与重复 key、placeholder、
glob/path/control-plane scope、repo mode、分支创建权限、重复角色、多
State-Writer/Reviewer、Goal/Dispatch ID、Goal Queue、triage、thread/automation/
dispatch outbox、严格 JSON/JSONL 状态、heartbeat wake CAS、STOP/恢复、limited
完成、repair/runtime retry、同目录 worktree Review、Full Mode、原子文件输出和
不可投递草稿。Adaptive 测试直接覆盖唯一确定性 runtime；`protocol_model.py` 只从 runtime
与两个公开 schema 派生只读协议目录，不再维护第二套可漂移状态机。测试还包含终态可达性和 1000 轮确定性畸形
输入验证/草稿渲染、确定性运行时随机请求序列与真实 lease acquire/release 重放、
正式 Draft 2020-12 Schema fixture 校验；发布前本地审查把生成器和运行时两组 fuzz
分别提高到 5000 轮。它还会保持两个
Standard fixture 的原始字节哈希，并逐字节核对第三个 Adaptive fixture；在隔离
`CODEX_HOME` 中验证
安装、旧备份迁移、缓存排除和安装失败回滚。GitHub Actions 会在 push/PR 自动运行
同一套检查。三个示例都来自真实生成器输出。

这些是 local checks。Adaptive 当前按 `beta/experimental` 发布；示例生成、确定性
runtime、测试、fuzz 和安装通过，不等于每个 Codex App 版本的真实任务 loop 都能
自动循环到终态。

## 真实 Codex App E2E

本仓库保留了一次在本机“测试 loop”Codex Project 中运行的受限 smoke 作为历史证据。
它曾覆盖以下场景，但不再是本次 beta 发布必须重新通过的发布门：

- 非 Git 隔离目录和两个 milestone。
- 一个 Controller、一个 State-Writer、一个可复用 Worker、一个按需 Reviewer。
- Reviewer 先 CODE_REVIEW，再在必要本机验证后做 ROADMAP_AUDIT；审计必须实际改变
  一次未来路线，最后再做 FINAL_AUDIT。
- 一个短 heartbeat，验证 Goal/heartbeat 共用 routing budget、完整 `controller_lease`
  竞争、同一活跃 Controller 超过 TTL 后安全续租且不伪造 `STALE`、无重复 dispatch、
  独立 FINALIZE_LOOP 和最终 PAUSED。
- State-Writer 只调用确定性状态运行时；真实 E2E 同时保存运行时 CAS 拒绝零副作用、
  journal 恢复、outbox ACK 和结构化状态码证据。
- Reviewer 报告必须在顶层重复 source Worker dispatch/report/thread 和 artifact 身份；
  缺失或错绑时 formal ACK 保持 SENT 且 state/events/journal 零副作用。
- 验证 canonical authorization envelope、review/local SENT outbox、最新 Worker artifact
  绑定、失败事务回滚和 lease takeover 后 proposal 恢复。
- 一个只读子代理，必须先有 DELEGATION PREPARED/SENT，结果报告在 ACK 事务中归档；
  只有 COMPLETED + ACKED 后才可作为证据。
- 禁止外部网络写入、push、merge、deploy、凭证和生产数据。

发布说明必须把它称为当前 App/机器上的受限且失败的历史 smoke，不得升级成所有
Codex 版本、所有项目类型或长期正式验收都已证明。

### 2026-07-11 实测结论

唯一 final E2E 确实在同一 Codex Project 中完成了四个正式任务、两阶段 Worker、三类
审查、路线图修改、finalization receipt 与业务 heartbeat 暂停；但它不计为发布 PASS。
冻结状态中，M1 assurance outbox 写的是 `INVALID_FORMAL_REPORT`，对应 ledger 却写成
`REVIEW_PASS_WITH_LIMITATION`；同时原生 Controller Goal 始终绑定 M1，没有在 M2 前
切换。当前源码 runtime 会以 `ASSURANCE_STATE_INCONSISTENT` 拒绝该状态，并已增加 Goal
切换硬门。因此这次运行只能证明部分真实 App smoke，不能证明修复后最新版 Pack 的完整
E2E。完整身份、摘要、证据与边界见
[evidence/adaptive-app-e2e-20260711.md](evidence/adaptive-app-e2e-20260711.md)。

按本次发布约束，该 E2E 已冻结，不会创建连续编号、替代版、最小版或其他变相 E2E。
暴露的 assurance ACK/ledger 和 Controller Goal 切换问题，以及后续独立审查发现的
锁、控制面身份/预算、外部 worktree、路线图提案、PREPARED 取消与 STOP 观察顺序问题，
均已进入确定性 runtime、schema 契约与回归测试；最新修复只完成了本地测试、fuzz、生成器、CLI/runtime smoke 和安装
验证，没有重新执行真实 Codex App E2E。因此 Adaptive 以 `beta/experimental` 发布，
不能声称最新 Pack 已在真实 App 中完整到达终态。

## 升级兼容性

- 现有用户不需要改变调用或启动方式。
- 未提供 `coordination_mode` 的旧 JSON 默认 `standard`。
- 原有 Standard 示例和输出保持字节级 fixture 兼容。
- Adaptive 是显式新增能力，不会让小任务自动生成 GOALS、dashboard 或更多正式任务。
- `verifier`/`auditor` 旧名称仍可在 Standard 中兼容推断；Adaptive 必须用明确
  `role_kind`，避免 Local Verifier 被误当作代码 Reviewer。

## 许可证

MIT. See [LICENSE](LICENSE).
