# Adaptive Codex App E2E Evidence - 2026-07-11

## Release Verdict

`FAIL_PROTOCOL_CONSISTENCY`

The run exercised a real Codex App project and reached the old runtime's
`FINALIZATION_ACKED` state, but it is not accepted as the release E2E PASS. The
persisted evidence violates two protocol invariants now enforced by the source
runtime, and the tested Pack predates those fixes.

Adaptive is released as `beta/experimental` under a local deterministic
acceptance policy. This frozen run remains a failed bounded App smoke; it is not
rewritten as PASS and no post-fix real Codex App E2E was executed.

## Run Identity

- Project root: `/Users/peachy/Documents/测试 loop`
- Integration root: `/Users/peachy/Documents/测试 loop/adaptive-loop-e2e-final-20260711`
- Loop id: `adaptive-e2e-5d7a24c7724e5819`
- Pack SHA-256: `dff10bed361186b197f50b65a8f83052132abf285daee1437583c3b25d5724a5`
- Controller: `019f50b2-0620-7970-b0c2-143066b9bb78`
- State-Writer: `019f50b6-7bd9-7d31-a3a6-b25008774ffb`
- Reused Worker: `019f50c3-91ba-7ce1-bef1-457074fffe25`
- Just-in-time Reviewer: `019f50e3-5a06-7712-ba95-343ff5a943f4`
- Business heartbeat: `loop-loop-heartbeat-adaptive-e2e-5d7a24c7724e5819`

The formal task registry contains exactly those four project tasks. No Local
Verifier or future-stage Worker was created. The one read-only sidecar was not
registered as a formal project task.

## Evidence Preserved

- Canonical state: `.codex-loop/LOOP_STATE.md`, SHA-256
  `d2b3fe5e2fd71b6f93c87d3e6699b9f650ddc341f984fb001380cdc2126c3ef7`
- Event log: `.codex-loop/LOOP_EVENTS.jsonl`, SHA-256
  `dd16fa4813f5e5a84998e08613338d47a25b5dbdecf723912ec8fb38cad4fa66`
- Goal projection: `.codex-loop/GOALS.md`, SHA-256
  `6b0decbc762ab0f28b428ea30bc7ee87e33fd0f9b39eb05641234d8604c7e2a8`
- Transaction journals: 69
- Archived reports: 36
- Old-runtime terminal snapshot: state version 69, roadmap version 3,
  `LOOP_COMPLETE_WITH_LIMITATION`, `FINALIZATION_ACKED` receipt present.
- External readback: Controller Goal `COMPLETE`; business heartbeat file is
  `PAUSED` and targets the exact Controller task.

The run also produced bounded positive smoke evidence for project placement,
single-writer state mutation, wrong-CAS zero-side-effect rejection, same-owner
lease renewal without resend, one roadmap revision, reused Worker/Reviewer,
three assurance kinds, finalization receipt creation, and heartbeat pause.

## Protocol Failures

### 1. Assurance ACK and ledger contradict each other

`review-code-g1-5d7a24c7724e5819-001` is `COMPLETED`, but its outbox result says
`INVALID_FORMAL_REPORT` and includes failure-only fields. The corresponding
assurance ledger records `REVIEW_PASS_WITH_LIMITATION` for the same report.

The current source runtime reads this frozen state as:

```json
{"details":{"reason":"ACK_RESULT_LEDGER_MISMATCH"},"ok":false,"path":"/assurance_dispatch_outbox/review-code-g1-5d7a24c7724e5819-001","status":"ASSURANCE_STATE_INCONSISTENT"}
```

### 2. Native Controller Goal never switched from M1 to M2

The roadmap changed from M1 to M2 and M2 was implemented and reviewed, but
`controller_goal` remained the M1 marker throughout. There is only one Goal
outbox, the original M1 CREATE. Finalization then completed that M1 Goal while
the final evidenced Worker Goal belonged to M2.

This violates the one-active-milestone Goal contract. Current source now rejects
Worker dispatch unless the canonical Controller Goal is active for the exact
milestone, returns `COMPLETE_CURRENT_CONTROLLER_GOAL` only when the Active
milestone changes, retains the Goal for same-milestone siblings, and applies the
same binding at `FINALIZE_LOOP` and `STOP_LOOP`.

## Source Corrections And Local Verification

- Formal ACK results are closed to status, report digest, and artifact digest.
- `RECORD_REVIEW` must exactly match the prior ACK tuple.
- Completed assurance outboxes and assurance ledger entries are one-to-one
  canonical-state invariants.
- Worker dispatch and finalization require an active Controller Goal for the
  exact milestone.
- Cross-milestone and same-milestone Goal routes have separate deterministic
  next-action tests.
- Control-plane Thread, Automation, and Goal ACKs now require immutable strict
  JSON tool-result observations; task roles, child-task budget, one business
  heartbeat, and authorized external Codex worktree roots are runtime-enforced.
- The runtime now locks the stable project-root directory descriptor, restores
  dashboard events in canonical version order, and rejects early same-milestone
  Goal closure.
- Roadmap Audit now binds one typed proposal and component digests. Obsolete
  PREPARED records must be cancelled in separate acknowledged transactions;
  ROADMAP_REVISION cannot silently cancel them.
- STOP_LOOP now requires three already archived prior observation-only Goal
  turns and runs on the following dedicated Goal turn; a heartbeat claim is
  rejected, and STOP cannot attach or backfill its own qualifying observation.
- Dashboard output now renders escaped milestone decisions, required evidence,
  local evidence links, and pending roadmap decisions, matching the generated
  Pack contract.
- Full local suite: 265 tests passed.
- Extended fuzz: 5000 malformed generator inputs plus 5000 randomized runtime
  sequences passed as part of the full 265-test run.
- Generator fixture regeneration, Standard fixed hashes, CLI/runtime recovery,
  validator, and isolated installation checks passed locally.

## Evidence Boundary

- Local checks: source tests and deterministic fuzz passed.
- Real App smoke: the frozen run exercised the App topology and control-plane
  actions, but its release verdict is failed because its protocol state is
  contradictory and it did not run the corrected Pack/runtime.
- Long-run/formal acceptance: not established.
- Public/production/cross-version claim: not established.

The protocol defects exposed by this run were corrected in source and covered
by deterministic regression tests. Those corrections were not rerun in a real
Codex App project. Per the release policy, this evidence is frozen and no
replacement, reduced, or disguised E2E will be created. Passing local checks is
not evidence that every Codex App environment can automatically reach a loop
terminal state.
