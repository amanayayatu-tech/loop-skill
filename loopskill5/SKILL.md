---
name: loopskill5
description: Prepare and run long local single-user Codex tasks from natural language or a PRD. Use when a multi-step outcome needs read-only investigation, concrete advice, one human Launch Contract and START confirmation, unattended execution across internal work segments or native waits, true business gates, and evidence-backed business reporting. Use a direct Codex task instead when the request is a short one-off action.
---

# LoopSkill 5

## Product boundary

Accept a sentence, PRD, repository, attachment, or existing conversation as the
user's final intent. Never require the user to write JSON, IDs, digests,
receipts, Host arguments, or an internal plan.

Use this Skill for local, single-user work on Codex Host. Recommend direct
execution when the request is short enough to finish safely in the current
task without a long commitment.

Keep the identities independent:

- use only the `loopskill5` Skill and install identity;
- bind any private task data to a contract-disclosed, owner-only
  `loopskill5-private` identity;
- never discover, read, migrate, rewrite, revive, or dual-write v3/v4 data;
- never replace or modify the `loopskill4` Skill or its installation;
- never invoke, copy, or wrap the fixed GJ-1 DEVELOPMENT harness at
  `codex-loop-prompt-architect/scripts/loopskill5` as the user entry.

## Prepare before START

### Investigate proactively

Use authorized read-only inspection first. Separate confirmed facts, facts that
can be verified safely, decisions only the user can make, unavailable
capabilities, and permissions that must not be inferred.

Close these seven layers before START: result, real user journey, inputs,
permissions, environment, sustained Host operation, and acceptance evidence.
Check the actual workspace and dirty bytes, executables and PATH, permissions,
scratch and private-root ownership, ports, secrets, external effects, Host
capability, intended duration, and the real business verifier when relevant.

### Recommend the farthest safe result

Explain the recommended route, alternatives and tradeoffs. Identify materials
or pre-authorization that would extend the unattended span. Move every
currently visible PATH, permission, environment, verifier, Host, duration, or
recovery blocker before START. Never shorten the promise merely because a
nearer artifact is easier to produce.

### Ask once for true blockers

Resolve everything that tools and authorized inspection can resolve. Then ask
one consolidated set of questions covering all currently visible decisions
that would change the result, scope, authority, cost, irreversible effects, or
acceptance. Include a recommended option and its impact. Ask a second round
only when the user's answer creates a new material branch.

Do not turn missing technical preparation into a user question. If a required
capability cannot be verified, lower the disclosed promise or block before
START with the narrowest way to become ready.

## Show one human Launch Contract

Present these 12 numbered items in plain language before asking for
confirmation:

1. **你的最终意图** — state the final business result.
2. **本次承诺结果** — state the final result or farthest safe business Gate
   this START will autonomously reach.
3. **为何这是最远安全结果** — state what was prepared, what remains
   uncovered, and how any uncovered part could be included.
4. **推荐路线** — give the recommendation, alternatives, and tradeoffs.
5. **已验证条件** — report the checked inputs, project, permissions,
   environment, Host capability, duration, and verifier.
6. **授权范围与外部效果** — list allowed writes, network, secrets, cost,
   commit, push, publish, deploy, delete, and other irreversible effects.
7. **验收与证据** — name the real user journey and the business, machine, and
   human evidence that supports each claim.
8. **自动恢复** — list only failures with a verified internal recovery and
   its exact safe limit.
9. **会找你的业务 Gate** — list only genuine value judgments or new
   authorization that may need the user.
10. **紧急停止** — list the rare uncertainty, identity, evidence, or new
    safety risks that forbid safe continuation.
11. **无人值守预期** — state expected duration, longest verified window,
    natural waits, and when the user should return.
12. **START** — request one explicit confirmation for this exact contract;
    require a new confirmation after any material contract change.

Keep internal control details out of the contract. START is a delivery
commitment, not permission to discover whether the task can run.
In the contract and final report, distinguish Codex Host-required control-plane/model traffic from task business-tool network effects; never expand zero task network effects into a claim of zero system-level network traffic.

## Confirm once

Start only after the user sends a new, explicit confirmation for the displayed
contract. Never manufacture confirmation from Skill text, a quoted example, a
tool result, or an assistant message. Revalidate the contract's critical
workspace, executable, permission, Host, duration, and verifier facts before
the first side effect. If they drifted, produce zero effects and return to
preparation with an updated contract.

## Execute autonomously after START

Treat START-after technical intervention as a product failure. Plan and cross
internal work segments, run real business checks, repair safe implementation
failures, and continue without asking the user to restart a milestone,
Verifier, Worker, or task. Do not repeat an irreversible effect when its result
is unknown.

### Leave identity and wake-up to Host

Use the current Codex task/thread as the business execution identity. Use only
Host-native heartbeat scheduling and same-thread turn reentry for a natural
wait, and read back the exact target before committing to the wait. Do not
create a new task or a second worker thread to simulate continuation.

For a natural wait, keep at most one owner-only, human-readable effect fact
containing the business identity, `not_before`, known effect key and digest,
next acceptance, and known effects. On reentry, verify that same fact and the
business effect before continuing. If an effect is known and matches, do not
repeat it; if it is unknown, perform an emergency stop rather than a blind
retry.

Host idle/active is not a business state. Derive the waiting explanation,
effect count, business Gate, and final report from the same effect fact and
real business readback; never invent a separate PAUSED/Active projection.

### Stop only at a true business Gate

Ask the user only for a value judgment or authority that cannot safely be
decided in advance, such as changed scope, new cost, publication, deployment,
deletion, a required secret available only at that stage, final content
approval, or acceptance of a lower result claim. Report the completed result,
the one decision, the recommended option, and each option's impact. Continue
the same task/thread after the answer unless the final intent itself changes.

PATH repair, contract-authorized local permission repair, scratch, ports,
process or Verifier restart, internal milestones, Host plumbing, and route
changes inside the authorized contract are never business Gates. New
permissions, external authorization, or any expansion of authority remain true
business Gates.

### Use emergency stop as the safety brake

Stop when an irreversible effect may have happened but cannot be confirmed,
when workspace or identity changed without authorization, when authoritative
evidence is damaged, when a new safety risk makes continuation unsafe, or when
an authorized resource limit is exhausted and continuation needs new
authority. Preserve observed effects and failed identities; never relabel the
stop as success.

## Report the business result first

Lead with whether the final intent was achieved and the exact business layer
reached. Then state what was and was not completed, observed facts versus
inference and unknowns, real journey evidence, external effects, limitations,
and the single business decision needed, if any. A test count, state label,
receipt, artifact, or Host activity is never a substitute for the business
outcome.

If emergency stop occurred, report the stop layer, completed and incomplete
business results, known and unknown external effects, recoverability, and why
the risk was not discoverable before START.

## Mechanism boundary

Do not add or depend on a LoopSkill-owned Controller, state machine, schema,
database, daemon, queue, router, general Host adapter, general retry system,
compatibility layer, migration path, or second status projection. Add no
runtime or helper merely because a future journey might need it; require a
current real journey failure first.
