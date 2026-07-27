# LoopSkill 4 artifact capability boundary

## Ownership

Artifact capture is a library/port, not Kernel state-transition code and not a
Host Adapter. It accepts a machine-selected capability profile and a confined
root, then returns immutable content identities and a canonical manifest. It
does not write canonical loop state, infer review success, retry a Host effect,
or invoke a Supervisor.

Profiles are deliberately separate:

- `existing_git`: exact base commit, binary tracked patch, exact opt-in
  untracked boundary, explicit empty diff;
- `non_git`: before/after content manifests with explicit add/modify/delete;
- `new_git`: explicit init and branch grants, immutable non-Git baseline, then
  the existing-Git capture contract.

Every file and patch byte is stored under the selected store's immutable blob
boundary. The canonical bundle identity is itself stored as a blob. The
artifact digest binds profile, base identity, manifest, and patch identity; it
does not contain model-authored paths, SHAs, or receipts.

## Path and race rules

Paths are normalized POSIX-relative names. Absolute paths, `..`, backslashes,
control roots, duplicates, and case-fold aliases fail closed. Directory
traversal uses descriptor-relative opens with no-follow semantics. Symlinks,
special files, oversized files/sets, and before/read/after identity changes are
rejected. Git names and patches are captured twice; any boundary change is
`ARTIFACT_STALE` rather than an inferred success.

## v3.3.8 public provenance

No v3 state shape or private fixture was copied. The selected public semantic
sources are bound to commit
`843945d9d34e7f065b65d9172ea4a2df66c0f2e3`:

- `codex-loop-prompt-architect/scripts/loop_architect/state_runtime.py`
  Git object `450375ada1a28125143bda2084ccc11419453182`, especially
  `capture_complete_diff`, `_gateway_observed_identity_delta`, and
  `_gateway_current_product_snapshot`;
- `tests/test_state_runtime_io.py` Git object
  `8c168394b23d7be92d04792fdd41bf87f8996270`, specifically
  `test_runtime_captures_binary_diff_without_model_patch_transport`,
  `test_complete_diff_excludes_tracked_control_plane_paths`,
  `test_complete_diff_rejects_symlinked_control_capture_paths_without_outside_write`,
  and `test_successor_snapshot_must_still_match_declared_base_and_current_root`.

The v4 library retains binary-safe capture, exact untracked allowlisting,
control-plane exclusion, immutable content identity, and race/staleness
classification. It replaces v3's runtime-owned capture directory and monolithic
state coupling with returned immutable blobs and explicit capability profiles.

## Guarantee boundary

Passing these library cases proves deterministic capture on synthetic temporary
roots. It does not prove Host delivery, Git remote behavior, reviewer approval,
or patch effectiveness. New-Git initialization is an explicit mutation and is
never selected for an existing Git root or without both machine grants.
