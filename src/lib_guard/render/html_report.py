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
import csv
import json
import os
import tempfile

from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES


IMPLEMENTATION_TYPES = {"verilog", "cdl"}
ABSTRACT_TYPES = {"lef"}
TIMING_TYPES = {"liberty", "lib", "db"}
CONSTRAINT_TYPES = {"sdc", "spef"}
POWER_TYPES = {"upf", "cpf"}
LAYOUT_TYPES = {"gds", "oas", "layout", "milkyway"}
BINARY_METADATA_TYPES = set(BINARY_METADATA_ONLY_TYPES)
COUNT_ONLY_TYPES = set(SUMMARY_ONLY_TYPES) | set(BINARY_METADATA_ONLY_TYPES)
DOC_TYPES = {"doc", "package", "waiver", "readme", "release_note", "update_note", "changelog", "known_issue", "integration_guide"}
FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)
CORE_VIEW_TYPES = ["lef", "liberty", "verilog"]
VIEW_ORDER = ["lef", "liberty", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db", "gds", "oas", "release_note", "waiver", "readme"]


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_tsv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter="\t")]


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
        "lef": "物理抽象视图。默认抽取 macro、pin、layer、OBS 和几何摘要。",
        "liberty": "时序库视图。普通 scan 默认只计数和识别文件名 corner，不深读内容。",
        "lib": "时序库视图。普通 scan 默认只计数和识别文件名 corner，不深读内容。",
        "verilog": "接口 / 结构视图。普通 scan 默认归入摘要级证据，不运行深解析。",
        "cdl": "电路网表视图。默认抽取 subckt、pin 和 instance 结构摘要。",
        "sdc": "约束视图。默认抽取 clock、group、uncertainty 等摘要。",
        "upf": "电源意图视图。默认抽取 power domain、supply、isolation 等摘要。",
        "cpf": "电源意图视图。默认抽取 domain 和 power mode 等摘要。",
        "spef": "寄生参数视图。普通 scan 默认只计数和识别文件名 corner，不深读内容。",
        "db": "二进制工具库。普通 scan 只记录 metadata，不打开二进制内容。",
        "gds": "版图二进制。普通 scan 只记录 metadata，不打开版图内容。",
        "oas": "版图二进制。普通 scan 只记录 metadata，不打开版图内容。",
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


def _parser_summary(parser_manifest: Mapping[str, Any], parser_quality: Mapping[str, Any]) -> dict[str, Any]:
    by_type: dict[str, dict[str, int]] = {}
    parsed_tasks = 0
    failed_tasks = 0
    pass_empty_tasks = 0
    for file_entry in parser_manifest.get("files", []) or []:
        file_type = str(file_entry.get("file_type") or "unknown")
        for task in file_entry.get("parser_tasks", []) or []:
            if not task.get("parser_name"):
                continue
            item = by_type.setdefault(file_type, {"tasks": 0, "parsed": 0, "failed": 0, "pass_empty": 0})
            item["tasks"] += 1
            status = str(task.get("result_status", task.get("status", ""))).upper()
            if status == "FAILED":
                item["failed"] += 1
                failed_tasks += 1
            elif status == "PASS_EMPTY":
                item["pass_empty"] += 1
                item["parsed"] += 1
                pass_empty_tasks += 1
                parsed_tasks += 1
            else:
                item["parsed"] += 1
                parsed_tasks += 1
    quality = parser_quality.get("parsers", []) if isinstance(parser_quality, Mapping) else []
    return {
        "parser_tasks": sum(item["tasks"] for item in by_type.values()),
        "parsed_tasks": parsed_tasks,
        "failed_tasks": failed_tasks,
        "pass_empty_tasks": pass_empty_tasks,
        "by_type": dict(sorted(by_type.items())),
        "quality_status": parser_quality.get("status") if isinstance(parser_quality, Mapping) else None,
        "parsers": quality,
    }


def _count_only_summary(counts: Mapping[str, int]) -> dict[str, Any]:
    file_type_counts = {name: int(counts.get(name, 0) or 0) for name in sorted(COUNT_ONLY_TYPES) if int(counts.get(name, 0) or 0)}
    return {"file_type_counts": file_type_counts, "total_files": sum(file_type_counts.values())}


def _scan_review_model(
    scan: Path,
    out: Path,
    meta: Mapping[str, Any],
    counts: Mapping[str, int],
    issue_items: list[Mapping[str, Any]],
    release_readiness: Mapping[str, Any],
    corner_summary: Mapping[str, Any],
    parser_summary: Mapping[str, Any],
) -> dict[str, Any]:
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
        msg = str(item.get("message") or item.get("title") or item.get("category") or "扫描问题")
        row = {"level": sev, "category": item.get("category") or "scan_issue", "message": msg}
        if sev in {"ERROR", "BLOCK", "BLOCKER", "FAILED"}:
            blockers.append(row)
        else:
            warnings.append(row)
    if blockers:
        decision = "SCAN_BLOCKED"
        headline = f"发现 {len(blockers)} 个阻塞项，先处理扫描证据。"
    elif warnings:
        decision = "SCAN_NEEDS_REVIEW"
        headline = f"扫描证据可用，但有 {len(warnings)} 个注意项。"
    else:
        decision = "READY_FOR_DIFF"
        headline = "核心扫描证据已具备，可进入对比。"
    library = _library_name(meta)
    version = _version_name(meta)
    base = str(meta.get("base_version") or "<base_version>")
    next_command = f"$PROJ/scripts/lg.csh cmp {library} {version} --base {base} --scan-if-missing" if decision != "SCAN_BLOCKED" else ""
    return {
        "schema_version": "scan_review.v1",
        "decision": decision,
        "headline": headline,
        "library": library,
        "version": version,
        "package_type": meta.get("package_type") or "UNKNOWN",
        "required_views": {"missing": missing_core, "found": [v for v in CORE_VIEW_TYPES if counts.get(v)]},
        "count_only": _count_only_summary(counts),
        "corner_summary": dict(corner_summary or {}),
        "parser_summary": dict(parser_summary or {}),
        "unknown_files": unknown,
        "total_files": sum(int(v or 0) for v in counts.values()),
        "blockers": blockers,
        "warnings": warnings[:50],
        "next_action": {
            "label": "运行对比" if next_command else "补齐扫描证据",
            "command": next_command,
            "reason": "扫描只确认版本交付证据。版本变化需要进入对比 / 文件深度对比查看。" if next_command else "存在阻塞项，暂不建议继续对比。",
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
        if count and name in COUNT_ONLY_TYPES:
            status = "COUNT_ONLY"
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
            f"<td>{ui.esc('yes' if name in CORE_VIEW_TYPES else 'no')}</td>"
            f"<td><code>{ui.esc('count_only' if name in COUNT_ONLY_TYPES and count else 'parsed' if count else 'missing')}</code></td>"
            f"<td>{ui.esc(_type_meaning(name))}</td>"
            "</tr>"
        )
    return rows


def _scan_view_rows_from_review(rows_in: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in rows_in:
        rows.append(
            "<tr>"
            f"<td>{ui.esc(item.get('view_label') or item.get('view_type') or '-')}</td>"
            f"<td>{ui.badge(item.get('status') or '-')}</td>"
            f"<td>{ui.esc(item.get('count') or 0)}</td>"
            f"<td>{ui.esc(item.get('required') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('evidence_level') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('meaning') or '-')}</td>"
            "</tr>"
        )
    return rows


def _files_by_view_rows(rows_in: list[Mapping[str, Any]], limit: int = 800) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in rows_in[:limit]:
        rows.append(
            "<tr>"
            f"<td>{ui.esc(item.get('view_label') or item.get('view_type') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('role') or '-')}</td>"
            f"<td>{ui.esc(item.get('size_bytes') or '-')}</td>"
            f"<td>{ui.badge(item.get('evidence_level') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _unknown_file_rows(rows_in: list[Mapping[str, Any]], limit: int = 300) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in rows_in[:limit]:
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('extension') or '-')}</td>"
            f"<td>{ui.esc(item.get('size_bytes') or '-')}</td>"
            f"<td>{ui.badge(item.get('suggested_action') or '-')}</td>"
            f"<td>{ui.esc(item.get('reason') or '-')}</td>"
            "</tr>"
        )
    return rows


def _large_metadata_rows(rows_in: list[Mapping[str, Any]], limit: int = 500) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in rows_in[:limit]:
        rows.append(
            "<tr>"
            f"<td>{ui.esc(item.get('view_label') or item.get('view_type') or '-')}</td>"
            f"<td>{ui.badge(item.get('evidence_level') or '-')}</td>"
            f"<td>{ui.esc(item.get('size_bytes') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('review_policy') or '-')}</td>"
            "</tr>"
        )
    return rows


def _parser_evidence_rows_from_review(rows_in: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in rows_in:
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.badge(item.get('status') or '-')}</td>"
            f"<td>{ui.esc(item.get('tasks') or 0)}</td>"
            f"<td>{ui.esc(item.get('parsed') or 0)}</td>"
            f"<td>{ui.esc(item.get('empty') or 0)}</td>"
            f"<td>{ui.esc(item.get('failed') or 0)}</td>"
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


def _corner_rows(corner_summary: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in corner_summary.get("examples", []) or []:
        corner = item.get("corner") or {}
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.esc(corner.get('process') or '-')}</td>"
            f"<td>{ui.esc(corner.get('voltage') or '-')}</td>"
            f"<td>{ui.esc(corner.get('temperature') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('file') or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _parser_summary_rows(parser_summary: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for file_type, item in (parser_summary.get("by_type") or {}).items():
        status = "FAILED" if int(item.get("failed", 0) or 0) else "PASS_EMPTY" if int(item.get("pass_empty", 0) or 0) else "PARSED"
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.badge(status)}</td>"
            f"<td>{ui.esc(item.get('tasks', 0))}</td>"
            f"<td>{ui.esc(item.get('parsed', 0))}</td>"
            f"<td>{ui.esc(item.get('pass_empty', 0))}</td>"
            f"<td>{ui.esc(item.get('failed', 0))}</td>"
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
    parser_quality = read_json(scan / "summary" / "parser_quality.json", {}) or {}
    review_dir = scan / "review"
    review_scan = read_json(review_dir / "scan_review.json", {}) or {}
    review_view_rows = read_tsv(review_dir / "view_coverage.tsv")
    review_files_by_view = read_tsv(review_dir / "files_by_view.tsv")
    review_unknown_files = read_tsv(review_dir / "unknown_files.tsv")
    review_large_metadata = read_tsv(review_dir / "large_metadata_files.tsv")
    review_parser_evidence = read_tsv(review_dir / "parser_evidence.tsv")
    files = inventory.get("files", []) or []
    issue_items = list(issues.get("issues", []) or [])
    counts = _type_counts(inventory, parser_manifest, dashboard)
    corner_summary = inventory.get("corner_filename_summary") or {}
    parser_summary = _parser_summary(parser_manifest, parser_quality)
    review = _scan_review_model(scan, out, meta, counts, issue_items, release_readiness, corner_summary, parser_summary)
    write_json(out / "scan_review.json", review)

    attention = [(x.get("level"), x.get("category"), x.get("message"), "scan_review.json") for x in (review.get("blockers") or []) + (review.get("warnings") or [])]
    rail = ui.status_rail([
        ("库目录", "DISCOVERED", "版本已进入库目录"),
        ("扫描", review["decision"], review["headline"]),
        ("对比", "COMPARE_READY" if review["decision"] != "SCAN_BLOCKED" else "NOT_READY", "下一步进入版本对比"),
        ("文件深度对比", "PAIRWISE_EMPTY", "由对比发现变化后生成"),
        ("发布", "RELEASE_CHECK_REQUIRED", "发布前再检查"),
    ])
    body = (
        ui.panel(
            "扫描结论",
            "只保留是否可继续审阅、缺失视图、注意项和下一步。数量明细放在证据区。",
            ui.metric_grid([
                ("Package", review.get("package_type"), "交付类型", "PASS" if review.get("package_type") != "UNKNOWN" else "WARNING"),
                ("核心视图缺失", len(review["required_views"]["missing"]), "LEF / Liberty / Verilog", "WARNING" if review["required_views"]["missing"] else "PASS"),
                ("元数据/摘要文件", int((review_scan or {}).get("large_metadata_files", len(review_large_metadata)) or 0), "summary-only / metadata-only", "INFO" if review_large_metadata else "PASS"),
                ("注意项", len(attention), review["headline"], review["decision"]),
            ])
            + ui.compact_meta([
                ("库", review.get("library")), ("版本", review.get("version")), ("原始根目录", meta.get("root_path") or meta.get("root")), ("扫描目录", scan),
            ]),
        )
        + ui.next_action_panel(review["next_action"]["label"], review["next_action"]["command"], review["next_action"]["reason"], status=review["decision"])
        + ui.panel(
            "View 覆盖矩阵",
            "先看每类交付视图是否存在、证据等级是什么；数量可以在下方文件证据表展开。",
            ui.table(
                ["View", "状态", "数量", "必需", "证据等级", "审查含义"],
                _scan_view_rows_from_review(review_view_rows) if review_view_rows else _scan_view_rows(counts),
                "暂无视图信息",
            ),
        )
        + ui.panel("优先关注", "只显示会影响继续对比 / 使用判断的注意项。", ui.attention_items(attention))
        + ui.panel(
            "文件证据表",
            "数量必须能追到文件。这里按 View 聚合列出路径、角色、证据等级；大表默认支持筛选。",
            ui.filterable_table(
                "files-by-view-table",
                ["View", "file_type", "role", "size", "证据等级", "path"],
                _files_by_view_rows(review_files_by_view) if review_files_by_view else _file_rows(files),
                "暂无文件证据",
                "筛选 View / file_type / path",
            ),
        )
        + ui.collapsible_panel(
            "Unknown 文件",
            "未识别文件不应被数量淹没；这里集中列出需要分类或确认可忽略的文件。",
            ui.filterable_table(
                "unknown-file-table",
                ["path", "extension", "size", "建议动作", "原因"],
                _unknown_file_rows(review_unknown_files),
                "没有 unknown 文件",
                "筛选 unknown 文件",
            ),
            open=bool(review_unknown_files),
        )
        + ui.collapsible_panel(
            "摘要级 / 元数据级文件",
            "大文件不是没审查，而是按证据等级审查；这里解释每个文件为什么不默认深读。",
            ui.filterable_table(
                "large-metadata-table",
                ["View", "证据等级", "size", "path", "审查策略"],
                _large_metadata_rows(review_large_metadata),
                "没有摘要级或元数据级文件",
                "筛选大文件 / 证据等级",
            ),
            open=False,
        )
        + ui.collapsible_panel(
            "调试证据区",
            "原始 JSON、cache、progress 和机器清单只作为追溯证据；人工审查优先看上面的证据表。",
            ui.trace_link_list([
                ("review/scan_review.json", _file_href(review_dir / "scan_review.json"), "scan 人工证据摘要"),
                ("review/view_coverage.tsv", _file_href(review_dir / "view_coverage.tsv"), "View 覆盖表"),
                ("review/files_by_view.tsv", _file_href(review_dir / "files_by_view.tsv"), "按 View 聚合的文件证据表"),
                ("review/unknown_files.tsv", _file_href(review_dir / "unknown_files.tsv"), "未识别文件表"),
                ("review/large_metadata_files.tsv", _file_href(review_dir / "large_metadata_files.tsv"), "摘要级 / 元数据级文件表"),
                ("review/parser_evidence.tsv", _file_href(review_dir / "parser_evidence.tsv"), "Parser 证据表"),
                ("scan_review.json", _file_href(out / "scan_review.json"), "当前 HTML 使用的审阅导航模型"),
                ("scan_meta.json", _file_href(scan / "scan_meta.json"), "版本和原始根目录上下文"),
                ("file_inventory.json", _file_href(scan / "file_inventory.json"), "完整文件清单"),
                ("scan_issues.json", _file_href(scan / "scan_issues.json"), "扫描原始问题"),
                ("release_readiness.json", _file_href(scan / "summary" / "release_readiness.json"), "后续发布检查参考"),
            ])
            + ui.filterable_table("file-type-table", ["领域", "file_type", "数量", "说明"], _file_type_rows(counts), "暂无 file_type", "筛选 file_type / 领域")
            + ui.collapsible_panel("旧版完整文件列表", "兼容旧 scan JSON；新审查优先看 files_by_view.tsv。", ui.filterable_table("file-list", ["file_type", "role", "size", "path"], _file_rows(files), "暂无文件", "筛选文件路径"), open=False),
            open=False,
        )
    )
    count_only = review.get("count_only") or {}
    corner = review.get("corner_summary") or {}
    parser = review.get("parser_summary") or {}
    body += (
        ui.panel(
            "大文件计数与 Corner 摘要",
            "大体量时序、寄生和二进制视图只按路径/文件名计数和归类；普通 scan 不读取它们的内容。",
            ui.metric_grid([
                ("计数文件", count_only.get("total_files", 0), ", ".join(f"{k}:{v}" for k, v in (count_only.get("file_type_counts") or {}).items()) or "无", "INFO" if count_only.get("total_files") else "PASS"),
                ("Process corners", len(corner.get("process_counts") or {}), ", ".join(f"{k}:{v}" for k, v in (corner.get("process_counts") or {}).items()) or "none", "PASS" if corner.get("process_counts") else "INFO"),
                ("Voltage corners", len(corner.get("voltage_counts") or {}), ", ".join(f"{k}:{v}" for k, v in (corner.get("voltage_counts") or {}).items()) or "none", "PASS" if corner.get("voltage_counts") else "INFO"),
                ("Temperature corners", len(corner.get("temperature_counts") or {}), ", ".join(f"{k}:{v}" for k, v in (corner.get("temperature_counts") or {}).items()) or "none", "PASS" if corner.get("temperature_counts") else "INFO"),
            ])
            + ui.table(["file_type", "Process", "Voltage", "Temp", "Path"], _corner_rows(corner), "没有文件名 corner 线索"),
        )
        + ui.panel(
            "解析器摘要",
            "默认运行的轻量解析器只提供结构摘要，作为版本审查证据。",
            ui.table(
                ["file_type", "状态", "任务", "已解析", "空结果", "失败"],
                _parser_evidence_rows_from_review(review_parser_evidence) if review_parser_evidence else _parser_summary_rows(parser),
                "没有解析器任务",
            ),
        )
    )
    html_text = ui.review_page_shell(
        f"{review.get('library')} / {review.get('version')} / 扫描",
        "扫描审查",
        review["headline"],
        body,
        decision=review["decision"],
        rail=rail,
        nav="<a class='active' href='#'>扫描</a><a href='#'>对比</a><a href='#'>文件深度对比</a><a href='#'>发布</a>",
        meta=ui.compact_meta([("包类型", review.get("package_type")), ("文件总数", review.get("total_files")), ("未知", review.get("unknown_files"))]),
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
    items.append({"domain": "发布证据", "status": "CHANGED" if ev_count else "SAME", "label": "changed" if ev_count else "same", "count": ev_count, "hint": "release note / waiver / README"})
    meta_count = len(metadata_tasks.get("tasks", []) or [])
    items.append({"domain": "元数据级证据", "status": "METADATA_ONLY" if meta_count else "SAME", "label": "metadata" if meta_count else "same", "count": meta_count, "hint": "DB / GDS / OAS 等二进制证据"})
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


def _task_priority(item: Mapping[str, Any]) -> str:
    text = str(item.get("priority") or item.get("severity") or "P1").upper()
    return text if text in {"P0", "P1", "P2", "P3"} else "P1"


def _task_is_key_view(item: Mapping[str, Any]) -> bool:
    return str(item.get("file_type") or "").lower() in {"lef", "liberty", "lib", "verilog", "cdl", "sdc", "upf", "cpf"}


def _changed_file_total(summary: Mapping[str, Any], type_diff: Mapping[str, Any], file_diff: Mapping[str, Any], pairwise_tasks: Mapping[str, Any]) -> int:
    for key in ["changed_files", "total_changed_files", "file_changes", "changed_file_total"]:
        try:
            value = int(summary.get(key, 0) or 0)
            if value:
                return value
        except Exception:
            pass
    counts = file_diff.get("counts") or {}
    total = 0
    for key in ["added", "removed", "changed", "metadata_only_changed"]:
        try:
            total += int(counts.get(key, 0) or 0)
        except Exception:
            pass
    if total:
        return total
    by_type = type_diff.get("by_type") or {}
    for item in by_type.values():
        try:
            total += int(item.get("added_count", 0) or 0) + int(item.get("removed_count", 0) or 0) + int(item.get("changed_count", 0) or 0)
        except Exception:
            continue
    if total:
        return total
    return len(pairwise_tasks.get("tasks", []) or [])


def _comparison_quality(changed_total: int, file_diff: Mapping[str, Any], meta: Mapping[str, Any], issues: Mapping[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    counts = file_diff.get("counts") or {}
    added = int(counts.get("added", 0) or 0)
    removed = int(counts.get("removed", 0) or 0)
    changed = int(counts.get("changed", 0) or 0)
    relation = meta.get("version_relation", {}) if isinstance(meta.get("version_relation"), Mapping) else {}
    if not (relation.get("old_version") or meta.get("old_version")) or not (relation.get("new_version") or meta.get("new_version")):
        reasons.append("old/new version 关系不完整")
    if changed_total >= 1000:
        reasons.append(f"变化文件 {changed_total} 个，疑似 comparison 过大")
        return "DIFF_EXPLOSION", reasons
    if changed_total >= 200:
        reasons.append(f"变化文件 {changed_total} 个，建议先确认 base / parent")
        return "LARGE_CHANGE", reasons
    if added + removed > max(changed * 3, 50):
        reasons.append(f"added/removed 远大于 changed：+{added}/-{removed}/~{changed}")
        return "PATH_RESTRUCTURE", reasons
    for item in issues.get("issues", []) or []:
        if str(item.get("category") or "").lower() in {"base", "version_relation", "scan_missing"}:
            reasons.append(str(item.get("message") or item.get("title") or "需确认 comparison 证据"))
            return "NEEDS_BASE_CONFIRM", reasons
    return "NORMAL", reasons


def _file_diff_recommendation(
    meta: Mapping[str, Any],
    summary: Mapping[str, Any],
    type_diff: Mapping[str, Any],
    file_diff: Mapping[str, Any],
    pairwise_tasks: Mapping[str, Any],
    issues: Mapping[str, Any],
) -> dict[str, Any]:
    tasks = list(pairwise_tasks.get("tasks", []) or [])
    changed_total = _changed_file_total(summary, type_diff, file_diff, pairwise_tasks)
    quality, reasons = _comparison_quality(changed_total, file_diff, meta, issues)
    # File Diff is recommendation, not completion. Keep only key-view P0/P1 items by default.
    if quality in {"DIFF_EXPLOSION", "LARGE_CHANGE", "PATH_RESTRUCTURE", "NEEDS_BASE_CONFIRM"}:
        max_items = 8
        allowed_priorities = {"P0"}
        allowed = [t for t in tasks if _task_is_key_view(t)] or tasks
    else:
        max_items = 24
        allowed_priorities = {"P0", "P1"}
        allowed = tasks
    recommended: list[dict[str, Any]] = []
    generated = 0
    needs_run = 0
    for item in allowed:
        pri = _task_priority(item)
        if pri not in allowed_priorities and len(recommended) >= max_items // 2:
            continue
        status, note, href = _pairwise_result_for(item)
        is_generated = status.upper() in {"DONE", "PASS", "SAME", "DIFF"} or bool(href)
        if is_generated:
            generated += 1
        else:
            needs_run += 1
        recommended.append({
            "priority": pri,
            "file_type": item.get("file_type") or "-",
            "old_path": item.get("old_path") or item.get("old_file") or "-",
            "new_path": item.get("new_path") or item.get("new_file") or "-",
            "reason": item.get("reason") or item.get("review_reason") or "关键视图变化，建议打开文件深度对比。",
            "status": status,
            "note": note,
            "result_html": href,
        })
        if len(recommended) >= max_items:
            break
    candidate_total = max(changed_total, len(tasks))
    suppressed_total = max(candidate_total - len(recommended), 0)
    return {
        "schema_version": "file_diff_recommendation.v1",
        "policy": "key_view_first_not_completion",
        "comparison_quality": quality,
        "quality_reasons": reasons,
        "changed_file_total": changed_total,
        "candidate_total": candidate_total,
        "recommended_total": len(recommended),
        "result_generated": generated,
        "needs_run": needs_run,
        "suppressed_total": suppressed_total,
        "items": recommended,
        "suppressed_summary": [
            {"reason": "not_recommended_by_policy", "count": suppressed_total},
        ] if suppressed_total else [],
    }


def _recommendation_rows(recommendation: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows: list[str] = []
    for item in recommendation.get("items", []) or []:
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('priority'), item.get('priority'))}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('old_path') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('new_path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('reason') or '')}</td>"
            f"<td>{ui.badge(item.get('status') or 'FILE_DIFF_RECOMMENDED')}<div class='muted'>{ui.esc(item.get('note') or '')}</div></td>"
            f"<td>{ui.button('打开文件深度对比', item.get('result_html') or '', 'primary', disabled=not bool(item.get('result_html')))}</td>"
            "</tr>"
        )
    return rows


def _diff_review_model(diff: Path, meta: Mapping[str, Any], summary: Mapping[str, Any], type_diff: Mapping[str, Any], file_diff: Mapping[str, Any], release_evidence: Mapping[str, Any], metadata_tasks: Mapping[str, Any], pairwise_tasks: Mapping[str, Any], issues: Mapping[str, Any]) -> dict[str, Any]:
    relation = meta.get("version_relation", {}) if isinstance(meta.get("version_relation"), Mapping) else {}
    old_version = relation.get("old_version") or meta.get("old_version") or "<old>"
    new_version = relation.get("new_version") or meta.get("new_version") or "<new>"
    mode = relation.get("mode") or relation.get("diff_mode") or meta.get("diff_mode") or "selected"
    issue_items = list(issues.get("issues") or [])
    impact = _domain_impact(type_diff, release_evidence, metadata_tasks)
    changed_domains = [item["domain"] for item in impact if item.get("status") in {"CHANGED", "METADATA_ONLY"}]
    recommendation = _file_diff_recommendation(meta, summary, type_diff, file_diff, pairwise_tasks, issues)
    blockers = [i for i in issue_items if str(i.get("severity") or "").upper() in {"ERROR", "BLOCK", "BLOCKER", "FAILED"}]
    quality = recommendation["comparison_quality"]
    if blockers:
        review_level = "DIFF_BLOCKED"
        headline = f"发现 {len(blockers)} 个对比阻塞项。"
    elif quality != "NORMAL":
        review_level = quality
        headline = f"对比需确认：{'; '.join(recommendation.get('quality_reasons') or [quality])}。系统只保留重点文件确认项。"
    elif recommendation["needs_run"]:
        review_level = "FILE_DIFF_RECOMMENDED"
        headline = f"{len(changed_domains)} 个影响域有变化，建议确认 {recommendation['recommended_total']} 个重点文件。"
    elif changed_domains:
        review_level = "CHANGED"
        headline = f"{len(changed_domains)} 个影响域有变化，重点文件已有结果或无需额外确认。"
    else:
        review_level = "SAME"
        headline = "未发现需要优先处理的结构变化。"
    return {
        "schema_version": "comparison_review.v2",
        "comparison_id": f"{mode}__{old_version}__{new_version}",
        "old_version": old_version,
        "new_version": new_version,
        "mode": mode,
        "review_level": review_level,
        "headline": headline,
        "impact": impact,
        "file_diff_recommendation": recommendation,
        "issues": issue_items,
        "next_action": {
            "label": "查看重点证据 / 返回 Timeline",
            "command": "",
            "reason": "页面只展示重点确认项；不再自动提供脚本命令。",
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

def _severity_rank(value: Any) -> int:
    text = str(value or "").upper()
    if text in {"BLOCKER", "BLOCK", "ERROR", "FAILED"}:
        return 0
    if text in {"WARNING", "WARN", "CHANGED"}:
        return 1
    return 2


def _view_order_key(view: str) -> tuple[int, str]:
    key = str(view or "unknown").lower()
    try:
        return (VIEW_ORDER.index(key), key)
    except ValueError:
        return (len(VIEW_ORDER), key)


def _status_label_pair(old_status: Any, new_status: Any, *, changed: bool) -> tuple[str, str]:
    old = str(old_status or "").strip()
    new = str(new_status or "").strip()
    if not old and not new:
        return "-", "仅文件计数" if changed else "未进入 readiness"
    if old == new:
        return old or "-", "状态保持"
    return f"{old or '-'} → {new or '-'}", "状态变化"


def _view_rows(view_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    items = sorted(
        list(view_diff.get("views", []) or []),
        key=lambda item: (
            0 if item.get("changed") else 1,
            _severity_rank(item.get("severity") or item.get("status")),
            *_view_order_key(str(item.get("view") or "")),
        ),
    )
    for item in items:
        changed = bool(item.get("changed"))
        status = item.get("severity") or ("CHANGED" if changed else "INFO")
        status_pair, meaning = _status_label_pair(item.get("old_status"), item.get("new_status"), changed=changed)
        old_count = int(item.get("old_count", 0) or 0)
        new_count = int(item.get("new_count", 0) or 0)
        delta = new_count - old_count
        requirement = str(item.get("requirement") or "file_type").replace("_", " ")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('view') or '-')}</code></td>"
            f"<td>{ui.badge(requirement, requirement)}</td>"
            f"<td>{ui.esc(status_pair)}</td>"
            f"<td>{ui.esc(old_count)} → {ui.esc(new_count)} <span class='muted'>({delta:+d})</span></td>"
            f"<td><span class='muted'>{ui.esc(meaning)}</span></td>"
            f"<td>{ui.badge(status)}</td>"
            "</tr>"
        )
    return rows


def _review_mode_label(value: Any, file_type: str) -> str:
    text = str(value or "").strip().lower()
    labels = {
        "manual_pairwise": "重点文件证据确认",
        "metadata_only": "只做 metadata",
        "governance": "治理/归档确认",
    }
    if text in labels:
        return labels[text]
    if str(file_type or "").lower() in FILE_DIFF_TYPES:
        return "重点文件证据确认"
    return "结构计数"


def _type_rows(type_diff: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    items = sorted(
        (type_diff.get("by_type") or {}).items(),
        key=lambda kv: (
            0 if _type_item_changed(kv[1]) else 1,
            _severity_rank(kv[1].get("status")),
            _type_group(kv[0]),
            kv[0],
        ),
    )
    for file_type, item in items:
        changed = _type_item_changed(item)
        status = item.get("status") or ("CHANGED" if changed else "SAME")
        added = int(item.get("added_count", 0) or 0)
        removed = int(item.get("removed_count", 0) or 0)
        changed_count = int(item.get("changed_count", 0) or 0)
        rows.append(
            "<tr>"
            f"<td>{ui.badge(_type_group(file_type), _type_group(file_type))}</td>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(item.get('old_count', 0))} → {ui.esc(item.get('new_count', 0))}</td>"
            f"<td>+{ui.esc(added)} / -{ui.esc(removed)} / ~{ui.esc(changed_count)}</td>"
            f"<td>{ui.esc(_review_mode_label(item.get('review_mode'), file_type))}</td>"
            f"<td>{ui.badge(status)}</td>"
            "</tr>"
        )
    return rows


def _structure_overview_panel(view_diff: Mapping[str, Any], type_diff: Mapping[str, Any]) -> str:
    from lib_guard.render import product_theme as ui

    view_summary = view_diff.get("summary") or {}
    type_summary = type_diff.get("summary") or {}
    view_rows = _view_rows(view_diff)
    type_rows = _type_rows(type_diff)
    return (
        "<style>"
        ".structure-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}"
        ".structure-card{border:1px solid var(--line);border-radius:12px;background:#fff;overflow:hidden}"
        ".structure-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:12px 14px;border-bottom:1px solid var(--line);background:#f8fafc}"
        ".structure-card-head h3{margin:0;font-size:15px}.structure-card-head p{font-size:12px;margin-top:3px}"
        ".structure-scroll{max-height:492px;overflow:auto;scrollbar-gutter:stable}"
        ".structure-scroll table{font-size:12px}.structure-scroll th{position:sticky;top:0;z-index:1}.structure-scroll td{padding:8px 10px}"
        ".structure-kpis{display:flex;gap:7px;flex-wrap:wrap}.structure-kpis span{display:inline-flex;border:1px solid var(--line);border-radius:999px;background:#fff;padding:4px 8px;font-size:12px;color:#344054}"
        "@media(max-width:1200px){.structure-grid{grid-template-columns:1fr}}"
        "</style>"
        "<div class='structure-grid'>"
        "<section class='structure-card'>"
        "<div class='structure-card-head'><div><h3>视图全量状态</h3><p>按变化优先排序；默认露出约 10 行，更多在表内滚动。</p></div>"
        f"<div class='structure-kpis'><span>{ui.esc(view_summary.get('total', len(view_rows)))} 个视图</span><span>{ui.esc(view_summary.get('changed', 0))} 个变化</span></div></div>"
        f"<div class='structure-scroll'>{ui.table(['视图', '类型', '状态', '数量', '含义', '判断'], view_rows, '暂无视图信息')}</div>"
        "</section>"
        "<section class='structure-card'>"
        "<div class='structure-card-head'><div><h3>文件类型全量变化</h3><p>说明每类文件是结构计数、元数据，还是重点文件证据确认。</p></div>"
        f"<div class='structure-kpis'><span>{ui.esc(type_summary.get('new_type_count', len(type_rows)))} types</span><span>{ui.esc(type_summary.get('changed_types', 0))} changed</span></div></div>"
        f"<div class='structure-scroll'>{ui.table(['领域', 'file_type', '数量', '增/删/改', '核查方式', '判断'], type_rows, '暂无 file_type 信息')}</div>"
        "</section>"
        "</div>"
    )


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
    file_diff = read_json(diff / "file_diff.json", {"counts": {}}) or {"counts": {}}
    release_evidence = read_json(diff / "release_evidence_diff.json", {"by_role": {}}) or {"by_role": {}}
    metadata_tasks = read_json(diff / "metadata_review_tasks.json", {"tasks": []}) or {"tasks": []}
    pairwise_tasks = read_json(diff / "manual_pairwise_tasks.json", None) or read_json(diff / "pairwise_diff_tasks.json", {"tasks": []}) or {"tasks": []}
    issues = read_json(diff / "diff_issues.json", {"issues": []}) or {"issues": []}
    review = _diff_review_model(diff, meta, summary, type_diff, file_diff, release_evidence, metadata_tasks, pairwise_tasks, issues)
    write_json(out / "comparison_review.json", review)
    recommendation = review["file_diff_recommendation"]
    rec_rows = _recommendation_rows(recommendation)
    rail = ui.status_rail([
        ("库目录", "DISCOVERED", "版本关系来自库目录"),
        ("扫描", "SCAN_READY", "旧版/新版扫描证据已参与比较"),
        ("对比", review["review_level"], review["headline"]),
        ("重点文件建议", recommendation.get("comparison_quality") or review["review_level"], f"重点 {recommendation.get('recommended_total', 0)} / 候选 {recommendation.get('candidate_total', 0)}"),
        ("发布", "RELEASE_CHECK_REQUIRED", "发布前需检查 manifest / alias"),
    ])
    attention = []
    if recommendation.get("comparison_quality") != "NORMAL":
        attention.append((recommendation.get("comparison_quality"), "对比需确认", "变化规模或版本关系异常；不要执行全量文件深度对比。", "comparison_review.json"))
    if recommendation.get("needs_run"):
        attention.append(("WARNING", "重点文件确认项", f"有 {recommendation.get('needs_run')} 个重点文件需要确认；不自动提供脚本命令。", "manual_pairwise_tasks.json"))
    for item in issues.get("issues", [])[:20]:
        attention.append((item.get("severity") or "WARNING", item.get("category") or "对比问题", item.get("message") or item.get("title") or "需确认", "diff_issues.json"))
    body = (
        ui.panel(
            "对比结论",
            "对比页面只审阅一次旧版 → 新版比较。库级多版本关系请看对比时间线。",
            ui.metric_grid([
                ("对比对象", f"{review['old_version']} → {review['new_version']}", review.get("mode"), "PASS"),
                ("影响域", sum(1 for x in review["impact"] if x.get("status") in {"CHANGED", "METADATA_ONLY"}), "变化 / 元数据级", review["review_level"]),
                ("重点建议", recommendation.get("recommended_total", 0), "不是全量完成度", review["review_level"]),
                ("候选变化", recommendation.get("candidate_total", 0), "大量候选默认折叠", recommendation.get("comparison_quality")),
                ("已生成结果", recommendation.get("result_generated", 0), "仅统计推荐队列", "PASS" if recommendation.get("result_generated") else "WARNING"),
                ("注意项", len(attention), review["headline"], review["review_level"]),
            ])
            + ui.compact_meta([("模式", review.get("mode")), ("对比目录", diff), ("审查 JSON", out / "comparison_review.json")]),
        )
        + ui.panel("结构概览", "优先看视图是否齐、文件类型是否异常增长，再决定是否进入文件深度对比。视图和文件类型都显示全量，默认露出 10 行。", _structure_overview_panel(view_diff, type_diff))
        + ui.next_action_panel(review["next_action"]["label"], review["next_action"]["command"], review["next_action"]["reason"], status=review["review_level"])
        + ui.panel("变化影响域", "面向使用者：先看变更影响哪个领域，再决定是否打开文件深度对比。", ui.impact_grid(review["impact"]))
        + ui.panel("重点文件确认项", "这里是重点变化证据入口，不是全量差异完成度；页面不再自动给出脚本命令。", ui.filterable_table("recommend-file-diff-table", ["优先级", "类型", "旧文件", "新文件", "原因", "状态", "结果"], rec_rows, "暂无重点文件确认项", "筛选类型 / 文件 / 状态"))
        + ui.collapsible_panel("候选变化 / 已折叠", "候选变化不默认展开，避免错误 base 或大规模重组导致上千条无效确认项。", ui.metric_grid([("候选变化", recommendation.get("candidate_total", 0), "changed/candidate files", recommendation.get("comparison_quality")), ("已折叠", recommendation.get("suppressed_total", 0), "未进入重点队列", "WARNING" if recommendation.get("suppressed_total") else "PASS"), ("策略", recommendation.get("policy"), "key view first", "INFO")]) + ui.table(["Reason", "Count"], [f"<tr><td>{ui.esc(x.get('reason'))}</td><td>{ui.esc(x.get('count'))}</td></tr>" for x in recommendation.get("suppressed_summary", [])], "暂无折叠项"), open=False)
        + ui.panel("优先关注", "只列出会影响继续审阅的事项。", ui.attention_items(attention))
        + ui.collapsible_panel(
            "补充证据",
            "发布证据、对比问题和原始 JSON 链接默认折叠；结构概览已经前置展示。",
            ui.collapsible_panel("发布证据变化", "release note / waiver / README", ui.table(["角色", "数量", "变化", "状态"], _release_evidence_rows(release_evidence), "暂无发布证据变化"), open=False)
            + ui.collapsible_panel("对比问题", "原始对比问题", ui.filterable_table("diff-issues", ["级别", "类别", "详情"], _issue_rows(list(issues.get("issues") or [])), "暂无问题", "筛选问题"), open=False)
            + ui.trace_link_list([
                ("comparison_review.json", _file_href(out / "comparison_review.json"), "本页面使用的变化导航模型"),
                ("diff_summary.json", _file_href(diff / "diff_summary.json"), "对比原始摘要"),
                ("type_diff.json", _file_href(diff / "type_diff.json"), "file_type 结构变化"),
                ("view_diff.json", _file_href(diff / "view_diff.json"), "视图变化"),
                ("manual_pairwise_tasks.json", _file_href(diff / "manual_pairwise_tasks.json"), "原始文件深度对比候选任务；页面只推荐重点项"),
            ]),
            open=False,
        )
    )
    html_text = ui.review_page_shell(
        f"{review['new_version']} vs {review['old_version']} / 对比",
        "对比审查",
        review["headline"],
        body,
        decision=review["review_level"],
        rail=rail,
        nav="<a href='#'>扫描</a><a class='active' href='#'>选定对比</a><a href='#'>文件深度对比从本页下钻</a><a href='#'>发布</a>",
        meta=ui.compact_meta([("旧版", review["old_version"]), ("新版", review["new_version"]), ("模式", review["mode"]), ("重点建议", recommendation.get("recommended_total", 0)), ("候选", recommendation.get("candidate_total", 0))]),
    )
    atomic_write_text(out / "index.html", html_text)
    atomic_write_text(out / "diff_report.html", html_text)
    return {"status": "PASS", "index_html": str(out / "index.html"), "diff_report_html": str(out / "diff_report.html"), "comparison_review": str(out / "comparison_review.json")}
