# LoopSkill 4 hard boundary and rollback

LoopSkill 4 uses semantic preservation with a runtime hard break.

## No v3 migration

v4 does not ship v3 read/shadow/import, existing-Pack repair, legacy CLI aliases,
the v3 97-field write API, Controller Pack execution, MCP State Gateway, or
State-Writer. It does not probe a v3 root for partial activation. A recognized
v3 root/state/Pack receives stable `USER_UNSUPPORTED_LEGACY_VERSION`, a direct
[v3.3.8 release](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)
link, and zero writes.

Historical P6 compatibility code and evidence are predecessor artifacts only.
They are excluded from v4 release acceptance and are not installed.

## v4 installation identity

The v4 installer owns `$CODEX_HOME/skills/loopskill4`,
`$CODEX_HOME/install-receipts/loopskill4`, and bounded v4 staging paths. It
never adds, changes, or removes `[mcp_servers.*]`; it preserves existing
`config.toml` bytes; it never overwrites `$CODEX_HOME/skills/codex-loop-prompt-architect`.
An occupied v4 target with different bytes fails before publication.

## Rollback

Uninstall consumes one exact receipt and refuses drift. Before commit, any
process fault restores the exact installed bytes; after commit, the exact
committed state has no v4 target. Config bytes and any independent v3 install
remain unchanged in both cases.

Rollback means uninstalling v4 and continuing to use an independently installed
v3.3.8 when desired. v4 never reverse-converts, repairs, restores, or migrates
v3 data.
