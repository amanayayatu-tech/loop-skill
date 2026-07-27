# LoopSkill 4 local-candidate quickstart

Status: isolated RC acceptance only. It is not released, not installed over the
current user environment, and not authorized to migrate a real v3 loop.

## Normal user path

Create one UTF-8 JSON file containing semantic requirements only. Do not enter
thread, task, route, effect, artifact, review, finalization, receipt, SHA,
schema, or Host-enum identities.

```json
{
  "goal": "Complete and verify one small change in a disposable example directory",
  "task_horizon": "long",
  "write_scope": ["disposable-example"],
  "budget": "20 minutes; no network or publish",
  "external_actions": [],
  "acceptance_criteria": ["focused tests pass", "result is independently reviewed"],
  "stop_conditions": ["stop on unknown external state"],
  "authorization_boundaries": ["no commit, push, publish, deploy, or real-user data"]
}
```

Run one main entry from the isolated installation:

```bash
loopskill4 start goal.json
```

The same interaction runs `INTAKE → PREPARE → CONFIRM → START`. Intake and
prepare have zero Host/execution effects. Confirm displays the Goal, write
scope, budget, external actions, acceptance criteria, stop conditions, and
publication boundary. Start accepts only an explicit confirmation bound to the
digest of every prepared artifact.

One main command means one entry, not silent authorization. A non-interactive
run stops after preparation and requests explicit confirmation.
`DIRECT_TASK_RECOMMENDED` creates no Loop.

The four phases can also be invoked separately:

```bash
loopskill4 intake goal.json
loopskill4 prepare goal.json --output /tmp/loopskill4-prepared
loopskill4 confirm /tmp/loopskill4-prepared
loopskill4 start /tmp/loopskill4-prepared --root /tmp/loopskill4-root
```

Normal status shows only Goal, progress, result, limitations, and next action.
Internal machine identity appears only with explicit `--diagnostics`.
`UNKNOWN` and `UNVERIFIABLE` are honest visible limitations and never trigger a
blind automatic resend.

Standard is the default bounded Goal Queue for a minimal long-running task.
Adaptive policy is loaded only after Intake explicitly selects it; users do
not need to install or understand a policy pack.
