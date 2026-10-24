#!/usr/bin/env python3
"""Select per-IP checks, run existing analyzers, and prepare one review workbook."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from uuid import uuid4

try:
    import yaml
except ImportError:  # JSON configs remain usable without PyYAML.
    yaml = None

from . import effective_file_tracker, lef_liberty_check, lef_review, macro_index
from .export_review_excel import export_review_excel
from .ip_check_overview import render_overview


CHECK_NAMES = {"formal_nl", "macro_index", "lef_review", "lef_liberty_check"}
VIEW_NAMES = ("lef", "liberty", "gds", "cdl", "db", "verilog")
SHEET_HEADERS = {
    "00-概览": ["IP", "库标识", "RAW版本", "正式阶段", "已选检查", "执行完成项", "执行失败项", "正式可见文件", "Macro数", "报告结论"],
    "01-检查项": ["IP", "检查", "执行状态", "结果摘要", "范围说明", "输入范围", "报告路径"],
    "02-问答": ["IP", "问题", "回答", "证据范围", "来源报告"],
    "03-关注项": ["IP", "类别", "对象", "发现", "状态", "建议核对", "证据路径"],
    "04-MacroView": ["IP", "RAW版本", "Macro", "LEF", "Liberty", "GDS", "CDL", "DB", "Verilog", "基准状态", "证据说明"],
    "05-正式文件": ["IP", "正式阶段", "相对路径", "View", "来源RAW版本", "来源路径", "正式路径", "盘点状态"],
    "06-LEF宏": ["IP", "LEF文件", "Macro", "类别", "Site", "宽度", "高度", "单位", "Pin数", "电源Pin", "地Pin", "OBS几何数", "解析范围"],
    "07-Liberty角": ["IP", "Liberty文件", "Library", "工艺角线索", "RC角线索", "PVT", "Cell数", "同名Cell", "LEF有而本文件无", "本文件有而LEF无", "信号Pin对照", "信号Pin差异", "电源/地脚对照", "电源/地脚差异", "证据不足Cell数", "角标说明"],
    "08-Liberty单元": ["IP", "Liberty文件", "Corner线索", "Cell", "LEF同名", "信号Pin数", "PG Pin数", "接口状态", "证据路径"],
}


def _load_config(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        data = json.loads(text)
    elif yaml is not None:
        data = yaml.safe_load(text)
    else:
        raise RuntimeError("读取 YAML 配置需要 PyYAML；也可使用 JSON 配置")
    if not isinstance(data, dict):
        raise ValueError("配置顶层必须是对象")
    data["_config_path"] = str(source)
    return data


def _resolve(value: Any, config_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else config_dir / path).resolve()


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.") or "ip"


def _library_dir(library_id: str) -> str:
    slug = _safe_id(library_id)[:72]
    suffix = hashlib.sha256(library_id.encode("utf-8")).hexdigest()[:12]
    return f"{slug}__{suffix}"


def _new_review_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"review_{timestamp}_{uuid4().hex[:8]}"


def _json_read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"结果 JSON 顶层不是对象：{path}")
    return data


def _json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_formal(spec: dict[str, Any], config_dir: Path, out_dir: Path) -> dict[str, Any]:
    if spec.get("report_json"):
        return _json_read(_resolve(spec["report_json"], config_dir))
    if not spec.get("config"):
        raise ValueError("formal_nl 需要 config 或 report_json")
    original = _resolve(spec["config"], config_dir)
    raw = effective_file_tracker._load_config(original)
    for section, key in (("library", "root"), ("formal_nl", "root"), ("library", "catalog")):
        value = (raw.get(section) or {}).get(key)
        if value:
            (raw[section])[key] = str(_resolve(value, original.parent))
    ip_label = str((raw.get("library") or {}).get("ip_directory_name") or
                   (raw.get("library") or {}).get("id") or original.stem)
    target = out_dir / "formal_nl"
    raw["output"] = {"report_json": str(target / "formal_nl.json"), "report_md": str(target / "formal_nl.md")}
    if yaml is None:
        raise RuntimeError("执行正式目录 YAML 配置需要 PyYAML")
    temp_config = target / "runner_config.yml"
    temp_config.parent.mkdir(parents=True, exist_ok=True)
    temp_config.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return effective_file_tracker.run(temp_config)


def _filemap_from_root(spec: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    root = _resolve(spec["root"], config_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Macro Index 输入目录不存在：{root}")
    version = str(spec.get("version") or root.name)
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        view = effective_file_tracker._view_for_path(Path(rel))
        if view in macro_index.VIEWS:
            files.append({"view": view, "relative_path": rel, "source_path": str(path.resolve()),
                          "source_version": version})
    return {"library_id": str(spec.get("library_id") or root.name),
            "context": {"type": str(spec.get("context_type") or "RAW"), "source": str(root)},
            "files": files}


def _run_macro(spec: dict[str, Any], config_dir: Path, out_dir: Path, ip_id: str) -> dict[str, Any]:
    if spec.get("report_json"):
        return _json_read(_resolve(spec["report_json"], config_dir))
    if spec.get("filemap_json"):
        filemap = _json_read(_resolve(spec["filemap_json"], config_dir))
    elif spec.get("root"):
        filemap = _filemap_from_root(spec, config_dir)
    else:
        raise ValueError("macro_index 需要 report_json、filemap_json 或 root")
    facts = _json_read(_resolve(spec["parser_facts_json"], config_dir)) if spec.get("parser_facts_json") else \
        macro_index.build_parser_facts(filemap)
    index = macro_index.build_macro_index_from_filemap(filemap, facts, spec.get("aliases"))
    result = {"source": {"ip": ip_id}, "filemap": filemap, "parser_facts": facts, "macro_index": index}
    target = out_dir / "macro_index.json"
    _json_write(target, result)
    return result


def _run_lef_review(spec: dict[str, Any], config_dir: Path, out_dir: Path, ip_id: str) -> dict[str, Any]:
    if spec.get("report_json"):
        return _json_read(_resolve(spec["report_json"], config_dir))
    if not spec.get("old_file") or not spec.get("new_file"):
        raise ValueError("lef_review 需要 old_file 和 new_file，或 report_json")
    result = lef_review.analyze(_resolve(spec["old_file"], config_dir), _resolve(spec["new_file"], config_dir))
    target = out_dir / "lef_review"
    _json_write(target / "lef_analysis.json", result)
    (target / "lef_review.md").write_text(lef_review.render_markdown(result), encoding="utf-8")
    return result


def _lef_source(lef_report: dict[str, Any]) -> dict[str, Any]:
    return dict(((lef_report.get("sources") or {}).get("new") or {}))


def _source_identity(source: dict[str, Any]) -> tuple[str, str]:
    path = source.get("path")
    digest = source.get("sha256")
    if not path or not digest:
        raise ValueError("LEF 来源身份不完整；需要源路径和 SHA-256")
    digest = str(digest).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("LEF 来源 SHA-256 格式无效")
    return str(Path(str(path)).expanduser().resolve()), digest


def _require_same_lef_source(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    if _source_identity(actual) != _source_identity(expected):
        raise ValueError("LEF 来源不一致；拒绝将其他文件的联动结果挂到当前 IP")


def _run_lef_liberty(spec: dict[str, Any], config_dir: Path, out_dir: Path,
                     ip_id: str, library_id: str,
                     lef_result: dict[str, Any] | None) -> dict[str, Any]:
    lef_report_path = None
    expected_source = None
    if lef_result is not None:
        lef_report_path = out_dir / "lef_review" / "lef_analysis.json"
        expected_source = _lef_source(lef_result)
    elif spec.get("lef_analysis_json"):
        if str(spec.get("lef_library_id") or "") != library_id:
            raise ValueError("单独引用 LEF 报告时必须提供匹配当前 IP 的 lef_library_id")
        lef_report_path = _resolve(spec["lef_analysis_json"], config_dir)
        expected_source = _lef_source(_json_read(lef_report_path))
    elif spec.get("lef_library_id") and str(spec["lef_library_id"]) != library_id:
        raise ValueError("lef_library_id 与当前 IP 不一致")

    if spec.get("report_json"):
        result = _json_read(_resolve(spec["report_json"], config_dir))
        actual_source = dict(result.get("lef_source") or {})
        if expected_source is not None:
            _require_same_lef_source(actual_source, expected_source)
        elif str(spec.get("lef_library_id") or "") != library_id:
            raise ValueError("引用既有联动报告时必须提供匹配当前 IP 的 lef_library_id，或同时选择 lef_review")
        else:
            _source_identity(actual_source)
        return result

    if lef_report_path is None:
        raise ValueError("lef_liberty_check 需要可用的 LEF 核查报告；请先选择 lef_review，或提供 lef_analysis_json 与 lef_library_id")
    if not lef_report_path.is_file():
        raise ValueError(f"LEF 核查报告不存在：{lef_report_path}")
    if expected_source:
        _source_identity(expected_source)
    liberty_values = spec.get("liberty_files") or []
    if not liberty_values:
        raise ValueError("lef_liberty_check 至少需要一个 liberty_files 路径")
    liberty_paths = [_resolve(item, config_dir) for item in liberty_values]
    result = lef_liberty_check.analyze_many(
        lef_report_path, liberty_paths, keep_matching_cells=bool(spec.get("include_matching_cells", True)))
    target = out_dir / "lef_liberty_check"
    _json_write(target / "lef_liberty_check.json", result)
    (target / "lef_liberty_check.md").write_text(lef_liberty_check.render_markdown(result), encoding="utf-8")
    return result


def run_review(config: dict[str, Any], out_dir: str | Path) -> list[dict[str, Any]]:
    config_dir = Path(config["_config_path"]).parent if config.get("_config_path") else Path.cwd()
    output_dir = Path(out_dir).expanduser().resolve()
    review_id = _new_review_id()
    reviews = []
    configured_ips = config.get("ips") or []
    library_ids = [str(ip.get("library_id") or ip.get("id") or ip.get("name") or f"IP_{index + 1}")
                   for index, ip in enumerate(configured_ips)]
    if len(library_ids) != len(set(library_ids)):
        duplicates = sorted({library_id for library_id in library_ids if library_ids.count(library_id) > 1})
        raise ValueError(f"library_id 重复；请拆分不同上下文为独立运行，避免结果合并：{', '.join(duplicates)}")
    for index, ip in enumerate(configured_ips):
        ip_id = str(ip.get("id") or ip.get("name") or f"IP_{index + 1}")
        library_id = str(ip.get("library_id") or ip_id)
        run_dir = output_dir / "libraries" / _library_dir(library_id) / "runs" / review_id
        evidence_dir = run_dir / "evidence"
        checks_spec = ip.get("checks") or {}
        if isinstance(checks_spec, list):
            checks_spec = {str(item.get("name")): item for item in checks_spec if isinstance(item, dict)}
        unknown = set(checks_spec) - CHECK_NAMES
        if unknown:
            raise ValueError(f"{ip_id}: 不支持的检查名：{', '.join(sorted(unknown))}")
        check_results: dict[str, dict[str, Any]] = {}
        evidence_dir.mkdir(parents=True, exist_ok=True)
        lef_result = None
        runners = {
            "formal_nl": lambda spec: _run_formal(spec, config_dir, evidence_dir),
            "macro_index": lambda spec: _run_macro(spec, config_dir, evidence_dir, ip_id),
            "lef_review": lambda spec: _run_lef_review(spec, config_dir, evidence_dir, ip_id),
        }
        execution_order = {"lef_review": 0, "formal_nl": 1, "macro_index": 2, "lef_liberty_check": 3}
        for name, spec in sorted(checks_spec.items(), key=lambda item: execution_order[item[0]]):
            if not isinstance(spec, dict) or spec.get("enabled", True) is False:
                continue
            try:
                if name == "lef_liberty_check":
                    result = _run_lef_liberty(spec, config_dir, evidence_dir, ip_id, library_id, lef_result)
                else:
                    result = runners[name](spec)
                if name == "lef_review":
                    lef_result = result
                    generated_lef_report = evidence_dir / "lef_review" / "lef_analysis.json"
                    if not generated_lef_report.is_file():
                        _json_write(generated_lef_report, result)
                result_status = str(result.get("report_status") or result.get("status") or "COMPLETE").upper()
                status = "COMPLETE" if result_status in {"COMPLETE", "MATCHED", "DONE", "PASS"} else "INCOMPLETE"
                report_path = str(result.get("report_json") or result.get("report_md") or spec.get("report_json") or "")
                if not report_path:
                    expected = {
                        "macro_index": evidence_dir / "macro_index.json",
                        "lef_review": evidence_dir / "lef_review" / "lef_analysis.json",
                        "lef_liberty_check": evidence_dir / "lef_liberty_check" / "lef_liberty_check.json",
                    }.get(name)
                    report_path = str(expected or "")
                snapshot_path = evidence_dir / f"{name}.json"
                _json_write(snapshot_path, result)
                check_results[name] = {"selected": True, "status": status,
                                       "result_status": result_status, "result": result,
                                       "report_path": report_path, "result_ref": f"evidence/{name}.json",
                                       "input_spec": dict(spec)}
            except Exception as exc:
                check_results[name] = {"selected": True, "status": "FAILED", "result_status": "FAILED",
                                       "error": str(exc), "result": {}, "report_path": "", "result_ref": "",
                                       "input_spec": dict(spec)}
        context = {"type": str(ip.get("context_type") or "LIBRARY_REVIEW"),
                   "formal_stage": ip.get("formal_stage"),
                   "formal_snapshot_id": ip.get("formal_snapshot_id"),
                   "target_raw_versions": [str(ip.get("raw_version"))] if ip.get("raw_version") else []}
        reviews.append({"ip": {**ip, "id": ip_id, "library_id": library_id},
                        "review_id": review_id, "generated_at": datetime.now(timezone.utc).isoformat(),
                        "context": context, "requested_checks": [name for name, item in check_results.items()
                                                                    if item.get("selected")],
                        "checks": check_results, "run_dir": str(run_dir),
                        "library_dir": str(run_dir.parents[1])})
    return reviews


def _check_result(review: dict[str, Any], name: str) -> dict[str, Any]:
    return (review.get("checks") or {}).get(name) or {}


def _result(review: dict[str, Any], name: str) -> dict[str, Any]:
    return _check_result(review, name).get("result") or {}


def _check_summary(name: str, item: dict[str, Any]) -> tuple[str, str]:
    """Separate execution success from engineering findings and their scope."""
    if item.get("status") == "FAILED":
        return str(item.get("error") or "执行失败"), "本项未产生可用结果。"
    if item.get("status") != "COMPLETE":
        return "结果不完整", "仅供定位；不能据此判定检查通过。"

    result = item.get("result") or {}
    if name == "formal_nl":
        inventories = result.get("inventories") or {}
        inventory = next(iter(inventories.values()), {}) if len(inventories) == 1 else {}
        broken = len(result.get("broken_links") or [])
        return f"可见文件 {inventory.get('file_count', '未统计')} 个；断链 {broken} 个", \
            "只读盘点链接和路径；不读取文件内容，也不判断交付齐套或发布放行。"
    if name == "macro_index":
        index = result.get("macro_index") or result
        baseline = index.get("baseline") or {}
        macros = baseline.get("macro_count", len(index.get("macros") or {}))
        unmatched_files = len(index.get("unmatched_files") or [])
        unmatched_objects = sum(len(values) for values in (index.get("unmatched_objects") or {}).values())
        return f"Macro {macros} 个；未关联文件 {unmatched_files} 个；未映射对象 {unmatched_objects} 个", \
            "按当前解析事实建立名称关联；未映射不等于交付缺失，索引完成不代表全部视图齐套。"
    if name == "lef_review":
        comparison = result.get("comparison") or {}
        names = comparison.get("macro_names") or {}
        content = comparison.get("content") or {}
        return (f"字节状态 {content.get('status', '未确认')}；Macro 新增 "
                f"{len(names.get('added') or [])}、移除 {len(names.get('removed') or [])}；"
                f"字段差异 {len(comparison.get('changes') or [])} 条"), \
            "仅比较指定的旧/新 LEF 文件及当前解析器覆盖字段。"
    if name == "lef_liberty_check":
        summary = result.get("summary") or {}
        return (f"Liberty {summary.get('liberty_file_count', len(result.get('files') or []))} 个；"
                f"接口不一致文件 {summary.get('files_with_mismatches', '未统计')} 个；"
                f"证据不足文件 {summary.get('files_with_unverified', '未统计')} 个；"
                f"单文件范围差异 {summary.get('files_with_scope_gaps', '未统计')} 个"), \
            "逐文件核对且不合并 Corner；范围差异不等于缺交付，不判断时序性能或发布放行。"
    return "执行完成", "结果仅适用于本次显式输入范围。"


def _formal_inventory(formal: dict[str, Any], stage: str | None = None) -> tuple[str, dict[str, Any]]:
    inventories = formal.get("inventories") or {}
    if stage and stage in inventories:
        return stage, inventories[stage]
    if len(inventories) == 1:
        return next(iter(inventories.items()))
    return stage or "", {}


def _macro_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    result = _result(review, "macro_index")
    index = result.get("macro_index") or result
    rows = []
    context = review.get("ip") or {}
    for name, mappings in (index.get("macros") or {}).items():
        row = {"IP": context.get("name") or context.get("id"),
               "RAW版本": context.get("raw_version") or "" , "Macro": name,
               "基准状态": (index.get("baseline") or {}).get("status", "未知"),
               "证据说明": index.get("evidence_note") or "按解析对象和文件名证据建立映射；文件名候选不等同内容验证。"}
        for view in VIEW_NAMES:
            entries = mappings.get(view) or []
            row[view.upper() if view != "liberty" else "Liberty"] = "\n".join(
                f"{item.get('file') or Path(item.get('source_path') or '').name} [{item.get('evidence', '未知')}]"
                for item in entries
            ) or "未关联"
        rows.append(row)
    return rows


def _formal_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    formal = _result(review, "formal_nl")
    stage, inventory = _formal_inventory(formal, ip.get("formal_stage"))
    rows = []
    for item in inventory.get("files") or []:
        rows.append({"IP": ip.get("name") or ip.get("id"), "正式阶段": stage,
                     "相对路径": item.get("relative_path", ""), "View": item.get("view", "other"),
                     "来源RAW版本": item.get("raw_version", "未映射"),
                     "来源路径": item.get("source_path", ""),
                     "正式路径": item.get("published_path", ""),
                     "盘点状态": inventory.get("status", formal.get("status", "未知"))})
    return rows


def _lef_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    result = _result(review, "lef_review")
    data = (((result.get("extraction") or {}).get("new") or {}).get("data") or {})
    source = (result.get("sources") or {}).get("new") or {}
    rows = []
    for name, macro in (data.get("macros") or {}).items():
        pins = macro.get("pins") or {}
        uses = Counter(str(pin.get("use") or "SIGNAL").upper() for pin in pins.values())
        size = macro.get("size") or {}
        rows.append({"IP": ip.get("name") or ip.get("id"), "LEF文件": source.get("path", ""),
                     "Macro": name, "类别": macro.get("class") or "未提供", "Site": macro.get("site") or "未提供",
                     "宽度": size.get("x", "未提取"), "高度": size.get("y", "未提取"),
                     "单位": "μm（源解析单位；具体覆盖见报告）", "Pin数": len(pins),
                     "电源Pin": uses.get("POWER", 0), "地Pin": uses.get("GROUND", 0),
                     "OBS几何数": sum(len(layer.get("rects") or []) for layer in (macro.get("obs") or [])),
                     "解析范围": "仅新文件；字段由当前 LEF Parser 提取，不表示 LEF 全语法验证"})
    return rows


def _liberty_rows(review: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ip = review.get("ip") or {}
    result = _result(review, "lef_liberty_check")
    corner_rows, cell_rows = [], []
    lef_names = set((((_result(review, "lef_review").get("extraction") or {}).get("new") or {}).get("data") or {}).get("macros", {}))
    for item in result.get("files") or []:
        axes = item.get("corner_axes") or {}
        summary = item.get("summary") or {}
        inventory = item.get("liberty_inventory") or {}
        comparison = item.get("comparison") or {}
        path = item.get("liberty_source", "")
        corner = axes.get("process_corner") or "未识别"
        corner_rows.append({"IP": ip.get("name") or ip.get("id"), "Liberty文件": path,
                            "Library": ", ".join(item.get("library_names") or []) or "未识别",
                            "工艺角线索": corner, "RC角线索": axes.get("rc_corner") or "未识别",
                            "PVT": json.dumps(item.get("operating_conditions") or {}, ensure_ascii=False),
                            "Cell数": inventory.get("cell_count", "未确认"),
                            "同名Cell": summary.get("matched_macro_count", "未确认"),
                            "LEF有而本文件无": summary.get("lef_only_macro_count", "未确认"),
                            "本文件有而LEF无": summary.get("liberty_only_cell_count", "未确认"),
                            "信号Pin对照": summary.get("signal_pin_checked_count", "未确认"),
                            "信号Pin差异": (summary.get("signal_pin_missing_count", 0) + summary.get("signal_pin_extra_count", 0)
                                           + summary.get("signal_pin_direction_mismatch_count", 0)),
                            "电源/地脚对照": summary.get("power_ground_checked_count", "未确认"),
                            "电源/地脚差异": (summary.get("power_ground_missing_count", 0) + summary.get("power_ground_extra_count", 0)
                                              + summary.get("power_ground_wrong_type_count", 0)),
                            "证据不足Cell数": summary.get("unverified_cell_count", "未统计"),
                            "角标说明": "工艺角仅为名称线索，不等于人工确认"})
        for cell in item.get("cells") or []:
            cell_rows.append({"IP": ip.get("name") or ip.get("id"), "Liberty文件": path,
                              "Corner线索": corner, "Cell": cell.get("macro", ""),
                              "LEF同名": cell.get("macro") in lef_names,
                              "信号Pin数": cell.get("signal_pin_checked_count", "未确认"),
                              "PG Pin数": cell.get("power_ground_checked_count", "未确认"),
                              "接口状态": cell.get("status", "未知"), "证据路径": path})
    return corner_rows, cell_rows


def _finding_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    label = ip.get("name") or ip.get("id")
    rows = []

    def add(category: str, object_name: str, finding: str, status: str, action: str, evidence: str = "") -> None:
        rows.append({"IP": label, "类别": category, "对象": object_name, "发现": finding,
                     "状态": status, "建议核对": action, "证据路径": evidence})

    formal = _result(review, "formal_nl")
    for item in formal.get("broken_links") or []:
        add("正式链接", item, "正式链接目标不可读或不存在", "需处理", "确认源路径和链接权限", formal.get("formal_nl_root", ""))
    for item in formal.get("ambiguous_versions") or []:
        add("正式来源", item.get("nl_version", ""), "同一阶段发现多个来源目标", "待确认", "人工确认应使用的来源", formal.get("formal_nl_root", ""))
    macro_result = _result(review, "macro_index")
    index = macro_result.get("macro_index") or macro_result
    for item in index.get("unmatched_files") or []:
        add("Macro/View映射", item.get("file", ""), str(item.get("reason", "文件未能关联解析事实")), "证据不足",
            "确认文件是否被支持的解析器覆盖", item.get("file", ""))
    for view, objects in (index.get("unmatched_objects") or {}).items():
        if objects:
            sample_names = ", ".join(str(item.get("name", "")) for item in objects[:5])
            add("Macro/View名称映射", view.upper(),
                f"{len(objects)} 个解析对象未与 LEF Macro 精确同名关联；示例：{sample_names}", "关联待确认",
                "名称差异不等于缺交付；按需确认别名或对象层级", objects[0].get("file", ""))
    lef = _result(review, "lef_review")
    comp = lef.get("comparison") or {}
    names = comp.get("macro_names") or {}
    for field, values in (("新增Macro", names.get("added")), ("移除Macro", names.get("removed"))):
        for name in values or []:
            add("LEF变化", name, field, "已提取差异", "核对该 Macro 的接入影响", (lef.get("sources") or {}).get("new", {}).get("path", ""))
    for change in comp.get("changes") or []:
        add("LEF字段变化", change.get("macro", ""),
            f"{change.get('field')}: {change.get('old')} → {change.get('new')}", "已提取差异",
            "结合对象用途核对变化", (lef.get("sources") or {}).get("new", {}).get("path", ""))
    for field in comp.get("unverified") or []:
        add("LEF证据范围", field, "该字段未得到完整解析覆盖", "证据不足", "确认是否需要补充针对性解析",
            (lef.get("sources") or {}).get("new", {}).get("path", ""))
    for file_result in (_result(review, "lef_liberty_check").get("files") or []):
        summary = file_result.get("summary") or {}
        if summary.get("mismatch_cell_count"):
            add("LEF-Liberty接口", Path(file_result.get("liberty_source", "")).name,
                f"发现 {summary['mismatch_cell_count']} 个接口不一致 Cell", "已确认差异",
                "查看 Liberty 单元明细中的 Pin 差异", file_result.get("liberty_source", ""))
        if summary.get("unverified_cell_count"):
            add("LEF-Liberty证据", Path(file_result.get("liberty_source", "")).name,
                f"{summary['unverified_cell_count']} 个同名 Cell 证据不足", "证据不足",
                "检查解析覆盖与受限语法", file_result.get("liberty_source", ""))
    ll = _result(review, "lef_liberty_check")
    gap_files = [item for item in ll.get("files", [])
                 if (item.get("summary") or {}).get("lef_only_macro_count")]
    if gap_files:
        counts = sorted({(item.get("summary") or {}).get("lef_only_macro_count") for item in gap_files})
        add("Liberty文件范围", f"{len(gap_files)} 个文件",
            f"所选文件单独未包含 {', '.join(str(value) for value in counts)} 个 LEF Macro 名称；这是输入文件范围差异，不直接表示交付缺失。",
            "范围说明", "若要统计该角的 Cell 并集，请选择同一用途/角的完整 Liberty 文件集合",
        "详见 07-Liberty角 的逐文件路径")
    return rows


def _qa_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    label = ip.get("name") or ip.get("id")
    rows = []
    formal = _result(review, "formal_nl")
    formal_check = _check_result(review, "formal_nl")
    stage, inventory = _formal_inventory(formal, ip.get("formal_stage"))
    if formal_check:
        counts = inventory.get("view_counts") or {}
        rows.append({"IP": label, "问题": "正式目录观察到哪些文件类型和数量？",
                     "回答": "观察到：" + ("；".join(f"{name} {count} 个" for name, count in sorted(counts.items())) or "当前清单为空"),
                     "证据范围": f"阶段 {stage}；目录盘点状态 {inventory.get('status', formal.get('status', '未知'))}。数量为可见路径，不判断是否必需。",
                     "来源报告": formal.get("report_json", "")})
    macro_check = _check_result(review, "macro_index")
    macro_result = _result(review, "macro_index")
    index = macro_result.get("macro_index") or macro_result
    baseline = index.get("baseline") or {}
    if macro_check:
        rows.append({"IP": label, "问题": "解析并建立了多少个 LEF Macro 索引？",
                     "回答": f"{baseline.get('macro_count', len(index.get('macros') or {}))} 个；LEF 基线状态：{baseline.get('status', '未知')}。",
                     "证据范围": "索引覆盖见 Macro-View 表；文件名/名称关联不代表文件内容确认或交付齐套。",
                     "来源报告": macro_check.get("report_path", "")})
    lef_check = _check_result(review, "lef_review")
    lef = _result(review, "lef_review")
    if lef_check:
        comp = lef.get("comparison") or {}
        names = comp.get("macro_names") or {}
        content = comp.get("content") or {}
        rows.append({"IP": label, "问题": "两份指定 LEF 有哪些已确认变化？",
                     "回答": f"文件字节状态：{content.get('status', '未确认')}；Macro新增 {len(names.get('added') or []) if names.get('added') is not None else '未确认'}，移除 {len(names.get('removed') or []) if names.get('removed') is not None else '未确认'}，字段差异 {len(comp.get('changes') or [])}。",
                     "证据范围": "仅限所选的旧/新 LEF 文件及当前 Parser 覆盖字段。", "来源报告": lef_check.get("report_path", "")})
    ll_check = _check_result(review, "lef_liberty_check")
    ll = _result(review, "lef_liberty_check")
    if ll_check:
        summary = ll.get("summary") or {}
        corners = ", ".join(summary.get("recognized_corners") or []) or "未识别"
        scope_gap_files = summary.get("files_with_scope_gaps", "未统计")
        rows.append({"IP": label, "问题": "指定 Liberty 与 LEF 的接口核对结果是什么？",
                     "回答": f"逐文件检查 {summary.get('liberty_file_count', len(ll.get('files') or []))} 个 Liberty；角标线索 {corners}；接口不一致文件 {summary.get('files_with_mismatches', '未统计')}，证据不足文件 {summary.get('files_with_unverified', '未统计')}，单文件名称范围差异 {scope_gap_files} 个。",
                     "证据范围": "单文件名称范围差异不等于缺交付；接口结论仅限输入 Liberty 与指定 LEF 的同名对象、当前解析器支持字段；不判断时序性能或放行。",
                     "来源报告": ll_check.get("report_path", "")})
    if not rows:
        rows.append({"IP": label, "问题": "本次执行了哪些检查？", "回答": "未选择检查。",
                     "证据范围": "没有产生工程检查结论。", "来源报告": ""})
    return rows


def build_workbook_model(reviews: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Flatten independently-scoped IP results into human-reviewable sheet rows."""
    selected_names = {name for review in reviews for name, item in (review.get("checks") or {}).items()
                      if item.get("selected")}
    sheet_names = ["00-概览", "01-检查项", "02-问答", "03-关注项"]
    if "macro_index" in selected_names:
        sheet_names.append("04-MacroView")
    if "formal_nl" in selected_names:
        sheet_names.append("05-正式文件")
    if "lef_review" in selected_names:
        sheet_names.append("06-LEF宏")
    if "lef_liberty_check" in selected_names:
        sheet_names.extend(["07-Liberty角", "08-Liberty单元"])
    model = {name: [] for name in sheet_names}
    for review in reviews:
        ip = review.get("ip") or {}
        label = ip.get("name") or ip.get("id") or "未命名IP"
        selected = [(name, item) for name, item in (review.get("checks") or {}).items() if item.get("selected")]
        complete = sum(item.get("status") == "COMPLETE" for _, item in selected)
        failed = sum(item.get("status") == "FAILED" for _, item in selected)
        formal = _result(review, "formal_nl")
        stage, inventory = _formal_inventory(formal, ip.get("formal_stage"))
        index = _result(review, "macro_index").get("macro_index") or _result(review, "macro_index")
        macro_count = (index.get("baseline") or {}).get("macro_count", len(index.get("macros") or {})) if _check_result(review, "macro_index") else "未检查"
        model["00-概览"].append({"IP": label, "库标识": ip.get("library_id") or ip.get("id", ""),
                                 "RAW版本": ip.get("raw_version", "未指定"), "正式阶段": stage or ip.get("formal_stage", "未检查"),
                                 "已选检查": "、".join(name for name, _ in selected) or "无",
                                 "执行完成项": complete, "执行失败项": failed,
                                 "正式可见文件": inventory.get("file_count", "未检查"), "Macro数": macro_count,
                                 "报告结论": "检查任务结果汇总；不等于正式放行或完整性通过"})
        for name, item in selected:
            summary, scope = _check_summary(name, item)
            execution = {"COMPLETE": "执行完成", "INCOMPLETE": "结果不完整", "FAILED": "执行失败"}.get(
                item.get("status"), "状态未知")
            model["01-检查项"].append({"IP": label, "检查": name, "执行状态": execution,
                                      "结果摘要": summary, "范围说明": scope,
                                      "输入范围": json.dumps({key: value for key, value in item.get("input_spec", {}).items() if key != "enabled"}, ensure_ascii=False),
                                      "报告路径": item.get("report_path", "")})
        model["02-问答"].extend(_qa_rows(review))
        model["03-关注项"].extend(_finding_rows(review))
        if _check_result(review, "macro_index").get("selected"):
            model["04-MacroView"].extend(_macro_rows(review))
        if _check_result(review, "formal_nl").get("selected"):
            model["05-正式文件"].extend(_formal_rows(review))
        if _check_result(review, "lef_review").get("selected"):
            model["06-LEF宏"].extend(_lef_rows(review))
        if _check_result(review, "lef_liberty_check").get("selected"):
            corners, cells = _liberty_rows(review)
            model["07-Liberty角"].extend(corners)
            model["08-Liberty单元"].extend(cells)
    return model


def run(config: dict[str, Any], out_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reviews = run_review(config, out_dir)
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    row_counts: Counter[str] = Counter()
    overview_rows = []
    for review in reviews:
        run_dir = Path(review["run_dir"])
        library_dir = Path(review["library_dir"])
        model = build_workbook_model([review])
        for name, rows in model.items():
            row_counts[name] += len(rows)
        requested = review.get("requested_checks") or []
        checks = review.get("checks") or {}
        complete = bool(requested) and all(checks[name].get("status") == "COMPLETE" for name in requested)
        serialized_checks = {}
        for name in sorted(CHECK_NAMES):
            item = checks.get(name)
            if not item:
                serialized_checks[name] = {"execution_status": "NOT_RUN"}
                continue
            serialized_checks[name] = {"execution_status": item.get("status", "INCOMPLETE"),
                                       "result_status": item.get("result_status"),
                                       "result_ref": item.get("result_ref") or None,
                                       "report_path": item.get("report_path") or None,
                                       "error": item.get("error")}
        review_record = {"schema_version": "review_result.v1",
                         "library_id": (review.get("ip") or {}).get("library_id"),
                         "review_id": review.get("review_id"), "generated_at": review.get("generated_at"),
                         "context": review.get("context"), "requested_checks": requested,
                         "execution_status": "COMPLETE" if complete else ("FAILED" if any(
                             item.get("status") == "FAILED" for item in checks.values()) else "INCOMPLETE"),
                         "checks": serialized_checks,
                         "summary": _review_summary(review),
                         "reports": {"xlsx": "ip_review.xlsx"}}
        _json_write(run_dir / "review_result.json", review_record)
        scope_note = (f"IP：{review_record['library_id']}；Review：{review_record['review_id']}；"
                      "仅汇总本 IP、本次选择的检查。未选择不代表通过。")
        export_review_excel(model, run_dir / "ip_review.xlsx", scope_note=scope_note)
        latest_ref = None
        if (review.get("ip") or {}).get("publish_latest") and complete:
            latest = {"schema_version": "review_latest.v1", "library_id": review_record["library_id"],
                      "review_id": review_record["review_id"],
                      "review_result_ref": f"runs/{review_record['review_id']}/review_result.json",
                      "xlsx_ref": f"runs/{review_record['review_id']}/ip_review.xlsx",
                      "generated_at": review_record["generated_at"]}
            latest_path = library_dir / "latest.json"
            temporary = latest_path.with_suffix(".json.tmp")
            _json_write(temporary, latest)
            temporary.replace(latest_path)
            latest_ref = str(latest_path)
        overview_rows.append({"library_id": review_record["library_id"],
                              "name": (review.get("ip") or {}).get("name") or review_record["library_id"],
                              "review_id": review_record["review_id"],
                              "execution_status": review_record["execution_status"],
                              "requested_checks": requested, "summary": review_record["summary"],
                              "xlsx_href": "../" + (run_dir / "ip_review.xlsx").relative_to(output).as_posix(),
                              "latest": bool(latest_ref)})
        review["review_result_path"] = str(run_dir / "review_result.json")
        review["xlsx_path"] = str(run_dir / "ip_review.xlsx")
        review["latest_path"] = latest_ref or ""
    overview_path = output / "ip_checks" / "index.html"
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text(render_overview(overview_rows), encoding="utf-8")
    return reviews, dict(row_counts)


def _review_summary(review: dict[str, Any]) -> dict[str, int]:
    findings = _finding_rows(review)
    return {"confirmed_changes": sum(item.get("状态") == "已提取差异" for item in findings),
            "confirmed_mismatches": sum(item.get("状态") == "已确认差异" for item in findings),
            "unverified": sum(item.get("状态") == "证据不足" for item in findings),
            "scope_notes": sum(item.get("状态") == "范围说明" for item in findings)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 IP 选择检查并生成独立 Excel 与总览")
    parser.add_argument("--config", required=True, help="YAML 或 JSON 配置，逐 IP 指定检查和输入")
    parser.add_argument("--out-dir", required=True, help="本次报告输出目录；不会写入正式目录")
    args = parser.parse_args(argv)
    try:
        config = _load_config(args.config)
        reviews, row_counts = run(config, args.out_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "DONE", "ip_count": len(reviews),
                      "check_count": sum(len(item.get("checks") or {}) for item in reviews),
                      "overview": str(Path(args.out_dir).expanduser().resolve() / "ip_checks" / "index.html"),
                      "reports": [{"library_id": (item.get("ip") or {}).get("library_id"),
                                   "review_result": item.get("review_result_path"),
                                   "workbook": item.get("xlsx_path"),
                                   "latest_pointer": item.get("latest_path") or None} for item in reviews],
                      "rows_by_sheet_across_separate_workbooks": row_counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
