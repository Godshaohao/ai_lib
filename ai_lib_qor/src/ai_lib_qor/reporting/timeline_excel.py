"""Incremental column-appending effective-version timeline model & Excel workbook renderer.

Each new effective revision naturally appends one column to the right (`rev_0001 | rev_0002 | ...`),
reusing saved immutable per-revision `check_*.json` artifacts without re-running older revisions.
"""
import os
from pathlib import Path
import time
import uuid

import xlsxwriter

from ai_lib_qor.application.minimal_effective import _norm_business_ip
from ai_lib_qor.application.path_acceptance import acceptance_status
from ai_lib_qor.application.path_query import PathDataQuery, build_track_index_view, find_latest_check
from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
from ai_lib_qor.sources.layout import library_folder, storage_dir
from ai_lib_qor.versions.store import read_json_readonly
from .excel_style import build_palette, configure_sheet_print, write_banner, write_data_table


_RUN_STATE_ZH = {
    'SUCCEEDED': '执行完成',
    'PARTIAL': '部分完成',
    'FAILED': '执行失败',
    'NOT_CHECKED': '未检查',
}


def timeline_excel_filename(business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'timeline__{ip}.xlsx' if ip else 'timeline.xlsx'


def baseline_display_label(baseline) -> str:
    if baseline == '__prev_file__':
        return '按文件上一时间版本'
    if baseline in (None, '', '__none__'):
        return '无基线'
    return str(baseline)


def _rule_status_summary(checks: list[dict], check_id: str) -> str:
    hits = [c for c in checks if isinstance(c, dict) and c.get('check_id') == check_id]
    if not hits:
        return '—'
    fails = sum(1 for c in hits if c.get('result') == 'FAIL')
    incs = sum(1 for c in hits if c.get('result') == 'INCONCLUSIVE')
    passes = sum(1 for c in hits if c.get('result') == 'PASS')
    if fails:
        return f'失败 {fails}' + (f' / 无结论 {incs}' if incs else '') + (f' / 通过 {passes}' if passes else '')
    if incs:
        return f'无结论 {incs}' + (f' / 通过 {passes}' if passes else '')
    return f'通过 ({passes})'


def _role_label(revision: str, latest_rev: str | None, accepted_rev: str | None) -> str:
    is_latest = bool(latest_rev and revision == latest_rev)
    is_acc = bool(accepted_rev and revision == accepted_rev)
    if is_latest and is_acc:
        return '最新且已采纳'
    if is_latest:
        return '最新有效版'
    if is_acc:
        return '当前已采纳'
    return '历史有效版'


def _find_best_check_for_revision(work, vendor: str, library: str, revision: str, *, business_ip=None, prev_rev=None):
    """Find the most recent saved check JSON for `revision` (prefers Mode A `__prev_file__`, then any saved check)."""
    for cand_base in ('__prev_file__', prev_rev, None):
        hit = find_latest_check(
            work, vendor, library,
            revision=revision,
            baseline=cand_base,
            business_ip=business_ip,
        )
        if hit and hit.get('check_path'):
            cp = Path(hit['check_path'])
            if cp.is_file() and not cp.is_symlink():
                try:
                    return cp, read_json_readonly(cp)
                except (OSError, ValueError):
                    continue
    # Fallback: scan log dir directly for any check matching this revision (covers custom baseline runs)
    folder = library_folder(work, vendor, library)
    log_dir = folder / 'log'
    if not log_dir.is_dir():
        return None, None
    ip = _norm_business_ip(business_ip)
    pat = f'check__{ip}__{revision}_*.json' if ip else f'check_{library}_{revision}_*.json'
    candidates = sorted(
        (p for p in log_dir.glob(pat) if not p.is_symlink()),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    for cp in candidates:
        try:
            doc = read_json_readonly(cp)
            if doc.get('revision') == revision and doc.get('business_ip') == ip:
                return cp, doc
        except (OSError, ValueError):
            continue
    return None, None


def build_timeline_model(work, vendor: str, library: str, *, business_ip=None) -> dict:
    """Build shared horizontal timeline projection (revisions as columns) for both Web UI and Excel 2."""
    root = Path(work).resolve()
    folder = library_folder(root, vendor, library)
    ip = _norm_business_ip(business_ip)
    raw_index = PathDataQuery(root).index(vendor, library)
    ip_type = None
    if ip is not None:
        index, ip_type, _ = build_track_index_view(folder, vendor, library, raw_index, ip)
    else:
        index = raw_index

    revisions = list(index.get('revisions') or [])
    try:
        acc = acceptance_status(root, vendor, library, limit=1, business_ip=ip)
        accepted_rev = acc.get('accepted_revision')
    except (OSError, ValueError, KeyError):
        accepted_rev = None
    latest_rev = revisions[-1] if revisions else None

    deliv_order = {d['version']: i for i, d in enumerate(index.get('deliveries') or [])}
    rev_latest_deliv: dict[str, tuple[int, str]] = {}
    rev_members: dict[str, dict[tuple[str, str], str]] = {r: {} for r in revisions}
    all_file_keys: set[tuple[str, str]] = set()
    for view, group in (index.get('views') or {}).items():
        for rel, row in group.items():
            for entry in row.get('effective') or []:
                er = entry.get('revision')
                ev = entry.get('version') or ''
                if er in rev_members:
                    rev_members[er][(view, rel)] = ev
                    all_file_keys.add((view, rel))
                    ord_idx = deliv_order.get(ev, -1)
                    prev_best = rev_latest_deliv.get(er)
                    if ev and (prev_best is None or ord_idx > prev_best[0]):
                        rev_latest_deliv[er] = (ord_idx, ev)

    columns: list[dict] = []
    comp_by_rev: dict[str, dict[tuple[str, str], dict]] = {}
    check_rows_flat: list[list] = []

    for idx_r, rev in enumerate(revisions):
        prev_rev = revisions[idx_r - 1] if idx_r > 0 else None
        cp, doc = _find_best_check_for_revision(root, vendor, library, rev, business_ip=ip, prev_rev=prev_rev)
        src_ver = rev_latest_deliv.get(rev, (-1, ''))[1] or '—'
        member_cnt = len(rev_members.get(rev) or {})
        role = _role_label(rev, latest_rev, accepted_rev)

        if isinstance(doc, dict):
            verdict = evaluate_check_verdict(doc)
            files = doc.get('files') or []
            parsed_cnt = sum(1 for f in files if isinstance(f, dict) and f.get('status') == 'PARSED')
            summ = doc.get('summary') or {}
            checks = doc.get('checks') or []
            changes = doc.get('changes') or []
            comps = {
                (c['view'], c['path']): c
                for c in (doc.get('comparisons') or [])
                if isinstance(c, dict) and c.get('view') and c.get('path')
            }
            comp_by_rev[rev] = comps
            state = doc.get('state') or 'UNKNOWN'
            col = {
                'seq': idx_r + 1,
                'revision': rev,
                'header': f'有效版 #{idx_r + 1} ({rev})',
                'role': role,
                'is_accepted': bool(accepted_rev and rev == accepted_rev),
                'source_version': src_ver,
                'checked': True,
                'baseline_label': baseline_display_label(doc.get('baseline')),
                'state_label': _RUN_STATE_ZH.get(state, state),
                'quality_code': verdict['code'],
                'quality_cls': verdict['cls'],
                'quality_text': verdict['text'],
                'member_count': member_cnt,
                'parsed_text': f"{parsed_cnt} / {summ.get('failed_files', 0)}",
                'content_diff_count': int(summ.get('files_with_confirmed_content_change') or 0),
                'object_changes_count': len(changes),
                'failed_checks': int(summ.get('failed_checks') or 0),
                'inconclusive_checks': int(summ.get('inconclusive_checks') or 0),
                'corner_status': _rule_status_summary(checks, 'LIBERTY_CORNER_COVERAGE'),
                'lib_db_status': _rule_status_summary(checks, 'LIB_DB_PAIRING'),
                'pin_status': _rule_status_summary(checks, 'LEF_LIBERTY_PIN_MATCH'),
                'run_at': (doc.get('run_at') or '')[:19].replace('T', ' '),
                'run_id': doc.get('run_id') or '',
                'check_name': cp.name if cp else None,
            }
            for c in checks:
                check_rows_flat.append([
                    rev,
                    src_ver,
                    c.get('check_id', ''),
                    c.get('result', 'INCONCLUSIVE'),
                    c.get('coverage', 'UNKNOWN'),
                    '\n'.join(c.get('scope_file_keys') or []),
                    c.get('detail', ''),
                ])
        else:
            comp_by_rev[rev] = {}
            col = {
                'seq': idx_r + 1,
                'revision': rev,
                'header': f'有效版 #{idx_r + 1} ({rev})',
                'role': role,
                'is_accepted': bool(accepted_rev and rev == accepted_rev),
                'source_version': src_ver,
                'checked': False,
                'baseline_label': '未检查',
                'state_label': '未检查',
                'quality_code': 'UNCHECKED',
                'quality_cls': 'tag-inherited',
                'quality_text': '未检查',
                'member_count': member_cnt,
                'parsed_text': '未检查',
                'content_diff_count': '未检查',
                'object_changes_count': '未检查',
                'failed_checks': '未检查',
                'inconclusive_checks': '未检查',
                'corner_status': '未检查',
                'lib_db_status': '未检查',
                'pin_status': '未检查',
                'run_at': '—',
                'run_id': '—',
                'check_name': None,
            }
        columns.append(col)

    # Sheet 1 (horizontal metric rows: metrics x revisions)
    metric_defs = [
        ('版本角色 / 采纳状态', 'role'),
        ('最新来源交付版本', 'source_version'),
        ('对比模式 / 基线', 'baseline_label'),
        ('执行状态', 'state_label'),
        ('质检结论', 'quality_text'),
        ('有效文件数', 'member_count'),
        ('已解析 / 解析失败', 'parsed_text'),
        ('内容变化文件数', 'content_diff_count'),
        ('结构对象变化条数', 'object_changes_count'),
        ('失败规则数', 'failed_checks'),
        ('不确定规则数', 'inconclusive_checks'),
        ('Corner 完备性', 'corner_status'),
        ('.lib / .db 配对', 'lib_db_status'),
        ('LEF / Liberty Pin', 'pin_status'),
        ('检查时间 (UTC)', 'run_at'),
        ('Run ID', 'run_id'),
    ]
    metric_rows = [
        {'label': label, 'key': key, 'values': [col[key] for col in columns]}
        for label, key in metric_defs
    ]

    # Sheet 2 (horizontal file evolution matrix: files x revisions)
    file_timeline_rows: list[list[str]] = []
    for view, rel in sorted(all_file_keys):
        row_cells = [view, rel]
        seen_before = False
        prev_ver = None
        for rev in revisions:
            cur_ver = rev_members[rev].get((view, rel))
            if cur_ver is None:
                row_cells.append('已移除' if seen_before else '—')
                prev_ver = None
                continue
            comp = comp_by_rev.get(rev, {}).get((view, rel))
            if comp:
                c_tag = '内容变化' if comp.get('content_status') == 'CURRENT_CONTENT_DIFF' else '内容一致'
                if seen_before and cur_ver == prev_ver:
                    cell = f'{cur_ver} [沿用·{c_tag}]'
                else:
                    cell = f'{cur_ver} [{c_tag}]'
            elif not seen_before:
                cell = f'{cur_ver} [首次出现]'
            elif cur_ver == prev_ver:
                cell = f'{cur_ver} [沿用上版]'
            else:
                cell = f'{cur_ver} [来源更新]'
            row_cells.append(cell)
            seen_before = True
            prev_ver = cur_ver
        file_timeline_rows.append(row_cells)

    return {
        'vendor': vendor,
        'library': library,
        'business_ip': ip,
        'ip_type': ip_type,
        'latest_revision': latest_rev,
        'accepted_revision': accepted_rev,
        'columns': columns,
        'metric_rows': metric_rows,
        'file_timeline_rows': file_timeline_rows,
        'check_rows': check_rows_flat,
        'filename': timeline_excel_filename(ip),
    }


def render_timeline_excel(model: dict, output) -> Path:
    """Write the 3-sheet column-appending timeline workbook atomically."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    cols = model['columns']
    rev_headers = [c['header'] for c in cols]
    title_scope = (
        f"{model['vendor']} / {model['library']} / {model['business_ip']}"
        if model.get('business_ip')
        else f"{model['vendor']} / {model['library']}"
    )
    title = f'有效版本演进时间线总表 · {title_scope}'
    subtitle = (
        f"共 {len(cols)} 个有效版本（按时间自左向右每版一列，增量更新不重跑历史）  |  "
        f"当前已采纳: {model.get('accepted_revision') or '尚未人工采纳'}  |  "
        f"最新有效版: {model.get('latest_revision') or '无'}"
    )

    book = xlsxwriter.Workbook(str(path), {'strings_to_formulas': False, 'strings_to_urls': False})
    book.set_properties({'title': title, 'subject': '有效版本横向演进时间线（增量加列）'})
    pal = build_palette(book)
    try:
        # Sheet 00: Version Timeline Matrix (metrics as rows, revisions as columns)
        sh0 = book.add_worksheet('00-版本演进时间线')
        headers0 = ['演进指标', *rev_headers]
        specs0 = [{'kind': 'text', 'min_w': 20, 'max_w': 24}] + [
            {'kind': 'center', 'min_w': 20, 'max_w': 28} for _ in rev_headers
        ]
        rows0 = [[m['label'], *m['values']] for m in model['metric_rows']]
        configure_sheet_print(sh0, header_row=3, tab_color='#1B365D')
        sh0.freeze_panes(4, 1)
        write_banner(sh0, pal, title, subtitle, max(2, len(headers0)))
        write_data_table(
            sh0, pal, 3, headers0, rows0,
            col_specs=specs0,
            empty_message='当前尚无有效版本。',
            autofilter=False, set_widths=True,
        )

        # Sheet 01: File Evolution Timeline Matrix (files as rows, revisions as columns)
        sh1 = book.add_worksheet('01-文件演进时间线')
        headers1 = ['View', '相对路径', *rev_headers]
        specs1 = [
            {'kind': 'center', 'min_w': 10, 'max_w': 14},
            {'kind': 'text', 'min_w': 32, 'max_w': 52},
            *({'kind': 'text', 'min_w': 22, 'max_w': 32} for _ in rev_headers),
        ]
        configure_sheet_print(sh1, header_row=3, tab_color='#0EA5E9')
        sh1.freeze_panes(4, 2)
        write_banner(
            sh1, pal, f'01 · 文件演进时间线 — {title_scope}',
            subtitle, max(3, len(headers1)), back_sheet='00-版本演进时间线',
        )
        write_data_table(
            sh1, pal, 3, headers1, model['file_timeline_rows'],
            col_specs=specs1,
            empty_message='当前有效版本中暂无文件记录。',
            autofilter=True, set_widths=True,
        )

        # Sheet 02: Rule & Exception Log across revisions
        sh2 = book.add_worksheet('02-规则与异常流水')
        headers2 = ['有效版本', '最新来源交付', '检查项 ID', '结果', '覆盖度', '涉及文件', '说明']
        specs2 = [
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
            {'kind': 'text', 'min_w': 20, 'max_w': 28},
            {'kind': 'text', 'min_w': 24, 'max_w': 30},
            {'kind': 'status', 'min_w': 14, 'max_w': 16},
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
            {'kind': 'text', 'min_w': 30, 'max_w': 48},
            {'kind': 'text', 'min_w': 36, 'max_w': 58},
        ]
        any_fail = any(r[3] == 'FAIL' for r in model['check_rows'])
        configure_sheet_print(sh2, header_row=3, freeze_row=4, tab_color='#DC2626' if any_fail else '#16A34A')
        write_banner(
            sh2, pal, f'02 · 历次有效版本规则流水 — {title_scope}',
            subtitle, len(headers2), back_sheet='00-版本演进时间线',
        )
        write_data_table(
            sh2, pal, 3, headers2, model['check_rows'],
            col_specs=specs2,
            empty_message='当前尚无已保存的检查规则记录。',
            autofilter=True, set_widths=True,
        )
    finally:
        book.close()
    return path


def render_timeline_excel_for_scope(work, vendor: str, library: str, *, business_ip=None, excel_path=None) -> str:
    """Incrementally rebuild & atomically update `log/timeline[__<ip>].xlsx` (zero re-running of old checks)."""
    folder = library_folder(work, vendor, library)
    ip = _norm_business_ip(business_ip)
    if excel_path is None:
        target = storage_dir(folder, 'log') / timeline_excel_filename(ip)
    else:
        target = Path(excel_path)
    if target.is_symlink():
        raise ValueError('时间线 Excel 输出路径不能为软链接')
    target.parent.mkdir(parents=True, exist_ok=True)
    model = build_timeline_model(work, vendor, library, business_ip=ip)
    tmp = target.parent / f'.{target.stem}.{uuid.uuid4().hex}.tmp.xlsx'
    rendered_at = time.time_ns()
    try:
        render_timeline_excel(model, tmp)
        os.utime(tmp, ns=(rendered_at, rendered_at))
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return str(target)
