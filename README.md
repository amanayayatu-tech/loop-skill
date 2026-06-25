# Codex Loop Prompt Architect

`codex-loop-prompt-architect` 是一个只面向 Codex macOS App 的 skill，用来把不成熟、上下文不完整、容易失控的提示词，改造成可以投递到 Controller / Worker / Reviewer / State-Writer 多线程体系里的 Codex Loop 提示词。

它不是“替你写代码”的 skill，而是“替你设计 loop prompt 系统”的 skill。

## 它解决什么问题

普通提示词通常只有一句目标，例如：

```text
帮我修一下登录流程，顺便跑测试，没问题就继续推进。
帮我把这个 PRD 完整的做出来，并且可运行。
```

这种提示词在 Codex 多线程或自动化场景里很容易出问题：

- Controller 和 Worker 角色混在一起。
- Worker 可能越权改文件。
- 没有明确 stop rule，容易无界循环。
- 模型可能把 smoke test 说成正式通过。
- 实现者可能自审。
- 多个 Worker 可能同时写 `LOOP_STATE.md`，导致状态撕裂。
- repo 文件、日志、issue 里可能藏有 prompt injection。
- 输出后用户不知道应该发给哪个线程。

这个 skill 会把粗糙提示词改成两层交付物：

1. **Controller Pack Markdown 文件**：发给控制线程的唯一材料，里面包含完整 Controller/Worker/Reviewer/State-Writer/First Goal。
2. **最终使用方法**：给用户看的中文说明，告诉你怎么启动、可能卡在哪、预估耗时、在哪里回查、什么时候需要介入。

Controller Pack 里包含可执行的 loop 体系：

- `Controller Prompt`
- `Worker Prompt`
- 自动补齐的 `Reviewer/Judge Prompt`
- 自动补齐的 `State-Writer Prompt`
- 第一个原子 `/goal`
- `Thread Bootstrap / Input Gates`
- `Heartbeat Automation Template`
- `Discovery/Triage`
- `Connector/Worktree Runtime Mapping`
- 明确的停止条件、人工审批门和证据边界

## 仓库结构

```text
loop-skill/
├── codex-loop-prompt-architect/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/loop-contract.md
│   └── scripts/loop_prompt_scaffold.py
├── examples/
│   ├── 01-passkey-login-input.json
│   ├── 01-passkey-login-controller-pack.md
│   ├── 01-passkey-login-usage.md
│   ├── 02-daily-ci-triage-input.json
│   ├── 02-daily-ci-triage-controller-pack.md
│   └── 02-daily-ci-triage-usage.md
├── scripts/install.sh
├── LICENSE
└── README.md
```

只有 `codex-loop-prompt-architect/` 是真正要安装到 Codex App 的 skill 目录。顶层 README、examples 和 install script 是发行说明，不需要放进 Codex skill 运行目录。

## 安装到 Codex macOS App

### 方法一：使用安装脚本

```bash
git clone https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
./scripts/install.sh
```

安装目标位置：

```bash
${CODEX_HOME:-$HOME/.codex}/skills/codex-loop-prompt-architect
```

如果本机已经有旧版本，安装脚本会先把旧版本移动到带时间戳的 backup 目录，再复制新版本。

安装后，打开一个新的 Codex App 线程。如果 skill 没有出现，重启 Codex App，让它重新加载本地 skills。

### 方法二：手动安装

```bash
git clone https://github.com/amanayayatu-tech/loop-skill.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R loop-skill/codex-loop-prompt-architect "${CODEX_HOME:-$HOME/.codex}/skills/"
```

然后在新的 Codex App 线程里使用：

```text
Use $codex-loop-prompt-architect，把下面这个不成熟提示词改成 Codex Loop 提示词体系：

[粘贴你的粗糙提示词]
```

## 最简单的用法

推荐日常使用这个短版来“生成 loop 提示词”：

```text
Use $codex-loop-prompt-architect，短版：把下面提示词变成可投递的 Codex macOS App Loop；如果信息不够，先反问，不要输出完整版。

[粘贴你的粗糙提示词]
```

如果粗糙提示词依赖 PRD、截图、PDF、设计稿或数据文件，第一条消息里要同时说明这些资料在哪里。推荐两种方式：

- 把资料放进将要执行任务的 Codex 工作区，例如 `docs/PRD.md`、`docs/spec.pdf`。
- 或者直接在提示词里写绝对路径，例如 `/Users/you/Downloads/Product_PRD.docx`。

如果关键信息不够，skill 应该先反问，而不是直接生成完整版。常见必须补足的信息包括：

- 目标和验收标准。
- Codex App 里的项目/工作区名称，以及它对应的本地根目录。
- repo/root/branch。
- 如果要用独立 worktree：区分已存在且可验证的 base branch/ref，以及目标实现分支。目标实现分支不存在时，不能把它当成 worktree 启动分支。
- Worker 分工。
- 每个 Worker 的权限：`read_only`、`workspace_write` 或 `state_write_only`。
- 允许写哪些路径。
- 禁止碰哪些文件、数据源、动作或 secrets。
- durable state 写在哪里。
- validation commands。
- evidence layer。
- review gate。
- 是否需要 automation / heartbeat。
- 是否依赖 GitHub、Linear、Slack、Notion 等 connector。
- 是否需要独立 worktree。
- 是否会运行 `codex exec`、真实 LLM/API、provider/backend、模型评分 smoke、付费 API 或其他按量计费服务；如果会，必须说明 `cost_cap_usd`、调用次数/Token 上限，或者明确“先占位/延后，停在 `BLOCKED_COST_CAP`”。
- 是否真的需要多个 Worker 并行或多个阶段专用线程；默认应该只用当前 Worker + Reviewer + State-Writer。
- 是否当前 Codex App 暴露了 `create_thread` / `read_thread` / `send_message_to_thread` / `automation_update` 等线程工具。没有线程工具时只能停在 `THREAD_TOOLS_UNAVAILABLE` 或进入手动降级，不能用内部 sub-agent 冒充线程。
- 需要哪些源文件/附件：PRD、截图、PDF、设计稿、数据文件等。
- 用户后续应该看哪些状态文件、事件日志和报告目录来回查 loop 是否按预期运行。

如果用户坚持要草稿，skill 会标记为 `NON_DISPATCHABLE_DRAFT`，不会把它说成 ready-to-send。

正式输出 loop 之后，最终使用方法里还会给两类预期，不能只藏在 Controller Pack 里：

- `运行中卡点预估`：只预测 loop 已经可以启动以后，仍然可能因为审批、真实外部服务、人工验收、审查修复、connector/runtime 或审计日志断档而停下的阶段。它不会把 repo/root/PRD/工作区缺失这类启动前问题包装成运行中风险。
- `预计耗时`：给出 min / typical / max 的本地 Codex loop wall-clock 估算，并明确不计入等待用户提供 API key、批准 deploy/merge、真人验收、离线业务判断或 registry/network 恢复的时间。
- `成本/付费调用闸`：如果任务可能运行 `codex exec`、真实 LLM/API、provider/backend、模型评分 smoke、付费 API 或 Token 计量调用，最终用法必须明确当前 `cost_cap_usd`、调用/Token 上限，或说明会在该阶段前停到 `BLOCKED_COST_CAP`。这类缺失不能让用户跑到后半程才意外发现。
- `线程数量原则`：默认精简拓扑，不按阶段提前创建一堆 Worker。正常情况下只需要一个当前 Worker、一个 Reviewer、一个 State-Writer；Explorer 和额外 Worker 只有在目标已经可派发、需要独立 worktree/专业角色/并行时才按需创建。
- `线程工具边界`：自动模式必须用 Codex App 的 `create_thread(target.type="project", projectId=...)` 创建真实项目线程。`multi_agent_v1.spawn_agent`、`agent_type`、`fork_context`、`agentId`、"创建智能体" 都不是 Codex App loop 线程。
- `worktree/分支启动边界`：目标实现分支不是默认可用的 worktree 起点。Controller 必须先验证 existing base branch/ref；目标分支不存在时，应从当前工作树或已验证基线启动 Worker，再让 Worker 在 `/goal` 里创建/切换目标分支。
- `线程身份边界`：真实身份是 `threadId`，不是标题、搜索关键词、分支名或 `pendingWorktreeId`。如果 pending worktree 后来生成了标题不对的线程，Controller 必须通过 projectId、cwd/worktree、bootstrap prompt、`READY_IDLE_AWAITING_GOAL` 等证据找回真实 Worker，重命名并登记，不能一直 heartbeat no-op。

对 Web/Node/前端项目，`运行中卡点预估` 会默认提醒首轮依赖安装和本地验证环境风险，例如 Next.js/SWC、Playwright、Sharp、canvas、Electron、native binary、大包下载、`pnpm`/`npm` store 或 lockfile 问题。遇到这类情况时，loop 不应该立刻卡死等用户处理；应该先进入 `RUNTIME_DEPENDENCY_RETRYING`，自动执行至少 10 次有策略的重试，包括延长 timeout、断点/分段/预取、降低并发、换安全公开 registry/source、清理项目内部分安装残留等。只有重试耗尽或错误明显不是临时波动时，才输出 `RUNTIME_DEPENDENCY_BLOCKED` 或 `VALIDATION_BLOCKED`。无论哪种情况，都不能把“源码已生成/静态审查通过”说成完整 PASS。

对需要真实 LLM/API、`codex exec` 或模型评分 smoke 的 loop，缺少预算上限不是普通运行中卡点，而是前置成本闸。生成前应该先问；如果用户明确选择延后或占位，Controller 可以继续跑本地-only 阶段，但必须在付费/计量阶段前停在 `BLOCKED_COST_CAP`，并且不能提前创建那个未来阶段的 Worker。

## Full Mode 用法

高风险任务、多 Worker、自动化、PR 合并、发布、auth/billing/security/secrets、生产数据、公开声明、科学/产品结论等任务，建议使用 Full Mode：

```text
Use $codex-loop-prompt-architect，Full Mode：
请把下面任务改成 Codex macOS App loop prompt，并输出 L1-L12 诊断、Controller/Worker/Goal、Automation、Discovery/Triage、Runtime Mapping、怎么发。

[粘贴你的粗糙提示词]
```

Full Mode 会额外输出：

- L1-L12 loop diagnosis。
- Loop Integrity Score。
- hard risks。
- changelog。
- flow map。
- test goals。
- final next step。

## 脚本化生成 scaffold

如果你已经知道结构化字段，可以直接调用脚本生成 scaffold：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --objective "Implement passkey-first login with email fallback" \
  --repo /workspace/myapp \
  --project-name myapp \
  --workspace-setup "Open /workspace/myapp as a Codex Project before starting; use worktree for writing Workers" \
  --branch feature/passkey-login \
  --base-branch main \
  --target-branch feature/passkey-login \
  --workers "implementation:write auth code" \
  --permissions "implementation:workspace_write" \
  --allowed "src/auth/**,tests/auth/**" \
  --forbidden "billing,database migrations,secrets,CI deploy config" \
  --validation "npm test -- auth;npm run lint;npm run typecheck" \
  --evidence "local checks" \
  --claim "candidate implementation only" \
  --state ".codex-loop/LOOP_STATE.md" \
  --source-artifacts "docs/auth-spec.md and attached screenshots" \
  --metered-runtime-policy "no real LLM/API/codex exec calls; keep AI/provider behavior placeholder unless user later supplies cost_cap_usd" \
  --max-child-threads 4 \
  --runtime-readiness "READY_BUT_LIKELY_REVIEW_REPAIRS" \
  --runtime-retry-attempts 10 \
  --time-min "45-90 分钟" \
  --time-typical "2-4 小时" \
  --time-max "4-8 小时" \
  --time-factors "auth edge cases,browser/passkey support,native dependency install,test fixture setup,Reviewer repair rounds" \
  --discovery "CI failures, auth issues, recent auth commits" \
  --triage-output ".codex-loop/TRIAGE.md" \
  --connectors "GitHub connector if exposed; otherwise manual PR links" \
  --worktree-policy "one Codex worktree per writing Worker" \
  --controller-pack-output ./passkey-codex-loop-controller-pack.md
```

使用 `--controller-pack-output` 时，脚本会把发给控制线程的 Markdown 写入该文件，并在终端输出给用户看的“怎么用、卡点预估、耗时预估、怎么回查”。

`--branch` 保留为兼容字段，默认会被当成目标实现分支。需要独立 worktree 时，建议显式提供 `--base-branch` 和 `--target-branch`：`--base-branch` 必须是本地已存在并可验证的 ref，`--target-branch` 可以是 Worker 在 `/goal` 中创建的新分支。不要把一个尚不存在的新分支直接当成 worktree starting branch。

默认 `运行中卡点预估` 和 `预计耗时` 是启发式预测：脚本只扫描用户显式提供的字段和非自动补齐 Worker 的职责，并使用 token-aware 匹配，避免把 `maintainable`、`requirements`、`decision` 这类词误判成 `ai`、`ui`、`ci`。高风险或复杂任务建议显式传入 `--runtime-readiness`、`--runtime-blockers`、`--time-*` 覆盖默认预测。

如果结构化输入里出现 `codex exec`、真实 LLM/API、provider/backend、模型评分 smoke 或其他计量执行信号，但没有提供 `--cost-cap-usd` / `--call-cap` / `--token-cap` / `--metered-runtime-policy`，`--check-only` 应该提示缺少 `cost_cap_usd_or_metered_runtime_policy`。如果只是想先占位，显式传入类似：

```bash
--metered-runtime-policy "deferred: run local-only stages, then stop with BLOCKED_COST_CAP before any codex exec or real LLM/API call"
```

默认线程拓扑是 lean / just-in-time：启动时只创建当前 Worker、Reviewer、State-Writer。不要为 R/S/T/U/W 这类顺序阶段提前创建多个 Worker；后续阶段优先复用同一个实现线程，只有明确需要独立 worktree、专业角色或并行时才新建。

生成前检查缺失字段：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --check-only \
  --objective "Fix README typo"
```

如果缺少必需字段，脚本会以非零状态退出，并列出缺少的字段。

## 输出内容长什么样

Compact Mode 默认输出两类内容：

1. 一个 Controller Pack `.md` 文件：发给控制线程的唯一材料。
2. 一段最终使用方法：给用户看，不发给控制线程。

Controller Pack 文件内部包含：

- `Controller Prompt`
- `Worker Prompt`
- `Reviewer Prompt`
- `State-Writer Prompt`
- `First Goal`
- durable state schema
- retry/stop rules
- review gate
- human approval gate
- evidence boundary
- thread bootstrap/input gates：Worker 只响应 `/goal`，Reviewer 只响应 `/review`，State-Writer 只响应 `/state_update`

如果任务是 recurring loop、多线程、需要 connector、需要 worktree 或可能进入自动化，Controller Pack 还会包含：

- `Runtime Mapping`
- `Transient Runtime Retry Policy`
- `Heartbeat Automation Template`
- `Discovery/Triage`
- connector fallback
- worktree isolation policy

最终使用方法必须单独包含：

- `运行中卡点预估`：loop 已经能启动后，可能在哪些阶段停下、触发什么状态、自动处理到什么程度才问你。
- `预计耗时`：min / typical / max，以及哪些等待时间不算进去。
- `你应该怎么用`：选择哪个工作区、在哪里建控制线程、把哪个 md 文件发过去。
- `怎么回查 loop`：看哪些线程和哪些 `.codex-loop/` 文件。
- `你只需要介入`：哪些状态需要用户回来处理。

生成出来的 Worker 通常包括：

- `implementation`：只允许在 scoped write set 内写代码。
- `reviewer`：当 review required 时自动补齐，且是 read-only。
- `state-writer`：自动补齐，唯一负责串行写 durable state。

## 输出之后应该怎么用

默认是 Codex macOS App 自动项目模式：你只启动一个控制线程，但这个控制线程必须在目标项目/工作区里启动。你发给控制线程的是生成的 Controller Pack `.md` 文件，不是从聊天里复制很多段 prompt。

### 1. 先准备工作区

1. 在本地准备一个文件夹。新项目尽量用空白文件夹，例如 `~/Documents/my-new-app`。
2. 在 Codex App 左侧“项目”里打开或添加这个文件夹，让它成为一个 Codex Project/Workspace。
3. 把 PRD、截图、PDF、设计稿、数据文件等资料放进这个工作区，推荐放到 `docs/`。
4. 如果资料暂时不在工作区，第一条 Controller 消息里必须写明绝对路径，或直接把文件附上。

### 2. 再启动控制线程

1. 在这个项目/工作区下面新建聊天，命名为“控制线程”。
2. 把生成的 Controller Pack `.md` 文件发给控制线程。不要手动拆分复制 Controller/Worker/Reviewer/State-Writer 段落。
3. 控制线程会先调用 `list_projects` 或等价工具，找到当前工作区的 `projectId`。
4. 控制线程创建实现/审查/状态线程时，必须使用 `create_thread` 的 project target，例如 `target.type="project"` + 同一个 `projectId`。这样新线程会出现在同一个左侧项目工作区下面。
5. 控制线程不能用内部 sub-agent 代替线程。只要看到 `multi_agent_v1.spawn_agent`、`agent_type`、`fork_context`、`agentId`、`Jason(worker)`、`创建智能体` 这类输出，就说明它没有创建真正的 Codex App 项目线程，应停在 `THREAD_TOOLS_UNAVAILABLE` 或手动降级。
6. 如果使用独立 worktree，控制线程必须先验证 starting branch/ref 存在。目标实现分支如果还不存在，不能直接作为 `startingState.branchName`；应从当前工作树或已验证 base branch 启动，再由 Worker 在 `/goal` 里创建/切换目标分支。
7. 控制线程必须登记真实 `threadId`。`pendingWorktreeId` 只能临时记录，标题只能用于显示；如果线程标题不符合预期，要 broad list 项目线程按 cwd/worktree、projectId、bootstrap prompt、idle 状态找回并重命名。
8. 如果控制线程无法找到项目，它应该输出 `MISSING_PROJECT_WORKSPACE` 并停止。不要让它创建 projectless 普通对话线程。

### 3. 自动 loop 怎么跑

控制线程会自动做这些事：

1. 创建或继续实现线程、审查线程、状态线程。
2. 先把各线程初始化到 idle：实现线程等待 `/goal`，审查线程等待 `/review`，状态线程等待 `/state_update`。初始化本身不能触发实现、审查或写状态。
3. 立即创建 heartbeat 自动唤醒，默认每 15 分钟唤醒控制线程；没有 heartbeat 就不算完整自动 loop。
4. 发送 `First Goal` 给第一个实现线程。
5. 读取 Worker 回报，批准或拒绝 `state_change_request`。
6. 把批准后的状态更新发给 `state-writer`。
7. 只有拿到 Worker 报告、changed files、validation、evidence 和 diff summary 后，才给审查线程发送 `/review`。
8. 审查不过时继续发修复任务；通过后由 heartbeat 推进下一个 goal；达到 retry/wakeup 上限后停止。

你只需要在这些情况介入：

- 需要真实订阅链接、支付链接、社群链接或密钥。
- 需要批准 PR merge、deploy、release 或真实外部写入。
- 出现 `AWAITING_HUMAN_APPROVAL`、`MISSING_CONNECTOR`、`MISSING_PROMPT_PACK`、`MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`WORKTREE_BOOTSTRAP_BLOCKED`、`THREAD_IDENTITY_UNRESOLVED`、`OBSERVABILITY_GAP` 或 `HARD_BLOCK`。
- 出现 `BLOCKED_COST_CAP` 或 `BLOCKED_USAGE_METADATA`。这表示后续需要真实付费/计量调用，但预算、调用/Token 上限或用量元数据边界还不够明确。
- 出现 `THREAD_TOOLS_UNAVAILABLE` 或 `MANUAL_FALLBACK_REQUIRED`。这表示当前环境没有可用的 Codex App 线程工具；不能用 sub-agent 顶替。
- 需要真人可用性测试证据，或你决定接受 waiver。

### 4. 怎么回查 loop 是否按预期在跑

先看 Codex App 左侧项目工作区：

- 控制线程、实现线程、审查线程、状态线程都应该在同一个项目下面。
- 如果实现/审查/状态线程跑到了普通对话列表，说明 Controller 没有正确使用 project target，需要停下修正。
- 如果左侧没有出现真实线程，而日志里出现“创建智能体”、`agentId` 或 `Jason/Descartes/Galileo` 这类 sub-agent 名称，说明 loop 跑错运行层了。让控制线程停止，不要继续执行。

再看线程职责：

- 控制线程：看每一步派发给谁、为什么派发、下一步等什么。
- 实现线程：看改了哪些文件、跑了哪些命令、验证结果是什么。
- 审查线程：先应是 idle，收到 `/review` 后才看 `PASS`、`NEEDS_REPAIR` 或具体 review findings。
- 状态线程：看它是否只写状态/日志，不写业务代码。
- heartbeat 自动化：看 Codex Automation/heartbeat 卡片是否 active、间隔是否正确、目标是否是控制线程。

再看工作区里的 loop 文件。它们不是装饰文件，是用来回查 loop 是否真的按预期运行的审计轨迹：

- `.codex-loop/LOOP_STATE.md`：当前进度快照；看现在在哪个阶段、卡点是什么、下一步做什么。
- `.codex-loop/LOOP_EVENTS.jsonl`：逐步流水账；看每次派发、回报、重试、审查、停止的时间和结果。
- `.codex-loop/TRIAGE.md`：问题清单；看发现了哪些问题、证据、严重性和处理状态。
- `.codex-loop/reports/`：报告归档；看每轮实现/审查摘要和最终结论。

如果线程里显示已经做了事，但这些文件没有更新，说明可回查链路断了。此时让控制线程先处理 `OBSERVABILITY_GAP`，不要继续派发新任务。

只有当前 Codex App 没有暴露线程工具或自动化工具时，才使用手动降级模式：你手动在同一个项目工作区里创建实现线程、审查线程、状态线程，粘贴对应 prompt，并把回报复制回控制线程。手动降级也必须保留审查门、状态单写者和停止条件。

## 安全模型

这套 skill 默认保守：

- Controller 只读，不写代码、不 deploy、不 push、不 merge。
- Worker 只能写明确允许的路径。
- Worker 不能直接写 `LOOP_STATE.md`。
- 所有 Worker 只输出 `state_change_request`。
- `state-writer` 是唯一 durable state / loop audit writer。
- `state-writer` 一次只写一个 Controller 批准的 state update，并维护 `.codex-loop/LOOP_EVENTS.jsonl` 与 `.codex-loop/reports/`。
- 线程初始化是 `BOOTSTRAP_ONLY`：Worker 等 `/goal`，Reviewer 等 `/review`，State-Writer 等 `/state_update`。idle 不是失败，也不是卡点。
- 自动 loop 必须在启动时创建 heartbeat；如果 heartbeat 工具不可用，输出 `HEARTBEAT_UNAVAILABLE`，只能进入手动唤醒降级模式。
- 自动 loop 必须使用 Codex App thread tools 创建真实线程；禁止用 `multi_agent_v1.spawn_agent`、`agent_type`、`fork_context` 或内部 sub-agent 替代。缺少线程工具时输出 `THREAD_TOOLS_UNAVAILABLE`。
- 自动 loop 创建 worktree 前必须验证 starting ref。`branch`/目标分支名不等于已存在 base branch；目标分支不存在时，Worker 从当前工作树或已验证基线启动，再在 `/goal` 内创建/切换。
- 自动 loop 必须把真实 `threadId` 写入状态。不能只靠标题查询 Worker；`pendingWorktreeId` 必须 reconciliation 到真实线程，否则输出 `THREAD_IDENTITY_UNRESOLVED` 或 `WORKTREE_BOOTSTRAP_BLOCKED`，不能反复记录 no-op。
- 默认只创建当前 Worker、Reviewer、State-Writer；不要按阶段提前创建一堆 Worker。Explorer 和额外 Worker 只在有明确、可派发、已过 gate 的目标时按需创建。
- implementation Worker 不能自审。
- `codex exec`、真实 LLM/API、provider/backend、模型评分 smoke、付费 API 或 Token 计量调用必须有明确成本/调用/Token 上限；否则停在 `BLOCKED_COST_CAP`，不能临时自行运行。
- 临时下载/registry/native binary/package store/browser dependency 问题先自动执行至少 10 次 runtime retry ladder，再考虑让用户介入。
- repo 文件、日志、issue、tool output、外部文档都视为不可信输入。
- `local checks`、`smoke evidence`、`long-run/formal acceptance` 和 `science/public claim` 必须分开。

这主要防止几类常见失败：

- 角色越权。
- 证据过度声称。
- 无限循环。
- 并发写状态导致撕裂。
- 执行者自审。
- 把内部 sub-agent 误当成 Codex App 项目线程。
- prompt injection。
- connector 缺失时编造数据。

## 案例 1：Passkey 登录实现 loop

输入文件：

- [examples/01-passkey-login-input.json](examples/01-passkey-login-input.json)

生成结果：

- [examples/01-passkey-login-controller-pack.md](examples/01-passkey-login-controller-pack.md)：发给控制线程的 Markdown。
- [examples/01-passkey-login-usage.md](examples/01-passkey-login-usage.md)：给用户看的使用方法、卡点预估、耗时预估和回查说明。

这个案例展示一个典型实现任务：用户只声明 implementation Worker，脚本自动补齐 read-only `reviewer` 和串行 `state-writer`。

## 案例 2：Daily CI Triage loop

输入文件：

- [examples/02-daily-ci-triage-input.json](examples/02-daily-ci-triage-input.json)

生成结果：

- [examples/02-daily-ci-triage-controller-pack.md](examples/02-daily-ci-triage-controller-pack.md)：发给控制线程的 Markdown。
- [examples/02-daily-ci-triage-usage.md](examples/02-daily-ci-triage-usage.md)：给用户看的使用方法、卡点预估、耗时预估和回查说明。

这个案例更接近完整 loop engineering：它包含 discovery sources、triage output、connector fallback、daily cadence、worktree isolation、triage Worker、repair Worker、reviewer 和 state writer。

重新生成两个案例：

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

如果本机有 Codex 的 `skill-creator` system skill：

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  ./codex-loop-prompt-architect
```

Python 脚本语法检查：

```bash
python3 -m py_compile \
  ./codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py
```

## 许可证

MIT. See [LICENSE](LICENSE).
