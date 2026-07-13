# Loop Skill v3.2 replacement attempt 02 — failed App E2E

Date: 2026-07-12 (Asia/Shanghai)

## Frozen result

- Result: `E2E_PROTOCOL_VIOLATION / INLINE_PACK_ARTIFACT_TRANSPORT_UNSAFE`
- Evidence layer: failed current-machine bounded App smoke; not E2E PASS, long-run, formal, production, science, or public acceptance.
- Controller: `019f56f4-f471-7a90-84d0-84fe7dad9051`
- State-Writer: `019f56f7-8af7-7942-aaeb-14938f12f8eb`
- Pack path: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260712-02/controller-pack.md`
- Pack bytes: `162878`
- Pack SHA-256: `ce35480b390dda1b9f6a30188955ba0caed141c8e34410253d1ce4f9d0b343c9`
- Canonical root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-02-final-e2e-20260712-02`

## What happened

The initial launcher attestation correctly bound the local Pack path, byte length, SHA-256, parent Controller thread, project, and a fresh root. A zero-side-effect root-name mismatch was corrected in the same Controller before child creation. The Controller independently verified the local Pack digest and uniquely resolved its own thread identity. The only State-Writer then bootstrapped and returned `READY_IDLE_AWAITING_STATE_UPDATE`.

Every `INITIALIZE` attempt was rejected by the deterministic runtime with:

```text
status=ARTIFACT_DIGEST_MISMATCH
expected=sha256:802bc28ea11343e16a66e6fcf6c44c2e23c5056efb211725912ee8e8e8bd13e7
actual=sha256:ce35480b390dda1b9f6a30188955ba0caed141c8e34410253d1ce4f9d0b343c9
state_version=0
external_action_count=0
```

In this runtime error, `expected` is the digest recomputed from received inline artifact content and `actual` is the request's declared digest. `802bc...` is exactly the digest of the frozen Pack after replacing angle brackets with HTML entities, while `ce354...` is the local Pack SHA-256. The App delegation transport therefore changed inline Pack content before the State-Writer invoked the runtime.

The Controller later used Base64 as an intermediate validation codec before sending request `init-replacement-02-final-006`. That violated the parent contract's explicit prohibition on Base64 and codec workarounds. The request was still rejected with the same zero-effect fingerprint. The attempt was immediately frozen and both tasks were archived.

## Zero-side-effect boundary

- No `.codex-loop/LOOP_STATE.md`.
- No `.codex-loop/LOOP_EVENTS.jsonl`.
- Canonical state version: `0`.
- No trusted Pack snapshot or state mutation was applied.
- No Worker or Reviewer.
- No native Goal.
- No heartbeat.
- No lease, dispatch, Decision, assurance, finalization outbox, or receipt.
- No Git, network, PR, merge, tag, release, deploy, production, or secrets action.

## Root cause and required repair

Transporting the entire Controller Pack as inline JSON artifact content is incompatible with the App wrapper's entity encoding and cannot be repaired with wrapper decoding, Base64, or manual substring replacement. `INITIALIZE` needs a narrowly scoped local-source artifact mode: the request supplies a root-confined, non-symlink Controller Pack `source_path` and its attested digest; the installed runtime reads those local bytes directly and archives them. Inline report artifacts remain unchanged.
