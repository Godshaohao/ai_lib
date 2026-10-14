"""Validated Web-to-CLI argument contracts for release actions.

The Web console may choose a release operation, but release/linker remains the
only component that creates, overwrites, or verifies a formal delivery.
"""

from __future__ import annotations

from typing import Any, Mapping

from lib_guard.project_config import WEB_RELEASE_ALIASES, WEB_RELEASE_LINK_MODES
from lib_guard.release.bundle import validate_release_name


_RELEASE_ACTIONS = frozenset({"release-plan", "release-overwrite-preview", "release-force", "release-apply"})


def _text(value: Any, *, label: str, required: bool = False, limit: int = 500) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"强制发布必须填写{label}")
    if len(text) > limit:
        raise ValueError(f"{label}不能超过 {limit} 个字符")
    return text


def _enabled(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"})


def build_release_web_args(action: str, payload: Mapping[str, Any]) -> list[str]:
    """Return the only release CLI arguments the Web console may construct."""

    if action not in _RELEASE_ACTIONS:
        raise ValueError(f"网页不支持该发布动作: {action}")
    if action == "release-apply":
        if any(key in payload for key in ("force", "force_reason", "force_by", "no_verify", "apply")):
            raise ValueError("普通发布不允许强制或跳过校验；发布参数由服务端控制")
        if not _enabled(payload.get("acknowledged")):
            raise ValueError("实际发布必须确认目标目录和链接设置")
    alias = _text(payload.get("alias") or "current", label="发布别名", limit=30).lower()
    if alias not in WEB_RELEASE_ALIASES:
        raise ValueError("发布别名只能是 current、stage 或 approved")
    link_mode = _text(payload.get("link_mode") or "symlink", label="交付方式", limit=30).lower()
    if link_mode not in WEB_RELEASE_LINK_MODES:
        raise ValueError("交付方式只能是 symlink 或 copy")

    args = ["--alias", alias, "--link-mode", link_mode, "--no-render"]
    publish_name = str(payload.get("publish_name") or "").strip()
    if publish_name:
        publish_name = validate_release_name(publish_name)
        latest_name = validate_release_name(payload.get("latest_name") or "latest")
        if publish_name == latest_name:
            raise ValueError("正式目录名与最新指针名不能相同")
        args.extend(["--publish-name", publish_name, "--latest-name", latest_name])
    if action == "release-overwrite-preview" or publish_name or _enabled(payload.get("overwrite", action == "release-apply")):
        args.append("--overwrite")
    if action == "release-apply":
        return args + ["--apply"]
    if action != "release-force":
        return args

    if not _enabled(payload.get("acknowledged")):
        raise ValueError("强制发布必须勾选已理解覆盖与审计要求")
    reason = _text(payload.get("force_reason"), label="强制原因", required=True)
    actor = _text(payload.get("force_by"), label="执行人", required=True, limit=80)
    args.extend(["--overwrite", "--apply", "--force", "--force-reason", reason, "--force-by", actor])
    return args
