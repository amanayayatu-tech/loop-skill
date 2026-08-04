# Security policy

## Multi-product boundary

This repository carries the independent `loopskill5` Skill product and the
preserved LoopSkill 4.2 runtime. The root `VERSION=4.2.0`, `scripts/install.sh`,
`loopskill4`, and v4 data remain v4-only. The v5 public identity is only the
annotated `v5.0.0` tag, the exact `loopskill5/SKILL.md` and
`loopskill5/agents/openai.yaml` blobs at that tag, and the matching GitHub
Release. Source on a branch or an unpeeled tag is not a supported release.

LoopSkill 5 must not overwrite or discover v3/v4 installations or data, edit
Codex config, register MCP, create a daemon, or expand task authority. Its
recoverable uninstall boundary is the exact `loopskill5` directory only.

## Supported versions

Security support follows the versions listed on GitHub Releases.
When GitHub Releases lists LoopSkill 4.2.0, it is the supported public v4 line.
LoopSkill v3.3.8 remains an independent historical release; v4 does not repair
or migrate its data. No
paper-treatment or prerelease branch is promoted to a supported public line by
implication.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for
`amanayayatu-tech/loop-skill`. Do not open a public issue containing secrets,
private repository paths, Codex task/thread/turn identities, App transcripts,
personal data, or a working exploit against another user's installation.

Include the affected release/tag, platform, minimal reproduction, expected
fail-closed behavior, and whether an external action may already have occurred.
If outcome identity is uncertain, preserve it as `UNKNOWN`; do not retry a
provider action merely to reproduce the report.

## Product boundary

LoopSkill 4 owns only its distinct v4 installation, data root, and receipts. It
must not modify unrelated Codex config, register MCP, overwrite a v3 install,
start a daemon, require an App restart, or import v3 state. The Kernel trusts
only machine-constructed authority and verified receipts; model-authored
control identities have no authority. Plan content is private, content-addressed,
and admitted only through the confirmed 1–128 Goal capacity contract.

Security reports and fixes do not authorize publishing private evidence,
force-pushing, rewriting historical releases, or claiming cross-system
exactly-once.
