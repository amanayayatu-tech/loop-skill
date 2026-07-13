# Loop Skill v3.2 replacement final App E2E failure evidence

## Result

- Result: `FAIL_E2E_PROTOCOL_VIOLATION`
- Evidence layer: local identity/preflight checks only; replacement App smoke did not initialize.
- This run is not `FINALIZATION_ACKED` and must never be relabeled PASS.

## Identity

- Replacement root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260712-01`
- Canonical Controller Pack path: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260712-01/controller-pack.md`
- Canonical Pack byte length: `168590`
- Canonical Pack SHA-256: `8cca228fad8ab0f5cbeec99ba5ca41321b774353885fd2acefaeba31ba1689a2`
- Controller thread: `019f56be-2e7b-7681-945a-953520df93f2`
- Incorrectly bootstrapped State-Writer thread: `019f56c5-342e-7840-bce9-367cd8460dfa`
- Incorrect transport-derived Pack SHA-256: `fcd4045b8827760006b6ab723887f54c7c73109ce05e437ab5625612c2ff381e`
- Incorrect loop marker prefix: `v32-replacement-final-dbc8b5d5d86adb4d`

## Root cause

The App delegation surface represented angle-bracket text using HTML entities. The Controller found that the exact local Pack bytes hashed to `8cca228f...`, but before the launcher identity correction arrived it derived bootstrap identity from the entity-encoded delegation representation and created the State-Writer with `fcd4045b...`. Pack identity must come from the launcher-attested on-disk artifact, never a delegation/XML/HTML/UI wrapper.

The installed contract requires an `E2E_PROTOCOL_VIOLATION` stop when a pre-state task was created with a nonconforming bootstrap identity. Creating a second State-Writer or second replacement E2E would violate the user authorization and erase the evidence boundary.

## Exact observed path

1. Controller preflight uniquely resolved project `/Users/peachy/Documents/测试 loop`, Controller thread `019f56be-2e7b-7681-945a-953520df93f2`, the empty replacement canonical root, and installed schema/runtime v2.
2. Controller computed a transport-derived marker using `fcd4045b...` and created State-Writer `019f56c5-342e-7840-bce9-367cd8460dfa`.
3. State-Writer returned only `READY_IDLE_AWAITING_STATE_UPDATE`.
4. The parent correction supplied the prevalidated local Pack SHA `8cca228f...`.
5. Controller stopped as `E2E_PROTOCOL_VIOLATION / CONTROLLER_PACK_TRANSPORT_IDENTITY_UNRESOLVED`.

## Zero-side-effect boundary

- No `.codex-loop/LOOP_STATE.md`.
- No `.codex-loop/LOOP_EVENTS.jsonl`.
- No trusted Pack snapshot.
- No `STATE_MUTATION` or canonical state version.
- No Worker.
- No Reviewer.
- No native Goal.
- No heartbeat/automation.
- No Decision Card or response.
- No dispatch, assurance, report, final audit, finalization outbox, or finalization receipt.
- Original failed E2E `/Users/peachy/Documents/测试 loop/loop-skill-v32-final-e2e-20260712` remained frozen and untouched.

## Source response

The generator, Adaptive contract, usage guide, Skill summary, and integration test now require a launcher `PACK_IDENTITY_ATTESTATION` before any child task. It binds the exact local Pack path, byte length, digest, and parent create-thread observation; delegation/XML/HTML/UI wrapper hashing or decoding is forbidden. Missing or mismatched identity must stop with zero child-task, Goal, heartbeat, or state side effects.

## Release boundary

- Local checks after this source change must be rerun before any engineering claim.
- No second replacement E2E is authorized.
- Git stage/commit/push/Draft PR/CI remain blocked because the required replacement smoke never reached `FINALIZATION_ACKED`.
- No merge, main update, tag, release, deploy, production write, formal acceptance, or science/public claim occurred.
