from __future__ import annotations

from html import escape
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import difflib
import hashlib
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
}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _stable_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_text(path: Path) -> list[str]:
    try:
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
            old_norm = {json.dumps(item, sort_keys=True, ensure_ascii=False, default=str) for item in old_value}
            new_norm = {json.dumps(item, sort_keys=True, ensure_ascii=False, default=str) for item in new_value}
            changes.append(
                {
                    "path": path,
                    "change_type": "list_changed",
                    "old_count": len(old_value),
                    "new_count": len(new_value),
                    "added_count": len(new_norm - old_norm),
                    "removed_count": len(old_norm - new_norm),
                }
            )
            return
        if old_value != new_value:
            changes.append({"path": path or "$", "change_type": "changed", "old": old_value, "new": new_value})

    walk(old_data, new_data, "")
    by_type: dict[str, int] = {}
    for item in changes:
        change_type = str(item.get("change_type"))
        by_type[change_type] = by_type.get(change_type, 0) + 1
    return {
        "schema_version": "1.0",
        "status": "SAME" if not changes else "DIFF",
        "summary": {"change_count": len(changes), "by_type": dict(sorted(by_type.items()))},
        "changes": changes[:1000],
        "truncated": len(changes) > 1000,
    }


def _render_raw_text_diff(old: Path, new: Path, out: Path) -> None:
    diff_html = difflib.HtmlDiff(wrapcolumn=120).make_file(
        _read_text(old),
        _read_text(new),
        fromdesc=escape(str(old)),
        todesc=escape(str(new)),
        context=True,
        numlines=3,
        charset="utf-8",
    )
    _write_text(out / "raw_text_diff.html", diff_html)


def _clip(value: Any, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _status_class(status: Any) -> str:
    text = str(status or "").upper()
    if text in {"PASS", "SAME"}:
        return "ok"
    if text in {"FAILED", "BLOCK", "ERROR"}:
        return "bad"
    if text in {"METADATA_ONLY", "UNSUPPORTED"}:
        return "muted"
    return "warn"


def _domain_counts(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in changes:
        path = str(item.get("path") or "$")
        domain = path.split(".", 1)[0] or "$"
        counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8])


def _render_index(out: Path, meta: dict[str, Any], summary: dict[str, Any], semantic: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    file_type = str(summary.get("file_type") or meta.get("file_type") or "unknown")
    changes = list(semantic.get("changes", []) or [])
    domain_rows = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in _domain_counts(changes).items())
    rows = []
    for item in changes[:100]:
        rows.append(
            "<tr>"
            f"<td><span class=\"pill\">{escape(str(item.get('change_type', '-')))}</span></td>"
            f"<td><code>{escape(str(item.get('path', '-')))}</code></td>"
            f"<td><code>{escape(_clip(item.get('old')))}</code></td>"
            f"<td><code>{escape(_clip(item.get('new')))}</code></td>"
            "</tr>"
        )
    issue_items = "".join(
        f"<li>{escape(str(item.get('title') or item.get('message') or item))}</li>"
        for item in issues
    ) or "<li>未发现 parser 执行错误；仍需结合原始 diff 做人工复核。</li>"
    status = str(summary.get("status") or "UNKNOWN")
    parser_status = f"{summary.get('old_parser_status')} / {summary.get('new_parser_status')}"
    evidence_mode = "metadata-only" if file_type == "db" or "METADATA_ONLY" in parser_status else "structured + raw"
    metadata_note = ""
    if evidence_mode == "metadata-only":
        metadata_note = "<div class=\"notice\">该类型当前为 metadata-only 审阅：页面展示文件元信息、结构哈希与原始文本差异入口，不给出内容级语义结论。</div>"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>单文件深度对比报告</title>
  <style>
    :root {{
      color-scheme: light;
      --ink:#17202a; --muted:#667085; --line:#d9e1ec; --panel:#ffffff;
      --wash:#f6f8fb; --accent:#1f5e8c; --good:#157347; --warn:#946200; --bad:#b42318;
      --shadow:0 18px 54px rgba(31,50,74,.10);
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; color:var(--ink);
      background:linear-gradient(180deg,#edf3f8 0,#fafbfc 360px,#fff 100%);
    }}
    main {{ max-width:1240px; margin:0 auto; padding:34px 26px 64px; }}
    header {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:22px; align-items:end; padding:14px 0 22px; }}
    h1 {{ margin:0 0 9px; font-size:30px; font-weight:760; letter-spacing:0; }}
    h2 {{ margin:0 0 14px; font-size:18px; font-weight:720; }}
    .sub {{ color:var(--muted); font-size:13px; line-height:1.7; max-width:820px; }}
    .badge {{ display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:999px; padding:7px 10px; background:#fff; color:#344054; font-size:12px; }}
    .badge.ok {{ color:var(--good); border-color:#b7dfc8; background:#f2fbf5; }}
    .badge.warn {{ color:var(--warn); border-color:#ead39a; background:#fff8e8; }}
    .badge.bad {{ color:var(--bad); border-color:#f3b8b3; background:#fff1f0; }}
    .badge.muted {{ color:#475467; border-color:#cfd8e3; background:#f4f6f8; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:12px 0 18px; }}
    .tile,.panel {{ background:rgba(255,255,255,.95); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); }}
    .tile {{ padding:15px 16px; min-height:92px; }}
    .tile span {{ display:block; color:var(--muted); font-size:12px; }}
    .tile b {{ display:block; margin-top:8px; font-size:22px; font-weight:760; word-break:break-word; }}
    .panel {{ padding:20px; margin:16px 0; }}
    .split {{ display:grid; grid-template-columns:1.1fr .9fr; gap:16px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px 11px; text-align:left; vertical-align:top; }}
    th {{ color:#344054; background:var(--wash); font-weight:680; }}
    code {{ white-space:pre-wrap; word-break:break-word; font-family:Consolas,"SFMono-Regular",monospace; font-size:12px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .actions a {{ display:inline-flex; align-items:center; min-height:34px; padding:8px 11px; border-radius:6px; border:1px solid var(--line); color:var(--accent); text-decoration:none; background:white; font-size:13px; }}
    .pill {{ display:inline-flex; padding:4px 8px; border-radius:999px; background:#eef4ff; color:#194185; font-size:12px; }}
    .notice {{ margin:12px 0 18px; padding:12px 14px; border:1px solid #ead39a; border-radius:8px; background:#fff8e8; color:#6f4f00; font-size:13px; }}
    ul {{ margin:0; padding-left:18px; color:#344054; line-height:1.75; font-size:13px; }}
    @media (max-width:900px) {{ header,.split,.grid {{ grid-template-columns:1fr; }} main {{ padding:22px 14px 46px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>单文件深度对比报告</h1>
      <div class="sub">{escape(TYPE_LABELS.get(file_type, file_type))} · {escape(TYPE_FOCUS.get(file_type, "用于定位两份文件之间的结构化变化与原始证据。"))}</div>
    </div>
    <span class="badge {_status_class(status)}">{escape(status)}</span>
  </header>

  <section class="grid">
    <div class="tile"><span>文件类型</span><b>{escape(file_type)}</b></div>
    <div class="tile"><span>结构化变化</span><b>{escape(str((semantic.get("summary") or {}).get("change_count", 0)))}</b></div>
    <div class="tile"><span>Parser 状态</span><b>{escape(parser_status)}</b></div>
    <div class="tile"><span>证据模式</span><b>{escape(evidence_mode)}</b></div>
  </section>
  {metadata_note}

  <section class="split">
    <div class="panel">
      <h2>对比对象</h2>
      <table>
        <tr><th>旧文件</th><td>{escape(str(meta.get("old_file")))}</td></tr>
        <tr><th>新文件</th><td>{escape(str(meta.get("new_file")))}</td></tr>
        <tr><th>旧结构哈希</th><td><code>{escape(str(summary.get("old_hash")))}</code></td></tr>
        <tr><th>新结构哈希</th><td><code>{escape(str(summary.get("new_hash")))}</code></td></tr>
      </table>
    </div>
    <div class="panel">
      <h2>变化域分布</h2>
      <table><thead><tr><th>域</th><th>变化数</th></tr></thead><tbody>{domain_rows or '<tr><td colspan="2">未发现结构化变化。</td></tr>'}</tbody></table>
    </div>
  </section>

  <section class="panel">
    <h2>证据文件</h2>
    <div class="actions">
      <a href="old_extract.json">旧文件 extract</a>
      <a href="new_extract.json">新文件 extract</a>
      <a href="semantic_diff.json">结构化变化 JSON</a>
      <a href="raw_text_diff.html">原始文本差异</a>
      <a href="file_diff_detail.json">完整明细 JSON</a>
    </div>
  </section>

  <section class="panel">
    <h2>结构化变化</h2>
    <table>
      <thead><tr><th>类型</th><th>路径</th><th>旧值</th><th>新值</th></tr></thead>
      <tbody>{''.join(rows) or '<tr><td colspan="4">未发现结构化变化。</td></tr>'}</tbody>
    </table>
  </section>

  <section class="panel">
    <h2>专家复核提示</h2>
    <ul>
      <li>本页用于 pairwise 人工复核，不替代正式 release gate 或签核。</li>
      <li>结构化变化来自轻量 parser，复杂语法、include 展开、EDA 工具语义需由专家确认。</li>
      <li>DB/GDS/OAS 等二进制或大型版图文件默认只做 metadata/hash 级证据，内容级检查应接入专用工具。</li>
    </ul>
  </section>

  <section class="panel">
    <h2>Parser 限制说明</h2>
    <ul>{issue_items}</ul>
  </section>
</main>
</body>
</html>
"""
    _write_text(out / "index.html", html)


def _record(path: Path, file_type: str) -> dict[str, Any]:
    name = path.name
    suffix = path.suffix.lower()
    combined = suffix
    if name.lower().endswith(".gz"):
        combined = Path(name[:-3]).suffix.lower() + ".gz"
    return {
        "path": name,
        "abs_path": str(path.resolve()),
        "name": name,
        "extension": suffix,
        "combined_extension": combined,
        "compression": "gzip" if suffix == ".gz" else None,
        "file_type": file_type,
        "is_key_file": True,
    }


def _parse_file(file_type: str, path: Path) -> dict[str, Any]:
    from lib_guard.scan.parser_registry import ParserRegistry

    registry = ParserRegistry.default(None)
    context = SimpleNamespace(root_path=str(path.parent), schema_version="1.0", scan_mode="file-diff")
    record = _record(path, file_type)
    for parser in registry.all():
        if parser.can_parse(record, context):
            return parser.parse(record, context)
    return {
        "schema_version": "1.0",
        "result_type": "parser_result",
        "parser_name": "UnsupportedParser",
        "file": str(path),
        "file_type": file_type,
        "status": "UNSUPPORTED",
        "data": {},
        "issues": [{"severity": "warning", "message": f"unsupported pairwise file type: {file_type}"}],
    }


def diff_pairwise_files(file_type: str, old_file: str | Path, new_file: str | Path, out_dir: str | Path) -> dict[str, Any]:
    old = Path(old_file)
    new = Path(new_file)
    out = Path(out_dir)
    old_result = _parse_file(file_type, old)
    new_result = _parse_file(file_type, new)
    old_hash = _stable_hash(old_result.get("data", {}))
    new_hash = _stable_hash(new_result.get("data", {}))
    status = "SAME" if old_hash == new_hash else "DIFF"
    issues = []
    if str(old_result.get("status")).upper() == "FAILED" or str(new_result.get("status")).upper() == "FAILED":
        status = "FAILED"
        issues.append({"severity": "error", "category": "parser", "title": "Parser failed", "message": "old or new parser failed"})

    meta = {
        "schema_version": "1.0",
        "diff_type": "pairwise_file_diff",
        "file_type": file_type,
        "old_file": str(old),
        "new_file": str(new),
    }
    summary = {
        "schema_version": "1.0",
        "status": status,
        "file_type": file_type,
        "old_parser_status": old_result.get("status"),
        "new_parser_status": new_result.get("status"),
        "old_hash": old_hash,
        "new_hash": new_hash,
        "changed": old_hash != new_hash,
    }
    detail = {
        "schema_version": "1.0",
        "file_type": file_type,
        "old": old_result,
        "new": new_result,
    }
    old_extract = {
        "schema_version": "1.0",
        "file_type": file_type,
        "parser_status": old_result.get("status"),
        "data": old_result.get("data", {}),
        "issues": old_result.get("issues", []),
    }
    new_extract = {
        "schema_version": "1.0",
        "file_type": file_type,
        "parser_status": new_result.get("status"),
        "data": new_result.get("data", {}),
        "issues": new_result.get("issues", []),
    }
    semantic = _semantic_diff(old_extract.get("data", {}), new_extract.get("data", {}))
    issue_payload = {"schema_version": "1.0", "issues": issues, "summary": {"error": len(issues)}}
    _write_json(out / "file_diff_meta.json", meta)
    _write_json(out / "file_diff_summary.json", summary)
    _write_json(out / "file_diff_issues.json", issue_payload)
    _write_json(out / "file_diff_detail.json", detail)
    _write_json(out / "old_extract.json", old_extract)
    _write_json(out / "new_extract.json", new_extract)
    _write_json(out / "semantic_diff.json", semantic)
    _render_raw_text_diff(old, new, out)
    _render_index(out, meta, summary, semantic, issues)
    return {"status": status, "out_dir": str(out), "summary": summary, "html": str(out / "index.html")}
