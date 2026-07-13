# Loop Skill v3.2 replacement attempt 03 — failed App E2E

Date: 2026-07-12 (Asia/Shanghai)

## Frozen result

- Result: `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST / TRANSIENT_READ_TIMEOUT_MISCLASSIFIED_BLOCKER`
- Evidence layer: failed current-machine bounded App smoke; not E2E PASS, long-run, formal, production, science, or public acceptance.
- Root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-replacement-final-e2e-20260712-03`
- Pack: `controller-pack.md`, 162938 bytes, SHA-256 `b8514ee88eff9dafad0970131483a4aab66e49354b6563747d40263e96bb7709`
- Loop id: `25e25dc9dbcd5835`
- Controller: `019f570c-88ad-7863-8af2-95be40e0f4ed`
- State-Writer: `019f5710-c130-7042-bc8e-fda37ec6de78`
- Worker: `019f571a-f07a-74d0-9f4d-17428e6b6535`

## Successful prefix

- Local Pack attestation and parent `create_thread` observation matched.
- State-Writer returned `READY_IDLE_AWAITING_STATE_UPDATE`.
- `INITIALIZE` used root-confined local `source_path`; no inline Pack, Base64, wrapper decode, or entity replacement.
- Canonical v1 validated as `schema_version=2`, `review_contract_version=2`; trusted Pack archive SHA matched.
- Unique heartbeat was canonically ACKED as `ACTIVE` with id `loop-loop-heartbeat-25e25dc9dbcd5835`.
- Unique native Goal was created and canonically ACKED as `ACTIVE`.
- Unique Worker was created through its THREAD outbox and returned `READY_IDLE_AWAITING_GOAL`.
- GOAL_DISPATCH Context Freshness was recorded as `FRESH`.
- Worker dispatch `dispatch-v32-replacement-03-final-g1-25e25dc9` was materialized and left canonically `PREPARED` with payload digest `sha256:b4b79003add0a0db5b70f921f5c1c058ad3953021e733e49b0508f8d4307aaf7`.

## Failure

The Controller's own `read_thread` calls timed out while checking whether the PREPARED dispatch had reached the idle Worker. Parent readback proved that the Worker remained idle with only `READY_IDLE_AWAITING_GOAL` and no dispatch id. Before that evidence was consumed, the Controller treated three transient task-read timeouts as a repeated hard blocker and called the native Goal update to `blocked` without a runtime `STOP_LOOP` transition.

Canonical state remained at v16 with:

- `controller_goal.status=ACTIVE`
- `terminal_status=null`
- dispatch outbox `PREPARED`
- same exact Controller lease/outbox identity
- no Worker report or artifact

The next Controller turn correctly reconciled the real native Goal as `blocked`, declared `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`, and refused to send, recreate, emulate, or replace the Goal/dispatch.

## Frozen boundary

- No Worker execution or product artifact.
- No Reviewer or Decision.
- No CODE_REVIEW, ROADMAP_AUDIT, FINAL_AUDIT, FINALIZE_LOOP, or finalization receipt.
- No Git, network, PR, merge, tag, release, deploy, production, or secrets action.
- Parent attempted to pause the canonically ACKED heartbeat by exact automation id; App returned: `Automation does not exist in the app and could not be updated. It may have been deleted manually by the user.` No PAUSED observation is claimed.
- Controller, State-Writer, and Worker tasks were archived after a stop instruction; history and canonical files remain preserved.

## Required repair

Generated Controller policy must state that App task read/index/transport timeouts are recoverable `WAITING_ACTIVE` or `WAITING_QUOTA_RECOVERY`, never consecutive hard-block observations and never grounds for native `update_goal(blocked)`. The native Goal may be blocked only after deterministic runtime `STOP_LOOP_APPLIED` has produced the matching BLOCKED finalization target. PREPARED dispatch recovery must reuse the same Worker/dispatch/payload and, when needed, same-owner lease renewal; it must not enter generic repeated-blocker handling.
