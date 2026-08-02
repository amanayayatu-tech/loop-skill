# Phase 2 GJ-1 DEVELOPMENT 真实运行记录

状态：`DEVELOPMENT / GJ1_WALKING_SKELETON_PASS`

证据日期：`2026-08-02`（Asia/Shanghai）

本记录是人类可读的真实旅程证据，不是 runtime receipt、schema 或新的控制面事实格式。本次结果只证明固定 GJ-1 walking skeleton；不证明通用任务、自动 wake 或 48 小时耐久。

## 实现身份

- clean implementation commit：`c4608d041e4eb256bd12ec02f8087418c5debaac`
- v5 入口文件 SHA-256：`63a3e6fdb851eb1c4fa2f563dc4044b74bd17d0a7e82f3eca8f58ed4d166902a`

## 运行身份与 START 前事实

- DEVELOPMENT run identity：`wZ5vnt`
- disposable archive：`/tmp/loopskill-v5-gj1-real.wZ5vnt/真实代码交付`
- exact target commit：`a3b57ecea7e7e2f6e000820b06e7c895efd4a84b`
- exact target tree：`09c6e0f54b879fe20a600bd62479e5caa05cd0df`
- target remote：空。
- START 前 target status：只有 `?? OWNER-NOTES.md`。
- Owner note SHA-256：`0e2ec45eb2cbf607487b376c57f11c48fea06443c4748f312bb3fdb23f11aa5d`。
- source repository START 前 HEAD：`74051fbaecced9feb326fe53bff43738fd439856`；status 为空。
- implementation worktree 在 prepare 与 START 前均为上述 clean commit。

prepare 从固定自然语言读取意图，向用户打印一份 Launch Contract。prepare 前后 target status 均只有 Owner note；合同未写入 target workspace。私有 handoff 位于 owner-only scratch，绑定 resolved workspace、HEAD、Owner note、允许文件基线、合同摘要以及 exact Codex、Node、Git executable；START 复核后使其失效。

合同实际报告 Codex `0.144.4`、Node `v22.22.1`、Git `2.50.1 (Apple Git-155)`，并完成 workspace 写权限、0700 scratch、loopback 和 exact executable 探针。

## 一次 START 的观察结果

START 后没有技术性人工介入，也没有重发 Worker。

1. Codex Worker 调用一次，只修改 `src/server.js` 与 `test/server.test.js`。
2. 直接 `node --test` 在独立 verifier 中 exit `0`。
3. 第一个 verifier 子进程按 DEVELOPMENT 注入明确 exit `73`；它没有业务或外部效果。
4. 系统保留同一 Worker diff，只重建真实 verifier 一次，Worker 调用次数仍为 `1`。
5. 独立 verifier 对 `/today`、`/inbox`、`/content`、`/settings` 分别执行真实 loopback GET；四项均为 HTTP `200` 且各自 `data-view` 正确。
6. verifier 从一个页面响应取得 session 与 CSRF；合法 `POST /api/intake` 返回 HTTP `201`，原 `501` 消失。
7. 缺 Origin、缺 Session、缺 CSRF 的真实 POST 各返回 HTTP `403`。
8. 固定私密 marker 未出现在业务响应、server stdout 或 stderr。
9. 最终报告先给出 intake 业务结果，再报告页面、安全、测试、恢复、diff、外部效果和限制。

## START 后 readback

- source repository HEAD 仍为 `74051fbaecced9feb326fe53bff43738fd439856`；status 仍为空。
- implementation worktree 仍为 clean `c4608d041e4eb256bd12ec02f8087418c5debaac`，入口 SHA-256 未变。
- target HEAD 仍为 `a3b57ecea7e7e2f6e000820b06e7c895efd4a84b`；remote 仍为空；staged diff 为空。
- target status 恰为 ` M src/server.js`、` M test/server.test.js`、`?? OWNER-NOTES.md`。
- target `git diff --name-only` 恰为 `src/server.js` 与 `test/server.test.js`，且 `git diff --check` 通过。
- final diff SHA-256：`1e1f34d59aaca9108279c96d7f086bd64b58a79e4c1e84fb227494d06783e55b`。
- final `src/server.js` SHA-256：`ec5fb8fa849308e0a3478c82a2dda4419edda8d684bce54c149ee9de9bd9fa90`。
- final `test/server.test.js` SHA-256：`81749f1006ecebc70e8e3ef3d3baa4d3a6535c257be52e3b9af05b0929030338`。
- Owner note SHA-256 仍为 exact `0e2ec45eb2cbf607487b376c57f11c48fea06443c4748f312bb3fdb23f11aa5d`。
- 对应私有 handoff 已不存在；START/Worker/verifier 进程均已退出。

目标仓库没有 commit、push 或 publication，且没有 remote。项目外部网络的边界由 `workspace-write` sandbox 与明确禁止网络的 Worker prompt 提供；本次没有做系统级网络监控，因此不把“全系统绝对无网络”列为已观察事实。

## 被纠偏中止且不得作为证据的身份

`Sb5Zgm` 在 exact-Git/四页面修正仍为未提交 diff 时已经完成 prepare，并在监督纠偏到达前刚进入 START。纠偏到达后，绑定该 archive 的 Python 与 Codex 进程被明确终止；终止 readback 时 target 仍只有 `?? OWNER-NOTES.md`，没有源码 diff。该身份永久标记为 `ABORTED / INVALID_FOR_PHASE_2_EVIDENCE`，不复用、不重分类为 PASS，也不计入上述成功旅程。

## Phase 2 结论

固定 GJ-1 已满足 Phase 2 walking skeleton 退出 Gate：自然语言形成 Launch Contract；START 前暴露并复核已知阻断；一次 START 到达真实业务结果；一次 verifier 故障在零技术介入下恢复；最终报告与 HTTP、Git 和 Owner note readback 一致。

Host 自动 wake 与 48 小时耐久仍未被本次运行证明；`docs/v5/phase-2/host-capability-spike.zh-CN.md` 中的 `WAKE_BLOCKED_BEFORE_START` 结论保持不变，进入 Phase 3 时不得由本结果外推。
