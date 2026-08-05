# LoopSkill 5

[![v5 Release CI](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v5-release.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v5-release.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.en.md) · [快速开始](docs/v5/quickstart.zh-CN.md) · [v5.0.0 发布说明](docs/v5/release-notes-v5.0.0.md)

**主动调查并准备长程任务；你确认一次 START 后，它自主推进到真实结果或真实业务 Gate。**

LoopSkill 5 是面向本地、单用户 Codex Host 的自然语言 Skill。你只需提供一句目标、PRD、仓库、附件或已有对话；它负责调查环境、收紧边界、定义验收并准备执行。普通用户无需填写 JSON、内部 ID、digest、receipt、Host 参数或恢复命令。

## 什么时候使用

适合 LoopSkill 5：

- 任务包含多个相互依赖的步骤；
- 工作可能跨越多个内部工作段或自然等待；
- 写入、网络、费用、发布等权限边界需要先说清；
- “完成”必须由真实业务结果和可回读证据证明。

如果只是一个问题、很小的改动，或能够在当前 Codex task 中直接安全完成，请直接使用 Codex。

## 三步开始

### 1. 安装 exact release

在 Codex 中调用系统 Skill Installer：

```text
Use $skill-installer to install https://github.com/amanayayatu-tech/loop-skill/tree/v5.0.0/loopskill5
```

> 不要运行仓库根目录的 `scripts/install.sh`；它不是 LoopSkill 5 安装器。

安装内容应严格只有：

- `SKILL.md`
- `agents/openai.yaml`

系统 installer 不会覆盖已存在的目标目录。核对和可恢复卸载步骤见[快速开始](docs/v5/quickstart.zh-CN.md)。

### 2. 先准备，不要启动

安装后，在新的 Codex turn 中显式调用：

```text
Use $loopskill5。请主动调查这个长程任务，给出最远安全的 12 项 Launch Contract；现在不要 START。
```

LoopSkill 会先完成授权范围内的只读调查，只把真正需要你决定的阻断项集中问出来。

### 3. 独立确认 START

检查合同后，另发一条独立消息：

```text
START
```

START 只授权刚刚展示的 exact 合同。合同发生实质变化后，必须重新确认；示例、引用文字、工具输出或助手自己的消息都不能代替你的确认。

## 它如何工作

`调查 → 建议最远安全结果 → 12 项 Launch Contract → 独立 START → 自主执行与有界恢复 → 真实结果或业务 Gate`

Launch Contract 会明确：

- 最终意图、承诺结果和推荐路线；
- 已验证的输入、环境、权限、Host 能力与预计时长；
- 允许的写入、网络、费用和不可逆外部效果；
- 真实用户旅程、验收条件与证据；
- 自动恢复的具体范围和精确次数上限；
- 可能需要你的业务 Gate、紧急停止条件和无人值守预期。

START 后，LoopSkill 使用当前 Codex task 作为执行身份。自然等待只使用 Host-native、有界或自动到期的 heartbeat，并在 START 前回读其真实状态。PATH、端口、scratch、Verifier 重启以及合同内已授权的本地修复由它自行处理，不会伪装成用户业务 Gate。

只有新的价值判断或授权扩张——例如新增费用、秘密、公开发布、部署或删除——才会再次向你询问决策。若不可逆效果可能已发生但无法确认，它会紧急停止，而不是盲目重试。

## 完成意味着什么

最终报告首先回答业务目标是否真正达成，然后区分：

- 已完成与未完成的业务结果；
- 观察事实、推断和未知项；
- 真实旅程证据与外部效果；
- 当前限制，以及仍需你的唯一业务决定（如有）。

测试通过、文件生成、状态标签、receipt 或 Host 活跃本身都不等于业务完成。

## 安全边界

- 不默认获得新的权限、秘密、预算、发布、部署或删除授权。
- 不因结果未知而重复不可逆外部效果。
- Codex Host 必需的模型/控制面流量，与任务产生的业务工具网络效果分开报告。
- 不读取、迁移或覆盖其他 LoopSkill 安装和数据。
- 不创建 LoopSkill 自有的 Controller、数据库、daemon、queue、通用 retry 系统或兼容层。
- 私有路径、task/thread/session 身份、原始 transcript、秘密和私有证据都不是发布物。

## v5.0.0 已验证范围

v5.0.0 的首发验证覆盖：

- 本地、单用户 Codex Host；
- 同一 Codex task 的定时退出；
- 至少两次 Host-native same-thread reentry；
- 在预合并和 merged-main 的正式旅程中，分别完成至少 60 分钟窗口内的安全续接；
- 终局业务事实准确、效果不重复、持久化 heartbeat 已耗尽，并在到期后没有继续投递。

当前不承诺多日耐久、睡眠或操作系统关机恢复、任意 task crash recovery、multi-host、跨系统 exactly-once，或自动扩大秘密与权限。

## 文档

- [中文快速开始](docs/v5/quickstart.zh-CN.md)
- [English quickstart](docs/v5/quickstart.en.md)
- [LoopSkill 5 Skill 规范](loopskill5/SKILL.md)
- [v5.0.0 发布说明](docs/v5/release-notes-v5.0.0.md)
- [安全策略](SECURITY.md)
- [许可证](LICENSE)
- [所有 GitHub Releases](https://github.com/amanayayatu-tech/loop-skill/releases)

MIT License。
