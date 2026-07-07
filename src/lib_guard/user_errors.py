from __future__ import annotations

import re
from typing import Any


def _message(exc: BaseException) -> str:
    text = str(exc)
    if isinstance(exc, KeyError):
        text = text.strip("'\"")
    return text


def _block(title: str, reason: str, steps: list[str]) -> str:
    lines = [f"ERROR: {title}"]
    if reason:
        lines.append(f"原因：{reason}")
    if steps:
        lines.append("下一步：")
        lines.extend(f"  {idx}. {step}" for idx, step in enumerate(steps, start=1))
    return "\n".join(lines)


def _friendly_reason(text: str) -> str:
    lower = text.lower()
    if "library not found" in lower:
        name = text.rsplit(":", 1)[-1].strip() if ":" in text else ""
        return f"catalog 中找不到这个库：{name or '<LIBRARY>'}"
    if "catalog version not found" in lower:
        library = re.search(r"library='([^']+)'", text)
        version = re.search(r"version='([^']+)'", text)
        lib_text = library.group(1) if library else "<LIBRARY>"
        ver_text = version.group(1) if version else "<VERSION>"
        return f"catalog 中找不到版本：库 {lib_text}，版本 {ver_text}"
    if "version not found" in lower:
        name = text.rsplit(":", 1)[-1].strip() if ":" in text else ""
        return f"catalog 中找不到这个版本：{name or '<VERSION>'}"
    if "pre-compare scan failed" in lower:
        return "compare 前自动补 scan 失败；需要先单独扫描失败版本并查看 scan_error。"
    return text


def format_user_error(exc: BaseException, *, argv: list[str] | None = None) -> str:
    """Return a concise Chinese explanation for expected operator errors."""

    text = _message(exc)
    lower = text.lower()

    if "lib_guard.yml" in lower or "config not found" in lower:
        return _block(
            "没有找到 lib_guard 配置。",
            "当前目录不是已初始化 workspace，或者 LIB_GUARD_CONFIG 没有指向正确的 lib_guard.yml。",
            [
                "进入 workspace 后再执行：cd $WORK",
                "或设置配置路径：setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml",
                "如果还没初始化：$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip",
            ],
        )

    if "catalog 尚未生成" in text:
        return f"ERROR: {text}"

    if "catalog.json" in lower and ("no such file" in lower or "not found" in lower):
        return _block(
            "catalog.json 不存在。",
            "库 registry/library_catalog.yml 可能已经有了，但 catalog 投影还没有生成。",
            [
                "已知单库时运行：lg cat <LIBRARY> --refresh-catalog",
                "首次全量投影运行：lg cat --refresh-catalog",
                "再确认库名：lg library list --plain",
            ],
        )

    if "library not found" in lower or "library not found in catalog" in lower:
        return _block(
            "库未在 catalog 中找到。",
            _friendly_reason(text),
            [
                "先复制正式库名：lg library list --plain",
                "如果刚入库，先投影 catalog：lg cat <LIBRARY> --refresh-catalog",
                "如果库还没入库：lg library add <LIBRARY> --root <LIB_ROOT> --apply --refresh-catalog",
            ],
        )

    if "ambiguous library alias" in lower:
        return _block(
            "库名不唯一。",
            text,
            [
                "不要用缩写或 display_name，先运行：lg library list --plain",
                "命令里使用完整正式库名，例如 Vendor_A.ucie 或 vendor_A.openroad_platform.xxx",
            ],
        )

    if "catalog 中没有版本" in text or "version not found" in lower:
        return _block(
            "版本未在 catalog 中找到。",
            _friendly_reason(text),
            [
                "先复制正式版本名：lg library list <LIBRARY> --versions --plain",
                "如果版本目录是新来的，先运行：lg cat <LIBRARY> --refresh-catalog",
                "再重试原命令。",
            ],
        )

    if "has no" in lower and "comparison target" in lower and "pass --base" in lower:
        return _block(
            "无法自动选择对比基线。",
            "catalog 里没有可靠的 adjacent/current_effective/previous_effective 关系。",
            [
                "先看系统推导表：lg window <LIBRARY>",
                "手动指定基线：lg cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing",
                "如果这是增量包，先绑定关系：lg library override <LIBRARY> <FIX_VERSION> --package-type PARTIAL_UPDATE --base-full <BASE_FULL_VERSION> --previous-effective <BASE_FULL_VERSION> --compare-default full_baseline --note \"manual confirmed base\"",
            ],
        )

    if "compare requires existing scan evidence" in lower or "missing or stale scan evidence" in lower:
        return _block(
            "对比前缺少 scan evidence。",
            "old/new 版本还没有扫描证据，或者已有扫描证据已过期。",
            [
                "最简单：lg cmp <LIBRARY> <VERSION> --scan-if-missing",
                "如果已经知道基线：lg cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing",
                "想分步排查时先扫：lg scan <LIBRARY> <VERSION>",
            ],
        )

    if "pre-compare scan failed" in lower:
        return _block(
            "compare 前自动扫描失败。",
            _friendly_reason(text),
            [
                "单独重跑失败版本：lg scan <LIBRARY> <VERSION>",
                "查看扫描进度/错误：python3 -m json.tool <SCAN_DIR>/logs/scan_progress_latest.json",
                "若只想确认是不是渲染慢：lg scan <LIBRARY> <VERSION> --no-render",
            ],
        )

    if "unknown package_type requires" in lower or "confirmed package_type" in lower:
        return _block(
            "存在未确认的包类型。",
            "系统不能确定某些版本是 FULL 还是 FIX/HOTFIX，所以不会继续自动 intake 或 accept-window。",
            [
                "先看窗口表：lg window <LIBRARY>",
                "完整包确认：lg mark <LIBRARY> <VERSION> --type FULL --note \"confirmed full package\"",
                "增量包确认：lg mark <LIBRARY> <VERSION> --type FIX --note \"confirmed partial update\"",
                "确认后重新执行：lg intake <LIBRARY> --plan-only",
            ],
        )

    if "candidate effective manifest does not exist" in lower or "pending window has no candidate effective manifest" in lower:
        return _block(
            "candidate effective 还没有生成。",
            "accept-window 只能接受已经执行过 intake 的 candidate effective。",
            [
                "先预演：lg intake <LIBRARY> --plan-only",
                "确认 Base/类型后执行：lg intake <LIBRARY>",
                "再接受：lg accept-window <LIBRARY> --accepted-by <USER> --note \"review passed\"",
            ],
        )

    if "window file not found" in lower or "window file not found or empty" in lower:
        return _block(
            "找不到 pending window。",
            "还没有为这个库生成接入窗口，或 window 文件为空。",
            [
                "先生成窗口：lg window <LIBRARY>",
                "需要执行计划时：lg intake <LIBRARY> --plan-only",
            ],
        )

    if "lg scan requires" in lower:
        return _block(
            "scan 参数不完整。",
            "scan 不会自己猜库和版本。",
            [
                "查库名：lg library list --plain",
                "查版本：lg library list <LIBRARY> --versions --plain",
                "扫描单版本：lg scan <LIBRARY> <VERSION>",
                "补齐缺失扫描：lg scan <LIBRARY> --missing",
            ],
        )

    if "file-diff" in lower or "lg fd" in lower:
        return _block(
            "文件级 diff 参数不正确。",
            text,
            [
                "普通版本审查优先看 Version Detail，不要默认跑 fd。",
                "专家下钻时使用：lg fd <LIBRARY> <VERSION> <RELPATH> --base <BASE_VERSION>",
                "大文件/summary-only 类型需要显式：--type <FILE_TYPE> --force-large",
            ],
        )

    if "target must be type:id/path" in lower or "unsupported target type" in lower or "catalog is required for raw target" in lower:
        return _block(
            "effective compare 目标格式不正确。",
            "effective compare 的目标必须带类型前缀，例如 raw:<VERSION> 或 effective:<ID>。",
            [
                "日常不要手写底层 effective compare，优先运行：lg intake <LIBRARY> --plan-only",
                "确认计划后运行：lg intake <LIBRARY>",
            ],
        )

    return _block(
        "操作失败。",
        text,
        [
            "先确认正式库名：lg library list --plain",
            "确认版本名：lg library list <LIBRARY> --versions --plain",
            "看基线/候选组合：lg window <LIBRARY>",
            "如果这是意料之外的错误，把完整命令和这段输出发给维护者。",
        ],
    )


__all__ = ["format_user_error"]
