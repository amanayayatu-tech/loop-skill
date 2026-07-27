# LoopSkill 4 快速开始

状态：LoopSkill 4.0.0 稳定版；公开发行身份以 `v4.0.0` tag 与 GitHub Release 的最终 readback 为准。

## 安装

要求 macOS 或 Linux、Git、Python 3.11–3.14。runtime 只使用标准库。

```bash
git clone --branch v4.0.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

安装器只写 `$CODEX_HOME/skills/loopskill4` 及其 v4 receipt/staging 路径；不读写
`config.toml`，不注册 MCP，不覆盖独立 v3 安装，也不要求为了 LoopSkill 4 重启 Codex。

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
4. `START`：只接受仍有效的明确确认，机器化创建并 readback 至多一个 Host resource。

单入口不等于静默授权。非交互 session 在 PREPARE 后停止。边界变化、过期确认或模糊
“继续”都会 fail closed。

## 分阶段使用

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data
```

`confirm` 需要交互式精确确认。普通状态隐藏内部 identity；添加 `--diagnostics` 才显示
诊断证据。`UNKNOWN`/`UNVERIFIABLE` 是有意的可见限制，不是成功，也不触发盲重发。

## v3

v4 不打开、导入、修复或运行 v3 loop/Pack/state。遇到 v3 输入时零写入，并指向
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)。
没有自动迁移；若需旧数据，继续独立使用 v3.3.8。
