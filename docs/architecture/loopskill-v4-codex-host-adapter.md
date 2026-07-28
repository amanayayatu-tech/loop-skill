# LoopSkill 4 Codex Host Adapter boundary

## Status and scope

This document records the P4 local implementation checkpoint under ADR 0011.
The first release has one Host Adapter, Codex; the Kernel remains Host-neutral.
No multi-host claim is permitted before a second real Adapter passes the same
conformance corpus. This checkpoint does not authorize installation, release,
real-loop migration, or a stable claim.

The generic Adapter boundary owns Codex project/task/thread creation, message
send, heartbeat, resource readback, eventual indexing, Host schema/enums, and
the declared sandbox/trust/model/memory capabilities when a Provider exposes
them; the narrower production 4.0 subset is stated below. Core sees only manifest-generated
`EffectAttempt`, `CapabilityRecord`, and `Receipt` values. Core contains no
Codex resource identifier or App enum.

## Execution ownership and recovery

An effect becomes executable only after the canonical store atomically commits
the Attempt, its typed subject state, event, snapshot, operation result, and
outbox row. P4 exercised Delivery subjects; P5 adds the same contract for the
startup `ExternalEffect` subject without changing execution ownership.
The outbox then has one invocation state:

| Invocation state | Meaning | Automatic provider call allowed |
| --- | --- | --- |
| `READY` | committed and not claimed | one atomic claimant may call |
| `STARTED` | execution ownership durably claimed | no resend; exact readback only |
| `OBSERVED` | strict authoritative observation accepted | no |
| `UNKNOWN` | readback exhausted or unavailable | no; late exact readback allowed |
| `UNVERIFIABLE` | cooperative response only | no; late exact readback allowed |

`SQLiteStore.claim_attempt` is the only execution-ownership transition. The
Adapter is not a canonical writer and no Supervisor or recovery writer exists.
A crash after `STARTED` but before the provider call sacrifices liveness rather
than guessing or resending. A crash after provider acceptance similarly uses
the exact Attempt/idempotency identity for bounded readback. The same Attempt
can later move from UNKNOWN/UNVERIFIABLE to OBSERVED only through a fresh,
trusted, identity-matching receipt accepted by the Kernel.

The allowed guarantee text is `effectively-once` only when strict provider
idempotency and strict lifecycle readback capabilities are both present.
Otherwise the exact text is `at-most-one automatic attempt; outcome may be
UNKNOWN`. End-to-end exactly-once is never claimed.

## Closed Host contract

The typed Adapter contract can represent `register_project`, `create_task`,
`create_thread`, `send`, and `heartbeat`, but the production 4.0 app-server
Provider exposes only the composite `create_task` action. That action uses
cwd-bound `thread/start` plus `turn/start`; `thread/read` and bounded,
cursor-complete `thread/list` provide its readback. Independent
`register_project`, `create_thread`, `send`, and `heartbeat` actions are
reported unavailable by this Provider rather than inferred from the wider
contract. Sandbox, trust, model, and memory receipts remain UNVERIFIABLE unless
the Host supplies authoritative evidence.

Codex Desktop folder-open plus exact-path project listing and project-bound
thread creation has separately been verified in 23/23 historical provisioning
receipts. Current app-server 0.144.4 exposes no saved-project registration API,
so that verified Desktop route is not wired into 4.0.0; optional saved-project
convenience is deferred to 4.0.x/4.1 and is not a startup prerequisite.

The typed read-only resource catalog can represent `project`, `task`, `thread`,
`message`, and `lifecycle`; the production Provider exposes only
`task`/`thread`/`lifecycle` readback backed by `thread/read`. Project and message
readback fail before a Host request. Responses are closed:
unknown fields, missing fields, schema-version changes, and unknown enums are
`ADAPTER_SCHEMA_DRIFT`; action/idempotency/provider-subject conflicts are
`RECEIPT_IDENTITY_MISMATCH`.

Strict effect observation requires both authoritative readback and strict
availability of the action capability plus lifecycle readback. A provider
response without authoritative readback is cooperative and therefore maps to
UNVERIFIABLE, even if the response says it succeeded. Exhausted or unavailable
readback maps to UNKNOWN and consumes no new attempt.

Final lifecycle readback binds the loop, FinalizationRef, provider lifecycle
identity, and exact subject-chain digest. TERMINAL plus authoritative and
strict lifecycle capability yields a strict acknowledged receipt. Cooperative
TERMINAL yields only cooperative assurance; a nonterminal read yields UNKNOWN.
The Kernel separately verifies the trusted issuer, freshness, FinalizationRef,
and subject-chain digest before it can emit strict finalization acknowledgement.

Capability absence is data, not inference. Memory, sandbox, trust, and model
capabilities may be AVAILABLE, UNAVAILABLE, or UNVERIFIABLE. A cooperative
profile may terminate honestly with LIMITATION, but cannot produce a strict
Host-attested claim. Every capability observation has a closed receipt shape
whose machine issuer, trust class, identity, and validity interval are checked;
the exact capability receipt identities are included in effect/finalization
evidence digests. An unavailable action capability causes no provider call.

## Manifest and persistence changes

`EffectAttempt` is an additive generated wire type in the sole typed protocol
manifest. The handwritten Adapter consumes that generated record; it does not
declare a parallel protocol shape. At the P4 checkpoint SQLite schema v2 added
exact target identity, invocation ownership, and observation receipt fields to
the outbox. P5 evolves that schema transactionally to v4 so the same outbox row
also binds `subject_kind`, `subject_ref`, action, and canonical provider payload;
receipt identity is persisted with the observation transaction. Every migration
derives projections only from canonical snapshots and fails closed when the
derivation is incomplete.

## Disposable App canary

After all synthetic/local P4 tests passed, one non-research, non-scored,
projectless App canary was created in a dedicated disposable root. It was not
attached to this repository, a v3 loop, a user project, or paper data. It made
no tool call and performed no file mutation.

- task/turn identity: retained only in private local evidence; omitted here
- host class: `local`
- root class: dedicated disposable root; absolute path omitted
- observed duration: 7,129 ms
- readback SHA-256: `210bf4cd5f27f8e12bb0c0d4245318980b0aead3189f633ef43b28ec8ff4199c`
- completion error: absent
- tool marker: absent

This canary proves only that the current App created and authoritatively read
back one disposable task result with exact semantic identity. It does not prove
the repository Adapter is installed, Host transactions exist, LoopSkill is
effective, or an RC candidate is ready. The exact-RC install/usability canary
remains a separate P8 gate.
