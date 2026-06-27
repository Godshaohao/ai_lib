# Tests

The active automated tests for `lib_guard` live under:

```text
src/lib_guard/test/
```

Run:

```bash
PYTHONPATH=src python -m unittest discover -s src/lib_guard/test -p "test*.py"
```

This directory is used for repository-level integration fixtures that are not
tied to the Python package layout.

Integration fixture libraries live under `tests/fixtures/raw/` and are
registered through `tests/fixtures/raw/library_map.yml`. The fixture layout
mirrors production-style delivery roots:

```text
vendor/library/version/platform_source_package/
```

The OpenROAD platform fixtures are copied from OpenROAD-flow-scripts. Each
version directory has a `SOURCE.md` with the upstream commit and license
provenance.
