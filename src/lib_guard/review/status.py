from __future__ import annotations

from typing import Any


LABELS = {
    "OK": "正常",
    "REVIEW": "需审阅",
    "BLOCK": "阻断",
    "UNKNOWN": "未知",
    "NEED_CONFIRM": "待确认",
    "UNKNOWN_STAGE": "阶段未确认",
    "NOT_SCANNED": "未扫描",
    "SCAN_PASS": "扫描通过",
    "SCAN_WARN": "扫描告警",
    "SCAN_BLOCK": "扫描阻断",
    "SCAN_FAILED": "扫描失败",
    "DIFF_NOT_READY": "对比未就绪",
    "DIFF_PENDING": "待对比",
    "DIFF_SAME": "无结构变化",
    "DIFF_REVIEW": "有变化需审阅",
    "DIFF_BLOCK": "对比阻断",
    "DIFF_FAILED": "对比失败",
    "PAIRWISE_EMPTY": "无需文件对比",
    "PAIRWISE_PENDING": "文件对比待完成",
    "PAIRWISE_PARTIAL": "文件对比部分完成",
    "PAIRWISE_DONE": "文件对比完成",
    "PAIRWISE_FAILED": "文件对比失败",
    "RELEASE_NOT_CHECKED": "发布未检查",
    "RELEASE_READY": "可发布",
    "RELEASE_BLOCKED": "发布阻断",
    "RELEASE_APPLIED": "已发布",
    "RELEASE_VERIFY_FAILED": "发布校验失败",
}


def label(status: Any) -> str:
    text = str(status or "UNKNOWN")
    return LABELS.get(text, LABELS.get(text.upper(), text))


def tone(status: Any) -> str:
    text = str(status or "").upper()
    if text in {"OK", "SCAN_PASS", "DIFF_SAME", "PAIRWISE_EMPTY", "PAIRWISE_DONE", "RELEASE_READY", "RELEASE_APPLIED", "PASS", "DONE"}:
        return "ok"
    if text in {"BLOCK", "SCAN_BLOCK", "SCAN_FAILED", "DIFF_BLOCK", "DIFF_FAILED", "PAIRWISE_FAILED", "RELEASE_BLOCKED", "RELEASE_VERIFY_FAILED", "FAILED", "ERROR"}:
        return "bad"
    if text in {"UNKNOWN", "NOT_SCANNED", "DIFF_NOT_READY", "RELEASE_NOT_CHECKED"}:
        return "muted"
    return "warn"
