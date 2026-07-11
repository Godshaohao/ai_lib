from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from lib_guard.effective.pointer import (
    approval_integrity_for_manifest,
    default_pointer_path_for_effective,
    effective_identity_for_manifest,
    safe_name,
    sha256_file,
    write_current_pointer,
)
from lib_guard.cli_commands.common import render_impacted_catalog_html
from lib_guard.plan.engine import build_plan_from_window, execute_plan, load_plan, plan_path_for, save_plan
from lib_guard.render.impact import impacts_for_versions
from lib_guard.window.resolver import find_library, read_json, resolve_review_window, write_json


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _quote(value: Any) -> str:
    text = str(value)
    if not text or any(ch.isspace() for ch in text):
        return repr(text)
    return text


def _run_commands(commands: list[list[str]]) -> int:
    from lib_guard.cli import main as cli_main

    for command in commands:
        print("python -m lib_guard.cli " + " ".join(_quote(item) for item in command))
        code = int(cli_main(command))
        if code != 0:
            return code
    return 0


def _run_one_command(command: list[str]) -> int:
    from lib_guard.cli import main as cli_main

    print("python -m lib_guard.cli " + " ".join(_quote(item) for item in command))
    return int(cli_main(command))


def _window_versions(window: dict[str, Any]) -> list[str]:
    versions: list[str] = []
    for item in window.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version") or item.get("version_id") or "")
        if version and version not in versions:
            versions.append(version)
    return versions


def _plan_followup_commands(library: str, window: dict[str, Any] | None = None) -> dict[str, Any]:
    lib = _quote(library)
    state = str((window or {}).get("state") or "").upper()
    candidate = (window or {}).get("candidate_effective") if isinstance((window or {}).get("candidate_effective"), dict) else {}
    if state == "EMPTY" or not candidate:
        return {
            "confirm_command": "无需执行：当前没有新的待审查版本",
            "relation_fix_commands": [],
            "accept_command": "无需执行：没有 candidate effective，不能接受新有效版",
            "review_hint": "当前只有已识别的基线版本；新版本到来后再运行 lg next。",
        }
    return {
        "confirm_command": f"lg next {lib} --apply",
        "relation_fix_commands": [
            f"lg mark {lib} <VERSION> --type FULL",
            f"lg library override {lib} <FIX_VERSION> --package-type PARTIAL_UPDATE --base-full <BASE_FULL_VERSION> --compare-default full_baseline --note 'confirmed fix baseline'",
        ],
        "accept_command": f"lg next {lib} --accept --by <USER> --note 'review passed'",
        "review_hint": "先确认 candidate/base/scan_versions；关系不对先运行 mark 或 library override，再重新执行 lg next --plan-only。",
    }


def _base_source_label(source: str) -> str:
    labels = {
        "current_effective_pointer": "当前Effective指针",
        "catalog_summary": "Catalog已确认引用",
        "latest_full_fallback": "自动回退到最新FULL",
        "first_catalog_version": "自动回退到首个版本",
    }
    return labels.get(source, source or "未知")


def _base_review(window: dict[str, Any]) -> dict[str, Any]:
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    source = str(base.get("source") or "")
    target = str(base.get("target") or "")
    fallback_sources = {"latest_full_fallback", "first_catalog_version"}
    unknowns = _unknown_package_versions(window)
    return {
        "状态": "需确认" if source in fallback_sources or unknowns else "已确认",
        "当前Base": target or "未识别",
        "来源": _base_source_label(source),
        "完整包基线": base.get("base_full") or "",
        "确认说明": "自动回退结果不能当作事实；如不符合预期，请用 mark/library override 修正。"
        if source in fallback_sources
        else "来自已接受指针或人工 catalog 信息。",
    }


def _version_review_table(window: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    target = str(base.get("target") or "")
    if target.startswith("raw:"):
        rows.append(
            {
                "版本名": target.split(":", 1)[1],
                "类型猜测": "FULL",
                "Catalog类型": "FULL_PACKAGE" if base.get("source") != "first_catalog_version" else "",
                "当前角色": "当前Base",
                "是否需确认": "Base来源需确认" if base.get("source") in {"latest_full_fallback", "first_catalog_version"} else "否",
            }
        )
    for item in window.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        guessed = str(item.get("guessed_kind") or kind or "")
        rows.append(
            {
                "版本名": item.get("version") or item.get("version_id") or "",
                "类型猜测": guessed,
                "Catalog类型": item.get("package_type") or "",
                "当前角色": item.get("role") or "",
                "是否需确认": "是" if item.get("requires_package_type_confirmation") else "否",
                "Scan状态": item.get("scan_status") or "",
            }
        )
    return rows


def _suggested_fix_commands(library: str, window: dict[str, Any]) -> list[str]:
    lib = _quote(library)
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    base_full = str(base.get("base_full") or "")
    commands: list[str] = []
    for item in window.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version") or item.get("version_id") or "")
        if not version:
            continue
        kind = str(item.get("kind") or "").upper()
        guessed = str(item.get("guessed_kind") or "").upper()
        suggested = guessed if kind == "UNKNOWN" else kind
        if item.get("requires_package_type_confirmation"):
            if suggested == "FULL":
                commands.append(f"lg mark {lib} {_quote(version)} --type FULL --note 'confirmed full package'")
            elif suggested == "FIX":
                commands.append(f"lg mark {lib} {_quote(version)} --type FIX --note 'confirmed fix package'")
            else:
                commands.append(f"lg mark {lib} {_quote(version)} --type FULL|FIX --note 'confirmed package type'")
        if suggested == "FIX" and base_full:
            commands.append(
                f"lg library override {lib} {_quote(version)} --package-type PARTIAL_UPDATE "
                f"--base-full {_quote(base_full)} --previous-effective {_quote(base_full)} "
                "--compare-default full_baseline --note 'manual confirmed base'"
            )
    if not commands and window.get("state") == "EMPTY":
        return []
    if not commands:
        commands.append(f"lg window {lib}")
    return commands


def _flow_review(window: dict[str, Any]) -> dict[str, Any]:
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    base_full = str(candidate.get("base_full") or base.get("base_full") or "")
    overlays = [str(item) for item in candidate.get("overlays", []) or [] if str(item)]
    rule = str(candidate.get("rule") or "")
    if window.get("state") == "EMPTY":
        return {
            "流程类型": "无新版本",
            "判断": "当前库没有新的待审查版本；无需执行 FULL 或增量接入。",
            "最新FULL": base_full or "-",
            "增量包": "-",
        }
    if overlays:
        flow_type = "FULL流程 + 增量流程"
        detail = (
            f"系统选择最新FULL：{base_full or '-'} 作为完整基线，"
            f"再叠加增量包：{', '.join(overlays)}。"
        )
    else:
        flow_type = "FULL流程"
        detail = f"系统选择最新FULL：{base_full or '-'} 作为候选有效版；没有需要叠加的增量包。"
    if rule:
        detail += f" 规则：{rule}。"
    return {
        "流程类型": flow_type,
        "判断": detail,
        "最新FULL": base_full or "-",
        "增量包": ", ".join(overlays) or "-",
    }


def _review_window_summary(library: str, window: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_review": _base_review(window),
        "flow_review": _flow_review(window),
        "版本选择表": _version_review_table(window),
        "建议修正命令": _suggested_fix_commands(library, window),
    }


def _library_cli_name(row: dict[str, Any]) -> str:
    return str(row.get("formal_library_id") or row.get("library_name") or row.get("library_id") or "")


def _worklist_row(library: str, window: dict[str, Any]) -> dict[str, Any]:
    base = _base_review(window)
    unknowns = _unknown_package_versions(window)
    state = str(window.get("state") or "")
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    new_versions = [str(item) for item in window.get("new_versions", []) or [] if str(item)]
    if not new_versions:
        new_versions = [
            str(item.get("version") or item.get("version_id") or "")
            for item in window.get("items", []) or []
            if isinstance(item, dict) and str(item.get("version") or item.get("version_id") or "")
        ]
    source = str((window.get("base_effective") or {}).get("source") or "")
    if state == "EMPTY":
        status = "无新版本"
        action = "无需执行"
    elif unknowns:
        status = "需确认包类型"
        action = f"lg next {_quote(library)} --fix"
    elif source == "first_catalog_version":
        status = "需确认Base"
        action = f"lg next {_quote(library)} --fix"
    else:
        status = "可执行" if window.get("commands") else "可接受"
        action = (
            f"lg next {_quote(library)} --apply"
            if status == "可执行"
            else f"lg next {_quote(library)} --accept --by <USER> --note 'review passed'"
        )
    return {
        "库": library,
        "状态": status,
        "当前Base": base.get("当前Base") or "-",
        "Base来源": base.get("来源") or "-",
        "新版本": ", ".join(new_versions) or "-",
        "Candidate": candidate.get("effective_id") or "-",
        "需扫描": len(window.get("scan_versions", []) or []),
        "建议动作": action,
    }


def _format_text_table(rows: list[dict[str, Any]], headers: list[str]) -> str:
    if not rows:
        return "无版本记录"
    widths: dict[str, int] = {}
    for header in headers:
        widths[header] = max(len(header), *(len(str(row.get(header) or "")) for row in rows))
    lines = ["  ".join(header.ljust(widths[header]) for header in headers)]
    lines.append("  ".join("-" * widths[header] for header in headers))
    for row in rows:
        lines.append("  ".join(str(row.get(header) or "").ljust(widths[header]) for header in headers))
    return "\n".join(lines)


def _format_window_text(library: str, window: dict[str, Any]) -> str:
    if all(key in window for key in ["base_review", "版本选择表", "建议修正命令"]):
        summary = {
            "base_review": window.get("base_review") or {},
            "flow_review": window.get("flow_review") or _flow_review(window),
            "版本选择表": window.get("版本选择表") or [],
            "建议修正命令": window.get("建议修正命令") or [],
        }
    else:
        summary = _review_window_summary(library, window)
    base = summary["base_review"]
    flow = summary.get("flow_review") or {}
    version_rows = summary["版本选择表"]
    version_table = _format_text_table(
        version_rows,
        ["版本名", "类型猜测", "Catalog类型", "当前角色", "是否需确认", "Scan状态"],
    )
    if not version_rows and window.get("state") == "EMPTY":
        version_table = "当前没有新的待审查版本；当前Base已来自有效版本指针。"
    fix_commands = summary["建议修正命令"]

    lines = [
        f"库：{library}",
        "",
        "基线确认",
        f"  状态：{base.get('状态')}",
        f"  当前Base：{base.get('当前Base')}",
        f"  来源：{base.get('来源')}",
        f"  完整包基线：{base.get('完整包基线') or '-'}",
        f"  说明：{base.get('确认说明')}",
        "",
        "流程判断",
        f"  类型：{flow.get('流程类型') or '-'}",
        f"  最新FULL：{flow.get('最新FULL') or '-'}",
        f"  增量包：{flow.get('增量包') or '-'}",
        f"  说明：{flow.get('判断') or '-'}",
        "",
        "版本选择表",
        version_table,
        "",
        "建议修正命令",
    ]
    if fix_commands:
        lines.extend(f"  {command}" for command in fix_commands)
    else:
        lines.append("  无需修正")
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    compare = window.get("compare") if isinstance(window.get("compare"), dict) else {}
    lines.extend(
        [
            "",
            "当前组合",
            f"  Candidate：{candidate.get('effective_id') or '-'}",
            f"  Base Full：{candidate.get('base_full') or '-'}",
            f"  Overlay：{', '.join(str(x) for x in candidate.get('overlays', []) or []) or '-'}",
            f"  Compare：{compare.get('old') or '-'} -> {compare.get('new') or '-'}",
        ]
    )
    warnings = [str(item) for item in window.get("warnings", []) or [] if str(item)]
    if warnings:
        lines.append("")
        lines.append("警告")
        lines.extend(f"  {item}" for item in warnings)
    return "\n".join(lines)


def _format_intake_plan_text(library: str, output: dict[str, Any]) -> str:
    lines = [
        _format_window_text(
            library,
            {
                "base_review": output.get("base_review") or {},
                "flow_review": output.get("flow_review") or {},
                "版本选择表": output.get("版本选择表") or [],
                "建议修正命令": output.get("建议修正命令") or [],
                "candidate_effective": output.get("candidate_effective") or {},
                "compare": output.get("compare") or {},
                "warnings": output.get("warnings") or [],
                "state": output.get("state") or "",
            },
        ),
        "",
        "执行计划",
        f"  状态：{output.get('plan_state') or output.get('state') or ''}",
        f"  下一步：{output.get('next_action') or ''}",
        f"  需扫描版本：{', '.join(str(item) for item in output.get('scan_versions', []) or []) or '无'}",
        f"  确认执行：{'无需执行' if output.get('state') == 'EMPTY' else output.get('confirm_command') or ''}",
        f"  接受窗口：{'无需执行' if output.get('state') == 'EMPTY' else output.get('accept_command') or ''}",
    ]
    blocked = str(output.get("blocked_reason") or "")
    if blocked:
        lines.extend(["", "阻塞原因", f"  {blocked}"])
    return "\n".join(lines)


def _format_worklist_text(output: dict[str, Any]) -> str:
    summary = output.get("summary", {}) or {}
    rows = output.get("rows", []) or []
    counts = "，".join(f"{key} {value}" for key, value in summary.items()) or "无"
    return "\n".join(
        [
            "接入工作清单",
            f"  汇总：{counts}",
            "",
            _format_text_table(rows, ["库", "状态", "当前Base", "Base来源", "新版本", "Candidate", "需扫描", "建议动作"]),
        ]
    )


def _unknown_package_versions(window: dict[str, Any]) -> list[str]:
    unknowns: list[str] = []
    for version in (window.get("candidate_effective") or {}).get("unknown_package_versions", []) or []:
        text = str(version or "")
        if text and text not in unknowns:
            unknowns.append(text)
    for item in window.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").upper() == "UNKNOWN" or item.get("requires_package_type_confirmation"):
            text = str(item.get("version") or item.get("version_id") or "")
            if text and text not in unknowns:
                unknowns.append(text)
    return unknowns


def _compare_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value):
            return value
    return ""


def _target_label(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["spec", "label"]:
            if value.get(key):
                return str(value.get(key))
        target_type = str(value.get("type") or value.get("target_type") or "")
        target_id = str(value.get("id") or value.get("target_id") or "")
        if target_type and target_id:
            return f"{target_type}:{target_id}"
        return target_id or str(value)
    return str(value or "")


def _target_digest(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["manifest_sha256", "sha256", "digest"]:
            if value.get(key):
                return str(value.get(key))
    return ""


def _target_effective_digest(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["effective_digest", "identity_digest"]:
            if value.get(key):
                return str(value[key])
    return ""


def _validate_accept_compare(window: dict[str, Any], compare_manifest_path: Path) -> None:
    compare = window.get("compare") if isinstance(window.get("compare"), dict) else {}
    expected_old = str(compare.get("old") or (window.get("base_effective") or {}).get("target") or "")
    expected_new = str(compare.get("new") or "")
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    if not expected_new and candidate.get("effective_id"):
        expected_new = f"effective:{candidate.get('effective_id')}"

    manifest = read_json(compare_manifest_path, {}) or {}
    actual_old_raw = _compare_value(manifest, "old_target", "old")
    actual_new_raw = _compare_value(manifest, "new_target", "new")
    actual_old = _target_label(actual_old_raw)
    actual_new = _target_label(actual_new_raw)
    if expected_old and actual_old and actual_old != expected_old:
        raise ValueError(
            "compare evidence does not match pending window: "
            f"old target is {actual_old}, expected {expected_old}"
        )
    if expected_new and actual_new and actual_new != expected_new:
        raise ValueError(
            "compare evidence does not match pending window: "
            f"new target is {actual_new}, expected {expected_new}"
        )
    candidate_manifest = str(candidate.get("manifest") or "")
    expected_effective_digest = _target_effective_digest(actual_new_raw)
    if candidate_manifest and Path(candidate_manifest).exists():
        identity = effective_identity_for_manifest(candidate_manifest)
        if not identity["valid"]:
            raise ValueError("candidate effective manifest identity does not match its recomputed digest")
        if expected_effective_digest and identity["digest"] != expected_effective_digest:
            raise ValueError(
                "compare evidence does not match pending window: "
                "candidate effective digest changed after compare"
            )
    expected_digest = _target_digest(actual_new_raw)
    if expected_digest and candidate_manifest and Path(candidate_manifest).exists():
        actual_digest = sha256_file(candidate_manifest)
        if actual_digest != expected_digest:
            raise ValueError(
                "compare evidence does not match pending window: "
                "candidate effective manifest digest changed after compare"
            )


def _effective_conflict_count(manifest: dict[str, Any]) -> int:
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    try:
        count = int(summary.get("conflict_count") or manifest.get("conflict_count") or 0)
    except Exception:
        count = 0
    conflicts = manifest.get("conflicts") if isinstance(manifest.get("conflicts"), list) else []
    return max(count, len(conflicts))


def _expected_current_effective(window: dict[str, Any]) -> str | None:
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    current = str(base.get("current_effective_id") or "")
    if current:
        return current
    target = str(base.get("target") or "")
    if target.startswith("effective:"):
        return target.split(":", 1)[1]
    return None


def _write_review_approval(
    *,
    window: dict[str, Any],
    manifest_path: Path,
    compare_manifest_path: Path,
    accepted_by: str,
    note: str,
) -> tuple[Path, str]:
    manifest = read_json(manifest_path, {}) or {}
    identity = effective_identity_for_manifest(manifest_path, manifest)
    if not identity["valid"]:
        raise ValueError("candidate effective manifest identity does not match its recomputed digest")
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    base = window.get("base_effective") if isinstance(window.get("base_effective"), dict) else {}
    conflict_count = _effective_conflict_count(manifest)
    approval_path = manifest_path.parent / "review_approval.json"
    approval = {
        "schema_version": "review_approval.v1",
        "library": window.get("library"),
        "old_effective_id": _expected_current_effective(window) or "",
        "old_effective_target": base.get("target") or "",
        "candidate_effective_id": candidate.get("effective_id") or manifest.get("effective_id") or manifest_path.parent.name,
        "candidate_effective_manifest": str(manifest_path),
        "candidate_effective_sha256": sha256_file(manifest_path),
        "candidate_effective_digest": identity["digest"],
        "candidate_effective_identity_source": identity["source"],
        "compare_manifest": str(compare_manifest_path),
        "compare_manifest_sha256": sha256_file(compare_manifest_path),
        "conflict_count": conflict_count,
        "approved_by": accepted_by,
        "approved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "note": note,
    }
    write_json(approval_path, approval)
    return approval_path, sha256_file(approval_path)


def _validate_review_approval(window: dict[str, Any], effective_digest: str, manifest_path: Path | None = None) -> None:
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), dict) else {}
    approval_refs = [
        (window.get("review_approval"), window.get("approval_sha256")),
        (candidate.get("review_approval"), candidate.get("approval_sha256")),
    ]
    for approval_ref, approval_sha256 in approval_refs:
        if not approval_ref:
            continue
        if manifest_path is None:
            approval = read_json(str(approval_ref), {}) or {}
            approved_digest = str(approval.get("candidate_effective_digest") or "")
            if not approval or (approved_digest and approved_digest != effective_digest):
                raise ValueError("approval effective digest does not match candidate effective manifest")
            continue
        status = approval_integrity_for_manifest(
            approval_ref,
            manifest_path,
            approval_sha256=str(approval_sha256 or ""),
            effective_digest=effective_digest,
        )
        if status != "MATCH":
            raise ValueError(f"approval integrity is {status}; approval does not match candidate effective manifest")


def _attach_render_impact(args: argparse.Namespace, output: dict[str, Any], window: dict[str, Any], reason: str) -> None:
    if not getattr(args, "catalog", None) or not getattr(args, "library", None) or not getattr(args, "catalog_html_out", None):
        return
    render_impact = render_impacted_catalog_html(args, impacts_for_versions(args.library, _window_versions(window), reason))
    output["render_impact"] = render_impact
    output["rendered_pages"] = render_impact.get("affected_pages", [])
    output["catalog_html_out"] = render_impact.get("catalog_html_out")


def cmd_worklist(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog, {}) or {}
    rows: list[dict[str, Any]] = []
    for lib in catalog.get("libraries", []) or []:
        if not isinstance(lib, dict):
            continue
        library = _library_cli_name(lib)
        if not library:
            continue
        try:
            window = resolve_review_window(
                catalog_path=args.catalog,
                library=library,
                workdir=args.workdir,
                catalog_html_out=args.catalog_html_out,
            )
            row = _worklist_row(library, window)
        except Exception as exc:
            row = {
                "库": library,
                "状态": "错误",
                "当前Base": "-",
                "Base来源": "-",
                "新版本": "-",
                "Candidate": "-",
                "需扫描": 0,
                "建议动作": f"lg window {_quote(library)}",
                "错误": str(exc),
            }
        if getattr(args, "ready", False) and row["状态"] not in {"可执行", "可接受"}:
            continue
        if getattr(args, "blocked", False) and not str(row["状态"]).startswith("需") and row["状态"] != "错误":
            continue
        rows.append(row)
    summary = dict(Counter(str(row.get("状态") or "未知") for row in rows))
    output = {"status": "PASS", "summary": summary, "rows": rows}
    if getattr(args, "format", "json") == "text":
        print(_format_worklist_text(output))
    else:
        _print_json(output)
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    window = resolve_review_window(
        catalog_path=args.catalog,
        library=args.library,
        workdir=args.workdir,
        catalog_html_out=args.catalog_html_out,
        since=args.since,
        window_path=args.window_file,
        force_rebuild=args.rebuild,
        parse_jobs=str(args.parse_jobs or ""),
        hash_policy=args.hash_policy or "",
        parse_file_types=args.parse_file_types or "",
        parse_exclude_file_types=args.parse_exclude_file_types or "",
    )
    if window.get("state") != "EMPTY":
        write_json(window["pending_window_path"], window)
    plan_path = plan_path_for(args.workdir, args.library)
    unknowns = _unknown_package_versions(window)
    blocked_reason = ""
    if unknowns:
        blocked_reason = "存在未确认包类型，执行 intake 前需要 owner 确认：" + ", ".join(unknowns)
    existing_plan = load_plan(plan_path)
    plan = build_plan_from_window(
        workdir=args.workdir,
        library=args.library,
        window=window,
        existing=existing_plan,
        blocked_reason=blocked_reason,
    )
    save_plan(plan_path, plan)
    output = {
        "status": "NEEDS_PACKAGE_CONFIRM" if blocked_reason else "PASS",
        "window": window.get("pending_window_path"),
        "plan": str(plan_path),
        "plan_state": plan.get("state"),
        "next_action": plan.get("next_action"),
        "blocked_reason": blocked_reason,
        "state": window.get("state"),
        "base": window.get("base_effective"),
        "candidate_effective": window.get("candidate_effective"),
        "compare": window.get("compare"),
        "scan_versions": window.get("scan_versions", []),
        "warnings": window.get("warnings", []),
        "command_count": len(window.get("commands", []) or []),
        "message": window.get("message", ""),
    }
    output.update(_review_window_summary(args.library, window))
    output.update(_plan_followup_commands(args.library, window))
    if args.plan_only or window.get("state") == "EMPTY" or blocked_reason:
        if getattr(args, "format", "json") == "text":
            print(_format_intake_plan_text(args.library, output))
            return 0 if args.plan_only or not blocked_reason else 2
        _print_json(output)
        return 0 if args.plan_only or not blocked_reason else 2
    code, plan = execute_plan(plan_path=plan_path, plan=plan, runner=_run_one_command)
    output["command_exit_code"] = code
    output["plan_state"] = plan.get("state")
    output["next_action"] = plan.get("next_action")
    _attach_render_impact(args, output, window, "window_intake_updated")
    _print_json(output)
    return code


def cmd_show(args: argparse.Namespace) -> int:
    if args.window_file:
        data = read_json(args.window_file, {}) or {"status": "MISSING", "window": args.window_file}
    else:
        data = resolve_review_window(
            catalog_path=args.catalog,
            library=args.library,
            workdir=args.workdir,
            catalog_html_out=args.catalog_html_out,
            since=args.since,
            parse_jobs=str(args.parse_jobs or ""),
        )
    output = dict(data)
    output.update(_review_window_summary(args.library, output))
    if getattr(args, "format", "json") == "text":
        print(_format_window_text(args.library, output))
        return 0
    _print_json(output)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog, {}) or {}
    library_row = find_library(catalog, args.library)
    library_key = safe_name(str(library_row.get("library_id") or library_row.get("library_name") or args.library))
    effective_id = str(args.to or "")
    manifest = Path(args.catalog_html_out) / "libraries" / library_key / "effective" / safe_name(effective_id) / "effective_manifest.json"
    if not manifest.exists():
        raise ValueError(f"effective manifest not found: {effective_id}")
    pointer_path = Path(args.catalog_html_out) / "libraries" / library_key / "effective" / "current_effective.json"
    pointer = write_current_pointer(
        manifest,
        out=pointer_path,
        status="accepted",
        accepted_by=args.by,
        note=f"rollback: {args.reason}",
    )
    output = {"status": "PASS", "library": args.library, "current_effective": str(pointer), "effective_id": effective_id}
    render_impact = render_impacted_catalog_html(args, impacts_for_versions(args.library, [], "effective_rollback"))
    output["render_impact"] = render_impact
    output["rendered_pages"] = render_impact.get("affected_pages", [])
    _print_json(output)
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    data = read_json(args.window_file, {}) or {}
    if not data:
        raise ValueError(f"window file not found or empty: {args.window_file}")
    unknowns = _unknown_package_versions(data)
    if unknowns:
        raise ValueError("accept-window requires confirmed package_type for: " + ", ".join(unknowns))
    manifest = (data.get("candidate_effective") or {}).get("manifest")
    if not manifest:
        raise ValueError("pending window has no candidate effective manifest")
    manifest_path = Path(str(manifest))
    if not manifest_path.exists():
        raise ValueError(f"candidate effective manifest does not exist: {manifest_path}. Run intake first.")
    plan = load_plan(plan_path_for(args.workdir, args.library))
    if not plan:
        raise ValueError("accept-window requires intake plan DONE; run lg next <LIBRARY> --apply first")
    if str(plan.get("state") or "") != "DONE":
        raise ValueError(f"accept-window requires intake plan DONE; current plan state is {plan.get('state') or 'UNKNOWN'}")
    unfinished = [
        str(task.get("id") or task.get("kind") or "task")
        for task in plan.get("tasks", []) or []
        if str(task.get("status") or "") != "DONE"
    ]
    if unfinished:
        raise ValueError("accept-window requires intake plan DONE; unfinished tasks: " + ", ".join(unfinished[:8]))
    compare = data.get("compare") if isinstance(data.get("compare"), dict) else {}
    compare_dir = Path(str(compare.get("out_dir") or "")) if compare.get("out_dir") else None
    compare_manifest_path = compare_dir / "compare_manifest.json" if compare_dir else None
    if not compare or not compare_manifest_path or not compare_manifest_path.exists():
        raise ValueError("accept-window requires fresh effective compare evidence; run lg next <LIBRARY> --apply --rebuild")
    _validate_accept_compare(data, compare_manifest_path)
    effective_manifest = read_json(manifest_path, {}) or {}
    identity = effective_identity_for_manifest(manifest_path, effective_manifest)
    if not identity["valid"]:
        raise ValueError("candidate effective manifest identity does not match its recomputed digest")
    _validate_review_approval(data, str(identity["digest"]), manifest_path)
    conflict_count = _effective_conflict_count(effective_manifest)
    if conflict_count:
        raise ValueError(
            "effective manifest has unresolved conflicts; "
            f"conflict_count={conflict_count}. Fix effective composition before accept."
        )
    pointer_path = default_pointer_path_for_effective(manifest_path)
    existing_pointer = read_json(pointer_path, {}) or {}
    expected_current = _expected_current_effective(data)
    expected_revision = int(existing_pointer.get("revision") or 0) if expected_current is not None else None
    approval_path, approval_sha256 = _write_review_approval(
        window=data,
        manifest_path=manifest_path,
        compare_manifest_path=compare_manifest_path,
        accepted_by=args.accepted_by,
        note=args.note or "accepted from review window",
    )
    pointer = write_current_pointer(
        manifest_path,
        status="accepted",
        accepted_by=args.accepted_by,
        note=args.note or "accepted from review window",
        expected_previous_effective_id=expected_current,
        expected_revision=expected_revision,
        review_approval=approval_path,
        approval_sha256=approval_sha256,
    )
    data["state"] = "ACCEPTED"
    data["accepted_by"] = args.accepted_by
    data["current_effective_pointer"] = str(pointer)
    data["review_approval"] = str(approval_path)
    data["approval_sha256"] = approval_sha256
    write_json(args.window_file, data)
    output = {
        "status": "PASS",
        "current_effective": str(pointer),
        "review_approval": str(approval_path),
        "approval_sha256": approval_sha256,
        "window": args.window_file,
    }
    _attach_render_impact(args, output, data, "window_accept_updated")
    _print_json(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review-window intake tools")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--catalog", required=True)
        p.add_argument("--library", required=True)
        p.add_argument("--workdir", default="work")
        p.add_argument("--catalog-html-out", required=True)
        p.add_argument("--window-file")
        p.add_argument("--since")
        p.add_argument("--parse-jobs", default="")
        p.add_argument("--hash-policy", choices=["none", "smart", "full"])
        p.add_argument("--parse-file-types")
        p.add_argument("--parse-exclude-file-types")

    p = sub.add_parser("intake")
    add_common(p)
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("show")
    add_common(p)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("worklist")
    p.add_argument("--catalog", required=True)
    p.add_argument("--workdir", default="work")
    p.add_argument("--catalog-html-out", required=True)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.add_argument("--ready", action="store_true")
    p.add_argument("--blocked", action="store_true")
    p.set_defaults(func=cmd_worklist)

    p = sub.add_parser("rollback")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--workdir", default="work")
    p.add_argument("--catalog-html-out", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("accept")
    p.add_argument("--catalog")
    p.add_argument("--library")
    p.add_argument("--workdir", default="work")
    p.add_argument("--catalog-html-out")
    p.add_argument("--window-file", required=True)
    p.add_argument("--accepted-by", default="manual")
    p.add_argument("--note")
    p.set_defaults(func=cmd_accept)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
