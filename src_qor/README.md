# ai_lib IP Review Tools

`src_qor` contains standalone IP library review scripts, a per-IP report runner, and an independent local review workbench. The workbench owns its Flask app, templates, CSS, and JavaScript; it does not mount into or import the legacy Catalog/Web application and does not run or expose the old Scan or Diff commands.

## Scope

The runner selects only the checks listed for each IP in YAML:

| Config key | Script | Purpose |
| --- | --- | --- |
| `formal_nl` | `lib_guard/effective_file_tracker.py` | Read-only inventory of formal NL links, their RAW origins, views, and path-based version references. |
| `macro_index` | `lib_guard/macro_index.py` | Builds a Macro-to-View index from a FileMap and parser facts, or directly from a selected IP root. |
| `lef_review` | `lib_guard/lef_review.py` | Compares two selected LEF files and extracts Macro/interface/geometry evidence. |
| `lef_liberty_check` | `lib_guard/lef_liberty_check.py` | Checks selected Liberty files against the bound LEF evidence, independently per file. |

These are evidence checks, not a release gate. `COMPLETE` means the selected script ran and produced a report; it does not mean the IP passed quality review or is approved for release. Checks not selected are `NOT_RUN`.

## Install and run

Requires Python 3.11 or newer. `Flask` is needed only for the local workbench; CLI report generation needs PyYAML and XlsxWriter.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r src_qor/requirements.txt
PYTHONPATH=src_qor python -m lib_guard.review_runner \
  --config src_qor/configs/review.example.yml \
  --out-dir work/ip_review_run
```

Start the local workbench with a persistent IP registry:

```bash
PYTHONPATH=src_qor python -m lib_guard.workbench \
  --registry ../3rd_IP/configs/ip_registry.simulation.yml \
  --out-dir work/ip_review_simulation \
  --port 5084
```

This command opens the multi-Vendor/multi-version Catalog simulation from the main `3rd_IP` tree. `SIMULATION_*` marker files are not valid IP data. Use `src_qor/configs/ip_registry.example.yml` only when creating a separate real registry.

Open the port selected with `--port` (the simulation command above uses `http://127.0.0.1:5084/`). The standalone workbench has separate tabs for the registered library/version overview, RAW discovery, read-only Formal NL inventory, and engineering checks (with nested configuration/history tabs). RAW discovery follows the previous Catalog/Discover model: it recursively finds library roots whose direct children are delivery/version directories, retaining the relative `Vendor / middle_path / Library / Version` hierarchy. It accepts one-version libraries and summarizes view types from filenames only.

Formal NL inventory is per IP and read-only. Enter the formal NL root and run a scan to list matching `lib_NL*` stages, IP link targets, visible file counts by View, filename-based Liberty/DB Corner clues, and the associated RAW source paths where resolvable. Stage order is inferred from the formal directory names and is a browsing aid, not an accepted Effective pointer. The inventory does not read file contents, validate required views or semantic correctness, change links, or approve release. JSON and Markdown snapshots are stored under `<out-dir>/formal_nl/<library-id>/runs/`; the last successful snapshot remains available if a later refresh fails.

Each Discover run writes the legacy-style candidate artifacts under `<out-dir>/discovery/`: `library.list` (editable review snapshot), `library_discovery.json` (candidate data and traversal statistics), and `library_discovery.html` (human-readable candidate table). The workbench exposes links to these artifacts. A candidate enters the Catalog overview only after explicit registration; registration updates the YAML registry with Vendor/group/library/version metadata. Discover and registration do not rename, move, copy, parse, or link files under the RAW root. Therefore `3rd_IP` retains its source hierarchy; the Catalog hierarchy is a view of the registry, not a physical reorganization.

The left rail searches registered libraries grouped by Vendor. Each registered library keeps the complete `raw_versions` list and absolute paths; no version is automatically declared newest. Check inputs expand only when selected. The workbench binds to loopback, saves library/check inputs back to the YAML registry, and invokes the same runner used by the CLI. A run is synchronous in the current version: the browser request waits for the selected checks to finish. It does not accept shell commands, modify formal NL links, or change release decisions.

The example config uses placeholder absolute paths. Replace them with paths readable by the host running the checks. Relative paths in YAML are resolved from the YAML file's directory.

## Configure checks

Each `ips[]` entry represents one IP context. Keep different IPs in separate entries with unique `id` and `library_id` values. The workbench registry is the persistent IP roster; `latest.json` is updated only when explicitly enabled and every selected check completes. The output contains a separate review record, evidence directory, and Excel workbook per IP; the HTML index keeps all registered IPs visible and does not combine IP findings.

`checks` is an allowlist for the current run. Omit a check to leave it `NOT_RUN`. For example, a LEF-only review can omit all other checks. When both `lef_review` and `lef_liberty_check` are selected, the runner executes LEF first regardless of YAML order and binds the Liberty report to that LEF's path and SHA-256. To reuse LEF evidence by itself, provide `lef_analysis_json` and a matching `lef_library_id`.

## Output layout

```text
work/ip_review_run/
  ip_checks/index.html                  # IP navigation; no merged findings
  libraries/<library-id>/
    latest.json                         # only when explicitly enabled and successful
    runs/<review-id>/
      review_result.json                # review_result.v1 for one IP
      ip_review.xlsx                    # workbook for this IP only
      evidence/                          # selected check snapshots and reports
```

History is retained by unique `review_id`. `review_result.json` is written only after the workbook has been exported and verified; `latest.json` is atomically updated only when that IP sets `publish_latest: true` and every selected check completes. A failed run does not replace a previous latest pointer. The formal NL tracker reads its configured paths and writes reports under the run output; it does not write to the formal release tree.

Each check result records its input identity. If explicit source versions differ from the IP's declared RAW version, the record is labeled `MIXED_EXPLICIT`; results remain separately scoped and are not silently merged. `COMPLETE` describes execution only. The ten-item engineering checklist separates selected evidence coverage from task execution and does not turn unselected or partially supported checks into passes.

## Tests

```bash
PYTHONPATH=src_qor python3 -m unittest discover -s src_qor/test -v
```

Tests cover IP isolation, selected-check reporting, failed-check QA, finding counts by stable kind/object count, explicit input identity, atomic report publication, the ten engineering topics, vertical Macro-View file mappings, persistent registry overview, local workbench asset isolation and save/run/download behavior, LEF/Liberty evidence binding, workbook sheets, and HTML report links.
