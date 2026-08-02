# LoopSkill 5.0 历史事故行为语料

本语料只定义 5.0 必须表现出的行为。产品条款以 [`../loopskill-5.0-master-plan.zh-CN.md`](../loopskill-5.0-master-plan.zh-CN.md) 为唯一事实源；此文件不继承 v4.3 的实现、Plan、状态、命令或 schema。

## 证据等级

| 等级 | 含义 |
| --- | --- |
| `A` | 当前可读取的固定 Git 字节或可直接复现的真实行为。 |
| `B` | Owner 已确认并写入主计划的真实事故记录；当前阶段未必持有原始运行日志。 |
| `C` | v4.3 只读脏工作树中的拟议回归或实现草稿；未在 exact clean candidate 上执行，不是 PASS。 |
| `U` | 原始证据当前不可得；必须保留未知并在后续 Phase 建立确定性复现，不能补写故事。 |

固定证据身份：

- `E-MASTER`：主计划 SHA-256 `69e88ed2b543033c12bf74bc753092b8e66316b8fc5759f765633792c3a13bb1`，第 14 节为 Owner 批准的事故行为表。
- `E-V43-REG`：只读 v4.3 `test_v4_3_incident_regressions.py` SHA-256 `fb2e13320c0eeb614b8abd07868815f74692d2911934e0c171101bea7365077d`；它是未提交草稿。
- `E-V43-RECOVERY`：只读 v4.3 deterministic runner SHA-256 `84c1f4144ce5bde77156db545f86ba08bbcf4b5a63f608a76966f275e1a83b0b`；其文件自述“不是 Host 可用性证明”。
- `E-NEPHA-501`：Nepha commit `a3b57ecea7e7e2f6e000820b06e7c895efd4a84b` 的 `src/server.js` blob `91309979c83be3192d62387e5e1825cbedfe5bf6` 明确返回 501；同 commit 的 `test/server.test.js` blob `756c2b45c8bc532cf1c7d6c4ee9a350ddbe5662c` 只覆盖 GET/Host 安全路径。
- `E-V4-SAFETY`：基线 `SPEC.md` blob `594c6e7c514c74135b4598a92b74239b831afe38` 与 `SECURITY.md` blob `84f97b99d454cb8987649e63781ec4f74da85e2a`，仅保留 UNKNOWN、秘密、证据不可改写和真实旧字节验证等安全行为。

## 行为案例

| ID | 历史输入或触发 | 5.0 必须有的行为 | 失败分类 | 证据 |
| --- | --- | --- | --- | --- |
| `IB-01` | 在常见 `umask 022` 下创建私有 Store，历史结果为 `0755` | PREPARE 真实创建并验证 owner-only 目录，或在零运行/零外部效果下拒绝 START；不得在 START 后让用户 `chmod` | 错误准入 / 隐私边界 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-02` | 验证声明的自定义 `env` 为空，但任务需要 `node`/`npm` | 用已验证的安全基础环境解析 executable 并做真实探针；自定义 env 为空不等于删除安全 PATH；失败不得消耗业务 Worker | 错误准入 / 能力归责 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-03` | executable 在 PREPARE 时缺失，或 PREPARE 后字节/身份漂移 | 缺失时阻断合同；漂移时 START 前复核并以零 Store、零 Host、零业务副作用拒绝，回到准备 | 错误准入 / 准备陈旧 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-04` | 文件在 START 前已经存在，却被“本次 transition 创建文件”语义判定为不存在 | 合同明确区分“工作区现有事实”和“本次 transition 变化”；按用户真正验收对象选择语义，不得把 verifier 名称误当业务真相 | 语义错误 / 虚假失败 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-05` | 端口已占用、listener 无权限，或预检后发生绑定竞态 | START 前探针；竞态发生后在授权 scratch 内换临时端口或重建 verifier，复用已完成业务结果，不再次调用 Worker；无法安全恢复才紧急停止 | 技术恢复失败 / 错误归责 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-06` | nested Codex 看似可用，真实调用却不能写目标状态或工作区 | 合同前执行与承诺相同权限/目录/模式的能力探针；不能只相信 capability flag。不可用则降低承诺或拒绝 START | Host 能力误报 / 错误准入 | `B:E-MASTER`；后续需 `A` 级 Host spike |
| `IB-07` | Controller/Verifier 自身故障被算作 Worker attempt/repair | 把控制面故障留在内部恢复范围；已完成 Worker 结果保持可验证，业务调用和修复预算不增加 | 故障归责错误 / 可避免早停 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-08` | 权威执行已 PAUSED，用户状态仍显示 Active | 一份权威进度/效果事实驱动所有用户投影；冲突时显示冲突并禁止更高完成主张 | 状态失真 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-09` | verifier/runtime 把数据、缓存或进程文件写入源码 | 默认使用合同绑定的私有 scratch；运行前后核对允许写范围和源树，任何未声明污染均使旅程失败 | 环境污染 / 未授权写入 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-10` | 一个宽 Goal 内出现多个独立故障，用户被要求建 successor | 在同一最终意图和业务身份内自行分段、修复和重新规划；内部工作段不是人类 Gate | 自治失败 / 技术性人工介入 | `B:E-MASTER` |
| `IB-11` | Owner 合法跳过 Telegram 或缩小范围，只能通过 successor 继续 | 在原业务身份中绑定新决定，失效旧批准上下文，继续未变范围；最终主张准确降格且历史决定保留 | Gate 处理失败 / 身份洗白风险 | `B:E-MASTER`；`C:E-V43-REG` |
| `IB-12` | 单元/页面测试全绿，但真实 `POST /api/intake` 返回 501 | 发布主张前执行从真实输入到业务 readback 的关键旅程；501 必须使该业务旅程 FAIL，静态 artifact 或其他测试不能覆盖它 | 黄金旅程缺失 / 虚假 PASS | `A:E-NEPHA-501`；`B:E-MASTER` |
| `IB-13` | 300 秒观察窗口实际终止仍在承诺时长内的任务 | 观察窗口不得拥有任务终止权；自然等待持久化后退出占用，通过已验证 Host 唤醒/续接同一业务身份；发布前需真实跨日证据 | 持续运行语义错误 | `B:E-MASTER`；原始 300 秒日志当前为 `U` |
| `IB-14` | 构造型升级测试通过，真实旧安装字节升级失败 | 测试必须从公开旧 tag/真实安装器字节建立环境。v5 首发不承诺迁移：应验证与真实 v3/v4 安装和数据原样并存、v5 安装/卸载不触碰旧身份；不得把“未测试迁移”写成升级 PASS | 发布回归失真 / 旧数据风险 | `B:E-MASTER`；`A` 级旧 tag 字节在 Phase 5 验证 |

## 所有案例共同断言

1. 普通用户不填写 JSON、内部 ID、digest、状态或恢复命令。
2. START 后技术性人工介入为 `0`；任何一次都使该运行 FAIL。
3. 不能通过缩短承诺结果或提前 Gate 把事故变成成功。
4. 不确定外部效果保持 `UNKNOWN`，禁止盲目重发；同一失败身份和证据不可改判或复活。
5. 预先存在的用户脏改动逐字节保留；写入只发生在合同范围。
6. 秘密不进入合同、Prompt、日志、artifact、测试 fixture 或公开报告；发现真实秘密时停止保留并要求轮换。
7. 每个回归必须同时断言业务结果、技术介入次数、外部效果次数和实际停止层，不能只断言状态字段。

## 后续执行规则

Phase 2 只为首条 walking skeleton 当前出现的失败实现最窄机制。Phase 3 再把本表转成确定性回归；若某条缺少 `A` 级复现，测试必须标记证据缺口而不是预期 PASS。正式/发布运行失败后保留原 identity，修根因并使用新 candidate/run identity。
