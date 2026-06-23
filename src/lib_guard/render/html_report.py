"""Chinese review-navigation HTML renderers for scan and diff outputs.

Design intent:
- Scan answers: this version can be reviewed or compared?
- Diff answers: what changed and which File Diff should be opened?
- Raw JSON and full file lists are evidence, folded by default.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import json
import os
import tempfile


IMPLEMENTATION_TYPES = {"verilog", "cdl"}
ABSTRACT_TYPES = {"lef"}
TIMING_TYPES = {"liberty", "lib", "db"}
CONSTRAINT_TYPES = {"sdc", "spef"}
POWER_TYPES = {"upf", "cpf"}
LAYOUT_TYPES = {"gds", "oas", "layout", "milkyway"}
BINARY_METADATA_TYPES = {"db", "gds", "oas", "milkyway", "layout"}
DOC_TYPES = {"doc", "package", "waiver", "readme", "release_note", "update_note", "changelog", "known_issue", "integration_guide"}
FILE_DIFF_TYPES = {"lef", "liberty", "lib", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db"}
CORE_VIEW_TYPES = ["lef", "liberty", "verilog"]
VIEW_ORDER = ["lef", "liberty", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db", "gds", "oas", "release_note", "waiver", "readme"]


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


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


def _file_href(path: Any) -> str:
    if not path:
        return ""
    text = str(path)
    if text.startswith(("http://", "https://", "file://")):
        return text
    try:
        p = Path(text)
        if p.is_absolute():
            return p.resolve().as_uri()
    except Exception:
        pass
    return text.replace("\\", "/")


def _type_group(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    if key in IMPLEMENTATION_TYPES:
        return "实现"
    if key in ABSTRACT_TYPES:
        return "物理抽象"
    if key in TIMING_TYPES:
        return "时序"
    if key in CONSTRAINT_TYPES:
        return "约束"
    if key in POWER_TYPES:
        return "电源"
    if key in LAYOUT_TYPES:
        return "版图"
    if key in DOC_TYPES:
        return "发布证据"
    if key in {"binary", "archive"}:
        return "二进制"
    if key == "unknown":
        return "未识别"
    return "其他"


def _type_meaning(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    return {
        "lef": "物理抽象视图。变更后通常建议打开 File Diff。",
        "liberty": "时序库视图。变更后通常建议打开 File Diff。",
        "lib": "时序库视图。变更后通常建议打开 File Diff。",
        "verilog": "接口 / 结构视图。变更后建议检查 module / port / instance。",
        "cdl": "电路网表视图。变更后建议检查 subckt / pin / instance。",
        "sdc": "约束视图。变更后建议检查 clock / exception / constraint。",
        "upf": "电源意图视图。变更后建议检查 power domain / supply / isolation。",
        "cpf": "电源意图视图。变更后建议检查 power domain / power mode。",
        "spef": "寄生参数视图。默认偏 metadata / 结构级检查。",
        "db": "二进制工具库。默认只做 metadata 检查。",
        "gds": "版图二进制。默认只做 metadata 检查。",
        "oas": "版图二进制。默认只做 metadata 检查。",
        "release_note": "发布说明，属于 release evidence。",
        "waiver": "waiver 证据，属于 release evidence。",
        "readme": "使用说明，属于 release evidence。",
        "unknown": "未识别文件类型。需要更新规则或人工确认可忽略。",
    }.get(key, "项目自定义或辅助文件类型。")


def _type_counts(inventory: Mapping[str, Any], parser_manifest: Mapping[str, Any], dashboard: Mapping[str, Any]) -> dict[str, int]:
    direct = inventory.get("file_type_counts") or (dashboard.get("counts") or {}).get("file_type_counts") or parser_manifest.get("file_type_counts")
    if isinstance(direct, Mapping):
        return {str(k): int(v or 0) for k, v in direct.items()}
    counts: Counter[str] = Counter()
    for item in inventory.get("files", []) or []:
        counts[str(item.get("file_type") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _version_name(meta: Mapping[str, Any]) -> str:
    return str(meta.get("release_version") or meta.get("version") or meta.get("version_id") or "<version>")


def _library_name(meta: Mapping[str, Any]) -> str:
    raw = str(meta.get("library_name") or meta.get("library_id") or "<library>")
    return raw.split("/")[-1]


def _scan_review_model(scan: Path, out: Path, meta: Mapping[str, Any], counts: Mapping[str, int], issue_items: list[Mapping[str, Any]], release_readiness: Mapping[str, Any]) -> dict[str, Any]:
    missing_core = [name for name in CORE_VIEW_TYPES if not counts.get(name)]
    unknown = int(counts.get("unknown", 0) or 0)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if missing_core:
        warnings.append({"level": "WARNING", "category": "core_view_missing", "message": "核心视图未发现: " + ", ".join(missing_core)})
    if unknown:
        warnings.append({"level": "WARNING", "category": "unknown_files", "message": f"{unknown} 个文件未识别，需要确认是否可忽略。"})
    for item in issue_items:
        sev = str(item.get("severity") or item.get("level") or "WARNING").upper()
        msg = str(item.get("message") or item.get("title") or item.get("category") or "Scan issue")
        row = {"level": sev, "category": item.get("category") or "scan_issue", "message": msg}
        if sev in {"ERROR", "BLOCK", "BLOCKER", "FAILED"}:
            blockers.append(row)
        else:
            warnings.append(row)
    if blockers:
        decision = "SCAN_BLOCKED"
        headline = f"发现 {len(blockers)} 个阻塞项，先处理 scan 证据。"
    elif warnings:
        decision = "SCAN_NEEDS_REVIEW"
        headline = f"Scan 证据可用，但有 {len(warnings)} 个注意项。"
    else:
        decision = "READY_FOR_DIFF"
        headline = "核心 scan 证据已具备，可进入 Diff。"
    library = _library_name(meta)
    version = _version_name(meta)
    base = str(meta.get("base_version") or "<base_version>")
    next_command = f"lg diff {library} {version} --base {base} --scan-if-missing" if decision != "SCAN_BLOCKED" else ""
    return {
        "schema_version": "scan_review.v1",
        "decision": decision,
        "headline": headline,
        "library": library,
        "version": version,
        "package_type": meta.get("package_type") or "UNKNOWN",
        "required_views": {"missing": missing_core, "found": [v for v in CORE_VIEW_TYPES if counts.get(v)]},
        "metadata_only": [name for name in BINARY_METADATA_TYPES if counts.get(name)],
        "unknown_files": unknown,
        "total_files": sum(int(v or 0) for v in counts.values()),
        "blockers": blockers,
        "warnings": warnings[:50],
        "next_action": {
            "label": "运行 Diff" if next_command else "补齐 Scan 证据",
            "command": next_command,
            "reason": "Scan 只确认版本交付证据。版本变化需要进入 Diff / File Diff 查看。" if next_command else "存在阻塞项，暂不建议继续 Diff。",
        },
        "evidence": {
            "scan_dir": str(scan),
            "scan_meta": str(scan / "scan_meta.json"),
            "file_inventory": str(scan / "file_inventory.json"),
            "scan_issues": str(scan / "scan_issues.json"),
            "release_readiness": str(scan / "summary" / "release_readiness.json"),
        },
    }


def _scan_view_rows(counts: Mapping[str, int]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for name in VIEW_ORDER:
        count = int(counts.get(name, 0) or 0)
        if count and name in BINARY_METADATA_TYPES:
            status = "METADATA_ONLY"
        elif count:
            status = "FOUND"
        elif name in CORE_VIEW_TYPES:
            status = "MISSING"
        else:
            status = "NOT_APPLICABLE"
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(name)}</code></td>"
            f"<td>{ui.badge(status)}</td>"
            f"<td>{ui.esc(count)}</td>"
            f"<td>{ui.esc(_type_group(name))}</td>"
            f"<td>{ui.esc(_type_meaning(name))}</td>"
            "</tr>"
        )
    return rows


def _file_type_rows(counts: Mapping[str, int]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for file_type, count in sorted(counts.items(), key=lambda kv: (_type_group(kv[0]), kv[0])):
        rows.append(
            "<tr>"
            f"<td>{ui.badge(_type_group(file_type), _type_group(file_type))}</td>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(count)}</td>"
            f"<td>{ui.esc(_type_meaning(file_type))}</td>"
            "</tr>"
        )
    return rows


def render_scan_html(scan_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render import product_theme as ui

    scan = Path(scan_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = read_json(scan / "scan_meta.json", {}) or {}
    inventory = read_json(scan / "file_inventory.json", {}) or {}
    parser_manifest = read_json(scan / "parser_manifest.json", {}) or {}
    issues = read_json(scan / "scan_issues.json", {}) or {}
    dashboard = read_json(scan / "summary" / "dashboard_summary.json", {}) or {}
    release_readiness = read_json(scan / "summary" / "release_readiness.json", {}) or {}
    files = inventory.get("files", []) or []
    issue_items = list(issues.get("issues", []) or [])
    counts = _type_counts(inventory, parser_manifest, dashboard)
    review = _scan_review_model(scan, out, meta, counts, issue_items, release_readiness)
    write_json(out / "scan_review.json", review)

    attention = [(x.get("level"), x.get("category"), x.get("message"), "scan_review.json") for x in (review.get("blockers") or []) + (review.get("warnings") or [])]
    rail = ui.status_rail([
        ("Catalog", "DISCOVERED", "版本已进入 catalog"),
        ("Scan", review["decision"], review["headline"]),
        ("Diff", "COMPARE_READY" if review["decision"] != "SCAN_BLOCKED" else "NOT_READY", "下一步进入版本对比"),
        ("File Diff", "PAIRWISE_EMPTY", "由 Diff 发现变化后生成"),
        ("Release", "RELEASE_CHECK_REQUIRED", "发布前再检查"),
    ])
    body = (
        ui.panel(
            "Scan 结论",
            "只保留是否可继续审阅、缺失视图、注意项和下一步。数量明细放在证据区。",
            ui.metric_grid([
                ("Package", review.get("package_type"), "交付类型", "PASS" if review.get("package_type") != "UNKNOWN" else "WARNING"),
                ("核心视图缺失", len(review["required_views"]["missing"]), "LEF / Liberty / Verilog", "WARNING" if review["required_views"]["missing"] else "PASS"),
                ("metadata-only", len(review.get("metadata_only") or []), "DB / GDS / OAS 等", "METADATA_ONLY" if review.get("metadata_only") else "PASS"),
                ("注意项", len(attention), review["headline"], review["decision"]),
            ])
            + ui.compact_meta([
                ("Library", review.get("library")), ("Version", review.get("version")), ("Raw Root", meta.get("root_path") or meta.get("root")), ("Scan Dir", scan),
            ]),
        )
        + ui.next_action_panel(review["next_action"]["label"], review["next_action"]["command"], review["next_action"]["reason"], status=review["decision"])
        + ui.panel("核心视图", "面向使用者的视图存在性检查。是否 required 仍以项目 policy 为准。", ui.table(["View", "状态", "数量", "领域", "说明"], _scan_view_rows(counts), "暂无视图信息"))
        + ui.panel("优先关注", "只显示会影响继续 Diff / 使用判断的注意项。", ui.attention_items(attention))
        + ui.collapsible_panel(
            "证据区",
            "原始 JSON、完整文件类型和文件列表只作为 trace evidence。",
            ui.trace_link_list([
                ("scan_review.json", _file_href(out / "scan_review.json"), "本页面使用的审阅导航模型"),
                ("scan_meta.json", _file_href(scan / "scan_meta.json"), "版本和 raw root 上下文"),
                ("file_inventory.json", _file_href(scan / "file_inventory.json"), "完整文件清单"),
                ("scan_issues.json", _file_href(scan / "scan_issues.json"), "scan 原始问题"),
                ("release_readiness.json", _file_href(scan / "summary" / "release_readiness.json"), "后续 release-check 参考"),
            ])
            + ui.filterable_table("file-type-table", ["领域", "file_type", "数量", "说明"], _file_type_rows(counts), "暂无 file_type", "筛选 file_type / 领域")
            + ui.collapsible_panel("完整文件列表", "默认折叠，避免 scan 页面变成 raw folder。", ui.filterable_table("file-list", ["file_type", "role", "size", "path"], _file_rows(files), "暂无文件", "筛选文件路径"), open=False),
            open=False,
        )
    )
    html_text = ui.review_page_shell(
        f"{review.get('library')} / {review.get('version')} / Scan",
        "SCAN REVIEW",
        review["headline"],
        body,
        decision=review["decision"],
        rail=rail,
        nav="<a class='active' href='#'>Scan</a><a href='#'>Diff</a><a href='#'>File Diff</a><a href='#'>Release</a>",
        meta=ui.compact_meta([("Package", review.get("package_type")), ("Total Files", review.get("total_files")), ("Unknown", review.get("unknown_files"))]),
    )
    atomic_write_text(out / "index.html", html_text)
    atomic_write_text(out / "scan_report.html", html_text)
    return {"status": "PASS", "index_html": str(out / "index.html"), "scan_report_html": str(out / "scan_report.html"), "scan_review": str(out / "scan_review.json")}


def _file_rows(files: list[Mapping[str, Any]], limit: int = 800) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for item in files[:limit]:
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('role') or '-')}</td>"
            f"<td>{ui.esc(item.get('size_bytes') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _summary_count(summary: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = summary.get(key)
        if value is not None:
            try:
                return int(value)
            except Exception:
                return 0
    return 0


def _type_item_changed(item: Mapping[str, Any]) -> bool:
    if str(item.get("status") or "").upper() not in {"", "SAME", "PASS"}:
        return True
    for key in ["added_count", "removed_count", "changed_count"]:
        if int(item.get(key, 0) or 0):
            return True
    old = item.get("old_count")
    new = item.get("new_count")
    return old is not None and new is not None and old != new


def _domain_impact(type_diff: Mapping[str, Any], release_evidence: Mapping[str, Any], metadata_tasks: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_type = type_diff.get("by_type") or {}
    domain_types = {
        "Interface": ["verilog", "cdl"],
        "Abstract": ["lef"],
        "Timing": ["liberty", "lib", "db"],
        "Constraint": ["sdc", "spef"],
        "Power": ["upf", "cpf"],
        "Layout": ["gds", "oas", "layout", "milkyway"],
    }
    items: list[dict[str, Any]] = []
    for domain, types in domain_types.items():
        count = 0
        metadata = False
        for tp in types:
            item = by_type.get(tp) or {}
            if _type_item_changed(item):
                count += int(item.get("added_count", 0) or 0) + int(item.get("removed_count", 0) or 0) + int(item.get("changed_count", 0) or 0) or 1
                if tp in BINARY_METADATA_TYPES:
                    metadata = True
        status = "METADATA_ONLY" if metadata and count else "CHANGED" if count else "SAME"
        label = "metadata" if status == "METADATA_ONLY" else "changed" if count else "same"
        items.append({"domain": domain, "status": status, "label": label, "count": count, "hint": ", ".join(types)})
    ev_summary = release_evidence.get("summary") or {}
    ev_count = sum(int(ev_summary.get(k, 0) or 0) for k in ["added", "removed", "changed", "changed_count", "added_count", "removed_count"])
    if not ev_count:
        for item in (release_evidence.get("by_role") or {}).values():
            if str(item.get("status") or "").upper() not in {"", "SAME", "PASS"}:
                ev_count += 1
    items.append({"domain": "Release Evidence", "status": "CHANGED" if ev_count else "SAME", "label": "changed" if ev_count else "same", "count": ev_count, "hint": "release note / waiver / README"})
    meta_count = len(metadata_tasks.get("tasks", []) or [])
    items.append({"domain": "Metadata-only", "status": "METADATA_ONLY" if meta_count else "SAME", "label": "metadata" if meta_count else "same", "count": meta_count, "hint": "DB / GDS / OAS 等二进制证据"})
    return items


def _pairwise_result_for(task: Mapping[str, Any]) -> tuple[str, str, str]:
    expected = task.get("expected_output") or task.get("out") or task.get("out_dir")
    status = str(task.get("status") or "PENDING")
    note = ""
    href = ""
    if expected:
        result_path = Path(str(expected)) / "pairwise_result.json"
        result = read_json(result_path, default=None)
        if result:
            status = str(result.get("status") or "DONE")
            note = f"{result.get('result') or '-'} / changes={result.get('change_count', 0)}"
            href = _file_href(result.get("html") or (Path(str(expected)) / "index.html"))
        elif (Path(str(expected)) / "index.html").exists():
            status = "DONE"
            href = _file_href(Path(str(expected)) / "index.html")
    return status, note, href


def _pairwise_rows(tasks: Mapping[str, Any]) -> tuple[list[str], int, int]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    done = 0
    total = 0
    for item in tasks.get("tasks", []) or []:
        total += 1
        status, note, href = _pairwise_result_for(item)
        if status.upper() in {"DONE", "PASS", "SAME", "DIFF"}:
            done += 1
        cmd = str(item.get("command") or "")
        old_path = item.get("old_path") or item.get("old_file") or "-"
        new_path = item.get("new_path") or item.get("new_file") or "-"
        reason = item.get("reason") or item.get("review_reason") or "文件在本次 comparison 中变化，建议打开 File Diff。"
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(old_path)}</code></td>"
            f"<td><code>{ui.esc(new_path)}</code></td>"
            f"<td>{ui.esc(reason)}</td>"
            f"<td>{ui.command_chip(cmd)}</td>"
            f"<td>{ui.badge(status)}<div class='muted'>{ui.esc(note)}</div></td>"
            f"<td>{ui.button('Open file diff / 打开 File Diff', href, 'primary', disabled=not bool(href))}</td>"
            "</tr>"
        )
    return rows, done, total


def _diff_review_model(diff: Path, meta: Mapping[str, Any], summary: Mapping[str, Any], type_diff: Mapping[str, Any], release_evidence: Mapping[str, Any], metadata_tasks: Mapping[str, Any], pairwise_tasks: Mapping[str, Any], issues: Mapping[str, Any]) -> dict[str, Any]:
    relation = meta.get("version_relation", {}) if isinstance(meta.get("version_relation"), Mapping) else {}
    old_version = relation.get("old_version") or meta.get("old_version") or "<old>"
    new_version = relation.get("new_version") or meta.get("new_version") or "<new>"
    mode = relation.get("mode") or relation.get("diff_mode") or meta.get("diff_mode") or "selected"
    issue_items = list(issues.get("issues") or [])
    impact = _domain_impact(type_diff, release_evidence, metadata_tasks)
    changed_domains = [item["domain"] for item in impact if item.get("status") in {"CHANGED", "METADATA_ONLY"}]
    pair_rows, done, total = _pairwise_rows(pairwise_tasks)
    blockers = [i for i in issue_items if str(i.get("severity") or "").upper() in {"ERROR", "BLOCK", "BLOCKER", "FAILED"}]
    pending = max(total - done, 0)
    if blockers:
        review_level = "DIFF_BLOCKED"
        headline = f"发现 {len(blockers)} 个 Diff 阻塞项。"
    elif pending:
        review_level = "NEEDS_FILE_DIFF"
        headline = f"{len(changed_domains)} 个影响域有变化，{pending} 个 File Diff 待完成。"
    elif changed_domains:
        review_level = "CHANGED"
        headline = f"{len(changed_domains)} 个影响域有变化，File Diff 已闭环或无需执行。"
    else:
        review_level = "SAME"
        headline = "未发现需要优先处理的结构变化。"
    first_cmd = ""
    for item in pairwise_tasks.get("tasks", []) or []:
        st, _, _ = _pairwise_result_for(item)
        if st.upper() not in {"DONE", "PASS", "SAME", "DIFF"}:
            first_cmd = str(item.get("command") or "")
            break
    return {
        "schema_version": "comparison_review.v1",
        "comparison_id": f"{mode}__{old_version}__{new_version}",
        "old_version": old_version,
        "new_version": new_version,
        "mode": mode,
        "review_level": review_level,
        "headline": headline,
        "impact": impact,
        "pairwise": {"done": done, "total": total, "pending": pending},
        "issues": issue_items,
        "next_action": {
            "label": "运行 File Diff" if first_cmd else "查看证据 / 返回 Catalog",
            "command": first_cmd,
            "reason": "Diff 只定位变化影响域。具体文件变化在 File Diff 页面查看。" if first_cmd else "当前没有待执行的 File Diff 命令。",
        },
        "evidence": {
            "diff_dir": str(diff),
            "diff_summary": str(diff / "diff_summary.json"),
            "type_diff": str(diff / "type_diff.json"),
            "view_diff": str(diff / "view_diff.json"),
            "release_evidence_diff": str(diff / "release_evidence_diff.json"),
            "manual_pairwise_tasks": str(diff / "manual_pairwise_tasks.json"),
        },
    }


def _view_rows(view_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for item in view_diff.get("views", []) or []:
        if item.get("changed") is False:
            continue
        status = item.get("severity") or item.get("status") or "CHANGED"
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('view') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('old_status') or '-')} → {ui.esc(item.get('new_status') or '-')}</td>"
            f"<td>{ui.esc(item.get('old_count', 0))} → {ui.esc(item.get('new_count', 0))}</td>"
            f"<td>{ui.badge(status)}</td>"
            "</tr>"
        )
    return rows


def _type_rows(type_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for file_type, item in sorted((type_diff.get("by_type") or {}).items(), key=lambda kv: (_type_group(kv[0]), kv[0])):
        if not _type_item_changed(item):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(_type_group(file_type), _type_group(file_type))}</td>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(item.get('old_count', 0))} → {ui.esc(item.get('new_count', 0))}</td>"
            f"<td>+{ui.esc(item.get('added_count', 0))} / -{ui.esc(item.get('removed_count', 0))} / ~{ui.esc(item.get('changed_count', 0))}</td>"
            f"<td>{ui.badge(item.get('status') or 'CHANGED')}</td>"
            "</tr>"
        )
    return rows


def _release_evidence_rows(release_evidence: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for role, item in sorted((release_evidence.get("by_role") or {}).items()):
        if str(item.get("status") or "").upper() in {"", "SAME", "PASS"}:
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(role)}</code></td>"
            f"<td>{ui.esc(item.get('old_count', 0))} → {ui.esc(item.get('new_count', 0))}</td>"
            f"<td>+{len(item.get('added') or [])} / -{len(item.get('removed') or [])} / ~{len(item.get('changed') or [])}</td>"
            f"<td>{ui.badge(item.get('status') or 'CHANGED')}</td>"
            "</tr>"
        )
    return rows


def _issue_rows(issues: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render import product_theme as ui

    return [
        "<tr>"
        f"<td>{ui.badge(item.get('severity') or 'WARNING')}</td>"
        f"<td><code>{ui.esc(item.get('category') or '-')}</code></td>"
        f"<td><b>{ui.esc(item.get('title') or '-')}</b><div class='muted'>{ui.esc(item.get('message') or '')}</div></td>"
        "</tr>"
        for item in issues
    ]


def render_diff_html(diff_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render import product_theme as ui

    diff = Path(diff_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = read_json(diff / "diff_meta.json", {}) or {}
    summary = read_json(diff / "diff_summary.json", {}) or {}
    view_diff = read_json(diff / "view_diff.json", {"views": []}) or {"views": []}
    type_diff = read_json(diff / "type_diff.json", {"by_type": {}}) or {"by_type": {}}
    release_evidence = read_json(diff / "release_evidence_diff.json", {"by_role": {}}) or {"by_role": {}}
    metadata_tasks = read_json(diff / "metadata_review_tasks.json", {"tasks": []}) or {"tasks": []}
    pairwise_tasks = read_json(diff / "manual_pairwise_tasks.json", None) or read_json(diff / "pairwise_diff_tasks.json", {"tasks": []}) or {"tasks": []}
    issues = read_json(diff / "diff_issues.json", {"issues": []}) or {"issues": []}
    review = _diff_review_model(diff, meta, summary, type_diff, release_evidence, metadata_tasks, pairwise_tasks, issues)
    write_json(out / "comparison_review.json", review)
    pair_rows, done, total = _pairwise_rows(pairwise_tasks)
    pending = max(total - done, 0)
    rail = ui.status_rail([
        ("Catalog", "DISCOVERED", "版本关系来自 catalog"),
        ("Scan", "SCAN_READY", "old/new scan 证据已参与比较"),
        ("Diff", review["review_level"], review["headline"]),
        ("File Diff", "FILE_DIFF_PENDING" if pending else "FILE_DIFF_DONE" if total else "PAIRWISE_EMPTY", f"{done}/{total}"),
        ("Release", "RELEASE_CHECK_REQUIRED", "发布前需检查 manifest / alias"),
    ])
    attention = []
    if pending:
        attention.append(("WARNING", "File Diff 待完成", f"还有 {pending} 个文件对建议打开 File Diff。", "manual_pairwise_tasks.json"))
    for item in issues.get("issues", [])[:20]:
        attention.append((item.get("severity") or "WARNING", item.get("category") or "Diff issue", item.get("message") or item.get("title") or "需确认", "diff_issues.json"))
    body = (
        ui.panel(
            "Comparison 结论 / 结构变化总览",
            "Diff 页面只审阅一次 old → new comparison。库级多版本关系请看 Diff Timeline。",
            ui.metric_grid([
                ("Comparison", f"{review['old_version']} → {review['new_version']}", review.get("mode"), "PASS"),
                ("影响域", sum(1 for x in review["impact"] if x.get("status") in {"CHANGED", "METADATA_ONLY"}), "changed / metadata-only", review["review_level"]),
                ("File Diff", f"{done}/{total}", "done / total", "FILE_DIFF_PENDING" if pending else "FILE_DIFF_DONE" if total else "PAIRWISE_EMPTY"),
                ("注意项", len(attention), review["headline"], review["review_level"]),
            ])
            + ui.compact_meta([("Mode", review.get("mode")), ("Diff Dir", diff), ("Review JSON", out / "comparison_review.json")]),
        )
        + ui.next_action_panel(review["next_action"]["label"], review["next_action"]["command"], review["next_action"]["reason"], status=review["review_level"])
        + ui.panel("变化影响域", "面向使用者：先看变更影响哪个领域，再决定是否打开 File Diff。", ui.impact_grid(review["impact"]))
        + ui.panel("File Diff 队列 / 人工任务摘要", "Diff 不嵌入单文件内容，只提供 File Diff 任务、命令和结果入口。", ui.filterable_table("pairwise-table", ["Type", "Old", "New", "原因", "命令", "状态", "结果"], pair_rows, "暂无 File Diff 任务", "筛选 type / file / status"))
        + ui.panel("优先关注", "只列出会影响继续审阅的事项。", ui.attention_items(attention))
        + ui.collapsible_panel(
            "结构证据",
            "view/type/release evidence/issue 等原始结构变化，默认折叠。",
            ui.collapsible_panel("View 变化", "view presence delta", ui.table(["View", "Status", "Count", "Severity"], _view_rows(view_diff), "暂无 View 变化"), open=False)
            + ui.collapsible_panel("file_type 变化", "按领域归类的文件结构变化", ui.table(["领域", "file_type", "数量", "变化", "状态"], _type_rows(type_diff), "暂无 file_type 变化"), open=False)
            + ui.collapsible_panel("Release Evidence 变化", "release note / waiver / README", ui.table(["Role", "数量", "变化", "状态"], _release_evidence_rows(release_evidence), "暂无 release evidence 变化"), open=False)
            + ui.collapsible_panel("Diff Issues", "原始 diff issue", ui.filterable_table("diff-issues", ["Severity", "Category", "Detail"], _issue_rows(list(issues.get("issues") or [])), "暂无 issue", "筛选 issue"), open=False)
            + ui.trace_link_list([
                ("comparison_review.json", _file_href(out / "comparison_review.json"), "本页面使用的变化导航模型"),
                ("diff_summary.json", _file_href(diff / "diff_summary.json"), "Diff 原始摘要"),
                ("type_diff.json", _file_href(diff / "type_diff.json"), "file_type 结构变化"),
                ("view_diff.json", _file_href(diff / "view_diff.json"), "view 变化"),
                ("manual_pairwise_tasks.json", _file_href(diff / "manual_pairwise_tasks.json"), "File Diff 任务"),
            ]),
            open=False,
        )
    )
    html_text = ui.review_page_shell(
        f"{review['new_version']} vs {review['old_version']} / Diff",
        "DIFF REVIEW",
        review["headline"],
        body,
        decision=review["review_level"],
        rail=rail,
        nav="<a href='#'>Scan</a><a class='active' href='#'>Diff</a><a href='#'>File Diff</a><a href='#'>Release</a>",
        meta=ui.compact_meta([("Old", review["old_version"]), ("New", review["new_version"]), ("Mode", review["mode"]), ("Pairwise", f"{done}/{total}")]),
    )
    atomic_write_text(out / "index.html", html_text)
    atomic_write_text(out / "diff_report.html", html_text)
    return {"status": "PASS", "index_html": str(out / "index.html"), "diff_report_html": str(out / "diff_report.html"), "comparison_review": str(out / "comparison_review.json")}


def render_diff_timeline_html(diff_index: str | Path | Mapping[str, Any], out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render import product_theme as ui

    data = read_json(diff_index, {}) if not isinstance(diff_index, Mapping) else dict(diff_index)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    comparisons = list(data.get("comparisons", []) or [])
    rows = []
    for item in comparisons:
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('mode') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('old_version') or '-')} → {ui.esc(item.get('new_version') or '-')}</td>"
            f"<td>{ui.badge(item.get('status') or item.get('review_level') or 'UNKNOWN')}</td>"
            f"<td>{ui.esc(item.get('pairwise_done', 0))}/{ui.esc(item.get('pairwise_total', 0))}</td>"
            f"<td>{ui.badge(item.get('release_impact') or 'RELEASE_CHECK_REQUIRED')}</td>"
            f"<td>{ui.button('打开 Diff', item.get('diff_html') or item.get('href') or '', 'primary', disabled=not bool(item.get('diff_html') or item.get('href')))}</td>"
            "</tr>"
        )
    body = (
        ui.panel("Diff Timeline", "一个 library 的多版本、多 comparison 入口。只看关系，不展开单次 diff 明细。", ui.comparison_filter_bar() + ui.timeline(comparisons))
        + ui.panel("Comparison 列表", "可按 mode 和状态筛选后进入 Selected Diff Review。", ui.filterable_table("comparison-table", ["Mode", "Comparison", "状态", "File Diff", "Release", "入口"], rows, "暂无 comparison", "筛选版本 / mode / status"))
        + ui.collapsible_panel("证据", "diff_index.json", ui.trace_link_list([("diff_index.json", _file_href(diff_index if not isinstance(diff_index, Mapping) else out / "diff_index.json"), "库级 diff 关系索引")]), open=False)
    )
    if isinstance(diff_index, Mapping):
        write_json(out / "diff_index.json", data)
    html_text = ui.review_page_shell(
        f"{data.get('display_name') or data.get('library_id') or 'Library'} / Diff Timeline",
        "DIFF TIMELINE",
        "库级版本对比关系。单次变化请进入 Selected Diff Review，文件变化请进入 File Diff。",
        body,
        decision="COMPARE_READY" if comparisons else "COMPARE_PENDING",
        nav="<a href='#'>Catalog</a><a class='active' href='#'>Diff Timeline</a><a href='#'>File Diff</a>",
        meta=ui.compact_meta([("Library", data.get("library_id") or "-"), ("Versions", len(data.get("versions", []) or [])), ("Comparisons", len(comparisons))]),
    )
    atomic_write_text(out / "index.html", html_text)
    return {"status": "PASS", "index_html": str(out / "index.html")}
