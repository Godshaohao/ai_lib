Status: archived
Archive reason: moved out of current lib_guard documentation.

---
name: policy-rule-update
description: Use when a one-time library identification, file type mapping, view mapping, vendor ignore rule, release target mapping, parser routing rule, or manual override should be converted into a stable project policy instead of remaining an ad-hoc AI judgment.
---

# Policy Rule Update

## Core Principle

Turn repeated human or AI judgments into explicit policy files. The first judgment may be assisted by reasoning; the second occurrence should become a rule.

This skill exists to make the library management system stable, repeatable, and reviewable.

## Policy Targets

Maintain or propose updates to:

- `catalog_policy.json`
- `file_type_map.yaml`
- `view_map.yaml`
- `vendor_ignore_rules.yaml`
- `release_target_map.yaml`
- `parser_registry.yaml`
- Catalog `manual_overrides`
- Catalog `runtime_state` rules, when separated from manual overrides

## Inputs

Accept any of:

- A misclassified library candidate.
- A directory that should always be ignored.
- A file extension or naming pattern that should map to a file type.
- A view folder that should map to a release target.
- A parser routing decision.
- A manual override that should become project policy.
- Diff or scan evidence showing repeated ambiguity.

## Rule Update Workflow

1. State the observed problem.
2. Identify whether it is a catalog, file type, view, parser, release target, or ignore-rule issue.
3. Locate the smallest policy file that should own the rule.
4. Propose a minimal rule change.
5. Show before/after classification behavior.
6. Call out blast radius and possible false positives.
7. Ask for confirmation before overwriting policy.

## Required Output

Always return five sections:

1. Conclusion
2. Evidence
3. Risks
4. Recommended Commands
5. Manual Confirmation

When proposing a rule, include a patch-style preview:

```json
{
  "policy_update": {
    "target_file": "configs/catalog_policy.json",
    "rule_type": "ignore_directory",
    "new_rule": {
      "pattern": "**/simulation_output/**",
      "reason": "simulation output is not a library version"
    },
    "expected_effect": {
      "previous": "candidate with low confidence",
      "after": "rejected as non-library directory"
    },
    "requires_confirmation": true
  }
}
```

## Rule Design Guidelines

Prefer narrow rules:

- Match vendor or library context when possible.
- Use explicit path segments instead of broad substrings.
- Separate ignore rules from view mapping rules.
- Keep manual overrides separate from runtime state.
- Add a reason for every rule.

Avoid broad rules:

- `*old*` as a global ignore.
- Mapping every `.txt` to release evidence.
- Treating every two-level directory as a version.
- Overwriting an existing policy block without explaining impact.

## Execution Policy

Default to proposing policy changes, not applying them.

May execute:

- Read policy files.
- Run dry-run catalog or scan checks.
- Generate patch previews.

Ask before executing:

- Any policy file write.
- Any migration that splits `manual_overrides` and `runtime_state`.
- Any rule that changes release target mapping.

Never execute automatically:

- Overwrite policy without confirmation.
- Delete existing rules.
- Bypass manual review.

## Boundaries

This skill does not decide release approval. It does not silently change behavior. It does not use AI judgment as a hidden long-term rule. It does not mix observed runtime status into manual policy.

## Common Mistakes

- Leaving repeated corrections as chat memory instead of policy.
- Making a broad rule from one example.
- Mixing manual override data with runtime scan/diff/release state.
- Updating parser behavior without updating the policy or test expectation that explains it.
