Status: current

# Deprecation Policy

Compatibility wrappers are allowed when old imports or workflows still need to
run, but each wrapper should have:

- current status
- replacement path
- reason for keeping it
- removal condition
- test coverage

Archived migration documents live under `docs/archive/`. Current docs should
not depend on archived instructions.

