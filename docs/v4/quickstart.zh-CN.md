# LoopSkill 4 快速开始

本文档对应 LoopSkill 4.2.0；当前可用的公开版本以 GitHub Releases 页面为准。

## 安装

要求 macOS 或 Linux、Git、Python 3.11–3.14。runtime 只使用标准库。4.2.0 的
发布验证覆盖直接 v3-cwd 零写入回归、完整确定性测试，以及 Linux/macOS ×
Python 3.11、3.12、3.13、3.14 的八个 release-CI runtime/distribution lane，
并要求三层有序的一次性 canary。GitHub Releases 列出 v4.2.0 后，以下命令
安装该精确 tag。

```bash
git clone --branch v4.2.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

安装器只写 `$CODEX_HOME/skills/loopskill4` 及其 v4 receipt/staging 路径；只读取
`config.toml` 以核验安装前后字节哈希，不修改它，不注册 MCP，不覆盖独立 v3 安装，
也不要求为了 LoopSkill 4 重启 Codex。

安装器和卸载器不会编辑 Codex 配置。首次在全新 workspace 真实调用官方 Codex Host
时，Host 自身可能在配置末尾登记该 workspace 的一条 `trust_level = "trusted"`
记录。LoopSkill 将其作为 Host-owned effect 单独测量：只允许当前机器生成的精确
canonical workspace 的单条 EOF 追加，保留真实非零 changed-byte 计数；其他配置变化
或任何 auth 变化都会 fail closed。

## 一句话或 PRD，一个入口，四个可见阶段

规范顺序是 `INTAKE → PREPARE → CONFIRM → START`。

在 Codex 对话中调用 `$loopskill4`，直接说一句话、粘贴 PRD，或明确提供一个 UTF-8
`.txt` / `.md` 文件。普通用户不需要写 JSON；每轮只问 1–3 个真正阻断问题，并在
本次 session 保留已经确认的答案。专家仍可使用 [v4 Standard 示例](../../examples/v4-standard-input.json)
或 canonical PlanDocument。用户提供的 control identity 数量必须为 0。

```bash
"$LOOPSKILL4" start ./requirements.md
```

入口依次执行：

1. `INTAKE`：严格只读；返回 `READY_FOR_LOOP`、`NEEDS_CLARIFICATION`、
   `BLOCKED` 或 `DIRECT_TASK_RECOMMENDED`。
2. `PREPARE`：生成 owner-only typed manifest、人类计划、PlanDocument、PlanIndex、
   容量报告和边界摘要；不创建 runtime Store，且 0 Host task、0 heartbeat、0 delivery。
3. `CONFIRM`：显示 Goal、写入范围、预算、外部动作、验收、停止和发布边界；确认绑定
   全部准备产物 digest。
4. `START`：只接受仍有效的明确确认，把 plan/index 写为 content-addressed blob，创建
   只含当前 Goal 的最小 Loop，并机器化启动当前 Goal 的一次前台 Codex invocation。

单入口不等于静默授权。非交互 session 在 PREPARE 后停止。边界变化、过期确认或模糊
“继续”都会 fail closed。

普通入口运行一次官方前台 `codex exec --json --output-schema --output-last-message` 进程，最长 30000 秒，并在成功、失败、
超时或中断时回收整个进程组。这是 Attempt 边界，不是整个 Loop 的预算。只有完整终态 JSONL、
零退出码、JSONL lifecycle 与机器控制 result 文件的唯一合法 outcome/summary 对象，
以及 artifact 验证全部成立才可闭合。证据丢失或无效会成为 `UNKNOWN`；LoopSkill
不从 `agent_message` 取 Result，也没有文本 marker 回退。Plan v2 把 session 与终态
控制证据持久保存在 workspace 外；控制器重启后可回读完成 Attempt，或对同一 session
执行一次有记录的 `codex exec resume`。bounded stderr 只作私有 digest 诊断；overflow fail closed。
每个 Goal 最多使用三次已声明 Attempt。一个已确认计划可包含 1–128 Goal；
`run`/`continue` 会推进到人工、时间、预算或重复失败等待边界，不承诺后台无限 daemon。

Codex Desktop 的 folder-open → `list_projects` → `projectId` → `create_thread`
路线已有历史 provisioning receipts，但 4.2.0 不接入该路线。普通入口采用
cwd-bound 前台 `codex exec` invocation，不承诺 Desktop-visible saved project/task。

## 分阶段使用

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" list --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" run --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" continue --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" budget-extend --root ./loopskill4-data --loop loop-example --max-host-invocations 40 --active-compute-seconds 14400 --reason "Continue the unchanged confirmed scope"
```

`confirm` 需要交互式精确确认。`list` 与普通 `status` 只读本地状态。`budget-extend`
只在 `WAITING_BUDGET` 接受，只能增加调用数与活跃计算时间，并仅持久化原因摘要，
不能改变已确认任务范围。存在多个 Loop
时，`run`/`continue` 必须明确选择一个。完成的持久 Attempt 可在控制器重启后回读；
已捕获的非 ephemeral session 最多恢复一次。旧进程仍存活时等待，不可安全重放的
动作进入人工门。
人工门和时间门只能通过与当前 Goal 及门内容摘要绑定的凭据解除；普通 `resume`
不能绕过它们。修复次数和重复失败指纹按 Goal 分别计算。
`UNKNOWN`/`UNVERIFIABLE` 是有意的可见限制，不是成功，也不触发盲重发。

## 容量与兼容

- 明确授权的 UTF-8 text/Markdown source 最大 256 KiB，canonical PlanDocument 最大 512 KiB，Goal 数为 1–128。
- CreateLoop 发布目标为 8 KiB / 64 members，硬上限保持 16 KiB / 128；Host prompt 目标为 24 KiB，硬上限 32 KiB。任何超限都在 Host 前阻断且不截断。
- 新 Loop 只写 `CONTENT_ADDRESSED_V1`。旧 `EAGER_V4_0` store 只支持 status、export 和原 reducer continuation；不迁移、不改写、不双写。

详见 [v4.2 compatibility matrix](compatibility-matrix-v4.2.md)。

对 receipt 完整的 v4.1.1，直接运行 `bash scripts/install.sh` 即可事务升级。
新 active pointer 提交前，旧 manager、target、receipt pointer、config 和 Loop data
均可恢复；未知漂移 fail closed。

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
bash scripts/install.sh
```

## v3

v4 不打开、导入、修复或运行 v3 loop/Pack/state。遇到 v3 输入时零写入，并指向
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)。
没有自动迁移；若需旧数据，继续独立使用 v3.3.8。
如果 cwd 仍带有 v3 的 `.codex-loop` 标记，4.2.0 会在 PREPARE、START 或
`status --refresh` 前停止，不创建准备产物、Store 或 Host 任务；请切换到新的 v4 工作目录。

## 卸载

卸载器机器解析安装时绑定的 active receipt；普通用户不填写 receipt：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
```

digest 绑定的管理入口位于被移除的安装目标之外，因此同一命令重放会安全返回
`ALREADY_UNINSTALLED`。receipt 缺失或漂移会 fail closed；`config.toml`、v3
安装和真实 loop 都不会被修改。
