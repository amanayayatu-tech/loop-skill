# LoopSkill P0-P2 closure matrix

This matrix records claim level separately from code, local tests, App canary,
GitHub CI, and merge evidence. It is updated at each stage and never upgrades a
failed or unrun lane into a pass.

| Stage | Requirement | Product status | Local evidence | App evidence | GitHub / merge | Remaining gate |
|---|---|---|---|---|---|---|
| P0 | Trustworthy long-loop startup, recovery, rejection journal, conditional host identity, Git closeout, policy migration, completion classes, lifecycle recovery | `PRODUCT_DONE` | P0 full suite, dual fuzz, and coverage passed on the P0 candidate | Fresh clean-precondition disposable canary reached exact `FINALIZATION_ACKED`; the earlier contaminated harness remains negative evidence | PR #29 merged as `18cc705` | None |
| P1 | Defect families, Reviewer disclosure/escalation, route orchestration, heartbeat registry, Supervisor capability, measurement/export, model canary, Goal registry, recovery coverage | `PRODUCT_DONE_PENDING_PR_EVIDENCE` | Targeted module, compiler, Gateway integration, malformed-boundary, and recovery inventory tests | Not required; no installed Skill replacement and no App restart | Pending P1 PR CI and merge | Affected shards, PR CI, review, merge |
| P2 | Content-addressed storage, audit UX, recovery templates, scanner, CLI convergence, CI telemetry/shadow gate, active/history split, archive v2 | `OPEN` | Not run | Not required | Not started | Implement after P1 merge from latest main |

P1 defaults do not require a concrete model identity. Strict model/reasoning
identity remains opt-in and fails closed when the host cannot provide a
non-agent-authored carrier.
