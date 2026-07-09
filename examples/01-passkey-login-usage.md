## 生成文件

已生成 Controller Pack：`examples/01-passkey-login-controller-pack.md`。
这个 Markdown 文件是发给控制线程的唯一材料；不要再手动拆分复制 Controller/Worker/Reviewer/State-Writer 段落。

## 运行中卡点预估

前提：以下预估只针对已经通过 Clarification Gate、可以正式启动的 loop；不包含工作区、repo/root、PRD、权限边界等启动前必须补齐的问题。

运行准备度：READY_BUT_LIKELY_REVIEW_REPAIRS

预计会停下等你的阶段：
1. 阶段：真实外部能力或高风险操作
   为什么会停：真实 API、密钥、Billing、Deploy、Merge、生产写入或用户可见发布不能由 loop 擅自启用
   触发状态：AWAITING_HUMAN_APPROVAL
   你会被问什么：是否提供凭证、批准真实调用/部署/合并，或继续保持占位/waiver

2. 阶段：依赖安装 / 本地验证环境
   为什么会停：首次 install 可能下载 native binary 或大依赖，受 registry、网络、package store、lockfile、平台包影响；Next/SWC、Playwright、Sharp、canvas、Electron 尤其常见
   触发状态：RUNTIME_DEPENDENCY_RETRYING；重试预算耗尽后才升级为 RUNTIME_DEPENDENCY_BLOCKED | VALIDATION_BLOCKED
   自动处理：控制线程应下发至少 10 次重试梯队，包括延长 timeout、断点/分段/预取、降低并发、换公开 registry/source、清理项目内部分残留
   你会被问什么：只有重试耗尽、错误明显非临时、或下一步需要凭证/付费/系统级改动/越界写入时，才会问你

3. 阶段：浏览器 smoke 或人工验收
   为什么会停：自动检查只能证明局部证据，不能替代真人可用性、视觉确认或公开声明批准
   触发状态：AWAITING_HUMAN_APPROVAL | PASS_WITH_WAIVER
   你会被问什么：是否完成真人验收、接受 waiver，或调整验收范围

4. 阶段：验证与独立审查修复
   为什么会停：lint/test/build/CI/export 或 Reviewer 可能发现缺口，需要 1-3 轮修复
   触发状态：NEEDS_REPAIR，超过修复上限后 HARD_BLOCK
   你会被问什么：是否继续增加修复轮数、放宽范围，或把部分 P1/P2 延后

5. 阶段：可选 connector / runtime 能力
   为什么会停：GitHub、浏览器、Automation、worktree 或云端能力可能未暴露给当前 Codex App 线程
   触发状态：MISSING_CONNECTOR
   你会被问什么：是否安装/授权 connector，或改用本地/手动证据

6. 阶段：loop 审计轨迹同步
   为什么会停：线程已经推进但 LOOP_STATE.md、LOOP_EVENTS.jsonl 或 reports 归档未同步时，必须先修复可回查链路
   触发状态：OBSERVABILITY_GAP
   你会被问什么：是否允许 State-Writer 根据最新线程报告补写状态/事件/报告摘要

## 预计耗时

前提：工作区、源文件、权限边界、验证命令和审查门已经齐全。这是本地 Codex loop wall-clock 估算，不是 SLA。

最短时间 min：45-90 分钟
典型时间：2-4 小时
最大时间 max：4-8 小时

不计入：
- 等你提供 API key / 凭证 / 订阅配置的时间
- 等你提供 cost_cap_usd / 调用次数 / Token 上限或批准真实付费调用的时间
- 等你批准 deploy / merge / 外部写入的时间
- 等真人验收或离线业务判断的时间
- 等 registry / 网络 / 原生包下载恢复的时间

可能拉长时间的因素：
- auth edge cases
- browser/passkey support
- native dependency install
- test fixture setup
- Reviewer repair rounds



## 你应该怎么用

1. 在 Codex App 左侧选择或创建项目工作区：`myapp`。
2. 确认该工作区根目录是：`/workspace/myapp`。
3. 把 PRD/spec/图片/PDF/数据放到工作区，推荐放 `docs/`；或确保控制线程能读取这些路径：docs/auth-spec.md and any attached login-flow screenshots。
4. 在这个工作区中新建一个聊天，命名为“控制线程”。不要在普通对话区启动。
5. 把生成的 Controller Pack `.md` 文件发给控制线程。
6. 控制线程默认只创建或继续当前需要的最少线程：一个当前 Worker、一个审查线程、一个状态线程；不会按 R/S/T/U/W 这种阶段提前创建一堆 Worker。
7. 这些必须是 Codex App 项目线程：控制线程要用 `list_projects` 和 `create_thread(target.type="project", projectId=...)` 创建。`multi_agent_v1.spawn_agent`、`agent_type`、`fork_context`、"创建智能体" 都不算。
8. 目标实现分支不等于 worktree 启动分支。控制线程必须先验证 existing base branch 是否存在；目标分支不存在时，不能把它当作 `startingState.branchName`，应从当前工作树或已验证基线启动 Worker，再由 Worker 在 `/goal` 里创建/切换目标分支。
9. 控制线程必须把真实 `threadId` 写进状态。线程标题只是显示名；如果 `create_thread` 只返回 `pendingWorktreeId`，控制线程要 broad list project threads，用 cwd/worktree、projectId、bootstrap prompt、`READY_IDLE_AWAITING_GOAL` 等证据找回真实 Worker，再重命名和登记。
10. 控制线程必须创建 heartbeat 自动唤醒，默认每 15 分钟检查并继续推进；如果没有 heartbeat，就不算完整自动 loop。
11. heartbeat 建好后，控制线程才把 First Goal 发给 `implementation`，之后按 Worker 报告 -> Reviewer 审查 -> State-Writer 记录 -> 下一 Goal 的顺序循环。后续阶段优先复用同一个实现线程，只有明确需要独立 worktree/专业角色/并行时才新建线程。
12. 如果子线程跑到普通对话列表，说明项目绑定失败，让控制线程停下处理 `MISSING_PROJECT_WORKSPACE`。
13. 如果控制线程说创建了“智能体 / sub-agent / agentId”，说明它没有创建真正的 Codex App 线程，让它停下处理 `THREAD_TOOLS_UNAVAILABLE`，不要继续执行。
14. 如果 Reviewer 已经 `REVIEW_PASS`，控制线程不应该只告诉你“等我决定下一步”。它必须记录状态并继续派发下一 Goal；否则让它按 `NON_ACTIONABLE_NOTIFY_BLOCKED` 处理。
15. 如果任务要求 commit hash、PR、push、deploy、source 文件入库或 `.codex-loop/` gitignore 处理，控制线程必须先确认当前阶段允许这些动作；不允许时应停在 `PHASE_PERMISSION_CONFLICT`，不能一边禁止一边要求 Worker 完成。

## 怎么回查 loop

- 控制线程：看它把任务派给谁、为什么派发、下一步等什么。
- 实现线程：看它改了哪些文件、跑了哪些命令、验证结果是什么。
- 审查线程：看 review findings、`PASS` 或 `NEEDS_REPAIR`。
- 状态线程：确认它只写状态/日志，不改业务代码。
- heartbeat 自动化：看 Codex Automation/heartbeat 卡片是否为 active、间隔是否正确、目标是否是控制线程。
- `.codex-loop/LOOP_STATE.md`：当前进度快照；看现在在哪个阶段、卡点是什么、下一步做什么。
- `.codex-loop/LOOP_EVENTS.jsonl`：逐步流水账；看每次派发、回报、重试、审查、停止的时间和结果。
- `.codex-loop/TRIAGE.md`：问题清单；看发现了哪些问题、证据、严重性和处理状态。
- `.codex-loop/reports/`：报告归档；看每轮实现/审查摘要和最终结论。

如果线程里显示已经做了事，但这些文件没有更新，让控制线程先处理 `OBSERVABILITY_GAP`，不要继续派发新任务。

正常自动推进信号：
- 启动后能看到 heartbeat 已 active，并且目标是控制线程。
- Worker 报 `READY_FOR_REVIEW` 或 `PASS` 后，控制线程会发 `/review`，不会直接说完成。
- Reviewer 报 `REVIEW_PASS` 后，控制线程会先让 State-Writer 记录，再继续下一 Goal 或最终 closeout。
- 依赖下载/registry/native binary 失败时，先看到 `RUNTIME_DEPENDENCY_RETRYING` 和多次自动重试，而不是马上问你。

异常断停信号：
- Controller 输出“等我决定 / 后续我会继续 / 需要用户提醒”但没有派发下一条消息。
- heartbeat 没创建、目标线程不是控制线程，或只 wake 不执行状态表里的下一动作。
- 已经有 Worker/Reviewer 结论，但 `LOOP_EVENTS.jsonl` 没有对应事件。
- 已经给了成本/Token/调用策略，却仍仅因为某个可选 cap 字段是 `UNSPECIFIED` 停在 `BLOCKED_COST_CAP`。

## 你只需要介入

- 需要真实订阅、支付、社群、密钥或外部服务配置时。
- 需要真实 LLM/API、`codex exec`、模型评分 smoke 或其他付费/计量调用，但没有预算/调用/Token 上限时。
- 需要批准 PR merge、deploy、release 或真实外部写入时。
- 出现 `AWAITING_HUMAN_APPROVAL`、`BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、`THREAD_TOOLS_UNAVAILABLE`、`MANUAL_FALLBACK_REQUIRED`、`MISSING_CONNECTOR`、`MISSING_PROMPT_PACK`、`MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`OBSERVABILITY_GAP`、`HARD_BLOCK` 时。
- 需要真人测试证据，或你决定接受 waiver 时。

## 手动降级

只有当 Codex App 没有线程工具或自动化工具时才手动降级：你手动在同一个项目工作区里创建实现线程、审查线程、状态线程，把 Controller Pack 里的对应 prompt 发过去，并把回报交回控制线程。手动降级也必须保留审查门、状态单写者和停止条件。
