from __future__ import annotations

from typing import Any, Mapping

from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, SUMMARY_ONLY_TYPES

P0_REVIEW_TYPES = {"lef", "cdl", "spice", "sp"}
P1_REVIEW_TYPES = {"sdc", "upf", "cpf", "waiver", "ibis", "pwl", "snp", "touchstone", "cpm"}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _package_type(version: Mapping[str, Any]) -> str:
    return str(version.get("package_type") or version.get("version_type") or version.get("stage") or "UNKNOWN").upper()


def _base_full_version(version: Mapping[str, Any]) -> str | None:
    diff = _as_mapping(version.get("diff"))
    lineage = _as_mapping(version.get("lineage"))
    for key in ["base_full_version", "base_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("cumulative_base_version"), diff.get("base_version"), lineage.get("base_candidate")]:
        if value:
            return str(value)
    return None


def _node_package_type(version: Mapping[str, Any]) -> str:
    pkg = _package_type(version)
    version_id = str(version.get("version_id") or version.get("version") or "").lower()
    stage = str(version.get("stage") or "").lower()
    if pkg in {"FULL_PACKAGE", "FULL"} or version_id.startswith(("stable_", "final_", "initial_")) or stage in {"stable", "final", "initial"}:
        return "full"
    if pkg == "HOTFIX" or stage == "ad-hoc":
        return "hotfix"
    if pkg in {"DOC_UPDATE", "DOC_ONLY"}:
        return "doc"
    if pkg in {"PARTIAL_UPDATE", "PARTIAL"} or version_id.startswith(("patch_", "update_")) or version.get("update_scope"):
        return "partial"
    return "unknown"


def resolve_review_base(version: Mapping[str, Any], library: Mapping[str, Any] | None = None) -> dict[str, str]:
    del library
    diff = _as_mapping(version.get("diff"))
    lineage = _as_mapping(version.get("lineage"))
    explicit = (
        version.get("explicit_base_version")
        or diff.get("explicit_base_version")
        or lineage.get("explicit_base_version")
    )
    if explicit:
        return {"base_ref": "explicit", "base_version": str(explicit), "base_source": "catalog_recorded_base"}
    for key in ["current_effective", "current_effective_ref", "latest_effective_ref"]:
        value = version.get(key) or diff.get(key) or lineage.get(key)
        if value and not isinstance(value, bool):
            return {"base_ref": "current_effective", "base_version": str(value), "base_source": key}
    previous = version.get("previous_effective_version") or version.get("parent_version") or lineage.get("parent_candidate")
    if previous:
        return {"base_ref": "previous_effective", "base_version": str(previous), "base_source": "previous_effective_version"}
    diff_base = diff.get("base_version")
    diff_base_source = str(diff.get("base_source") or diff.get("base_version_source") or "").lower()
    diff_kind = str(diff.get("kind") or diff.get("diff_kind") or "").lower()
    if diff_base and (diff_base_source in {"explicit", "current_effective"} or diff_kind == "current_library_diff"):
        base_ref = "current_effective" if diff_base_source == "current_effective" or diff_kind == "current_library_diff" else "explicit"
        return {"base_ref": base_ref, "base_version": str(diff_base), "base_source": f"diff.base_version:{diff_base_source or diff_kind}"}
    full_base = _base_full_version(version)
    if full_base:
        return {"base_ref": "base_full", "base_version": str(full_base), "base_source": "base_full_version"}
    adjacent = diff.get("adjacent_old_version")
    if adjacent:
        return {"base_ref": "adjacent_fallback", "base_version": str(adjacent), "base_source": "adjacent_old_version"}
    if diff_base:
        return {"base_ref": "recorded_base", "base_version": str(diff_base), "base_source": "diff.base_version:fallback"}
    return {"base_ref": "NEEDS_BASE_CONFIRM", "base_version": "", "base_source": "missing_base"}


def classify_review_lane(file_type: str) -> dict[str, str]:
    key = str(file_type or "").lower()
    if key in SUMMARY_ONLY_TYPES:
        return {"lane": "Summary-only", "hint": "摘要级审查；默认不生成文件级 Diff 命令"}
    if key in BINARY_METADATA_ONLY_TYPES:
        return {"lane": "Metadata-only", "hint": "metadata-only 审查；默认不生成文件级 Diff 命令"}
    if key in P0_REVIEW_TYPES:
        return {"lane": "P0", "hint": "建议优先做文件级 Diff"}
    if key in P1_REVIEW_TYPES:
        return {"lane": "P1", "hint": "建议定向审查"}
    return {"lane": "Review", "hint": "按需人工检查"}


def comparison_semantics_for_package(package_type: str, node_kind: str = "") -> dict[str, str]:
    package = str(package_type or "").upper()
    node_type = str(node_kind or "").lower()
    if package in {"PARTIAL_UPDATE", "PARTIAL", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"} or node_type in {"partial", "hotfix", "doc"}:
        return {
            "comparison_scope": "incremental",
            "compare_strategy": "incremental compare",
            "delete_semantics": "out_of_scope_missing",
        }
    return {
        "comparison_scope": "full",
        "compare_strategy": "full compare",
        "delete_semantics": "real_delete",
    }
