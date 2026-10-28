"""Deterministic plan for the checks supported by the current IP evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .file_version_projection import reproject_projection


ENGINEERING_TOPICS = (
    ("raw_inventory", "RAW 文件盘点", "逐个已登记 RAW 交付盘点支持的 View 和文件路径；数量不代表齐套。"),
    ("file_delta", "文件更新与清单 Delta", "文件提供关系与逐文件内容比较分开记录；单侧文件不能形成内容变化结论。"),
    ("formal_source", "正式 NL 来源", "只读核对明确阶段、链接状态和 RAW 来源；不代表 EDA 工具实际加载或放行。"),
    ("macro_provenance", "Macro 清单、来源与变化", "当前 Macro Index 与 LEF 变化证据；跨交付关联不完整时标部分覆盖。"),
    ("view_completeness", "Macro 六类文件齐套", "需要项目必需 View 规则；候选名称关联不能判定齐套。"),
    ("corner_coverage", "Signoff Corner 覆盖", "角标/PVT 仅是观察线索；没有期望 Corner 规则时不判齐套。"),
    ("lef_delta", "LEF 物理属性 Delta", "仅对唯一配对 LEF 和解析器支持字段给出差异。"),
    ("cross_view", "接口与跨 View 一致性", "只核对明确绑定的 LEF–Liberty 输入；未选 Verilog/CDL 不代表一致。"),
    ("other_view", "其他 View 内部对象检查", "CDL/Verilog 等仅限现有解析覆盖；GDS/DB 当前主要是文件级证据。"),
    ("doc_delta", "文档更新 Delta", "当前没有文档正文差异检查器；文件清单观察不等于正文比较。"),
)


def build_applicable_plan(projection: dict[str, Any], version_roots: dict[str, str], *,
                          formal_state: dict[str, Any] | None = None) -> dict[str, Any]:
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

    if base and target:
        projection = reproject_projection(projection, base_version=base, target_version=target)
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

    if target and version_roots.get(target) and Path(version_roots[target]).is_dir():
        checks["macro_index"] = {"root": version_roots[target], "version": target,
                                 "library_id": str(projection.get("library_id") or "")}
        row("macro_provenance", "计划执行", "检查最新交付 Macro 与 View 关联",
            "单次 Index 不等于跨交付 Macro 更新判断", "evidence/macro_index.json", ("macro_index",))
        row("other_view", "计划执行", "检查支持的解析对象并记录其余文件线索",
            "GDS/DB 等内部对象仍未验证", "evidence/macro_index.json", ("macro_index",))
    else:
        row("macro_provenance", "未执行", "无结论", "最新交付顺序或目录不可确认")
        row("other_view", "未执行", "无结论", "没有可用的最新 RAW 目录")
    row("view_completeness", "未执行", "无结论", "尚未配置项目必需 View 规则")

    target_lefs = []
    target_liberties = []
    for item in projection.get("files") or []:
        occurrences = item.get("occurrences") or []
        matches = [record.get("source_path") for record in occurrences
                   if record.get("version") == target and record.get("source_path")]
        if len(matches) != 1:
            continue
        if item.get("view") == "lef":
            target_lefs.append(matches[0])
        elif item.get("view") == "liberty":
            target_liberties.append(matches[0])
    if len(target_lefs) == 1 and len(target_liberties) == 1:
        checks["lef_liberty_check"] = {
            "lef_file": target_lefs[0], "liberty_files": target_liberties,
            "source_versions": {"lef": target, "liberties": {target_liberties[0]: target}},
        }
        row("cross_view", "计划执行", "唯一 LEF 与唯一 Liberty 输入已绑定",
            "仅覆盖所选 LEF/Liberty 文件；不覆盖 Verilog/CDL", "evidence/lef_liberty_check.json",
            ("lef_liberty_check",))
        row("corner_coverage", "部分覆盖", "仅观察所选 Liberty 的 Corner/PVT 线索",
            "未配置期望 Corner 集合，不能判定齐套", "evidence/lef_liberty_check.json",
            ("lef_liberty_check",))
    elif target_lefs and target_liberties:
        reason = f"发现 {len(target_lefs)} 个 LEF、{len(target_liberties)} 个 Liberty；输入组合待确认"
        row("cross_view", "未执行", "无结论", reason)
        row("corner_coverage", "未执行", "无结论", "未配置期望 Corner 集合；Liberty 输入组合也待确认")
    else:
        row("cross_view", "未执行", "无结论", "最新交付未同时发现 LEF 和 Liberty")
        row("corner_coverage", "未执行", "无结论", "未配置期望 Corner 集合")
    row("doc_delta", "未执行", "无结论", "当前没有文档正文差异检查器")

    return {"scope": scope, "checks": checks, "content_keys": content_keys,
            "engineering_checklist": [rows[key] for key, _, _ in ENGINEERING_TOPICS],
            "projection": projection}
