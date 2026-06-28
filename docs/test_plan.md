Status: current

# Test Plan

Primary local checks:

```bash
PYTHONPATH=src python -m py_compile <changed python files>
PYTHONPATH=src python -m unittest discover -s src/lib_guard/test -p "test*.py"
PYTHONPATH=src python -m lib_guard.cli --help
PYTHONPATH=src python -m lib_guard.short_cli --help
scripts/lg.csh --help
```

For renderer changes, regenerate a catalog under `work/` and inspect the HTML.
For review gate or release gate changes, include
`src.lib_guard.test.test_review_gate`.

Repository cleanup is guarded by tests that check current docs for status
headers and user-facing files for stale workflow text.
