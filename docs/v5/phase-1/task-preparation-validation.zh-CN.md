# Phase 1 无代码任务准备验证

状态：`DEVELOPMENT / PHASE_1_PASS`

证据日期：`2026-08-02`（Asia/Shanghai）

本阶段只验证主动调查、建议、一次性补齐和 START 决策，没有实现 Loop、调用 Worker、修改源项目或产生外部业务效果。`PHASE_1_PASS` 只表示全部当前已知阻断都已在模拟 START 前暴露；不表示三条黄金旅程已经获准 START 或已经通过。

## 固定输入

- 产品事实来源：[LoopSkill 5.0 主计划](../loopskill-5.0-master-plan.zh-CN.md)
- 无代码合同基线：[Phase 0 Launch Contract 演练](../phase-0/launch-contract-rehearsals.zh-CN.md)
- 旅程规格：[GJ-1](../phase-0/golden-journey-gj1-code-delivery.zh-CN.md)、[GJ-2](../phase-0/golden-journey-gj2-nepha.zh-CN.md)、[GJ-3](../phase-0/golden-journey-gj3-durable-wait.zh-CN.md)
- 事故行为：[Phase 0 incident corpus](../phase-0/incident-behavior-corpus.zh-CN.md)

## 直接探针证据

### P1-E1：GJ-1 历史失败可复现

在中文路径的一次性 archive 中读取 exact commit `a3b57ecea7e7e2f6e000820b06e7c895efd4a84b`，其 Git tree 为 `09c6e0f54b879fe20a600bd62479e5caa05cd0df`。

- `node --test test/server.test.js`：`2/2 PASS`。
- 合法 loopback `POST /api/intake`：`501 not_implemented`。
- 缺少 Origin 的请求：`403`，安全拒绝仍成立。
- 私密输入没有出现在响应中。
- archive 和源仓库在探针前后均无改动。

事实边界：现有直接测试通过，但真实用户行为失败。该证据只证明 GJ-1 的当前失败和真实 HTTP 验收的必要性，不证明 v5 已具备修改、验证或恢复能力。

### P1-E2：GJ-2 现有验证的可用部分与边界

在中文路径的一次性 clean archive 中读取 exact commit `74051fbaecced9feb326fe53bff43738fd439856`，其 Git tree 为 `edb0729811c533b5a2539bbf39865097359dd789`。

- `npm run preflight`：`PASS`；该入口明确只是静态预检，没有调用真实 Codex Host。
- `npm run verify:core-shippable`：`PASS`；报告 `62` 个测试、`0` failure、`0` skip，其中包含持久化 Web workflow smoke、导出 hash readback、固定 12 例 benchmark、故障恢复场景、secret scan、clean-room 和 backup/restore。
- Web workflow receipt 报告 `persisted=true` 与 `exportHashesVerified=true`。
- archive 内容摘要在前后均为 `a1b8d461f4541cc384e2874c74935904dbd40c2760c598a476adbffa06f96169`；源仓库前后无改动。

事实边界：这些结果证明现有确定性核心验证可运行，不证明 Phase 0 固定真实输入已由 v5 一次 START 推进，不证明四个平台包的 exact fixture 批准与最终 Owner Gate 已按 GJ-2 完成，也不证明 nested Codex、端口竞态恢复或 2–4 小时 Host 包络。

### P1-E3：准入环境与 executable 身份

解析并记录的当前 executable 身份如下；公开合同只需展示版本与“身份已复核”，机器证据保留 exact fingerprint。

| executable | 版本 | SHA-256 |
| --- | --- | --- |
| Node | `v22.22.1` | `245e0321af97d3c21dd4e7104457334dfe3c3ba7982d0db75363e354565f8cbb` |
| npm | `10.9.4` | `8e5f6f3429f8cdbe693cdc29904e9d5a7b127a494bd15c804bd54c7403bfcbe7` |
| Codex CLI | `0.144.4` | `3302acbda5f53de1a71ebdb0c0f2aae0d47f9324aa9fb6b4e78a47014fd51c7d` |
| Git | `2.50.1 (Apple Git-155)` | `179301dcb41ea78accc3fa0048a7e6f6710d891945a751a34addd622020c1818` |

使用只含解析后 executable 目录和系统目录的最小环境时，四个命令均可运行；一次性 scratch 与 Store 均为 `0700`；`127.0.0.1` ephemeral port 可绑定；探针目录已完整清理。

同时得到一条直接负证据：如果按错误顺序拼接同一批 PATH 目录，`codex` 会被解析为另一份 SHA-256 为 `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477` 的入口，并以 `Missing optional dependency`、exit `1` 失败。没有业务步骤或 scratch 写入发生。由此，Phase 2 的最小准入必须绑定并复核最终执行环境中的 exact executable 身份，不能只检查命令名“存在”。

### P1-E4：Host 与持续运行仍未证实

当前 Codex CLI 暴露 session-id resume 接口，Desktop Host 暴露 heartbeat/automation 接口；这里仅观察到接口存在。尚无同等权限 sandbox 下的 nested Codex 写入、一次故障后同身份续接、等待前退出常驻进程、到期唤醒或不少于 48 小时的机器证据。因此不能据此承诺小时级主动执行或多日级耐久等待。

## 七层闭合结果

`已闭合` 表示形成合同不再需要 Owner 补充；`START 阻断` 表示系统必须先获得直接能力证据，不能留到运行中找用户。

| 层 | GJ-1 真实代码交付 | GJ-2 Nepha | GJ-3 耐久等待 |
| --- | --- | --- | --- |
| 结果 | 已闭合：修复真实 501，并交付测试、HTTP smoke、故障恢复和边界报告。 | 已闭合：完成四包导出和重启 readback，停在公开发布 Owner Gate。 | 已闭合：两段本地交付跨自然等待完成，前段效果不重复。 |
| 旅程 | 已闭合规格；P1-E1 已证明当前真实失败。v5 纵切尚不存在，START 阻断。 | 已闭合规格；P1-E2 只证明已有核心验证。Phase 0 exact fixture 全旅程尚未执行，START 阻断。 | 已闭合规格；没有 durable wake 全旅程证据，START 阻断。 |
| 输入 | 已闭合：exact 历史 commit、固定脏字节和 HTTP 输入均可取得。 | 已闭合：exact commit、固定中文输入和四个平台目标均已版本化。 | 已闭合：一次性仓库、两份固定本地交付物和 effect identity 已定义。 |
| 权限 | 已闭合：只写 archive/scratch；无 commit、push、发布、付费或源仓库修改。 | 已闭合：只写 clean archive/私有数据根；不触碰源、v3/v4 数据、Telegram 或平台。 | 已闭合：只写一次性本地项目；不联网、不提交、不发布，不承诺关机恢复。 |
| 环境 | P1-E3 证明本机基础条件；相同 sandbox 的 Host 写入、最终环境指纹复核和故障恢复尚未验证，START 阻断。 | P1-E3 与 P1-E2 证明基础命令、私有目录和 loopback；nested Codex、端口竞态和 verifier 恢复尚未验证，START 阻断。 | 本地基础条件已验证；跨 Host 重新进入时的工作区、身份和效果事实未验证，START 阻断。 |
| 持续运行 | 小时内目标尚无相同包络 Host spike，START 阻断。 | 2–4 小时目标尚无相同包络 Host spike，START 阻断。 | 2–5 分钟 development spike 与不少于 48 小时 release journey 均未完成，START 阻断。 |
| 验收 | 已闭合：非 501、安全拒绝、无回显、直接测试、脏字节和 diff 边界。 | 已闭合：四包 exact version 分别由预置 fixture 批准，X 中英文分别版本化；导出、幂等、重启 readback 和秘密边界均明确。 | 已闭合：同一身份、第一效果写入恰为 1、第二结果引用第一 digest、最终 readback 一致。 |

## 一次性补齐建议

### GJ-1

Phase 2 只实现这一条最小 walking skeleton。START 前先在同一 sandbox 中完成 exact executable 复核、Host 写入、loopback、verifier 和一次无外部效果故障探针；全部通过后才允许模拟 START。运行中没有业务 Gate，也不要求用户填写控制 JSON。

### GJ-2

复用 GJ-1 已证明的最小能力，不提前建设 GJ-2 专属控制面。待 Phase 2/3 能力成立后，用 Phase 0 exact fixture 执行四包全旅程；四个包的 exact version 均由预置 fixture 逐一批准，运行中不需要 Owner 介入。公开发布决定仍是唯一最终业务 Gate。

### GJ-3

Phase 2 前半段先做 2–5 分钟同身份 development spike，主动进程必须在等待前退出；失败就缩小或拒绝时长承诺。后续只有跨独立 Host 唤醒的回归和不少于 48 小时的 release journey 才能分别支持恢复与多日耐久主张，不建设 daemon 或大型队列来掩盖 Host 缺口。

## 模拟 START 决策

| 旅程 | 决策 | START 前剩余技术条件 | 现在还需 Owner 回答 |
| --- | --- | --- | --- |
| GJ-1 | `REJECT_NOW / READY_AFTER_PHASE_2_PREFLIGHT` | 最小纵切、相同 sandbox Host 写入、一次故障恢复、环境身份复核。 | `0` |
| GJ-2 | `REJECT_NOW / READY_AFTER_PHASE_2_3` | v5 最小能力复用、exact fixture 全旅程、nested Codex 与恢复实证。 | `0` |
| GJ-3 | `BLOCKED_BEFORE_START` | 同身份 resume/wake、效果去重 readback、合同时长内耐久实证。 | `0` |

拒绝 START 是当前正确的准入结果：所有 PATH、权限、Store、scratch、端口、verifier、Host 和时长问题都已在模拟 START 前展示，没有把技术问题伪装成运行中 Owner Gate，也没有用较短观察窗口制造成功。

## Phase 1 退出 Gate

- 三条真实需求均已用人类可读合同和七层问题演练，用户无需 JSON。
- 历史 501 与 PATH/executable 身份问题已有当前可复现直接证据。
- 现有验证能证明什么、不能证明什么均已写明。
- 所有已知技术阻断在模拟 START 前暴露，并各有最窄补齐顺序。
- 当前不需要 Owner 追加业务答案、权限或秘密。
- 本阶段没有新增产品代码、依赖、模块、状态、schema、wrapper、validator、gate 或恢复机制。

因此 Phase 1 通过，下一步进入 Phase 2，并只针对 P1-E1 的真实 501 失败与 P1-E3 的 executable 身份失败建设最小 walking skeleton。
