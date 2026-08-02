# Phase 3 事故行为缺口审计

状态：`DEVELOPMENT / GAP_AUDIT_COMPLETE / SAME_THREAD_WAKE_SPIKE_PASS / OVER300_CHILD_TERM_WAKE_PASS / IB02_IB05_IB10_REGRESSION_PASS / PHASE3_GJ1_CANDIDATE_PASS / GJ2_A43_OWNER_GATE_REACHED_SPEC_INCOMPLETE / GJ2_SCOPQP_DEVELOPMENT_PASS / GJ3_SURFACE_DEVELOPMENT_PASS`

证据日期：`2026-08-02`（Asia/Shanghai）

审计基线为 [事故行为语料](../phase-0/incident-behavior-corpus.zh-CN.md)、[GJ-1 DEVELOPMENT 真实运行](../phase-2/gj1-development-run.zh-CN.md)、[Host capability spike](../phase-2/host-capability-spike.zh-CN.md) 和 [GJ-3 规格](../phase-0/golden-journey-gj3-durable-wait.zh-CN.md)。本审计不新增代码、状态、命令、schema、Store 或恢复机制；GJ-1 成功只支持其已观察固定路径，不自动闭合其他事故。

| ID | 当前分类 | 尚未闭合的最窄缺口 |
| --- | --- | --- |
| `IB-01` | `GJ1 已有直接证据` | 已证明固定 private prepare root 为 0700、handoff 为 0600 且不污染 workspace；尚未由此建设或主张通用 Store。 |
| `IB-02` | `GJ1 已有直接证据` | Phase 1 证明错误 PATH 顺序会选错 Codex；Phase 3 直接回归在清空可选 ambient env 后仍使用 prepare 绑定的安全 PATH，并以 exact Node 真实运行 `--version`。当前固定入口不接受用户自填 env，也没有为此新增 env schema。 |
| `IB-03` | `GJ1 已有直接证据` | prepare 绑定 Codex/Node/Git，现有直接回归证明 START 前 executable 指纹漂移以 Worker 0、workspace 0 effect 拒绝；没有通用 executable registry 主张。 |
| `IB-04` | `GJ1 已有直接证据` | 固定 Owner note 被明确记录为 START 前既有事实，最终 diff 只认两项 transition 修改；其他 artifact 的“既有事实/本次变化”语义尚未验证。 |
| `IB-05` | `GJ1 已有直接证据` | Phase 3 以真实 socket 抢占 verifier 选定端口并观察 Node `EADDRINUSE`；系统只换临时端口重建 verifier 一次，真实 loopback 随后通过，Worker 仍为 `1`。listener 权限失败仍没有独立真实输入。 |
| `IB-06` | `GJ1 已有直接证据` | exact Host spike 与 GJ-1 都证明相同 workspace-write 模式能真实写目标 workspace；不支持自动 wake 或更宽权限主张。 |
| `IB-07` | `GJ1 已有直接证据` | 真实 GJ-1 注入 verifier exit `73`，只重建 verifier 一次且 Worker 调用仍为 `1`。 |
| `IB-08` | `已有部分直接证据 / 原事故仍未完全闭合` | GJ-3 实际表面已有“单一 effect fact → 等待说明 → same-thread wake → 最终报告”同源的直接证据；但 v5 没有 PAUSED/Active 用户投影，权威 PAUSED、用户显示 Active 的原始冲突输入仍未复现，因此不得写成 IB-08 PASS。 |
| `IB-09` | `GJ1 已有直接证据` | 真实运行前后 target status 只含两项允许修改与 Owner note，私有 handoff 位于 scratch 并在 START 后失效；其他 runtime 类型尚未验证。 |
| `IB-10` | `GJ1 已有直接证据` | Phase 3 在同一 GJ-1 START 中依次注入 verifier exit 与真实端口竞态，保留同一 Worker 结果并最终真实验收通过；这只证明已知两类技术故障，不外推任意宽 Goal 的通用重规划。 |
| `IB-11` | `仍缺真实复现` | A43hpY 已证明从一开始不含 Telegram 的固定四包合同可在原身份到达最终 Owner Gate；但没有复现运行中 Owner 跳过 Telegram/缩小范围、旧批准失效和最终主张降格，因此不改判。 |
| `IB-12` | `GJ1 已有直接证据` | Phase 1 在测试全绿时真实复现 501；GJ-1 再以真实 POST 201、安全拒绝和无回显闭合固定业务路径。 |
| `IB-13` | `GJ3 才能证明` | >300 秒 DEVELOPMENT regression 已证明等待不依赖一个已定向 TERM 的 disposable child，且 same-thread wake 后 A 不重复；该 child 不是 task 进程，因此原始 task-process 终止、跨自然日和 48 小时耐久仍未证明。 |
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

## GJ-3 >300 秒 child-termination DEVELOPMENT regression

business identity 为 `GJ3-DEVELOPMENT-OVER300-MzUovw`，架构门 candidate 为 `2549964d8a4e1dffd2db56c378df476cca5b6fc7`。disposable workspace HEAD 为 `f5f95b980e061e5bf8b1fee21ddab2c773579911`，remote 为空；0700 private root 中唯一 0600 事实文件 SHA-256 为 `7cc50d0d834a065c3e931451cdbe834862232e31019597ad21704dcf23b8cee9`。

- artifact A effect key 为 `GJ3-DEVELOPMENT-OVER300-MzUovw:artifact-A:v1`，SHA-256 为 `df96c1a1725de952b675bd701aea5daada9b434d5c50503d60278d7846b3863a`，等待前写入次数为 `1`。
- 唯一 disposable child PID `70186` 于 `2026-08-02T11:32:18Z` 启动，argv 绑定本 identity；确认 A/effect 后只对该 PID 发送 TERM。它于 `11:32:43Z` 以 `143` 退出，后续 `ps` readback 始终为不存在。
- 唯一 native heartbeat `loopskill-v5-gj3-over-300s-development-wake-mzuovw` 创建于 `2026-08-02T11:34:46.877Z`，target thread 精确为 `019fc1d7-b776-7583-a5c8-cdea92f7e458`。`11:41:19.451Z` 的首次同线程触发早于 `not_before=11:41:30Z`，因此零写入结束并保留同一 heartbeat。
- 首次零写入 turn 完成 epoch 为 `1785670890`，第二次 turn 启动 epoch 为 `1785671327`；两次 turn 之间真实 Host idle 间隔为 `437` 秒。这一机器时间独立于 heartbeat 创建到 wake 的累计计时。
- `2026-08-02T11:48:47.629Z`，同一 heartbeat 再次原生进入当前 thread；从创建到本次 wake 实际为 `840.752` 秒。事实、HEAD、empty remote、唯一 A status、A digest、B 不存在和 child PID 不存在全部匹配后，artifact B 写入一次。
- artifact B effect key 为 `GJ3-DEVELOPMENT-OVER300-MzUovw:artifact-B:v1`，SHA-256 为 `2aeefb192c62a84397fff582f4b73b412b1b4c9fcf70ab6f92b1b175cac6724b`，并引用 A exact digest。最终 A/B effect count 各为 `1`，A digest 未变，Git status 仅为两个 untracked artifact，HEAD 未变、remote 为空；没有 commit、项目外网络工具调用或 publication。
- heartbeat 删除成功；截至 `2026-08-02T11:50:30Z`，automation 文件与 identity 搜索均 readback 为不存在。

允许主张：当前 Host 能在同一 thread 以超过 300 秒的自然等待重新进入；等待不依赖该 disposable child 的存活，且已知 A 在 child 终止后没有被重写。技术性人工介入为 `0`。

不允许主张：该 child 不是 Codex Desktop、Host task 或当前 task 进程，因此本回归不证明任意 task crash recovery；也不证明 48 小时、多日、跨自然日、OS 睡眠或关机恢复。第一次过早触发的零写入只证明当前 `not_before` Gate，不扩大调度耐久主张。

## IB-02 / IB-05 确定性回归

exact implementation commit：`b6fa01acdb4271a4aa653993c92762ab1c44df30`；v5 入口 SHA-256：`cba47c1b1638494eec4b13d40b651111a91eaa61258f52a8ab88201f0b9a1530`。

IB-05 修复前，直接用例真实占用 verifier 刚选择的 loopback port；Node 因 `EADDRINUSE` 退出，现有入口错误停止为 `real verifier failed: loopback server did not become ready`。修复只把该 exact stderr 分类为 port collision，并在保留 Worker diff 后重建 verifier 一次；没有 retry loop、attempt budget、公开恢复状态或新模块。

修复后同一个 port-collision 用例通过：Worker 调用 `1`，verifier 调用 `2`，第二次真实四页面与 intake loopback 验收通过。空可选环境用例也以准备好的 safe PATH 运行 exact Node 成功。最终 `tests/test_v5_walking_skeleton.py` 共 `5` 项直接回归全部 PASS，且 Python 语法与 `git diff --check` 通过。

随后 test-only commit `346b859b62f36423df6a08f685d3437ab2afa432` 将同一用例升级为一次 START 内连续两种独立故障：verifier 依次为注入 exit、真实 `EADDRINUSE`、真实 PASS，共调用 `3` 次；Worker 仍为 `1`，最终报告准确列出两次内部恢复。没有新增 runtime 分支或用户 Gate。

该回归提交形成时，GJ-1 真实 Codex DEVELOPMENT 旅程尚未重新执行；因此这一小节只记确定性事故回归，不改写 `c4608d041e4eb256bd12ec02f8087418c5debaac` 上既有真实运行身份。后续新 candidate 的真实运行另记于下一节。

## Phase 3 candidate 上的真实 GJ-1

### 保留的报告失败身份

run identity `pQPjua` 绑定 clean candidate `ae8284c2ffeec0d2a9e9e5f613b09976e8bd48c2` 与入口 SHA-256 `fa7d5327f4048a6ec3179b7d9f9306a9df7e7ecad6984110e2e95c5f8cfecc21`。一次真实 START 的 intake、四页面、安全拒绝、无回显、直接测试、verifier crash 恢复和 Git readback 全部通过，但最终限制行仍错误声称“只证明 Phase 2 DEVELOPMENT GJ-1”。因此该身份永久保持 `BUSINESS_PASS / REPORTING_FAIL`，不计为 Phase 3 黄金旅程 PASS，也不在修复后复活或改判。

报告修复只移除开发阶段编号，使稳定限制成为“只证明固定 DEVELOPMENT GJ-1”；5 项直接回归通过后形成新 clean candidate。

### 新 candidate 成功身份

- run identity：`uFBj6h`。
- clean candidate：`b1e1a03b472a3cf7611e581c79e594ab4805ff2e`。
- v5 入口 SHA-256：`905cdeb76e9007ecc5d81f585ba9e76fa4a7a37d5e8a97bcf63a54459c788721`。
- target source：commit `a3b57ecea7e7e2f6e000820b06e7c895efd4a84b`；START 前只有 exact Owner note，remote 为空。

一次 START 后，真实 Codex Worker 调用 `1`；注入的首次 verifier exit 后只重建 verifier `1` 次，Worker 未重跑。真实 loopback POST 返回 `201`，四页面分别为 `200 + exact data-view`，缺 Origin/Session/CSRF 分别为 `403`，私密 marker 未进入响应或 server logs，最终报告阶段边界准确。

最终 readback：source repository 前后均为 clean `74051fbaecced9feb326fe53bff43738fd439856`；target HEAD 未变、remote/staged diff 为空，status 恰为两项允许修改与 Owner note；Owner note SHA-256 仍为 `0e2ec45eb2cbf607487b376c57f11c48fea06443c4748f312bb3fdb23f11aa5d`。最终 diff SHA-256 为 `e64cd3a25656a0174a87846734983ecc6e6563ce55468260facfaf2988f3f7f4`，私有 handoff 与运行进程均已不存在。

本真实运行没有注入端口竞态；IB-05 的 `EADDRINUSE` 恢复证据仍来自 exact implementation 上的确定性真实 socket/Node 回归。`uFBj6h` 是 DEVELOPMENT 证据，不是 formal canary、48 小时耐久或 release candidate 证明。

## 实际 Skill 表面的 GJ-2 DEVELOPMENT 旅程

### 身份、准入与一次 START

- business identity：`GJ2-DEVELOPMENT-A43hpY`；唯一 Codex task/thread：`019fc262-8025-7001-923c-0957b69b8fdd`。
- v5 Skill candidate：`7fdacb45781751cc2a33968ebcbed8057ede7f70`。实际开发态安装只有 `SKILL.md` 与 `agents/openai.yaml`，blob 分别为 `48cb0688ec39386bca1fceda7a3579b767d59034`、`6295d897c694e67785f25c04987ce2a5b1914d86`，均与该 commit 匹配。显式 `$loopskill5` 加载已有直接证据；全局 description budget 下的隐式自然语言发现仍为未知。
- source 为只读仓库 `/Users/peachy/Documents/自媒体之路/nepha-content-os` 的 exact commit `74051fbaecced9feb326fe53bff43738fd439856`；Git archive SHA-256 为 `87c3a36c66d3959842e818b04323ff0a4b938888d83e175d5572a4fd634b7bf7`。中文副本位于 `/tmp/loopskill-v5-gj2.A43hpY/中文项目验证/nepha-content-os`，初始 44 文件 manifest 为 `be8d843eab097f7396ba74ce311fcc9cafc264699dfb652994a71d8499a520f6`。
- 同一 PREPARE 先诚实保留 read-only Host 阻断；`workspace-write` 下 owner-only sentinel create/read/remove 通过，但 `listen(127.0.0.1:0)` 精确失败为 `EPERM`。切换到 Owner 已授权的 `danger-full-access` 技术 profile 后，只做同一短命 loopback 探针并通过：端口 `50905`，62-byte request SHA-256 `6338db8c97c2606e49844a09cbd3d4aeac0d623aa2260e4d2caecb7d09c43357`，63-byte response SHA-256 `03b92981c0cfb1d8ef4de0efa9152b5dd6a2f0e6d8e0eb69f180eedf5eabff5c`，关闭后无 listener。
- Skill 随后在同一 task、同一 identity 重展示 exact 12 项 READY Launch Contract；`2026-08-02T12:49:51.164Z` 收到唯一一条独立 `START`。直到最终 Gate，外层没有发送继续、路径、端口、Store、CSRF、内容或恢复答案；没有第二次 START、新 task、Goal、worker thread 或 heartbeat。

### 业务结果与内部恢复

真实产品入口为副本中的 `src/server.js`，数据根为 `/tmp/loopskill-v5-gj2.A43hpY/private/nepha-data`，业务端口为动态 loopback `52447`。固定输入保留末尾 LF，257 UTF-8 bytes，SHA-256 为 `24590244fb4cbe71099e8d417751c0933ddcd1ed956bf4fa4ed2650675f33025`。

第一次客户端脚本在 HTTP 前因 CommonJS 与 top-level await 的解析冲突退出；数据库 readback 为零业务效果后，Skill 自行改用 ESM。第二次在英文 v2 已创建后因 verifier 错把历史英文 v1 断言为 `invalidated` 而停止；Skill 先 readback 出产品真实语义为 v1 `current=false`、旧质量结果失效，再从 v2 之后继续，没有重放创建、主题、Brief、四包生成或 revision。两次均未请求技术救援，也没有不明效果或盲重发。

| current 包 | version | package digest | exact Approval | ExportRecord / manifest SHA-256 |
| --- | ---: | --- | --- | --- |
| `x:zh-CN` | 1 | `05bb0dcd787116a0341e3ac2bf76fb9f3ea8688b50c375d5dc7b2860f412030d` | `a8dae1c8-36c7-4229-8eee-e083fee5efdf` | `export:9d3987b8-3b07-4578-bef5-b087f4263bc0:GJ2-DEVELOPMENT-A43hpY:export:x:zh-CN:v1` / `f72bd3b9a7164332a8a6d2192ce4f568d5edfb0be2e4f2ac777e5610a481f3d0` |
| `x:en` | 2 | `f5da725a463074f9d8584ce4d5d0c1c04ae3658741250b3ce718219249ffda2a` | `b3bc6d76-5354-4fd6-b01f-75ce7bbf877b` | `export:a361308d-98a4-415b-9937-97cfa77d68f9:GJ2-DEVELOPMENT-A43hpY:export:x:en:v2` / `cdc18c8701bb3d3f388dbbfc4888d785501fe61aa789052ecff8e5312fbd490e` |
| `xiaohongshu:zh-CN` | 1 | `da61b8b2fd051f6ace6cbeefe2e22ce793db9cfd4cf31a87222b7bd0928c3d41` | `a75db2ab-a8ff-4e16-92ea-7ecd31ae5dcc` | `export:ccfc8687-32eb-4e17-b67e-9780759ca93a:GJ2-DEVELOPMENT-A43hpY:export:xiaohongshu:zh-CN:v1` / `75d83508ab7abc3a3d460882c63680467b21fefa55de19cfcf6a651ed8ab5472` |
| `wechat:zh-CN` | 1 | `e13be2a86b5f811321f89192f78288873786a9d54e90f64a3781058a8e09d336` | `4ad613a9-fcd0-4758-a380-1c5e55971117` | `export:df8d0f62-d34a-420b-a559-6271301c856c:GJ2-DEVELOPMENT-A43hpY:export:wechat:zh-CN:v1` / `014ea2c189e9bad3ed916f150403016612346b3a005880fdd7051b7db7cdb2f6` |

英文 v1 `7fe1c03f-8d54-4261-ad03-c21ad55639e0` 的 deterministic 检查通过、semantic fixture 因 `bilingual_meaning_drift` 拒绝；它没有 Approval 或 ExportRecord。英文 v2 随后独立通过两个质量类、批准与导出。四个 current 包合计 8 个 active PASS QualityResult、4 个 exact package Approval、4 个 ExportRecord 和 8 个内容寻址文件。

服务计划停止后以同一数据根重启并取得新 Session；API、数据库、依赖链、四个内容文件和四个 manifest 均精确 readback。restart-open 数据库为 schema v1、revision `61`、36 条记录、SHA-256 `a5fc39a65c67a455b7f65f249bf0825687fbe710aeb0bb8594797c89f47f2d28`。最终再次停止服务，`52447` 无 listener；`publications=[]` 且 `PublicationRecord=0`。最终报告首先指出到达 Owner 发布判断，推荐不公开并明确测试型 fixture 不等于编辑背书。

### 外部效果 readback 与严格判定

- source 最终仍为 clean exact commit；中文副本仍恰好 44 文件且 manifest 未变，代码修改、commit、push、remote、PR、部署和平台发布均为 0。既有源仓库 listener `127.0.0.1:4317` 仍为 PID `62719`，未被本任务停止或复用。
- v4 安装树仍为 67 文件、manifest `e2bbbf514e7d2821e732506320fa013d858f2030a16ce72c139653e1bb3a89ce`；未读取或迁移 v3/v4 业务数据。Codex `config.toml` 与 `auth.json` 最终 SHA-256 分别仍为 `e6939d175d6ccdc1db5512d519948658ed4e74ed972652b5947e2c018c804505`、`01679363d8ddb1357677ecafedbf59757368ad40a2a6f39a4191adf80b53f6fd`。
- owner-only 数据根保留供审阅：10 个 0700 目录、9 个 0600 文件、symlink 为 0。临时 v5 安装最终从 `/Users/peachy/.codex/skills/loopskill5` 可恢复地移动到 `/Users/peachy/.Trash/loopskill5-development-install-A43hpY`；安装目标已不存在，备份仍是上述两个 exact blob，v4 未动。
- 业务执行没有调用外部工作流、平台或网络工具；但 Codex Host 本身存在模型控制面流量，并观察到一次失败的插件目录预热，因此不主张系统级网络为 0。
- 从唯一 START 到最终消息 `2026-08-02T13:10:49.573Z` 实际约 `20 分 58.4 秒`，超过合同“保守约 15 分钟”的无人值守预期。无人值守仍成立，但合同的时长预测不准确。
- 本身份只对四个 exact version 各执行一次导出。Phase 0 GJ-2 规格中的“重复导出返回相同逻辑结果和 manifest identity”没有逐项映射进本次 Launch Contract，START 因而没有真实发起第二次同版本导出。最终只有 4 个 ExportRecord 和 8 个内容文件，证明没有重复效果，但不能从幂等键设计或最终计数推定该漏项已通过。

因此本身份的准确结论是 **`OWNER_GATE_REACHED / GJ2_SPEC_INCOMPLETE`**，不得记为 GJ-2 PASS。它也不是连续第二次干净运行、全新正式安装、故障注入 canary 或 release candidate 证据。IB-08 仍缺等待/报告同源 effect fact 的真实用户表面回归；IB-11 仍缺运行中缩小范围与旧批准失效的原始冲突复现。

## GJ-2 exact repeated-export DEVELOPMENT 成功身份

### 身份、合同与一次 START

- business identity：`GJ2-DEVELOPMENT-scOpQp`；唯一 Codex task/thread：`019fc2a4-12b4-7c23-a84c-7fbcdb4ecbe5`。
- clean Skill candidate：`675cc9c437f8b1f25d8a826d898622b61acc88f1`；开发态安装的 `SKILL.md` SHA-256 为 `3637909ee48b58724b093652831078ebaec4d8cf3360599a22ead30fa79e9c85`，`agents/openai.yaml` SHA-256 为 `d46efb72a0309a53729499e90b2200e9f872bb6eeaba691c589c7108680a6740`，均与 candidate 匹配。显式 `$loopskill5` 实际加载再次成立；全局 description budget 下的隐式自然语言发现仍为未知。
- source 仍为只读 exact commit `74051fbaecced9feb326fe53bff43738fd439856`、tree `edb0729811c533b5a2539bbf39865097359dd789`；Git archive SHA-256 为 `87c3a36c66d3959842e818b04323ff0a4b938888d83e175d5572a4fd634b7bf7`。中文副本为 `/tmp/loopskill-v5-gj2.scOpQp/中文项目验证/nepha-content-os`，私有数据根为 `/tmp/loopskill-v5-gj2.scOpQp/private/nepha-data`。
- PREPARE 真实证明默认时钟下用同一个 HTTP 幂等键重复导出会因 `exportedAt` 漂移产生 `idempotency_conflict`；固定时钟注入被明确排除，源码未改。隔离 scratch 随后通过合同路线：首次四包 HTTP 导出与磁盘 readback，停服确认无 listener，现有 `ReleaseRuntime` 用四个新调用 key 实际第二次导出并返回 exact existing，关闭 writer，再以新 HTTP 进程和新 Session 完整 readback。首个 scratch 的一次 inline JavaScript `ReferenceError` 在产品断言前停止并保留为准备失败；新 scratch PASS 后才展示修正版合同。
- exact 12 项合同披露实际 Host 技术 sandbox 为 `danger-full-access`，同时把业务权能严格限制为 disposable archive、副本、owner-only data root、动态 loopback 与只读证据；更宽 Host 文件系统/网络能力不扩大业务授权。
- 外层于 `2026-08-02T13:59:15.977776Z` 发起 exact resume 调用；child session 于 `14:00:24.311Z` 记录唯一独立用户消息 `START`，最终业务报告于 `14:13:39.139Z` 产生，task 于 `14:13:39.535Z` 完成。以 child 持久化 START 计时为 `795.224` 秒（`13 分 15.224 秒`）；Host 另报告本 turn `duration_ms=860897`。START 后 outer technical messages 为 `0`，没有继续、路径、端口、Store、内容、恢复提示、第二次 START、新 task、Goal、worker thread 或 heartbeat。

### 业务结果、真实重放与重启

固定输入以 exact SHA-256 `24590244fb4cbe71099e8d417751c0933ddcd1ed956bf4fa4ed2650675f33025` 持久化并 readback。真实 API 完成 intake/provenance、Evidence、Claim Ledger、topic selection、PerspectiveBrief fixture confirmation、MasterDraft、四个独立包、质量、exact-version fixture approval 与首次导出。项目 ID 为 `web-ca3324cc7c759fa9b0deb0cbe4274df8`；PerspectiveBrief v1 digest 为 `5d50ecb104dbff0f5c6d1f0e310707d83863b25e315622817a19270c751bb931`，MasterDraft v1 digest 为 `8885aa8a34e9ec36edb691d0386ad17ff9773d276049b94cd80afbf81d8d476a`。英文 v1 真实以 `bilingual_meaning_drift` 失败且无批准/导出；exact 英文 fixture 形成独立 v2，250 codepoints，文本 SHA-256 为 `3bb0ac8c9fa69afadfec91a0219b3889e229bc782b02d4c2e8f04dd00cd0fb9e`。

| current 包 | version | package digest | exact Approval | exact ExportRecord / manifest SHA-256 |
| --- | ---: | --- | --- | --- |
| `x:zh-CN` | 1 | `0e4557613d798e9405b4c1b1f635d6b6ae94f8c7ba842c4a81a686ad8b2018c9` | `2567873d-e847-49b0-a03d-6f76d895d7c9` | `export:2c3a65be-2a4e-4bbd-a4ea-ec414b4b5b17:GJ2-DEVELOPMENT-scOpQp:http-export:x:zh-CN:v1` / `2e09a3f93dbe9ddcf34044c4937345aad5d20fab545555c5e9b1c9f9fd87aea1` |
| `x:en` | 2 | `69c76c76bfc9a92b977ee7be1afd885a07821a98a11991c70370ebbd63320ce5` | `72a9a124-9a54-49bc-8ec5-4405786d87fc` | `export:5399a75b-c4f2-4eec-8eb5-e675fda70a69:GJ2-DEVELOPMENT-scOpQp:http-export:x:en:v2` / `9a95d85e34672f1be6244dabdb21df3fd406226cd8ad9241ad3b78bda72050ef` |
| `xiaohongshu:zh-CN` | 1 | `a0d8a5ee9d883a019f3d2f5c364124796f5b14b09537b1c88b1a0ba15bc39909` | `9c5859ce-6292-4f58-a980-f09740a3cf50` | `export:8eb776a6-983d-4a52-9ae0-c5b00b440825:GJ2-DEVELOPMENT-scOpQp:http-export:xiaohongshu:zh-CN:v1` / `06c358d7cbca2b5b84ca72a5596d9d0dc5507bc2e4f646d31161471c0eb5456b` |
| `wechat:zh-CN` | 1 | `bef0c723fe1c70590ae19aeda6aec098051a072a126c0f2e3146548cd4fa3b24` | `d13cb7f0-29ed-495f-9464-96b1a1f04d0b` | `export:af34542c-06a3-4cc9-9bdd-77da9e1a4752:GJ2-DEVELOPMENT-scOpQp:http-export:wechat:zh-CN:v1` / `bf36a82a46b296deefc628b0467dc780af3824c58433d3a834693ed8393e6225` |

- 首个真实 HTTP writer 为 PID `44037`、`127.0.0.1:65364`。四个首次导出均逐包核对实际 content/manifest bytes、文件 ID、SHA 与 package digest；随后进程退出，端口无 listener 且连接拒绝。
- 单一 `ReleaseRuntime` writer 为 PID `44066`。它对同一 data root 以四个不同于首次 HTTP 的新 key 实际调用 export；四次均返回上表原 `ExportRecord` ID、package digest、manifest file ID 与 manifest SHA。writer 关闭后 `ExportRecord=4`、内容寻址文件 `=8`、`JobRun=0`、`PublicationRecord=0`；排除 Store-open meta 字段后的逻辑状态 SHA-256 前后均为 `d80a973d625a5e2e033e83d32ac8eb7c2d8c41c8f5ba679b6a9c312da0958a50`。
- 重启 HTTP writer 为新 PID `44067`、新端口 `65386`，签发不同的新 Session/Cookie/CSRF；完整 API 与磁盘 readback 后停止。最终三个 writer PID 均不存在，两个 GJ-2 端口均无 listener，data root 没有 open file。

### 外层最终 readback 与严格判定

- `database.json` owner/mode 为当前 uid/0600，SHA-256 为 `47838b5a75558539aee4e4fffb8d083fa6099b3f9567d8e3f6995de6f66822b8`；data root 与 `files/` 均为 0700。外层独立读取到 `ExportRecord=4`、`JobRun=0`、`PublicationRecord=0` 和恰好 8 个文件，8 个文件内容 SHA 均与其内容寻址文件名一致。
- source 最终仍 clean exact commit；排除其既有 ignored `.nepha-data` 后，中文 archive 副本 44 文件与 source 逐字节无差异。既有 source listener `127.0.0.1:4317` 仍为 PID `62719`，未被复用或停止。没有源写入、v3/v4 数据访问、auth/config 改动、外部工作流或平台访问、secret、付费效果、commit、push、部署、publication 或删除。
- 任务业务工具网络效果只有合同内动态 loopback。Codex Host 控制面/模型和其他系统流量可能存在，本身份不主张系统级 network 为零；`danger-full-access` 也不扩大业务权能。
- 临时 v5 安装已从 `/Users/peachy/.codex/skills/loopskill5` 可恢复地移动到 `/Users/peachy/.Trash/loopskill5-development-install-scOpQp`；安装目标不存在，废纸篓中的两个文件 SHA 仍与 candidate 精确匹配。v4 安装树移动前后聚合 SHA-256 均为 `6cb22d41d9326b962ce45263b9803b1436eb7aaf7d3ea160d3da2307abb3243f`。
- 最终业务状态是 `OWNER_GATE_REACHED`，推荐不公开；没有发布调用或虚假 `PublicationRecord`。准确分类为 **`OWNER_GATE_REACHED / GJ2_DEVELOPMENT_PASS`**。

本身份闭合 Phase-0 GJ-2 基础 DEVELOPMENT 路径以及 A43hpY 漏掉的真实 repeated-export acceptance，但不是冻结 release candidate 上的连续第二次全新干净环境、故障注入 canary、48 小时/多日耐久或正式发布证据。IB-08 没有因本次无等待旅程而闭合；IB-11 仍缺运行中 Owner 跳过 Telegram/缩小范围、旧批准失效和最终主张降格的原始冲突复现。

## 实际 Skill 表面的 GJ-3 DEVELOPMENT 失败身份

### 身份与 PREPARE 偏差

- business identity 永久固定为 `GJ3-DEVELOPMENT-SURFACE-Y58h8e`；唯一业务 task/thread 为 `019fc1d7-b776-7583-a5c8-cdea92f7e458`。disposable workspace 为 `/tmp/loopskill-v5-gj3-surface.Y58h8e/workspace`，baseline HEAD `1f33b3d906a29a5eb66858eed2f225cb731d0f31`，remote 为空。
- nested Host PREPARE 表面没有受支持的 heartbeat 写入口，却越界创建了三个被禁止的 subagent：`workspace_audit` / `019fc2de-d52d-7153-bbe7-b2488fad9797`、`host_heartbeat_audit` / `019fc2de-f4be-7be2-85cc-b805b1fc950c`、`gj3_crosscheck` / `019fc2df-1b15-7c91-aaac-c1bb91a44b49`。父 PREPARE 中断后精确进程 readback 均无残留；已完成者报告零写入、零 heartbeat、零外网，未完成者没有可判定业务效果。该范围偏差保留，不改写为产品机制。
- 同一 PREPARE 改绑 Desktop 原生 automation 后只创建 heartbeat `loopskill-v5-gj3-surface-y58h8e`。create 请求携带 `PAUSED`，但 Host 于 `2026-08-02T14:39:51.647Z` 实际持久化为 `ACTIVE`；监督在 START 前于 `14:40:44.679Z` 用同一受支持 API、同一 identity 自动纠正为 `PAUSED`。这段 `53.032s` 窗口没有该 heartbeat 的新 turn 或业务效果。后续 readback 的持久化 target 精确为上述同一 thread，identity 数量始终为 `1`。

### START、同线程投递与已知效果

- session JSONL 于 `2026-08-02T14:49:23.810Z` 持久化唯一独立 `START`；准入复核后的 effect fact 另记录 `START observed at=14:50:02.616Z`。A readback 后，唯一 owner-only fact 于 `14:50:23.714Z` 形成，`not_before=14:53:23.714Z`、`latest acceptance=14:55:23.714Z`，初始 SHA-256 为 `680021732f2d9a26d21518e4cfcc071aff32b649c2a31cd5e647eae8a84d99ac`。
- artifact A 为 195 bytes（含末尾 LF），effect key `GJ3-DEVELOPMENT-SURFACE-Y58h8e:artifact-A:v1`，写入次数 `1`，SHA-256 `262bd923cbfcdcaa6b72d1de06376ea6120e0d4291dab0afc71ce8973a26c6ac`。`2026-08-02T14:53:18.033Z` 的首次同线程 delivery 比 `not_before` 早 `5.681s`，该 turn readback fact/A 后零写入结束，B 仍为 `0`，同一 heartbeat 保留。
- 第二次 Host-native same-thread delivery 为 `2026-08-02T14:54:48.047Z`，进入时仍在合同窗口内，但距最终完成上限只剩 `35.667s`。artifact B 的 birth/mtime 为 `14:55:44Z`，从 delivery 到效果约 `55.953s`，比 `latest acceptance` 晚约 `20.286s`。B 为已知单次效果：304 bytes、effect key `GJ3-DEVELOPMENT-SURFACE-Y58h8e:artifact-B:v1`、写入次数 `1`、SHA-256 `0346d7ca4d8f26aa7a7bf98e3361267e77609e6ef2ee25b1cb07444f55133748`；它正确引用 A digest，但按时业务效果没有完成。
- 同一 fact 追加 terminal emergency-stop readback 后仍为 uid 501 / mode 0600，最终 SHA-256 为 `8cc83ebec4c10cfa8119b020c49e5135494027127b15cf8b60527b6ab5bee06a`。A/B 均保留且各出现一次；workspace HEAD 未变、remote 为空、Git status 仅 A/B。唯一 heartbeat 已通过受支持 API 删除，automation 文件、identity 搜索和匹配进程 readback 均为不存在。
- 从唯一 START 到 terminal stop，外层技术消息为 `0`；除两次 Host heartbeat delivery 外没有第二次 START、继续指令、路径、恢复提示或新 task。任务业务工具没有调用网络、commit、push、publication 或发布接口；Codex Host 必需模型/控制面流量不在“业务网络为 0”的主张内。

### 严格判定与最窄根因

本身份永久分类为 **`DEVELOPMENT FAIL / LATE_EFFECT_AFTER_ACCEPTANCE_WINDOW`**。B 的 bytes 与 digest 正确不能覆盖时长 Gate；不得重试、删除 B、改判、复活或把该身份写成 IB-08/GJ-3 PASS。它也不证明 48 小时、多日、OS 关机恢复或任意 task crash recovery，IB-08 仍保持未闭合。

最窄根因是 Launch Contract 容量预算不足：300 秒总完成窗把前 180 秒全部分配给 `not_before`，首次早醒又占用一次 Host cadence；合格 delivery 到来时只剩 `35.667s`，而同源 fact/A readback 与 B 业务写入实际约需 `55.953s`。因此“唤醒在截止前开始”不等于“业务效果在截止前完成”。修正应在 START 前用真实探测为 Host 调度/投递和醒后 verifier/业务执行预留明确预算，不需要 Controller、retry、状态机、schema 或新恢复层。

## 实际 Skill 表面的第二个 GJ-3 DEVELOPMENT 失败身份

### 不可变身份、时间与效果 readback

- business identity 永久固定为 `GJ3-DEVELOPMENT-SURFACE-NKxcK6`，task/thread 仍为 `019fc1d7-b776-7583-a5c8-cdea92f7e458`。唯一 owner-only fact 形成于 `2026-08-02T15:25:02.321Z`，`not_before=15:27:02.321Z`；内部容量预测另写为 `latest Host delivery=15:29:02.321Z`，真正业务 effect deadline 为 `15:30:32.321Z`，final completion deadline 为 `15:33:02.321Z`。
- Host 在 `15:28:22.477Z` 实际原生投递同一 thread，早于内部预测的 latest delivery `39.844s`。wake 热路径的 pre-effect validation 到 `15:29:34.047Z` 才完成；此时 B 仍不存在，但距真正业务 effect deadline 仍有 `58.274s`。
- artifact A 保持 195 bytes（含末尾 LF）、effect key `GJ3-DEVELOPMENT-SURFACE-NKxcK6:artifact-A:v1`、effect count `1`，SHA-256 精确为 `62abab106dbc2446dbd62d151d1a25f204e3ee668ef37fdfed61c59917f7a89c`；artifact B 从未创建，effect count 为 `0`。workspace 仍为 unborn `main`、commit count `0`、remote 为空、Git status 仅 `?? artifact-A.txt`。
- 唯一 0600 fact 追加失败终态后 SHA-256 为 `df01a4f04069489430e6ed1dadd8db42bab2f231540262073858264938738ebb`。唯一 heartbeat `loopskill-v5-gj3-surface-nkxck6` 已由受支持 API 删除；automation 目录与 identity 搜索均回读为不存在，不会再次投递。
- START 后外层技术消息为 `0`。任务业务工具的 network、commit、push、publication 与 deploy 效果均为 `0`；这不包含 Codex Host 必需的模型/控制面流量，也不主张系统级 network 为零。

### 同一 START 内部自恢复与最窄根因

- START 准入第一次通过自由 PATH 调用 `find`、`sort`、`tr` 与 `ps` 时得到 `command not found`；在任何业务写入和 heartbeat 创建前，系统改用 `/usr/bin/find`、`/usr/bin/sort`、`/usr/bin/tr` 与 `/bin/ps` 完成同一只读复核。heartbeat 第一次 create 又因 API 不接受显式 `id` 参数而零持久化效果拒绝；系统移除该不支持参数后创建并实际 readback 同一约定 identity。两项技术故障都在同一 START 内自主闭合，没有外层提示、第二次 START、第二 heartbeat 或新 task。
- 真正根因不是所有时限都应扩大。heartbeat prompt step 5 在 identity、目录、fact、heartbeat、Git 与 A 的重复 readback 之后，拿当时机器时间比较内部 `latest Host delivery` 预测，并把预测升级为新的硬停止。真实 delivery 已在预计窗内，`not_before` 已满足，B 的业务 deadline 尚未到；重复 verifier 又让 delivery 到 validation 耗时 `71.570s`。这是内部技术里程碑冒充业务 Gate 与 wake 热路径过度验证的组合失败，不需要 Controller、retry、状态机、schema、scheduler 或 wrapper。

本身份永久分类为 **`DEVELOPMENT FAIL`**，已知效果固定为 **A=1/B=0**；不得补写 B、重试、改判、复活或把它写成 IB-08/GJ-3 PASS。后续语义只要求 turn 入口先捕获真实 `delivery_observed_at`，将 Host cadence/phase 估算保留为 START 前容量规划，并在运行期只执行已承诺的 `not_before`、真实业务 effect deadline 与 final completion deadline。

## 实际 Skill 表面的 GJ-3 DEVELOPMENT 成功身份

### 身份、唯一 START 与三项时间

- business identity 为 `GJ3-DEVELOPMENT-SURFACE-Bd6HN0`，唯一 task/thread 为 `019fc1d7-b776-7583-a5c8-cdea92f7e458`；disposable workspace 为 `/tmp/loopskill-v5-gj3-surface.Bd6HN0/workspace`，private root 为同 identity 下的 `private`。唯一 START user event 为 `2026-08-02T15:48:54.450Z`。
- A exact readback 后，唯一 owner-only effect fact 于 `15:50:11.331Z` 形成，`not_before=15:52:11.331Z`、B 业务效果截止 `15:55:41.331Z`、final completion deadline `15:58:11.331Z`。合同和事实没有 `latest Host delivery` 或其他内部阶段硬 Gate。
- 唯一 heartbeat `loopskill-v5-gj3-surface-bd6hn0` 实际持久化为 ACTIVE，target 精确为上述同一 thread。START 后原 turn 结束；没有新 task、第二 heartbeat、Controller、daemon、queue、retry、状态机或 schema。

### 同线程 reentry、业务效果与终局 readback

- Host heartbeat user event 与入口即捕获的 `delivery_observed_at` 均为 `2026-08-02T15:52:22.611Z`，比 `not_before` 晚 `11.280s`。wake 热路径只 readback identity/thread、owner/mode/non-symlink、单一 fact、实际 heartbeat target/status、A exact、B 不存在及 Git commit/remote/status；没有复核固定 inode/dev、`.git/config` digest、candidate blob 或全量 automation。
- artifact A 为 195 bytes（含末尾 LF），effect key `GJ3-DEVELOPMENT-SURFACE-Bd6HN0:artifact-A:v1`，SHA-256 为 `60087bbb84f3740167312e421a611eadf31c7e3e80cd89a9b8b2448f71010c35`。A 从等待前到最终 readback 始终为 effect count `1`，没有重写。
- artifact B 于 `15:52:58.834Z` 写入一次，距 delivery `36.223s`，比 B 业务效果截止早 `162.497s`；`15:53:14Z` 完成真实 readback。B 为 304 bytes（含末尾 LF），effect key `GJ3-DEVELOPMENT-SURFACE-Bd6HN0:artifact-B:v1`，SHA-256 为 `8489b4c4d66b82c865c89efe64e2861095405a5eb43a7f74d24169dae96e4d7a`，并引用 A exact digest；effect count 为 `1`。
- 唯一 heartbeat 于 `15:54:05Z` 由受支持 Desktop API 删除，supported view 与 exact local path 均确认不存在。最终 verifier readback 于 `15:54:35.775Z` 开始并在 final deadline 前通过；随后 final heartbeat message 完成并明确报告 DEVELOPMENT PASS。
- final fact 仍为 uid 501 / mode 0600，SHA-256 为 `9e7a47ef2ec2ba776dc656270bab3b3b4aacc13b13510af55bc7ae6fc482f35b`；A/B effect count 各为 `1`。Git 仍为 unborn `main`、commit count `0`、remote 为空，status 仅 `?? artifact-A.txt` 与 `?? artifact-B.txt`。
- 从唯一 START 到 final message，用户输入只有该 START 与 Host-native heartbeat user event，外层技术消息为 `0`。任务业务工具的 network、secrets、commit、push、PR、publication 与 deploy 效果均为 `0`；Codex Host 必需的模型/控制面流量不在该业务网络主张内，也不主张系统级 network 为零。

### 因果边界与严格判定

本次 PASS 的直接因果是：删去伪 `latest Host delivery` Gate，在 turn 入口、任何 verifier 前先捕获真实 delivery，并把 wake 热路径缩到安全续接所需的最少 readback；运行期只执行 `not_before`、B 业务效果截止和 final completion deadline。成功没有依赖 Controller、retry、状态机、schema、第二 task 或第二 heartbeat。

因此 `GJ3-DEVELOPMENT-SURFACE-Bd6HN0` 准确分类为 **`GJ3 DEVELOPMENT PASS`**，闭合实际 `$loopskill5` 表面的 GJ-3 基础 DEVELOPMENT 路径。它不覆盖或改判 `GJ3-DEVELOPMENT-SURFACE-Y58h8e` 与 `GJ3-DEVELOPMENT-SURFACE-NKxcK6`：前两者继续永久保持各自 FAIL 与原始效果；本 PASS 也不证明 48 小时、多日、跨自然日、睡眠、OS 关机或任意 task crash recovery。

IB-08 只获得“单一 effect fact 驱动等待说明、same-thread wake 和最终报告”的直接支持；v5 仍没有 PAUSED/Active 用户投影，也没有复现“权威执行已 PAUSED、用户状态仍显示 Active”的原始冲突输入，因此该事故仍未完全闭合，不得记为 IB-08 PASS。
