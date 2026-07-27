# LoopSkill 4 本地候选快速开始

状态：仅供隔离 RC 验收；未发布、未安装到当前用户环境、未授权迁移真实 v3 loop。

## 普通用户路径

准备一个 UTF-8 JSON 文件，只写语义需求。用户不填写 thread、task、route、
effect、artifact、review、finalization、receipt、SHA、schema 或 Host enum。

```json
{
  "goal": "在 disposable 示例目录中完成并验证一个最小改动",
  "task_horizon": "long",
  "write_scope": ["disposable-example"],
  "budget": "20 minutes; no network or publish",
  "external_actions": [],
  "acceptance_criteria": ["focused tests pass", "result is independently reviewed"],
  "stop_conditions": ["stop on unknown external state"],
  "authorization_boundaries": ["no commit, push, publish, deploy, or real-user data"]
}
```

从隔离安装目录执行一次主入口：

规范阶段顺序是 `INTAKE → PREPARE → CONFIRM → START`。

```bash
loopskill4 start goal.json
```

同一交互依次执行：

1. `INTAKE` 只读质检；可能返回 `READY_FOR_LOOP`、
   `NEEDS_CLARIFICATION`、`BLOCKED` 或 `DIRECT_TASK_RECOMMENDED`。
2. `PREPARE` 写 typed manifest、人类计划、中文说明和边界摘要；不创建 Host task。
3. `CONFIRM` 展示 Goal、写入范围、预算、外部动作、验收、停止与发布边界。
4. 只有用户输入精确确认语句后，`START` 才消费绑定全部准备内容 digest 的确认。

“一次主命令”表示入口统一，不表示静默授权。非交互环境会停在准备结果，要求显式
确认。`DIRECT_TASK_RECOMMENDED` 不创建 Loop。

也可以逐步运行：

```bash
loopskill4 intake goal.json
loopskill4 prepare goal.json --output /tmp/loopskill4-prepared
loopskill4 confirm /tmp/loopskill4-prepared
loopskill4 start /tmp/loopskill4-prepared --root /tmp/loopskill4-root
```

普通状态只显示 Goal、进度、结果、限制和下一步。只有显式 `--diagnostics` 才显示
内部机器身份。外部结果为 `UNKNOWN` 或 `UNVERIFIABLE` 时，产品会显示限制并停止
自动重发，不会伪装成功。

Standard 是长期最小任务的默认有界 Goal Queue。只有 intake 明确选择 Adaptive 时
才加载可选 Adaptive policy；用户不需要安装或选择 policy pack。
