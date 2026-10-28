"""Human-readable labels for file projection states; evidence keeps raw values."""

_LABELS = {
    "presence": {"PRESENT": "已提供", "ABSENT_VERIFIED": "未发现", "UNKNOWN": "无法确认", "NOT_SELECTED": "未选择版本"},
    "identity": {"EXACT_RELATIVE_PATH": "路径一致", "AMBIGUOUS": "对应关系不唯一", "OBSERVED_PATH": "仅记录路径", "UNRESOLVED": "对应关系待确认", "CANDIDATE_MATCH": "候选对应"},
    "content": {"SAME": "文件内容相同", "DIFF": "文件内容不同", "BYTE_SAME": "文件内容相同", "BYTE_DIFFERENT": "文件内容不同", "FAILED": "比较失败", "UNVERIFIED": "无法核实", "NOT_COMPARED": "未比较内容"},
    "semantic": {"CHANGED": "发现技术变化", "SAME_WITHIN_SCOPE": "已检查内容无变化", "UNVERIFIED": "部分内容待核实", "NOT_CHECKED": "未做技术检查", "FAILED": "检查失败"},
    "formal": {"OBSERVED": "已找到正式来源", "NOT_OBSERVED": "未找到正式链接", "UNKNOWN": "未盘点正式目录", "AMBIGUOUS": "正式来源不唯一", "UNRESOLVED": "正式来源待确认", "FORMAL_CONTEXT_REQUIRED": "需要指定正式阶段"},
    "coverage": {"COMPLETE": "已登记版本盘点完整", "PARTIAL": "部分盘点", "INCOMPLETE": "盘点不完整", "NOT_AVAILABLE": "未登记版本", "UNKNOWN_COVERAGE": "覆盖范围未知", "CONTEXT_REQUIRED": "需要指定正式阶段"},
    "latest": {"CONFIRMED": "已确认", "LATEST_OBSERVED": "当前已观察到", "UNKNOWN_COVERAGE": "覆盖范围未知", "UNKNOWN_ORDER": "顺序未知", "NONE": "无"},
    "previous": {"CONFIRMED": "无次新", "LATEST_OBSERVED": "当前已观察到", "UNKNOWN_COVERAGE": "覆盖范围未知", "UNKNOWN_ORDER": "顺序未知", "NONE": "无次新"},
    "delivery": {"READY_TO_COMPARE": "已准备比较", "NEWLY_PROVIDED": "本次新提供", "NOT_PROVIDED_IN_TARGET": "本次未提供", "NOT_PROVIDED_BOTH": "两次均未提供", "UNKNOWN_COVERAGE": "覆盖范围未知", "AMBIGUOUS": "对应关系不唯一", "CANDIDATE_MATCH": "候选对应", "NOT_SELECTED": "未选择版本"},
    "approval": {"NOT_CONFIGURED": "未核实批准状态"},
}


def projection_label(value: object, kind: str) -> str:
    if value is None or value == "":
        return "未记录"
    return _LABELS.get(kind, {}).get(str(value), f"未识别状态（{value}）")
