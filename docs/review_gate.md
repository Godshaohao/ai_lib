Status: current

# Review Gate

Review Gate is a lightweight release-risk check. It is not a multi-department
approval workflow.

The gate separates:

| Output | Meaning |
| --- | --- |
| `blocking_items` | Real blockers for the selected gate, such as catalog trust problems, release fatal issues, or metadata-only binary changes that need owner acceptance |
| `attention_items` | Recommended evidence, such as focused File Diff tasks; these do not block `current` by default |
| `accepted_items` / `waived_items` | Owner decisions written through CLI commands |

Primary files:

```text
$WORK/catalog/html/catalog_state.json
$WORK/catalog/html/manager_tasks.json
$WORK/review/<library>/<version>/review_gate.json
$WORK/review/<library>/<version>/review_overrides.json
```

Normal commands:

```csh
$PROJ/scripts/lg.csh rv-check  <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-list   <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rv-waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
```

`lg.csh review` remains the action-file runner alias. Manual review decisions
use `rv-*` commands.

Release policy:

- `current` requires `review_gate.blocking_open == 0`.
- `current` does not require all File Diff recommendations to be complete.
- `approved` may require stricter deep diff or pairwise completion by policy.
- Release defaults to manifest-driven file-level symlink mode.
