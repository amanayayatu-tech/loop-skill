# Phase 0 无代码 Launch Contract 演练

本文件演练“主动调查 → 建议 → 一次性补齐 → START 决策”。它不创建 Loop、不调用 Worker、不产生业务或发布效果。合同字段来自唯一主计划；下面的阻断必须在 Phase 1/2 被真实消除后才能 START。

## 演练 1：GJ-1 代码交付

| 合同项 | 演练结果 |
| --- | --- |
| 最终意图 | 修复真实仓库的 `/api/intake` 501，同时保护用户脏改动并完成真实 HTTP 验收。 |
| 本次承诺结果 | 在一次 START 内完成最窄代码/测试修改、直接测试、HTTP smoke、一次 verifier 故障恢复和最终报告。 |
| 为何是最远结果 | 用户明确禁止 commit/push/发布；因此工作区内可用修复与证据是当前最远安全结果，不把内部工作段设为 Gate。 |
| 推荐路线 | 从 `a3b57ec` archive 开始；写范围先限直接源码和测试；保留脏文件摘要；独立 verifier 在 Worker 后运行。 |
| 已验证条件 | exact 历史 commit 与 501 字节存在；Node/npm/Codex executable 当前可解析。目标 sandbox 下真实 Host 写入、进程恢复和 START 前后指纹复核尚未验证。 |
| 授权与外部效果 | 仅一次性 archive、私有 scratch 和本机 loopback 验收；无 commit、push、外部网络、发布、付费、安装或源仓库修改。 |
| 验收 | 合法 POST 非 501、安全拒绝仍成立、私密文本不回显、直接测试 PASS、脏字节不变、diff 不越界。 |
| 自动恢复 | verifier 首次异常退出且无外部效果时重建并复验；不得再次调用 Worker。 |
| 业务 Gate | 本旅程没有运行中业务 Gate；扩大需求或允许提交/发布才需要新决定。 |
| 紧急停止 | 工作区身份漂移、越界写入、外部效果不确定、证据损坏。 |
| 无人值守 | Phase 2 目标为小时内；实际窗口须在 START 前用 Host spike 证明。 |
| START 决策 | `REJECT_NOW / READY_AFTER_PHASE_2_PREFLIGHT`：v5 walking skeleton 尚不存在，Host 写入与恢复能力尚未在相同包络验证。 |

一次性补齐清单只有两项：实现可运行的最小纵切；用相同 sandbox 做 Host/故障探针。没有需要 Owner 再回答的业务问题。

## 演练 2：GJ-2 Nepha

| 合同项 | 演练结果 |
| --- | --- |
| 最终意图 | 在中文路径把真实输入推进到四个可 readback 文本导出，并停在公开发布 Owner Gate。 |
| 本次承诺结果 | intake → 主题 → Claim/Brief → 测试型确认 → Draft → 四包 → 质量 → 测试型批准 → 导出 → 重启 readback。 |
| 为何是最远结果 | 用户未授权平台发布；四包导出后是否公开是不可由系统替代的最终业务判断。 |
| 推荐路线 | 固定 `74051f…` archive；使用项目已有 core verification 与真实 Web API 旅程；数据全部进入私有 scratch。 |
| 已验证条件 | 源 commit 当前干净；Node/npm 和现有 verify/smoke 入口存在。中文 archive、全四包旅程、端口竞态恢复、Host 包络和重启 readback 需在候选上重验。 |
| 授权与外部效果 | 只写副本和私有数据根；不写源仓库、Codex auth/config、v3/v4 数据、Telegram、Git remote 或平台。 |
| 验收 | 四包精确版本、四份 manifest、幂等导出、重启 readback、无未批准/秘密内容、源和 Host 身份不变。 |
| 自动恢复 | 临时端口冲突时换端口；server/verifier 退出时在同一数据根重建；已知导出 identity 不重复。 |
| 业务 Gate | 四包交付后的公开发布决定；不得把 PATH、端口、Store、scratch、nested Codex 或 verifier 变成人类 Gate。 |
| 紧急停止 | 导出是否已发生无法确认、源/候选身份漂移、私密材料泄露、持久事实损坏。 |
| 无人值守 | 目标 2–4 小时；真实 Host 窗口未证明前不能写入正式合同。 |
| START 决策 | `REJECT_NOW / READY_AFTER_PHASE_2_3`：缺少 v5 runtime、相同包络 Host probe 和一次完整四包 DEVELOPMENT 旅程。 |

Owner 的公开发布决定已经被集中为唯一运行中业务 Gate；其余当前缺口全部是系统需先消除的技术条件。

## 演练 3：GJ-3 耐久等待

| 合同项 | 演练结果 |
| --- | --- |
| 最终意图 | 第一份交付物完成后跨自然等待续接，生成第二份并最终 readback，前段效果不重复。 |
| 本次承诺结果 | 一次 START、两个主动工作段、一次 durable wait/Host 重入、一次进程故障恢复和最终结果。 |
| 为何是最远结果 | 本地交付物无需业务 Gate；系统应完成到底。操作系统关机后的恢复明确不在首发承诺。 |
| 推荐路线 | 优先验证 Codex 原生 persisted session/resume 与 Desktop thread heartbeat；只持久化续接所需最小事实，不建 daemon/队列。 |
| 已验证条件 | CLI 当前暴露按 session id resume，Desktop 当前暴露 heartbeat/automation 接口；尚无相同身份、48 小时、零重复效果的实证。 |
| 授权与外部效果 | 只写一次性项目和私有进度事实；不联网、不发布、不提交、不付费扩大。 |
| 验收 | 同一身份、第一效果次数 1、等待无常驻进程、到期续接、第二结果引用第一 digest、最终 readback 一致。 |
| 自动恢复 | 已知无外部效果的进程退出由 Host 重入；效果已知存在则 readback 后跳过；效果未知则紧急停止。 |
| 业务 Gate | 无。若唤醒需新权限、费用或改变目标，必须在 START 前补齐。 |
| 紧急停止 | 调度消失且无法确认、工作区/身份漂移、第一效果 UNKNOWN、证据损坏。 |
| 无人值守 | development 2–5 分钟；release 不少于 48 小时。短 spike 的合同不得声称多日能力。 |
| START 决策 | `BLOCKED_BEFORE_START`：当前只有接口存在证据，没有耐久、身份和 exactly-once-like readback 实证。 |

该阻断是 Phase 2 前半段必须消除的最高不确定性。若原生 Host 能力不足，应缩小公开承诺或拒绝发布，而不是新增大型控制平面。

## 演练结论

三次演练均能在 START 前一次性区分业务决定与技术条件：GJ-1 没有运行中 Gate；GJ-2 只有最终公开发布 Gate；GJ-3 没有业务 Gate但当前因 Host 耐久能力证据不足而拒绝 START。没有任何 PATH、权限、Store、端口、Verifier、Host 或时长问题被留到 START 后。
