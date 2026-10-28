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

## Run with the configured Python

Requires Python 3.11 or newer. Use the host's existing interpreter with PyYAML and XlsxWriter; Flask is needed for the local workbench. Do not switch to a virtual environment or another `python3` alias between the workbench and the exporter. `requirements.txt` lists dependencies but is not an installation step for managed hosts.

```bash
export SRC_QOR_PYTHON=/absolute/path/to/configured/python3
"$SRC_QOR_PYTHON" -c 'import sys, yaml, xlsxwriter, flask; print(sys.executable, xlsxwriter.__version__)'
PYTHONPATH=src_qor "$SRC_QOR_PYTHON" -m lib_guard.review_runner \
  --config src_qor/configs/review.example.yml \
  --out-dir work/ip_review_run
```

Start the local workbench with a persistent IP registry:

```bash
PYTHONPATH=src_qor "$SRC_QOR_PYTHON" -m lib_guard.workbench \
  --registry ../3rd_IP/configs/ip_registry.simulation.yml \
  --out-dir work/ip_review_simulation \
  --port 5084
```

This command opens the multi-Vendor/multi-version Catalog simulation from the main `3rd_IP` tree. `SIMULATION_*` marker files are not valid IP data. Use `src_qor/configs/ip_registry.example.yml` only when creating a separate real registry.

Open the port selected with `--port` (the simulation command above uses `http://127.0.0.1:5084/`). The standalone workbench has separate tabs for the registered library/version overview, RAW discovery, read-only Formal NL inventory, and engineering checks (with nested configuration/history tabs). RAW discovery supports both `Vendor/Library/Date/View` and `Vendor/Group/Date/[intermediate]/Cell/View` layouts. It accepts one-version libraries and summarizes view types from filenames only. An ambiguous single wrapper below a date remains a review candidate instead of being silently treated as a Cell library.

Formal NL inventory is per IP and read-only. Enter the formal NL root and run a scan to list matching `lib_NL*` stages, IP link targets, visible file counts by View, filename-based Liberty/DB Corner clues, and the associated RAW source paths where resolvable. Stage order is inferred from the formal directory names and is a browsing aid, not an accepted Effective pointer. The inventory does not read file contents, validate required views or semantic correctness, change links, or approve release. JSON and Markdown snapshots are stored under `<out-dir>/formal_nl/<library-id>/runs/`; the last successful snapshot remains available if a later refresh fails.

Each Discover run writes only `<out-dir>/discovery/library_discovery.json` by default; the candidate table is already shown in the workbench. HTML and `library.list` are generated on demand from that JSON when their export links are opened. A candidate enters the Catalog overview only after explicit registration; registration updates the YAML registry with Vendor/group/library/version metadata. Discover and registration do not rename, move, copy, parse, or link files under the RAW root. Therefore `3rd_IP` retains its source hierarchy; the Catalog hierarchy is a view of the registry, not a physical reorganization.

The left rail searches registered libraries grouped by Vendor. Each registered library keeps the complete `raw_versions` list and absolute paths; no version is automatically declared newest. Check inputs expand only when selected. The workbench binds to loopback, saves library/check inputs back to the YAML registry, and invokes the same runner used by the CLI. Checks run in a bounded in-process queue (two workers, at most eight queued/running tasks); task state is persisted as JSON and can be polled after leaving or refreshing the page. A process restart does not resume queued work; the next read marks an old queued/running task `INTERRUPTED` and asks the operator to resubmit. The overview distinguishes the latest attempt from the latest successful result. The service does not accept shell commands, modify formal NL links, or change release decisions.

The left rail also has an exact library selector; it combines with Vendor, text search, and RAW/Formal scope. Formal NL inventory is a separate page action, not a manual Review check; it reads the selected formal root, writes its own JSON/Markdown snapshots, and does not enter the per-IP technical Review workbook. The Review runner accepts Macro Index, LEF Review, and LEF–Liberty checks only. No generated configuration is written to RAW or Formal NL input directories.

Choose a RAW version in the library list to open the review form with that version's Macro Index root and source version filled in for this run. Saved reports are cleared from this temporary selection so the chosen version is actually inspected. Save Configuration is explicit; Run does not rewrite the registry. Formal NL browsing keeps a separate latest discovery snapshot; a selected stage only updates the successful check pointer when the single-stage report is `COMPLETE`. Discovery reports sampled filename limits and refuses colliding library IDs.

In the review tab, choose target and optional baseline RAW versions to list their LEF files and the target's Liberty files. Selecting a LEF fills its corresponding path input; checking Liberty files fills the multiline input. File listing is bounded and marked when incomplete. The operator still selects which checks to execute, and may enter an external path directly.

The review tab opens on **文件资产矩阵**. On first use, click **刷新 RAW 文件清单**; this establishes the read-only asset snapshot without requiring a Formal NL snapshot or Base/Target selection. The page reads the saved projection only after that; GET and Base/Target changes do not scan RAW. Delivery order uses explicit `delivery_order` when complete and unique, then unique date hints; otherwise the order is UNKNOWN. The main matrix shows each file's latest and previous distinct delivery, Formal source (when independently observed), delivery relation, content comparison, and quality-check status as separate dimensions. A later path occurrence is not a content comparison, replacement decision, or Effective/release conclusion. Multiple unresolved Formal NL stages affect only the Formal column; the tool will not pick the highest stage. Select locatable rows; **比较可选文件内容** is enabled only for confirmed Base/Target pairs, while **检查可选 LEF** can run a single latest LEF interface check when its target is uniquely known or a paired LEF review when Base/Target is selected. The source-tracking snapshot is stored at `<out-dir>/file_status/<library-id>/latest.json`. Choose **手动检查** for explicit Macro/LEF/Liberty inputs and **运行记录** for prior task results.

The file-status refresh also writes a separate `file_version_projection.v1` snapshot under
`<out-dir>/file_versions/<library-id>/runs/<snapshot-id>/projection.json`, with an independent
`latest.json` pointer. Base and target versions are explicit selections; inventory absence is
`UNKNOWN` when the relevant enumeration is incomplete. File-path association is not a content
comparison or an approved Effective decision. The workbench matrix displays that snapshot without
scanning on GET. Changing Base/Target uses snapshot-only range reprojection and retains
`source_snapshot_id` as the actual RAW inventory evidence. A CLI review may explicitly provide `projection_json` in its IP entry; the runner
requires the IP and target RAW version to match and copies the projection into the review evidence.
Only such explicitly bound reviews receive the Excel file-version matrix. In the workbench,
select a base and target in 文件资产矩阵, apply the range without rescanning, and select up to 50 uniquely matched
LEF pairs for one background review, or compare up to 50 uniquely bound files in the matrix. The service revalidates every selection against the saved
source snapshot; batch results produce a separate review projection and individual evidence,
without modifying that source snapshot or the formal tree. Other Views remain not compared.
An incomplete batch retains completed pair evidence but does not replace the latest complete Excel.
Batch LEF and LEF–Liberty interface checks run separately to prevent accidental cross-file binding.

The **正式来源** view reads a saved Formal NL inventory without rescanning RAW. When more than one Formal stage matches, select the stage explicitly. In **交付对比**, the latest two deliveries are suggested only when their order is known. A scope change clears the previous scope's comparison results from the new projection; historical snapshots remain available. `source_snapshot_id` identifies the original RAW inventory and `input_snapshot_id` identifies the immediate input projection. The existing Formal-link API remains available for explicitly publishing a combined snapshot.

The review workspace offers three independent views: **文件定位** shows each file's latest and previous observations and exposes its history in the row; **交付对比** shows what two packages supplied and runs selected content or LEF-structure comparisons; **正式来源** reads a saved Formal NL inventory and compares its observed reference with the latest RAW occurrence. The Formal view requires explicit stage selection when more than one stage is observed. Viewing a saved inventory does not publish a new projection or rescan the RAW or Formal directories. Advanced manual checks and run history remain under **高级检查和历史**.

The normal user paths are:

- First delivery without Formal NL: register IP/RAW versions, refresh **RAW 文件清单**, inspect latest/previous, optionally choose Base/Target without another scan, compare selected content, then run the applicable LEF/Liberty check from the matrix.
- Existing Formal NL with a partial update: refresh RAW, optionally refresh/select one Formal stage, inspect latest/previous and Formal source in the same row, compare the selected deliveries, then run checks. A missing file in a partial package is not reported as deletion and the latest RAW source is not written as the Formal source.
- Single-file lookup: open the IP, search by filename or View, read latest/previous/Formal source, and run a single-file LEF interface check when the target is uniquely located; no delivery comparison is implied.

Each per-IP Review workbook also includes the most recent successful saved Formal NL and multi-version RAW file inventories in separate sheets (`07-正式文件`, `RAW文件清单`). These are read-only snapshot projections, not manual checks or quality findings; the workbook records snapshot time and report path. Export does not rescan the directories or establish whether their contents changed after that snapshot. If no matching snapshot exists, the sheets say so instead of reporting zero files.

The example config uses placeholder absolute paths. Replace them with paths readable by the host running the checks. Relative paths in YAML are resolved from the YAML file's directory.

## Configure checks

Each `ips[]` entry represents one IP context. Keep different IPs in separate entries with unique `id` and `library_id` values. The workbench registry is the persistent IP roster; `latest.json` is updated only when explicitly enabled and every selected check completes. The output contains a separate review record, evidence directory, and Excel workbook per IP; the HTML index keeps all registered IPs visible and does not combine IP findings.

`checks` is an allowlist for the current run. Omit a check to leave it `NOT_RUN`. For example, a LEF-only review can omit all other checks. When both `lef_review` and `lef_liberty_check` are selected, the runner executes LEF first regardless of YAML order and binds the Liberty report to that LEF's path and SHA-256. To reuse LEF evidence by itself, provide `lef_analysis_json` and a matching `lef_library_id`.

## Output layout

```text
work/ip_review_run/
  ip_checks/index.html                  # IP navigation; no merged findings
  libraries/<library-id>/
    latest.json                         # explicitly selected Review pointer, if enabled
    latest.xlsx                         # most recent fully completed per-IP workbook
    latest_workbook.json                # points to the run represented by latest.xlsx
    latest_attempt.json                # most recently submitted task, including failure
    tasks/<task-id>.json                # durable task status
    runs/<review-id>/
      review_result.json                # review_result.v1 for one IP
      ip_review.xlsx                    # workbook for this IP only
      evidence/                          # selected check snapshots and reports
```

History is retained by unique `review_id`. `review_result.json` is written only after the workbook has been exported and verified. Every fully completed run atomically refreshes that IP's stable `latest.xlsx`; incomplete runs preserve the previous workbook. The workbench calls this the most recent complete check report and exposes it with `ip_checks/index.html` without auto-downloading either. `latest.json` is a different pointer: the explicitly selected Review, updated only when that IP sets `publish_latest: true` and every selected check completes. A failed run does not replace either pointer; its task remains visible through `latest_attempt.json` and the task record. Workbook evidence links are relative to the corresponding `runs/<review-id>/` directory; absolute source paths remain in the evidence JSON. The formal NL tracker reads its configured paths and writes reports under the run output; it does not write to the formal release tree.

Each check result records its input identity. If explicit source versions differ from the IP's declared RAW version, the record is labeled `MIXED_EXPLICIT`; results remain separately scoped and are not silently merged. `COMPLETE` describes execution only. The ten-item engineering checklist separates selected evidence coverage from task execution and does not turn unselected or partially supported checks into passes.

## Tests

```bash
PYTHONPATH=src_qor "$SRC_QOR_PYTHON" -m unittest discover -s src_qor/test -v
```

Tests cover IP isolation, selected-check reporting, failed-check QA, finding counts by stable kind/object count, explicit input identity, atomic report publication, the nine current engineering topics plus legacy Formal NL projection, vertical Macro-View file mappings, persistent registry overview, local workbench asset isolation and save/run/download behavior, LEF/Liberty evidence binding, workbook sheets, and HTML report links.

## Project Design Knowledge

The incremental design map for data sources, review flow, audiences, reports, and validation is in [`design_knowledge/index.html`](design_knowledge/index.html). Its Markdown nodes are the editable source; the generated HTML is a read-only view. New or unreviewed design claims are labeled as proposed/unknown and are not approval records.
