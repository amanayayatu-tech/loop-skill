# Phase 3 最小架构选择门

状态：`DEVELOPMENT / ARCHITECTURE_CHOICE_GATE_PASS`

证据日期：`2026-08-02`（Asia/Shanghai）

本页只依据 [主计划 13.1 与 17.1](../loopskill-5.0-master-plan.zh-CN.md)、[GJ-1 真实运行](../phase-2/gj1-development-run.zh-CN.md) 和 [Phase 3 事故/Host 证据](incident-gap-audit.zh-CN.md) 作最小选择；它不是实现计划，也不授权新增公开命令、schema、数据库、queue、daemon、status projection 或通用恢复层。

## 选择结论

| 责任 | 选择 | 当前证据边界 |
| --- | --- | --- |
| 业务 task/thread identity | 交给 Codex Host | Desktop heartbeat 已精确绑定并重新进入同一 thread；LoopSkill 不另造 Loop id、task registry 或第二线程。 |
| 等待调度与投递 | 交给 Desktop native heartbeat | Host 负责 native scheduling/投递与 target readback；当前只证明约 2 分钟，长期耐久未证明；LoopSkill 不建设 daemon、queue、cron wrapper 或 supervisor heartbeat。 |
| turn 退出后的重新进入 | 交给 Codex Host | 2–5 分钟 DEVELOPMENT spike 已证明一次 same-thread reentry；48 小时与跨日仍未知。 |
| 主动 Worker 执行 | 交给 exact Codex executable/session | v5 只在合同中绑定 executable、workspace 和权限，既有 Host event stream 证明一次真实工作段；不建设通用 Host adapter。 |
| 用户承诺 | LoopSkill 保留一份人类可读 Launch Contract | 用户只看最终意图、承诺、权限、自动恢复、Gate、停止边界和限制；不看控制 JSON、ID 或 digest。 |
| prepare→START 复核 | LoopSkill 在 owner-only scratch 保留一份最小 prepared fact | 仅绑定当前 workspace、HEAD、Owner 脏字节、允许文件、exact executable 与合同摘要；START 后失效，不成为长期 Store。 |
| 自然等待效果去重 | LoopSkill 在 0700 私有根保留一份最小人类可读效果事实 | 只含 business identity、`not_before`、已有效果 key/digest、next acceptance 和 known effects；Host 醒来先 readback，未知即停止。 |
| verifier 启动与局部恢复 | 固定纵切内的局部函数 | 只处理当前已复现的 verifier exit 与一次 `EADDRINUSE`；不形成 retry loop、attempt budget 或公开恢复状态。 |

v3/v4 runtime、Store、gateway、schema 和数据保持原样并存；v5 不读取、迁移、复活或双写它们。

## 当前 `loopskill5` 的产品身份

`codex-loop-prompt-architect/scripts/loopskill5` 明确定性为 **固定 GJ-1 DEVELOPMENT harness**，不是 5.0 公开产品入口。它只接受固定自然语言、固定 source commit 和 `prepare`/`start` 操作，用来证明 Launch Contract、一次 START、真实 Worker、HTTP 业务验收与局部恢复。

普通用户未来面对的产品入口仍应是 Codex 中的自然语言 Skill 会话：系统主动调查、展示合同、取得一次确认并自主执行。当前 harness 的 workspace 参数、固定 fixture 和内部命令不得直接包装成公开 UX；在真实 Beta 证明最小会话入口前，不新增路由器或通用任务协议。

## 自有机制的 17.1 四问

### M1：私有 prepared contract fact

1. **当前失败**：Phase 1 真实复现错误 PATH 选择；Phase 2 直接复现 prepare 后 executable 漂移。仅靠屏幕合同无法在 START 前证明 workspace、Owner note 与 executable 未漂移。
2. **为何不只交给 Host**：Host thread 可保留对话，但不会自动提供 prepare 与 START 两个时间点的 exact byte/workspace 比较；一个私有文件已经是最小承载。
3. **减少什么**：避免错误准入、START 后才找用户修 PATH，以及 Worker 在陈旧合同上产生副作用。
4. **删除后哪项失败**：IB-01/IB-03 与 GJ-1 的“START 前漂移零副作用拒绝”失去直接保证。

### M2：固定 GJ-1 verifier 的一次局部恢复

1. **当前失败**：真实 verifier 子进程 exit 与真实 Node `EADDRINUSE` 均已复现；未恢复时会错误终止已完成 Worker。
2. **为何不只交给 Host**：verifier 进程、临时端口和 Worker diff 都由 harness 当前调用拥有；在同一函数内重建一次比把故障升级为 Host task 或新线程更小。
3. **减少什么**：消除一次技术性人工救场，且 Worker 调用保持 `1`，不重复业务效果。
4. **删除后哪项失败**：IB-05/IB-07、GJ-1 注入故障和组合 IB-10 回归重新失败。

### M3：自然等待的一份最小效果事实

1. **当前失败**：GJ-3 在 wake 前必须退出 turn；仅靠调度 identity 无法证明 artifact A 是否已写、摘要是否一致或能否安全避免重写。
2. **为何不只交给 Host**：Host 负责唤醒同一 thread，但业务效果位于用户 workspace；线程历史可能压缩，且 Host 不替业务 verifier 保存 artifact digest。
3. **减少什么**：醒来无需用户重发任务；A 已知一致时直接继续，未知时停止，避免重复效果。
4. **删除后哪项失败**：GJ-3 的同一 business identity、A 写入恰为 `1`、B 引用 A exact digest和未知不盲重发无法证明。

## 删除审查与未决边界

- Host 已承担 identity、调度与 reentry，因此不建设自有 Controller、heartbeat、task queue 或长期状态机。
- 一份合同 fact 与一份等待 effect fact 分属不同真实旅程，不并存为两套长期 writer；前者 START 后失效，后者只跨一次自然等待。
- IB-08 没有真实 PAUSED/Active 用户表面，继续保留证据缺口；不得为测试造 projection。
- IB-11 等真实 GJ-2；IB-14 等真实安装/卸载旧字节矩阵。它们不驱动当前新增机制。
- Phase 3 下一项只允许执行一个超过 300 秒、含明确进程终止注入的 native same-thread GJ-3 regression。48 小时运行必须等待可冻结 candidate，当前不得启动。
