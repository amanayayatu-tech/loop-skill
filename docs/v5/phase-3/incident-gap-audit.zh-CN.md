# Phase 3 事故行为缺口审计

状态：`DEVELOPMENT / READ_ONLY_GAP_AUDIT`

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
| `IB-13` | `GJ3 才能证明` | 当前没有退出占用后的 same-thread Host wake；300 秒观察窗口不拥有终止权、跨等待不重复效果和 48 小时耐久均未证明。 |
| `IB-14` | `仍缺真实复现` | 尚未从公开 v3/v4 tag 与真实安装器字节验证原样并存，以及 v5 安装/卸载不触碰旧身份；该发布矩阵仍待后续阶段。 |

## 下一项允许动作

不改 v5 runtime，先执行 2–5 分钟 GJ-3 DEVELOPMENT 原生 Host spike：一个 disposable Git workspace、一个 0700 私有根、一个最小人类可读事实文件、artifact A 写入恰为一次；只在 Desktop heartbeat 能创建、readback 为当前 thread、并可安全暂停或删除时 START。否则继续保持 `BLOCKED_BEFORE_START`。
