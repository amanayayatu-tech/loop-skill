# Phase 2 Codex Host capability spike

状态：`DEVELOPMENT / WRITE_AND_RESUME_PASS / WAKE_BLOCKED_BEFORE_START`

证据日期：`2026-08-02`（Asia/Shanghai）

本探针只回答 Phase 2 前半段的 Host 能力问题，不是黄金旅程 PASS，不支持小时级或 48 小时耐久主张，也没有创建 Loop、persistent goal、heartbeat、独立 task、daemon、queue、schema 或 v3 控制状态。

## exact 输入

- Codex CLI：`0.144.4`
- executable SHA-256：`3302acbda5f53de1a71ebdb0c0f2aae0d47f9324aa9fb6b4e78a47014fd51c7d`
- sandbox：`workspace-write`
- 一次性私有 Git fixture commit：`a7709f00e52328dd336ead1cf1160324d6d12d4c`
- Codex session identity：`019fc1f6-8c75-7713-9370-01bc0623ede6`
- session identity SHA-256：`d69f2e36ff8fabf3b63f2383803a81657ef306a3b82f5a849ac1b20ac8797293`

fixture 只有两个已提交文本文件；提示明确禁止网络、提交、Git metadata 和仓库外写入。

## 工作段 A：真实 workspace write

exact Codex executable 启动 session 后只把 `probe-a.txt` 改为 `host-write-ok\n`，SHA-256 为 `b78e86c24c70a7e059456d294095bc43debdbecf7f8f527f6cc7e01d7323bab4`。

- Codex 自己执行 byte-level readback 并返回 `PROBE_A_OK`。
- 进程 exit `0`。
- Git diff 只有 `probe-a.txt`。
- `probe-b.txt` 仍为原摘要 `fc083bec714595c28f00de8eb8c1b18611f50e3f5b0581ce5b4131234f618963`。

## 工作段 B：同 session resume

第一个 Codex 进程退出后，以 exact session id 调用 `codex exec resume`。事件流再次报告同一个 `thread_id`，随后只把 `probe-b.txt` 改为 `host-resume-ok\n`，SHA-256 为 `9a5e0d8817c9498adb1a9240a7bcbbed94ec9e9cdd69d8a4a99a5f2a8294b17b`。

- Codex 自己复核 `probe-a.txt` 未变并返回 `PROBE_B_OK`。
- resume 进程 exit `0`。
- 最终 Git diff 恰为两个目标文件；fixture HEAD 未变。
- 外层 readback 再次逐字节验证两个结果；一次性 fixture 随后安全清理。

允许主张：当前 exact CLI、权限和 sandbox 下，真实 workspace write 与进程退出后的显式同 session resume 可用。

不允许主张：这不是故障后自动恢复，不是自然等待后的 Host wake，也没有证明重复效果保护或任何时长可靠性。

## 非终止诊断

事件流同时出现 model cache 字段、unstable feature、skill context budget 和 MCP shutdown 警告。两段业务动作与最终 verifier 均完成且进程 exit `0`，所以这些事实不改判本探针；它们也不能被删除或伪装成“无警告”。Phase 2 walking skeleton 使用更窄的 Codex 配置与明确写范围，仍以最终业务 readback 决定结果。

## Desktop wake 决策

Desktop 原生 automation 接口能够表达 target thread、view 和 delete，但当前工作线程正在 active turn 中；“短时触发前真实退出 → 原生重新进入 → 仍是同一业务执行身份”的语义没有直接证据。CLI session 也没有出现在 Desktop 最近线程 readback 中，不能把两种 identity 猜测为同一对象。

因此没有创建任何 automation 或持久调度，GJ-3 保持 `BLOCKED_BEFORE_START`。这满足保守边界：只要 exact thread 绑定、短时触发、创建后 readback、触发后安全停用/删除中的任一项不能被完整证明，就不运行 wake spike。Phase 2 继续 GJ-1，不用 GJ-3 阻断最小纵切。
