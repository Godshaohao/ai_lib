# Anti-Overengineering Checklist

Use this before accepting a design or AI-generated plan.

## Requirement Overdesign

- [ ] Is this helping a named user today?
- [ ] Does it directly improve the main judgement?
- [ ] Is it required for current P0 delivery?
- [ ] Is it supported by current data?

## Architecture Overdesign

Reject unless explicitly justified:

- [ ] state machine
- [ ] database
- [ ] service/API
- [ ] plugin system
- [ ] cache framework
- [ ] multi-role platform
- [ ] workflow engine
- [ ] agent orchestration
- [ ] complex configuration center

## Algorithm Overdesign

Reject unless validated:

- [ ] automatic root cause
- [ ] clustering
- [ ] scoring
- [ ] ranking
- [ ] prediction
- [ ] anomaly detection
- [ ] fuzzy matching
- [ ] AI inference

## Code Overdesign

Reject unless necessary:

- [ ] unused config
- [ ] new dependency
- [ ] generic abstraction
- [ ] unrelated refactor
- [ ] class hierarchy for one implementation
- [ ] broad exception swallowing
- [ ] future compatibility layer
