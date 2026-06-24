from __future__ import annotations

from typing import Any, Mapping


def derive_next_action(version: Mapping[str, Any]) -> dict[str, Any]:
    library = str(version.get("display_name") or version.get("library_name") or version.get("library_id") or "")
    version_id = str(version.get("version_id") or "")
    base = version.get("base_version") or version.get("parent_version")

    if version.get("catalog_status") in {"NEED_CONFIRM", "UNKNOWN_STAGE"}:
        return {
            "next_action": "CONFIRM_VERSION_RELATION",
            "next_command": "",
            "next_reason": "版本阶段、parent 或 base 关系需要人工确认后再继续。",
        }
    if version.get("scan_status") == "NOT_SCANNED":
        return {
            "next_action": "RUN_SCAN",
            "next_command": f"$PROJ/scripts/lg.csh scan {library} {version_id}",
            "next_reason": "该版本还没有 scan evidence。",
        }
    if version.get("scan_status") in {"SCAN_BLOCK", "SCAN_FAILED"}:
        return {
            "next_action": "FIX_SCAN_ISSUE",
            "next_command": "",
            "next_reason": "scan 结果阻断或失败，需要先修复扫描问题。",
        }
    if version.get("diff_status") in {"DIFF_PENDING", "DIFF_NOT_READY"}:
        if not base:
            return {
                "next_action": "CONFIRM_VERSION_RELATION",
                "next_command": "",
                "next_reason": "缺少 base/parent，无法生成可靠 diff 命令。",
            }
        return {
            "next_action": "RUN_DIFF",
            "next_command": f"$PROJ/scripts/lg.csh cmp {library} {version_id} --base {base}",
            "next_reason": "已有 scan evidence，下一步需要生成版本结构 diff。",
        }
    if version.get("pairwise_status") in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL"}:
        task = next((item for item in version.get("pairwise_tasks", []) or [] if item.get("status") != "DONE"), None)
        return {
            "next_action": "RUN_PAIRWISE",
            "next_command": str((task or {}).get("command") or ""),
            "next_reason": "diff 发现内容级文件变化，release 前建议完成 pairwise file-diff。",
        }
    if version.get("release_status") == "RELEASE_READY":
        return {
            "next_action": "RELEASE_REVIEW",
            "next_command": "",
            "next_reason": "该版本已有 release evidence，需要进入 Release Review 单独确认。",
        }
    if version.get("release_status") == "RELEASE_APPLIED":
        return {"next_action": "DONE", "next_command": "", "next_reason": "该版本已有发布结果。"}
    return {"next_action": "REVIEW_READY", "next_command": "", "next_reason": "Scan/Diff evidence 已就绪，可进入版本对比审阅。"}
