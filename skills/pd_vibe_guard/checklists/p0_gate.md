# P0 Gate Checklist

A task can enter P0 only if these are clear:

- [ ] Target user is named.
- [ ] Main judgement is named.
- [ ] Current data source exists.
- [ ] Output artifact is clear.
- [ ] A user can inspect the output without running a platform.
- [ ] The task can ship without state machine/database/agent flow.
- [ ] The result page can answer the main judgement in about 3 minutes.

Reject or defer if:

- [ ] The requirement is mostly about future extensibility.
- [ ] The requirement is mostly about making the system feel complete.
- [ ] The data source cannot support the claim.
- [ ] The feature delays the first useful result page.
- [ ] A table/sort/filter/link/manual command can solve it for now.
