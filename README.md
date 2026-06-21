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

推荐日常使用这个短版：

```text
Use $codex-loop-prompt-architect，短版：把下面提示词变成可投递的 Codex macOS App Loop；如果信息不够，先反问，不要输出完整版。

[粘贴你的粗糙提示词]
```

如果关键信息不够，skill 应该先反问，而不是直接生成完整版。常见必须补足的信息包括：

- 目标和验收标准。
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

如果用户坚持要草稿，skill 会标记为 `NON_DISPATCHABLE_DRAFT`，不会把它说成 ready-to-send。

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
  --branch feature/passkey-login \
  --workers "implementation:write auth code" \
  --permissions "implementation:workspace_write" \
  --allowed "src/auth/**,tests/auth/**" \
  --forbidden "billing,database migrations,secrets,CI deploy config" \
  --validation "npm test -- auth;npm run lint;npm run typecheck" \
  --evidence "local checks" \
  --claim "candidate implementation only" \
  --state ".codex-loop/LOOP_STATE.md" \
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

Compact Mode 默认输出五块：

1. `关键风险`
2. `Controller Prompt`
3. `Worker Prompt`
4. `First Goal`
5. `怎么发`

如果任务是 recurring loop、多线程、需要 connector、需要 worktree 或可能进入自动化，Controller Prompt 还会包含：

- `Runtime Mapping`
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

生成 prompt 后，不是整段都发给一个线程。要按输出里的 `SEND TO` 和 `怎么发` 分开发：

1. 在 Codex App 创建或找到 Controller thread。
2. 创建或找到每个 Worker thread。
3. 如果有写代码 Worker，尽量给每个 writing Worker 配独立 Codex thread/worktree。
4. 把 `Controller Prompt` 只发给 Controller thread。
5. 把每个 `Worker Prompt` 只发给对应 Worker thread。
6. 把所有 `<THREAD_IDENTIFIER_...>` 替换成真实 thread ID、URL 或稳定标题。
7. 把 `First Goal` 发给指定 Worker thread。
8. 等 Worker 输出结构化 report。
9. Controller 审查 Worker 的 `state_change_request`。
10. Controller 一次只批准一个 state update。
11. 把批准后的 state update 发给 `state-writer`。
12. `state-writer` 串行更新 durable state。
13. Controller 对齐 Worker report、State-Writer result 和 durable state。
14. 如果有 code/config/CI/deploy/PR diff，必须跑独立 Review/Audit。
15. 如果出现 `AWAITING_HUMAN_APPROVAL`、`MISSING_CONNECTOR` 或 `HARD_BLOCK`，停止，不要继续自动化。
16. 只有手动第一轮验证了 thread addressing、worktree isolation、connector access、triage output 和 report schema 后，才配置 Codex Automation。

## 安全模型

这套 skill 默认保守：

- Controller 只读，不写代码、不 deploy、不 push、不 merge。
- Worker 只能写明确允许的路径。
- Worker 不能直接写 `LOOP_STATE.md`。
- 所有 Worker 只输出 `state_change_request`。
- `state-writer` 是唯一 durable state writer。
- `state-writer` 一次只写一个 Controller 批准的 state update。
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
