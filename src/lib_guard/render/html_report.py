"""Structure-first HTML rendering for lib_guard scan/diff outputs.

Current UI policy:
- Scan is a delivery inventory review page, not a parser result page.
- Diff is a selected-version structure delta page, not an all-pairs diff engine.
- Content-level review for LEF/GDS/DB/SDC/etc. is driven by generated commands and
  reviewer-side scripts after the diff report detects changed files.
- Parser details, raw JSON and low-level file lists are trace evidence only and are
  not promoted as page conclusions.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import html
import json
import os
import tempfile


IMPLEMENTATION_TYPES = {"verilog", "cdl"}
ABSTRACT_TYPES = {"lef"}
TIMING_TYPES = {"liberty", "lib", "db"}
CONSTRAINT_TYPES = {"sdc", "spef"}
POWER_TYPES = {"upf", "cpf"}
LAYOUT_TYPES = {"gds", "oas", "layout", "milkyway"}
BINARY_METADATA_TYPES = {"db", "gds", "oas", "milkyway"}
EVIDENCE_TYPES = {
    "doc",
    "package",
    "waiver",
    "readme",
    "release_note",
    "update_note",
    "changelog",
    "known_issue",
    "integration_guide",
}
COMMAND_REVIEW_TYPES = {"verilog", "lef", "liberty", "lib", "cdl", "sdc", "upf", "cpf"}

KEY_VIEW_ORDER = [
    ("verilog", "Netlist / Verilog", "Implementation / 实现"),
    ("lef", "LEF", "Abstract / 抽象"),
    ("liberty", "Liberty", "Timing / 时序"),
    ("db", "DB", "Timing / 二进制"),
    ("cdl", "CDL", "Implementation / 实现"),
    ("sdc", "SDC", "Constraint / 约束"),
    ("upf", "UPF", "Power / 电源"),
    ("cpf", "CPF", "Power / 电源"),
    ("spef", "SPEF", "Constraint / 约束"),
    ("gds", "GDS", "Layout / 二进制"),
    ("oas", "OAS", "Layout / 二进制"),
    ("release_note", "Release Note", "Doc / 证据"),
    ("waiver", "Waiver", "Doc / 证据"),
    ("readme", "README", "Doc / 证据"),
]

REVIEW_GROUP_ORDER = [
    "Implementation / 实现",
    "Abstract / 抽象",
    "Timing / 时序",
    "Layout / 版图",
    "Constraint / 约束",
    "Power / 电源",
    "Doc / 证据",
    "Binary / 二进制",
    "Other / 其他",
    "Unknown / 未识别",
]


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _file_href(path: Any) -> str:
    if not path:
        return ""
    try:
        return Path(str(path)).resolve().as_uri()
    except Exception:
        return str(path)


def _json_arg(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _json_preview(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _pct(part: int, total: int) -> int:
    return 0 if total <= 0 else int(round(part * 100 / total))


def _type_group(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    if key in IMPLEMENTATION_TYPES:
        return "Implementation / 实现"
    if key in ABSTRACT_TYPES:
        return "Abstract / 抽象"
    if key in TIMING_TYPES:
        return "Timing / 时序"
    if key in LAYOUT_TYPES:
        return "Layout / 版图"
    if key in CONSTRAINT_TYPES:
        return "Constraint / 约束"
    if key in POWER_TYPES:
        return "Power / 电源"
    if key in EVIDENCE_TYPES:
        return "Doc / 证据"
    if key in {"binary", "archive"}:
        return "Binary / 二进制"
    if key == "unknown":
        return "Unknown / 未识别"
    return "Other / 其他"


def _type_meaning(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    return {
        "verilog": "Presence is reported here. Content review is done by generated domain diff commands when this file changes.",
        "lef": "Presence is reported here. Do not trust rough parser output; use content-level diff command when changed.",
        "liberty": "Presence is reported here. Use generated timing/lib diff command when changed.",
        "lib": "Presence is reported here. Use generated timing/lib diff command when changed.",
        "db": "Binary/tool database. UI reports presence and metadata; content review is external/tool-specific.",
        "cdl": "Presence is reported here. Use generated netlist/circuit diff command when changed.",
        "sdc": "Presence is reported here. Use generated constraint diff command when changed.",
        "upf": "Presence is reported here. Use generated power-intent diff command when changed.",
        "cpf": "Presence is reported here. Use generated power-intent diff command when changed.",
        "spef": "Presence/metadata review only unless a dedicated external diff is provided.",
        "gds": "Binary layout. UI reports presence and metadata; content review is external/tool-specific.",
        "oas": "Binary layout. UI reports presence and metadata; content review is external/tool-specific.",
        "release_note": "Release evidence; review as release evidence rather than ordinary text diff.",
        "waiver": "Waiver evidence; review as release evidence.",
        "readme": "Integration/readme evidence; review as release evidence.",
        "unknown": "Unknown file type; update classifier rules or confirm it can be ignored.",
    }.get(key, "Auxiliary or project-defined delivery file type.")


def _type_counts(inventory: Mapping[str, Any], parser_manifest: Mapping[str, Any], dashboard: Mapping[str, Any]) -> dict[str, int]:
    # Prefer inventory/dashboard classification. Parser manifest is only a fallback for old runs.
    direct = inventory.get("file_type_counts") or (dashboard.get("counts") or {}).get("file_type_counts") or parser_manifest.get("file_type_counts")
    if isinstance(direct, Mapping):
        return {str(k): int(v or 0) for k, v in direct.items()}
    counts: Counter[str] = Counter()
    for item in inventory.get("files", []) or []:
        counts[str(item.get("file_type") or "unknown")] += 1
    return dict(counts)


def _group_counts(counts: Mapping[str, int]) -> dict[str, int]:
    grouped = {label: 0 for label in REVIEW_GROUP_ORDER}
    for k, v in counts.items():
        group = _type_group(k)
        grouped[group] = grouped.get(group, 0) + int(v or 0)
    return grouped


def _structure_cards(counts: Mapping[str, int]) -> str:
    grouped = _group_counts(counts)
    total = sum(int(v or 0) for v in counts.values())
    notes = {
        "Implementation / 实现": "Verilog / CDL delivery presence",
        "Abstract / 抽象": "LEF delivery presence; content diff is external",
        "Timing / 时序": "Liberty / DB presence; command or metadata review when changed",
        "Layout / 版图": "GDS / OAS / Milkyway metadata-oriented delivery",
        "Constraint / 约束": "SDC / SPEF presence; command review when changed",
        "Power / 电源": "UPF / CPF presence; command review when changed",
        "Doc / 证据": "release note / waiver / README / known issue evidence",
        "Binary / 二进制": "binary evidence that defaults to metadata review",
        "Other / 其他": "project-defined auxiliary files",
        "Unknown / 未识别": "needs classifier rule update or manual ignore confirmation",
    }
    cards = []
    for label in REVIEW_GROUP_ORDER:
        value = grouped.get(label, 0)
        tone = "bad" if label == "Unknown / 未识别" and value else "ok" if value else "neutral"
        cards.append(
            "<div class='group-card'>"
            f"<div class='group-title'>{esc(label)}</div>"
            f"<div class='group-note'>{esc(notes[label])}</div>"
            "<div class='group-stats'>"
            f"<div class='group-stat'><b>{value}</b>files</div>"
            f"<div class='group-stat'><b>{_pct(value, total)}%</b>share</div>"
            "</div>"
            f"<div class='sub {tone}'>Inventory group</div>"
            "</div>"
        )
    return "<div class='group-overview'>" + "".join(cards) + "</div>"


def _type_matrix_rows(counts: Mapping[str, int]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    total = sum(int(v or 0) for v in counts.values())
    rows: list[str] = []
    for file_type, count in sorted(counts.items(), key=lambda kv: (_type_group(kv[0]), kv[0])):
        rows.append(
            "<tr>"
            f"<td>{badge(_type_group(file_type), _type_group(file_type))}</td>"
            f"<td><code>{p_esc(file_type)}</code></td>"
            f"<td><b>{p_esc(count)}</b></td>"
            f"<td>{_pct(int(count or 0), total)}%</td>"
            f"<td>{p_esc(_type_meaning(file_type))}</td>"
            "</tr>"
        )
    return rows


def _view_coverage_items(counts: Mapping[str, int]) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    for key, label, group in KEY_VIEW_ORDER:
        count = int(counts.get(key, 0) or 0)
        if count and key in BINARY_METADATA_TYPES:
            status = "METADATA_ONLY"
            status_label = "metadata-only"
            hint = "Presence and metadata only. Use external/tool-specific review if this changed."
        elif count:
            status = "FOUND"
            status_label = "found"
            if key in COMMAND_REVIEW_TYPES:
                hint = "Presence only here. Content-level review is triggered by Diff command tasks."
            else:
                hint = "Presence recorded in inventory. Open trace evidence for file list."
        else:
            status = "MISSING"
            status_label = "missing"
            hint = "Not detected. This is not a failure unless project policy marks this view as required."
        items.append({"title": label, "subtitle": group, "status": status, "status_label": status_label, "count": count, "hint": hint})
    return items


def _scan_delivery_brief(meta: Mapping[str, Any], scan: Path, total_files: int, counts: Mapping[str, int], attention_status: str) -> list[tuple[str, Any, str, Any]]:
    version = meta.get("release_version") or meta.get("version") or "-"
    scope = meta.get("update_scope") or "-"
    if isinstance(scope, list):
        scope = "/".join(str(x) for x in scope)
    return [
        ("Library", meta.get("library_name") or meta.get("library_id") or "-", "asset name", "PASS"),
        ("Version", version, "scanned version", "PASS"),
        ("Package", meta.get("package_type") or "-", "delivery package type", "PASS"),
        ("Stage", meta.get("stage") or "-", "catalog stage if provided", "PASS" if meta.get("stage") else "WARNING"),
        ("Base Version", meta.get("base_version") or "-", "version lineage reference", "PASS" if meta.get("base_version") else "WARNING"),
        ("Scope", scope, "update scope", "PASS"),
        ("Files", total_files, f"{len(counts)} file types", "PASS"),
        ("Raw Root", meta.get("root_path") or "-", "raw delivery path; folded when long", "PASS" if meta.get("root_path") else "WARNING"),
        ("Scan Output", str(scan), "scan evidence directory", attention_status),
    ]


def _scan_next_command_rows(meta: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import esc as p_esc

    library = str(meta.get("library_name") or meta.get("library_id") or "<library>").split("/")[-1]
    version = str(meta.get("release_version") or meta.get("version") or "<version>")
    base = str(meta.get("base_version") or "<base_version>")
    rows = [
        (
            "Diff against base",
            f"$PROJ/scripts/lg.csh diff {library} {version} --base {base} --auto-scan",
            "Use after Scan when you need to answer what changed versus a selected base.",
        ),
        (
            "Open catalog",
            "$WORK/catalog/html/index.html",
            "Return to the library/version index and report links.",
        ),
        (
            "Release dry-run/apply",
            f"$PROJ/scripts/lg.csh release {library} {version} --apply --overwrite",
            "Run only after Scan/Diff evidence is reviewed and release policy is satisfied.",
        ),
    ]
    return [
        "<tr>"
        f"<td><b>{p_esc(title)}</b></td>"
        f"<td><code>{p_esc(cmd)}</code></td>"
        f"<td>{p_esc(why)}</td>"
        "</tr>"
        for title, cmd, why in rows
    ]


DOC_REVIEW_MARKERS = {
    "doc",
    "readme",
    "release",
    "release_note",
    "waiver",
    "changelog",
    "known_issue",
    "integration",
    "delivery_note",
    "version_note",
}
DOC_REVIEW_EXTS = {".md", ".txt", ".pdf", ".doc", ".docx", ".rst"}


def _is_doc_parser_issue(issue: Mapping[str, Any]) -> bool:
    category = str(issue.get("category") or "").lower()
    title = str(issue.get("title") or "").lower()
    message = str(issue.get("message") or "").lower()
    if "parser" not in category and "parser" not in title:
        return False
    haystack = " ".join([category, title, message])
    files = issue.get("files") or []
    if isinstance(files, str):
        files = [files]
    file_text = " ".join(str(item).lower().replace("\\", "/") for item in files)
    suffix_hit = any(file_text.endswith(ext) or ext + " " in file_text for ext in DOC_REVIEW_EXTS)
    marker_hit = any(marker in haystack or marker in file_text for marker in DOC_REVIEW_MARKERS)
    return suffix_hit or marker_hit


def _attention_issue_items(issue_items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    filtered: list[Mapping[str, Any]] = []
    for issue in issue_items:
        category = str(issue.get("category") or "").lower()
        title = str(issue.get("title") or "").lower()
        if "parser" in category or "parser" in title:
            if _is_doc_parser_issue(issue):
                filtered.append(issue)
            continue
        filtered.append(issue)
    return filtered


def _scan_attention_rows(counts: Mapping[str, int], issue_items: list[Mapping[str, Any]]) -> list[tuple[Any, str, str, str]]:
    rows: list[tuple[Any, str, str, str]] = []
    unknown = int(counts.get("unknown", 0) or 0)
    if unknown:
        rows.append(("WARNING", "Unknown files", f"{unknown} files were not classified.", "file_inventory.json"))
    missing_core = [name for name in ["verilog", "lef", "liberty"] if not counts.get(name)]
    if missing_core:
        rows.append(("WARNING", "Core delivery missing", "Missing expected delivery views: " + ", ".join(missing_core), "View Coverage"))
    for issue in _attention_issue_items(issue_items)[:12]:
        rows.append((issue.get("severity") or "WARNING", str(issue.get("title") or issue.get("category") or "Scan issue"), str(issue.get("message") or "Manual confirmation required."), str(issue.get("category") or "scan_issues.json")))
    return rows


def _attention_summary(counts: Mapping[str, int], issue_items: list[Mapping[str, Any]]) -> tuple[str, list[str]]:
    unknown = int(counts.get("unknown", 0) or 0)
    missing_core = [name for name in ["verilog", "lef", "liberty"] if not counts.get(name)]
    notes: list[str] = []
    if unknown:
        notes.append(f"{unknown} unknown files need classifier update or manual ignore confirmation.")
    if missing_core:
        notes.append("Core delivery views missing: " + ", ".join(missing_core))
    attention_issues = _attention_issue_items(issue_items)
    if attention_issues:
        notes.append(f"{len(attention_issues)} scan issues need review in the evidence drawer.")
    if not notes:
        notes.append("No priority review attention items were detected.")
    status = "WARNING" if unknown or missing_core or attention_issues else "PASS"
    return status, notes


def _issue_rows(items: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    return [
        "<tr>"
        f"<td>{badge(i.get('severity'))}</td>"
        f"<td><code>{p_esc(i.get('category'))}</code></td>"
        f"<td><b>{p_esc(i.get('title'))}</b><div class='sub'>{p_esc(i.get('message'))}</div></td>"
        "</tr>"
        for i in items
    ]


def _file_rows(files: list[Mapping[str, Any]], limit: int = 500) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows: list[str] = []
    for item in files[:limit]:
        rows.append(
            "<tr>"
            f"<td>{badge(item.get('file_type'))}</td>"
            f"<td><code>{p_esc(item.get('role'))}</code></td>"
            f"<td>{p_esc(item.get('size_bytes'))}</td>"
            f"<td><code>{p_esc(item.get('path'))}</code></td>"
            "</tr>"
        )
    return rows


def render_scan_html(scan_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render.product_theme import (
        attention_items,
        brief_grid,
        collapsible_panel,
        evidence_grid,
        filterable_table,
        intent_banner,
        page_shell,
        panel,
        product_summary,
        table,
        tile_grid,
        trace_link_list,
    )

    scan = Path(scan_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    meta = read_json(scan / "scan_meta.json", default={}) or {}
    inventory = read_json(scan / "file_inventory.json", default={}) or {}
    parser_manifest = read_json(scan / "parser_manifest.json", default={}) or {}
    issues = read_json(scan / "scan_issues.json", default={}) or {}
    dashboard = read_json(scan / "summary" / "dashboard_summary.json", default={}) or {}
    release_readiness = read_json(scan / "summary" / "release_readiness.json", default={}) or {}

    files = inventory.get("files", []) or []
    issue_items = list(issues.get("issues", []) or [])
    counts = _type_counts(inventory, parser_manifest, dashboard)
    attention_status, _attention_notes = _attention_summary(counts, issue_items)
    total_files = sum(int(v or 0) for v in counts.values()) or len(files)
    key_present = sum(1 for key, _, _ in KEY_VIEW_ORDER if counts.get(key))
    attention_rows = _scan_attention_rows(counts, issue_items)

    summary = product_summary(
        [
            ("Total Files", total_files, "inventory/type count", "PASS"),
            ("File Types", len(counts), "recognized delivery categories", "PASS"),
            ("View Presence", f"{key_present}/{len(KEY_VIEW_ORDER)}", "presence only, not parser quality", "PASS" if key_present else "WARNING"),
            ("Attention", len(attention_rows), "items surfaced for human review", attention_status),
        ]
    )
    evidence = evidence_grid(
        [
            ("File Inventory", "PASS" if (scan / "file_inventory.json").exists() else "UNKNOWN", "Complete file list and file_type evidence.", _file_href(scan / "file_inventory.json")),
            ("Scan Meta", "PASS" if (scan / "scan_meta.json").exists() else "UNKNOWN", "Library, version and raw root context.", _file_href(scan / "scan_meta.json")),
            ("Dashboard Summary", "PASS" if (scan / "summary" / "dashboard_summary.json").exists() else "UNKNOWN", "Inventory summary used for this page.", _file_href(scan / "summary" / "dashboard_summary.json")),
            ("Release Readiness", release_readiness.get("bundle_status", "UNKNOWN"), "Release-check reference; not the scan headline.", _file_href(scan / "summary" / "release_readiness.json")),
        ]
    )
    release_rows = [f"<tr><td><code>{esc(k)}</code></td><td>{esc(_json_preview(v))}</td></tr>" for k, v in sorted(release_readiness.items())]

    delivery_brief = brief_grid(_scan_delivery_brief(meta, scan, total_files, counts, attention_status))
    view_coverage = tile_grid(_view_coverage_items(counts))
    review_attention = attention_items(attention_rows)
    evidence_drawer = (
        trace_link_list(
            [
                ("file_inventory.json", _file_href(scan / "file_inventory.json"), "Complete file inventory and file_type statistics"),
                ("scan_meta.json", _file_href(scan / "scan_meta.json"), "Library, version, raw root and scan context"),
                ("dashboard_summary.json", _file_href(scan / "summary" / "dashboard_summary.json"), "Summary evidence used by this page"),
                ("release_readiness.json", _file_href(scan / "summary" / "release_readiness.json"), "Release-check reference; not the scan headline"),
                ("parser_manifest.json", _file_href(scan / "parser_manifest.json"), "Legacy trace only. Parser results are not promoted as review conclusions."),
            ]
        )
        + evidence
        + collapsible_panel("Scan Issues / 扫描关注项", "Unknown files, missing expected delivery views and scan issues are reviewed here.", filterable_table("issue-table", ["Severity", "Category", "Detail"], _issue_rows(issue_items), "No scan issues", "Filter severity / category / detail"), open=bool(issue_items))
        + collapsible_panel("Release Readiness Reference / Release 参考", "Release readiness supports later release-check and is not the primary scan goal.", table(["Item", "Value"], release_rows, "No release readiness"), open=False)
        + collapsible_panel("Full File Inventory / 全量文件清单", "Collapsed by default; shows up to 500 rows. Open file_inventory.json for full evidence.", filterable_table("file-table", ["Type", "Role", "Size", "Relative Path"], _file_rows(files), "No files", "Filter type / role / path"), open=False)
    )
    intent = intent_banner(
        "Page intent / 页面意图",
        [
            ("Inventory review", "Show what this version delivered by file type and view presence."),
            ("Not a diff page", "Scan answers what this version delivered; Diff answers what changed versus another version."),
            ("No rough parser conclusion", "LEF/GDS/DB/SDC parser results are not promoted as review conclusions."),
            ("Policy-aware missing", "Missing means not detected here; it is only a problem when project policy marks the view as required."),
            ("Folded evidence", "Raw JSON and full file lists stay in the evidence drawer for traceability."),
        ],
    )
    next_commands = table(["Next Step", "Command / Entry", "Use Case"], _scan_next_command_rows(meta), "No commands")
    body = (
        "<span class='compat-token'>交付结构总览</span>"
        + intent
        + panel("Delivery Brief / 交付概览", "Confirm asset, version, raw delivery path and scan evidence path first.", delivery_brief)
        + panel("Delivery Presence / 交付视图存在性", "Presence and metadata only. This section does not claim parser-level correctness.", view_coverage)
        + panel("Review Attention / 审阅关注", "Only priority scan review items are shown here; parser details are not used as main conclusions.", review_attention)
        + panel("Recommended Next Commands / 建议下一步命令", "Scan 结束后通常进入 Diff、Catalog 或 Release。这里给出可复制的短命令入口。", next_commands)
        + panel("File Type Structure / 文件类型结构", "Group delivery files by review domain. Content-level diff is handled on the Diff page after changes are detected.", summary + _structure_cards(counts) + table(["Review Domain", "File Type", "Count", "Share", "Review Meaning"], _type_matrix_rows(counts), "No file type statistics"))
        + collapsible_panel("Evidence Drawer / 证据抽屉", "JSON, release readiness and full inventory are folded as trace evidence.", evidence_drawer, open=False)
    )

    html_text = page_shell(
        "Library Version Scan Review / 库版本交付审阅",
        "SCAN REVIEW",
        f"{meta.get('library_name') or meta.get('library_id') or scan.name} | {meta.get('release_version') or meta.get('version') or '-'} | {total_files} files | {attention_status}",
        body,
        nav="<a class='active' href='#'>Brief</a><a href='#'>Presence</a><a href='#'>Attention</a><a href='#'>Evidence</a>",
    )
    atomic_write_text(out / "index.html", html_text)
    atomic_write_text(out / "scan_report.html", html_text)
    return {"status": "PASS", "index_html": str(out / "index.html"), "scan_report_html": str(out / "scan_report.html")}


def _summary_count(summary: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = summary.get(key)
        if value is not None:
            try:
                return int(value)
            except Exception:
                return 0
    return 0


def _diff_view_rows(view_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows = []
    for item in view_diff.get("views", []) or []:
        if item.get("changed") is False:
            continue
        rows.append(
            "<tr>"
            f"<td><code>{p_esc(item.get('view') or '-')}</code></td>"
            f"<td>{p_esc(item.get('requirement') or '-')}</td>"
            f"<td>{p_esc(item.get('old_status') or '-')}</td>"
            f"<td>{p_esc(item.get('new_status') or '-')}</td>"
            f"<td>{p_esc(item.get('old_count', 0))} -> {p_esc(item.get('new_count', 0))}</td>"
            f"<td>{badge(item.get('severity'))}</td>"
            "</tr>"
        )
    return rows


def _diff_type_rows(type_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows = []
    for file_type, item in sorted((type_diff.get("by_type") or {}).items(), key=lambda kv: (_type_group(kv[0]), kv[0])):
        if item.get("status") == "SAME":
            continue
        rows.append(
            "<tr>"
            f"<td>{badge(_type_group(file_type), _type_group(file_type))}</td>"
            f"<td><code>{p_esc(file_type)}</code></td>"
            f"<td>{p_esc(item.get('old_count', 0))} -> {p_esc(item.get('new_count', 0))}</td>"
            f"<td>+{p_esc(item.get('added_count', 0))} / -{p_esc(item.get('removed_count', 0))} / ~{p_esc(item.get('changed_count', 0))}</td>"
            f"<td><code>{p_esc(item.get('review_mode') or '-')}</code></td>"
            f"<td>{badge(item.get('status'))}</td>"
            "</tr>"
        )
    return rows


def _release_evidence_rows(release_evidence: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows = []
    for role, item in sorted((release_evidence.get("by_role") or {}).items()):
        if item.get("status") == "SAME":
            continue
        rows.append(
            "<tr>"
            f"<td><code>{p_esc(role)}</code></td>"
            f"<td>{p_esc(item.get('old_count', 0))} -> {p_esc(item.get('new_count', 0))}</td>"
            f"<td>+{len(item.get('added') or [])} / -{len(item.get('removed') or [])} / ~{len(item.get('changed') or [])}</td>"
            f"<td>{p_esc(item.get('release_meaning') or '-')}</td>"
            f"<td>{badge(item.get('status'))}</td>"
            "</tr>"
        )
    return rows


def _metadata_rows(metadata_tasks: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows = []
    for item in metadata_tasks.get("tasks", []) or []:
        rows.append(
            "<tr>"
            f"<td><code>{p_esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{p_esc(item.get('path') or '-')}</code></td>"
            f"<td>{p_esc(item.get('change_type') or '-')}</td>"
            f"<td>{p_esc(item.get('recommended_action') or '-')}</td>"
            f"<td>{badge(item.get('status'))}</td>"
            "</tr>"
        )
    return rows


def _diff_comparison_brief(meta: Mapping[str, Any], relation: Mapping[str, Any], view_changes: int, type_changes: int, pairwise_count: int, metadata_count: int, issue_count: int) -> list[tuple[str, Any, str, Any]]:
    return [
        ("Old Version", relation.get("old_version") or "-", "selected comparison baseline", "PASS"),
        ("New Version", relation.get("new_version") or "-", "selected target version", "PASS"),
        ("Diff Mode", relation.get("diff_mode") or meta.get("diff_mode") or "selected", "not all-pairs; only selected relation", "PASS"),
        ("Old Scan", meta.get("old_scan") or "-", "old scan evidence", "PASS" if meta.get("old_scan") else "WARNING"),
        ("New Scan", meta.get("new_scan") or "-", "new scan evidence", "PASS" if meta.get("new_scan") else "WARNING"),
        ("View Changes", view_changes, "view coverage delta", "WARNING" if view_changes else "PASS"),
        ("Type Changes", type_changes, "file_type structure delta", "WARNING" if type_changes else "PASS"),
        ("Review Tasks", pairwise_count + metadata_count + issue_count, "commands / metadata / issues", "WARNING" if pairwise_count + metadata_count + issue_count else "PASS"),
    ]


def _change_summary_items(view_changes: int, type_changes: int, evidence_changes: int, pairwise_count: int, metadata_count: int, issue_count: int) -> list[Mapping[str, Any]]:
    return [
        {"title": "View changes", "subtitle": "presence delta", "status": "WARNING" if view_changes else "FOUND", "status_label": "review" if view_changes else "stable", "count": view_changes, "hint": "Use this to find which delivery views changed."},
        {"title": "Type changes", "subtitle": "file_type structure", "status": "WARNING" if type_changes else "FOUND", "status_label": "review" if type_changes else "stable", "count": type_changes, "hint": "Focus on delivery structure domains, not raw file dumps."},
        {"title": "Release evidence", "subtitle": "note / waiver / README", "status": "WARNING" if evidence_changes else "FOUND", "status_label": "review" if evidence_changes else "stable", "count": evidence_changes, "hint": "Docs, release notes and waivers are release evidence changes."},
        {"title": "Content diff commands", "subtitle": "manual structural diff", "status": "WARNING" if pairwise_count else "FOUND", "status_label": "run" if pairwise_count else "none", "count": pairwise_count, "hint": "Run these commands only for changed file pairs detected by this diff."},
        {"title": "Metadata-only", "subtitle": "DB / GDS / OAS", "status": "METADATA_ONLY" if metadata_count else "FOUND", "status_label": "metadata" if metadata_count else "none", "count": metadata_count, "hint": "Binary deliveries default to size/hash/path review."},
        {"title": "Issues", "subtitle": "blocker / warning", "status": "WARNING" if issue_count else "FOUND", "status_label": "review" if issue_count else "clear", "count": issue_count, "hint": "Only structure-impacting blocker/warning/manual review items are surfaced."},
    ]


def _domain_review_task_rows(pairwise_tasks: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    rows = []
    for item in pairwise_tasks.get("tasks", []) or []:
        cmd = str(item.get("command") or "")
        old_path = item.get("old_path") or item.get("old_file") or "-"
        new_path = item.get("new_path") or item.get("new_file") or "-"
        why = item.get("reason") or item.get("review_reason") or "File changed in selected version diff; run content-level review outside this HTML."
        status = item.get("status")
        result_note = ""
        result_link = ""
        expected = item.get("expected_output")
        if expected:
            result_path = Path(str(expected)) / "pairwise_result.json"
            result = read_json(result_path, default=None)
            if result:
                status = result.get("status") or "DONE"
                result_note = f"{result.get('result') or '-'} / changes: {result.get('change_count', 0)}"
                html_path = result.get("html") or (Path(str(expected)) / "index.html")
                result_link = f"<div class='sub'><a class='link' href='{p_esc(_file_href(html_path))}'>Open file diff</a></div>"
            elif (Path(str(expected)) / "file_diff_summary.json").exists():
                status = "DONE"
                result_link = f"<div class='sub'><a class='link' href='{p_esc(_file_href(Path(str(expected)) / 'index.html'))}'>Open file diff</a></div>"
        rows.append(
            "<tr>"
            f"<td><code>{p_esc(item.get('file_type') or '-')}</code><div class='sub'>{badge(item.get('priority'))}</div></td>"
            f"<td><code>{p_esc(old_path)}</code></td>"
            f"<td><code>{p_esc(new_path)}</code></td>"
            f"<td>{p_esc(why)}</td>"
            f"<td><details><summary>Show command</summary><div class='cmd'><code>{p_esc(cmd)}</code><button class='copy' onclick='copyText({_json_arg(cmd)}, this)'>Copy</button></div></details></td>"
            f"<td>{badge(status)}<div class='sub'>{p_esc(status or '-')}</div><div class='sub'>{p_esc(result_note)}</div>{result_link}</td>"
            "</tr>"
        )
    return rows


def _diff_issue_rows(issues: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc as p_esc

    return [
        "<tr>"
        f"<td>{badge(item.get('severity'))}</td>"
        f"<td><code>{p_esc(item.get('category') or '-')}</code></td>"
        f"<td><b>{p_esc(item.get('title') or '-')}</b><div class='sub'>{p_esc(item.get('message') or '')}</div></td>"
        "</tr>"
        for item in issues
    ]


def _file_diff_rows(file_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import esc as p_esc

    counts = file_diff.get("counts") or {}
    rows = []
    for key, label in [("added", "Added"), ("removed", "Removed"), ("changed", "Content changed"), ("renamed_or_moved", "Moved/renamed"), ("metadata_only_changed", "Metadata-only changed")]:
        samples = file_diff.get(key) or []
        if samples and isinstance(samples[0], Mapping):
            sample_text = ", ".join(str(x.get("new") or x.get("old") or x) for x in samples[:6])
        else:
            sample_text = ", ".join(str(x) for x in samples[:6])
        rows.append(f"<tr><td>{p_esc(label)}</td><td>{p_esc(counts.get(key, len(samples)))}</td><td><code>{p_esc(sample_text)}</code></td></tr>")
    return rows


def render_diff_html(diff_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render.product_theme import (
        brief_grid,
        collapsible_panel,
        evidence_grid,
        intent_banner,
        page_shell,
        panel,
        table,
        tile_grid,
        trace_link_list,
    )

    diff = Path(diff_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    meta = read_json(diff / "diff_meta.json", default={}) or {}
    summary = read_json(diff / "diff_summary.json", default={}) or {}
    view_diff = read_json(diff / "view_diff.json", default={"views": [], "summary": {}}) or {"views": [], "summary": {}}
    type_diff = read_json(diff / "type_diff.json", default={"by_type": {}, "summary": {}}) or {"by_type": {}, "summary": {}}
    release_evidence = read_json(diff / "release_evidence_diff.json", default={"by_role": {}, "summary": {}}) or {"by_role": {}, "summary": {}}
    metadata_tasks = read_json(diff / "metadata_review_tasks.json", default={"tasks": [], "summary": {}}) or {"tasks": [], "summary": {}}
    pairwise_tasks = read_json(diff / "manual_pairwise_tasks.json", default=None) or read_json(diff / "pairwise_diff_tasks.json", default={"tasks": [], "summary": {}}) or {"tasks": [], "summary": {}}
    readiness = read_json(diff / "release_readiness_diff.json", default={}) or {}
    issues = read_json(diff / "diff_issues.json", default={"issues": []}) or {"issues": []}
    file_diff = read_json(diff / "file_inventory_diff.json", default=None) or read_json(diff / "file_diff.json", default={}) or {}

    relation = meta.get("version_relation", {}) if isinstance(meta.get("version_relation"), Mapping) else {}
    issue_items = list(issues.get("issues") or [])
    view_changes = _summary_count(summary, "view_changes")
    type_changes = _summary_count(summary, "type_changes")
    evidence_changes = _summary_count(summary, "release_evidence_changes")
    metadata_count = _summary_count(summary, "metadata_review_tasks") or len(metadata_tasks.get("tasks", []) or [])
    pairwise_count = _summary_count(summary, "manual_pairwise_tasks", "pairwise_tasks") or len(pairwise_tasks.get("tasks", []) or [])

    evidence = evidence_grid(
        [
            ("view_diff", view_diff.get("status", "PASS"), "Selected old/new view presence changes.", _file_href(diff / "view_diff.json")),
            ("type_diff", type_diff.get("status", "PASS"), "Selected old/new file_type aggregate changes.", _file_href(diff / "type_diff.json")),
            ("release_evidence", release_evidence.get("status", "PASS"), "Release note / waiver / README evidence changes.", _file_href(diff / "release_evidence_diff.json")),
            ("manual_pairwise", pairwise_tasks.get("status", "EMPTY"), "Commands for content-level review of changed file pairs.", _file_href(diff / "manual_pairwise_tasks.json")),
        ]
    )
    readiness_rows = []
    for key in ["bundle_status", "release_channel", "blocking_count", "manual_review_count"]:
        item = readiness.get(key) or {}
        readiness_rows.append(f"<tr><td><code>{esc(key)}</code></td><td>{esc(_json_preview(item.get('old')))}</td><td>{esc(_json_preview(item.get('new')))}</td><td>{esc(_json_preview(item.get('delta')))}</td></tr>")

    comparison_brief = brief_grid(_diff_comparison_brief(meta, relation, view_changes, type_changes, pairwise_count, metadata_count, len(issue_items)))
    change_summary = tile_grid(_change_summary_items(view_changes, type_changes, evidence_changes, pairwise_count, metadata_count, len(issue_items)))
    trace_evidence = (
        trace_link_list(
            [
                ("view_diff.json", _file_href(diff / "view_diff.json"), "Selected-version view presence delta"),
                ("type_diff.json", _file_href(diff / "type_diff.json"), "Selected-version file_type structure delta"),
                ("release_evidence_diff.json", _file_href(diff / "release_evidence_diff.json"), "Release note / waiver / README evidence changes"),
                ("metadata_review_tasks.json", _file_href(diff / "metadata_review_tasks.json"), "Metadata-only review tasks for binary/tool artifacts"),
                ("manual_pairwise_tasks.json", _file_href(diff / "manual_pairwise_tasks.json"), "Generated commands for content-level diff"),
                ("file_inventory_diff.json", _file_href(diff / "file_inventory_diff.json"), "Low-level file scope trace"),
            ]
        )
        + evidence
        + collapsible_panel("Risk and Review Issues / 风险与确认项", "Expanded only when blocker/warning/manual review items exist.", table(["Severity", "Category", "Evidence"], _diff_issue_rows(issue_items), "No blockers or warnings"), open=bool(issue_items))
        + collapsible_panel("Release Gate Reference / Release 参考", "Release-check data is supporting evidence, not the diff headline.", table(["Item", "Old", "New", "Delta"], readiness_rows, "No release readiness delta"), open=False)
        + collapsible_panel("Low-level File Evidence / 底层文件证据", "file_inventory_diff / file_diff is only used for trace scope.", table(["Change Type", "Count", "Samples"], _file_diff_rows(file_diff), "No low-level file changes"), open=False)
    )
    intent = intent_banner(
        "Page intent / 页面意图",
        [
            ("Selected diff only", "This page compares a selected old/new relation, not every library pair."),
            ("Detect structure change", "Use view/type/release evidence deltas to decide where to investigate."),
            ("Run content diff manually", "Generated commands guide reviewers into the directory/tool flow for content-level diff."),
            ("Traceability", "Raw JSON, release gate reference and file diff remain folded below."),
        ],
    )
    body = (
        "<span class='compat-token'>结构变化总览</span><span class='compat-token'>人工任务摘要</span>"
        + intent
        + panel("Comparison Brief / 对比概览", "Confirm old/new versions, scan evidence and diff selection mode first.", comparison_brief)
        + panel("Change Summary / 变化摘要", "Review route: structure delta first, then content diff commands for changed file pairs.", change_summary)
        + panel("View Delta / View 变化", "Selected-version view presence delta. This is not parser-level correctness.", table(["View", "Requirement", "Old", "New", "Count Delta", "Attention"], _diff_view_rows(view_diff), "No view changes"))
        + panel("File Type Delta / 文件类型变化", "File-type structure delta before raw changed files. Use this to choose review domains.", table(["Review Domain", "Type", "Count Delta", "Added/Removed/Changed", "Review Mode", "Status"], _diff_type_rows(type_diff), "No type changes"))
        + panel("Content Diff Commands / 内容级 Diff 命令", "Commands are generated only for changed file pairs selected by this diff; reviewers run them in the real environment.", table(["Domain", "Old", "New", "Why", "Command", "Status"], _domain_review_task_rows(pairwise_tasks), "No content-level command tasks"))
        + panel("Metadata-only Review / 元数据审阅", "DB / GDS / OAS and similar binary deliveries default to size/hash/path review unless an external tool is provided.", table(["Type", "Path", "Change", "Recommended Action", "Status"], _metadata_rows(metadata_tasks), "No metadata-only review items"))
        + panel("Release Evidence Delta / 发布证据变化", "Release notes, waivers, README and known issues are release evidence, not ordinary file diffs.", table(["Evidence Role", "Count Delta", "Added/Removed/Changed", "Meaning", "Status"], _release_evidence_rows(release_evidence), "No release evidence changes"))
        + collapsible_panel("Trace Evidence / 底层证据", "Underlying JSON, release gate reference and file diff remain folded as trace evidence.", trace_evidence, open=False)
    )

    html_text = page_shell(
        "lib_guard 结构变化审阅台",
        "STRUCTURE DIFF",
        f"{relation.get('old_version') or 'old'} -> {relation.get('new_version') or 'new'} | view {view_changes} / type {type_changes}",
        body,
        nav="<a class='active' href='#'>Brief</a><a href='#'>Delta</a><a href='#'>Commands</a><a href='#'>Evidence</a>",
    )
    atomic_write_text(out / "index.html", html_text)
    return {"status": "PASS", "diff_dir": str(diff), "html_dir": str(out), "index_html": str(out / "index.html")}


class RenderRunner:
    def __init__(self, scan_dir: str | Path, out_dir: str | Path) -> None:
        self.scan_dir = Path(scan_dir)
        self.out_dir = Path(out_dir)

    def run(self) -> dict[str, Any]:
        return render_scan_html(self.scan_dir, self.out_dir)
