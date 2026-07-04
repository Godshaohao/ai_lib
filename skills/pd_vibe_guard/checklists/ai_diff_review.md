# AI Diff Review Checklist

Use after AI modifies code.

## Boundary Check

- [ ] Did AI edit only allowed files?
- [ ] Did AI avoid parser/schema changes during UI tasks?
- [ ] Did AI avoid template/UI changes during parser tasks?
- [ ] Did AI preserve CLI parameters unless requested?
- [ ] Did AI avoid generated report files as source of truth?

## Scope Check

- [ ] Did AI avoid state machine/database/agent additions?
- [ ] Did AI avoid unused configuration?
- [ ] Did AI avoid generic framework code?
- [ ] Did AI avoid unrelated refactor?
- [ ] Did AI avoid changing data contracts unnecessarily?

## Minimality Check

- [ ] Is there a simpler standard-library solution?
- [ ] Can any helper be inlined?
- [ ] Can any class be replaced by a function?
- [ ] Can any new dependency be removed?
- [ ] Can any branch be removed because the state cannot happen in current scope?

## Validation

- [ ] Smoke test command provided.
- [ ] Sample input still works.
- [ ] Output artifact is generated.
- [ ] Main judgement is still visible.
