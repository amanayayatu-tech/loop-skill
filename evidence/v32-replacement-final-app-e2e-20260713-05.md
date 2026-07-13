# Loop Skill v3.2 replacement final App E2E attempt 05 — passed

## Evidence class

This is one current-machine, current-Codex-App, root-confined frozen-Pack bounded
smoke. It establishes the exact App/runtime closure described below. It is not
long-run, cross-version, production, formal, science, or public acceptance.

## Identity

- Attempt root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260713-05`
- Controller Pack source: `controller-pack.md`
- Archived Controller Pack: `.codex-loop/sources/CONTROLLER_PACK.md`
- Pack byte length: `171549`
- Pack SHA-256: `ab2ecee3772434623eb96e8b7e1b1f8b70eed0379282412802e2b39b29bbfa9c`
- Loop ID: `05d2a438d9cd6337`
- Controller task/native Goal: `019f5941-5836-7e91-b81c-15684743a607`
- State-Writer task: `019f5945-9dcf-7fc1-b8e0-93211734fbe3`
- Worker task: `019f5950-0bfe-7822-953e-d6245eccb9e9`
- Reviewer task: `019f5975-2b68-7b13-96eb-9c65f27733a1`
- Heartbeat: `loop-loop-heartbeat-05d2a438d9cd6337`
- Goal: `V32-REPLACEMENT-05-FINAL-G1`
- Milestone: `M1-REPLACEMENT-05-FINAL-BOUNDED-SMOKE`
- Review-surface Decision: `DEC-V32-REPLACEMENT-05-FINAL-SURFACE`
- Native Goal policy: `required`

The source and archived Pack are both `171549` bytes and have the same SHA-256.
Canonical `controller_pack_identity` records that digest and the exact
`.codex-loop/sources/CONTROLLER_PACK.md` path.

## Artifact and report identity

- Product artifact: `artifact/result.md`, `292` bytes
- Product file SHA-256: `7da1e3a404b61b8db4525376a0e6fe2d92398a0c10c29a830e29a371a34f2be6`
- Canonical product snapshot digest: `sha256:c0a0a9bd9f30f5c264d5b9a1888765594a41ce4500b19ec6e1797be63d19808c`
- Final Worker report: `sha256:6542fcbe7bab9b490fe1ea59b6e4c03440d216669d61092b1b787ee185c1e98c`
- Passing CODE_REVIEW report: `sha256:c626fb082e4b84aec5366945df92846043ea357d8ce3ab53afd0de488957d9ef`
- ROADMAP_AUDIT report: `sha256:655ebc2712d1c3af7991dcd21d354d291b6d473bc942b44f84148215979b9378`
- Accepted review-surface evidence: `sha256:c79e81fa3c83fcf5c46fdb76151b50d5ff4e3d187536f8161f97bc4add7ac634`
- FINAL_AUDIT report: `sha256:4cc6ab611c5bae9774e37809c72a75beec5bbfcd475493e08ca6a24b4979b55b`

The final Worker handoff contains a replayable `MANIFEST_DELTA_V1`; its file row
binds the `292`-byte product file and its SHA-256, and the reference digest is
`359659a5414809c9a1aca829965b00c2094e910534c21946cd652bd5233cb88c`.
The Worker, CODE_REVIEW, ROADMAP_AUDIT, and FINAL_AUDIT formal reports were staged
by their target tasks under `.codex-loop/report-staging/` as regular read-only
files and then archived by the runtime. The inspected staging files had mode
`0444`; no formal report bytes were relayed inline through App transport.

## Canonical execution chain

1. `INITIALIZE` archived the exact root-confined frozen Pack and registered the
   one Controller and one State-Writer.
2. The same heartbeat and same native Controller Goal were created and ACKed.
   The one Worker was created, registered, and reused across the bounded repair
   sequence; no replacement Worker identity was substituted.
3. The first Worker return was a strict zero-product-effect payload capture
   blocker. The next bounded execution created the exact artifact. A final
   evidence repair returned a PASS report with the complete diff reference,
   without changing the artifact digest.
4. All five required validation dimensions became `PASS`: `functional`,
   `regression`, `static_quality`, `user_experience`, and `change_impact`.
5. The same Reviewer produced the passing CODE_REVIEW, the
   `ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`, and `FINAL_REVIEW_PASS`. The artifact-bound
   `ACCEPT_REVIEW_SURFACE` Decision was applied between ROADMAP_AUDIT and
   FINAL_AUDIT.
6. `FINALIZE_LOOP` advanced state v73 to v74 with
   `status_code=FINALIZE_LOOP_APPLIED`, set the business result to
   `terminal_status=LOOP_COMPLETE`, and prepared the one success finalization
   outbox with an exact closeout capability.
7. Independent JSON observations then bound the same native Goal as `COMPLETE`
   and the same heartbeat as `PAUSED`. `ACK_FINALIZATION` advanced state v74 to
   v75, ACKed the finalization outbox, wrote the non-null receipt, and returned
   exact `FINALIZATION_ACKED` with `next_action_code=NONE`.

## Native Goal resume evidence

The App had non-canonically marked the same native Controller Goal `BLOCKED`
during the run. The recovery did not create a replacement Goal and did not claim
that App Goal was `ACTIVE`.

At canonical state v59, `RECORD_CONTROLLER_GOAL_RESUME` recorded:

- native observed status: `BLOCKED`
- pre-observation digest: `sha256:0ee56833d200ee6acf0205713048d6dca28ba8dbc387557d90221ad78c55a705`
- authorization digest: `sha256:2771d5d5b51b77cecd79b6942a5470a650e45b5e3a1f689512864b4822945e5b`
- post-observation digest: `sha256:368c26d50aeffa245f0cf331e0f7baca4a1236aad0f4e34504c75ec727827cef`
- exact same Goal ID: `019f5941-5836-7e91-b81c-15684743a607`
- resulting action: `CONTINUE_CANONICAL_EXECUTION`

The pre and post App readbacks both preserved the factual blocked status. Only
the final closeout observation later established that same Goal as `COMPLETE`.

## Exact finalization evidence

The final canonical state is v75 with:

- `terminal_status=LOOP_COMPLETE`
- `controller_goal.status=COMPLETE`
- `finalization_outbox.status=ACKED`
- `finalization_outbox.outcome_kind=SUCCESS`
- `finalization_receipt.ack_state_version=75`
- `finalization_receipt.controller_goal_id=019f5941-5836-7e91-b81c-15684743a607`
- `finalization_receipt.controller_goal_status=COMPLETE`
- `finalization_receipt.automation_id=loop-loop-heartbeat-05d2a438d9cd6337`
- `finalization_receipt.automation_status=PAUSED`
- `finalization_receipt.outcome_kind=SUCCESS`
- closeout capability: `sha256:ae5d3373b48a32ca87939837d92afbfe5b08d36295a6947cd4f80859e5c863b0`
- Goal observation digest: `sha256:d8d1895d24baec72a02c2a9e5f3f84235a2d35be480f4c3dc32c5a072f79cff1`
- heartbeat observation digest: `sha256:8243761129d8e4c59d845c1e20a073b0ca5a80773c57ac2e70f6a84bea5162a3`

The final append-only event is:

- event type: `ACK_FINALIZATION`
- state transition: `74 -> 75`
- operation/event status code: `FINALIZATION_ACKED`
- next action: `NONE`
- timestamp: `2026-07-13T07:05:20.066Z`

`terminal_status` and `FINALIZATION_ACKED` deliberately represent different
layers. The public state schema permits the business outcome field to be only
`null`, `LOOP_COMPLETE`, `LOOP_COMPLETE_WITH_LIMITATION`, or `LOOP_BLOCKED`;
`FINALIZATION_ACKED` is therefore not a legal `terminal_status`. It is the exact
`ACK_FINALIZATION` operation/event result which, together with the bound non-null
receipt, opens the release gate. Runtime regression coverage explicitly asserts
that a successful ACK returns `operation_status=FINALIZATION_ACKED` while the
business result remains `terminal_status=LOOP_COMPLETE`.

## Local release validation

The release candidate was validated with the following observed results:

- Normal full discovery: `python3 -W error -m unittest discover -s tests -v` —
  `363 tests`, `OK`, `254.742s`.
- Dual 5000-round fuzz:
  `ADAPTIVE_FUZZ_CASES=5000 ADAPTIVE_STATE_FUZZ_CASES=5000 python3 -W error -m unittest discover -s tests -q`
  — `363 tests`, `OK`, `1282.349s`.
- Source skill validator: PASS.
- Official quick validator on source: PASS.
- Source `compileall`/`py_compile`: PASS.
- Standard and Adaptive fixture determinism and size regression: PASS.
- Adaptive fixture: `2601` lines, `207257` bytes, approximately `14.97%`
  growth from `180266` bytes and below the `15%` cap.
- `git diff --check`: PASS.
- Formal `scripts/install.sh` installation: PASS.
- Installed skill validator, official quick validator, and compile check: PASS.
- Full source/installed byte manifest, excluding caches: identical.
- Installed cache scan: no `__pycache__` or `.pyc` files.
- Source and installed deterministic runtime SHA-256:
  `998d1038df063ed2d0ee622be3e30999c8a639c7ce3364a182ce2f9d32fd4f0d`.

The current exact Standard fixture baselines are:

- `01` Controller Pack: `b8ea8ed56d6fef4689e83fb5fd7ab8dfb033ad881910b48b000372e2e3b6da5e`
- `01` usage: `d8e38f4680a47aed114adf3ddfa20ba9534be7dbfc03fd6a770b345b118f81e4`
- `02` Controller Pack: `42e264a0ef54812c73935d0d9c039a12805e7168365748f24474b10cf263445e`
- `02` usage: `cea1c0a82898712685aac818ef3862fe0cbda444967a7e0313592b77ac2eb73a`

The two Controller Pack hashes changed intentionally with the v3.2 protocol
text; the two usage hashes remained stable.

## Side-effect and identity boundary

- Attempt 05 used the exact Controller, State-Writer, Worker, Reviewer, native
  Goal, heartbeat, loop, and Pack identities listed above.
- No attempt 06, replacement Controller, replacement native Goal, or duplicate
  heartbeat was created.
- The bounded artifact itself declares that it is one current-machine App smoke
  and not long-run, production, formal, science, or public acceptance.
- The E2E authorized no merge, deploy, production write, external network write,
  credentials, or secrets access.

## Known next-stage limitation

This release validates only a frozen Pack already located inside the canonical
attempt root. The current runtime requires `INITIALIZE` artifact `source_path`
to resolve under that root; it does not yet provide a general launcher path that
stages an external Pack into canonical root before initialization.

Accordingly, the Alaya external-Pack `source_path` startup deadlock is not fixed
or tested by attempt 05 and is outside this release claim. External Pack ->
canonical root staging remains an explicitly deferred next-stage item. No
post-finalization runtime change was inserted to imply otherwise or to alter the
artifact identity validated by this attempt.
