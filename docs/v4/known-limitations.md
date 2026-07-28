# LoopSkill 4 known limitations

- Only the Codex Host Adapter is supported in 4.0. The Kernel is host-neutral,
  but there is no multi-host support claim before a second real Adapter passes
  conformance.
- SQLite and Codex do not share one transaction. LoopSkill does not promise
  cross-system exactly-once across SQLite, Codex, Git, or network boundaries.
  External outcomes can remain `UNKNOWN`.
- The 4.0 Provider owns one foreground `codex exec --json` process and accepts
  only its directly captured terminal stream. It does not promise a
  Desktop-visible saved project/task, provider idempotency, cross-process Host
  readback, or automatic `exec resume`. Lost process/stream evidence remains
  `UNKNOWN` with no resend.
- Cooperative Host evidence can close work with a visible limitation, but it
  cannot become strict Host-attested assurance. Missing capability is reported
  as unavailable or `UNVERIFIABLE`.
- Host memory isolation is represented only to the strength the Host actually
  exposes. LoopSkill cannot prove isolation the Host cannot attest.
- The artifact libraries enforce tested path, symlink, case-fold, special-file,
  size, and open/read-race boundaries. They are not a general filesystem
  sandbox or a distributed content store.
- Standard and Adaptive policy constrain sequencing and repair; they do not
  prove the target task is achievable or that a model will produce a correct
  patch.
- Repository tests and a disposable foreground Codex exec canary do not prove empirical
  patch-success superiority, arbitrary long-horizon efficacy, or production
  reliability for every project.
- v4 cannot open, import, repair, run, or automatically migrate v3 roots,
  state, Controller Packs, MCP state, or CLI data. Use the independent
  [v3.3.8 release](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)
  for old data.
- Uninstall removes only receipt-bound v4 files. It does not restore or convert
  v3 data and does not alter unrelated Codex configuration.
- A first official Codex invocation in a fresh workspace may append one
  Host-owned `trust_level = "trusted"` project record to Codex configuration.
  LoopSkill does not prewrite or remove it. Release validation accepts only the
  exact current canonical disposable-workspace EOF append and rejects every
  other config or auth delta.
