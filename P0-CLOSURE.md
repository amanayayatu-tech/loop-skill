# P0 closure matrix

This matrix separates product implementation, local verification, real Codex
App evidence, and the remaining host boundary. The evaluated product candidate
is the exact Git HEAD named in the PR and final verification receipt; test
reuse is additionally bound to the recorded implementation and test tree digests.

| ID | Requirement | Product implementation | Targeted verification | Real canary lane | Status | Minimum remaining action |
|---|---|---|---|---|---|---|
| P0-1 | Startup compiler, doctor, and disposable full-chain canary | `scripts/loopctl`, installer, compiler/canary schemas | doctor/install tests, canary receipt validation | Attempts 1-4 preserved; attempt 4 passed preflight and initialization under the former unconditional identity policy | PRODUCT_DONE | Run the single final fresh full-chain canary with the default unspecified-model policy |
| P0-2 | Every recoverable state has one legal recovery operation | generated recovery registry and structured recovery envelopes | registry source enumeration and `RecoveryRegistryTests` | Attempt 4 rejection returned `RESUBMIT_CORRECTED_REQUEST` without canonical mutation | PRODUCT_DONE | Keep registry enumeration as a required gate |
| P0-3 | Append-only rejection journal | hash-chained, fsynced `LOOP_REJECTIONS.jsonl` and unified audit | concurrency, crash, tamper, privacy, and write-failure tests | Attempt 4's `REGISTER_TASK` failed at the MCP boundary before runtime, so it is negative receipt evidence but not a journal append | PRODUCT_DONE | Exercise one runtime rejection and unified audit in the final canary |
| P0-4 | Conditional model/reasoning identity guarantee | default `NOT_REQUIRED`/`NOT_APPLICABLE` policy plus opt-in strict App carrier, exact binding, replay rejection, and fail-closed path | unspecified-model continuation, strict missing-carrier, false `APP_SIGNED`, mismatch and replay tests | Attempt 4 remains negative evidence for strict identity mode; it does not block a default unspecified-model Loop | PRODUCT_DONE | Prove the default path in the final canary; strict mode remains `HOST_BLOCKED` on hosts without the carrier |
| P0-5 | Canonical/Git/artifact/commit-push closeout saga | prepare/ack closeout, HEAD/path/ref locks, original outbox recovery | drift, crash-after-commit/push, replay, and remote-ref tests | Not reached in attempt 4 because P0-4 stopped first | PRODUCT_DONE | Exercise once in the final canary |
| P0-6 | Generic historical policy migration | schema-driven bounded/monotonic migration with retained history | legacy 2-to-5, generic 5-to-20, bounds, stale source, rollback/stop tests | Not required before the role gate | PRODUCT_DONE | No repair-budget reimplementation |
| P0-7 | Workflow state separate from evidence completion class | completion classes and `status-v5` projections | legacy migration, limitation, and receipt-gated empirical/formal/public tests | Not reached in attempt 4 | PRODUCT_DONE | Confirm final status and evidence class in the final canary |
| P0-8 | Host MCP lifecycle recovery/readback | `host_lifecycle_readback` with install/restart/reconnect/schema/App identities and dispatcher counts | lifecycle supported/unsupported, drift, active-call, and identity mismatch tests | Attempt 4 independently returned all five lanes `SUPPORTED` with zero before/after counts | CANARY_PROVEN | Preserve receipt in the final canary; no watchdog or agent self-restart |

## Conditional host receipt boundary

The default policy does not request a model/reasoning receipt and stores those
identities as `UNSPECIFIED`; artifact, review, recovery, closeout, lifecycle,
and finalization gates remain mandatory. If a caller explicitly requires a
model or reasoning level, the product accepts a host-cooperative receipt only from App-injected
top-level MCP metadata, never from tool arguments. The carrier must be bound to
the current Controller thread and turn and contain an exact
`THREAD_CREATE_OR_READ` result. A missing carrier, extra field, wrong action,
cross-turn value, task mismatch, role/model/reasoning/App-build mismatch, or
replayed task identity fails with zero canonical side effects.

Reading a same-user mutable Codex SQLite database and hashing a row is not an
App signature and is not a supported fallback. The private store path, schema,
WAL behavior, and retention policy are not a public compatibility contract.
Accordingly strict model-identity acceptance remains blocked until the host
exposes the receipt carrier. Default P0 acceptance is not blocked by an
unrequested guarantee, but still requires a fresh canary to reach the actual
`FINALIZATION_ACKED` terminal state.
