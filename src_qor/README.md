# ai_lib IP Review Tools

`src_qor` contains standalone IP library review scripts and a per-IP report runner. It is separate from the legacy Catalog/Web workflow and does not run or expose the old Scan or Diff commands.

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

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r src_qor/requirements.txt
PYTHONPATH=src_qor python -m lib_guard.review_runner \
  --config src_qor/configs/review.example.yml \
  --out-dir work/ip_review_run
```

The example config uses placeholder absolute paths. Replace them with paths readable by the host running the checks. Relative paths in YAML are resolved from the YAML file's directory.

## Configure checks

Each `ips[]` entry represents one IP context. Keep different IPs in separate entries with unique `library_id` values. The output contains a separate immutable review record, evidence directory, and Excel workbook per IP; the HTML index is navigation only and does not combine IP findings.

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

History is retained by unique `review_id`. `latest.json` is written only when that IP sets `publish_latest: true` and every selected check completes. A failed run does not replace a previous latest pointer. The formal NL tracker reads its configured paths and writes reports under the run output; it does not write to the formal release tree.

## Tests

```bash
PYTHONPATH=src_qor python3 -m unittest discover -s src_qor/test -v
```

Tests cover IP isolation, selected-check reporting, explicit latest behavior, LEF/Liberty evidence binding, workbook sheets, and HTML report links.
