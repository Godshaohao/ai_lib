"""Human-readable labels for file projection states; evidence keeps raw values."""

_LABELS = {
    "presence": {"PRESENT": "已提供", "ABSENT_VERIFIED": "未发现", "UNKNOWN": "无法确认", "NOT_SELECTED": "未选择版本"},
    "identity": {"EXACT_RELATIVE_PATH": "路径一致", "AMBIGUOUS": "对应关系不唯一", "OBSERVED_PATH": "仅记录路径", "UNRESOLVED": "对应关系待确认"},
    "content": {"SAME": "文件内容相同", "DIFF": "文件内容不同", "NOT_COMPARED": "未比较内容"},
    "semantic": {"CHANGED": "发现技术变化", "SAME_WITHIN_SCOPE": "已检查内容无变化", "UNVERIFIED": "部分内容待核实", "NOT_CHECKED": "未做技术检查", "FAILED": "检查失败"},
    "formal": {"OBSERVED": "已找到正式来源", "NOT_OBSERVED": "未找到正式链接", "UNKNOWN": "未盘点正式目录", "AMBIGUOUS": "正式来源不唯一", "UNRESOLVED": "正式来源待确认"},
    "coverage": {"COMPLETE": "已登记版本盘点完整", "PARTIAL": "部分盘点", "NOT_AVAILABLE": "未登记版本"},
    "approval": {"NOT_CONFIGURED": "未核实批准状态"},
}


def projection_label(value: object, kind: str) -> str:
    if value is None or value == "":
        return "未记录"
    return _LABELS.get(kind, {}).get(str(value), f"未识别状态（{value}）")
