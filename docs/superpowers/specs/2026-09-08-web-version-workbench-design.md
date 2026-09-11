# Web Version Workbench Design

Status: current

## Goal

Make the Web Console let a library manager select one version, understand the
recommended next action, and run it without interpreting internal status
codes or remembering CLI options.

## Users and Decisions

| User | Decision | Minimum visible output |
| --- | --- | --- |
| Library manager | Which version needs work now? | Version work queue with one next action per row. |
| Library manager | What will the primary action do? | Target, comparison base, action explanation, and one primary button. |
| Library manager | Which scan evidence is worth paying for? | Per-run evidence policy and explicit view-type hash selection. |
| Library administrator | Which roots are candidates and which are registered libraries? | Separate registered-library and candidate tables. |

## Product Contract

1. The version list is a work queue, not a raw state table. It displays
   `version`, `role`, `current status`, and `next action`.
2. Selecting a version renders a current-processing card directly below the
   queue. It always shows target version, suggested comparison base, why that
   base was selected, and the primary action's exact effect.
3. The primary action is derived only from existing scan evidence, comparison
   base, and diff status. It never writes governance or effective-version
   state.
4. Release checking remains available but is a low-frequency management
   action, not a version work-queue column or the default action.
5. Scan evidence controls are per-run overrides. They never modify workspace
   defaults unless a separate configuration feature is requested later.
6. Hash selection is view-type based. Per-file hash checkboxes are forbidden;
   they are unbounded on large libraries and unsuitable for audit.
7. Candidate discovery and registered libraries are distinct datasets and
   receive distinct tables. The left rail remains navigation only.

## Type-Level Hash Policy

The existing global policies remain valid:

| Policy | Meaning |
| --- | --- |
| `none` | Do not compute content hashes. |
| `smart` | Preserve existing small-file and heavy-format rules. |
| `full` | Compute content hashes for all files. |

Two optional per-run lists extend, rather than replace, that policy:

```text
force_hash_file_types: selected canonical file types
skip_hash_file_types: selected canonical file types
```

Decision order is exact: `none` policy, skipped type, forced type, `full`
policy, existing `smart` policy. A selected forced type therefore gives a
manager stronger evidence for a relevant view without forcing full hashes for
the rest of the library.

The Web Console exposes common types as checkboxes: LEF, Liberty, Verilog,
SDC, and technology configuration. Heavy binary types GDS, OAS, and DB are
shown separately and require an explicit expert confirmation before they can
be forced. This iteration does not add workload prediction because the first
scan has no inventory from which to calculate a reliable estimate.

## Information Architecture

```text
Version work queue
  selected row
  current-processing card
  advanced scan / compare actions

Management
  Registered libraries table
  Candidate libraries table
  Add known library
  Review and effective-version controls
```

### Work Queue States

| Condition | Current status | Next action |
| --- | --- | --- |
| No scan evidence | Not scanned | Scan version |
| Scan evidence and comparison base, no diff | Ready to compare | Compare target and base |
| Scan evidence and no base | First-version facts ready | Open scan result |
| Diff exists | Review facts ready | Open version detail |
| No usable base | Base needs confirmation | Choose comparison base |

## Out of Scope

- No new CLI verbs or workflow state machine.
- No changes to catalog, diff, release, or effective-version facts.
- No automatic full hashing of GDS/OAS/DB.
- No persistent Web-only settings or a second review decision model.

## Acceptance Criteria

1. A manager can identify and start the next action from a selected version
   without expanding advanced controls.
2. The visible action describes scan, compare, first-version handling, or
   detail opening accurately.
3. Explicit type forcing overrides smart hash skips; skip types override all
   hashing except the global `none` policy.
4. Registered-library rows and candidate rows are shown in separate tables.
5. Existing CLI defaults and existing `smart` behavior remain unchanged when
   no new options are supplied.
