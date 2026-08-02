# GJ-2：Nepha 核心业务旅程

## 最终意图

证明 LoopSkill 能在中文路径的干净副本中，把一份真实中文输入推进为有证据链、经测试型确认和批准、可导出且重启后可 readback 的 Nepha 文本包，并准确停在“是否公开发布”的最终 Owner Gate。

## 固定输入与边界

- 项目候选：Nepha Content OS exact commit `74051fbaecced9feb326fe53bff43738fd439856`，只通过 Git archive 复制，源仓库只读。
- 工作路径：一次性私有临时根下的中文目录，例如 `中文项目验证/nepha-content-os`。
- 输入为以下 exact UTF-8 Markdown（末尾一个 LF），SHA-256 `24590244fb4cbe71099e8d417751c0933ddcd1ed956bf4fa4ed2650675f33025`，目标输出为 X 中文、X 英文、小红书中文和微信公众号中文：

> 当 AI 能生成越来越多内容时，可靠工作流的竞争力不在生成速度，而在每个关键主张都能找到来源、观点经过本人确认、最终版本在发布前被审阅。本文只陈述流程原则，不声称真实运营数据。
- 旅程内的 Brief 确认和 Package 批准是固定 golden-fixture 决策，只证明流程与版本绑定，不代表 Owner 对真实公开内容背书。
- 最终 Gate：四个文本包导出并持久化 readback 后，由 Owner 决定是否公开发布；本旅程不调用发布接口、不创建虚假 PublicationRecord。

## START 前必须闭合

1. exact source commit、archive 能力、中文路径、源仓库状态和副本初始 tree digest。
2. Node `>=20`、npm、`verify:core-shippable`、Web workflow smoke、loopback listener、动态端口、scratch、数据目录和写权限。
3. Host 调用与 verifier 使用相同候选、副本和数据根；nested Codex 能力若未真实证明，不进入合同。
4. 允许写入仅为副本和私有 scratch/data；除本机 loopback 验收外，禁止源仓库、真实 Codex auth/config、Telegram、平台发布、Git remote 和外部网络写入。
5. 关键旅程验收不能由 `verify:core-shippable` 单独替代，必须实际调用 Web API 并在进程重启后 readback。

## 一次 START 后的真实路径

1. intake 保存原始输入和 provenance，创建候选主题。
2. 选择主题，生成 Claim Ledger 与 PerspectiveBrief；按固定 fixture 确认观点边界。
3. 生成 MasterDraft，再生成四个独立 PlatformPackage。
4. 对每个包运行质量检查；X 中英文分别版本化、检查和测试型批准。
5. 对四个已批准精确版本分别导出，重复导出返回相同逻辑结果和 manifest identity。
6. 停止服务并使用同一数据目录重启；readback 项目、版本、批准和四个 export manifest。
7. 输出最终业务报告并停在公开发布 Owner Gate。

## 通过事实

- 一次 START；技术性人工介入 `0`；不存在 PATH、端口、Store、scratch、Host 或 verifier 救场。
- 源仓库字节、状态、Codex auth/config 与 v3/v4 数据均不变；临时进程全部回收。
- 真实 API 路径完整经过主题、Brief、确认、Draft、四个包、质量、批准、导出和重启 readback。
- 四个 manifest identity 可验证；同版本重复导出不产生第二份逻辑内容。
- 未批准版本、未确认个人经历和秘密均未进入导出。
- 最终状态是准确的最终 Owner 发布 Gate，不把“测试型批准”或 artifact 写成公开发布。

发布候选上本旅程必须在两个全新干净环境连续通过；至少一次从全新 v5 安装开始，至少一次包含安全可恢复故障注入。旧失败 identity 永久保留。
