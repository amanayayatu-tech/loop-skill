# Evidence index

These records are immutable historical evidence. They preserve both failures and
successes and must not be rewritten to make a later result look cleaner.

| Date | Record | Result | Evidence ceiling |
| --- | --- | --- | --- |
| 2026-07-11 | [Adaptive App E2E](adaptive-app-e2e-20260711.md) | Bounded historical smoke | Not v3.2 acceptance |
| 2026-07-12 | [Initial v3.2 attempt](v32-app-e2e-20260712-failed.md) | Failed | Failure evidence only |
| 2026-07-12 | [Final attempt](v32-final-app-e2e-20260712-failed.md) | Failed | Failure evidence only |
| 2026-07-12 | [Replacement 01](v32-replacement-final-app-e2e-20260712-failed.md) | Failed | Failure evidence only |
| 2026-07-12 | [Replacement 02](v32-replacement-final-app-e2e-20260712-02-failed.md) | Failed | Failure evidence only |
| 2026-07-12 | [Replacement 03](v32-replacement-final-app-e2e-20260712-03-failed.md) | Failed | Failure evidence only |
| 2026-07-12 | [Replacement 04](v32-replacement-final-app-e2e-20260712-04-failed.md) | Failed and frozen | Failure evidence only |
| 2026-07-13 | [Transport canary](v32-app-transport-canary-20260713.md) | `CANARY_PASS` | Transport smoke only |
| 2026-07-13 | [Replacement 05](v32-replacement-final-app-e2e-20260713-05.md) | `FINALIZATION_ACKED` | Current-machine, root-confined bounded smoke only |

The final successful record does not constitute production, long-run,
cross-version, formal, science, or public acceptance. Historical absolute local
paths are retained because they are part of the frozen identity evidence; new
records should prefer stable variables such as `$ATTEMPT_ROOT` in public prose
while keeping authoritative digests and task identities in the evidence bundle.
