# Control-plane reliability fixtures

These fixtures preserve relationships from the real control-plane incident while
using synthetic identifiers and synthetic payload bytes. They contain no user
product content, provider response, credentials, database, rollout, or generated
Controller Pack.

- `transport-8265.json` preserves the exact frame size and open-pipe/PTY shapes.
- `attempt-reconciliation.json` separates product executions from control-plane
  rejections.
- `review-closeout-recovery.json` preserves stale-validation, ACKED-review,
  lease, freshness, history, and unknown-usage relationships.
- `pack-heartbeat-split.json` preserves a versioned canonical Pack versus legacy
  heartbeat prompt split while keeping one automation identity.
- `source-v3.2.4-baseline.json` freezes the exact `origin/main@v3.2.4` package
  manifest used to start remediation.

Regenerate or verify them with:

```bash
python3 tests/fixtures/control_plane_reliability/build_fixtures.py
python3 tests/fixtures/control_plane_reliability/build_fixtures.py --check
```

The builder derives the source baseline from the immutable Git object, and
asserts its aggregate manifest digest before writing any fixture.
