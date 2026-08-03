# LoopSkill 5 快速开始

LoopSkill 5 是本仓库中独立的两文件 Codex Skill 产品。根 `VERSION=4.2.0` 与 `scripts/install.sh` 属于保留的 LoopSkill 4.2 runtime；不要用它们安装 v5。

## 安装

先在 GitHub Releases 确认公开、非 prerelease 的 `v5.0.0` Release 存在。然后在 Codex 中调用系统 Skill Installer：

```text
Use $skill-installer to install https://github.com/amanayayatu-tech/loop-skill/tree/v5.0.0/loopskill5
```

安装目标是 `${CODEX_HOME:-$HOME/.codex}/skills/loopskill5`，内容必须只有：

- `SKILL.md`
- `agents/openai.yaml`

目标已存在时，系统 installer 会拒绝覆盖。不要手工把新字节叠加到旧目录；先核对现有安装，再按下方可恢复步骤移出。

安装后在新的 Codex turn 中显式调用：

```text
Use $loopskill5。请先主动调查这个长程任务，给出最远安全的 12 项 Launch Contract；现在不要 START。
```

检查合同中的最终意图、承诺结果、授权范围、真实验收、恢复上限、业务 Gate、紧急停止和无人值守预期。只有接受该 exact 合同后，再发送一条独立的 `START`。

## 可恢复卸载

以下命令不删除文件，只把 exact v5 Skill 目录移到 `skills` 之外的 owner-only 备份。它不会触碰 `loopskill4`、根 `VERSION`、v4 receipts 或任何 v3/v4 数据。

```bash
set -eu
loopskill5_home="${CODEX_HOME:-$HOME/.codex}"
loopskill5_dir="$loopskill5_home/skills/loopskill5"
loopskill5_backup_root="$loopskill5_home/uninstalled-skills"

test -d "$loopskill5_dir"
test ! -L "$loopskill5_dir"
test -O "$loopskill5_dir"
test -f "$loopskill5_dir/SKILL.md"
test ! -L "$loopskill5_dir/SKILL.md"
test -O "$loopskill5_dir/SKILL.md"
test -d "$loopskill5_dir/agents"
test ! -L "$loopskill5_dir/agents"
test -O "$loopskill5_dir/agents"
test -f "$loopskill5_dir/agents/openai.yaml"
test ! -L "$loopskill5_dir/agents/openai.yaml"
test -O "$loopskill5_dir/agents/openai.yaml"
test "$(find "$loopskill5_dir" -type f | wc -l | tr -d ' ')" = 2
test "$(find "$loopskill5_dir" -type d | wc -l | tr -d ' ')" = 2
test -z "$(find "$loopskill5_dir" -type l -print)"

umask 077
mkdir -p "$loopskill5_backup_root"
test -d "$loopskill5_backup_root"
test ! -L "$loopskill5_backup_root"
test -O "$loopskill5_backup_root"
chmod 700 "$loopskill5_backup_root"
loopskill5_backup="$loopskill5_backup_root/loopskill5-$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$loopskill5_backup"
mv "$loopskill5_dir" "$loopskill5_backup"

test ! -e "$loopskill5_dir"
test -f "$loopskill5_backup/SKILL.md"
test -f "$loopskill5_backup/agents/openai.yaml"
printf 'LoopSkill 5 moved recoverably to %s\n' "$loopskill5_backup"
```

若目录含额外文件、symlink、身份不明或同时存在其他写者，停止并先审查；不要用递归删除掩盖漂移。

## 产品边界

- 普通用户不填写 JSON、内部 ID、digest、receipt 或恢复命令。
- START 后 PATH、端口、scratch、Verifier 和合同内本地权限修复不是用户 Gate。
- 新权限、秘密、付费、公开发布、部署、删除或其他扩大授权仍是真实业务 Gate。
- Codex Host 必需的模型/控制面流量与任务业务工具网络效果分别报告。
- v5 不读取、迁移、复活或双写 v3/v4 数据。
- v5.0.0 已验证的等待主张只包括同一 Codex task 的定时退出、至少两次 Host-native same-thread reentry 与安全续接；多日耐久、睡眠或操作系统关机恢复留待发布后验证，不作首发承诺。
