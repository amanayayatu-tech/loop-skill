# Loop Skill v3.2 replacement final App E2E attempt 04 — failed

## Identity

- Attempt root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260712-04`
- Controller Pack: `controller-pack.md`
- Pack byte length: `163728`
- Pack SHA-256: `9d8bf3904b20579119b2d9236c59db3cfe4b4d1b8af283205c613803b4884a85`
- Loop ID: `ef8b7ae85b636d24`
- Controller task: `019f572e-8442-7291-9a97-cc06636d470b`
- State-Writer task: `019f5730-61bf-7962-a359-5705e04c9ac1`
- Worker task: `019f5746-3c6d-70c1-b28c-666eb59e805c`
- Goal: `V32-REPLACEMENT-04-FINAL-G1`
- Milestone: `M1-REPLACEMENT-04-FINAL-BOUNDED-SMOKE`
- Review-surface decision: `DEC-V32-REPLACEMENT-04-FINAL-SURFACE`

## Last canonical state

- State version at the report-archive rejection: `19`
- Native Controller Goal ID: `019f572e-8442-7291-9a97-cc06636d470b`
- Native Controller Goal canonical status: `ACTIVE`
- Heartbeat automation ID: `loop-loop-heartbeat-ef8b7ae85b636d24`
- Worker dispatch outbox: `dispatch.v32.replacement.04.final.g1.1`
- Worker dispatch status: `SENT`
- Worker payload digest: `sha256:89ca37ce35c6fb19ed15fe9b97e7fa29e1c731a1eaa296fa95d37c54409e4d80`
- Finalization receipt: absent
- Success status `FINALIZATION_ACKED`: not reached

After the failed canonical closeout, a later Controller continuation incorrectly marked the native Goal `BLOCKED` without an acknowledged `STOP_LOOP`; canonical state remained v19/ACTIVE. This produced `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`. The parent then paused the exact heartbeat `loop-loop-heartbeat-ef8b7ae85b636d24`; it did not rewrite canonical state or claim finalization success.

## What succeeded

1. The frozen local Pack passed its byte-length and SHA-256 attestation.
2. `INITIALIZE` archived the Pack through the root-confined `source_path` path and produced schema/review contract v2 canonical state.
3. The same heartbeat was created and acknowledged ACTIVE.
4. The native Controller Goal was created and acknowledged ACTIVE.
5. The implementation Worker was created once, returned `READY_IDLE_AWAITING_GOAL`, and was registered in canonical state.
6. Context Freshness was recorded as deterministic `FRESH` at state v16.
7. The Worker payload was materialized by the installed runtime, prepared once, sent once, and marked canonical `SENT` at state v19.

## Failure chain

1. The Worker invoked `adaptive_state_runtime.py --payload-verify` through a local capture path that did not preserve the exact no-trailing-newline transport body. It returned a strict zero-write `BLOCKED` report with `DISPATCH_PAYLOAD_JSON_INVALID`.
2. A parent read-only reproduction extracted the exact structured `content[0].codexDelegation.input` bytes from the Worker task and passed them directly to the installed runtime with LF-only/no trailing newline. The exact tool result was:

   `PAYLOAD_VERIFIED`, exit `0`, canonical byte count `7503`, transport byte count `7548`, state version `19`, outbox `dispatch.v32.replacement.04.final.g1.1`, and the expected payload digest.

   This proves the App-delivered payload was intact; the first failure was Worker-local invocation/capture, not payload corruption.
3. The strict Worker report contained the generated required-field text `sha256:<after_snapshot_sha256>`.
4. Sending that report as inline mutation artifact content through the App surface entity-encoded the literal angle brackets. The deterministic runtime rejected the archive with:

   `ARTIFACT_DIGEST_MISMATCH`

   expected `sha256:5a37c14b17e21111d20829e8125b94abbf64acfc7cfdd0479087d86079117331`, actual `sha256:4529e17969ff2c37d565bed84eddfcf77d5ef6f3bbb8e54e35bd73a9e5f7a656`, path `/artifacts/0/digest`.
5. The rejected mutation left canonical state and the `SENT` outbox unchanged. Base64, wrapper decoding, HTML/XML entity decoding, and hand-written JSON codec workarounds were explicitly forbidden and were not accepted as recovery paths.

## Side-effect boundary

- No `artifact/result.md` was created.
- No product file in the attempt root was changed by the Worker.
- No Reviewer was created.
- No review-surface Decision was registered.
- No Git stage, commit, push, PR, merge, tag, release, deploy, production write, or secrets access occurred in this attempt.
- The failed report archive was a pure runtime rejection; it did not advance state v19 or fabricate an ACK.
- A canonical `CANCEL_OUTBOX` closeout was attempted once and rejected as `OUTBOX_CANCELLATION_NOT_SAFE` because the dispatch was already `SENT`; state remained v19. No `STOP_LOOP` or `ACK_FINALIZATION` was applied.
- The native Goal/canonical mismatch is preserved as failure evidence. The exact heartbeat is now externally `PAUSED` to prevent further routing.

## Root repair

The generated formal report instruction no longer uses the angle-bracket placeholder `sha256:<after_snapshot_sha256>`. It now states the same invariant as: the literal `sha256:` prefix followed by `after_snapshot_sha256`. Deterministic generated-Pack coverage asserts that the report-facing placeholder is absent.

This repair still requires a new real App E2E identity. Attempt 04 was the third and final new attempt authorized by the current execution contract, so no attempt 05 was started.
