# GJ-1：真实代码仓库交付

## 最终意图

证明用户只说自然语言并确认一次后，LoopSkill 能在一个真实 Git 仓库中保留用户脏改动、完成最小代码修复、运行直接测试和业务 smoke、恢复一次 verifier/进程故障，并给出与实际 diff 一致的报告。

## 固定输入

- 项目：Nepha Content OS 的一次性 Git archive，起点为真实 commit `a3b57ec`。
- 已观察缺陷：受 Origin/Session/CSRF 保护的 `POST /api/intake` 固定返回 HTTP 501；同 commit 的测试未覆盖该 POST 业务行为。
- 旅程设置：在 archive 内初始化本地 Git 身份，并在 START 前创建未跟踪的 `OWNER-NOTES.md`，exact bytes 为 `Owner draft: keep this byte-for-byte.\n`，SHA-256 为 `0e2ec45eb2cbf607487b376c57f11c48fea06443c4748f312bb3fdb23f11aa5d`。
- 用户原话：

> 修复这个仓库里 `/api/intake` 永远返回 501 的问题。只做一个最小可用的直接文本 intake：合法同源会话提交标题和文本后返回成功结果，不回显原始私密文本；保留现有四个页面和安全边界。只修改直接相关源码和测试，保留我的未提交备注，运行相关测试和真实 loopback HTTP smoke。不要 commit、push、访问外部网络、发布或修改仓库外文件。

## START 前必须闭合

1. 记录 exact source commit、工作区路径、Git 状态和 Owner 脏文件摘要。
2. 建议将写范围限定为 `src/server.js` 与直接测试；若调查证明最小行为必须触及第三个现有文件，在合同中一次性披露原因。
3. 真实解析并探测 Node、测试命令、loopback listener、临时端口、workspace 写权限和私有 scratch。
4. 验证 Codex Host 能在相同 sandbox/write scope 下修改 archive，且不会读取源仓库或用户秘密。
5. 明确业务 smoke：取得页面 session/CSRF，POST 合法直接文本得到非 501 成功；缺 Origin/Session/CSRF 仍失败关闭；响应和日志不含原始私密文本。
6. 外部效果固定为 `0`：除本机 loopback 验收外，无 commit、push、外部网络、发布、付费、安装或源仓库写入。

## 一次 START 后的路径

1. 工作段 A：阅读当前代码与直接测试，实施能解释 501 的最窄修复并添加直接回归。
2. 内部验证：运行直接单测与真实 loopback HTTP smoke。
3. 故障注入：第一次独立 verifier 进程在获得 Worker diff 后异常退出，且外部效果已知为零。
4. 内部恢复：保留同一 Worker 结果，重建 verifier/scratch 并重新验证，不再次询问用户、不创建新 Loop、不重复 Worker 调用。
5. 工作段 B：核对允许写范围、Owner 脏文件摘要、业务响应和测试结果，形成业务优先报告。

## 通过事实

- 一次 START；START 后技术性人工介入 `0`。
- 至少跨两个内部工作段；注入故障后 Worker 业务调用次数不增加。
- 合法 intake 真实 HTTP smoke 通过，原始 501 行为消失；安全拒绝路径仍通过。
- 修改仅在合同允许范围；Owner 预存脏文件字节完全一致；源仓库和仓库外路径未改变。
- 直接测试与业务 smoke 均 PASS；没有用测试数量替代 HTTP 业务结果。
- commit/push/external-network/publication/paid effect 均为 `0`。
- 最终报告先回答 intake 是否真实可用，再列测试、diff、限制和外部效果。

任何一项不成立，本次 GJ-1 为 FAIL；诚实停止不是 PASS。Phase 2 walking skeleton 只需闭合本页，不由此推导通用工作流引擎。
