# LoopSkill 4 release acceptance boundary

LoopSkill 4.2.0 is publicly released only after the exact merged-main commit,
annotated `v4.2.0` tag, tag CI, and public GitHub Release have all been read
back. A local candidate, RC packet, exec canary, pushed branch, merged PR, or tag
alone is not a release.

## Candidate gates

v4.2.0 has no version-scoped exception. It requires the deterministic and
distribution gates plus three ordered exact-SHA canary layers: base 2+8 Host
routes, a long-horizon recovery scenario, and a disposable Nepha copy. A failed
identity remains terminal predecessor evidence and is never relabeled or
reused.

- every v4 protocol, Store, Artifact, Adapter, Entry, policy, projection,
  distribution, fault, liveness, cost, UX, preservation, and hard-break case;
- acyclic import graph, one writer, generated wire literals, and minimal-profile
  execution with optional policy unavailable;
- v4-only isolated install/uninstall on Linux and macOS, source/install drift
  zero, `config.toml` byte-identical, zero MCP registration/process, no
  LoopSkill-required App restart, conflict rejection, and fault rollback;
- privacy-safe risk/audit/archive/metrics, secret/private-path/raw-identity/
  large-artifact scan, dependency/license inventory, and SBOM;
- bilingual README parity, real command syntax/smoke, local links, exact
  4.2.0 version/changelog/release-note identity, and no stale v3 current-product
  wording;
- content-addressed PlanDocument/PlanIndex parity, 1/4/8/16/32 Goal capacity,
  33-Goal and prompt-overflow zero-effect rejection, canonical property/fuzz,
  two-process activation concurrency, crash/replay, privacy, and closed
  `EAGER_V4_0` continuation;
- exactly two disposable, non-research foreground Codex exec routes on the same
  exact candidate: fresh 2-Goal first, then fresh 8-Goal only after PASS, for at
  most 10 invocations and two hours. Both require zero-effect intake and
  prepare, explicit digest-bound confirmation, one fresh Provider per Goal,
  minimal artifact/review/finalization, no
  MCP, no restart, no provider resend, and no real v3/user/private data. The
  distribution is independently installed and uninstalled in an isolated home,
  while the ten bounded model turns use an already-authenticated official Host
  context without copying credentials. Before any Host effect, each route binds
  the live canary module to the clean exact commit tree. Host auth must remain
  unchanged, while Host config may either
  remain unchanged or gain exactly one EOF-appended trusted-project stanza for
  the exact canonical disposable workspace, with the real nonzero delta bound
  into private measurement and the minimized receipt;
  the official `--output-schema` plus `--output-last-message` paths must yield
  exactly one schema-valid outcome/summary object whose schema and canonical
  result digests are bound to private evidence; JSONL is lifecycle-only, bounded
  stderr is diagnostic, and no `agent_message`/text-marker fallback or raw
  public transcript is allowed;
- a deterministic long-horizon canary proving continuous advancement,
  same-Loop repair, persistent terminal readback, one recorded session resume,
  human/time/budget waits, optional skip, multi-Loop selection, exact command
  verification, and loopback HTTP smoke;
- a disposable Nepha copy proving Chinese-path startup, tests, listener and
  four routes, with no write to the real Nepha project;
- independent read-only architecture, UX, installer, CI, privacy, artifact,
  preservation, and documentation review bound to the same SHA.

## Conformance and receipts

`scripts/run_v4_conformance.py` emits exactly 349 semantic coverage mappings
bound to exactly 74 unique, actually executed deterministic assertion methods.
It sets `independent_case_observation_claimed=false`; the mappings are not 349
independent executions or runtime observations. Zero-test loads, skipped
required tests, foreign case IDs, changed catalog digests, mapping or executed-
method count drift, stronger observation claims, and missing results fail. The
two real exec canaries consume typed fixture authorities instead of
reconstructing protocol literals. `UX-009-a` binds the 2-Goal receipt and
`CAP-RELEASE-CANARY` binds the 8-Goal receipt; their total Host invocation count
is exactly 10. Their public receipts contain no absolute private path,
task/thread/turn identity, prompt, transcript, secret, or raw log.

The minimized canary JSON is not self-authenticating and cannot satisfy the
final gate alone. Final validation opens the exact disposable v4 store and recomputes
the closed same-process evidence binding; it does not start another process or
claim post-process Host readback. A domain-separated attestation binds the
candidate goal digest, hashed machine-emitted identity, Host-result digest,
canonical snapshot digest, Result/Artifact/Review/Finalization states, and
STRICT chain closure. The disposable store and raw Host identity remain local
and are never committed or attached to the public Release.

Historical P6 compatibility and earlier P8 candidate evidence remain immutable
predecessor evidence only. They are explicitly excluded from current v4
acceptance. The active release gate requires the stable zero-write
`USER_UNSUPPORTED_LEGACY_VERSION` boundary and absence of v3 importer/runtime/
MCP/Pack/State-Writer/dual-write production surfaces.

The final local validator emits
`LOOPSKILL_4_2_PUBLICATION_CANDIDATE_VALIDATED`, not a publication claim. Only
the GitHub readback at the end of this document establishes that 4.2.0 is
public, latest, and non-prerelease.

## Publication gates

Before external Git writes, fetch origin/tags, integrate any main drift
non-destructively, confirm intended clean diff and no v4.2.0 tag/Release, and
rerun affected gates. The feature branch must pass v4 PR CI before a
non-destructive merge. The merged-main SHA is separately verified with all
three canary layers. Annotated tag CI must pass
before creating GitHub Release 4.2.0 as latest
and non-prerelease.

Final readback binds Release URL, tag object and peeled commit, verified main
commit, tag CI, asset names/sizes/digests, default branch, and unchanged v3
tags/Releases. Failures and `UNKNOWN` remain visible; none may be removed or
retried merely to obtain PASS.
