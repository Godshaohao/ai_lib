# Tests

The active automated tests for `lib_guard` live under:

```text
src/lib_guard/test/
```

Run:

```powershell
$env:PYTHONPATH='src'
$PY='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $PY -m unittest discover -s src\lib_guard\test -p 'test*.py'
```

This directory is reserved for future repository-level integration fixtures that are not tied to the Python package layout.
