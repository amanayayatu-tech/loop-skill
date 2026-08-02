# LoopSkill 5.0 Phase 0 证据索引

- 状态：`DEVELOPMENT / PHASE_0_PASS`
- 产品事实源：[`../loopskill-5.0-master-plan.zh-CN.md`](../loopskill-5.0-master-plan.zh-CN.md)
- 约束：本目录只记录阶段输入、演练和证据，不定义第二套产品、协议或运行时。

## 已核验基线

| 项目 | 已观察事实 | 允许主张 |
| --- | --- | --- |
| Git 基线 | `origin/main = 476f6ba298151c4a6930d4a8c9e60945e1c4d37d`，当前基线带 `v4.2.0` tag；建分支前 worktree 干净 | v5 从公开远端当前干净基线开始，不从 v4.3 脏工作树开始 |
| v5 分支 | `codex/loopskill-v5`；主计划导入提交 `c6ab5001da64a8918086a008c5aee4e81fb8fe24` | 后续 Phase 提交可与基线逐项审查 |
| 主计划身份 | 源文件与分支文件 SHA-256 均为 `69e88ed2b543033c12bf74bc753092b8e66316b8fc5759f765633792c3a13bb1`；Git blob 为 `b42bc5b7b69ebab90a3a6f51a6ea73ba2192f8dc` | 分支内产品事实源与 Owner 确认版本逐字节一致 |
| 本机执行环境 | macOS `26.5.2` arm64；Python `3.14.6`；Node `22.22.1`；npm `10.9.4`；Codex CLI `0.144.4`；Git `2.50.1` | 这些 executable 当前可解析；尚不能推出 START 时仍未漂移 |
| Codex Host 表面能力 | `codex exec` 提供 JSON、schema、workspace sandbox；`codex exec resume` 可按 session id 续接；Desktop 暴露 thread heartbeat/automation 能力 | 只证明接口当前存在，不证明小时级主动执行或多日级耐久续接可靠 |
| Nepha 真实项目 | 干净 commit `74051fbaecced9feb326fe53bff43738fd439856` 可读取，现有 `verify:core-shippable`、Web smoke 和持久化 readback 路径可用作 GJ-2 输入 | 可把该 commit 归档到中文路径做独立验证；不得改写源仓库 |
| v4.3 事故样本 | 只读 worktree 的 HEAD 仍为 `476f6ba298151c4a6930d4a8c9e60945e1c4d37d`，存在大量 tracked/untracked 改动；其 porcelain 清单 SHA-256 为 `f10716a9f79d042b22ddc21fa47d6dae3d203363b620ed1a4c3ce892f06c1264` | 只能提取行为和拟议回归，不能把其中测试或实现当作 v5 基线或已通过证据 |

## Phase 0 产物

1. [`incident-behavior-corpus.zh-CN.md`](incident-behavior-corpus.zh-CN.md)：十四类历史事故的输入、5.0 行为、失败分类和证据强度。
2. [`golden-journey-gj1-code-delivery.zh-CN.md`](golden-journey-gj1-code-delivery.zh-CN.md)：真实 Git 代码交付旅程。
3. [`golden-journey-gj2-nepha.zh-CN.md`](golden-journey-gj2-nepha.zh-CN.md)：Nepha 中文路径核心业务旅程。
4. [`golden-journey-gj3-durable-wait.zh-CN.md`](golden-journey-gj3-durable-wait.zh-CN.md)：跨等待窗口的耐久续接旅程。
5. [`launch-contract-rehearsals.zh-CN.md`](launch-contract-rehearsals.zh-CN.md)：三条旅程的无代码准入演练。

## Phase 0 退出 Gate

- [x] Owner 已在主计划和执行授权中确认价值排序、首发范围及非目标。
- [x] 事故被压缩为行为语料，没有复制 Plan v3、状态、命令、schema 或恢复结构。
- [x] GJ-1、GJ-2、GJ-3 均具有固定输入、真实路径、外部效果边界和可判定验收事实。
- [x] 无代码 Launch Contract 演练一次性暴露当前全部已知阻断；没有把技术阻断留到 START 后。
- [x] 当前没有新增运行时、依赖、服务、状态、命令、schema、wrapper、validator、gate 或恢复机制。

## 带入 Phase 1/2 的待验证问题

1. Codex Host 的实际主动执行上限和 session 续接是否能覆盖合同声明的窗口。
2. Desktop heartbeat 能否在同一业务身份下耐久唤醒，且不会重复已确认效果。
3. GJ-1 的最小实现能否只依赖 Host、一个人类可读合同和一份最小进度事实。
4. Nepha 的端口、scratch、进程重启与持久化 readback 能否在一次 START 内闭合。
5. v5 首发是否完全不需要复用任何 v4 低层库；在真实纵切证明前默认答案为“不复用”。

这些是验证题，不是新增控制平面的依据。Phase 1 仍为无代码任务准备验证；Phase 1 Gate 通过前不实现完整运行时。

## 直接验证

- 主计划源/分支字节 `cmp` 相同，SHA-256 与 Git blob 已记录。
- 行为语料包含恰好 `14` 个唯一事故 ID。
- Phase 0 staged diff 仅含本目录六份 Markdown，`git diff --cached --check` 通过。
- 文档不存在本机用户名、绝对私有路径或凭据文件名；相对事实源链接可解析。
