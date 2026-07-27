# LoopSkill 4.0

[![v4 Release CI](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v4-release.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v4-release.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.en.md) · [中文快速开始](docs/v4/quickstart.zh-CN.md) · [English quickstart](docs/v4/quickstart.en.md)

<!-- parity: identity -->
> 发布状态：LoopSkill 4.0.0 候选正在接受发行门禁；尚未发布。公开发行身份最终以 `v4.0.0` tag 与 GitHub Release 的 readback 为准。

LoopSkill 把长任务变成一个有明确授权、证据和停止条件的可恢复 loop。普通用户只提供目标或目标文件；机器负责协议身份、版本、收据和 Host readback。产品仍保留必要的人类流程：

`INTAKE / 质检 → PREPARE / 准备 → CONFIRM / 确认边界 → START / 启动`

<!-- parity: break -->
## 破坏性版本说明

LoopSkill 4 是 **v4-only hard break**。它保留 v3 已验证的安全原则，但不打开、导入、修复或运行 v3 loop、Controller Pack、MCP 状态或 CLI 数据。没有自动迁移，也没有双写。

需要继续使用旧数据时，请独立安装或保留 [LoopSkill v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)。v4 安装器不会修改它。

<!-- parity: changes -->
## 4.0 的变化

- 一个 typed protocol manifest 定义 command、event、reference、receipt、capability 和 error 的 wire shape。
- deterministic Kernel 只依赖 typed protocol 与 ports；SQLite Store 是唯一 canonical writer。
- artifact、review、finalization 与 Codex Host Adapter 都在 Kernel 边界之外。
- operation ID、handle、Actor/Grant、revision、receipt、digest 和 Host identity 全由机器生成、解析或验证。
- Standard、Adaptive、Reviewer、Local Verifier、Decision Card 与 repair 是可选 policy；最小路径不加载 policy pack。
- 外部 effect 只允许一次自动 attempt；不能权威 readback 时诚实返回 `UNKNOWN` 或 `UNVERIFIABLE`。

<!-- parity: install -->
## 30 秒安装

要求：macOS 或 Linux、Git、Python 3.11–3.14。LoopSkill 4 runtime 只使用 Python 标准库。

```bash
git clone --branch v4.0.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

安装目标是独立的 `$CODEX_HOME/skills/loopskill4`。LoopSkill 4 自身不注册 MCP、不编辑 `config.toml`，也不要求为安装或使用 LoopSkill 4 重启 Codex App。Codex 或其他产品因无关原因仍可能要求重启。

<!-- parity: usage -->
## 最简单的使用方式

创建 `goal.json`：

```json
{
  "goal": "在 disposable 示例目录中完成并验证一个小改动",
  "task_horizon": "long",
  "write_scope": ["disposable-example"],
  "budget": "20 minutes; no network or publish",
  "external_actions": [],
  "acceptance_criteria": ["focused tests pass", "result is reviewed"],
  "stop_conditions": ["stop on unknown external state"],
  "authorization_boundaries": ["no commit, push, publish, deploy, or real-user data"]
}
```

然后执行一个主入口：

```bash
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" start goal.json
```

同一交互会先只读质检，再写本地准备产物并展示 Goal、写入范围、预算、外部动作、验收标准、停止条件和发布边界。只有精确的显式确认才能启动。非交互环境会停在 PREPARE；`DIRECT_TASK_RECOMMENDED` 不创建 loop。

确认后，公开入口通过本机 Codex `app-server` 创建至多一个 task 并执行权威 readback；它不注册 LoopSkill MCP，也不要求用户复制 Host identity。若 create 响应丢失且无法用机器 request marker 唯一回读，状态为 `UNKNOWN`，不会再次 create。

也可以显式执行四个阶段：

```bash
"$LOOPSKILL4" intake goal.json
"$LOOPSKILL4" prepare goal.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
```

<!-- parity: no-control -->
## 普通用户永远不手工提供什么

普通输入中的控制身份数量必须为 0。用户不复制 task/thread/turn/route/effect/artifact/review/finalization ID，不粘贴 SHA、receipt、Pack identity、Gateway schema、MCP/App enum、heartbeat、readback 或 retry 参数。即使模型文本含有这些值，它们也不获得 authority。

<!-- parity: status -->
## 状态、结果与限制

```bash
"$LOOPSKILL4" status --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data --diagnostics
```

默认状态只展示目标、进度、结果、限制和可行动的下一步。内部 identity 与 receipt 只在显式 diagnostics 中出现。`UNKNOWN` 表示外部动作可能已经发生但无法权威确认；`UNVERIFIABLE` 表示 Host 不能提供所需证明。两者都不是成功，也不会触发盲重发。

<!-- parity: policy -->
## 可选策略

Standard 提供固定、依赖有序的 Goal Queue。Adaptive 提供一个 active goal 和有界、版本化的 roadmap revision。Reviewer、Local Verifier、Decision Card、human steering 与 bounded repair 都是可选能力，只能提交受权 semantic command，不能写 Store、签 Host receipt 或成为 Supervisor。

<!-- parity: architecture -->
## 架构

```mermaid
flowchart LR
    E["Entry / composition root"] --> K["Deterministic Kernel"]
    K --> P["Typed protocol + ports"]
    E --> S["SQLite Store / one writer"]
    E --> A["Artifact, review, finalization libraries"]
    E --> H["Codex Host Adapter"]
    E -. optional .-> O["Standard / Adaptive policy"]
```

Store 不控制 Host；Artifact 与 Host 不写 canonical state。一个 state authority 可以维护正交 aggregate/event streams，不等于一个巨大 enum 或单一物理 event stream。详见 [架构图](docs/v4/architecture-map.md)、[ADR 0011](docs/adr/0011-loopskill-4-compatible-kernel-refactor.md) 与 [typed protocol](protocol/v4/README.md)。

<!-- parity: safety -->
## 安全与恢复

- 本地 operation acceptance、per-loop CAS、outbox 与 snapshot 在一个 SQLite transaction 中提交。
- 相同 operation ID 和相同请求重放不产生第二个 event、handle 或 effect；不同请求返回 idempotency conflict。
- provider 有 idempotency key 且存在 authoritative readback 时只称 effectively-once。
- 否则仅承诺 at-most-one automatic attempt；crash/lost response 可能留下 `UNKNOWN`。
- path traversal、symlink、casefold alias、special file 和 open/read race 都 fail closed。
- artifact correctness、workflow closure、assurance 和 external-effect finalization 是不同事实，不能互相替代。

<!-- parity: evidence -->
## 证据边界

仓库的 unit、fault-injection、conformance、isolated install 与 disposable Codex App canary 只证明绑定版本和场景中的合同行为。它们不证明 patch-success 优势、任意长期任务有效性、Host 无故障或跨系统 exactly-once。

<!-- parity: v3 -->
## v3 硬边界

v4 遇到 v3 root、state 或 Controller Pack 时零写入，并返回稳定的 `USER_UNSUPPORTED_LEGACY_VERSION`，指向 [v3.3.8 Release](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)。v4 不提供 importer、repair、legacy CLI alias、Pack runtime 或 v3 MCP State Gateway。

<!-- parity: uninstall -->
## 卸载与回退

安装器会输出 receipt 路径。使用同一 receipt 卸载：

```bash
python3 scripts/uninstall_v4.py --codex-home "${CODEX_HOME:-$HOME/.codex}" --receipt "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/<receipt>.json"
```

卸载只移除 receipt 绑定的 v4 安装，保持 `config.toml` 和独立 v3 安装字节不变。回退意味着卸载 v4 后继续使用单独的 v3.3.8；v4 不恢复、转换或迁移 v3 数据。

<!-- parity: limitations -->
## 已知限制

- 首发只支持 Codex Host Adapter；Kernel host-neutral 不等于 multi-host 支持。
- 不承诺 SQLite/Codex/Git/network 的跨系统 exactly-once。
- 不承诺实证 patch-success 提升或长期任务优越性。
- memory isolation 只报告 Host 实际可证明的能力，可能是 unavailable 或 unverifiable。
- Git/non-Git/new-Git capture 只在授权 root 和已验证 capability 内运行。

完整列表见 [已知限制](docs/v4/known-limitations.md)。

<!-- parity: contributor -->
## 开发与验证

```bash
python3 scripts/generate_v4_protocol.py --check
python3 scripts/validate_v4_preservation.py --root . --json
PYTHONDONTWRITEBYTECODE=1 python3 -B -W error -m unittest discover -s tests -p 'test_v4*.py' -v
coverage run -m unittest discover -s tests -p 'test_v4*.py'
coverage report
python3 scripts/check_v4_docs.py
```

CI 还执行 Linux/macOS 隔离安装、dependency/import graph、stale legacy runtime、privacy/secret/large artifact、SBOM/license 和 release identity 门禁。真实 Codex App canary 只在本地 exact-SHA release gate 运行，不在 GitHub-hosted runner 中伪造。

<!-- parity: release -->
## 发布、安全与历史版本

- [v4 发布流程](docs/RELEASING.md)
- [4.0 release notes](docs/v4/release-notes.md)
- [Security policy](SECURITY.md)
- [MIT License](LICENSE)
- [v3.3.8 historical release](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)
- [All GitHub Releases](https://github.com/amanayayatu-tech/loop-skill/releases)
