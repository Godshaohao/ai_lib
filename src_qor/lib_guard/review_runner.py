#!/usr/bin/env python3
"""Select per-IP checks, run existing analyzers, and prepare one review workbook."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
from typing import Any
from uuid import uuid4

try:
    import yaml
except ImportError:  # JSON configs remain usable without PyYAML.
    yaml = None

from . import effective_file_tracker, lef_liberty_check, lef_review, macro_index
from .export_review_excel import export_review_excel
from .ip_check_overview import render_overview


CHECK_NAMES = {"macro_index", "lef_review", "lef_liberty_check"}
LEGACY_CHECK_NAMES = {"formal_nl"}
CHECK_LABELS = {
    "formal_nl": "正式目录盘点（旧版 Review 记录）",
    "macro_index": "Macro / View 文件索引",
    "lef_review": "LEF 双文件核查",
    "lef_liberty_check": "LEF–Liberty 接口核查",
}
VIEW_NAMES = ("lef", "liberty", "gds", "cdl", "db", "verilog")
SHEET_HEADERS = {
    "文件版本矩阵": ["IP", "View", "文件键", "文件名", "基准版本", "目标版本", "基准路径", "目标路径",
                   "基准存在性", "目标存在性", "身份状态", "内容状态", "语义状态", "正式阶段", "正式来源",
                   "批准状态", "RAW 覆盖", "快照 ID", "投影证据"],
    "00-概览": ["IP", "库标识", "RAW版本", "正式阶段", "已选检查", "执行完成项", "执行失败项", "质量判断", "Macro数", "报告结论", "报告生成时间", "源提交", "工作区有改动", "输入范围"],
    "01-工程检查": ["序号", "工程检查主题", "工程覆盖", "本次执行", "本次证据", "范围或缺口"],
    "02-执行记录": ["IP", "检查", "执行状态", "上下文关系", "结果摘要", "范围说明", "输入身份", "输入范围", "报告路径"],
    "03-问答": ["IP", "问题", "回答", "证据范围", "来源报告"],
    "04-关注项": ["IP", "类别", "类型", "对象", "数量", "发现", "状态", "建议核对", "证据路径"],
    "05-MacroView": ["IP", "RAW版本", "Macro", "LEF", "Liberty", "GDS", "CDL", "DB", "Verilog", "基准状态", "证据说明"],
    "06-MacroView文件": ["IP", "RAW版本", "Macro", "View", "Corner/线索", "来源版本", "文件名", "关联证据", "状态", "来源路径"],
    "07-正式文件": ["IP", "快照时间", "正式阶段", "相对路径", "View", "来源RAW版本", "来源路径", "正式路径", "盘点状态", "盘点报告"],
    "RAW文件清单": ["IP", "快照时间", "RAW版本", "RAW根目录", "版本盘点状态", "版本文件数", "View", "View文件数", "相对路径", "来源路径", "盘点报告"],
    "08-LEF宏": ["IP", "LEF文件", "Macro", "类别", "Site", "宽度", "高度", "单位", "Pin数", "电源Pin", "地Pin", "OBS几何数", "解析范围"],
    "09-Liberty角": ["IP", "Liberty文件", "Library", "工艺角线索", "RC角线索", "条件", "Process", "Voltage (V)", "Temp (°C)", "文件Cell数", "同名Cell", "LEF有而本文件无", "本文件有而LEF无", "信号Pin对照", "信号Pin差异", "电源/地脚对照", "电源/地脚差异", "证据不足Cell数", "角标说明"],
    "10-Liberty单元": ["IP", "Liberty文件", "Corner线索", "Cell", "LEF同名", "信号Pin数", "PG Pin数", "接口状态", "差异类型", "具体差异", "证据路径"],
}

ENGINEERING_CHECKLIST = (
    ("RAW 版本与文件索引", ("macro_index",), "单次选定版本索引，不代表完整历史。"),
    ("文件更新与清单 Delta", ("lef_review",), "限指定 LEF 对及当前 Parser 支持字段。"),
    ("Macro 清单、来源与更新", ("macro_index",), "选定 FileMap 的对象与文件关联，不代表多版本演进已覆盖。"),
    ("Macro 六类文件映射", ("macro_index",), "名称/解析证据映射；候选关联不是已确认齐套。"),
    ("Signoff Corner 覆盖", ("lef_liberty_check",), "仅显示所选 Liberty 的角标线索；没有期望角集合时不判断齐套。"),
    ("LEF 物理属性 Delta", ("lef_review",), "限指定 LEF 对及当前 Parser 支持字段。"),
    ("接口与跨 View 一致性", ("macro_index", "lef_liberty_check"), "限已选择输入和当前解析字段；不推断未绑定视图。"),
    ("其他 View 内部对象", ("macro_index",), "按已支持解析器提取；GDS/DB 仍为路径/文件名证据。"),
    ("文档更新 Delta", (), "当前四个检查器没有执行 DOC 正文比较。"),
)


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


def _latest_complete_run(library_dir: Path) -> tuple[dict[str, Any], Path | None]:
    """Find the newest completed run that still has its workbook artifact."""
    runs_dir = library_dir / "runs"
    candidates: list[tuple[str, dict[str, Any], Path]] = []
    if not runs_dir.is_dir():
        return {}, None
    for result_path in runs_dir.glob("review_*/review_result.json"):
        try:
            result = _json_read(result_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        review_id = str(result.get("review_id") or result_path.parent.name)
        workbook = result_path.parent / "ip_review.xlsx"
        if (result.get("execution_status") == "COMPLETE"
                and re.fullmatch(r"review_[A-Za-z0-9_-]+", review_id)
                and workbook.is_file()):
            candidates.append((str(result.get("generated_at") or review_id), result, workbook))
    if not candidates:
        return {}, None
    _, result, workbook = max(candidates, key=lambda item: (item[0], item[1].get("review_id", "")))
    return result, workbook


def _publish_cli_attempt_if_idle(path: Path, attempt: dict[str, Any]) -> bool:
    """Persist a synchronous CLI attempt without replacing a live workbench task."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(".latest_attempt.lock")
    with lock_path.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                current = _json_read(path) if path.is_file() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                current = {}
            if current.get("status") in {"QUEUED", "PENDING", "RUNNING"}:
                return False
            current_time = (current.get("submitted_at") or current.get("started_at")
                            or current.get("finished_at") or current.get("updated_at")
                            or current.get("generated_at"))
            if current_time and _timestamp_key(attempt.get("submitted_at")) <= _timestamp_key(current_time):
                return False
            _json_write_atomic(path, attempt)
            return True
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


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


def _json_write_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        _json_write(temporary, data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_latest_if_newer(latest_path: Path, latest: dict[str, Any]) -> bool:
    """Publish monotonically so a slower older run cannot move the pointer back."""
    def parsed_time(value: Any):
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    latest_path.parent.mkdir(parents=True, exist_ok=True)
    with latest_path.with_name(".latest.lock").open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            current = _json_read(latest_path) if latest_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            current = {}
        current_time = parsed_time(current.get("generated_at"))
        proposed_time = parsed_time(latest.get("generated_at"))
        if proposed_time is None:
            return False
        if current_time and proposed_time and proposed_time <= current_time:
            return False
        _json_write_atomic(latest_path, latest)
        return True


def _publish_latest_workbook(workbook_path: Path, library_dir: Path,
                             review_id: str, generated_at: str) -> bool:
    """Atomically update the per-library workbook without letting late older runs win."""
    def parsed_time(value: Any):
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    proposed_time = parsed_time(generated_at)
    if proposed_time is None:
        return False
    library_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = library_dir / "latest_workbook.json"
    temporary = library_dir / f".latest.{review_id}.tmp.xlsx"
    with (library_dir / ".latest.lock").open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                current = _json_read(pointer_path) if pointer_path.is_file() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                current = {}
            current_time = parsed_time(current.get("generated_at"))
            if current_time and proposed_time <= current_time:
                return False
            shutil.copyfile(workbook_path, temporary)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise OSError("最新 Excel 临时文件为空")
            os.replace(temporary, library_dir / "latest.xlsx")
            _json_write_atomic(pointer_path, {
                "schema_version": "workbook_latest.v1",
                "review_id": review_id,
                "generated_at": generated_at,
            })
            return True
        finally:
            temporary.unlink(missing_ok=True)


def _run_formal(spec: dict[str, Any], config_dir: Path, out_dir: Path) -> dict[str, Any]:
    if spec.get("report_json"):
        return _json_read(_resolve(spec["report_json"], config_dir))
    if spec.get("config"):
        original = _resolve(spec["config"], config_dir)
        raw = effective_file_tracker._load_config(original)
        for section, key in (("library", "root"), ("formal_nl", "root"), ("library", "catalog")):
            value = (raw.get(section) or {}).get(key)
            if value:
                (raw[section])[key] = str(_resolve(value, original.parent))
    else:
        if not (spec.get("formal_nl_root") and spec.get("ip_directory_name")):
            raise ValueError("formal_nl 需要已登记的正式 NL 路径和库名，或自选 config/report_json")
        raw = {"library": {"id": str(spec.get("library_id") or ""),
                           "root": str(_resolve(spec["root"], config_dir)) if spec.get("root") else "",
                           "ip_directory_name": str(spec["ip_directory_name"])},
               "formal_nl": {"root": str(_resolve(spec["formal_nl_root"], config_dir))}}
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
    if spec.get("pairs"):
        from .batch_lef_review import analyze_pairs
        return analyze_pairs(spec["pairs"], out_dir / "lef_batch")
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
        if spec.get("lef_file"):
            expected_path, _ = _source_identity(expected_source)
            supplied_path = str(_resolve(spec["lef_file"], config_dir).resolve())
            if supplied_path != expected_path:
                raise ValueError("接口核查 LEF 与 LEF 对比目标文件不一致；请统一输入或分别运行")
        if spec.get("lef_analysis_json"):
            supplied_report = _json_read(_resolve(spec["lef_analysis_json"], config_dir))
            _require_same_lef_source(_lef_source(supplied_report), expected_source)
    elif spec.get("lef_analysis_json"):
        if str(spec.get("lef_library_id") or "") != library_id:
            raise ValueError("单独引用 LEF 报告时必须提供匹配当前 IP 的 lef_library_id")
        lef_report_path = _resolve(spec["lef_analysis_json"], config_dir)
        expected_source = _lef_source(_json_read(lef_report_path))
    elif spec.get("lef_file"):
        source_path = _resolve(spec["lef_file"], config_dir)
        if not source_path.is_file():
            raise ValueError(f"LEF 文件不存在：{source_path}")
        snapshot = lef_review.analyze(source_path, source_path)
        snapshot["analysis_mode"] = "SINGLE_FILE_SNAPSHOT"
        lef_report_path = out_dir / "lef_liberty_check" / "lef_snapshot.json"
        _json_write(lef_report_path, snapshot)
        expected_source = _lef_source(snapshot)
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
        projection = None
        batch_pairs = None
        if ip.get("projection_json"):
            projection = _json_read(_resolve(ip["projection_json"], config_dir))
            if projection.get("schema_version") != "file_version_projection.v1" or not projection.get("snapshot_id"):
                raise ValueError("文件版本投影格式或快照标识无效")
            if str(projection.get("library_id") or "") != library_id:
                raise ValueError("文件版本投影的库标识不一致")
            target = str((projection.get("scope") or {}).get("target_version") or "")
            if not target or target != str(ip.get("raw_version") or ""):
                raise ValueError("文件版本投影的目标版本与本次检查不一致")
            lef_spec = checks_spec.get("lef_review") or {}
            if lef_spec and lef_spec.get("enabled", True):
                if lef_spec.get("pairs"):
                    requested = lef_spec["pairs"]
                    if not isinstance(requested, list) or not 1 <= len(requested) <= 50:
                        raise ValueError("LEF 批量检查需选择 1 至 50 个文件")
                    keys = [str(item.get("file_key") or "") for item in requested if isinstance(item, dict)]
                    if len(keys) != len(requested) or len(set(keys)) != len(keys):
                        raise ValueError("LEF 文件选择无效或重复")
                    base = str((projection.get("scope") or {}).get("base_version") or "")
                    if not base:
                        raise ValueError("LEF 批量检查需要投影基准版本")
                    batch_pairs = []
                    for key in keys:
                        rows = [row for row in projection.get("files") or [] if row.get("file_key") == key]
                        if len(rows) != 1 or rows[0].get("view") != "lef" or rows[0].get("identity_status") != "EXACT_RELATIVE_PATH":
                            raise ValueError("LEF 文件不属于投影中的唯一配对")
                        occurrences = rows[0].get("occurrences") or []
                        old = [item.get("source_path") for item in occurrences if item.get("version") == base and item.get("source_path")]
                        new = [item.get("source_path") for item in occurrences if item.get("version") == target and item.get("source_path")]
                        if len(old) != 1 or len(new) != 1:
                            raise ValueError("LEF 文件的基准或目标来源不唯一")
                        batch_pairs.append({"pair_id": hashlib.sha256(key.encode()).hexdigest()[:24],
                                            "file_key": key, "old_file": str(_resolve(old[0], config_dir)),
                                            "new_file": str(_resolve(new[0], config_dir))})
                    if checks_spec.get("lef_liberty_check"):
                        raise ValueError("批量 LEF 与接口核查需分别运行，避免错误绑定")
                    checks_spec = dict(checks_spec)
                    checks_spec["lef_review"] = {"pairs": batch_pairs}
                elif lef_spec.get("report_json"):
                    report = _json_read(_resolve(lef_spec["report_json"], config_dir))
                    sources = report.get("sources") or {}
                    old_path = (sources.get("old") or {}).get("path")
                    new_path = (sources.get("new") or {}).get("path")
                else:
                    old_path, new_path = lef_spec.get("old_file"), lef_spec.get("new_file")
                base = str((projection.get("scope") or {}).get("base_version") or "")
                if batch_pairs is None and (not old_path or not new_path or not base):
                    raise ValueError("LEF 检查无法与投影基准和目标文件核对")
                actual = (str(_resolve(old_path, config_dir)), str(_resolve(new_path, config_dir))) if batch_pairs is None else None
                valid_pair = False
                for row in projection.get("files") or []:
                    if row.get("view") != "lef" or row.get("identity_status") != "EXACT_RELATIVE_PATH":
                        continue
                    occurrences = row.get("occurrences") or []
                    old = [item.get("source_path") for item in occurrences if item.get("version") == base and item.get("source_path")]
                    new = [item.get("source_path") for item in occurrences if item.get("version") == target and item.get("source_path")]
                    if len(old) == len(new) == 1 and (str(_resolve(old[0], config_dir)), str(_resolve(new[0], config_dir))) == actual:
                        valid_pair = True
                        break
                if batch_pairs is None and not valid_pair:
                    raise ValueError("LEF 检查文件与投影中的唯一基准/目标配对不一致")
            _json_write(evidence_dir / "file_version_projection.json", projection)
        lef_result = None
        runners = {
            "macro_index": lambda spec: _run_macro(spec, config_dir, evidence_dir, ip_id),
            "lef_review": lambda spec: _run_lef_review(spec, config_dir, evidence_dir, ip_id),
        }
        execution_order = {"lef_review": 0, "macro_index": 1, "lef_liberty_check": 2}
        for name, spec in sorted(checks_spec.items(), key=lambda item: execution_order[item[0]]):
            if not isinstance(spec, dict) or spec.get("enabled", True) is False:
                continue
            try:
                if name == "lef_liberty_check":
                    result = _run_lef_liberty(spec, config_dir, evidence_dir, ip_id, library_id, lef_result)
                else:
                    result = runners[name](spec)
                if name == "lef_review" and result.get("schema_version") != "batch_lef_review.v1":
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
                    if name == "lef_review" and result.get("schema_version") == "batch_lef_review.v1":
                        expected = evidence_dir / "lef_review.json"
                    report_path = str(expected or "")
                snapshot_path = evidence_dir / f"{name}.json"
                _json_write(snapshot_path, result)
                check_results[name] = {"selected": True, "status": status,
                                       "result_status": result_status, "result": result,
                                       "report_path": report_path, "result_ref": f"evidence/{name}.json",
                                       "input_spec": dict(spec),
                                       "input_identity": _input_identity(name, spec, result)}
                if name == "lef_review" and batch_pairs is not None:
                    by_id = {pair["pair_id"]: pair["file_key"] for pair in batch_pairs}
                    by_key = {row["file_key"]: row for row in projection["files"]}
                    for pair in result.get("pairs") or []:
                        row = by_key[by_id[pair["pair_id"]]]
                        if pair.get("execution_status") != "COMPLETE":
                            row["comparison"].update({"content_status": "NOT_COMPARED", "semantic_status": "FAILED"})
                            continue
                        comp = pair.get("comparison") or {}
                        names = comp.get("macro_names") or {}
                        changed = bool(comp.get("changes") or names.get("added") or names.get("removed"))
                        semantic = "CHANGED" if changed else ("UNVERIFIED" if comp.get("unverified") else "SAME_WITHIN_SCOPE")
                        row["comparison"].update({"content_status": (comp.get("content") or {}).get("status", "NOT_COMPARED"),
                            "semantic_status": semantic, "unverified": comp.get("unverified") or [],
                            "evidence_refs": [f"evidence/lef_batch/{pair['evidence_ref']}"]})
                    projection["source_snapshot_id"] = projection["snapshot_id"]
                    projection["snapshot_id"] = f"review_projection_{review_id}"
                    projection["summary"]["not_compared"] = sum(row["comparison"]["content_status"] == "NOT_COMPARED" for row in projection["files"])
                    projection["coverage"]["content_comparison"] = "PARTIAL"
                    _json_write(evidence_dir / "file_version_projection.json", projection)
            except Exception as exc:
                check_results[name] = {"selected": True, "status": "FAILED", "result_status": "FAILED",
                                       "error": str(exc), "result": {}, "report_path": "", "result_ref": "",
                                       "input_spec": dict(spec),
                                       "input_identity": _input_identity(name, spec, {})}
        context = {"type": str(ip.get("context_type") or "LIBRARY_REVIEW"),
                   "formal_stage": ip.get("formal_stage"),
                   "formal_snapshot_id": ip.get("formal_snapshot_id"),
                   "target_raw_versions": [str(ip.get("raw_version"))] if ip.get("raw_version") else []}
        reviews.append({"ip": {**ip, "id": ip_id, "library_id": library_id},
                        "review_id": review_id, "generated_at": datetime.now(timezone.utc).isoformat(),
                        "context": context, "context_alignment": _context_alignment(check_results, ip.get("raw_version")),
                        "requested_checks": [name for name, item in check_results.items()
                                                                    if item.get("selected")],
                        "file_version_projection": projection,
                        "checks": check_results, "run_dir": str(run_dir),
                        "library_dir": str(run_dir.parents[1])})
    return reviews


def _check_result(review: dict[str, Any], name: str) -> dict[str, Any]:
    return (review.get("checks") or {}).get(name) or {}


def _input_identity(name: str, spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []

    def add(role: str, path: Any = None, version: Any = None, sha256: Any = None, stage: Any = None) -> None:
        if not any((path, version, sha256, stage)):
            return
        sources.append({key: str(value) for key, value in {
            "role": role, "path": path, "version": version, "sha256": sha256, "stage": stage,
        }.items() if value not in (None, "")})

    if name == "formal_nl":
        add("formal_nl_config", spec.get("config"))
        add("formal_nl_report", spec.get("report_json"))
        add("formal_nl_root", result.get("formal_nl_root"), stage=spec.get("stage"))
        versions, stages = set(), set()
        for stage_name, inventory in (result.get("inventories") or {}).items():
            stages.add(str(stage_name))
            for item in inventory.get("files") or []:
                if item.get("raw_version"):
                    versions.add(str(item["raw_version"]))
        for version in sorted(versions):
            add("formal_raw_source", version=version)
        for stage in sorted(stages):
            add("formal_stage", stage=stage)
    elif name == "macro_index":
        add("filemap", spec.get("filemap_json") or spec.get("root"), version=spec.get("version"))
        result_map = result.get("filemap") or {}
        add("filemap_context", (result_map.get("context") or {}).get("source"))
        versions = {str(item.get("source_version")) for item in result_map.get("files", [])
                    if item.get("source_version")}
        for version in sorted(versions):
            add("macro_source", version=version)
        add("macro_report", spec.get("report_json"))
    elif name == "lef_review":
        if result.get("schema_version") == "batch_lef_review.v1":
            for pair in result.get("pairs") or []:
                for side, source in (pair.get("sources") or {}).items():
                    add(f"lef_{side}:{pair.get('pair_id', '')}", source.get("path"), sha256=source.get("sha256"))
        for side, source in (result.get("sources") or {}).items():
            add(f"lef_{side}", source.get("path"), sha256=source.get("sha256"))
        if not sources:
            add("lef_old", spec.get("old_file"))
            add("lef_new", spec.get("new_file"))
        add("lef_report", spec.get("report_json"))
    elif name == "lef_liberty_check":
        lef_source = result.get("lef_source") or {}
        add("bound_lef", lef_source.get("path"), sha256=lef_source.get("sha256"))
        if not lef_source:
            add("lef_report", spec.get("lef_analysis_json"))
        files = result.get("files") or []
        for item in files:
            add("liberty", item.get("liberty_source"))
        if not files:
            for path in spec.get("liberty_files") or []:
                add("liberty", path)
        add("cross_view_report", spec.get("report_json"))
    versions = sorted({source["version"] for source in sources if source.get("version")})
    stages = sorted({source["stage"] for source in sources if source.get("stage")})
    identity = {"check": name, "sources": sources, "source_versions": versions,
                "formal_stages": stages}
    comparison_scope = spec.get("comparison_scope") if name == "lef_review" else None
    if isinstance(comparison_scope, dict):
        identity["comparison_scope"] = dict(comparison_scope)
    return identity


def _context_alignment(checks: dict[str, dict[str, Any]], target_version: Any = None) -> str:
    selected = [item.get("input_identity") or {} for item in checks.values() if item.get("selected")]
    version_sets = [set(identity.get("source_versions") or []) for identity in selected]
    explicit = [versions for versions in version_sets if versions]
    if not explicit or len(explicit) != len(version_sets):
        return "INDEPENDENT"
    all_versions = set().union(*explicit)
    if target_version and all_versions != {str(target_version)}:
        return "MIXED_EXPLICIT"
    if len(all_versions) > 1:
        return "MIXED_EXPLICIT"
    return "ALIGNED_EXPLICIT"


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
        unmatched = {view: len(values) for view, values in (index.get("unmatched_objects") or {}).items() if values}
        cdl_count = unmatched.pop("cdl", 0)
        unresolved_count = sum(unmatched.values())
        object_summary = f"待核实对象 {unresolved_count} 个"
        if cdl_count:
            object_summary += f"；CDL 子电路范围说明 {cdl_count} 个"
        return f"Macro {macros} 个；未关联文件 {unmatched_files} 个；{object_summary}", \
            "按当前解析事实建立名称关联；未映射不等于交付缺失，索引完成不代表全部视图齐套。"
    if name == "lef_review":
        if result.get("schema_version") == "batch_lef_review.v1":
            pairs = result.get("pairs") or []
            completed = sum(pair.get("execution_status") == "COMPLETE" for pair in pairs)
            return f"LEF 配对 {len(pairs)} 组；执行完成 {completed} 组", "仅核查本次明确选择的文件对；不代表全库通过。"
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


def _load_saved_formal_inventory(output: Path, library_id: str) -> dict[str, Any]:
    """Load the newest successful saved Formal NL report for one IP, without rescanning."""
    formal_dir = output / "formal_nl" / _library_dir(library_id)
    candidates = []
    for priority, pointer_name in enumerate(("latest.json", "latest_check.json")):
        pointer_path = formal_dir / pointer_name
        if not pointer_path.is_file():
            continue
        try:
            pointer = _json_read(pointer_path)
            report_value = str(pointer.get("report_json") or "").strip()
            if not report_value:
                continue
            report_path = Path(report_value).expanduser()
            if not report_path.is_absolute():
                report_path = pointer_path.parent / report_path
            report_path = report_path.resolve()
            if not report_path.is_relative_to(output.resolve()) or not report_path.is_file():
                continue
            report = _json_read(report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if str(report.get("library_id") or "") != library_id:
            continue
        status = str(pointer.get("report_status") or report.get("report_status") or
                     report.get("status") or "").upper()
        if status not in {"COMPLETE", "MATCHED", "DONE", "PASS"}:
            continue
        try:
            report_ref = report_path.relative_to(output.resolve()).as_posix()
        except ValueError:
            continue
        candidates.append((str(pointer.get("generated_at") or report.get("generated_at") or ""),
                           -priority, report, report_ref))
    if not candidates:
        return {}
    generated_at, _priority, report, report_ref = max(candidates, key=lambda item: (item[0], item[1]))
    return {"report": report, "generated_at": generated_at, "report_ref": report_ref,
            "status": str(report.get("report_status") or report.get("status") or "COMPLETE")}


def _inventory_snapshot(review: dict[str, Any]) -> dict[str, Any]:
    saved = review.get("inventory_snapshot")
    if isinstance(saved, dict):
        return saved
    check = _check_result(review, "formal_nl")
    if check.get("selected") and check.get("status") == "COMPLETE":
        return {"report": check.get("result") or {},
                "generated_at": (check.get("result") or {}).get("generated_at") or
                                review.get("generated_at") or "",
                "report_ref": check.get("result_ref") or check.get("report_path") or "",
                "status": check.get("result_status") or "COMPLETE"}
    return {}


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


def _macro_file_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    result = _result(review, "macro_index")
    index = result.get("macro_index") or result
    ip = review.get("ip") or {}
    rows = []
    for macro_name, mappings in (index.get("macros") or {}).items():
        for view in VIEW_NAMES:
            for item in mappings.get(view) or []:
                source_path = item.get("source_path", "")
                rows.append({"IP": ip.get("name") or ip.get("id"),
                             "RAW版本": ip.get("raw_version") or item.get("source_version", ""),
                             "Macro": macro_name, "View": "Liberty" if view == "liberty" else view.upper(),
                             "Corner/线索": item.get("corner") or "未确认",
                             "来源版本": item.get("source_version") or "未标注",
                             "文件名": item.get("file") or Path(source_path).name,
                             "关联证据": item.get("match_basis") or item.get("evidence") or "未说明",
                             "状态": item.get("evidence") or "未确认", "来源路径": source_path})
    return rows


def _engineering_check_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    checks = review.get("checks") or {}
    rows = []
    checklist = list(ENGINEERING_CHECKLIST)
    if "formal_nl" in checks:
        checklist.insert(2, ("正式文件及 RAW 来源（旧版 Review）", ("formal_nl",),
                             "正式目录链接统计已由独立页承担；此行仅保留历史检查记录。"))
    for number, (topic, supporting_checks, limitation) in enumerate(checklist, 1):
        selected = [(name, checks[name]) for name in supporting_checks if name in checks and checks[name].get("selected")]
        if not selected:
            coverage, execution, evidence = "未检查", "未选择相关检查", ""
        else:
            failed = [(name, item) for name, item in selected if item.get("status") != "COMPLETE"]
            if failed:
                coverage = "结果不可用"
                execution = "；".join(f"{name}：{item.get('status')}" for name, item in failed)
            else:
                coverage = "部分覆盖"
                execution = "；".join(f"{name}：执行完成" for name, _ in selected)
            evidence = "；".join(
                f"{name}：{_check_summary(name, item)[0]}" for name, item in selected
                if item.get("status") == "COMPLETE")
        rows.append({"序号": number, "工程检查主题": topic, "工程覆盖": coverage,
                     "本次执行": execution, "本次证据": evidence,
                     "范围或缺口": limitation})
    return rows


def _formal_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    snapshot = _inventory_snapshot(review)
    formal = snapshot.get("report") or {}
    label = ip.get("name") or ip.get("id") or "未命名IP"
    report_ref = snapshot.get("report_ref") or ""
    snapshot_at = snapshot.get("generated_at") or "未记录"
    rows = []
    inventories = formal.get("inventories") or {}
    selected_stage = str(ip.get("formal_stage") or "")
    stages = [(selected_stage, inventories[selected_stage])] if selected_stage in inventories else (
        list(inventories.items()) if not selected_stage else [])
    for stage, inventory in stages:
        for item in inventory.get("files") or []:
            rows.append({"IP": label, "快照时间": snapshot_at, "正式阶段": stage,
                         "相对路径": item.get("relative_path", ""), "View": item.get("view", "other"),
                         "来源RAW版本": item.get("raw_version", "未映射"),
                         "来源路径": item.get("source_path", ""),
                         "正式路径": item.get("published_path", ""),
                         "盘点状态": inventory.get("status", formal.get("status", "未知")),
                         "盘点报告": report_ref})
    if not rows:
        rows.append({"IP": label, "快照时间": snapshot_at, "正式阶段": selected_stage or "未指定",
                     "相对路径": "", "View": "", "来源RAW版本": "", "来源路径": "",
                     "正式路径": "", "盘点状态": "未附盘点" if not snapshot else "无匹配阶段或无文件记录",
                     "盘点报告": report_ref or "未找到该 IP 已保存的正式 NL 盘点报告"})
    return rows


def _raw_inventory_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    label = ip.get("name") or ip.get("id") or "未命名IP"
    snapshot = _inventory_snapshot(review)
    formal_report = snapshot.get("report") or {}
    has_raw_inventory = isinstance(formal_report.get("raw_library"), dict)
    raw_library = formal_report.get("raw_library") or {}
    inventories = raw_library.get("inventories") or {}
    versions = raw_library.get("versions") or []
    snapshot_at = snapshot.get("generated_at") or "未记录"
    report_ref = snapshot.get("report_ref") or ""
    rows = []
    for version in versions:
        version_id = str(version.get("version_id") or "未标版本")
        inventory = inventories.get(version_id) or {}
        files = inventory.get("files") or []
        view_counts = inventory.get("view_counts") or version.get("view_counts") or {}
        status = str(inventory.get("status") or version.get("inventory_status") or "明细未记录")
        file_count = inventory.get("file_count", version.get("file_count", len(files)))
        common = {"IP": label, "快照时间": snapshot_at, "RAW版本": version_id,
                  "RAW根目录": version.get("resolved_path") or version.get("path") or inventory.get("target_path", ""),
                  "版本盘点状态": status, "版本文件数": file_count,
                  "盘点报告": report_ref}
        if files:
            for item in files:
                view = str(item.get("view") or "other")
                rows.append({**common, "View": view, "View文件数": view_counts.get(view, "未统计"),
                             "相对路径": item.get("relative_path", ""),
                             "来源路径": item.get("source_path") or item.get("published_path", "")})
        else:
            rows.append({**common, "View": "", "View文件数": "",
                         "相对路径": "该版本没有文件明细记录", "来源路径": ""})
    if not rows:
        has_snapshot = bool(snapshot)
        rows.append({"IP": label, "快照时间": snapshot_at, "RAW版本": "", "RAW根目录": "",
                     "版本盘点状态": (str(raw_library.get("status") or "无 RAW 版本记录")
                                    if has_snapshot and has_raw_inventory else
                                    ("快照未包含 RAW 多版本盘点" if has_snapshot else "未附盘点")),
                     "版本文件数": "", "View": "", "View文件数": "",
                     "相对路径": ("未发现已登记 RAW 版本" if has_raw_inventory else
                                  ("该盘点报告未包含 RAW 多版本清单" if has_snapshot else "")),
                     "来源路径": "",
                     "盘点报告": report_ref or "未找到该 IP 已保存的 RAW 多版本盘点报告"})
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
    evidence = _check_result(review, "lef_liberty_check").get("result_ref") or ""
    for item in result.get("files") or []:
        axes = item.get("corner_axes") or {}
        summary = item.get("summary") or {}
        inventory = item.get("liberty_inventory") or {}
        comparison = item.get("comparison") or {}
        path = item.get("liberty_source", "")
        corner = axes.get("process_corner") or "未识别"
        conditions = item.get("operating_conditions") or {}
        libraries = sorted(set(item.get("library_names") or []) | set(conditions)) or ["未识别"]
        for library in libraries:
            operating = conditions.get(library) or {}
            for condition_name, values in (operating.items() if operating else [("未提供", {})]):
                values = values if isinstance(values, dict) else {}
                corner_rows.append({"IP": ip.get("name") or ip.get("id"), "Liberty文件": path,
                            "Library": library,
                            "工艺角线索": corner, "RC角线索": axes.get("rc_corner") or "未识别",
                            "条件": condition_name,
                            "Process": _numeric_condition(values.get("process")),
                            "Voltage (V)": _numeric_condition(values.get("voltage")),
                            "Temp (°C)": _numeric_condition(values.get("temperature")),
                            "文件Cell数": inventory.get("cell_count", "未确认"),
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
                            "角标说明": "工艺角仅为名称线索；P/V/T 为 Liberty 声明值，不代表签核确认"})
        for cell in item.get("cells") or []:
            issues = _cell_issues(cell)
            cell_rows.append({"IP": ip.get("name") or ip.get("id"), "Liberty文件": path,
                              "Corner线索": corner, "Cell": cell.get("macro", ""),
                              "LEF同名": True,
                              "信号Pin数": cell.get("signal_pin_checked_count", "未确认"),
                              "PG Pin数": cell.get("power_ground_checked_count", "未确认"),
                              "接口状态": cell.get("status", "未知"),
                              "差异类型": "；".join(name for name, _ in issues),
                              "具体差异": "；".join(f"{name}：{detail}" for name, detail in issues),
                              "证据路径": evidence})
    return corner_rows, cell_rows


def _numeric_condition(value: Any) -> Any:
    if value in (None, ""):
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _cell_issues(cell: dict[str, Any]) -> list[tuple[str, str]]:
    signal = cell.get("signal_pins") or {}
    pg = cell.get("power_ground") or {}
    groups = (
        ("信号Pin缺失", signal.get("missing_in_liberty")),
        ("信号Pin多出", signal.get("extra_in_liberty")),
        ("信号Pin方向不同", signal.get("direction_mismatch")),
        ("PG脚缺失", pg.get("missing_in_liberty")),
        ("PG脚多出", pg.get("extra_in_liberty")),
        ("PG脚类型不同", pg.get("wrong_type")),
        ("PG脚类型未验证", pg.get("unverified_type")),
        ("PG脚名称待确认", pg.get("name_alias_candidates")),
        ("解析范围不足", cell.get("unverified")),
    )
    issues = []
    for label, values in groups:
        if values:
            details = []
            for value in values:
                if isinstance(value, dict):
                    pin_name = value.get("pin") or value.get("lef") or "?"
                    lef_value = value.get("lef_use") or value.get("lef") or "?"
                    liberty_value = value.get("liberty") or value.get("liberty_pg_type") or "?"
                    if value.get("liberty") and value.get("liberty_pg_type"):
                        liberty_value += f" ({value['liberty_pg_type']})"
                    details.append(f"{pin_name} (LEF {lef_value}; Liberty {liberty_value})")
                else:
                    details.append(str(value))
            issues.append((label, ", ".join(details)))
    return issues


def _finding_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    label = ip.get("name") or ip.get("id")
    rows = []
    kind_labels = {"CHANGED": "已确认变化", "MISMATCH": "已确认不一致",
                   "UNVERIFIED": "待核实", "SCOPE_INFO": "范围说明"}

    def add(category: str, object_name: str, finding: str, status: str, action: str,
            evidence: str = "", *, kind: str, count: int = 1) -> None:
        count = max(0, int(count))
        rows.append({"IP": label, "category": category, "kind": kind, "object": object_name,
                     "count": count, "message": finding, "status": status, "action": action,
                     "evidence": evidence, "IP": label, "类别": category, "类型": kind_labels[kind],
                     "对象": object_name, "数量": count, "发现": finding, "状态": status,
                     "建议核对": action, "证据路径": evidence})

    formal = (_result(review, "formal_nl") if _check_result(review, "formal_nl").get("status") == "COMPLETE" else {})
    for item in formal.get("broken_links") or []:
        add("正式链接", item, "正式链接目标不可读或不存在", "需处理", "确认源路径和链接权限",
            formal.get("formal_nl_root", ""), kind="MISMATCH")
    for item in formal.get("ambiguous_versions") or []:
        add("正式来源", item.get("nl_version", ""), "同一阶段发现多个来源目标", "待确认",
            "人工确认应使用的来源", formal.get("formal_nl_root", ""), kind="UNVERIFIED")
    macro_result = (_result(review, "macro_index") if _check_result(review, "macro_index").get("status") == "COMPLETE" else {})
    index = macro_result.get("macro_index") or macro_result
    for item in index.get("unmatched_files") or []:
        add("Macro/View映射", item.get("file", ""), str(item.get("reason", "文件未能关联解析事实")), "证据不足",
            "确认文件是否被支持的解析器覆盖", item.get("file", ""), kind="UNVERIFIED")
    for view, objects in (index.get("unmatched_objects") or {}).items():
        if objects:
            sample_names = ", ".join(str(item.get("name", "")) for item in objects[:5])
            if view == "cdl":
                add("CDL对象范围", "CDL 子电路",
                    f"{len(objects)} 个子电路名称未与 LEF Macro 同名关联；索引没有 CDL 到 Macro 的层级绑定规则。示例：{sample_names}",
                    "范围说明", "如需跨层核查，请提供顶层 Subckt 与 LEF Macro 的对应关系",
                    objects[0].get("file", ""), kind="SCOPE_INFO", count=len(objects))
            else:
                add("Macro/View名称映射", view.upper(),
                    f"{len(objects)} 个解析对象未与 LEF Macro 精确同名关联；示例：{sample_names}", "关联待确认",
                    "名称差异不等于缺交付；按需确认别名或对象层级", objects[0].get("file", ""),
                    kind="UNVERIFIED", count=len(objects))
    lef_check = _check_result(review, "lef_review")
    lef_result = _result(review, "lef_review")
    if lef_result.get("schema_version") == "batch_lef_review.v1":
        for pair in lef_result.get("pairs") or []:
            if pair.get("execution_status") != "COMPLETE":
                add("LEF批量检查", pair.get("pair_id", ""), "文件对执行失败", "证据不足",
                    "核对文件路径和权限后重试", lef_check.get("result_ref") or "", kind="UNVERIFIED")
                continue
            pair_review = {"ip": ip, "checks": {"lef_review": {"selected": True, "status": "COMPLETE",
                "result": {"comparison": pair.get("comparison") or {}},
                "result_ref": f"evidence/lef_batch/{pair.get('evidence_ref', '')}"}}}
            rows.extend(_finding_rows(pair_review))
    lef = lef_result if lef_check.get("status") == "COMPLETE" and lef_result.get("schema_version") != "batch_lef_review.v1" else {}
    comp = lef.get("comparison") or {}
    lef_evidence = _check_result(review, "lef_review").get("result_ref") or ""
    names = comp.get("macro_names") or {}
    for field, values in (("新增Macro", names.get("added")), ("移除Macro", names.get("removed"))):
        for name in values or []:
            add("LEF变化", name, field, "已提取差异", "核对该 Macro 的接入影响",
                lef_evidence, kind="CHANGED")

    def rect_count(value: Any, *, require_layer: bool = False) -> int | None:
        if not isinstance(value, list):
            return None
        for rect in value:
            if not isinstance(rect, dict):
                return None
            if not all(isinstance(rect.get(key), (int, float)) and not isinstance(rect.get(key), bool)
                       for key in ("x1", "y1", "x2", "y2")):
                return None
            if require_layer and not isinstance(rect.get("layer"), str):
                return None
        return len(value)

    for change in comp.get("changes") or []:
        macro = str(change.get("macro") or "未命名 Macro")
        field = str(change.get("field") or "未知字段")
        pin_match = re.fullmatch(r"pins\.(.+)\.rects", field, flags=re.IGNORECASE)
        if pin_match:
            old_count = rect_count(change.get("old"))
            new_count = rect_count(change.get("new"))
            object_name = f"{macro} / Pin {pin_match.group(1)}"
            if old_count is None or new_count is None:
                finding = ("Pin RECT 记录集合发生变化；结构化详情见证据，旧、新记录数无法确认；"
                           "物理区域等价性未验证。")
            else:
                finding = (f"Pin RECT 记录集合发生变化：旧 {old_count} 条 → 新 {new_count} 条；"
                           "物理区域等价性未验证。")
            add("LEF字段变化", object_name, finding, "已提取差异",
                "按需查看归档 LEF 核查证据中的坐标、Layer 与 PORT；本摘要不判断面积变化",
                lef_evidence, kind="CHANGED")
            continue
        if re.fullmatch(r"obs(?:\.rects)?", field, flags=re.IGNORECASE):
            old_count = rect_count(change.get("old"), require_layer=True)
            new_count = rect_count(change.get("new"), require_layer=True)
            if old_count is None or new_count is None:
                finding = ("OBS 几何表示发生变化；结构化详情见证据，记录数无法确认；"
                           "几何覆盖区域等价性未验证。")
            else:
                finding = (f"OBS 几何表示发生变化：旧 {old_count} 条 RECT 记录 → 新 {new_count} 条；"
                           "几何覆盖区域等价性未验证。")
            add("LEF字段变化", macro, finding, "已提取差异",
                "按需查看归档 LEF 核查证据；本摘要不推断覆盖面积变化",
                lef_evidence, kind="CHANGED")
            continue
        add("LEF字段变化", macro,
            f"{field}: {change.get('old')} → {change.get('new')}", "已提取差异",
            "结合对象用途核对变化", lef_evidence, kind="CHANGED")
    for field in comp.get("unverified") or []:
        add("LEF证据范围", field, "该字段未得到完整解析覆盖", "证据不足", "确认是否需要补充针对性解析",
            lef_evidence, kind="UNVERIFIED")
    ll_result = (_result(review, "lef_liberty_check")
                 if _check_result(review, "lef_liberty_check").get("status") == "COMPLETE" else {})
    mismatch_groups: dict[tuple[str, ...], dict[str, Any]] = {}
    ll_evidence = _check_result(review, "lef_liberty_check").get("result_ref") or ""
    unclassified_corner_files = []
    for file_result in (ll_result.get("files") or []):
        summary = file_result.get("summary") or {}
        source = file_result.get("liberty_source", "")
        axes = file_result.get("corner_axes") or {}
        if "process_corner" in axes and not axes.get("process_corner"):
            unclassified_corner_files.append((Path(source).name or "未命名 Liberty", axes))
        mismatch_cells = [cell for cell in file_result.get("cells") or [] if cell.get("status") == "MISMATCH"]
        for cell in mismatch_cells:
            issues = _cell_issues(cell)
            names = tuple(name for name, _ in issues) or ("差异明细未留存",)
            group = mismatch_groups.setdefault(names, {"count": 0, "files": set(), "example": ""})
            group["count"] += 1
            group["files"].add(source)
            if not group["example"]:
                details = "；".join(f"{name}：{detail}" for name, detail in issues)
                group["example"] = f"{Path(source).name} / {cell.get('macro', '未知Cell')} / {details}"
        if summary.get("mismatch_cell_count", 0) > len(mismatch_cells):
            missing_details = summary["mismatch_cell_count"] - len(mismatch_cells)
            group = mismatch_groups.setdefault(("差异明细未留存",), {"count": 0, "files": set(), "example": ""})
            group["count"] += missing_details
            group["files"].add(source)
            if not group["example"]:
                group["example"] = f"{Path(source).name}：{missing_details} 个实例无逐 Cell 明细"
        if summary.get("unverified_cell_count"):
            add("LEF-Liberty证据", Path(file_result.get("liberty_source", "")).name,
                f"{summary['unverified_cell_count']} 个同名 Cell 证据不足", "证据不足",
                "检查解析覆盖与受限语法", ll_evidence,
                kind="UNVERIFIED", count=summary["unverified_cell_count"])
    if unclassified_corner_files:
        examples = []
        for filename, axes in unclassified_corner_files[:5]:
            candidates = axes.get("process_corner_candidates") or []
            clue = f"（候选：{', '.join(map(str, candidates))}）" if candidates else ""
            examples.append(f"{filename}{clue}")
        add("Liberty工艺角", f"{len(unclassified_corner_files)} 个文件",
            f"{len(unclassified_corner_files)} 个 Liberty 文件未能确认工艺角标签；文件名及 PVT 声明只能作为线索。示例：{'；'.join(examples)}",
            "工艺角未确认", "核对项目 Corner 命名映射；未确认前不将这些文件计入指定 Corner 覆盖",
            ll_evidence, kind="UNVERIFIED", count=len(unclassified_corner_files))
    for names, group in mismatch_groups.items():
        add("LEF-Liberty接口", " + ".join(names),
            f"{group['count']} 个文件×Cell 检查实例，涉及 {len(group['files'])} 个 Liberty 文件；例：{group['example']}",
            "已提取差异", "按 Cell、Pin 和原始证据核对；多种差异在同一实例中只计一次",
            ll_evidence, kind="MISMATCH", count=group["count"])
    ll = ll_result
    gap_files = [item for item in ll.get("files", [])
                 if (item.get("summary") or {}).get("lef_only_macro_count")]
    if gap_files:
        counts = sorted({(item.get("summary") or {}).get("lef_only_macro_count") for item in gap_files})
        add("Liberty文件范围", f"{len(gap_files)} 个文件",
            f"所选文件单独未包含 {', '.join(str(value) for value in counts)} 个 LEF Macro 名称；这是输入文件范围差异，不直接表示交付缺失。",
            "范围说明", "若要统计该角的 Cell 并集，请选择同一用途/角的完整 Liberty 文件集合",
            "详见 09-Liberty角 的逐文件路径", kind="SCOPE_INFO",
            count=sum((item.get("summary") or {}).get("lef_only_macro_count", 0) for item in gap_files))
    return rows


def _qa_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    ip = review.get("ip") or {}
    label = ip.get("name") or ip.get("id")
    rows = []
    def evidence(name: str) -> str:
        return str(_check_result(review, name).get("result_ref") or "")
    result_record = review.get("review_result") or {}
    requested = set(result_record.get("requested_checks") or review.get("requested_checks") or [])
    execution_records = result_record.get("checks") or {}
    if not result_record:
        runtime_checks = review.get("checks") or {}
        if not requested:
            requested = {name for name, item in runtime_checks.items() if item.get("selected")}
        execution_records = {
            name: {"execution_status": (item.get("status") or "INCOMPLETE")
                                     if item.get("selected") else "NOT_RUN"}
            for name, item in runtime_checks.items()
        }
    not_run_names = []
    available_checks = set(CHECK_NAMES)
    if "formal_nl" in execution_records or "formal_nl" in (review.get("checks") or {}):
        available_checks.update(LEGACY_CHECK_NAMES)
    for name in sorted(available_checks):
        execution = execution_records.get(name) or {}
        status = str(execution.get("execution_status") or execution.get("status") or "").upper()
        if status == "NOT_RUN" or (not status and name not in requested):
            not_run_names.append(name)
    review_result_ref = str(review.get("review_result_ref") or "")
    rows.append({"IP": label, "问题": "本次有哪些检查没有运行？",
                 "回答": "、".join(CHECK_LABELS[name] for name in not_run_names) if not_run_names else "无，本次列出的检查项均已选择执行。",
                 "证据范围": "未选择或未配置的检查不代表通过或失败；如需结论，先补齐输入并单独执行。",
                 "来源报告": review_result_ref})
    qa_questions = {
        "formal_nl": "正式目录观察到哪些文件类型和数量？",
        "macro_index": "解析并建立了多少个 LEF Macro 索引？",
        "lef_review": "两份指定 LEF 有哪些已确认变化？",
        "lef_liberty_check": "指定 Liberty 与 LEF 的接口核对结果是什么？",
    }
    for check_name, question in qa_questions.items():
        item = _check_result(review, check_name)
        if item.get("selected") and item.get("status") != "COMPLETE":
            execution = "执行失败" if item.get("status") == "FAILED" else "结果不完整"
            detail = item.get("error") or item.get("result_status") or "检查未生成完整结果"
            rows.append({"IP": label, "问题": question,
                         "回答": f"未生成工程结论：{execution}（{detail}）。",
                         "证据范围": "不得将缺少结果解释为数量为零、无差异或检查通过。",
                         "来源报告": evidence(check_name)})
    formal = _result(review, "formal_nl")
    formal_check = _check_result(review, "formal_nl")
    stage, inventory = _formal_inventory(formal, ip.get("formal_stage"))
    if formal_check.get("selected") and formal_check.get("status") == "COMPLETE":
        counts = inventory.get("view_counts") or {}
        rows.append({"IP": label, "问题": "正式目录观察到哪些文件类型和数量？",
                     "回答": "观察到：" + ("；".join(f"{name} {count} 个" for name, count in sorted(counts.items())) or "当前清单为空"),
                     "证据范围": f"阶段 {stage}；目录盘点状态 {inventory.get('status', formal.get('status', '未知'))}。数量为可见路径，不判断是否必需。",
                     "来源报告": evidence("formal_nl")})
        versions = Counter(str(file.get("raw_version")) for file in inventory.get("files") or []
                           if file.get("raw_version"))
        rows.append({"IP": label, "问题": "当前正式文件分别来自哪些 RAW 版本？",
                     "回答": "；".join(f"{version}：{count} 个文件" for version, count in sorted(versions.items())) or "未能从链接目标识别 RAW 版本",
                     "证据范围": "仅统计所选正式阶段可见且来源可追溯的文件；不推断内容新旧。",
                     "来源报告": evidence("formal_nl")})
    macro_check = _check_result(review, "macro_index")
    macro_result = _result(review, "macro_index")
    index = macro_result.get("macro_index") or macro_result
    baseline = index.get("baseline") or {}
    if macro_check.get("selected") and macro_check.get("status") == "COMPLETE":
        rows.append({"IP": label, "问题": "解析并建立了多少个 LEF Macro 索引？",
                     "回答": f"{baseline.get('macro_count', len(index.get('macros') or {}))} 个；LEF 基线状态：{baseline.get('status', '未知')}。",
                     "证据范围": "索引覆盖见 Macro-View 表；文件名/名称关联不代表文件内容确认或交付齐套。",
                     "来源报告": evidence("macro_index")})
        macros = index.get("macros") or {}
        if macros:
            unlinked = {view: sum(not (mappings.get(view) or []) for mappings in macros.values())
                        for view in VIEW_NAMES}
            rows.append({"IP": label, "问题": "哪些 View 尚未关联到 LEF Macro？",
                         "回答": "；".join(f"{view.upper()}：{count} 个 Macro 未关联" for view, count in unlinked.items() if count) or "本次索引的视图均有关联记录",
                         "证据范围": "未关联只是当前索引范围的名称/解析关联状态，不等于必需文件缺失。",
                         "来源报告": evidence("macro_index")})
    lef_check = _check_result(review, "lef_review")
    lef = _result(review, "lef_review")
    if lef_check.get("selected") and lef.get("schema_version") == "batch_lef_review.v1":
        pairs = lef.get("pairs") or []
        complete_count = sum(pair.get("execution_status") == "COMPLETE" for pair in pairs)
        rows.append({"IP": label, "问题": "本次批量 LEF 检查了哪些文件？",
                     "回答": f"共选择 {len(pairs)} 组；执行完成 {complete_count} 组，失败 {len(pairs) - complete_count} 组。",
                     "证据范围": "各文件对的结果和解析限制分别记录；未选择文件未检查。", "来源报告": evidence("lef_review")})
    if lef_check.get("selected") and lef_check.get("status") == "COMPLETE" and lef.get("schema_version") != "batch_lef_review.v1":
        comp = lef.get("comparison") or {}
        names = comp.get("macro_names") or {}
        content = comp.get("content") or {}
        rows.append({"IP": label, "问题": "两份指定 LEF 有哪些已确认变化？",
                     "回答": f"文件字节状态：{content.get('status', '未确认')}；Macro新增 {len(names.get('added') or []) if names.get('added') is not None else '未确认'}，移除 {len(names.get('removed') or []) if names.get('removed') is not None else '未确认'}，字段差异 {len(comp.get('changes') or [])}。",
                     "证据范围": "仅限所选的旧/新 LEF 文件及当前 Parser 覆盖字段。", "来源报告": evidence("lef_review")})
        changed_macros = sorted({str(change.get("macro")) for change in comp.get("changes") or [] if change.get("macro")})
        added = names.get("added") or []
        removed = names.get("removed") or []
        rows.append({"IP": label, "问题": "目标 LEF 比基准改了哪些 Macro？",
                     "回答": f"新增：{', '.join(added[:8]) or '无'}；移除：{', '.join(removed[:8]) or '无'}；字段变化对象：{', '.join(changed_macros[:8]) or '无'}"
                             + ("；其余见 04-关注项" if len(added) + len(removed) + len(changed_macros) > 24 else ""),
                     "证据范围": "仅限两份指定 LEF；字段变化不自动代表功能影响。",
                     "来源报告": evidence("lef_review")})
    ll_check = _check_result(review, "lef_liberty_check")
    ll = _result(review, "lef_liberty_check")
    if ll_check.get("selected") and ll_check.get("status") == "COMPLETE":
        summary = ll.get("summary") or {}
        corners = ", ".join(summary.get("recognized_corners") or []) or "未识别"
        scope_gap_files = summary.get("files_with_scope_gaps", "未统计")
        rows.append({"IP": label, "问题": "指定 Liberty 与 LEF 的接口核对结果是什么？",
                     "回答": f"逐文件检查 {summary.get('liberty_file_count', len(ll.get('files') or []))} 个 Liberty；角标线索 {corners}；接口不一致文件 {summary.get('files_with_mismatches', '未统计')}，证据不足文件 {summary.get('files_with_unverified', '未统计')}，单文件名称范围差异 {scope_gap_files} 个。",
                     "证据范围": "单文件名称范围差异不等于缺交付；接口结论仅限输入 Liberty 与指定 LEF 的同名对象、当前解析器支持字段；不判断时序性能或放行。",
                     "来源报告": evidence("lef_liberty_check")})
        rows.append({"IP": label, "问题": "本次 Liberty 识别到哪些工艺角线索？",
                     "回答": corners + f"；未识别工艺角文件 {summary.get('files_with_unknown_process_corner', '未统计')} 个。",
                     "证据范围": "角标由文件名/Library 名提取，不代表已确认 Signoff 条件。",
                     "来源报告": evidence("lef_liberty_check")})
        mismatch_groups = [row for row in _finding_rows(review) if row["类别"] == "LEF-Liberty接口"]
        if mismatch_groups:
            rows.append({"IP": label, "问题": "哪些接口差异应先复核？",
                         "回答": "；".join(f"{row['对象']}：{row['数量']} 个文件×Cell 实例" for row in mismatch_groups[:5]),
                         "证据范围": "同一 Cell 的多个差异合并为一个检查实例；定位见 10-Liberty单元。",
                         "来源报告": evidence("lef_liberty_check")})
        unknown = summary.get("files_with_incomplete_signal_pin_coverage", 0) + summary.get("files_with_incomplete_power_ground_coverage", 0)
        if unknown:
            rows.append({"IP": label, "问题": "哪些接口内容仍因解析覆盖不足无法确认？",
                         "回答": f"信号 Pin 覆盖不完整文件 {summary.get('files_with_incomplete_signal_pin_coverage', 0)} 个；PG Pin 覆盖不完整文件 {summary.get('files_with_incomplete_power_ground_coverage', 0)} 个。",
                         "证据范围": "仅说明本次解析证据限制；不是已确认缺陷。",
                         "来源报告": evidence("lef_liberty_check")})
    if not rows:
        rows.append({"IP": label, "问题": "本次执行了哪些检查？", "回答": "未选择检查。",
                     "证据范围": "没有产生工程检查结论。", "来源报告": ""})
    return rows


def _input_brief(item: dict[str, Any]) -> tuple[str, str]:
    identity = item.get("input_identity") or {}
    sources = identity.get("sources") or []
    roles = Counter(str(source.get("role") or "来源") for source in sources)
    source_text = "；".join(f"{role} {count}" for role, count in roles.items()) or "未记录来源"
    versions = identity.get("source_versions") or []
    if versions:
        source_text += "；版本 " + ", ".join(str(version) for version in versions[:5])
    selections = []
    for key, value in (item.get("input_spec") or {}).items():
        if key == "enabled" or value in (None, ""):
            continue
        if isinstance(value, (list, tuple)):
            selections.append(f"{key} {len(value)} 项")
        elif isinstance(value, (str, Path)):
            selections.append(f"{key}: {Path(value).name if '/' in str(value) else value}")
        else:
            selections.append(str(key))
    return source_text, "；".join(selections) or "见证据 JSON"


def _source_revision() -> dict[str, Any]:
    """Identify the code revision without claiming a dirty tree is reproducible."""
    repository = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True,
                                capture_output=True, text=True, timeout=2).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                    cwd=repository, check=True, capture_output=True, text=True,
                                    timeout=2).stdout.strip())
        return {"commit": commit, "working_tree_dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": "UNAVAILABLE", "working_tree_dirty": None}


def _input_scope(review: dict[str, Any]) -> dict[str, Any]:
    context = review.get("context") or {}
    versions = context.get("target_raw_versions") or []
    if not versions and context.get("raw_version"):
        versions = [context.get("raw_version")]
    raw_versions = [str(item.get("id") or item.get("version") or "") if isinstance(item, dict)
                    else str(item) for item in versions]
    checks = []
    source_count = 0
    for name, item in (review.get("checks") or {}).items():
        if not item.get("selected"):
            continue
        identity = item.get("input_identity") or {}
        sources = identity.get("sources") or []
        source_count += len(sources)
        check_scope = {"name": name, "source_count": len(sources),
                       "source_roles": sorted({str(source.get("role") or "") for source in sources if source.get("role")}),
                       "source_versions": identity.get("source_versions") or [],
                       "formal_stages": identity.get("formal_stages") or []}
        if isinstance(identity.get("comparison_scope"), dict):
            check_scope["comparison_scope"] = identity["comparison_scope"]
        checks.append(check_scope)
    snapshot = _inventory_snapshot(review)
    snapshot_report = snapshot.get("report") or {}
    formal_snapshot = {
        "status": str(snapshot.get("status") or "NOT_FOUND"),
        "generated_at": str(snapshot.get("generated_at") or ""),
        "report_ref": str(snapshot.get("report_ref") or ""),
        "stages": sorted(str(stage) for stage in (snapshot_report.get("inventories") or {})),
    }
    return {"checks": checks, "target_raw_versions": raw_versions,
            "formal_stage": str(context.get("formal_stage") or ""), "source_count": source_count,
            "formal_inventory_snapshot": formal_snapshot}


def _input_scope_label(scope: dict[str, Any]) -> str:
    check_names = [CHECK_LABELS.get(str(item.get("name") or ""), str(item.get("name") or "未记录"))
                   for item in scope.get("checks") or []]
    parts = ["检查：" + ("、".join(check_names) or "无")]
    if scope.get("target_raw_versions"):
        parts.append("RAW：" + "、".join(scope["target_raw_versions"]))
    if scope.get("formal_stage"):
        parts.append("正式阶段：" + str(scope["formal_stage"]))
    parts.append(f"输入来源 {int(scope.get('source_count') or 0)} 项")
    for check in scope.get("checks") or []:
        comparison = check.get("comparison_scope") or {}
        if comparison.get("kind") == "INDEPENDENT_CROSS_IP":
            parts.append("LEF：独立跨 IP 文件对比，不代表所选库的版本变化")
    snapshot = scope.get("formal_inventory_snapshot") or {}
    if snapshot.get("generated_at"):
        stages = "、".join(snapshot.get("stages") or []) or "阶段未列明"
        parts.append(f"单 IP 正式盘点快照：{snapshot['generated_at']}（{stages}）")
    else:
        parts.append("单 IP 正式盘点快照：未找到")
    return "；".join(parts)


def build_workbook_model(reviews: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Flatten independently-scoped IP results into human-reviewable sheet rows."""
    from .display_labels import projection_label
    selected_names = {name for review in reviews for name, item in (review.get("checks") or {}).items()
                      if item.get("selected")}
    sheet_names = ["00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项"]
    if any(review.get("file_version_projection") for review in reviews):
        sheet_names.insert(1, "文件版本矩阵")
    if "macro_index" in selected_names:
        sheet_names.extend(["05-MacroView", "06-MacroView文件"])
    sheet_names.append("07-正式文件")
    if "lef_review" in selected_names:
        sheet_names.append("08-LEF宏")
    if "lef_liberty_check" in selected_names:
        sheet_names.extend(["09-Liberty角", "10-Liberty单元"])
    sheet_names.append("RAW文件清单")
    model = {name: [] for name in sheet_names}
    for review in reviews:
        ip = review.get("ip") or {}
        label = ip.get("name") or ip.get("id") or "未命名IP"
        projection = review.get("file_version_projection") or {}
        if projection:
            scope = projection.get("scope") or {}
            for file in projection.get("files") or []:
                comparison = file.get("comparison") or {}
                formal = file.get("formal_usage") or {}
                def unique_source(version):
                    matches = [item.get("source_path") for item in file.get("occurrences") or []
                               if item.get("version") == version]
                    return matches[0] if version and len(matches) == 1 else ""
                model["文件版本矩阵"].append({"IP": label, "View": file.get("view"), "文件键": file.get("file_key"),
                    "文件名": file.get("display_name"), "基准版本": scope.get("base_version"),
                    "目标版本": scope.get("target_version"), "基准路径": unique_source(scope.get("base_version")),
                    "目标路径": unique_source(scope.get("target_version")), "基准存在性": projection_label(comparison.get("base_presence"), "presence"),
                    "目标存在性": projection_label(comparison.get("target_presence"), "presence"), "身份状态": projection_label(file.get("identity_status"), "identity"),
                    "内容状态": projection_label(comparison.get("content_status"), "content"), "语义状态": projection_label(comparison.get("semantic_status"), "semantic"),
                    "正式阶段": formal.get("stage"), "正式来源": formal.get("source_path"),
                    "批准状态": projection_label(formal.get("approved_effective_status"), "approval"),
                    "RAW 覆盖": projection_label((projection.get("coverage") or {}).get("raw_inventory"), "coverage"),
                    "快照 ID": projection.get("snapshot_id"), "投影证据": "evidence/file_version_projection.json"})
        selected = [(name, item) for name, item in (review.get("checks") or {}).items() if item.get("selected")]
        complete = sum(item.get("status") == "COMPLETE" for _, item in selected)
        failed = sum(item.get("status") == "FAILED" for _, item in selected)
        formal = _result(review, "formal_nl")
        stage, _inventory = _formal_inventory(formal, ip.get("formal_stage"))
        index = _result(review, "macro_index").get("macro_index") or _result(review, "macro_index")
        macro_count = (index.get("baseline") or {}).get("macro_count", len(index.get("macros") or {})) if _check_result(review, "macro_index") else "未检查"
        quality = _review_summary(review)["quality_assessment"]
        input_scope = review.get("input_scope") or _input_scope(review)
        revision = review.get("source_revision") or {}
        model["00-概览"].append({"IP": label, "库标识": ip.get("library_id") or ip.get("id", ""),
                                 "RAW版本": ip.get("raw_version", "未指定"), "正式阶段": stage or ip.get("formal_stage", "未检查"),
                                 "已选检查": "、".join(CHECK_LABELS.get(name, name) for name, _ in selected) or "无",
                                 "执行完成项": complete, "执行失败项": failed,
                                 "质量判断": quality["label"], "Macro数": macro_count,
                                 "报告结论": quality["boundary"],
                                 "报告生成时间": review.get("generated_at") or "未记录",
                                 "源提交": revision.get("commit") or "未记录",
                                 "工作区有改动": "是" if revision.get("working_tree_dirty") is True else
                                     ("否" if revision.get("working_tree_dirty") is False else "未知"),
                                 "输入范围": _input_scope_label(input_scope)})
        for name, item in selected:
            summary, scope = _check_summary(name, item)
            execution = {"COMPLETE": "执行完成", "INCOMPLETE": "结果不完整", "FAILED": "执行失败"}.get(
                item.get("status"), "状态未知")
            identity_brief, input_brief = _input_brief(item)
            model["02-执行记录"].append({"IP": label, "检查": CHECK_LABELS.get(name, name), "执行状态": execution,
                                      "上下文关系": {"INDEPENDENT": "输入关联未确认", "MIXED_EXPLICIT": "输入来自多个版本", "ALIGNED_EXPLICIT": "输入版本一致"}.get(review.get("context_alignment", "INDEPENDENT"), "输入关联待核实"),
                                      "结果摘要": summary, "范围说明": scope,
                                      "输入身份": identity_brief,
                                      "输入范围": input_brief,
                                      "报告路径": item.get("result_ref") or ""})
        model["01-工程检查"].extend(_engineering_check_rows(review))
        model["03-问答"].extend(_qa_rows(review))
        model["04-关注项"].extend(_finding_rows(review))
        model["07-正式文件"].extend(_formal_rows(review))
        model["RAW文件清单"].extend(_raw_inventory_rows(review))
        if _check_result(review, "macro_index").get("selected"):
            model["05-MacroView"].extend(_macro_rows(review))
            model["06-MacroView文件"].extend(_macro_file_rows(review))
        if _check_result(review, "lef_review").get("selected"):
            model["08-LEF宏"].extend(_lef_rows(review))
        if _check_result(review, "lef_liberty_check").get("selected"):
            corners, cells = _liberty_rows(review)
            model["09-Liberty角"].extend(corners)
            model["10-Liberty单元"].extend(cells)
    return model


def run(config: dict[str, Any], out_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    run_started_at = datetime.now(timezone.utc).isoformat()
    source_revision = _source_revision()
    reviews = run_review(config, out_dir)
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    row_counts: Counter[str] = Counter()
    overview_rows = []
    for review in reviews:
        ip_context = review.get("ip") or {}
        library_id = str(ip_context.get("library_id") or ip_context.get("id") or "")
        if not _inventory_snapshot(review) and library_id:
            review["inventory_snapshot"] = _load_saved_formal_inventory(output, library_id)
        review["source_revision"] = source_revision
        review["input_scope"] = _input_scope(review)
        run_dir = Path(review["run_dir"])
        library_dir = Path(review["library_dir"])
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
                                       "input_identity": item.get("input_identity") or {},
                                       "error": item.get("error")}
        summary = _review_summary(review)
        review_record = {"schema_version": "review_result.v1",
                         "library_id": (review.get("ip") or {}).get("library_id"),
                         "review_id": review.get("review_id"), "generated_at": review.get("generated_at"),
                         "context": review.get("context"),
                         "context_alignment": review.get("context_alignment", "INDEPENDENT"),
                         "source_revision": source_revision,
                         "input_scope": review["input_scope"],
                         "requested_checks": requested,
                         "execution_status": "COMPLETE" if complete else ("FAILED" if any(
                             item.get("status") == "FAILED" for item in checks.values()) else "INCOMPLETE"),
                         "quality_status": summary["quality_assessment"]["status"],
                         "checks": serialized_checks,
                         "summary": summary,
                         "reports": {"xlsx": "ip_review.xlsx"}}
        if review.get("file_version_projection"):
            review_record["file_version_projection"] = {
                "snapshot_id": review["file_version_projection"]["snapshot_id"],
                "result_ref": "evidence/file_version_projection.json"}
        review["review_result"] = review_record
        review["review_result_ref"] = "review_result.json"
        model = build_workbook_model([review])
        for name, rows in model.items():
            row_counts[name] += len(rows)
        review["execution_status"] = review_record["execution_status"]
        review["quality_status"] = review_record["quality_status"]
        review["summary"] = summary
        revision_label = source_revision.get("commit") or "UNAVAILABLE"
        if source_revision.get("working_tree_dirty") is True:
            revision_label += "（工作区有改动）"
        scope_note = (f"IP：{review_record['library_id']}；Review：{review_record['review_id']}；"
                      f"生成：{review_record['generated_at']}；源提交：{revision_label}；"
                      f"{_input_scope_label(review_record['input_scope'])}；"
                      "仅汇总本 IP、本次选择的检查。未选择不代表通过。NL/RAW盘点表复用该 IP 最近一次成功的正式目录快照；导出不重扫，也不验证源目录此后是否变化。")
        workbook_path = run_dir / "ip_review.xlsx"
        workbook_tmp = run_dir / f".ip_review.{review_record['review_id']}.tmp.xlsx"
        try:
            export_review_excel(model, workbook_tmp, scope_note=scope_note)
            if not workbook_tmp.is_file() or workbook_tmp.stat().st_size == 0:
                raise OSError("Excel 导出未产生有效工作簿")
            workbook_tmp.replace(workbook_path)
        finally:
            workbook_tmp.unlink(missing_ok=True)
        _json_write_atomic(run_dir / "review_result.json", review_record)
        _publish_cli_attempt_if_idle(library_dir / "latest_attempt.json", {
            "task_id": review_record["review_id"],
            "review_id": review_record["review_id"],
            "library_id": review_record["library_id"],
            "status": "COMPLETE",
            "execution_status": review_record["execution_status"],
            "quality_status": review_record["quality_status"],
            "requested_checks": requested,
            "submitted_at": run_started_at,
            "started_at": run_started_at,
            "finished_at": review_record["generated_at"],
            "summary": summary,
        })
        latest_xlsx_ref = ""
        if complete and _publish_latest_workbook(workbook_path, library_dir, review_record["review_id"],
                                                 review_record["generated_at"]):
            latest_xlsx_ref = "latest.xlsx"
        latest_ref = None
        if (review.get("ip") or {}).get("publish_latest") and complete:
            latest = {"schema_version": "review_latest.v1", "library_id": review_record["library_id"],
                      "review_id": review_record["review_id"],
                      "review_result_ref": f"runs/{review_record['review_id']}/review_result.json",
                      "xlsx_ref": f"runs/{review_record['review_id']}/ip_review.xlsx",
                      "generated_at": review_record["generated_at"]}
            latest_path = library_dir / "latest.json"
            if _write_latest_if_newer(latest_path, latest):
                latest_ref = str(latest_path)
        overview_rows.append({"library_id": review_record["library_id"],
                              "name": (review.get("ip") or {}).get("name") or review_record["library_id"],
                              "review_id": review_record["review_id"],
                              "generated_at": review_record["generated_at"],
                              "execution_status": review_record["execution_status"],
                              "requested_checks": requested, "summary": review_record["summary"],
                              "source_revision": source_revision, "input_scope": review_record["input_scope"],
                              "xlsx_href": "../" + (run_dir / "ip_review.xlsx").relative_to(output).as_posix(),
                              "current_xlsx_href": "../" + (run_dir / "ip_review.xlsx").relative_to(output).as_posix(),
                              "latest_xlsx_href": "../" + (library_dir / "latest.xlsx").relative_to(output).as_posix()
                              if latest_xlsx_ref else "",
                              "latest": bool(latest_ref)})
        review["review_result_path"] = str(run_dir / "review_result.json")
        review["xlsx_path"] = str(run_dir / "ip_review.xlsx")
        review["latest_path"] = latest_ref or ""
    try:
        refresh_ip_overview(config, output, current_attempts=overview_rows)
    except Exception as exc:
        print(f"WARNING: Review 已生成，但 IP 总览未同步：{exc}", file=sys.stderr)
    return reviews, dict(row_counts)


def _timestamp_key(value: Any) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def refresh_ip_overview(registry: dict[str, Any], output_dir: str | Path, *,
                        current_attempts: list[dict[str, Any]] | None = None) -> Path:
    """Refresh the static overview from registry and persisted reports only.

    This function never runs a checker. The optional current_attempts are the
    just-finished CLI attempt records; persisted active workbench task snapshots
    always take precedence until the workbench writes its terminal state.
    """
    output = Path(output_dir).expanduser().resolve()
    page = output / "ip_checks" / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    rows = _overview_rows_for_registry(registry, output, current_attempts or [])
    content = render_overview(rows, simulation=(str(registry.get("environment") or "").upper() == "SIMULATION"
                                                or bool(registry.get("simulation"))))
    temporary = page.with_name(f".{page.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        if temporary.stat().st_size == 0:
            raise OSError("IP 总览临时文件为空")
        os.replace(temporary, page)
    finally:
        temporary.unlink(missing_ok=True)
    return page


def _overview_rows_for_registry(config: dict[str, Any], output: Path,
                                current_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_by_library = {str(item.get("library_id")): item for item in current_rows}
    registry = config.get("registry_ips") or config.get("ips") or []
    rows = []
    for index, ip in enumerate(registry):
        library_id = str(ip.get("library_id") or ip.get("id") or ip.get("name") or f"IP_{index + 1}")
        library_dir = output / "libraries" / _library_dir(library_id)
        latest_result, latest_workbook = _latest_complete_run(library_dir)
        complete_id = str(latest_result.get("review_id") or "")
        workbook_href = ""
        if latest_workbook and latest_workbook.is_file():
            stable_workbook = library_dir / "latest.xlsx"
            pointer_path = library_dir / "latest_workbook.json"
            try:
                stable_pointer = _json_read(pointer_path) if pointer_path.is_file() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                stable_pointer = {}
            if (stable_workbook.is_file() and str(stable_pointer.get("review_id") or "") == complete_id):
                workbook_href = "../" + stable_workbook.relative_to(output).as_posix()
            else:
                workbook_href = "../" + latest_workbook.relative_to(output).as_posix()
        attempt_path = library_dir / "latest_attempt.json"
        try:
            saved_attempt = _json_read(attempt_path) if attempt_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            saved_attempt = {}
        current = current_by_library.get(library_id) or {}
        saved_status = str(saved_attempt.get("status") or "")
        current_time = str(current.get("generated_at") or "")
        saved_time = str(saved_attempt.get("finished_at") or saved_attempt.get("submitted_at") or "")
        active_saved_attempt = saved_status in {"QUEUED", "PENDING", "RUNNING"}
        current_is_newer = bool(current and _timestamp_key(current_time) > _timestamp_key(saved_time))
        if active_saved_attempt:
            attempt = saved_attempt
        elif current_is_newer:
            attempt = {
                "status": "COMPLETE",
                "execution_status": current.get("execution_status") or "INCOMPLETE",
                "task_id": current.get("review_id") or "",
                "review_id": current.get("review_id") or "",
                "generated_at": current_time,
                "requested_checks": current.get("requested_checks") or [],
            }
        else:
            attempt = saved_attempt
        if not attempt and latest_result:
            # A persisted complete Review is valid attempt evidence when an older
            # workspace has no separate task snapshot for that execution.
            attempt = {"status": latest_result.get("execution_status") or "COMPLETE",
                       "execution_status": latest_result.get("execution_status") or "COMPLETE",
                       "review_id": complete_id, "generated_at": latest_result.get("generated_at"),
                       "requested_checks": latest_result.get("requested_checks") or []}
        attempt_time = (attempt.get("finished_at") or attempt.get("updated_at")
                        or attempt.get("started_at") or attempt.get("submitted_at")
                        or attempt.get("generated_at") or "")
        attempt_status = str(attempt.get("status") or attempt.get("execution_status") or "NOT_RUN")
        attempt_id = str(attempt.get("task_id") or attempt.get("review_id") or "")

        input_paths = []
        for check in (latest_result.get("checks") or {}).values():
            for source in ((check.get("input_identity") or {}).get("sources") or []):
                path = source.get("path")
                if path and path not in input_paths:
                    input_paths.append(path)
        context = latest_result.get("context") or {}
        last_complete = ({
            "id": complete_id,
            "time": latest_result.get("generated_at") or "",
            "requested_checks": latest_result.get("requested_checks") or [],
            "checks": latest_result.get("checks") or {},
            "summary": latest_result.get("summary") or {},
            "context": context,
            "input_paths": input_paths,
            "source_revision": latest_result.get("source_revision") or {},
            "input_scope": latest_result.get("input_scope") or {},
            "xlsx_href": workbook_href,
        } if complete_id else {})
        rows.append({
            "ip": {"id": ip.get("id") or library_id,
                   "name": ip.get("name") or ip.get("id") or library_id,
                   "library_id": library_id, "vendor": ip.get("vendor") or "未分组",
                   "group": ip.get("middle_path") or ip.get("group") or ""},
            "last_attempt": {"status": attempt_status, "execution_status": attempt.get("execution_status") or "",
                             "id": attempt_id, "time": attempt_time,
                             "checks": attempt.get("requested_checks") or []},
            "last_complete": last_complete,
        })
    return rows


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    findings = _finding_rows(review)
    counts = {}
    for kind in ("CHANGED", "MISMATCH", "UNVERIFIED", "SCOPE_INFO"):
        selected = [item for item in findings if item.get("kind") == kind]
        counts[kind] = {"finding_records": len(selected),
                        "affected_objects": sum(item.get("count", 0) for item in selected)}
    selected = [item for item in (review.get("checks") or {}).values() if item.get("selected")]
    selected_names = {name for name, item in (review.get("checks") or {}).items() if item.get("selected")}
    known_checks = set(CHECK_NAMES)
    if "formal_nl" in (review.get("checks") or {}) or "formal_nl" in ((review.get("review_result") or {}).get("checks") or {}):
        known_checks.update(LEGACY_CHECK_NAMES)
    not_run_checks = sorted(known_checks - selected_names)
    incomplete_checks = [item for item in selected if item.get("status") != "COMPLETE"]
    if not selected:
        quality_status, quality_label = "NOT_ASSESSED", "未形成质量结论"
    elif incomplete_checks:
        quality_status, quality_label = "INCOMPLETE", "检查未完整"
    elif counts["MISMATCH"]["affected_objects"]:
        quality_status, quality_label = "ISSUES_FOUND", "发现已确认不一致"
    elif counts["UNVERIFIED"]["affected_objects"]:
        quality_status, quality_label = "REVIEW_REQUIRED", "存在待核实项"
    elif counts["CHANGED"]["affected_objects"]:
        quality_status, quality_label = "CHANGES_FOUND", "发现已确认变化"
    else:
        quality_status, quality_label = "NO_FINDINGS_WITHIN_SCOPE", "本次范围未发现问题"
    quality_assessment = {
        "status": quality_status,
        "label": quality_label,
        "not_run_checks": not_run_checks,
        "boundary": ("仅评价本次已选检查与输入范围；本次未运行：" +
                     ("、".join(CHECK_LABELS[name] for name in not_run_checks) if not_run_checks else "无") +
                     "。不等同于 IP 全面质量通过或正式发布放行。"),
        "incomplete_check_count": len(incomplete_checks),
    }
    kind_order = {"MISMATCH": 0, "UNVERIFIED": 1, "CHANGED": 2, "SCOPE_INFO": 3}
    primary_findings = []
    candidates = sorted((item for item in findings if item.get("kind") in {"MISMATCH", "UNVERIFIED", "CHANGED"}),
                        key=lambda item: (kind_order.get(item.get("kind"), 9), -int(item.get("count") or 0)))
    for item in candidates[:3]:
        primary_findings.append({"kind": item.get("kind"), "category": item.get("category"),
                                 "label": item.get("object") or item.get("message") or "发现项",
                                 "count": max(0, int(item.get("count") or 0))})
    return {"counts": counts, "finding_records": len(findings),
            "affected_objects": sum(item.get("count", 0) for item in findings),
            "confirmed_changes": counts["CHANGED"]["affected_objects"],
            "confirmed_mismatches": counts["MISMATCH"]["affected_objects"],
            "unverified": counts["UNVERIFIED"]["affected_objects"],
            "scope_notes": counts["SCOPE_INFO"]["affected_objects"],
            "primary_findings": primary_findings,
            "quality_assessment": quality_assessment}


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
