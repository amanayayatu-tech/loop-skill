# LoopSkill 4 快速开始

本文档对应 LoopSkill 4.1.0 发布候选，正在等待作者发布授权；当前可用的公开版本仍以 GitHub Releases 页面为准。

## 安装

要求 macOS 或 Linux、Git、Python 3.11–3.14。runtime 只使用标准库。4.1.0 只有在
Linux/macOS × Python 3.11、3.12、3.13、3.14 的八个 release-CI
runtime/distribution lane、两条真实 Host canary 和独立审查全部通过，并获得作者另行发布授权后才能发布。以下安装命令只适用于届时已发布的 tag。

```bash
git clone --branch v4.1.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
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

普通入口运行一次官方前台 `codex exec --json --output-schema --output-last-message` 进程，最长 300 秒，并在成功、失败、
超时或中断时回收整个进程组。这是观察窗口，不是任务预算。只有完整终态 JSONL、
零退出码、JSONL lifecycle 与机器控制 result 文件的唯一合法 outcome/summary 对象，
以及 artifact 验证全部成立才可闭合。证据丢失或无效会成为 `UNKNOWN`；LoopSkill
不从 `agent_message` 取 Result、没有文本 marker 回退，绝不 resend，也不执行 `codex exec resume`。bounded stderr 只作私有 digest 诊断；overflow fail closed。
每个 Goal 的普通入口只支持预期能在此窗口内结束的单个 Host task；更长的单次 Host
执行不在本版公开支持范围内。一个已确认计划可包含 1–32 Goal，后续 Goal 通过原子
`AdvanceGoal` 按需激活；系统不承诺后台无限长跑。

Codex Desktop 的 folder-open → `list_projects` → `projectId` → `create_thread`
路线已有历史 provisioning receipts，但 4.1.0 不接入该路线。普通入口采用
cwd-bound 前台 `codex exec` invocation，不承诺 Desktop-visible saved project/task。

## 分阶段使用

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data
"$LOOPSKILL4" status --refresh --root ./loopskill4-data
```

`confirm` 需要交互式精确确认。普通 `status` 只读本地状态。若崩溃发生在本地 Attempt
提交后、执行权被取得前，`status --refresh` 可执行该 Attempt 的唯一首次 invocation。
一旦进程已启动，当前前台协议没有跨进程 readback 或自动 resume；丢失证据保持
`UNKNOWN`。它绝不第二次 spawn 或 resend。普通状态隐藏内部 identity；添加
`--diagnostics` 才显示诊断证据。
`UNKNOWN`/`UNVERIFIABLE` 是有意的可见限制，不是成功，也不触发盲重发。

## 容量与兼容

- 明确授权的 UTF-8 text/Markdown source 最大 256 KiB，canonical PlanDocument 最大 128 KiB，Goal 数为 1–32。
- CreateLoop 发布目标为 8 KiB / 64 members，硬上限保持 16 KiB / 128；Host prompt 目标为 24 KiB，硬上限 32 KiB。任何超限都在 Host 前阻断且不截断。
- 新 Loop 只写 `CONTENT_ADDRESSED_V1`。旧 `EAGER_V4_0` store 只支持 status、export 和原 reducer continuation；不迁移、不改写、不双写。

详见 [v4.1 compatibility matrix](compatibility-matrix-v4.1.md)。

从已安装的 v4.0.0 升级采用 receipt-bound 清洁替换，不做原地覆盖或 Store 迁移：先用
现有安装自己的管理卸载器移除 runtime，再安装 v4.1.0。真实 Loop data root 不属于
安装目录，必须保持不变。

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
bash scripts/install.sh
```

## v3

v4 不打开、导入、修复或运行 v3 loop/Pack/state。遇到 v3 输入时零写入，并指向
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)。
没有自动迁移；若需旧数据，继续独立使用 v3.3.8。

## 卸载

卸载器机器解析安装时绑定的 active receipt；普通用户不填写 receipt：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
```

digest 绑定的管理入口位于被移除的安装目标之外，因此同一命令重放会安全返回
`ALREADY_UNINSTALLED`。receipt 缺失或漂移会 fail closed；`config.toml`、v3
安装和真实 loop 都不会被修改。
