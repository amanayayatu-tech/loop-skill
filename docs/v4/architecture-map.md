# LoopSkill 4 RC architecture map

```text
Public Entry / composition root
  ├─ typed semantic Intake and digest-bound Prepare/Confirm
  ├─ Kernel ──> typed protocol + Store/Artifact/Host ports only
  ├─ SQLite Store ──> sole canonical transactional writer
  ├─ Artifact libraries ──> existing-Git / non-Git / new-Git capability ports
  ├─ Codex Host Adapter ──> task/thread/send/readback/capability receipts
  ├─ optional Policy ──> Standard / Adaptive / role / repair / human decision
  ├─ rebuildable projections ──> status/audit/archive/privacy/metrics/Doctor
  └─ one-major-cycle compatibility ──> v3 read/shadow/import and human exports
```

The Store does not call Host. Artifact and Host implementations do not write
canonical state. Policy submits authorized semantic commands only. Projection
deletion loses no authority. Compatibility cannot import into Kernel and never
dual-writes. The complete v4 import graph is acyclic and the minimal entry path
loads neither optional policy nor v3 compatibility.

External effects follow one durable Attempt identity. The executor claims that
Attempt once, consumes the one automatic-attempt budget immediately before the
provider call, and never reconstructs identity from model text or memory.
Provider idempotency plus authoritative readback permits “effectively-once”;
otherwise the only claim is “at-most-one automatic attempt; outcome may be
UNKNOWN.” A late authoritative observation may resolve the same UNKNOWN
subject but cannot authorize resend or rewrite a terminal disposition.

The v4 canonical state keeps orthogonal Lifecycle, Delivery/ExternalEffect,
Goal, Result/Report, Artifact, Review, Finalization and Assurance subjects under
one transactional authority. One authority does not mean one giant enum or one
physical event stream.
