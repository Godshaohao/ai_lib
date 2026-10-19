from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from datetime import datetime, timezone
import difflib
import hashlib
import gzip
import html
import json
import zipfile


TYPE_LABELS = {
    "generic": "通用文件（仅字节级）",
    "lef": "LEF 物理抽象",
    "liberty": "Liberty 时序库",
    "verilog": "Verilog RTL/Netlist",
    "cdl": "CDL/SPICE 网表",
    "sdc": "SDC 约束",
    "upf": "UPF 电源意图",
    "cpf": "CPF 电源意图",
    "spef": "SPEF 寄生参数",
    "db": "DB 二进制库",
    "gds": "GDS 版图",
    "oas": "OASIS 版图",
    "ndm": "NDM 二进制库",
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
    "db": "DB 为二进制文件，当前仅做元数据/哈希级证据，不做语义解析。",
    "gds": "GDS 为二进制版图，当前仅做元数据/哈希级证据，不做文本或语义解析。",
    "oas": "OASIS 为二进制版图，当前仅做元数据/哈希级证据，不做文本或语义解析。",
    "ndm": "NDM 为二进制库，当前仅做元数据/哈希级证据，不做文本或语义解析。",
    "waiver": "关注 waiver 条目增删、规则名和作用对象变化。",
    "ibis": "关注 component、pin、model 和 model_type 变化。",
    "pwl": "关注 PWL 点数、时间/值变化和异常 directive。",
    "snp": "关注 Touchstone option line、端口数和频点数据行变化。",
    "cpm": "关注 component、pin、方向和记录数量变化。",
}


# This map documents the review contract exposed by the pairwise report. Binary
# views must never fall through to a text viewer merely because a caller
# explicitly selected them for a file comparison.
TEXT_COMPARISON_PARAMETERS: dict[str, tuple[str, ...]] = {
    "lef": ("宏单元", "引脚", "引脚方向", "金属层", "尺寸"),
    "liberty": ("库定义", "单元", "引脚", "时序弧", "工艺角"),
    "verilog": ("模块", "端口", "端口方向", "位宽", "实例"),
    "cdl": ("子电路", "端口", "器件/实例", "连接关系"),
    "sdc": ("时钟", "生成时钟", "时序例外", "负载与延迟约束"),
    "upf": ("电源域", "供电网络", "隔离", "电平转换", "保持"),
    "cpf": ("电源域", "电源模式", "隔离", "电平转换", "保持"),
    "spef": ("头信息", "网络", "寄生参数条目"),
    "waiver": ("规则名", "作用对象", "豁免条目"),
    "ibis": ("组件", "引脚", "模型", "模型类型"),
    "pwl": ("采样点", "时间", "数值", "点数"),
    "snp": ("选项行", "端口数", "频点", "S 参数数据行"),
    "cpm": ("组件", "引脚", "方向", "记录数"),
}

BINARY_METADATA_ONLY_TYPES = {"db", "gds", "oas", "ndm"}


def comparison_capability(file_type: str) -> dict[str, Any]:
    """Return the explicit evidence contract for a manual file comparison."""
    normalized = str(file_type or "unknown").strip().lower()
    parameters = TEXT_COMPARISON_PARAMETERS.get(normalized)
    if parameters is not None:
        return {
            "file_type": normalized,
            "evidence_mode": "structured_text",
            "evidence_mode_label": "结构化 + 文本级证据",
            "text_diff_available": True,
            "parameters": list(parameters),
            "parameter_method": "解析器抽取字段 + 双栏逐行核对",
            "hash_provenance": "本次手工两两对比计算完整源文件 SHA-256；解析字段另行比较",
        }
    if normalized in BINARY_METADATA_ONLY_TYPES | {"generic"}:
        return {
            "file_type": normalized,
            "evidence_mode": "metadata_only",
            "evidence_mode_label": "元数据级证据",
            "text_diff_available": False,
            "parameters": ["文件大小", "完整内容 SHA-256", "解析器状态", "原始交付路径"],
            "parameter_method": "单文件完整内容指纹 + 交付元数据",
            "hash_provenance": "本次手工两两对比计算完整 SHA-256",
        }
    return {
        "file_type": normalized,
        "evidence_mode": "metadata_only",
        "evidence_mode_label": "元数据级证据",
        "text_diff_available": False,
        "parameters": ["文件大小", "解析器状态", "原始交付路径"],
        "parameter_method": "交付元数据",
        "hash_provenance": "未定义内容级比较策略",
    }

BOOKKEEPING_TOP_LEVEL_KEYS = {
    "source",
    "file",
    "path",
    "abs_path",
    "raw_path",
    "file_path",
}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _stable_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _content_data(data: Any) -> Any:
    """Return parser data used for engineering comparison.

    Parser outputs keep top-level bookkeeping fields such as the source file path.
    Those fields are useful as evidence, but they must not decide whether two IP
    files are materially different.
    """
    if not isinstance(data, dict):
        return data
    return {key: value for key, value in data.items() if str(key) not in BOOKKEEPING_TOP_LEVEL_KEYS}


def _ignored_bookkeeping_changes(old_data: Any, new_data: Any) -> dict[str, Any]:
    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        return {"count": 0, "keys": []}
    keys = sorted((set(old_data) | set(new_data)) & BOOKKEEPING_TOP_LEVEL_KEYS)
    changed = [key for key in keys if old_data.get(key) != new_data.get(key)]
    return {"count": len(changed), "keys": changed}


def _status_label(status: str) -> str:
    labels = {
        "SAME": "源文件字节相同",
        "DIFF": "源文件字节不同",
        "FAILED": "核对失败",
    }
    return labels.get(str(status).upper(), str(status or "未知"))


def _parsed_fields_label(status: str) -> str:
    return {
        "SAME": "已提取字段无差异",
        "DIFF": "已提取字段有差异",
        "NOT_CHECKED": "解析字段未核对",
        "NOT_APPLICABLE": "不适用结构化字段比较",
    }.get(str(status).upper(), "解析字段状态未知")


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


def _intraline_diff(old_line: str, new_line: str) -> tuple[str, str]:
    old_parts: list[str] = []
    new_parts: list[str] = []
    matcher = difflib.SequenceMatcher(None, old_line, new_line, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_text = html.escape(old_line[old_start:old_end])
        new_text = html.escape(new_line[new_start:new_end])
        if tag == "equal":
            old_parts.append(old_text)
            new_parts.append(new_text)
        else:
            if old_text:
                old_parts.append(f'<mark class="inline-change">{old_text}</mark>')
            if new_text:
                new_parts.append(f'<mark class="inline-change">{new_text}</mark>')
    return "".join(old_parts), "".join(new_parts)


def _aligned_text_diff(old_lines: list[str], new_lines: list[str], *, context_lines: int = 3) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    change_block = 0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=max(len(old_lines), len(new_lines)) > 5_000)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(old_end - old_start):
                old_line = old_lines[old_start + offset]
                rows.append({
                    "kind": "equal",
                    "block": None,
                    "old_no": old_start + offset + 1,
                    "new_no": new_start + offset + 1,
                    "old_html": html.escape(old_line),
                    "new_html": html.escape(old_line),
                })
            continue

        change_block += 1
        width = max(old_end - old_start, new_end - new_start)
        for offset in range(width):
            old_exists = old_start + offset < old_end
            new_exists = new_start + offset < new_end
            old_line = old_lines[old_start + offset] if old_exists else ""
            new_line = new_lines[new_start + offset] if new_exists else ""
            if old_exists and new_exists:
                kind = "changed"
                old_html, new_html = _intraline_diff(old_line, new_line)
            elif old_exists:
                kind = "removed"
                old_html, new_html = html.escape(old_line), ""
            else:
                kind = "added"
                old_html, new_html = "", html.escape(new_line)
            rows.append({
                "kind": kind,
                "block": change_block,
                "old_no": old_start + offset + 1 if old_exists else None,
                "new_no": new_start + offset + 1 if new_exists else None,
                "old_html": old_html,
                "new_html": new_html,
            })

    visible: set[int] = set()
    changed_indices = [index for index, row in enumerate(rows) if row["kind"] != "equal"]
    for index in changed_indices:
        visible.update(range(max(0, index - context_lines), min(len(rows), index + context_lines + 1)))
    for index, row in enumerate(rows):
        row["context_visible"] = not changed_indices or index in visible
    return rows, change_block


def _render_raw_text_diff(old: Path, new: Path, out: Path) -> None:
    rows, change_blocks = _aligned_text_diff(_read_text(old), _read_text(new))
    bounded_large_file = len(rows) > 20_000
    counts = {
        kind: sum(1 for row in rows if row["kind"] == kind)
        for kind in ("changed", "added", "removed")
    }
    rendered_rows: list[str] = []
    gap_id = 0
    index = 0
    marker_by_kind = {"equal": "", "changed": "~", "added": "+", "removed": "−"}
    label_by_kind = {"equal": "未变化", "changed": "内容修改", "added": "新增行", "removed": "删除行"}
    if bounded_large_file and not change_blocks:
        rendered_rows.append(
            f'<tr><td colspan="5" class="empty-diff">两个大文件文本相同，共 {len(rows)} 行；页面未复制未变化正文。</td></tr>'
        )
        index = len(rows)
    while index < len(rows):
        if not rows[index]["context_visible"]:
            gap_start = index
            while index < len(rows) and not rows[index]["context_visible"]:
                index += 1
            gap_id += 1
            gap_count = index - gap_start
            if bounded_large_file:
                rendered_rows.append(
                    f'<tr class="diff-gap-row" data-gap-summary="{gap_id}"><td colspan="5">'
                    f'<span>省略 {gap_count} 行未变化内容</span></td></tr>'
                )
                continue
            rendered_rows.append(
                f'<tr class="diff-gap-row" data-gap-summary="{gap_id}"><td colspan="5">'
                f'<button type="button" data-expand-gap="{gap_id}">展开 {gap_count} 行未变化内容</button></td></tr>'
            )
            for hidden_row in rows[gap_start:index]:
                hidden_row["gap_id"] = gap_id
                kind = hidden_row["kind"]
                rendered_rows.append(
                    f'<tr class="diff-row kind-{kind} is-context-hidden" data-diff-row data-gap-id="{gap_id}">'
                    f'<td class="line-no">{hidden_row["old_no"] or ""}</td>'
                    f'<td class="code-cell"><code>{hidden_row["old_html"]}</code></td>'
                    f'<td class="change-marker" aria-label="{label_by_kind[kind]}">{marker_by_kind[kind]}</td>'
                    f'<td class="line-no">{hidden_row["new_no"] or ""}</td>'
                    f'<td class="code-cell"><code>{hidden_row["new_html"]}</code></td></tr>'
                )
            continue

        row = rows[index]
        kind = row["kind"]
        block_attr = f' data-change-block="{row["block"]}"' if row["block"] is not None else ""
        rendered_rows.append(
            f'<tr class="diff-row kind-{kind}" data-diff-row{block_attr}>'
            f'<td class="line-no">{row["old_no"] or ""}</td>'
            f'<td class="code-cell"><code>{row["old_html"]}</code></td>'
            f'<td class="change-marker" aria-label="{label_by_kind[kind]}">{marker_by_kind[kind]}</td>'
            f'<td class="line-no">{row["new_no"] or ""}</td>'
            f'<td class="code-cell"><code>{row["new_html"]}</code></td></tr>'
        )
        index += 1

    old_label = html.escape(str(old))
    new_label = html.escape(str(new))
    old_name = html.escape(old.name)
    new_name = html.escape(new.name)
    body_rows = "".join(rendered_rows) or '<tr><td colspan="5" class="empty-diff">两个文件均为空。</td></tr>'
    if bounded_large_file:
        initial_mode = "compact"
        mode_options = '<option value="compact">仅看变化</option>'
        mode_disabled = " disabled"
        size_note = f'<span class="large-file-note">大文件仅呈现差异上下文（对齐后 {len(rows)} 行）</span>'
    elif not change_blocks:
        initial_mode = "full"
        mode_options = '<option value="full">完整文件</option>'
        mode_disabled = " disabled"
        size_note = '<span>文本相同，显示完整文件</span>'
    else:
        initial_mode = "compact"
        mode_options = '<option value="compact">仅看变化</option><option value="full">完整文件</option>'
        mode_disabled = ""
        size_note = '<span>可切换完整文件</span>'
    diff_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>双栏文本对比 · {old_name} ↔ {new_name}</title>
  <style>
    :root {{ --ink:#163236; --muted:#63787b; --line:#cfdbdc; --surface:#fff; --canvas:#eef3f3; --teal:#167a86; --teal-soft:#e8f4f4; --add:#e6f6eb; --add-strong:#bfe8cc; --remove:#fcebea; --remove-strong:#f3c7c3; --change:#fff4d7; --change-strong:#f1dda4; --focus:#0e6570; }}
    * {{ box-sizing:border-box; }}
    html, body {{ margin:0; min-height:100%; background:var(--canvas); color:var(--ink); font-family:Inter, "Noto Sans SC", "Microsoft YaHei", sans-serif; }}
    button, select {{ font:inherit; }}
    .sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
    button:focus-visible, select:focus-visible {{ outline:3px solid rgba(22,122,134,.28); outline-offset:2px; }}
    .text-diff-workbench {{ min-width:980px; }}
    .diff-toolbar {{ position:sticky; top:0; z-index:30; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:center; min-height:68px; padding:10px 16px; background:#f9fbfb; border-bottom:1px solid var(--line); box-shadow:0 2px 10px rgba(28,58,62,.08); }}
    .diff-title {{ min-width:0; }}
    .diff-title h1 {{ margin:0; font-size:16px; letter-spacing:0; }}
    .diff-title p {{ margin:4px 0 0; color:var(--muted); font-size:11px; }}
    .diff-controls {{ display:flex; align-items:center; gap:7px; }}
    .diff-controls button, .diff-controls select {{ min-height:34px; padding:6px 10px; border:1px solid var(--line); border-radius:3px; background:#fff; color:var(--ink); font-weight:750; cursor:pointer; }}
    .diff-controls button:hover {{ border-color:var(--teal); color:var(--teal); }}
    .diff-counter {{ min-width:74px; color:var(--muted); font:12px/1.2 Consolas, "Liberation Mono", monospace; text-align:center; }}
    .diff-summary {{ display:flex; gap:18px; padding:8px 16px; background:var(--surface); border-bottom:1px solid var(--line); color:var(--muted); font-size:11px; }}
    .diff-summary b {{ margin-left:4px; color:var(--ink); font-variant-numeric:tabular-nums; }}
    .diff-scroll {{ height:calc(100vh - 104px); overflow:auto; background:var(--surface); }}
    .diff-grid {{ width:100%; min-width:1180px; border-collapse:separate; border-spacing:0; table-layout:fixed; font:12px/1.48 Consolas, "Liberation Mono", monospace; }}
    .diff-grid col.line {{ width:54px; }} .diff-grid col.marker {{ width:30px; }}
    .diff-grid thead th {{ position:sticky; top:0; z-index:20; padding:8px 10px; background:#21383b; color:#f3f8f8; border-bottom:1px solid #13282b; text-align:left; }}
    .diff-grid thead th:first-child, .diff-grid thead th:nth-child(4) {{ text-align:right; color:#abc0c2; }}
    .pane-heading {{ display:grid; gap:2px; }} .pane-heading strong {{ font-family:Inter, "Noto Sans SC", sans-serif; font-size:12px; }} .pane-heading span {{ overflow:hidden; color:#b8cbcd; font-size:10px; text-overflow:ellipsis; white-space:nowrap; }}
    .diff-row td {{ min-height:24px; border-bottom:1px solid #edf1f1; }}
    .line-no {{ padding:3px 8px; background:#f4f7f7; color:#829194; border-right:1px solid #dde5e5; text-align:right; user-select:none; font-variant-numeric:tabular-nums; }}
    .code-cell {{ padding:3px 10px; overflow:hidden; vertical-align:top; }} .code-cell code {{ display:block; min-height:18px; white-space:pre; }}
    .change-marker {{ padding:3px 0; background:#f4f7f7; color:var(--muted); border-left:1px solid #d7e0e0; border-right:1px solid #d7e0e0; text-align:center; font-weight:900; user-select:none; }}
    .kind-added td:nth-child(4), .kind-added td:nth-child(5) {{ background:var(--add); }} .kind-added .change-marker {{ background:var(--add-strong); color:#176b34; }}
    .kind-removed td:nth-child(1), .kind-removed td:nth-child(2) {{ background:var(--remove); }} .kind-removed .change-marker {{ background:var(--remove-strong); color:#a63831; }}
    .kind-changed td:nth-child(1), .kind-changed td:nth-child(2), .kind-changed td:nth-child(4), .kind-changed td:nth-child(5) {{ background:var(--change); }} .kind-changed .change-marker {{ background:var(--change-strong); color:#775a0b; }}
    mark.inline-change {{ padding:0; background:#f2c66d; color:inherit; border-bottom:2px solid #bc8318; }}
    .diff-row.is-current td {{ box-shadow:inset 0 2px var(--focus), inset 0 -2px var(--focus); }} .diff-row.is-current td:first-child {{ box-shadow:inset 3px 0 var(--focus), inset 0 2px var(--focus), inset 0 -2px var(--focus); }} .diff-row.is-current td:last-child {{ box-shadow:inset -3px 0 var(--focus), inset 0 2px var(--focus), inset 0 -2px var(--focus); }}
    .diff-gap-row td {{ padding:0; background:#f5f8f8; border-bottom:1px solid var(--line); text-align:center; }} .diff-gap-row button, .diff-gap-row span {{ display:block; width:100%; padding:6px; border:0; background:transparent; color:var(--teal); font-size:11px; }} .diff-gap-row button {{ cursor:pointer; }} .diff-gap-row button:hover {{ background:var(--teal-soft); }}
    .large-file-note {{ color:#8a5a0b; font-weight:750; }}
    body[data-mode="compact"] .is-context-hidden:not(.is-gap-revealed) {{ display:none; }} body[data-mode="full"] .diff-gap-row {{ display:none; }}
    .empty-diff {{ padding:28px; color:var(--muted); text-align:center; }}
    @media (prefers-reduced-motion:no-preference) {{ .diff-row.is-current td {{ transition:box-shadow .16s ease; }} }}
  </style>
</head>
<body data-mode="{initial_mode}">
  <main class="text-diff-workbench">
    <header class="diff-toolbar">
      <div class="diff-title"><h1>双栏文本对比</h1><p>共享滚动与行对齐；只读，不会修改源文件。</p></div>
      <div class="diff-controls" aria-label="差异导航">
        <label for="diff-mode" class="sr-only">显示范围</label>
        <select id="diff-mode"{mode_disabled}>{mode_options}</select>
        <button id="diff-prev" type="button" title="快捷键 [">上一处</button>
        <span id="diff-counter" class="diff-counter">0 / {change_blocks}</span>
        <button id="diff-next" type="button" title="快捷键 ]">下一处</button>
      </div>
    </header>
    <div class="diff-summary" aria-label="变化摘要"><span>修改<b>{counts["changed"]}</b></span><span>新增<b>{counts["added"]}</b></span><span>删除<b>{counts["removed"]}</b></span><span>变化块<b>{change_blocks}</b></span>{size_note}<span>快捷键<b>[ ] / n / f</b></span></div>
    <section class="diff-scroll" aria-label="文件文本差异">
      <table class="diff-grid">
        <colgroup><col class="line"><col><col class="marker"><col class="line"><col></colgroup>
        <thead><tr><th>行</th><th><span class="pane-heading"><strong>旧文件 · {old_name}</strong><span title="{old_label}">{old_label}</span></span></th><th>变化</th><th>行</th><th><span class="pane-heading"><strong>新文件 · {new_name}</strong><span title="{new_label}">{new_label}</span></span></th></tr></thead>
        <tbody>{body_rows}</tbody>
      </table>
    </section>
  </main>
  <script>
    (() => {{
      const blocks = [...new Set([...document.querySelectorAll('[data-change-block]')].map((row) => row.dataset.changeBlock))];
      const counter = document.getElementById('diff-counter');
      const mode = document.getElementById('diff-mode');
      let current = blocks.length ? 0 : -1;
      function selectBlock(index, scroll = true) {{
        document.querySelectorAll('.is-current').forEach((row) => row.classList.remove('is-current'));
        if (!blocks.length) {{ counter.textContent = '0 / 0'; return; }}
        current = (index + blocks.length) % blocks.length;
        const rows = [...document.querySelectorAll(`[data-change-block="${{blocks[current]}}"]`)];
        rows.forEach((row) => row.classList.add('is-current'));
        counter.textContent = `${{current + 1}} / ${{blocks.length}}`;
        if (scroll && rows[0]) rows[0].scrollIntoView({{ block:'center', behavior:'smooth' }});
      }}
      document.getElementById('diff-prev').addEventListener('click', () => selectBlock(current - 1));
      document.getElementById('diff-next').addEventListener('click', () => selectBlock(current + 1));
      mode.addEventListener('change', () => {{ document.body.dataset.mode = mode.value; selectBlock(current, false); }});
      document.querySelectorAll('[data-expand-gap]').forEach((button) => button.addEventListener('click', () => {{
        const gap = button.dataset.expandGap;
        document.querySelectorAll(`[data-gap-id="${{gap}}"]`).forEach((row) => row.classList.add('is-gap-revealed'));
        button.closest('tr').hidden = true;
      }}));
      document.addEventListener('keydown', (event) => {{
        if (/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) return;
        if (event.key === ']') selectBlock(current + 1);
        if (event.key === '[') selectBlock(current - 1);
        if (event.key.toLowerCase() === 'n' && !mode.disabled) {{ mode.value = 'compact'; mode.dispatchEvent(new Event('change')); }}
        if (event.key.toLowerCase() === 'f' && !mode.disabled) {{ mode.value = 'full'; mode.dispatchEvent(new Event('change')); }}
      }});
      selectBlock(0, false);
    }})();
  </script>
</body>
</html>"""
    _write_text(out / "raw_text_diff.html", diff_html)


def _render_export_zip(out: Path) -> Path:
    export_path = out / "file_diff_export.zip"
    members = [
        "index.html",
        "pairwise_summary.md",
        "raw_text_diff.html",
        "file_diff_meta.json",
        "file_diff_summary.json",
        "file_diff_issues.json",
        "file_diff_detail.json",
        "old_extract.json",
        "new_extract.json",
        "semantic_diff.json",
        "pairwise_result.json",
    ]
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in members:
            path = out / name
            if path.is_file():
                archive.write(path, arcname=name)
    return export_path


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


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None and value != "" else "-")
    return text.replace("|", "\\|").replace("\n", " ")


def _render_markdown_summary(
    out: Path,
    meta: dict[str, Any],
    summary: dict[str, Any],
    semantic: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    file_type = str(summary.get("file_type") or meta.get("file_type") or "unknown")
    capability = comparison_capability(file_type)
    status = str(summary.get("status") or "UNKNOWN")
    status_text = _status_label(status)
    changes = list(semantic.get("changes", []) or [])
    change_count = int((semantic.get("summary") or {}).get("change_count") or 0)
    ignored = semantic.get("ignored_changes") if isinstance(semantic.get("ignored_changes"), dict) else {}
    ignored_count = int(ignored.get("count") or 0)
    ignored_keys = ", ".join(str(item) for item in ignored.get("keys", []) or [])
    by_type = dict((semantic.get("summary") or {}).get("by_type") or {})
    domain_counts = _domain_counts(changes)
    lines = [
        "# 单文件深度对比摘要",
        "",
        "## 结论",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 结果 | {_markdown_cell(status_text)} |",
        f"| 源文件内容 | {_markdown_cell(_status_label(summary.get('source_content_status')) if summary.get('source_content_status') != 'UNVERIFIED' else '源文件内容未验证')} |",
        f"| 已提取字段 | {_markdown_cell(_parsed_fields_label(summary.get('parsed_fields_status')))} |",
        f"| 文件类型 | {_markdown_cell(TYPE_LABELS.get(file_type, file_type))} |",
        f"| 结构化变化 | {_markdown_cell(change_count)} |",
        f"| 已忽略证据字段 | {_markdown_cell(f'{ignored_count} 项' + (f'：{ignored_keys}' if ignored_keys else ''))} |",
        f"| 旧文件 | `{_markdown_cell(meta.get('old_file'))}` |",
        f"| 新文件 | `{_markdown_cell(meta.get('new_file'))}` |",
        f"| 关注点 | {_markdown_cell(TYPE_FOCUS.get(file_type, '人工复核文件变化。'))} |",
        "",
        "## 本类型比较参数",
        "",
        "| 参数 | 比较方式 |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {_markdown_cell(parameter)} | {_markdown_cell(capability['parameter_method'])} |"
        for parameter in capability["parameters"]
    )
    lines.extend([
        "",
        f"证据等级：{capability['evidence_mode_label']}。{capability['hash_provenance']}。",
        "",
        "## 变化类型",
        "",
    ])
    if summary.get("unexplained_change"):
        lines.extend(["源文件字节不同，但已提取字段无差异；可能涉及注释、格式、压缩封装或当前 Parser 未覆盖的内容，需查看原始差异。", ""])
    if by_type:
        lines.extend(["| 类型 | 数量 |", "| --- | ---: |"])
        lines.extend(f"| {_markdown_cell(key)} | {int(value)} |" for key, value in sorted(by_type.items()))
    else:
        lines.append("未发现结构化变化。")
    if ignored_count:
        lines.extend(["", f"已忽略 {ignored_count} 项路径/来源类证据字段；这些字段只说明文件来自哪里，不代表 IP 内容变化。"])
    lines.extend(["", "## 变化域分布", ""])
    if domain_counts:
        lines.extend(["| 域 | 变化数 |", "| --- | ---: |"])
        lines.extend(f"| `{_markdown_cell(key)}` | {int(value)} |" for key, value in domain_counts.items())
    else:
        lines.append("未发现结构化变化。")
    lines.extend(["", "## 重点变化样例", ""])
    if changes:
        lines.extend(["| 类型 | 路径 | 定位 |", "| --- | --- | --- |"])
        for item in changes[:20]:
            lines.append(
                f"| {_markdown_cell(item.get('change_type'))} | `{_markdown_cell(item.get('path', '-'))}` | `{_markdown_cell(_change_location(item))}` |"
            )
        if len(changes) > 20:
            lines.append("")
            lines.append(f"仅展示前 20 条；完整结构化变化见 `semantic_diff.json`。")
    else:
        lines.append("未发现结构化变化。")
    lines.extend(["", "## 证据入口", ""])
    lines.append("- HTML 结构化报告：`index.html`")
    if capability["text_diff_available"]:
        lines.append("- 双栏文本对比：`raw_text_diff.html`")
    else:
        lines.append("- 文本逐行对比：不提供文本逐行对比（二进制或未定义文本语义的交付格式）")
    lines.extend([
        "- 结构化变化：`semantic_diff.json`",
        "- 旧文件提取：`old_extract.json`",
        "- 新文件提取：`new_extract.json`",
    ])
    lines.extend(["", "## 解析器限制", ""])
    if issues:
        for issue in issues[:20]:
            title = issue.get("title") or issue.get("message") or issue
            lines.append(f"- [{_markdown_cell(issue.get('severity') or 'warning')}] {_markdown_cell(title)}")
        if len(issues) > 20:
            lines.append(f"- 还有 {len(issues) - 20} 条解析器提示，请查看 `file_diff_issues.json`。")
    else:
        lines.append("未发现解析器错误；仍需结合双栏文本对比和使用场景确认。")
    lines.append("")
    _write_text(out / "pairwise_summary.md", "\n".join(lines))


def _render_index(out: Path, meta: dict[str, Any], summary: dict[str, Any], semantic: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    from lib_guard.render import product_theme as ui

    file_type = str(summary.get("file_type") or meta.get("file_type") or "unknown")
    capability = comparison_capability(file_type)
    status = str(summary.get("status") or "UNKNOWN")
    status_text = _status_label(status)
    changes = list(semantic.get("changes", []) or [])
    change_count = int((semantic.get("summary") or {}).get("change_count") or 0)
    ignored = semantic.get("ignored_changes") if isinstance(semantic.get("ignored_changes"), dict) else {}
    ignored_count = int(ignored.get("count") or 0)
    ignored_keys = ", ".join(str(item) for item in ignored.get("keys", []) or [])
    parser_status = f"{summary.get('old_parser_status')} / {summary.get('new_parser_status')}"
    evidence_mode = str(capability["evidence_mode"])
    evidence_mode_label = str(capability["evidence_mode_label"])
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
        ("对比入口", "PASS", "本页由运行台文件对比进入"),
        ("文件深度对比", status, f"结构化变化 {change_count}"),
        (
            "双栏文本对比" if capability["text_diff_available"] else "文本逐行对比",
            "READY" if capability["text_diff_available"] else "INFO",
            "可逐行核对旧文件和新文件" if capability["text_diff_available"] else "二进制交付不提供文本逐行对比",
        ),
        ("减噪", "PASS", f"忽略证据字段 {ignored_count}"),
    ])
    body = (
        ui.panel(
            "对比对象",
            "先确认这是一组正确的 old_file → new_file，再看结构化变化和双栏文本对比。",
            ui.compact_meta([
                ("旧侧文件", meta.get("old_file")),
                ("新侧文件", meta.get("new_file")),
                ("内容判定", status_text),
                ("源文件内容", _status_label(summary.get("source_content_status")) if summary.get("source_content_status") != "UNVERIFIED" else "源文件内容未验证"),
                ("已提取字段", _parsed_fields_label(summary.get("parsed_fields_status"))),
                ("已忽略证据字段", f"{ignored_count} 项" + (f"：{ignored_keys}" if ignored_keys else "")),
                ("导出文件", "file_diff_export.zip"),
            ]),
        )
        +
        ui.panel(
            "本类型比较参数",
            "参数由文件类型固定定义；报告只承诺这些参数及对应证据方式，不把路径变化当作内容变化。",
            ui.table(
                ["比较参数", "比较方式"],
                [
                    f"<tr><td>{ui.esc(parameter)}</td><td>{ui.esc(capability['parameter_method'])}</td></tr>"
                    for parameter in capability["parameters"]
                ],
                "未定义比较参数",
            )
            + ui.compact_meta([
                ("证据等级", evidence_mode_label),
                ("内容指纹来源", capability["hash_provenance"]),
            ]),
        )
        +
        ui.panel(
            "单文件深度对比结论",
            "源文件字节不同，但已提取字段无差异；请查看原始文本，当前解析器可能未覆盖变化内容。"
            if summary.get("unexplained_change") else "原始字节与已提取字段分别判定；本页只对应所选的一对文件。",
            ui.metric_grid([
                ("文件类型", file_type, TYPE_LABELS.get(file_type, file_type), "PASS"),
                ("内容结论", status_text, "基于源文件完整 SHA-256", status),
                ("解析字段", _parsed_fields_label(summary.get("parsed_fields_status")), "仅限当前解析器提取范围", "INFO"),
                ("结构化变化", change_count, "semantic_diff.json", status),
                ("解析器", parser_status, "old / new", "WARNING" if "FAILED" in parser_status else "PASS"),
                ("证据模式", evidence_mode_label, "结构化 + 原始文本 / 元数据级证据", "METADATA_ONLY" if evidence_mode == "metadata-only" else "PASS"),
                ("路径/来源噪声", ignored_count, "不参与内容判定", "PASS"),
            ])
            + ui.compact_meta([("旧文件", meta.get("old_file")), ("新文件", meta.get("new_file")), ("关注点", TYPE_FOCUS.get(file_type, "人工复核文件变化。"))]),
        )
        + ui.panel(
            "减噪说明",
            "路径、来源文件名、临时工作目录等字段只说明证据从哪里来，不作为 IP 内容变化。",
            ui.compact_meta([
                ("已忽略字段数", ignored_count),
                ("字段", ignored_keys or "-"),
                ("判定口径", "源文件 SHA-256 判定原始字节；已提取字段单独比较"),
            ]),
        )
        + ui.panel("变化域分布", "用于快速定位变化集中在哪些结构域。", ui.table(["域", "变化数"], domain_rows, "未发现结构化变化"))
        + ui.panel("证据入口", "结构化结论与原始证据相互核对；原始 JSON 只用于追溯。", ui.action_strip([
            ui.button("打开双栏文本对比", "raw_text_diff.html", "primary", target="_blank") if capability["text_diff_available"] else ui.button("不提供文本逐行对比", "", disabled=True),
            ui.button("导出对比结果", "file_diff_export.zip", "primary", target="_blank"),
            ui.button("Markdown 摘要", "pairwise_summary.md", "primary", target="_blank"),
            ui.button("old_extract.json", "old_extract.json", target="_blank"),
            ui.button("new_extract.json", "new_extract.json", target="_blank"),
            ui.button("semantic_diff.json", "semantic_diff.json", target="_blank"),
            ui.button("pairwise_result.json", "pairwise_result.json", target="_blank"),
        ]))
        + ui.panel("字段变化 / 定位", "默认最多展示前 200 条，完整内容看 semantic_diff.json；定位列尽量显示 parser 抽取到的源文件行号和原始命令。", ui.filterable_table("semantic-change-table", ["类型", "路径", "定位", "旧值", "新值"], change_rows, "未发现结构化变化", "筛选路径 / 类型"))
        + ui.collapsible_panel("解析器限制 / 专家复核提示", "轻量解析器不替代 EDA tool signoff。", ui.table(["级别", "类别", "信息"], issue_rows, "未发现解析器错误；仍需结合原始差异人工确认。"), open=False)
    )
    html_text = ui.review_page_shell(
        "单文件深度对比报告",
        "文件深度对比",
        f"{TYPE_LABELS.get(file_type, file_type)} · {TYPE_FOCUS.get(file_type, '用于定位两份文件之间的结构化变化与原始证据。')}",
        body,
        decision=status,
        rail=rail,
        nav=(
            "<a href='#'>对比</a><a class='active' href='#'>文件深度对比</a>"
            + ("<a href='raw_text_diff.html'>双栏文本对比</a>" if capability["text_diff_available"] else "")
        ),
        meta=ui.compact_meta([("文件类型", file_type), ("结构化变化", change_count), ("忽略字段", ignored_count), ("结论", status_text)]),
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


def _source_stamp(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


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
                "message": f"{file_type} 不做语义解析；当前仅使用元数据/哈希级证据",
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
    from lib_guard.atomic import file_lock

    out = Path(out_dir)
    with file_lock(out.parent / f'.{out.name}.file_diff.lock'):
        return _diff_pairwise_files(file_type, old_file, new_file, out_dir, task_id=task_id,
                                    library_id=library_id, version_id=version_id, base_version=base_version)


def _diff_pairwise_files(
    file_type: str, old_file: str | Path, new_file: str | Path, out_dir: str | Path,
    *, task_id: str | None = None, library_id: str | None = None,
    version_id: str | None = None, base_version: str | None = None,
) -> dict[str, Any]:
    old = Path(old_file).expanduser().resolve()
    new = Path(new_file).expanduser().resolve()
    out = Path(out_dir)
    # A failed overwrite must not leave the previous DONE generation attachable.
    _write_json(out / 'pairwise_result.json', {'status': 'RUNNING', 'generated_at': _utc_now()})
    capability = comparison_capability(file_type)
    source_stamps: dict[str, dict[str, int]] = {}
    content_sha256: dict[str, str] = {}
    old_result: dict[str, Any] = {"status": "NOT_CHECKED", "data": {}, "issues": []}
    new_result: dict[str, Any] = {"status": "NOT_CHECKED", "data": {}, "issues": []}
    source_error = ""
    source_changed = False
    try:
        for side, path in (("old", old), ("new", new)):
            source_stamps[side] = _source_stamp(path)
        old_result = _parse_file(file_type, old)
        new_result = _parse_file(file_type, new)
        for side, path, parsed in (("old", old, old_result), ("new", new, new_result)):
            cached_hash = (parsed.get("data") or {}).get("sha256_bytes") if capability["evidence_mode"] == "metadata_only" else None
            content_sha256[side] = cached_hash or _sha256_file(path)
        if capability["text_diff_available"]:
            _render_raw_text_diff(old, new, out)
        source_changed = any(_source_stamp(path) != source_stamps[side] for side, path in (("old", old), ("new", new)))
    except OSError as exc:
        source_error = f"{type(exc).__name__}: {exc}"

    old_data = old_result.get("data", {})
    new_data = new_result.get("data", {})
    old_content_data = _content_data(old_data)
    new_content_data = _content_data(new_data)
    old_hash = _stable_hash(old_content_data)
    new_hash = _stable_hash(new_content_data)
    source_content_status = (
        "UNVERIFIED" if source_error or source_changed or len(content_sha256) != 2
        else "SAME" if content_sha256["old"] == content_sha256["new"] else "DIFF"
    )
    parser_statuses = {str(res.get("status") or "").upper() for res in (old_result, new_result)}
    parsed_fields_status = (
        "NOT_CHECKED" if source_content_status == "UNVERIFIED" or "FAILED" in parser_statuses else
        "NOT_APPLICABLE" if capability["evidence_mode"] == "metadata_only" else
        "NOT_CHECKED" if not parser_statuses.issubset({"PASS", "PASS_WITH_WARNING"}) else
        "SAME" if old_hash == new_hash else "DIFF"
    )
    status = "FAILED" if source_content_status == "UNVERIFIED" or "FAILED" in parser_statuses else source_content_status
    issues: list[dict[str, Any]] = []
    if source_error or source_changed:
        issues.append({"severity": "error", "category": "source",
                       "title": "源文件检查期间不可验证",
                       "message": source_error or "源文件大小或修改时间在检查期间变化；请对稳定的文件重新执行。"})
    for res, side in [(old_result, "old"), (new_result, "new")]:
        for issue in res.get("issues", []) or []:
            issues.append({"severity": issue.get("severity") or "warning", "category": issue.get("category") or "parser", "title": f"{side} parser issue", "message": issue.get("message") or str(issue)})
        if str(res.get("status")).upper() == "FAILED":
            issues.append({"severity": "error", "category": "parser", "title": "解析器失败", "message": f"{side} 侧解析器失败"})
    meta = {"schema_version": "1.0", "diff_type": "pairwise_file_diff", "file_type": file_type, "old_file": str(old), "new_file": str(new), "comparison_capability": capability}
    summary = {"schema_version": "1.0", "status": status, "file_type": file_type,
               "source_content_status": source_content_status, "content_sha256": content_sha256,
               "parsed_fields_status": parsed_fields_status,
               "unexplained_change": source_content_status == "DIFF" and parsed_fields_status == "SAME",
               "source_stability": "SOURCE_CHANGED_DURING_CHECK" if source_changed else "UNVERIFIED" if source_error else "STABLE",
               "old_parser_status": old_result.get("status"), "new_parser_status": new_result.get("status"),
               "old_hash": old_hash, "new_hash": new_hash, "changed": status == "DIFF", "comparison_capability": capability}
    old_extract = {"schema_version": "1.0", "file_type": file_type, "parser_status": old_result.get("status"), "data": old_data, "issues": old_result.get("issues", [])}
    new_extract = {"schema_version": "1.0", "file_type": file_type, "parser_status": new_result.get("status"), "data": new_data, "issues": new_result.get("issues", [])}
    if parsed_fields_status in {"NOT_CHECKED", "NOT_APPLICABLE"}:
        semantic = {"schema_version": "1.0", "status": parsed_fields_status,
                    "summary": {"change_count": 0, "by_type": {}}, "changes": [], "truncated": False}
    else:
        semantic = _semantic_diff(old_content_data, new_content_data)
    semantic["ignored_changes"] = _ignored_bookkeeping_changes(old_data, new_data)
    change_count = int((semantic.get("summary") or {}).get("change_count") or 0)
    pairwise_result = {"schema_version": "pairwise_result.v1", "task_id": task_id or out.name, "library_id": library_id, "version_id": version_id, "base_version": base_version, "file_type": file_type, "old_file": str(old), "new_file": str(new), "status": "FAILED" if status == "FAILED" else "DONE", "result": status, "source_content_status": source_content_status, "content_sha256": content_sha256, "parsed_fields_status": parsed_fields_status, "unexplained_change": summary["unexplained_change"], "change_count": change_count, "review_result": "NEED_EXPERT_REVIEW" if status == "DIFF" else "NOT_REVIEWED", "reviewer_note": "", "comparison_capability": capability, "html": str(out / "index.html"), "markdown": str(out / "pairwise_summary.md"), "text_diff_html": str(out / "raw_text_diff.html") if capability["text_diff_available"] and (out / "raw_text_diff.html").exists() else None, "export": str(out / "file_diff_export.zip"), "generated_at": _utc_now()}
    pairwise_result['source_stamps'] = source_stamps
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
    _render_markdown_summary(out, meta, summary, semantic, issues)
    raw_text_diff = out / "raw_text_diff.html"
    if not capability["text_diff_available"] and raw_text_diff.is_file():
        raw_text_diff.unlink()
    _render_index(out, meta, summary, semantic, issues)
    export_path = _render_export_zip(out)
    return {"status": status, "out_dir": str(out), "summary": summary, "html": str(out / "index.html"), "markdown": str(out / "pairwise_summary.md"), "export": str(export_path), "pairwise_result": str(out / "pairwise_result.json"), "generated_at": pairwise_result['generated_at']}
