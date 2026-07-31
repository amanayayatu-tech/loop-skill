# LoopSkill v4.1 compatibility matrix

| Surface | EAGER_V4_0 input | CONTENT_ADDRESSED_V1 input | v4.1 write policy |
|---|---|---|---|
| Status | Supported | Supported | Read-only projection |
| Public/privacy export | Redacted compatibility projection | Redacted plan identity and capacity only | Never exports source digest, source path, raw PRD, or blob content |
| Explicit private backup | Full canonical SQLite backup | Full canonical SQLite backup including blobs | Owner-authorized destination only |
| Reducer continuation | Original v4.0 semantics | Lazy activation through existing `AdvanceGoal` | No migration and no dual write |
| CreateLoop | Rejected for new public starts | Required | One compact command |
| Authority | Existing exact subjects | Immutable `AuthorityGrantV2` plan selector | No post-create mutation |
| Adaptive revision | Existing objective envelope continuation | Reorder-only immutable PlanIndex | No Goal edits |
| v3 runtime | Unsupported | Unsupported | No restored controller, heartbeat, or State Gateway |

The public v4.0.0 annotated tag and its historical evidence remain unchanged.
This matrix describes the public v4.1.1 behavior; it does not authorize
migration, installation, publication, or deploy of any other product line.
