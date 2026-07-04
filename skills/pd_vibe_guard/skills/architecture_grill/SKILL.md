# Architecture Grill Skill

## Purpose

Interrogate proposed architecture before it enters implementation.

This skill is triggered only when a change introduces structural complexity: state machines, databases, services, multi-page systems, workflow orchestration, plugin frameworks, caches, configuration centers, or agent flows.

## First Principle

Architecture is justified only when it reduces current delivery/review cost more than it increases complexity.

In P0, the preferred architecture is usually:

```text
input file -> normalize/summary -> static HTML/report
```

## When To Use

Use when the proposal includes or implies:

- state machine
- database
- service/API/microservice
- auto-refresh daemon
- scheduler
- multi-role UI architecture
- plugin system
- generic workflow engine
- checkpoint/retry framework
- cache layer
- configuration center
- agent orchestration
- multiple generated pages beyond what the main judgement needs

## Architecture Adversarial Questions

1. Without this architecture, can the current result page still ship?
2. Which main judgement does this architecture directly improve?
3. Is current data volume/usage frequency large enough to require it?
4. Has this workflow been used repeatedly enough to justify automation?
5. Is the architecture solving a proven pain or a future imagined pain?
6. Can a static file, CSV, JSON, or simple command do the job?
7. Does this architecture mix concerns that should remain separate?
8. Does it delay the first useful review output?
9. Does it create new maintenance obligations for the user?
10. Can it be replaced by a manual step until the pain repeats?

## Decisions

- KEEP: architecture is necessary now
- CUT: architecture is unnecessary and should not be implemented
- DEFER: architecture may be useful later but not current version
- SHRINK: use a smaller architectural substitute

## Output Format

```markdown
## Architecture Grill Result

Proposed architecture:
Decision: KEEP / CUT / DEFER / SHRINK

Main judgement affected:
Evidence of necessity:
Complexity introduced:
Simpler substitute:
Forbidden architecture:
Allowed current architecture:
```

## Preferred Substitutes

Use these before adding heavy architecture:

| Heavy proposal | Substitute |
|---|---|
| database | CSV/JSON snapshot |
| service/API | static HTML generation script |
| scheduler | manual command + latest.html symlink/copy |
| state machine | status column in summary JSON/CSV |
| multi-role platform | one main page + secondary details section |
| plugin system | explicit function mapping |
| agent workflow | printed next-step command |
| cache framework | skip unchanged files with timestamp/hash if necessary |

## Examples

### FCT QoR State Machine

```markdown
Proposed architecture: Add run lifecycle state machine.
Decision: CUT
Main judgement affected: current run group/corner regression
Evidence of necessity: none; P0 only needs trend and latest table
Complexity introduced: states, transitions, persistence, UI state rendering
Simpler substitute: current_run field in config or CLI argument
Forbidden architecture: lifecycle state machine in P0
Allowed current architecture: read CSV -> summary -> static HTML
```

### Release Monitor latest.html

```markdown
Proposed architecture: Generate daily HTML and latest.html pointer.
Decision: KEEP
Main judgement affected: project owner needs latest status while preserving daily evidence
Evidence of necessity: report refreshes every 10 minutes; daily records must be retained
Complexity introduced: minimal file naming and copy/link
Simpler substitute: write daily file and copy to latest.html
Forbidden architecture: web service or database scheduler
Allowed current architecture: static daily file + latest.html
```
