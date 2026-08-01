# LoopSkill 4 Codex Host Adapter boundary

## Status and scope

LoopSkill 4.2 ships one Host Adapter, Codex. The Kernel remains Host-neutral,
but no multi-host claim is allowed before a second real Adapter passes the same
conformance corpus. Core sees only manifest-generated `EffectAttempt`,
`CapabilityRecord`, and `Receipt` values; it contains no Codex ID, enum, argv,
or subprocess behavior.

The production Provider is `CodexExecProvider`. It consumes the official
foreground `codex exec --json --output-schema --output-last-message` boundary. It does not implement the experimental
external app-server protocol and does not expose a fallback to it.

## Execution ownership

The canonical Store atomically commits the Attempt, subject state, event,
snapshot, operation result, and outbox row before any Host invocation.
`SQLiteStore.claim_attempt` is the only execution-ownership transition. The
Adapter and Provider never write canonical state.

One claimed Goal Attempt permits a bounded initial foreground process and, only
after interruption with a captured session, one recorded same-session resume:

| Local condition | Provider action | Recovery |
| --- | --- | --- |
| Attempt committed but unclaimed | one claimant may invoke `codex exec` | the same durable Attempt may make its first call |
| process started and still live | wait; do not spawn | read its persistent terminal evidence when available |
| complete valid JSONL lifecycle + one schema-valid result file + zero exit | bind persistent terminal observation and schema/result digests | local result/artifact/review/finalization may advance |
| interrupted with session and replay-safe policy | record and run one `codex exec resume` | no second automatic resume |
| no session or non-replayable action | no blind call | reconcile local workspace or wait for human confirmation |

There is no daemon, proxy, Supervisor, project provisioner, second writer, or
unbounded retry. Recovery is restricted to owner-only evidence for the same
provider key and session.

The only guarantee text for this Provider is:

> at-most-one automatic attempt; outcome may be UNKNOWN

It is not cross-system exactly-once or provider idempotency.

## Preflight and invocation

Preflight requires the official `--output-schema` and `--output-last-message`
capabilities. The Provider
derives one closed object schema from the typed `StageExternalResult` and
`StageResult` payload contract, writes it to a private canonical non-symlink
read-only temporary control file outside the artifact workspace, verifies its
identity and bytes before and after the one process, and removes it. A second
machine-controlled owner-only ordinary file in the same private directory is
the sole semantic-result byte source. It is inode-, type-, size-, digest-, and
schema-checked before cleanup. JSONL never supplies the Result and no
agent-message or prose-marker fallback exists.

Preflight has zero model/Host effects. It:

1. selects the safe regular executable using macOS bundle-first and resolved
   PATH fallback;
2. binds its real file digest and `codex-cli` version;
3. runs bounded `--version` and `exec --help` inspection; and
4. fails closed if any required reviewed flag is absent.

The pure argv builder selects `exec --json`, both machine-controlled output
paths, exact `--cd`, workspace-write
sandbox, Plan-bound network access, non-Git support, persistent Plan v2
sessions, ignored user config/rules, and prompt input from stdin. It
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
- zero process exit status; and
- one nonempty bounded result file valid against the closed manifest-derived schema.

Unknown additive event types and item-level warnings may be ignored. Duplicate
or conflicting identities, multiple terminal events, missing terminal/result,
malformed or truncated JSON, oversized output, nonzero exit, timeout, or
process death fail closed. Bounded stderr is retained only as byte count and
digest diagnostics and does not veto an otherwise valid terminal chain;
stderr overflow fails closed. The existing semantic-result parser and external
artifact verification remain independent gates; terminal JSONL alone cannot
mint PASS.

Failure evidence retains one privacy-safe internal classification and bounded
byte/digest measurements. The public receipt binds its digest but contains no
raw stderr, result, transcript, path, or Host identity. The classification is
diagnostic only; the Adapter still maps ambiguous external completion to
canonical `UNKNOWN` and never resends.

For Plan v2, the Provider copies terminal schema/result/transcript bytes and a
digest manifest into one owner-only Attempt directory. `readback`,
`read_task_result`, and lifecycle reads validate those files after restart.
Partial stdout binds `thread.started` as soon as observed; recovery never parses
unrelated rollout files.

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
That proves the Desktop route exists; it is not wired into the 4.2 Provider.
Saved-project convenience and Desktop-visible task creation are not 4.2
claims.

## Predecessor transport evidence

The external `app-server --stdio` implementation and its default-path tests
were removed after the exec vertical passed. Commits `5edbaef`, `2354639`, and
`f0d33c4` preserve the prior implementation and both terminal canary failures.
Those canaries created one Host thread apiece, sent no model turn, produced no
artifact, and were never retried or supplemented. The narrow conclusion is
that external app-server lifecycle ownership was unsuitable for the 4.0.0
default, not that the Kernel, Store, or model effect failed.
