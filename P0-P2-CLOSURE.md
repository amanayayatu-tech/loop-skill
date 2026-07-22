# LoopSkill P0-P2 closure matrix

This matrix records claim level separately from code, local tests, App canary,
GitHub CI, and merge evidence. It is updated at each stage and never upgrades a
failed or unrun lane into a pass.

| Stage | Requirement | Product status | Local evidence | App evidence | GitHub / merge | Remaining gate |
|---|---|---|---|---|---|---|
| P0 | Trustworthy long-loop startup, recovery, rejection journal, conditional host identity, Git closeout, policy migration, completion classes, lifecycle recovery | `PRODUCT_DONE` | P0 full suite, dual fuzz, and coverage passed on the P0 candidate | Fresh clean-precondition disposable canary reached exact `FINALIZATION_ACKED`; the earlier contaminated harness remains negative evidence | PR #29 merged as `18cc705` | None |
| P1 | Defect families, Reviewer disclosure/escalation, route orchestration, heartbeat registry, Supervisor capability, measurement/export, model canary, Goal registry, recovery coverage | `PRODUCT_DONE` | 754-test inventory, affected shards, dual 5000 fuzz and 80.008125% canonical branch coverage passed | Not required; no installed Skill replacement and no App restart | PR #30 merged as `a144d0f` with all required CI jobs green | None |
| P2 | Content-addressed storage, audit UX, recovery templates, scanner, CLI convergence, CI telemetry/shadow replay, active/history split, archive v2 | `PRODUCT_DONE` | Canonical inventory is 765; targeted security/recovery tests, four canonical shards, dual 5000 fuzz, branch coverage, and isolated Linux/macOS installs are required | Not required; isolated install only, no active Skill replacement or App restart | PR #31 is the integration record and may merge only with its exact-SHA final gate green and review threads resolved | None after PR #31 satisfies the stated merge gate |

P1 defaults do not require a concrete model identity. Strict model/reasoning
identity remains opt-in and fails closed when the host cannot provide a
non-agent-authored carrier.
