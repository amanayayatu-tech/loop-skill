# Codex Loop Prompt Architect

`codex-loop-prompt-architect` 是一个只面向 Codex macOS App 的 skill，用来把不成熟、上下文不完整、容易失控的提示词，改造成可以投递到 Controller / Worker / Reviewer / State-Writer 多线程体系里的 Codex Loop 提示词。

它不是“替你写代码”的 skill，而是“替你设计 loop prompt 系统”的 skill。

## 它解决什么问题

普通提示词通常只有一句目标，例如：

```text
帮我修一下登录流程，顺便跑测试，没问题就继续推进。
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

这个 skill 会把粗糙提示词改成一套可执行的 loop 体系：

- `Controller Prompt`
- `Worker Prompt`
- 自动补齐的 `Reviewer/Judge Prompt`
- 自动补齐的 `State-Writer Prompt`
- 第一个原子 `/goal`
- `Automation Template`
- `Discovery/Triage`
- `Connector/Worktree Runtime Mapping`
- 明确的发送顺序、停止条件、人工审批门和证据边界

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
│   ├── 01-passkey-login-output.md
│   ├── 02-daily-ci-triage-input.json
│   └── 02-daily-ci-triage-output.md
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
- 需要哪些源文件/附件：PRD、截图、PDF、设计稿、数据文件等。
- 用户后续应该看哪些状态文件、事件日志和报告目录来回查 loop 是否按预期运行。

如果用户坚持要草稿，skill 会标记为 `NON_DISPATCHABLE_DRAFT`，不会把它说成 ready-to-send。

正式输出 loop 之后，skill 还会给两类预期：

- `运行中卡点预估`：只预测 loop 已经可以启动以后，仍然可能因为审批、真实外部服务、人工验收、审查修复、connector/runtime 或审计日志断档而停下的阶段。它不会把 repo/root/PRD/工作区缺失这类启动前问题包装成运行中风险。
- `预计耗时`：给出 min / typical / max 的本地 Codex loop wall-clock 估算，并明确不计入等待用户提供 API key、批准 deploy/merge、真人验收、离线业务判断或 registry/network 恢复的时间。

对 Web/Node/前端项目，`运行中卡点预估` 会默认提醒首轮依赖安装和本地验证环境风险，例如 Next.js/SWC、Playwright、Sharp、canvas、Electron、native binary、大包下载、`pnpm`/`npm` store 或 lockfile 问题。遇到这类情况时，loop 应该输出 `RUNTIME_DEPENDENCY_BLOCKED` 或 `VALIDATION_BLOCKED`，不能把“源码已生成/静态审查通过”说成完整 PASS。

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
  --workers "implementation:write auth code" \
  --permissions "implementation:workspace_write" \
  --allowed "src/auth/**,tests/auth/**" \
  --forbidden "billing,database migrations,secrets,CI deploy config" \
  --validation "npm test -- auth;npm run lint;npm run typecheck" \
  --evidence "local checks" \
  --claim "candidate implementation only" \
  --state ".codex-loop/LOOP_STATE.md" \
  --source-artifacts "docs/auth-spec.md and attached screenshots" \
  --runtime-readiness "READY_BUT_LIKELY_REVIEW_REPAIRS" \
  --time-min "45-90 分钟" \
  --time-typical "2-4 小时" \
  --time-max "4-8 小时" \
  --time-factors "auth edge cases,browser/passkey support,native dependency install,test fixture setup,Reviewer repair rounds" \
  --discovery "CI failures, auth issues, recent auth commits" \
  --triage-output ".codex-loop/TRIAGE.md" \
  --connectors "GitHub connector if exposed; otherwise manual PR links" \
  --worktree-policy "one Codex worktree per writing Worker"
```

生成前检查缺失字段：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --check-only \
  --objective "Fix README typo"
```

如果缺少必需字段，脚本会以非零状态退出，并列出缺少的字段。

## 输出内容长什么样

Compact Mode 默认输出七块：

1. `运行中卡点预估`
2. `预计耗时`
3. `关键风险`
4. `Controller Prompt`
5. `Worker Prompt`
6. `First Goal`
7. `怎么启动` / `怎么发`

如果任务是 recurring loop、多线程、需要 connector、需要 worktree 或可能进入自动化，Controller Prompt 还会包含：

- `Runtime Mapping`
- `Runtime Blocker Forecast`
- `Time Estimate`
- `Automation Template`
- `Discovery/Triage`
- durable state schema
- connector fallback
- worktree isolation policy
- review gate
- human approval gate
- stop rules

生成出来的 Worker 通常包括：

- `implementation`：只允许在 scoped write set 内写代码。
- `reviewer`：当 review required 时自动补齐，且是 read-only。
- `state-writer`：自动补齐，唯一负责串行写 durable state。

## 输出之后应该怎么用

默认是 Codex macOS App 自动项目模式：你只启动一个控制线程，但这个控制线程必须在目标项目/工作区里启动。

### 1. 先准备工作区

1. 在本地准备一个文件夹。新项目尽量用空白文件夹，例如 `~/Documents/my-new-app`。
2. 在 Codex App 左侧“项目”里打开或添加这个文件夹，让它成为一个 Codex Project/Workspace。
3. 把 PRD、截图、PDF、设计稿、数据文件等资料放进这个工作区，推荐放到 `docs/`。
4. 如果资料暂时不在工作区，第一条 Controller 消息里必须写明绝对路径，或直接把文件附上。

### 2. 再启动控制线程

1. 在这个项目/工作区下面新建聊天，命名为“控制线程”。
2. 默认把生成结果完整粘贴进去，从 `运行中卡点预估` 到 `怎么启动`。不要只粘贴短的 `Controller Prompt` 代码块，除非它已经内嵌了 Worker Prompt 和 First Goal。
3. 控制线程会先调用 `list_projects` 或等价工具，找到当前工作区的 `projectId`。
4. 控制线程创建实现/审查/状态线程时，必须使用 `create_thread` 的 project target，例如 `target.type="project"` + 同一个 `projectId`。这样新线程会出现在同一个左侧项目工作区下面。
5. 如果控制线程无法找到项目，它应该输出 `MISSING_PROJECT_WORKSPACE` 并停止。不要让它创建 projectless 普通对话线程。

### 3. 自动 loop 怎么跑

控制线程会自动做这些事：

1. 创建或继续实现线程、审查线程、状态线程。
2. 把对应的 `Worker Prompt` 和 `First Goal` 发给目标线程。
3. 读取 Worker 回报，批准或拒绝 `state_change_request`。
4. 把批准后的状态更新发给 `state-writer`。
5. 如果有 code/config/CI/deploy/PR diff，把报告发给审查线程。
6. 审查不过时继续发修复任务；达到 retry/wakeup 上限后停止。

你只需要在这些情况介入：

- 需要真实订阅链接、支付链接、社群链接或密钥。
- 需要批准 PR merge、deploy、release 或真实外部写入。
- 出现 `AWAITING_HUMAN_APPROVAL`、`MISSING_CONNECTOR`、`MISSING_PROMPT_PACK`、`MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`OBSERVABILITY_GAP` 或 `HARD_BLOCK`。
- 需要真人可用性测试证据，或你决定接受 waiver。

### 4. 怎么回查 loop 是否按预期在跑

先看 Codex App 左侧项目工作区：

- 控制线程、实现线程、审查线程、状态线程都应该在同一个项目下面。
- 如果实现/审查/状态线程跑到了普通对话列表，说明 Controller 没有正确使用 project target，需要停下修正。

再看线程职责：

- 控制线程：看每一步派发给谁、为什么派发、下一步等什么。
- 实现线程：看改了哪些文件、跑了哪些命令、验证结果是什么。
- 审查线程：看 `PASS`、`NEEDS_REPAIR` 或具体 review findings。
- 状态线程：看它是否只写状态/日志，不写业务代码。

再看工作区里的 loop 文件：

- `.codex-loop/LOOP_STATE.md`：当前阶段、active goal、open blockers、next action、human approval 状态。
- `.codex-loop/LOOP_EVENTS.jsonl`：每次派发、回报、审查、修复、停止都应该有一行 JSON 事件。
- `.codex-loop/TRIAGE.md`：如果有 discovery/triage，这里记录发现、证据、严重性和状态。
- `.codex-loop/reports/`：保存 Controller 批准归档的 Worker/Reviewer 报告摘要。

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
- implementation Worker 不能自审。
- repo 文件、日志、issue、tool output、外部文档都视为不可信输入。
- `local checks`、`smoke evidence`、`long-run/formal acceptance` 和 `science/public claim` 必须分开。

这主要防止几类常见失败：

- 角色越权。
- 证据过度声称。
- 无限循环。
- 并发写状态导致撕裂。
- 执行者自审。
- prompt injection。
- connector 缺失时编造数据。

## 案例 1：Passkey 登录实现 loop

输入文件：

- [examples/01-passkey-login-input.json](examples/01-passkey-login-input.json)

生成结果：

- [examples/01-passkey-login-output.md](examples/01-passkey-login-output.md)

这个案例展示一个典型实现任务：用户只声明 implementation Worker，脚本自动补齐 read-only `reviewer` 和串行 `state-writer`。

## 案例 2：Daily CI Triage loop

输入文件：

- [examples/02-daily-ci-triage-input.json](examples/02-daily-ci-triage-input.json)

生成结果：

- [examples/02-daily-ci-triage-output.md](examples/02-daily-ci-triage-output.md)

这个案例更接近完整 loop engineering：它包含 discovery sources、triage output、connector fallback、daily cadence、worktree isolation、triage Worker、repair Worker、reviewer 和 state writer。

重新生成两个案例：

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  > examples/01-passkey-login-output.md

python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/02-daily-ci-triage-input.json \
  > examples/02-daily-ci-triage-output.md
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
