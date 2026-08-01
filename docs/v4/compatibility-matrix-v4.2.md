# LoopSkill 4.2 compatibility matrix

| Surface | v4.2 behavior |
|---|---|
| Runtime | macOS and Linux; Python 3.11–3.14; standard-library runtime |
| Plan | PlanDocument/PlanIndex v2, 1–128 Goals, 512 KiB canonical plan |
| Existing plans | Plan v1 remains readable and executable without rewriting |
| Store | v4.0/v4.1 single-Loop Stores remain read-only/queryable; new Stores are per Loop |
| Discovery | Rebuildable `list` view over canonical per-Loop SQLite Stores |
| Host | Official foreground `codex exec`; Plan v2 is non-ephemeral and session-bound |
| Attempt bound | 1–30000 seconds, set from one Plan worker profile |
| Recovery | Persistent terminal readback; one recorded same-session resume; local reconciliation or human wait when replay is unsafe |
| Verification | File, SHA-256, exact argv command, loopback HTTP, human, time, and optional capability evidence |
| Failure | Repair, waiting, skip-with-evidence, fail, or stop according to the confirmed Goal policy |
| Budgets | Host invocation and observed active-compute budgets checked before Host effects; positive cost budgets fail PREPARE until a trusted cost meter exists |
| Installation | Receipt-valid v4.1.1 upgrades transactionally; same-version install is a no-op; unknown drift fails closed |
| v3 | No import, migration, repair, or dual write; use the independent v3.3.8 release |

LoopSkill does not claim cross-system exactly-once delivery, unlimited background
execution, automatic product publication, arbitrary credential access, or
multi-host support.
