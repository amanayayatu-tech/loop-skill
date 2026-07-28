# LoopSkill 4 快速开始

状态：此源码树是 LoopSkill 4.0.0 稳定发行；公开可用性以 `v4.0.0` tag 与 GitHub Release readback 为准。

## 安装

要求 macOS 或 Linux、Git、Python 3.11–3.14。runtime 只使用标准库。4.0.0 只有在
Linux/macOS × Python 3.11、3.12、3.13、3.14 的八个 release-CI
runtime/distribution lane 全部通过后才能发布。

```bash
git clone --branch v4.0.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

安装器只写 `$CODEX_HOME/skills/loopskill4` 及其 v4 receipt/staging 路径；只读取
`config.toml` 以核验安装前后字节哈希，不修改它，不注册 MCP，不覆盖独立 v3 安装，
也不要求为了 LoopSkill 4 重启 Codex。

## 一个目标，一个入口，四个可见阶段

规范顺序是 `INTAKE → PREPARE → CONFIRM → START`。

复制 [v4 Standard 示例](../../examples/v4-standard-input.json)，或创建只含语义需求的
UTF-8 JSON。用户提供的 control identity 数量必须为 0。

```bash
"$LOOPSKILL4" start examples/v4-standard-input.json
```

入口依次执行：

1. `INTAKE`：严格只读；返回 `READY_FOR_LOOP`、`NEEDS_CLARIFICATION`、
   `BLOCKED` 或 `DIRECT_TASK_RECOMMENDED`。
2. `PREPARE`：生成 typed manifest、人类计划、中文说明和边界摘要；0 Host task、
   0 heartbeat、0 delivery。
3. `CONFIRM`：显示 Goal、写入范围、预算、外部动作、验收、停止和发布边界；确认绑定
   全部准备产物 digest。
4. `START`：只接受仍有效的明确确认，机器化启动至多一次前台 Codex invocation。

单入口不等于静默授权。非交互 session 在 PREPARE 后停止。边界变化、过期确认或模糊
“继续”都会 fail closed。

普通入口运行一次官方前台 `codex exec --json` 进程，最长 300 秒，并在成功、失败、
超时或中断时回收整个进程组。这是观察窗口，不是任务预算。只有完整终态 JSONL、
零退出码、最终结果和 artifact 验证全部成立才可闭合。证据丢失或无效会成为
`UNKNOWN`；LoopSkill 绝不 resend，也不执行 `codex exec resume`。
4.0.0 的普通入口只支持预期能在此窗口内结束的单个 Host task；更长的单次 Host 执行
不在本版公开支持范围内。

Codex Desktop 的 folder-open → `list_projects` → `projectId` → `create_thread`
路线已有 23/23 provisioning receipts，但 4.0.0 不接入该路线。普通入口采用
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
一旦进程已启动，4.0.0 没有跨进程 readback 或自动 resume；丢失证据保持
`UNKNOWN`。它绝不第二次 spawn 或 resend。普通状态隐藏内部 identity；添加
`--diagnostics` 才显示诊断证据。
`UNKNOWN`/`UNVERIFIABLE` 是有意的可见限制，不是成功，也不触发盲重发。

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
