"""Reporting-layer Excel rendering orchestrators for saved CheckResult and OverallRun artifacts."""
import json
import os
from pathlib import Path
import uuid

from ai_lib_qor.application.facts_pool import load_check_bundle, resolve_check_file
from ai_lib_qor.application.path_acceptance import acceptance_status
from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import validate
from .excel import render_excel
from .overall_excel import render_overall_excel


def _safe_acceptance(work, vendor, library):
    try:
        return acceptance_status(work, vendor, library, limit=5)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _members(index, revision):
    return {
        (view, path): entry
        for view, group in index['views'].items()
        for path, row in group.items()
        for entry in row['effective']
        if entry['revision'] == revision
    }


def _index_source_deltas(index, revision, baseline):
    curr_m = _members(index, revision)
    if not baseline:
        return len(curr_m), None, None, None
    base_m = _members(index, baseline)
    curr_keys = set(curr_m)
    base_keys = set(base_m)
    added = len(curr_keys - base_keys)
    removed = len(base_keys - curr_keys)
    changed = sum(1 for k in (curr_keys & base_keys) if curr_m[k]['version'] != base_m[k]['version'])
    return len(curr_m), added, changed, removed


def render_excel_from_check(work, vendor, library, check_filename, excel_path=None):
    """Pure read-only report renderer decoupled from check execution (atomic file placement)."""
    bundle = load_check_bundle(work, vendor, library, check_filename)
    report = bundle['report']
    if excel_path is None:
        cp = bundle['check_path']
        excel_path = cp.with_suffix('.xlsx') if cp.parent.name == 'log' else bundle['folder'] / ('report_' + report['run_id'] + '.xlsx')
    else:
        excel_path = Path(excel_path)
    if excel_path.is_symlink():
        raise ValueError('Excel 输出路径不能为软链接')
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = excel_path.parent / f'.{excel_path.stem}.{uuid.uuid4().hex}.tmp.xlsx'
    acceptance = _safe_acceptance(work, vendor, library)
    try:
        render_excel(
            {**report, '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': acceptance, 'unavailable_facts': bundle['unavailable_facts']}},
            tmp,
        )
        os.replace(tmp, excel_path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(excel_path)


def render_overall_excel_rows(work, vendor, library, rows, excel_path):
    """Render library-level multi-revision overall Excel atomically."""
    excel_path = Path(excel_path)
    if excel_path.is_symlink():
        raise ValueError('Excel 输出路径不能为软链接')
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = excel_path.parent / f'.{excel_path.stem}.{uuid.uuid4().hex}.tmp.xlsx'
    acceptance = _safe_acceptance(work, vendor, library)
    try:
        render_overall_excel({'vendor': vendor, 'library': library}, rows, tmp, acceptance=acceptance)
        os.replace(tmp, excel_path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(excel_path)


def render_overall_excel_from_saved(work, vendor, library, overall_filename, excel_path=None):
    """Pure read-only re-renderer for a saved overall_run_*.json without mutating JSON/runs.jsonl."""
    folder = library_folder(work, vendor, library)
    index = PathDataQuery(work).index(vendor, library)
    overall_path = resolve_check_file(folder, overall_filename)
    saved = json.loads(overall_path.read_text(encoding='utf-8'))
    if (saved.get('vendor'), saved.get('library')) != (vendor, library) or not isinstance(saved.get('versions'), list):
        raise ValueError('整体运行记录与当前库归属不一致或格式无效')
    available = index.get('revisions') or []
    rows = []
    for entry in saved['versions']:
        rev = entry['revision']
        pos = available.index(rev) if rev in available else -1
        default_base = available[pos - 1] if pos > 0 else None
        chk_path_raw = entry.get('check')
        chk_file = None
        if chk_path_raw:
            cand = Path(chk_path_raw)
            if cand.is_file() and not cand.is_symlink() and cand.resolve().is_relative_to(folder.resolve()):
                chk_file = cand
            else:
                try:
                    chk_file = resolve_check_file(folder, cand.name)
                except ValueError:
                    chk_file = None
        if not chk_file:
            member_cnt, src_add, src_chg, src_rem = _index_source_deltas(index, rev, default_base)
            rows.append({
                'revision': rev,
                'baseline': default_base,
                'run_id': entry.get('run_id') or '',
                'state': entry.get('state') or 'NOT_CHECKED',
                'plan': '未执行',
                'note': '无已保存的单版本检查结果',
                'checks': [],
                'changes': [],
                'member_count': member_cnt,
                'index_source_added': src_add,
                'index_source_changes': src_chg,
                'index_source_removed': src_rem,
            })
            continue
        check = json.loads(chk_file.read_text(encoding='utf-8'))
        validate(check, 'check_result_path')
        member_cnt, src_add, src_chg, src_rem = _index_source_deltas(index, rev, check.get('baseline'))
        rows.append({
            'revision': rev,
            'baseline': check.get('baseline'),
            'run_id': check['run_id'],
            'run_at': check.get('run_at', ''),
            'state': check['state'],
            'plan': '路径式有效版本检查',
            'summary': check['summary'],
            'checks': check['checks'],
            'changes': check.get('changes') or [],
            'facts_evidence': check.get('facts_evidence') or {},
            'parsed_files': sum(1 for f in check.get('files', []) if f.get('status') == 'PARSED'),
            'member_count': member_cnt,
            'index_source_added': src_add,
            'index_source_changes': src_chg,
            'index_source_removed': src_rem,
            'note': check['note'] + '；从已保存历史结果重新渲染',
            'error': f"解析失败 {check['summary']['failed_files']} 个文件" if check['summary']['failed_files'] else None,
            'comparison_count': len(check['comparisons']),
        })
    target = overall_path.with_suffix('.xlsx') if excel_path is None else Path(excel_path)
    return render_overall_excel_rows(work, vendor, library, rows, target)
