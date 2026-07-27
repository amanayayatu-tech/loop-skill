# LoopSkill 4 RC known limitations

- The candidate does not prove improved patch success, long-horizon
  superiority, or production effectiveness.
- Codex is the only supported Host Adapter. The Kernel is host-neutral, but no
  multi-host claim is allowed before a second real Adapter passes conformance.
- Codex does not expose a transaction shared with local SQLite. Cross-system
  exactly-once is not claimed; some outcomes remain `UNKNOWN` or
  `UNVERIFIABLE`.
- Host memory isolation is reported only as available, unavailable, or
  unverifiable. The Adapter does not invent isolation the Host cannot attest.
- SQLite conformance covers the tested local macOS filesystem, bounded writer
  contention, backup/readback and corruption cases. It is not a distributed
  database claim.
- v3 compatibility is read/shadow/import/export only and sunsets after one
  major cycle subject to a separate author decision. There is no canonical
  dual write or reverse conversion.
- The public stable line remains v3.3.8. This local candidate is neither tagged
  nor released and must not replace the current user installation.
- The one real App canary is a disposable conformance/usability observation,
  not research evidence or a guarantee for arbitrary real projects.
