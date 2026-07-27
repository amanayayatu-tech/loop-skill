# LoopSkill 4 release acceptance boundary

LoopSkill 4.0.0 is publicly released only after the exact merged-main commit,
annotated `v4.0.0` tag, tag CI, and public GitHub Release have all been read
back. A local candidate, RC packet, App canary, pushed branch, merged PR, or tag
alone is not a release.

## Candidate gates

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
  4.0.0 version/changelog/release-note identity, and no stale v3 current-product
  wording;
- one disposable, non-research Codex App canary on the exact candidate:
  zero-effect intake and prepare, explicit digest-bound confirmation, one
  machine-owned task start/readback, minimal artifact/review/finalization, no
  MCP, no restart, no provider resend, and no real v3/user/private data;
- independent read-only architecture, UX, installer, CI, privacy, artifact,
  preservation, and documentation review bound to the same SHA.

## Conformance and receipts

`scripts/run_v4_conformance.py` emits one result for each frozen case ID after
running its bound unittest. Zero-test loads, skipped required tests, foreign
case IDs, changed catalog digests, and missing results fail. The real App
canary consumes typed fixture authorities instead of reconstructing protocol
literals, and its public receipt contains no absolute private path, task/thread/
turn identity, prompt, transcript, secret, or raw log.

That minimized JSON is not self-authenticating and cannot satisfy the final
gate alone. Final validation also opens the exact disposable v4 store and
performs a fresh authoritative app-server readback of the machine-owned Host
task and lifecycle. A domain-separated live attestation binds the candidate
goal digest, hashed Host identity, Host-result digest, canonical snapshot
digest, Result/Artifact/Review/Finalization states, and STRICT closure. The
disposable store and raw Host identity remain local and are never committed or
attached to the public Release.

Historical P6 compatibility and earlier P8 candidate evidence remain immutable
predecessor evidence only. They are explicitly excluded from current v4
acceptance. The active release gate requires the stable zero-write
`USER_UNSUPPORTED_LEGACY_VERSION` boundary and absence of v3 importer/runtime/
MCP/Pack/State-Writer/dual-write production surfaces.

The final local validator emits
`LOOPSKILL_4_0_PUBLICATION_CANDIDATE_VALIDATED`, not a publication claim. Only
the GitHub readback at the end of this document establishes that 4.0.0 is
public, latest, and non-prerelease.

## Publication gates

Before external Git writes, fetch origin/tags, integrate any main drift
non-destructively, confirm intended clean diff and no v4.0.0 tag/Release, and
rerun affected gates. The feature branch must pass v4 PR CI before a
non-destructive merge. The merged-main SHA is separately verified and canaried,
then annotated tag CI must pass before creating GitHub Release 4.0.0 as latest
and non-prerelease.

Final readback binds Release URL, tag object and peeled commit, verified main
commit, tag CI, asset names/sizes/digests, default branch, and unchanged v3
tags/Releases. Failures and `UNKNOWN` remain visible; none may be removed or
retried merely to obtain PASS.
