# ADR 0006: Bind release evidence to the local main Mac and exact SHA

- Status: Accepted
- Date: 2026-07-16

## Context

CI, remote machines, historical App runs, and local source trees can differ in
artifact bytes, installation, host metadata, or App identity.

## Decision

The current main Mac is release authority. Release evidence binds one exact
commit, tracked-tree digest, installed manifest, Pack, App build, app-server
identity, and disposable canary receipt. GitHub Actions is a compatibility
mirror. Real user Loops are excluded from canary mutation.

## Consequences

New candidate or host identity requires new evidence. Local development tests
remain useful but cannot be promoted into a release claim.

## Evolution

Additional independent evidence may strengthen claims. Changing release
authority requires an explicit replacement ADR and updated release contract;
weaker or historical evidence cannot silently substitute.
