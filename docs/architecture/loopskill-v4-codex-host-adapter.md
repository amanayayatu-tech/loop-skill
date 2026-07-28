# LoopSkill 4 Codex Host Adapter boundary

## Status and scope

LoopSkill 4.0 ships one Host Adapter, Codex. The Kernel remains Host-neutral,
but no multi-host claim is allowed before a second real Adapter passes the same
conformance corpus. Core sees only manifest-generated `EffectAttempt`,
`CapabilityRecord`, and `Receipt` values; it contains no Codex ID, enum, argv,
or subprocess behavior.

The production Provider is `CodexExecProvider`. It consumes the official
foreground `codex exec --json` boundary. It does not implement the experimental
external app-server protocol and does not expose a fallback to it.

## Execution ownership

The canonical Store atomically commits the Attempt, subject state, event,
snapshot, operation result, and outbox row before any Host invocation.
`SQLiteStore.claim_attempt` is the only execution-ownership transition. The
Adapter and Provider never write canonical state.

One claimed Attempt permits one foreground process spawn:

| Local condition | Provider action | Recovery |
| --- | --- | --- |
| Attempt committed but unclaimed | one claimant may invoke `codex exec` | the same durable Attempt may make its first call |
| process started | no second spawn | accept only the directly captured terminal stream |
| complete valid JSONL + zero exit | bind same-process terminal observation | local result/artifact/review/finalization may advance |
| lost, malformed, failed, ambiguous, timed-out, or interrupted evidence | no retry or resume | preserve `UNKNOWN` |

There is no daemon, proxy, Supervisor, automatic `exec resume`, project
provisioner, second writer, or post-process Host lookup. A crash after the
Attempt is claimed sacrifices liveness rather than risking a duplicate effect.

The only guarantee text for this Provider is:

> at-most-one automatic attempt; outcome may be UNKNOWN

It is not cross-system exactly-once or provider idempotency.

## Preflight and invocation

Preflight has zero model/Host effects. It:

1. selects the safe regular executable using macOS bundle-first and resolved
   PATH fallback;
2. binds its real file digest and `codex-cli` version;
3. runs bounded `--version` and `exec --help` inspection; and
4. fails closed if any required reviewed flag is absent.

The pure argv builder selects `exec --json`, exact `--cd`, workspace-write
sandbox, `sandbox_workspace_write.network_access=false`, non-Git support,
ephemeral execution, ignored user config/rules, and prompt input from stdin. It
never invokes a shell or asks the model/user for a control identity.

The subprocess runs in one owned process group. stdout, stderr, individual
JSONL lines, total duration, and prompt bytes are bounded. Success, failure,
timeout, interruption, and output-bound violations all reap the process group.
No child process may remain after closure.

## Terminal evidence

The UTF-8 JSONL parser requires exactly:

- one `thread.started` with one machine-emitted identity;
- one `turn.started`;
- one `turn.completed` and no `turn.failed` or top-level `error`;
- zero process exit status and empty stderr; and
- at least one completed agent message, with the final one used as the result.

Unknown additive event types and item-level warnings may be ignored. Duplicate
or conflicting identities, multiple terminal events, missing terminal/result,
malformed or truncated JSON, oversized output, nonzero exit, stderr, timeout,
or process death fail closed. The existing semantic-result parser and external
artifact verification remain independent gates; terminal JSONL alone cannot
mint PASS.

The Provider caches the valid transcript only inside the live Provider object.
`readback`, `read_task_result`, and lifecycle reads expose that same-process
evidence to the existing Adapter. A new process cannot recover it, and 4.0.0
does not parse rollout files to manufacture recovery.

## Capability truth

`task_create`, `resource_read`, and `lifecycle_readback` are available strictly
only for the directly captured same-process transcript. The capability source
explicitly identifies this scope. These are unavailable as cross-process Host
lookups.

`project_registration`, independent `thread_create`, `message_send`,
`heartbeat`, and `provider_idempotency` are unavailable. Sandbox, trust, model,
and memory are reported only to the strength actually exposed. Because the
strict overall profile also requires capabilities that are absent, the overall
Provider profile remains `COOPERATIVE` even when one successful chain has
strict directly captured terminal evidence.

Codex Desktop folder-open plus exact-path project listing and project-bound
thread creation has separately passed 23/23 historical provisioning receipts.
That proves the Desktop route exists; it is not wired into the 4.0.0 Provider.
Saved-project convenience and Desktop-visible task creation are not 4.0.0
claims.

## Predecessor transport evidence

The external `app-server --stdio` implementation and its default-path tests
were removed after the exec vertical passed. Commits `5edbaef`, `2354639`, and
`f0d33c4` preserve the prior implementation and both terminal canary failures.
Those canaries created one Host thread apiece, sent no model turn, produced no
artifact, and were never retried or supplemented. The narrow conclusion is
that external app-server lifecycle ownership was unsuitable for the 4.0.0
default, not that the Kernel, Store, or model effect failed.
