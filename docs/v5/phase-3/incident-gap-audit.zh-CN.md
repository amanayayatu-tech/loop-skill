# Phase 3 事故行为缺口审计

状态：`DEVELOPMENT / GAP_AUDIT_COMPLETE / SAME_THREAD_WAKE_SPIKE_PASS`

证据日期：`2026-08-02`（Asia/Shanghai）

审计基线为 [事故行为语料](../phase-0/incident-behavior-corpus.zh-CN.md)、[GJ-1 DEVELOPMENT 真实运行](../phase-2/gj1-development-run.zh-CN.md)、[Host capability spike](../phase-2/host-capability-spike.zh-CN.md) 和 [GJ-3 规格](../phase-0/golden-journey-gj3-durable-wait.zh-CN.md)。本审计不新增代码、状态、命令、schema、Store 或恢复机制；GJ-1 成功只支持其已观察固定路径，不自动闭合其他事故。

| ID | 当前分类 | 尚未闭合的最窄缺口 |
| --- | --- | --- |
| `IB-01` | `GJ1 已有直接证据` | 已证明固定 private prepare root 为 0700、handoff 为 0600 且不污染 workspace；尚未由此建设或主张通用 Store。 |
| `IB-02` | `仍缺真实复现` | Phase 1 证明了错误 PATH 顺序会选错 Codex，GJ-1 证明 exact PATH 可运行；尚未以“自定义 env 为空”作为真实触发并断言 Worker 调用为 0。 |
| `IB-03` | `GJ1 已有直接证据` | prepare 绑定 Codex/Node/Git，现有直接回归证明 START 前 executable 指纹漂移以 Worker 0、workspace 0 effect 拒绝；没有通用 executable registry 主张。 |
| `IB-04` | `GJ1 已有直接证据` | 固定 Owner note 被明确记录为 START 前既有事实，最终 diff 只认两项 transition 修改；其他 artifact 的“既有事实/本次变化”语义尚未验证。 |
| `IB-05` | `仍缺真实复现` | GJ-1 证明 verifier exit 后不重跑 Worker，但没有真实制造端口占用、listener 权限失败或 bind 竞态。 |
| `IB-06` | `GJ1 已有直接证据` | exact Host spike 与 GJ-1 都证明相同 workspace-write 模式能真实写目标 workspace；不支持自动 wake 或更宽权限主张。 |
| `IB-07` | `GJ1 已有直接证据` | 真实 GJ-1 注入 verifier exit `73`，只重建 verifier 一次且 Worker 调用仍为 `1`。 |
| `IB-08` | `仍缺真实复现` | v5 当前没有 PAUSED/Active 用户投影；尚无可执行冲突输入，不能把“不存在该表面”写成 PASS。 |
| `IB-09` | `GJ1 已有直接证据` | 真实运行前后 target status 只含两项允许修改与 Owner note，私有 handoff 位于 scratch 并在 START 后失效；其他 runtime 类型尚未验证。 |
| `IB-10` | `仍缺真实复现` | GJ-1 只有一个固定 Worker 与一个 verifier 故障，没有“一个最终意图内多个独立故障”的真实输入和同身份重规划证据。 |
| `IB-11` | `仍缺真实复现` | 尚未执行 GJ-2 的 Owner 跳过 Telegram/缩小范围路径，不能证明原身份继续、旧批准失效和最终主张降格。 |
| `IB-12` | `GJ1 已有直接证据` | Phase 1 在测试全绿时真实复现 501；GJ-1 再以真实 POST 201、安全拒绝和无回显闭合固定业务路径。 |
| `IB-13` | `GJ3 才能证明` | 2–5 分钟 DEVELOPMENT spike 已证明一次退出占用后的 same-thread Host wake 与 A 效果不重复；300 秒观察窗口的独立终止语义、跨自然日和 48 小时耐久仍未证明。 |
| `IB-14` | `仍缺真实复现` | 尚未从公开 v3/v4 tag 与真实安装器字节验证原样并存，以及 v5 安装/卸载不触碰旧身份；该发布矩阵仍待后续阶段。 |

## GJ-3 DEVELOPMENT 原生 same-thread wake spike

本 spike 没有修改 v5 runtime。business identity 为 `GJ3-DEVELOPMENT-KSGzSL`；disposable workspace 为 `/tmp/loopskill-v5-gj3-wake.KSGzSL/workspace`，private root 为 `/tmp/loopskill-v5-gj3-wake.KSGzSL/private`。

### 等待前事实

- workspace fixture HEAD：`d5317d4b0ebb4622ca30d3d39f43319f3442f638`；remote 为空。
- private root 为当前 uid 所有的 0700 目录；唯一事实文件 `wake-fact.txt` 为 0600，SHA-256 为 `097c0d8156cde9138d6132389ba78e871d5e8530f102433ed0235ee7c595ccb1`。
- `not_before`：`2026-08-02T11:03:46Z`。
- artifact A effect key：`GJ3-DEVELOPMENT-KSGzSL:artifact-A:v1`。
- artifact A SHA-256：`bbf5f3f7b5a8f4571dcd6a1b32d3e4cdf99ea162616dab0947cc796edbfd36ae`；写入次数为 `1`。
- 等待前 Git status 只有 `?? artifact-A.txt`；没有绑定该 workspace 的常驻进程。

Desktop 创建唯一临时 heartbeat `loopskill-v5-gj3-development-wake-ksgzsl`。`2026-08-02T11:01:59Z` 的 metadata readback 为 `kind=heartbeat`、`status=ACTIVE`，target thread 精确为当前执行 thread `019fc1d7-b776-7583-a5c8-cdea92f7e458`。随后原 turn 真实结束；没有创建新 task、worker thread、persistent goal、daemon、queue、v3 state 或第二 heartbeat。

### 原生重新进入与最终 readback

- Desktop heartbeat 在 `2026-08-02T11:04:17.578Z` 触发当前同一 thread 的新独立 turn；从调度 readback 到重新进入约 `2 分 18.6 秒`，且已经晚于 `not_before`。
- 续接首先 readback 同一 private fact、workspace、HEAD、empty remote、唯一 A status、effect key 与 A digest；全部精确匹配。artifact B 在写入前不存在，artifact A 没有重写。
- artifact B 只写入一次，引用同一 business identity 与 A exact digest；SHA-256 为 `9b58a2c82f2fb6653017a194b6ef7cbf5fbb6da1a8aecc3e71f60e3f948f9ae2`。
- 最终 A SHA-256 仍为 exact `bbf5f3f7b5a8f4571dcd6a1b32d3e4cdf99ea162616dab0947cc796edbfd36ae`；private fact SHA-256 也未变。
- 最终 HEAD 仍为 fixture commit，remote 与 staged diff 为空，Git status 恰为 `?? artifact-A.txt` 与 `?? artifact-B.txt`；等待前后没有 commit、publication 或项目外网络工具调用。
- `2026-08-02T11:05:20Z`，临时 heartbeat 经 Desktop 原生 delete 成功；automation id 和 metadata 文件均已 readback 为不存在，不会再次触发。

允许主张：当前 Codex Desktop Host 能在约两分钟的 DEVELOPMENT 等待中，退出原 turn 后以同一 thread 重新进入，readback 既有效果且不重复 A，再完成 B；技术性人工介入为 `0`。

不允许主张：这不是 48 小时运行，没有跨两个自然日，也没有证明操作系统睡眠/关机恢复、长期调度可靠性、300 秒历史终止事故的完整复现或多日级发布耐久。系统级网络活动没有被监控，因此外部网络边界只限于本 spike 没有发起项目外网络工具调用。
