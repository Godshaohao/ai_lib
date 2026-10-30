"""Deterministic plan for the checks supported by the current IP evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .file_version_projection import reproject_projection
from .lef_liberty_check import _pvt_process_corner


ENGINEERING_TOPICS = (
    ("raw_inventory", "RAW 文件盘点", "逐个已登记 RAW 交付盘点支持的 View 和文件路径；数量不代表齐套。"),
    ("file_delta", "文件更新与清单 Delta", "文件提供关系与逐文件内容比较分开记录；单侧文件不能形成内容变化结论。"),
    ("formal_source", "正式 NL 来源", "只读核对明确阶段、链接状态和 RAW 来源；不代表 EDA 工具实际加载或放行。"),
    ("macro_provenance", "Macro 清单、来源与变化", "当前 Macro Index 与 LEF 变化证据；跨交付关联不完整时标部分覆盖。"),
    ("view_completeness", "View 清单与齐套观察", "盘点并展示当前 View；没有项目必需 View 规则时不判定齐套。"),
    ("corner_coverage", "Signoff Corner 覆盖", "角标/PVT 仅是观察线索；没有期望 Corner 规则时不判齐套。"),
    ("lef_delta", "LEF 物理属性 Delta", "仅对唯一配对 LEF 和解析器支持字段给出差异。"),
    ("cross_view", "接口与跨 View 一致性", "只核对明确绑定的 LEF–Liberty 输入；未选 Verilog/CDL 不代表一致。"),
    ("other_view", "其他 View 内部对象检查", "CDL/Verilog 等仅限现有解析覆盖；GDS/DB 当前主要是文件级证据。"),
)


def _pvt_condition_summary(item: dict[str, Any], library: str, condition: str,
                          values: dict[str, Any]) -> str:
    process = _pvt_process_corner(Path(item.get("source_path") or ""), str(library), str(condition)) or "未识别"
    return (f"{Path(item.get('source_path') or '').name}/{library}/{condition} "
            f"Process={process} V={values.get('voltage', '?')} T={values.get('temperature', '?')}")


def build_applicable_plan(projection: dict[str, Any], version_roots: dict[str, str], *,
                          formal_state: dict[str, Any] | None = None,
                          current_file_set: dict[str, Any] | None = None,
                          interface_groups: dict[str, Any] | None = None,
                          current_filemap_json: str = "") -> dict[str, Any]:
    """Choose only unambiguous checks; leave unavailable or rule-bound work explicit."""
    order = projection.get("version_order") or {}
    ordered = [str(value) for value in order.get("ordered_ids") or []]
    known = order.get("status") == "KNOWN" and bool(ordered)
    target = ordered[-1] if known else ""
    base = ordered[-2] if known and len(ordered) > 1 else ""
    scope = {"base_version": base, "target_version": target}
    checks: dict[str, dict[str, Any]] = {}
    rows: dict[str, dict[str, Any]] = {}

    def row(item_id: str, execution: str, result: str, reason: str = "", evidence: str = "",
            check_names: tuple[str, ...] = ()) -> None:
        topic = next(name for key, name, _ in ENGINEERING_TOPICS if key == item_id)
        rows[item_id] = {"id": item_id, "topic": topic, "execution": execution,
                         "result": result, "reason": reason, "evidence": evidence,
                         "check_names": list(check_names)}

    coverage = projection.get("coverage") or {}
    raw_status = str(coverage.get("raw_inventory") or "NOT_AVAILABLE")
    row("raw_inventory", "已执行" if raw_status == "COMPLETE" else "部分覆盖",
        f"盘点 {len(projection.get('files') or [])} 个文件记录",
        "" if raw_status == "COMPLETE" else "一个或多个交付不可读、未登记或盘点不完整",
        "evidence/file_version_projection.json")

    if target:
        projection = reproject_projection(projection, base_version=base, target_version=target)
    if base and target:
        content_keys = [str(item.get("file_key") or "") for item in projection.get("files") or []
                        if item.get("comparison", {}).get("delivery_relation") == "READY_TO_COMPARE"
                        and item.get("capabilities", {}).get("content_comparable")]
        row("file_delta", "计划执行" if content_keys else "部分覆盖",
            f"{len(content_keys)} 个唯一文件对可比较",
            "" if content_keys else "没有形成可确认的双边文件对；单侧文件只保留提供关系",
            "evidence/file_version_projection.json", ("projection_content",))
        lef_pairs = []
        for item in projection.get("files") or []:
            if (item.get("view") != "lef" or item.get("identity_status") != "EXACT_RELATIVE_PATH"
                    or item.get("comparison", {}).get("delivery_relation") != "READY_TO_COMPARE"):
                continue
            occurrences = item.get("occurrences") or []
            old = [row.get("source_path") for row in occurrences if row.get("version") == base and row.get("source_path")]
            new = [row.get("source_path") for row in occurrences if row.get("version") == target and row.get("source_path")]
            if len(old) == 1 and len(new) == 1:
                key = str(item.get("file_key") or "")
                pair_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
                lef_pairs.append({"pair_id": pair_id, "file_key": key,
                                  "old_file": old[0], "new_file": new[0],
                                  "source_versions": {"old": base, "new": target}})
        if lef_pairs:
            checks["lef_review"] = {"pairs": lef_pairs}
            row("lef_delta", "计划执行", f"{len(lef_pairs)} 对唯一配对 LEF",
                "", "evidence/lef_review.json", ("lef_review",))
        else:
            row("lef_delta", "未执行", "无结论", "两次交付没有唯一配对的 LEF")
    else:
        content_keys = []
        reason = "交付顺序未确认" if not known else "只有一个已登记交付"
        row("file_delta", "未执行", "无结论", f"{reason}，不猜测 Base/Target")
        row("lef_delta", "未执行", "无结论", f"{reason}，无法确认 LEF 差异范围")

    formal = formal_state or {}
    formal_stages = list(formal.get("stages") or [])
    if formal.get("status") == "COMPLETE" and len(formal_stages) == 1:
        row("formal_source", "已执行", f"正式阶段 {formal_stages[0]} 已盘点",
            "链接来源不等于工具实际加载来源", "formal_nl/overview/latest.json")
    elif formal_stages:
        row("formal_source", "部分覆盖", f"发现 {len(formal_stages)} 个正式阶段",
            "阶段不唯一；需要用户确认正式阶段", "formal_nl/overview/latest.json")
    else:
        row("formal_source", "未执行", "无结论",
            formal.get("reason") or "未配置或未发现可用正式目录")

    current_files = (current_file_set or {}).get("files") or []
    if current_file_set and current_filemap_json and current_files:
        checks["macro_index"] = {"filemap_json": current_filemap_json,
                                 "library_id": str(projection.get("library_id") or ""),
                                 "current_file_set": current_file_set}
        file_set_status = str(current_file_set.get("status") or "PARTIAL")
        row("macro_provenance", "计划执行" if file_set_status == "COMPLETE" else "部分覆盖",
            f"检查当前文件集中的 {len(current_files)} 个文件及 Macro/View 关联",
            "逐文件来源见当前文件集；不把未确认的历史副本自动并入" if file_set_status != "COMPLETE"
            else "单次 Index 不等于跨交付 Macro 更新判断",
            "evidence/macro_index.json", ("macro_index",))
        row("other_view", "计划执行" if file_set_status == "COMPLETE" else "部分覆盖",
            "检查当前文件集中现有解析器支持的对象并保留其他 View 文件线索",
            "GDS/DB 等内部对象仍未验证", "evidence/macro_index.json", ("macro_index",))
    elif target and version_roots.get(target) and Path(version_roots[target]).is_dir():
        checks["macro_index"] = {"root": version_roots[target], "version": target,
                                 "library_id": str(projection.get("library_id") or "")}
        row("macro_provenance", "计划执行", "检查最新交付 Macro 与 View 关联",
            "单次 Index 不等于跨交付 Macro 更新判断", "evidence/macro_index.json", ("macro_index",))
        row("other_view", "计划执行", "检查支持的解析对象并记录其余文件线索",
            "GDS/DB 等内部对象仍未验证", "evidence/macro_index.json", ("macro_index",))
    else:
        row("macro_provenance", "未执行", "无结论", "最新交付顺序或目录不可确认")
        row("other_view", "未执行", "无结论", "没有可用的最新 RAW 目录")
    if "macro_index" in checks:
        row("view_completeness", "计划执行", "将盘点并展示当前文件集的 View 与数量",
            "未配置项目必需 View 规则时只报告观察结果，不判断齐套",
            "evidence/macro_index.json", ("macro_index",))
    else:
        row("view_completeness", "未执行", "无结论", "没有可盘点的 RAW 文件清单")

    if interface_groups and interface_groups.get("groups"):
        groups = interface_groups["groups"]
        observed = interface_groups.get("observed_liberties") or []
        process_counts: dict[str, int] = {}
        rc_counts: dict[str, int] = {}
        for item in observed:
            axes = item.get("corner_axes") or {}
            for counts, axis in ((process_counts, "process_corner"), (rc_counts, "rc_corner")):
                label = axes.get(axis)
                if label:
                    counts[str(label)] = counts.get(str(label), 0) + 1
        pvt_values = []
        for item in observed:
            for library, conditions in (item.get("operating_conditions") or {}).items():
                for name, values in (conditions or {}).items():
                    if isinstance(values, dict):
                        pvt_values.append(_pvt_condition_summary(item, library, name, values))
        checks["lef_liberty_check"] = {
            "groups": groups, "candidate_status": interface_groups.get("status"),
            "ambiguous_objects": interface_groups.get("ambiguous_objects") or [],
            "unresolved": interface_groups.get("unresolved") or [],
            "observed_liberties": interface_groups.get("observed_liberties") or [],
        }
        group_state = str(interface_groups.get("status") or "PARTIAL")
        row("cross_view", "计划执行" if group_state == "COMPLETE" else "部分覆盖",
            f"按 Macro/Cell 关联执行 {len(groups)} 个 LEF 文件组",
            (f"{len(interface_groups.get('ambiguous_objects') or [])} 个对象存在歧义；其余可确认对象继续检查"
             if group_state != "COMPLETE" else "只检查当前最新文件集中对象匹配的 Liberty，不混入被替代历史文件"),
            "evidence/lef_liberty_check.json", ("lef_liberty_check",))
        liberty_paths = {str(item.get("source_path") or "") for item in observed}
        process_text = "、".join(f"{name}×{count}" for name, count in sorted(process_counts.items())) or "未识别"
        rc_text = "、".join(f"{name}×{count}" for name, count in sorted(rc_counts.items())) or "未识别"
        pvt_text = "；".join(pvt_values[:6]) or "未声明"
        if len(pvt_values) > 6:
            pvt_text += f"；另有 {len(pvt_values) - 6} 项"
        row("corner_coverage", "已执行" if group_state == "COMPLETE" else "部分覆盖",
            f"当前 {len(liberty_paths)} 个 Liberty；工艺角 {process_text}；RC角 {rc_text}；PVT：{pvt_text}",
            "未配置期望 Corner 集合；只报告观察项，不判断齐套",
            "evidence/lef_liberty_check.json", ("lef_liberty_check",))
    elif interface_groups and any(item.get("view") == "liberty"
                                  for item in (current_file_set or {}).get("files") or []):
        reason = "；".join(item.get("reason", "") for item in interface_groups.get("unresolved") or [])
        checks["lef_liberty_check"] = {
            "groups": [], "candidate_status": interface_groups.get("status"),
            "ambiguous_objects": interface_groups.get("ambiguous_objects") or [],
            "unresolved": interface_groups.get("unresolved") or [],
            "observed_liberties": interface_groups.get("observed_liberties") or [],
        }
        row("cross_view", "部分覆盖", "没有可唯一关联的 LEF–Liberty 对象组",
            reason or "当前文件集中没有可确认的同名 Macro/Cell 对象", "evidence/current_file_set.json")
        observed = interface_groups.get("observed_liberties") or []
        corners = sorted({str((item.get("corner_axes") or {}).get("process_corner") or "未识别")
                          for item in observed})
        pvt_values = []
        for item in observed:
            for library, conditions in (item.get("operating_conditions") or {}).items():
                for name, values in (conditions or {}).items():
                    if isinstance(values, dict):
                        pvt_values.append(_pvt_condition_summary(item, library, name, values))
        row("corner_coverage", "部分覆盖", f"观察 {len(observed)} 个 Liberty；工艺角：{'、'.join(corners) or '无'}；"
            f"PVT：{'；'.join(pvt_values[:6]) or '未声明'}",
            "未发现可执行接口关联组；未配置期望 Corner 集合，不判断齐套",
            "evidence/current_file_set.json")
    else:
        row("cross_view", "未执行", "无结论", "当前文件集中没有可用的 LEF 和 Liberty 输入")
        row("corner_coverage", "未执行", "无结论", "当前文件集中没有可观察的 Liberty 文件")
    return {"scope": scope, "checks": checks, "content_keys": content_keys,
            "engineering_checklist": [rows[key] for key, _, _ in ENGINEERING_TOPICS],
            "projection": projection, "current_file_set": current_file_set,
            "interface_groups": interface_groups}
