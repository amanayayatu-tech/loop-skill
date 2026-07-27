# LoopSkill 4 RC acceptance boundary

`LOOPSKILL_4_0_RC_READY_FOR_AUTHOR_APPROVAL` means a fixed local candidate SHA
passed the frozen corpus. It does not mean stable, released, pushed, tagged,
published, installed for the user, or effective for long-horizon tasks.

The exact candidate gate requires:

- all v4 protocol, store, artifact, Adapter, Entry, compatibility, policy,
  projection, distribution, fault, liveness, cost, UX and preservation tests;
- acyclic import graph, one writer, generated wire literals, and minimal-profile
  execution with policy/compat unavailable;
- isolated install, source/install drift zero, exact Python and MCP registration
  readback, install conflict rejection, bounded rollback and uninstall;
- risk scan, privacy aggregate, secret and large-artifact scan, dependency and
  license inventory, and a machine-readable SBOM;
- one disposable, non-research App canary on the exact candidate:
  intake has zero side effect, prepare has zero Host effect, explicit
  digest-bound confirmation precedes one machine-owned task start/readback,
  and a minimal artifact/review/finalization reaches acknowledged closure;
- an independent read-only security, privacy, artifact, architecture and
  preservation review bound to the same SHA;
- an author packet containing every receipt, limitation, `UNKNOWN`, rollback
  instruction, compatibility statement and draft release note.

Use `scripts/validate_v4_rc.py --static-only` only before the App canary; it
always emits `rc_ready=false`. Final invocation omits that flag and must provide
`--canary-receipt`, `--conformance-receipt`, and `--author-packet`; any missing
receipt is a hard failure. `scripts/run_v4_conformance.py` emits one result for
each of the 343 frozen case IDs after running every bound test module.

The disposable canary must import the canonical encoder from the typed
protocol authority (`loop_architect.v4_alpha.protocol.canonical_bytes`). A
canary instruction that names an unbound helper module is apparatus failure,
not product PASS: preserve the failed receipt, do not retry that candidate, and
fix the instruction contract before creating a new exact candidate.

Any code change creates a new candidate SHA and reruns affected gates. Failure
and `UNKNOWN` evidence stays in the packet. The author alone decides whether a
future candidate may be tagged or publicly released.
