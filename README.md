# Codex Loop Prompt Architect

`codex-loop-prompt-architect` 是一个只面向 Codex macOS App 的 skill。它把
不成熟、信息不完整或容易断停的需求，转换成一个可直接发送给控制线程的
Controller Pack Markdown 文件，并另外告诉用户怎么启动、怎么回查、可能卡
在哪里、预计需要多久。

它负责设计 loop，不负责直接实现 PRD 或修改目标项目。

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

这个 skill 生成的 loop 通过以下机制处理这些问题：

- 真实 Codex App 项目线程和稳定 `threadId`。
- dependency-ordered Goal Queue。
- 每次派发都有 `goal_id` 和唯一 `dispatch_id`。
- transactional dispatch outbox 防止发送成功但状态未落盘后重复派发。
- State-Writer compare-and-swap 状态版本与事件幂等。
- State-Writer ACK 后才能 review、repair 或进入下一 Goal。
- Worker active 时使用 `WAITING_ACTIVE`，heartbeat 不会关闭或重复派发。
- worktree Worker 使用同目录 Reviewer，或提供可验证的绝对 worktree 路径。
- 每个 Goal 独立声明 commit、PR、push、merge、deploy 和外部写入权限。
- 有超时、无进展 watchdog、退避和总耗时上限的下载重试梯队。
- 每个 Goal 审查，加一次最终完整 diff 审查。
- `.codex-loop/` 状态、事件、分诊和报告审计面。

## 输出什么

日常 Compact Mode 输出两份内容：

1. `<project>-codex-loop-controller-pack.md`
   - 发给控制线程的唯一材料。
   - 包含 Controller、Worker、Reviewer、State-Writer、Goal Queue、First
     Goal、heartbeat、状态协议、审查门和停止条件。
2. 最终使用方法
   - 留给用户阅读，不发给控制线程。
   - 包含运行卡点、时间预估、工作区准备、启动步骤、回查方法和人工介入状态。

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
│   ├── references/loop-contract.md
│   └── scripts/
│       ├── loop_prompt_scaffold.py
│       └── validate_skill.py
├── examples/
│   ├── 01-passkey-login-input.json
│   ├── 01-passkey-login-controller-pack.md
│   ├── 01-passkey-login-usage.md
│   ├── 02-daily-ci-triage-input.json
│   ├── 02-daily-ci-triage-controller-pack.md
│   └── 02-daily-ci-triage-usage.md
├── tests/test_loop_prompt_scaffold.py
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
./scripts/install.sh
```

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
- `repo_mode`。
- 现有 Git 项目的 base/target branch。
- PRD、截图、PDF、数据集等源文件路径。
- Worker 分工、权限和路径所有权。
- 禁止路径、secrets、数据和副作用。
- 多 Worker/多阶段任务的 Goal Queue。
- validation commands。
- evidence layer 和 claim boundary。
- durable state 位置。
- review policy。
- heartbeat、wake、idle、每 Goal 修复轮数、retry 和 hard-stop 上限。
- connector 和 worktree 策略。
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

用户只创建一个控制聊天：

把 Controller Pack 发给控制线程，就表示已明确授权它在 pack 的线程数量上限内
创建、恢复、发消息和归档所声明的子线程，并创建/更新/暂停唯一 heartbeat；不必
再次询问。这不授权 deploy、merge、push、密钥、生产写入或 Controller 改代码。

1. 在 Codex App 左侧选择目标项目工作区。
2. 在这个项目下面新建“控制线程”。
3. 把生成的 Controller Pack `.md` 文件发给它。
4. Controller 调用 `list_projects` 得到 `projectId`，并计算 pack/loop/bootstrap 标记。
   若当前控制任务 ID 不可读，LOOP_ID 使用
   `SHA-256(projectId + canonical repo + PACK_SHA256)` 的确定性 fallback，不能
   随机生成。
5. Controller 运行 repo-mode-specific preflight。
6. Controller 先用 `list_threads` 恢复或创建唯一 State-Writer，初始化状态并等 ACK；
   再通过 `THREAD_CREATE_PREPARED` 恢复或创建当前 Worker。
7. 不预创建 Reviewer。Worker 报告已持久化且存在可审 artifact 后，再按需创建
   同 checkout Reviewer；worktree Reviewer 优先使用同目录线程。
8. 每个后续 `create_thread/fork_thread` 都先登记 role、environment、bootstrap
   marker 和 prompt digest；成功后写 `THREAD_REGISTERED`，不能按标题猜 threadId。
9. Controller 先写 `AUTOMATION_CREATE_PREPARED`；按“项目名 + loop_id”、目标线程、
   rrule 和 prompt digest 检查已有 automation。只有没有精确匹配时才创建，再把
   `AUTOMATION_REGISTERED`/id 写入状态并等待 ACK。
10. Controller 替换所有 `MATERIALIZE_*` 运行时 token，先把
    `DISPATCH_PREPARED` 和 payload digest 写入 outbox 并等待 ACK。
11. Controller 发送 First Goal；确认目标线程已收到后写入
    `DISPATCH_SENT` 并等待 ACK。
12. 后续按 Worker -> state ACK -> Reviewer -> state ACK -> 下一 Goal 循环。
13. Goal Queue 结束后运行 FINAL_AUDIT，最终状态 ACK 后暂停 heartbeat。

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

worktree 环境则把 `target.environment` 设为
`{type:"worktree", startingState:{type:"branch", branchName:VERIFIED_BASE_BRANCH}}`。

以下都不是有效的 Codex App Loop Worker：

- `multi_agent_v1.spawn_agent`
- `agent_type`
- `fork_context`
- `agentId`
- “创建智能体”

缺少真实线程工具时，Controller 输出 `THREAD_TOOLS_UNAVAILABLE`，然后由
用户决定是否进入手动降级。

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

每次 heartbeat 唤醒先处理遗留状态请求，再用
`automation_id + next wake_count` 生成稳定 wake event，经 State-Writer CAS
写入一次 `HEARTBEAT_WAKE` 并等待 ACK。重复唤醒不能把同一次 wake 计数两遍。

同一时间最多一个写入型 execution Worker。State-Writer 可串行写状态；Reviewer
只在有可审 artifact 时短期并存，不预创建未来阶段线程。
`max_child_threads` 是整个 loop 生命周期总上限：不含 Controller，但已归档任务
仍计数；达到上限时复用现有任务或停止 `THREAD_BUDGET_EXHAUSTED`，不能继续堆线程。

默认所有顺序写入 Goal 共享一条 integration worktree。角色不变时复用同一
Worker；确实需要更换写入角色时，只能在前一 Writer idle 且报告/状态 ACK 后，
按需调用 `fork_thread(threadId=PRIOR_WRITER_THREAD_ID,
environment={type:"same-directory"})`，再发送新角色的完整 bootstrap prompt。
只有 Goal Queue 明确给出 promotion/merge 计划和权限时，才允许分叉写入 worktree，
否则停止 `WORKTREE_INTEGRATION_PLAN_MISSING`。

已完成且不会复用的 Worker/Reviewer 在报告和状态 ACK 后通过
`set_thread_archived(..., archived=true)` 归档；不能归档 active、未 ACK 或仍需
修复的任务，State-Writer 必须保留到最终状态 ACK。

heartbeat 只有在以下情况暂停：

- `LOOP_COMPLETE` 等终态已经写入并 ACK。
- 没有 inflight/queue，且 idle 预算耗尽。
- 总 wake 预算耗尽并已记录 `HEARTBEAT_BUDGET_EXHAUSTED`。

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

non-git 或未提交 new_git 的产品 before/after digest 只覆盖获批产品 scope；
`.codex-loop`、声明过的原有无关文件和 cache 从产品 digest 排除，但必须输出
exclusion manifest 供 FINAL_AUDIT 单独检查，避免状态写入制造假产品 diff。

Goal 派发采用 transactional outbox：

1. 生成唯一 `dispatch_id` 和稳定 payload digest。
2. 写入 `DISPATCH_PREPARED`，等待 State-Writer ACK。
3. 向真实目标 threadId 发送一次。
4. 写入 `DISPATCH_SENT`，等待 State-Writer ACK。
5. heartbeat 恢复到 PREPARED 状态时，先按 `dispatch_id` 查询目标线程；只有
   确认未送达才重发。Worker 收到重复 `dispatch_id` 时返回既有报告，不能重做。

每个 Goal 还必须物化一份有界 canonical state 快照，至少包含 state version、
repo/worktree、依赖、审批/预算切片、重试计数、原有脏文件和 claim/evidence 边界。
只给 worktree Worker 一个 `.codex-loop/LOOP_STATE.md` 路径不算自包含。

## worktree 审查

Reviewer 必须看到 Worker 的真实代码，而不是只看文字摘要。
任何 `workspace_write` Goal 都不能把 review 关闭；脚本会拒绝
`review not required`。只有纯只读、无 diff 的 loop 可以省略代码审查。

local Worker：

- Reviewer 可在相同项目 checkout 中读取代码。
- Git 工作的 `/review` 带 base/head SHA、完整 patch 和 `diff_sha256`。
- `non_git` 或尚未提交的 `new_git` 使用 before/after manifest 与 snapshot
  SHA-256；不可用 Git SHA 写 `NOT_APPLICABLE`。

worktree Worker：

- 优先使用真实 Codex App
  `fork_thread(threadId=WORKER_THREAD_ID, environment={type:"same-directory"})`。
- 如果同目录 fork 不可用，Reviewer 必须能读取绝对 worktree 路径，并拿到
  base SHA、head SHA、changed files、`diff_sha256` 和完整 patch/diff。
- 任何一项无法证明时输出 `REVIEW_ARTIFACT_UNAVAILABLE`，不能只根据 Worker
  摘要给 `REVIEW_PASS`。

每个 Goal 的 diff 需要审查。所有 Goal 完成后，还要对完整 Git base-to-head 或
`non_git` before-to-after snapshot diff 运行一次 FINAL_AUDIT。

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

`unlimited`、`尽量跑完`、`自行控制成本` 等无上限表达不是有效 policy。
只限制“运行几小时/几天”也不能约束花费，因此不能单独作为付费调用授权。

目标里出现 `fake`、`mock`、`placeholder` 不等于成本授权或 deferred policy。
中文“真实大模型调用、付费模型评分、计量调用”等同样会触发成本闸。

审批写进 `approval_ledger`。已经明确预授权的本地代码和测试不应反复询问；
生产 deploy、merge、secrets、用户数据删除、迁移、真实外部写入和超证据声明
仍需对应范围的授权。

## 怎么回查 loop

### 看线程

- 控制线程：Goal Queue、真实 threadId、dispatch_id、状态 ACK、下一动作。
- 实现线程：worktree、base/head SHA、changed files、diff summary、验证 exit code。
- 审查线程：按严重度排序的 file/line findings、reviewed SHA、test gaps。
- 状态线程：event/request id、state version、transaction journal 和写入结果。

### 看文件

- `.codex-loop/LOOP_STATE.md`
  - 当前状态版本、Goal Queue、thread-creation/automation/dispatch outbox、
    inflight dispatch、线程登记、预算和审批 ledger。
- `.codex-loop/LOOP_EVENTS.jsonl`
  - 每次派发、ACK、重试、审查和停止的 append-only 流水。
- `.codex-loop/TRIAGE.md`
  - 分诊发现、证据、`TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION` 和后续 Goal。
- `.codex-loop/reports/`
  - Worker、Reviewer 和 FINAL_AUDIT 报告。
- `.codex-loop/transactions/`
  - State-Writer 按 `state_request_id` 保存的 `PREPARED/APPLIED` 恢复日志，
    用于补齐中断事务，不是第二份状态源。
- `.codex-loop/sources/CONTROLLER_PACK.md`
  - 初始化时归档的精确 pack 快照和对应 `PACK_SHA256`；heartbeat 优先读它，
    避免长对话压缩后依赖不完整聊天摘要。
- Codex Automation 卡片
  - automation id、ACTIVE/PAUSED、rrule、目标线程和运行次数。

### 正常推进信号

- Worker active 时 heartbeat 记录 `WAITING_ACTIVE`，仍保持 ACTIVE。
- Worker 报告后先出现 `STATE_WRITE_APPLIED`，然后才 `/review`。
- Reviewer 通过后先写状态 ACK，再派发恰好一个新 Goal。
- 新 Goal 依次出现 `DISPATCH_PREPARED`、消息送达、`DISPATCH_SENT`；恢复时不会
  生成第二个 dispatch。
- 依赖波动时先出现带 attempt/timeout/backoff 的
  `RUNTIME_DEPENDENCY_RETRYING`。
- 队列结束后出现 FINAL_AUDIT，再出现 `LOOP_COMPLETE`。

### 异常信号

- `MATERIALIZE_*` 运行时 token 未替换就发给 Worker。
- 相同 `dispatch_id` 被执行两次。
- State-Writer 尚未 ACK，Controller 已派发下一任务。
- Reviewer 只看 Worker 摘要，不知道 worktree/base/head SHA。
- Worker active 时 heartbeat 被暂停或创建重复 Worker。
- event log 缺失、版本倒退或 event id 重复。
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
  `HEARTBEAT_BUDGET_EXHAUSTED`、`HEARTBEAT_IDLE_BUDGET_EXHAUSTED`、
  `HARD_BLOCK`。

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
  --controller-pack-output ./passkey-codex-loop-controller-pack.md
```

Full Mode：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --mode full \
  --controller-pack-output ./passkey-codex-loop-controller-pack-full.md
```

输入不完整时脚本默认拒绝生成。只有明确需要不可投递草稿时才使用：

```bash
--allow-draft
```

草稿文件以 `NON_DISPATCHABLE_DRAFT` 开头，最终使用方法也会明确写“不要发送”。
JSON 顶层或嵌套对象出现重复 key 时会直接作为 input error 拒绝，避免后一个值
静默覆盖权限、review 或预算配置。

## 两个案例

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

重新生成：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --controller-pack-output examples/01-passkey-login-controller-pack.md \
  > examples/01-passkey-login-usage.md

python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/02-daily-ci-triage-input.json \
  --controller-pack-output examples/02-daily-ci-triage-controller-pack.md \
  > examples/02-daily-ci-triage-usage.md
```

## 本地校验

运行全部语义回归：

```bash
python3 -m unittest discover -s tests -v
```

运行 skill 与脚本校验：

```bash
python3 -m py_compile \
  codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py

python3 codex-loop-prompt-architect/scripts/validate_skill.py

bash -n scripts/install.sh
```

如果当前 Codex 安装还提供 system `quick_validate.py`，安装脚本会额外运行；
它不存在时不会阻止安装，因为仓库自带 validator 已覆盖 frontmatter、目录、
metadata、脚本编译和 schema 输出检查。

当前回归套件共 110 项，覆盖中文/英文成本检测、否定语义、provider 文档误报、
`fake/mock` 成本绕过、无限/零/模糊预算、schema 类型与重复 key、placeholder、
glob/path/control-plane scope、repo mode、分支创建权限、重复角色、多
State-Writer/Reviewer、Goal/Dispatch ID、Goal Queue、triage、thread/automation/
dispatch outbox、严格 JSON/JSONL 状态、heartbeat wake CAS、STOP/恢复、limited
完成、repair/runtime retry、同目录 worktree Review、Full Mode、原子文件输出和
不可投递草稿。它还会逐字节核对两个示例 fixture，并在隔离 `CODEX_HOME` 中验证
安装、旧备份迁移、缓存排除和安装失败回滚。GitHub Actions 会在 push/PR 自动运行
同一套检查。

这些是 local checks。示例生成通过并不等于每个 Codex App 版本的真实线程
loop 已完成端到端运行；发布前仍应在当前 App 版本做一个受控 smoke。

## 许可证

MIT. See [LICENSE](LICENSE).
