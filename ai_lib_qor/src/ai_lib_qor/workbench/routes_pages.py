"""Read-only HTML pages and file download routes for the path workbench."""
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile

from flask import abort, render_template, request, send_file

from ai_lib_qor.application.path_acceptance import acceptance_status
from ai_lib_qor.application.path_query import latest_check_for_scope, unadopted_new_files
from ai_lib_qor.application.path_refresh import read_refresh_history, refresh_status
from ai_lib_qor.application.path_storage import storage_stats
from ai_lib_qor.sources.layout import archive_files, library_folder


def _fmt_bytes(n):
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def _fmt_mtime_utc(path):
    try:
        st = path.stat()
    except OSError:
        return '—', 0, '—', 0
    dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return dt, int(st.st_mtime), _fmt_bytes(st.st_size), int(st.st_size)


def _resolve_pointer_in_folder(folder, pointer_name):
    ptr = folder / pointer_name
    if not ptr.is_symlink():
        return None
    try:
        target = ptr.resolve(strict=True)
        if target.is_relative_to(folder.resolve()) and target.is_file():
            return target
    except (OSError, ValueError):
        return None
    return None


def _source_verification_note(source, evidence):
    if not evidence or not evidence.get('at'):
        return '暂无本库来源核验记录'
    at = evidence['at'].replace('T', ' ').removesuffix('Z')
    verified = evidence.get('verified_at')
    last_full = f" · 上次完整核验 {verified.replace('T', ' ').removesuffix('Z')} UTC" if verified and verified != evidence['at'] else ''
    if source == 'RAW':
        if evidence['versions_incomplete']:
            return f'最近 RAW 盘点 {at} UTC（有版本未完成）{last_full}'
        if evidence['versions_reused']:
            return f"最近 RAW 盘点 {at} UTC（复用 {evidence['versions_reused']} 个已归档版本）{last_full}"
    elif evidence['status'] == 'PARTIAL':
        return f'最近 Formal 盘点 {at} UTC（观察不完整）{last_full}'
    elif evidence['status'] == 'NO_MATCH':
        return f'最近 Formal 盘点 {at} UTC（本库没有匹配链接）{last_full}'
    return f'最近 {source} 核验 {at} UTC'


def _collect_json_inventory(work, refresh_info, libraries, *, include_workspace=True, filters=None, page_size=100):
    """Filter and order all saved JSON entries before taking the requested page."""
    root = Path(work)
    filters = filters or {}
    last_by = (refresh_info or {}).get('last_by_layer') or {}
    r1, r2, r3 = (last_by.get(layer) for layer in ('L1', 'L2', 'L3'))

    changed_deliveries = {}
    changed_formals = {}
    if r1:
        for item in r1.get('libraries_changed') or []:
            key = (item.get('vendor'), item.get('library'))
            if item.get('new_deliveries'):
                changed_deliveries[key] = set(item['new_deliveries'])
            if item.get('new_formals'):
                changed_formals[key] = set(item['new_formals'])

    changed_revs = {}
    if r2:
        for item in r2.get('libraries_changed') or []:
            key = (item.get('vendor'), item.get('library'))
            rev_map = changed_revs.setdefault(key, {})
            for ev in item.get('events') or []:
                if ev.get('revision'):
                    rev_map[ev['revision']] = ev.get('action') or 'UPDATE'

    rows = []

    if include_workspace:
        cfg_path = root / 'path_sources.json'
        if cfg_path.is_file() and not cfg_path.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime_utc(cfg_path)
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '来源目录配置',
                'filename': 'path_sources.json',
                'rel_path': 'path_sources.json',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'unchanged',
                'status_label': '已生效',
                'tag_cls': 'tag-inherited',
                'status_note': '记录 RAW 与 Formal 根目录及默认同步选项',
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'config',
            })
        else:
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '来源目录配置',
                'filename': 'path_sources.json',
                'rel_path': 'path_sources.json',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'issue',
                'status_label': '未配置',
                'tag_cls': 'tag-partial',
                'status_note': '请前往「目录配置」设置来源根目录',
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'config',
            })

        hist_path = root / 'refresh_history.jsonl'
        if hist_path.is_file() and not hist_path.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime_utc(hist_path)
            runs_cnt = len((refresh_info or {}).get('recent_runs') or [])
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '同步审计日志',
                'filename': 'refresh_history.jsonl',
                'rel_path': 'refresh_history.jsonl',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'unchanged',
                'status_label': '持续记录',
                'tag_cls': 'tag-inherited',
                'status_note': f'最近 {runs_cnt} 条同步批次已留痕',
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'history',
            })

    for lib_item in libraries or []:
        v = lib_item['vendor']
        lib = lib_item['library']
        try:
            folder = library_folder(root, v, lib)
        except ValueError:
            continue
        if not folder.is_dir():
            continue

        key = (v, lib)
        scope_label = f'{v}/{lib}'
        latest_deliv = _resolve_pointer_in_folder(folder, 'latest_delivery.json')
        latest_eff = _resolve_pointer_in_folder(folder, 'latest_effective.json')
        accepted_eff = _resolve_pointer_in_folder(folder, 'accepted_effective.json')
        latest_formals = set()
        for fptr in folder.glob('latest_formal_*.json'):
            resolved = _resolve_pointer_in_folder(folder, fptr.name)
            if resolved:
                latest_formals.add(resolved)

        sources = lib_item.get('source_verifications', {})
        raw_note = _source_verification_note('RAW', sources.get('RAW'))
        formal_evidence = sources.get('FORMAL', {})
        index_attempt = lib_item.get('index_attempt') or {}
        index_failure = index_attempt.get('reason') if index_attempt.get('status') == 'FAILED' else None

        # L1: RAW deliveries
        deliv_changed_versions = changed_deliveries.get(key) or set()
        for p in archive_files(folder, 'delivery', 'delivery_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
            rel_in_lib = str(p.relative_to(folder))
            is_new = False
            if deliv_changed_versions:
                try:
                    d_ver = json.loads(p.read_text(encoding='utf-8')).get('version')
                    is_new = d_ver in deliv_changed_versions
                except (OSError, ValueError, TypeError):
                    is_new = False
            if is_new:
                sg, sl, tc = 'updated', '本轮新增', 'tag-new'
            else:
                sg, sl, tc = 'unchanged', '已归档', 'tag-inherited'
            rows.append({
                'layer': 'L1',
                'layer_label': 'L1 来源',
                'category': 'RAW 交付归档',
                'filename': p.name,
                'rel_path': f'{scope_label}/{rel_in_lib}',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': raw_note,
                'pointer_badge': '最新交付' if (latest_deliv and p.resolve() == latest_deliv) else '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'library',
            })

        # L1: Formal snapshots
        formal_changed_names = changed_formals.get(key) or set()
        for p in archive_files(folder, 'formal', 'formal_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
            rel_in_lib = str(p.relative_to(folder))
            match = re.fullmatch(r'formal_(.+?)_(?:\d{8}T\d{6}Z_)?\d+\.json', p.name)
            note = _source_verification_note('Formal', formal_evidence.get(match[1]) if match else None)
            if p.name in formal_changed_names:
                sg, sl, tc = 'updated', '本轮新增', 'tag-new'
            else:
                sg, sl, tc = 'unchanged', '已归档', 'tag-inherited'
            rows.append({
                'layer': 'L1',
                'layer_label': 'L1 来源',
                'category': 'Formal 快照',
                'filename': p.name,
                'rel_path': f'{scope_label}/{rel_in_lib}',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': note,
                'pointer_badge': '最新快照' if (p.resolve() in latest_formals) else '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'index',
            })

        # L2: Effective revisions
        eff_files = [p for p in archive_files(folder, 'effective', f'effective_{lib}_*.json') if not p.is_symlink() and p.is_file()]
        rev_changed_map = changed_revs.get(key) or {}
        if eff_files:
            for p in eff_files:
                dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
                rel_in_lib = str(p.relative_to(folder))
                m_rev = re.search(r'_(\d+)\.json$', p.name)
                rev_id = f'rev_{int(m_rev.group(1)):04d}' if m_rev else ''
                act = rev_changed_map.get(rev_id)
                if act == 'INITIALIZE':
                    sg, sl, tc, sn = 'updated', '本轮初始化', 'tag-new', '最近 L2 推进自动初始化'
                elif act:
                    sg, sl, tc, sn = 'updated', '本轮发布', 'tag-new', '最近 L2 推进自动演进'
                else:
                    sg, sl, tc, sn = 'unchanged', '已归档', 'tag-inherited', '只读有效版本归档'
                p_res = p.resolve()
                badges = []
                if latest_eff and p_res == latest_eff:
                    badges.append('最新有效版')
                if accepted_eff and p_res == accepted_eff:
                    badges.append('已采纳')
                rows.append({
                    'layer': 'L2',
                    'layer_label': 'L2 版本',
                    'category': f'有效版本 {rev_id}' if rev_id else '有效版本归档',
                    'filename': p.name,
                    'rel_path': f'{scope_label}/{rel_in_lib}',
                    'vendor': v,
                    'library': lib,
                    'scope_label': scope_label,
                    'sync_group': sg,
                    'status_label': sl,
                    'tag_cls': tc,
                    'status_note': sn,
                    'pointer_badge': ' · '.join(badges),
                    'updated_at': dt,
                    'updated_ts': ts,
                    'size_text': sz_txt,
                    'size_bytes': sz,
                    'exists': True,
                    'action_kind': 'library',
                    'revision': rev_id,
                })
        else:
            has_formal = (lib_item.get('formal_count') or 0) > 0
            rows.append({
                'layer': 'L2',
                'layer_label': 'L2 版本',
                'category': '有效版本归档',
                'filename': f'effective_{lib}_001.json',
                'rel_path': f'{scope_label}/effective/effective_{lib}_001.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': 'issue',
                'status_label': '未建有效版',
                'tag_cls': 'tag-partial',
                'status_note': '已有 Formal 快照，可推进 L2 初始化' if has_formal else '尚无 Formal 快照，待初始化',
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'library',
            })

        # L3: File index
        idx_path = folder / 'file_index.json'
        idx_status = lib_item.get('index_status') or ('MISSING' if not idx_path.is_file() else 'UNVERIFIED')
        if idx_status == 'MISSING' or idx_path.is_symlink() or not idx_path.is_file():
            rows.append({
                'layer': 'L3',
                'layer_label': 'L3 索引',
                'category': '跨版本文件索引',
                'filename': 'file_index.json',
                'rel_path': f'{scope_label}/file_index.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': 'issue',
                'status_label': '刷新失败' if index_failure else '未生成',
                'tag_cls': 'tag-failed',
                'status_note': index_failure or '索引缺失，需确认顺序后刷新 L3',
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'library',
            })
        else:
            dt, ts, sz_txt, sz = _fmt_mtime_utc(idx_path)
            if index_failure:
                sg, sl, tc, sn = 'issue', '刷新失败', 'tag-failed', index_failure
            elif idx_status in ('STALE', 'UNVERIFIED'):
                sg = 'issue'
                sl = '待刷新'
                tc = 'tag-partial'
                sn = '归档已变动，需刷新 L3' if idx_status == 'STALE' else '未校验指纹，建议刷新 L3'
            elif index_attempt.get('status') == 'UPDATED' and r3 and index_attempt.get('at') == r3.get('at'):
                sg = 'updated'
                sl = '本轮更新'
                tc = 'tag-new'
                sn = '最近 L3 同步已重建索引'
            else:
                sg = 'unchanged'
                sl = '同步一致'
                tc = 'tag-new'
                sn = '与来源归档指纹一致'
            rows.append({
                'layer': 'L3',
                'layer_label': 'L3 索引',
                'category': '跨版本文件索引',
                'filename': 'file_index.json',
                'rel_path': f'{scope_label}/file_index.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': sn,
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'download_index',
            })

    group_rank = {'updated': 0, 'issue': 1, 'unchanged': 2}
    layer_rank = {'L1': 0, 'L2': 1, 'L3': 2, 'WORKSPACE': 3}
    counts = {'total': len(rows), **dict.fromkeys(group_rank, 0), **dict.fromkeys(layer_rank, 0)}
    for row in rows:
        counts[row['layer']] += 1
        counts[row['sync_group']] += 1

    query = {key: filters.get(key, '').strip() for key in ('json_layer', 'json_status', 'json_scope', 'json_q', 'json_sort')}
    if query['json_layer'] not in layer_rank:
        query['json_layer'] = ''
    if query['json_status'] not in group_rank:
        query['json_status'] = ''
    if query['json_sort'] not in ('newest', 'layer'):
        query['json_sort'] = 'priority'
    q = query['json_q'].casefold()
    search_fields = ('filename', 'rel_path', 'category', 'scope_label', 'status_label', 'status_note')
    rows = [
        row for row in rows
        if (not query['json_layer'] or row['layer'] == query['json_layer'])
        and (not query['json_status'] or row['sync_group'] == query['json_status'])
        and (not query['json_scope'] or row['scope_label'] == query['json_scope'])
        and (not q or q in ' '.join(row[key] for key in search_fields).casefold())
    ]

    def sort_key(row):
        layer = layer_rank[row['layer']]
        scope, filename = row['scope_label'], row['rel_path']
        newest = -row['updated_ts']
        if query['json_sort'] == 'newest':
            return newest, layer, scope, filename
        if query['json_sort'] == 'layer':
            return layer, scope, newest, filename
        return group_rank[row['sync_group']], newest, layer, scope, filename

    rows.sort(key=sort_key)
    try:
        page = int(filters.get('json_page', 1))
    except (ValueError, TypeError):
        page = 1
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    return {
        'rows': rows[(page - 1) * page_size : page * page_size],
        'counts': counts,
        'matched': len(rows),
        'page': page,
        'pages': pages,
        'query': query,
    }


def register_page_routes(app, ctx):
    work = ctx['work']
    scope = ctx['scope']
    index_state = ctx['index_state']
    source_config = ctx['source_config']

    @app.get('/')
    def overview():
        status = refresh_status(work, limit=8)
        libraries = []
        for item in status['libraries']:
            err = None
            attempt = item['index_attempt'] or {}
            if attempt.get('status') == 'FAILED':
                err = attempt['reason']
            elif item['index_status'] == 'MISSING':
                err = '索引未生成，请刷新 L3'
            elif item['index_status'] == 'STALE':
                err = '归档已更新，索引待刷新 (L3)'
            sources = item['source_verifications']
            libraries.append({
                **item, 'error': err,
                'raw_verification_note': _source_verification_note('RAW', sources.get('RAW')),
                'formal_verification_notes': {
                    version: _source_verification_note('Formal', evidence)
                    for version, evidence in sorted(sources.get('FORMAL', {}).items())
                },
            })
        summary = {
            'vendors': status['totals']['vendors'],
            'libraries': status['totals']['libraries'],
            'with_effective': status['totals']['libraries_with_effective'],
            'accepted': sum(1 for x in libraries if x.get('accepted_revision')),
            'revisions': status['totals']['revisions'],
            'issues': sum(1 for x in libraries if x.get('error')),
        }
        try:
            st = storage_stats(work)
            storage_display = {
                'total': _fmt_bytes(st['total_bytes']),
                'auth': _fmt_bytes(st['authoritative_bytes']),
                'cache': _fmt_bytes(st['rebuildable_cache_bytes']),
            }
        except (OSError, ValueError):
            storage_display = None
        json_inventory = _collect_json_inventory(work, status, libraries, filters=request.args)
        return render_template(
            'path_overview.html',
            libraries=libraries,
            config=source_config(),
            summary=summary,
            refresh_info=status,
            storage_display=storage_display,
            json_inventory=json_inventory,
        )

    @app.get('/path/overview/export.xlsx')
    def overview_export_excel():
        from ai_lib_qor.reporting.work_overview_excel import render_work_overview_excel
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'workspace_overview.xlsx'
            render_work_overview_excel(work, out, overwrite=True)
            data = out.read_bytes()
        return send_file(
            BytesIO(data),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='ai_lib_qor_workspace_overview.xlsx',
        )

    @app.get('/path/library')
    def library_page():
        vendor, library, folder = scope()
        index, error = index_state(vendor, library, folder)
        revision = request.args.get('revision', '')
        baseline = request.args.get('baseline', '')
        members = []
        removed = []
        delivery_rows = []
        member_views = []
        prev_rev = None
        next_rev = None
        baseline_rev = None
        rev_idx = -1
        if index:
            if revision and revision not in index['revisions']:
                abort(400)
            if not revision and index['revisions']:
                revision = index['revisions'][-1]
            if revision:
                rev_idx = index['revisions'].index(revision)
                prev_rev = index['revisions'][rev_idx - 1] if rev_idx > 0 else None
                next_rev = index['revisions'][rev_idx + 1] if rev_idx < len(index['revisions']) - 1 else None
            if baseline == '__none__':
                baseline_rev = None
            elif baseline:
                if baseline not in index['revisions'] or index['revisions'].index(baseline) >= rev_idx:
                    abort(400)
                baseline_rev = baseline
            else:
                baseline_rev = prev_rev

            for view, group in index['views'].items():
                for path, row in group.items():
                    for entry in row['effective']:
                        if entry['revision'] == revision:
                            diff_status = 'NEW' if baseline_rev else 'CURRENT'
                            if baseline_rev:
                                prev_entry = next((e for e in row['effective'] if e['revision'] == baseline_rev), None)
                                if prev_entry:
                                    diff_status = 'INHERITED' if prev_entry['version'] == entry['version'] else 'UPDATED'
                            members.append({'view': view, 'relative_path': path, 'diff_status': diff_status, **entry})
                    old = next((e for e in row['effective'] if e['revision'] == baseline_rev), None) if baseline_rev else None
                    if old and not any(e['revision'] == revision for e in row['effective']):
                        removed.append({'view': view, 'relative_path': path, **old})
            member_views = sorted({m['view'] for m in members} | {r['view'] for r in removed})
            diff_counts = {
                'NEW': sum(1 for m in members if m['diff_status'] == 'NEW'),
                'UPDATED': sum(1 for m in members if m['diff_status'] == 'UPDATED'),
                'INHERITED': sum(1 for m in members if m['diff_status'] == 'INHERITED'),
                'REMOVED': len(removed),
            }
            diff_counts['CHANGED'] = diff_counts['NEW'] + diff_counts['UPDATED'] + diff_counts['REMOVED']
            for delivery in index['deliveries']:
                kinds = {}
                count = 0
                for kind, group in index['views'].items():
                    for row in group.values():
                        if any(entry['version'] == delivery['version'] for entry in row['raw']):
                            count += 1
                            kinds[kind] = kinds.get(kind, 0) + 1
                delivery_rows.append({**delivery, 'file_count': count, 'view_counts': kinds})
        else:
            diff_counts = {'NEW': 0, 'UPDATED': 0, 'INHERITED': 0, 'REMOVED': 0, 'CHANGED': 0}

        artifacts = []
        for path in sorted([*folder.glob('check_run_*.json'), *(folder / 'log').glob('check_rev_*_run_*.json')], key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if path.is_symlink():
                continue
            try:
                d = json.loads(path.read_text(encoding='utf-8'))
                if d.get('schema_version') == 'check_result.path.v1':
                    report = path.with_suffix('.xlsx').name if path.parent.name == 'log' else 'report_' + d['run_id'] + '.xlsx'
                    from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
                    verdict = evaluate_check_verdict(d)
                    failed_checks = verdict['failed_checks']
                    inconclusive_checks = verdict['inconclusive_checks']
                    failed_files = verdict['failed_files']
                    run_state = d.get('state', 'UNKNOWN')
                    q_code, q_cls, q_text = verdict['code'], verdict['cls'], verdict['text']
                    facts_files = sorted({Path(f['facts']).name for f in d.get('files', []) if f.get('facts')})
                    artifacts.append({
                        'kind': 'SINGLE',
                        'name': report,
                        'check': path.name,
                        'revision': d['revision'],
                        'baseline': d.get('baseline'),
                        'run_at': d.get('run_at', ''),
                        'run_state': run_state,
                        'quality_code': q_code,
                        'quality_cls': q_cls,
                        'quality_text': q_text,
                        'failed_checks': failed_checks,
                        'inconclusive_checks': inconclusive_checks,
                        'failed_files': failed_files,
                        'facts_files': facts_files,
                        'label': d['revision'] + ' · 运行 ' + run_state + ' · 失败 ' + str(failed_checks) + ' · 无结论 ' + str(inconclusive_checks) + ' · 文件失败 ' + str(failed_files),
                        'excel_cached': (path.parent / report).is_file(),
                        'available': (path.parent / report).is_file() or path.parent.name == 'log',
                    })
            except (OSError, ValueError, KeyError):
                continue
        for path in sorted([*folder.glob('overall_run_*.xlsx'), *(folder / 'log').glob('overall_run_*.xlsx')], key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if not path.is_symlink():
                artifacts.append({
                    'kind': 'OVERALL',
                    'name': path.name,
                    'label': '整体报告 · ' + path.name,
                    'overall_json': path.with_suffix('.json').name if path.with_suffix('.json').is_file() and not path.with_suffix('.json').is_symlink() else None,
                    'available': True,
                })
        audit_available = any(p.is_file() and not p.is_symlink() for p in (folder / 'effective_operations.tsv', folder / 'log/effective_operations.tsv'))
        latest_check = None
        latest_path = folder / 'latest_check.json'
        if latest_path.is_symlink():
            try:
                target = latest_path.resolve(strict=True)
                if target.is_relative_to(folder.resolve()) and target.is_file():
                    row = json.loads(target.read_text(encoding='utf-8'))
                    if (row.get('vendor'), row.get('library')) == (vendor, library):
                        latest_check = {'revision': row['revision'], 'run_at': row['run_at'], 'name': target.name}
            except (OSError, ValueError, KeyError):
                pass
        matched_check = latest_check_for_scope(work, vendor, library, revision, baseline_rev) if index and revision else None
        if matched_check:
            fmap = matched_check['files']
            for m in members:
                info = fmap.get((m['view'], m['relative_path']))
                if info:
                    m.update(info)
        try:
            acceptance = acceptance_status(work, vendor, library, limit=10)
        except (OSError, ValueError):
            acceptance = None
        unadopted = unadopted_new_files(work, vendor, library, sample_limit=10)
        try:
            from ai_lib_qor.application.minimal_file_index import index_manifest_matches
            idx_path = folder / 'file_index.json'
            if idx_path.is_symlink() or not idx_path.is_file():
                lib_idx_status = 'MISSING'
            else:
                matched_m, manifest_m = index_manifest_matches(work, vendor, library, fast=True)
                lib_idx_status = 'FRESH' if matched_m else ('UNVERIFIED' if manifest_m is None else 'STALE')
            _, last_by_layer, verifications, index_attempts = read_refresh_history(work, limit=0)
            key = (vendor, library)
            single_lib_item = {
                'vendor': vendor,
                'library': library,
                'formal_count': len([p for p in archive_files(folder, 'formal', 'formal_*.json') if not p.is_symlink()]),
                'index_status': lib_idx_status,
                'source_verifications': verifications.get(key, {}),
                'index_attempt': index_attempts.get(key),
            }
            library_json_inventory = _collect_json_inventory(
                work,
                {'last_by_layer': last_by_layer},
                [single_lib_item],
                include_workspace=False,
                filters=request.args,
            )
        except (OSError, ValueError, TypeError):
            library_json_inventory = None
        return render_template(
            'path_library.html',
            vendor=vendor,
            library=library,
            index=index,
            error=error,
            revision=revision,
            members=members,
            removed=removed,
            diff_counts=diff_counts,
            delivery_rows=delivery_rows,
            artifacts=artifacts,
            audit_available=audit_available,
            member_views=member_views,
            prev_rev=prev_rev,
            next_rev=next_rev,
            baseline_rev=baseline_rev,
            rev_idx=rev_idx,
            latest_check=latest_check,
            matched_check=matched_check,
            acceptance=acceptance,
            unadopted_new_files=unadopted,
            library_json_inventory=library_json_inventory,
        )

    @app.get('/path/index')
    def index_page():
        from ai_lib_qor.application.formal_comparison import compare_formal_member, latest_formal_snapshot
        vendor, library, folder = scope()
        index, error = index_state(vendor, library, folder)
        query = request.args.get('q', '').strip()
        view = request.args.get('view', '')
        delivery = request.args.get('delivery', '')
        nl_version = request.args.get('nl_version', '')
        adoption = request.args.get('adoption', '')
        nl_rel = request.args.get('nl_rel', '')
        rows = []
        views = []
        nl_versions = []
        revision = request.args.get('revision', '')
        if index:
            views = sorted(index['views'])
            nl_versions = sorted({n['nl_version'] for n in index['nl_snapshots']})
            if nl_version and nl_version not in nl_versions:
                abort(400)
            if not nl_version and index['nl_snapshots']:
                nl_version = index['nl_snapshots'][-1]['nl_version']
            latest = latest_formal_snapshot(index, nl_version or None)
            if delivery and delivery not in [d['version'] for d in index['deliveries']]:
                abort(400)
            if view and view not in views:
                abort(400)
            if revision and revision not in index['revisions']:
                abort(400)
            if adoption not in ('', 'adopted', 'unadopted'):
                abort(400)
            if nl_rel not in ('', '来源相同', '来源不同', '无法确认', '无法对照', '最新快照未观察到', '尚无 Formal 快照'):
                abort(400)
            if not revision and index['revisions']:
                revision = index['revisions'][-1]
            for kind, group in index['views'].items():
                if view and kind != view:
                    continue
                for path, history in group.items():
                    if delivery and not any(r['version'] == delivery for r in history['raw']):
                        continue
                    if query:
                        hay = (kind + ' ' + path + ' ' + ' '.join(r['version'] for r in history['raw'])).casefold()
                        if query.casefold() not in hay:
                            continue
                    effective_in_rev = None
                    if revision:
                        effective_in_rev = next((e for e in history['effective'] if e['revision'] == revision), None)
                    if adoption == 'adopted' and not effective_in_rev:
                        continue
                    if adoption == 'unadopted' and effective_in_rev:
                        continue
                    nl_latest, nl_relation = compare_formal_member(latest, history['nl'], effective_in_rev)
                    if nl_rel and nl_relation != nl_rel:
                        continue
                    rows.append({'view': kind, 'path': path, 'effective_in_rev': effective_in_rev, 'nl_latest': nl_latest, 'nl_relation': nl_relation, **history})
        try:
            page = max(1, int(request.args.get('page', '1')))
        except ValueError:
            abort(400)
        total = len(rows)
        pages = max(1, (total + 79) // 80)
        page = min(page, pages)
        rows = rows[(page - 1) * 80 : page * 80]
        return render_template(
            'path_index.html',
            vendor=vendor,
            library=library,
            index=index,
            error=error,
            rows=rows,
            views=views,
            view=view,
            q=query,
            delivery=delivery,
            nl_version=nl_version,
            nl_versions=nl_versions,
            adoption=adoption,
            nl_rel=nl_rel,
            page=page,
            pages=pages,
            total=total,
            revision=revision,
        )

    @app.get('/path/check/view')
    def check_view_page():
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            view_data = build_check_view(work, vendor, library, name)
        except ValueError:
            abort(404)
        return render_template('path_analysis.html', mode='check', vendor=vendor, library=library, data=view_data)

    @app.get('/path/facts/view')
    def facts_view_page():
        from ai_lib_qor.reporting.qor_views import build_facts_view, load_fact_object, paginate_facts_view
        vendor, library, _ = scope()
        name = request.args.get('name', '') or None
        check_name = request.args.get('check', '') or None
        ref = request.args.get('ref', '') or None
        try:
            fact, label, _ = load_fact_object(work, vendor, library, name=name, check=check_name, ref=ref)
            entity_page = int(request.args.get('entity_page', '1'))
            pin_page = int(request.args.get('pin_page', '1'))
            per_page = int(request.args.get('per_page', '100'))
        except ValueError:
            abort(404)
        raw_view = build_facts_view(fact, label=label)
        view_data = paginate_facts_view(
            raw_view,
            q=request.args.get('q', ''),
            direction=request.args.get('direction', ''),
            use=request.args.get('use', ''),
            entity_page=entity_page,
            pin_page=pin_page,
            per_page=per_page,
        )
        return render_template('path_analysis.html', mode='facts', vendor=vendor, library=library, data=view_data, check_name=check_name, fact_ref=ref, fact_name=name)

    @app.get('/path/facts/compare')
    def facts_compare_page():
        from ai_lib_qor.reporting.qor_views import build_facts_diff, load_fact_object, paginate_facts_diff
        vendor, library, _ = scope()
        check_name = request.args.get('check', '') or None
        old_ref = request.args.get('old', '') or None
        new_ref = request.args.get('new', '') or None
        if not old_ref or not new_ref:
            abort(400)
        try:
            old_fact, old_label, _ = load_fact_object(work, vendor, library, name=None if check_name else old_ref, check=check_name, ref=old_ref if check_name else None)
            new_fact, new_label, _ = load_fact_object(work, vendor, library, name=None if check_name else new_ref, check=check_name, ref=new_ref if check_name else None)
            raw_diff = build_facts_diff(old_fact, new_fact, old_label=old_label, new_label=new_label)
            pin_page = int(request.args.get('pin_page', '1'))
            per_page = int(request.args.get('per_page', '100'))
        except ValueError:
            abort(404)
        diff = paginate_facts_diff(
            raw_diff,
            q=request.args.get('q', ''),
            status=request.args.get('status', 'auto'),
            pin_page=pin_page,
            per_page=per_page,
        )
        return render_template('path_analysis.html', mode='compare', vendor=vendor, library=library, data=diff, check_name=check_name, old_ref=old_ref, new_ref=new_ref)

    @app.get('/path/facts/download')
    def facts_download():
        from ai_lib_qor.reporting.qor_views import load_fact_object
        vendor, library, _ = scope()
        name = request.args.get('name', '') or None
        check_name = request.args.get('check', '') or None
        ref = request.args.get('ref', '') or None
        try:
            fact, label, _ = load_fact_object(work, vendor, library, name=name, check=check_name, ref=ref)
        except ValueError:
            abort(404)
        filename = label if label.endswith('.json') else label + '.json'
        payload = json.dumps(fact, ensure_ascii=False, indent=2).encode('utf-8')
        return send_file(BytesIO(payload), mimetype='application/json', as_attachment=True, download_name=filename)

    @app.get('/path/artifact')
    def artifact():
        vendor, library, folder = scope()
        name = request.args.get('name', '')
        if not re.fullmatch(
            r'(?:report_run_[a-f0-9]{32}\.xlsx|overall_run_[a-f0-9]{32}\.(?:xlsx|json)|check_run_[a-f0-9]{32}\.json|check_rev_[0-9]+_run_[a-f0-9]{32}\.(?:xlsx|json)|facts_[A-Z]+_[A-Za-z0-9_]+\.json|file_index\.json|effective_operations\.tsv|file_index_reconciliation\.tsv|formal_observations\.tsv)',
            name,
        ):
            abort(400)
        if (folder / 'log').is_symlink():
            abort(400)
        path = folder / 'log' / name if (folder / 'log' / name).is_file() else folder / name
        if not path.is_file() and re.fullmatch(r'check_rev_[0-9]+_run_[a-f0-9]{32}\.xlsx', name):
            json_path = folder / 'log' / (Path(name).stem + '.json')
            target_xlsx = folder / 'log' / name
            if json_path.is_file() and not json_path.is_symlink() and not target_xlsx.is_symlink():
                from ai_lib_qor.reporting.check_renderer import render_excel_from_check
                try:
                    if not target_xlsx.is_file():
                        render_excel_from_check(work, vendor, library, json_path.name, target_xlsx)
                except (OSError, ValueError, KeyError, TypeError):
                    abort(404)
                path = target_xlsx
        if not path.is_file() and name == 'formal_observations.tsv' and (work / name).is_file():
            path = work / name
        if path.is_symlink() or not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=name)
