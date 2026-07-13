# v3.2 App Transport Canary — PASS

Date: 2026-07-13 (Asia/Shanghai)

## Scope

Non-product canary for Route B only. It exercised installed-skill payload
verification, a read-only Reviewer task's runtime-owned report spool, staged
source ACK, and native Goal/heartbeat result shapes. It did not start or consume
replacement attempt-05.

## Identity

- Project: `/Users/peachy/Documents/测试 loop`
- Successful canonical root:
  `/Users/peachy/Documents/测试 loop/loop-skill-v32-app-transport-canary-20260713-02`
- Reviewer task: `019f5935-492b-75f3-9e9a-76aebed5ae44`
- Review outbox: `review-app-transport-canary-1`
- Payload digest:
  `sha256:62a76e5ad6235ba0cb735162b2cc32150eb827e1bc100811273fa7a76ec62d50`
- Report digest:
  `sha256:d1bf5ab4f00a2ef9f57e4af1e3ebd0a1b81b8230153e501db033a875a5c17d64`

The first setup root was intentionally retained after runtime rejected an
external Reviewer cwd with `PATH_SCOPE_ESCAPE`. The second root initialized an
explicit allowed external worktree root and passed. No product action occurred
in the rejected setup.

## Payload Transport

- Semantic probe: literal value `<tag>&中文 &lt;literal` before materialization.
- Sent transport: ASCII-only; no literal `<`, `>`, `&`, or non-ASCII code point.
- The sender supplied one trailing LF. App structured `codexDelegation.input`
  readback omitted that LF while preserving the canonical JSON semantics.
- The target passed the structured input to installed `--payload-verify` and
  proceeded only after `PAYLOAD_VERIFIED`.
- CRLF and single-trailing-newline acceptance remain separately covered by the
  deterministic local codec regression; the App surface itself trimmed the
  supplied trailing LF in this canary.

## Read-Only Reviewer Staging

The Reviewer task retained read-only product scope. Its only write was through
installed `adaptive_state_runtime.py --report-stage` into the runtime-owned
`.codex-loop/report-staging/` spool. Its final answer contained only the
ASCII-safe `FORMAL_REPORT_STAGED` JSON handle.

The staged source was a regular owner-controlled 0444 file. Controller did not
read or transport report bytes. Installed runtime consumed the source handle
and returned:

- `STATE_WRITE_APPLIED`
- `operation_status=ASSURANCE_OUTBOX_ACKED`
- canonical state `v21 -> v22`
- assurance outbox readback `status=ACKED`

The staged source and archived report both hashed to the report digest above.

## Goal And Heartbeat Shapes

- `create_goal` returned the exact current task id, objective, `status=active`,
  usage fields, and no implicit token budget.
- `get_goal` returned the same ACTIVE identity.
- After the canary objective was actually achieved, `update_goal(complete)`
  returned `status=complete`, `tokensUsed=44565`, and `timeUsedSeconds=278`.
- A subsequent `get_goal` returned `goal=null`, confirming the native completed
  row is no longer exposed as current.
- Heartbeat id `loop-skill-v32-route-b-canary` was created ACTIVE for the exact
  current task and then updated to PAUSED with the same id/name/prompt/schedule.
- The canary Reviewer task was archived only after report ACK.

## Verdict

`CANARY_PASS`. The App transport, installed semantic verifier, target-local
staging, staged-source ACK, Goal adapter shape, and heartbeat update shape are
compatible with a fresh sequential replacement attempt. This is smoke evidence
only; it is not attempt-05 acceptance and does not itself authorize GitHub
delivery.
