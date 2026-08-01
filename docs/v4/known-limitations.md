# LoopSkill 4 known limitations

- Only the Codex Host Adapter is supported in 4.2. The Kernel is host-neutral,
  but there is no multi-host support claim before a second real Adapter passes
  conformance.
- SQLite and Codex do not share one transaction. LoopSkill does not promise
  cross-system exactly-once across SQLite, Codex, Git, or network boundaries.
  External outcomes can remain `UNKNOWN`.
- Each Attempt uses one foreground `codex exec --json --output-schema
  --output-last-message` process and accepts only its captured terminal stream
  plus one schema-valid final outcome/summary object. Schema or result drift
  fails closed; there is no prose-marker fallback. Owner-only persistent
  controls allow terminal readback after controller restart and at most one
  recorded `codex exec resume` for a captured replay-safe session. A live
  process is waited on, and an unsafe external action requires a human gate;
  none of these paths promises a Desktop-visible saved project/task or remote
  exactly-once behavior.
- A confirmed plan contains 1–128 Goals, not an unbounded queue. Canonical plans
  are limited to 512 KiB, explicitly authorized text/Markdown sources to
  256 KiB, and materialized prompts to a 24 KiB release target / 32 KiB hard
  limit. Overflow is rejected before Host execution and is never truncated.
- Conversational answers exist only in the current pre-PREPARE session. There
  is no draft database or background intake service; after session loss the
  user must provide the input again.
- `EAGER_V4_0` compatibility is deliberately closed to status, export, and
  original-reducer continuation. There is no migration, rewrite, dual write,
  or conversion to `CONTENT_ADDRESSED_V1`.
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
- Repository tests, disposable 2/8-Goal foreground Host routes, the deterministic
  long-horizon canary, and the Nepha copy canary do not prove empirical
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
