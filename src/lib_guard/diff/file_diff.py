from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from datetime import datetime, timezone
import difflib
import hashlib
import gzip
import json


TYPE_LABELS = {
    "lef": "LEF 物理抽象",
    "liberty": "Liberty 时序库",
    "verilog": "Verilog RTL/Netlist",
    "cdl": "CDL/SPICE 网表",
    "sdc": "SDC 约束",
    "upf": "UPF 电源意图",
    "cpf": "CPF 电源意图",
    "spef": "SPEF 寄生参数",
    "db": "DB 二进制库",
    "waiver": "Waiver 规则",
    "ibis": "IBIS SI 模型",
    "pwl": "PWL 波形模型",
    "snp": "Touchstone SNP 模型",
    "cpm": "CPM package/model",
}

TYPE_FOCUS = {
    "lef": "关注 macro、pin、direction、layer、size 等物理抽象变化。",
    "liberty": "关注 library、cell、pin、timing arc、corner 等时序库结构变化。",
    "verilog": "关注 module、port、方向、位宽、实例等接口与结构变化。",
    "cdl": "关注 subckt、pin、instance/device 数量变化。",
    "sdc": "关注 clock、generated clock、约束命令与例外路径变化。",
    "upf": "关注 power domain、supply net、isolation、level shifter、retention 变化。",
    "cpf": "关注 power domain、power mode、isolation/level shifter/retention rule 变化。",
    "spef": "当前为轻量解析，关注 header 与 D_NET 数量等结构信号。",
    "db": "DB 为二进制文件，当前仅做 metadata/hash 级证据，不做语义解析。",
    "waiver": "关注 waiver 条目增删、规则名和作用对象变化。",
    "ibis": "关注 component、pin、model 和 model_type 变化。",
    "pwl": "关注 PWL 点数、时间/值变化和异常 directive。",
    "snp": "关注 Touchstone option line、端口数和频点数据行变化。",
    "cpm": "关注 component、pin、方向和记录数量变化。",
}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _stable_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_gzip_file(path: Path) -> bool:
    if path.suffix.lower() == ".gz":
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def _read_text(path: Path) -> list[str]:
    try:
        if _is_gzip_file(path):
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                return fh.read().splitlines()
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [f"<read failed: {type(exc).__name__}: {exc}>"]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _semantic_diff(old_data: Any, new_data: Any) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []

    def walk(old_value: Any, new_value: Any, path: str) -> None:
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            keys = sorted(set(old_value) | set(new_value), key=str)
            for key in keys:
                child = f"{path}.{key}" if path else str(key)
                if key not in old_value:
                    changes.append({"path": child, "change_type": "added", "old": None, "new": new_value[key]})
                elif key not in new_value:
                    changes.append({"path": child, "change_type": "removed", "old": old_value[key], "new": None})
                else:
                    walk(old_value[key], new_value[key], child)
            return
        if isinstance(old_value, list) and isinstance(new_value, list):
            if old_value == new_value:
                return
            old_norm = {json.dumps(item, sort_keys=True, ensure_ascii=False, default=str): item for item in old_value}
            new_norm = {json.dumps(item, sort_keys=True, ensure_ascii=False, default=str): item for item in new_value}
            added_keys = sorted(set(new_norm) - set(old_norm))
            removed_keys = sorted(set(old_norm) - set(new_norm))
            changes.append({
                "path": path,
                "change_type": "list_changed",
                "old_count": len(old_value),
                "new_count": len(new_value),
                "added_count": len(added_keys),
                "removed_count": len(removed_keys),
                "added_samples": [new_norm[key] for key in added_keys[:5]],
                "removed_samples": [old_norm[key] for key in removed_keys[:5]],
            })
            return
        if old_value != new_value:
            changes.append({"path": path or "$", "change_type": "changed", "old": old_value, "new": new_value})

    walk(old_data, new_data, "")
    by_type: dict[str, int] = {}
    for item in changes:
        change_type = str(item.get("change_type"))
        by_type[change_type] = by_type.get(change_type, 0) + 1
    return {"schema_version": "1.0", "status": "SAME" if not changes else "DIFF", "summary": {"change_count": len(changes), "by_type": dict(sorted(by_type.items()))}, "changes": changes[:1000], "truncated": len(changes) > 1000}


def _render_raw_text_diff(old: Path, new: Path, out: Path) -> None:
    diff_html = difflib.HtmlDiff(wrapcolumn=120).make_file(
        _read_text(old),
        _read_text(new),
        fromdesc=str(old),
        todesc=str(new),
        context=True,
        numlines=3,
        charset="utf-8",
    )
    _write_text(out / "raw_text_diff.html", diff_html)


def _clip(value: Any, limit: int = 180) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _change_location(item: dict[str, Any]) -> str:
    bits: list[str] = []
    for side in ["old", "new"]:
        value = item.get(side)
        if isinstance(value, dict):
            line = value.get("line") or value.get("line_start")
            raw = value.get("raw")
            if line:
                bits.append(f"{side}:L{line}")
            if raw:
                bits.append(f"{side}: {str(raw)[:80]}")
    for sample_key in ["removed_samples", "added_samples"]:
        samples = item.get(sample_key)
        if isinstance(samples, list):
            for sample in samples[:2]:
                if isinstance(sample, dict):
                    line = sample.get("line") or sample.get("line_start")
                    raw = sample.get("raw")
                    if line:
                        bits.append(f"{sample_key}:L{line}")
                    if raw:
                        bits.append(f"{sample_key}: {str(raw)[:80]}")
    return " | ".join(bits) if bits else "-"


def _domain_counts(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in changes:
        path = str(item.get("path") or "$")
        domain = path.split(".", 1)[0] or "$"
        counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12])


def _render_index(out: Path, meta: dict[str, Any], summary: dict[str, Any], semantic: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    from lib_guard.render import product_theme as ui

    file_type = str(summary.get("file_type") or meta.get("file_type") or "unknown")
    status = str(summary.get("status") or "UNKNOWN")
    changes = list(semantic.get("changes", []) or [])
    change_count = int((semantic.get("summary") or {}).get("change_count") or 0)
    parser_status = f"{summary.get('old_parser_status')} / {summary.get('new_parser_status')}"
    evidence_mode = "metadata-only" if file_type == "db" or "METADATA_ONLY" in parser_status else "structured + raw"
    domain_rows = [f"<tr><td><code>{ui.esc(k)}</code></td><td>{ui.esc(v)}</td></tr>" for k, v in _domain_counts(changes).items()]
    change_rows = []
    for item in changes[:200]:
        change_rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('change_type'), item.get('change_type'))}</td>"
            f"<td><code>{ui.esc(item.get('path', '-'))}</code></td>"
            f"<td><code>{ui.esc(_change_location(item))}</code></td>"
            f"<td><code>{ui.esc(_clip(item.get('old')))}</code></td>"
            f"<td><code>{ui.esc(_clip(item.get('new')))}</code></td>"
            "</tr>"
        )
    issue_rows = [
        "<tr>"
        f"<td>{ui.badge(item.get('severity') or 'WARNING')}</td>"
        f"<td>{ui.esc(item.get('category') or 'parser')}</td>"
        f"<td>{ui.esc(item.get('title') or item.get('message') or item)}</td>"
        "</tr>"
        for item in issues
    ]
    rail = ui.status_rail([
        ("Diff", "NEEDS_FILE_DIFF", "本页由 Diff 任务进入"),
        ("File Diff", status, f"结构化变化 {change_count}"),
        ("Raw Diff", "READY", "可打开 raw_text_diff.html"),
        ("Review", "MANUAL_REVIEW" if status == "DIFF" else "SAME", "最终结论由使用者确认"),
    ])
    body = (
        ui.panel(
            "File Diff 结论 / 单文件深度对比报告",
            "单文件深度页只服务一个 old_file → new_file。Diff 主页面只保留任务和入口。",
            ui.metric_grid([
                ("file_type", file_type, TYPE_LABELS.get(file_type, file_type), status),
                ("结构化变化", change_count, "semantic_diff.json", status),
                ("Parser", parser_status, "old / new", "WARNING" if "FAILED" in parser_status else "PASS"),
                ("证据模式", evidence_mode, "structured + raw / metadata-only", "METADATA_ONLY" if evidence_mode == "metadata-only" else "PASS"),
            ])
            + ui.compact_meta([("Old", meta.get("old_file")), ("New", meta.get("new_file")), ("Focus", TYPE_FOCUS.get(file_type, "人工复核文件变化。"))]),
        )
        + ui.panel("变化域分布", "用于快速定位变化集中在哪些结构域。", ui.table(["域", "变化数"], domain_rows, "未发现结构化变化"))
        + ui.panel("证据入口", "File Diff 保持独立页面，原始文本差异也独立打开。", ui.action_strip([
            ui.button("old_extract.json", "old_extract.json", target="_blank"),
            ui.button("new_extract.json", "new_extract.json", target="_blank"),
            ui.button("semantic_diff.json", "semantic_diff.json", target="_blank"),
            ui.button("raw_text_diff.html", "raw_text_diff.html", "primary", target="_blank"),
            ui.button("pairwise_result.json", "pairwise_result.json", target="_blank"),
        ]))
        + ui.panel("字段变化 / 定位", "默认最多展示前 200 条，完整内容看 semantic_diff.json；定位列尽量显示 parser 抽取到的源文件行号和原始命令。", ui.filterable_table("semantic-change-table", ["类型", "路径", "定位", "旧值", "新值"], change_rows, "未发现结构化变化", "筛选路径 / 类型"))
        + ui.collapsible_panel("Parser 限制 / 专家复核提示", "轻量 parser 不替代 EDA tool signoff。", ui.table(["Severity", "Category", "Message"], issue_rows, "未发现 parser 错误；仍需结合原始 diff 人工确认。"), open=False)
    )
    html_text = ui.review_page_shell(
        "File Diff / 单文件深度对比报告",
        "FILE DIFF",
        f"{TYPE_LABELS.get(file_type, file_type)} · {TYPE_FOCUS.get(file_type, '用于定位两份文件之间的结构化变化与原始证据。')}",
        body,
        decision=status,
        rail=rail,
        nav="<a href='#'>Diff</a><a class='active' href='#'>File Diff</a><a href='raw_text_diff.html'>Raw Text Diff</a>",
        meta=ui.compact_meta([("file_type", file_type), ("changes", change_count), ("status", status)]),
    )
    _write_text(out / "index.html", html_text)


def _record(path: Path, file_type: str) -> dict[str, Any]:
    name = path.name
    suffix = path.suffix.lower()
    combined = suffix
    if name.lower().endswith(".gz"):
        combined = Path(name[:-3]).suffix.lower() + ".gz"
    return {"path": name, "abs_path": str(path.resolve()), "name": name, "extension": suffix, "combined_extension": combined, "compression": "gzip" if suffix == ".gz" else None, "file_type": file_type, "is_key_file": True}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unsupported_metadata_parse(file_type: str, path: Path) -> dict[str, Any]:
    stat = path.stat()
    data = {
        "evidence_mode": "metadata-only",
        "byte_size": stat.st_size,
        "sha256_bytes": _sha256_file(path),
        "path": str(path),
        "abs_path": str(path.resolve()),
        "name": path.name,
        "extension": path.suffix.lower(),
        "file_type": file_type,
    }
    return {
        "schema_version": "1.0",
        "result_type": "parser_result",
        "parser_name": "UnsupportedParser",
        "file": str(path),
        "file_type": file_type,
        "status": "UNSUPPORTED",
        "data": data,
        "issues": [
            {
                "severity": "warning",
                "category": "unsupported",
                "message": f"unsupported pairwise file type: {file_type}; using metadata/hash-only evidence",
            }
        ],
    }


def _parse_file(file_type: str, path: Path) -> dict[str, Any]:
    from lib_guard.scan.parser_engine import ParserRegistry

    registry = ParserRegistry.default(None)
    context = SimpleNamespace(root_path=str(path.parent), schema_version="1.0", scan_mode="file-diff")
    record = _record(path, file_type)
    for parser in registry.all():
        if parser.can_parse(record, context):
            return parser.parse(record, context)
    return _unsupported_metadata_parse(file_type, path)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def diff_pairwise_files(
    file_type: str,
    old_file: str | Path,
    new_file: str | Path,
    out_dir: str | Path,
    *,
    task_id: str | None = None,
    library_id: str | None = None,
    version_id: str | None = None,
    base_version: str | None = None,
) -> dict[str, Any]:
    old = Path(old_file)
    new = Path(new_file)
    out = Path(out_dir)
    old_result = _parse_file(file_type, old)
    new_result = _parse_file(file_type, new)
    old_hash = _stable_hash(old_result.get("data", {}))
    new_hash = _stable_hash(new_result.get("data", {}))
    status = "SAME" if old_hash == new_hash else "DIFF"
    issues: list[dict[str, Any]] = []
    for res, side in [(old_result, "old"), (new_result, "new")]:
        for issue in res.get("issues", []) or []:
            issues.append({"severity": issue.get("severity") or "warning", "category": issue.get("category") or "parser", "title": f"{side} parser issue", "message": issue.get("message") or str(issue)})
        if str(res.get("status")).upper() == "FAILED":
            status = "FAILED"
            issues.append({"severity": "error", "category": "parser", "title": "Parser failed", "message": f"{side} parser failed"})
    meta = {"schema_version": "1.0", "diff_type": "pairwise_file_diff", "file_type": file_type, "old_file": str(old), "new_file": str(new)}
    summary = {"schema_version": "1.0", "status": status, "file_type": file_type, "old_parser_status": old_result.get("status"), "new_parser_status": new_result.get("status"), "old_hash": old_hash, "new_hash": new_hash, "changed": old_hash != new_hash}
    old_extract = {"schema_version": "1.0", "file_type": file_type, "parser_status": old_result.get("status"), "data": old_result.get("data", {}), "issues": old_result.get("issues", [])}
    new_extract = {"schema_version": "1.0", "file_type": file_type, "parser_status": new_result.get("status"), "data": new_result.get("data", {}), "issues": new_result.get("issues", [])}
    semantic = _semantic_diff(old_extract.get("data", {}), new_extract.get("data", {}))
    change_count = int((semantic.get("summary") or {}).get("change_count") or 0)
    pairwise_result = {"schema_version": "pairwise_result.v1", "task_id": task_id or out.name, "library_id": library_id, "version_id": version_id, "base_version": base_version, "file_type": file_type, "old_file": str(old), "new_file": str(new), "status": "FAILED" if status == "FAILED" else "DONE", "result": status, "change_count": change_count, "review_result": "NEED_EXPERT_REVIEW" if status == "DIFF" else "NOT_REVIEWED", "reviewer_note": "", "html": str(out / "index.html"), "generated_at": _utc_now()}
    detail = {"schema_version": "1.0", "file_type": file_type, "old": old_result, "new": new_result}
    issue_payload = {"schema_version": "1.0", "issues": issues, "summary": {"error": sum(1 for i in issues if str(i.get('severity')).lower() == 'error'), "warning": sum(1 for i in issues if str(i.get('severity')).lower() != 'error')}}
    _write_json(out / "file_diff_meta.json", meta)
    _write_json(out / "file_diff_summary.json", summary)
    _write_json(out / "file_diff_issues.json", issue_payload)
    _write_json(out / "file_diff_detail.json", detail)
    _write_json(out / "old_extract.json", old_extract)
    _write_json(out / "new_extract.json", new_extract)
    _write_json(out / "semantic_diff.json", semantic)
    _write_json(out / "pairwise_result.json", pairwise_result)
    _render_raw_text_diff(old, new, out)
    _render_index(out, meta, summary, semantic, issues)
    return {"status": status, "out_dir": str(out), "summary": summary, "html": str(out / "index.html"), "pairwise_result": str(out / "pairwise_result.json")}
