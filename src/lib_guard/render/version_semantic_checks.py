"""Compact advisory check projection for IP readers."""

from pathlib import Path
import shutil

from lib_guard.render import product_theme as ui


CHECK_LABELS = {
    'MACRO_BINDING': '对象关联', 'SIGNAL_PORT_SET': '信号端口集合',
    'SIGNAL_PORT_DIRECTION': '信号端口方向', 'PG_PORT_LEF_LIB': '电源端口',
    'LIB_MACRO_FLAGS': 'Liberty 宏标志', 'PROFILE_SCOPE': '检查范围',
    'FILE_EVIDENCE': '文件证据', 'LEF_SIZE_DELTA': 'LEF 尺寸变化',
    'LEF_PIN_DELTA': 'LEF 引脚变化', 'PORT_DECLARATION_DELTA': '端口声明变化',
    'LIB_PORT_DELTA': 'Liberty 端口变化',
}
REASON_LABELS = {
    'PORT_SET_MISMATCH': '端口集合不一致', 'PORT_DIRECTION_MISMATCH': '端口方向不一致',
    'PG_ROLE_MISMATCH': '电源端口角色不一致', 'INCOMPLETE_PORT_COVERAGE': '端口证据不完整',
    'UNCONFIRMED_BINDING': '对象关联待确认', 'UNALIGNED_PORT_SET': '端口集合尚未对齐',
    'UNKNOWN_DIRECTION': '端口方向未知', 'NO_SEMANTIC_OBJECTS': '未识别可检查对象',
    'SELECTED_CONTEXT_UNAVAILABLE': '所选上下文不可用',
    'SELECTED_MACRO_UNAVAILABLE': '所选对象不可用',
    'MACRO_CONTEXT_UNAVAILABLE': '对象上下文不可用',
    'UNSUPPORTED_OR_INCOMPLETE_PARSE': '解析证据不完整',
    'INCOMPLETE_ATTRIBUTE_EVIDENCE': '属性证据不完整',
    'INCOMPLETE_LEF_CHECK_INPUT': 'LEF 检查输入不完整',
}
STATUS_LABELS = {
    'FAIL': '未通过', 'REVIEW_REQUIRED': '需人工确认', 'NOT_CHECKED': '未检查',
    'UNKNOWN': '证据不足', 'INCOMPLETE': '未完成', 'AMBIGUOUS': '结果不明确',
    'CHANGED': '发现变化',
}


def semantic_reader_totals(row):
    """Separate current check conclusions from confirmed and pending deltas."""
    counts = row.get('counts') or {}
    delta = row.get('delta_counts') or {}
    number = lambda values, key: int(values.get(key) or 0)
    passed, failed = number(counts, 'PASS'), number(counts, 'FAIL')
    pending = sum(number(counts, key) for key in ('REVIEW_REQUIRED', 'NOT_CHECKED', 'UNKNOWN'))
    if _no_delta_base(row):
        delta = {}
    changed, unchanged = number(delta, 'CHANGED'), number(delta, 'UNCHANGED')
    delta_pending = sum(number(delta, key) for key in ('INCOMPLETE', 'UNKNOWN', 'AMBIGUOUS', 'NOT_CHECKED'))
    return {'current_executed': passed + failed, 'current_passed': passed,
            'current_failed': failed, 'current_pending': pending,
            'delta_executed': changed + unchanged, 'changed': changed,
            'delta_pending': delta_pending, 'unchanged': unchanged}


def _no_delta_base(row):
    scope = row.get('scope') or {}
    return row.get('delta_context') == 'NO_BASE_EFFECTIVE' or (
        not row.get('delta_context') and 'base' in scope and scope['base'] is None)


def _example(item, names, *, delta=False):
    check = CHECK_LABELS.get(item.get('check_id'), '技术检查' if not delta else '版本属性变化')
    reason = REASON_LABELS.get(item.get('reason_code')) or STATUS_LABELS.get(item.get('status'), '需核对证据')
    obj = names.get(item.get('macro_id')) or item.get('macro') or '文件范围'
    return f'<li>{ui.esc(obj)}：{ui.esc(check)}，{ui.esc(reason)}</li>'


def render_semantic_check(row, page):
    if not row:
        return ''
    status = row.get('status') or 'STALE'
    totals = semantic_reader_totals(row)
    components = ' → '.join(str(item) for item in row.get('components', []))
    link = ''
    if status != 'INVALID':
        source = Path(str(row.get('markdown_path') or ''))
        if source.is_file():
            relative = Path('semantic') / str(row['generation']) / 'summary.md'
            destination = Path(page).parent / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            link = f"<a href='{ui.esc(relative.as_posix())}'>完整检查摘要</a>"
        detail_source = Path(str(row.get('details_path') or ''))
        if detail_source.is_file():
            detail_relative = Path('semantic') / str(row['generation']) / 'check_results.json'
            detail_destination = Path(page).parent / detail_relative
            detail_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(detail_source, detail_destination)
            link += f" <a href='{ui.esc(detail_relative.as_posix())}'>逐项证据</a>"
    status_label = {'CURRENT': '当前证据', 'STALE': '来源已变化，需重查', 'INVALID': '快照损坏，不能引用'}.get(status, '需核对')
    if status == 'CURRENT':
        current = ('当前版：尚未执行独立检查' if not totals['current_executed'] and not totals['current_pending']
                   else f"当前版：{totals['current_passed']} 项通过，{totals['current_failed']} 项未通过，{totals['current_pending']} 项待核对")
        if _no_delta_base(row):
            version_change = '版本变化：未执行；未选择基准组合'
        else:
            version_change = (f"版本变化：{totals['changed']} 项变化，{totals['unchanged']} 项未变化，"
                              f"{totals['delta_pending']} 项待核对")
        conclusion = f'{current}；{version_change}'
        names = row.get('object_names') or {}
        check_rows = [item for item in row.get('checks', []) if item.get('status') not in {'PASS', 'NOT_APPLICABLE'}]
        delta_rows = [item for item in row.get('delta', []) if item.get('status') not in {'UNCHANGED'}]
        examples = ''.join(_example(item, names, delta=is_delta)
                           for is_delta, item in ([(False, item) for item in check_rows] +
                                                  [(True, item) for item in delta_rows])[:3])
        if not examples:
            examples = ''.join(_example(item, names) for item in row.get('attention_examples', [])[:3])
    else:
        conclusion, examples = '旧结果仅供追溯，不计入当前判断', ''
    return (
        "<section id='semantic-check' class='semantic-reader-check'>"
        "<div class='semantic-reader-head'><h2>跨视图技术检查</h2>"
        f"<span>{ui.esc(status_label)}</span></div>"
        f"<p><b>{ui.esc(conclusion)}</b> · 检查对象：完整有效组合 {ui.esc(row.get('effective_id'))}</p>"
        f"<p>组成顺序：{ui.esc(components)}；方案：{ui.esc(row.get('profile'))}；记录时间：{ui.esc(row.get('published_at'))}</p>"
        "<p>这是一份建议性检查，不代表 IP 可用，也不代表正式放行。</p>"
        f"{'<ul>' + examples + '</ul>' if examples else ''}"
        f"{link}</section>"
        "<style>.semantic-reader-check{margin:16px 0;padding:14px 18px;border:1px solid var(--line);background:#fff}"
        ".semantic-reader-head{display:flex;align-items:center;justify-content:space-between;gap:16px}"
        ".semantic-reader-head h2{margin:0;font-size:16px}.semantic-reader-check p{margin-top:6px;font-size:13px}"
        ".semantic-reader-check a{display:inline-block;margin-top:8px;color:#155eef;text-decoration:underline}</style>"
    )
