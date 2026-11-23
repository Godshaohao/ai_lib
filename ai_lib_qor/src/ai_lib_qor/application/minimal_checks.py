"""Thin pluggable QoR check orchestrator with atomic evidence+report publication and fixed point-in-time report context."""
import hashlib
import json
import os
from pathlib import Path
import uuid

from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, describe_check_note, resolve_path_plugins, run_path_plugins
from ai_lib_qor.facts.parsers import _file_digest, parser_signature, supported_views
from ai_lib_qor.sources.layout import library_folder, storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.runtime import check_cancel, emit_progress
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .facts_pool import (
    hydrate_fact as _hydrate_fact,
    load_check_bundle,
    load_raw_observations as _load_raw_observations,
    read_pool as _read_pool,
    resolve_check_file as _resolve_check_file,
    write_pool_atomic as _write_pool_atomic,
)
from .minimal_facts import _stat_key, build_facts

_DIFF_ONLY_PLUGINS = {'LEF_MACRO_DIFF', 'VERILOG_PARTIAL_DIFF', 'NETLIST_PARTIAL_DIFF'}


def _fresh(work, vendor, library):
    from .path_query import PathDataQuery
    return library_folder(work, vendor, library), PathDataQuery(work).index(vendor, library)


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
    """Backward-compatible wrapper delegating to reporting.check_renderer.render_excel_from_check."""
    from ai_lib_qor.reporting.check_renderer import render_excel_from_check as _impl
    return _impl(work, vendor, library, check_filename, excel_path=excel_path)


def render_overall_excel_from_saved(work, vendor, library, overall_filename, excel_path=None):
    """Backward-compatible wrapper delegating to reporting.check_renderer.render_overall_excel_from_saved."""
    from ai_lib_qor.reporting.check_renderer import render_overall_excel_from_saved as _impl
    return _impl(work, vendor, library, overall_filename, excel_path=excel_path)


def _default_overall_renderer(work, vendor, library, rows, excel_path):
    from ai_lib_qor.reporting.check_renderer import render_overall_excel_rows
    return render_overall_excel_rows(work, vendor, library, rows, excel_path)


def _archive_unchanged(work, vendor, library, folder, index, start_stat, *, already_locked=False):
    """Fast stat-first mid-run archive drift check; escalates to full index comparison only if stat changed."""
    from .minimal_file_index import _archive_stat_summary
    from .path_query import PathDataQuery
    try:
        if start_stat is not None and _archive_stat_summary(work, vendor, library, folder / 'file_index.json') == start_stat:
            return True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if already_locked:
        current = PathDataQuery(work)._index_locked(vendor, library)
    else:
        _, current = _fresh(work, vendor, library)
    return current == index


def _run(
    work,
    vendor,
    library,
    revision,
    cache,
    *,
    baseline=None,
    plugins=None,
    render=True,
    single_renderer=None,
    progress_cb=None,
    cancel_event=None,
    _verified=None,
):
    from .path_query import PathDataQuery, build_check_context_from_index
    check_cancel(cancel_event, f'检查 {vendor}/{library} {revision} 已终止')
    if _verified is not None:
        folder, index, start_stat = _verified
    else:
        folder = library_folder(work, vendor, library)
        index, start_stat = PathDataQuery(work).index(vendor, library, _return_stat=True)
    context = build_check_context_from_index(vendor, library, index, revision, baseline=baseline)
    parent = context['baseline']
    target = {(row['view'], row['path']): {'version': row['version'], 'path': row['absolute_path']} for row in context['members']}
    baseline_map = {(row['view'], row['path']): row['baseline'] for row in context['members'] if row['baseline']}

    run = 'run_' + uuid.uuid4().hex
    rows = []
    facts = {}
    evidence = {}
    used_parser_sigs = {}
    # Stage every referenced pool blob in memory so publication writes pool + CheckResult under one shared locked(folder) boundary.
    used_pool_blobs = {}
    parseable = set(supported_views())
    raw_obs = _load_raw_observations(folder)
    deliveries_by_ver = {}
    for d in index['deliveries']:
        deliveries_by_ver.setdefault(d['version'], []).append(d)
    pool_mem = {}

    def obtain(view, path, source):
        key = (view, path, source['version'])
        if key in cache:
            p, data, pointer, expected, digest, pool_rel, pool_path, pool_data = cache[key]
            actual = Path(data['source']['absolute_path'])
            if _stat_key(actual) != expected:
                raise ValueError('本次运行中的来源文件发生变化，不能复用事实')
            evidence[str(p)] = pointer
            used_pool_blobs[pool_rel] = (pool_path, pool_data)
            used_parser_sigs[view] = parser_signature(view, allow_pg=True)
            return p, data

        source_version = source['version']
        if view not in parseable:
            raise ValueError('此 View 暂不支持 FileFacts 解析')
        matches = deliveries_by_ver.get(source_version, [])
        if len(matches) != 1:
            raise ValueError('来源版本不唯一')
        root = Path(matches[0]['root']).resolve(strict=True)
        absolute = Path(source['path'])
        real = absolute.resolve(strict=True)
        if not real.is_relative_to(root) or not real.is_file() or real != absolute:
            raise ValueError('RAW 文件不存在、越界或包含符号链接')
        recorded = raw_obs.get((source_version, path))
        if recorded is not None:
            st = real.stat()
            if (st.st_size, st.st_mtime_ns) != recorded:
                raise ValueError('RAW 文件相对首次观察已变化，不能当作历史文件解析')
        before = _stat_key(real)
        digest = _file_digest(real)
        if _stat_key(real) != before:
            raise ValueError('读取 RAW 文件时发生变化')

        sig = parser_signature(view, allow_pg=True)
        pool_hash = hashlib.sha256(f'{sig}|{digest}'.encode('utf-8')).hexdigest()[:16]
        pool_filename = f'fact_ca_{view}_{pool_hash}.json.gz'
        pool_rel = f'facts/{pool_filename}'
        pool_dir = storage_dir(folder, 'facts')
        pool_path = pool_dir / pool_filename

        pool_data = pool_mem.get(pool_rel)
        if pool_data is None and pool_path.is_file() and not pool_path.is_symlink():
            candidate = _read_pool(folder, pool_rel)
            if (
                not isinstance(candidate, dict)
                or candidate.get('source_sha256') != digest
                or candidate.get('parser_sig') != sig
                or candidate.get('view') != view
                or not isinstance(candidate.get('objects'), dict)
            ):
                raise ValueError(f'Facts 共享池记录与来源不一致: {pool_rel}')
            pool_data = candidate
            pool_mem[pool_rel] = pool_data

        if pool_data is not None:
            if _stat_key(real) != before:
                raise ValueError('事实复用核验期间文件变化')
            data = {
                'schema_version': 'file_facts.path.v1',
                'source': {
                    'vendor': vendor,
                    'library': library,
                    'version': source_version,
                    'relative_path': path,
                    'absolute_path': str(absolute),
                    'historical_content': 'UNVERIFIED',
                },
                'selection': {'kind': 'DELIVERY', 'value': source_version},
                'parsed_at': utc_text(),
                'view': pool_data['view'],
                'parser': pool_data['parser'],
                'parse_status': pool_data['parse_status'],
                'covered_sections': pool_data['covered_sections'],
                'units': pool_data['units'],
                'objects': pool_data['objects'],
            }
        else:
            result = build_facts(
                work,
                vendor,
                library,
                view,
                path,
                version=source_version,
                _capture=True,
                _in_memory=True,
                _index=index,
                _raw_obs=raw_obs,
                _precomputed_stamp=(before, digest),
            )
            data = result['_facts']
            actual = Path(data['source']['absolute_path'])
            before, digest = result['_source_stamp']
            if _stat_key(actual) != before:
                raise ValueError('事实复用核验期间文件变化')
            pool_data = {
                'schema_version': 'file_facts_pool.v1',
                'source_sha256': digest,
                'parser_sig': sig,
                'view': data['view'],
                'parser': data['parser'],
                'parse_status': data['parse_status'],
                'covered_sections': data['covered_sections'],
                'units': data['units'],
                'objects': data['objects'],
            }
            pool_mem[pool_rel] = pool_data

        p = Path('fact_' + uuid.uuid4().hex)
        pointer = {
            'storage': 'CONTENT_ADDRESSED_POOL',
            'schema_version': data['schema_version'],
            'pool_file': pool_rel,
            'source_sha256': digest,
            'view': data['view'],
            'source': data['source'],
            'selection': data['selection'],
            'parsed_at': data['parsed_at'],
            'parser': data['parser'],
            'parse_status': data['parse_status'],
            'covered_sections': data['covered_sections'],
            'units': data['units'],
        }
        cache[key] = (p, data, pointer, before, digest, pool_rel, pool_path, pool_data)
        evidence[str(p)] = pointer
        used_pool_blobs[pool_rel] = (pool_path, pool_data)
        used_parser_sigs[view] = sig
        return p, data

    target_items = sorted(target.items())
    total_files = len(target_items)
    for f_idx, ((view, path), source) in enumerate(target_items, 1):
        check_cancel(cancel_event, f'解析 {view} {path} 前任务已终止')
        emit_progress(progress_cb, 'PARSE', f'处理 {revision} 文件 {view} {path} ({f_idx}/{total_files})', completed=f_idx - 1, total=total_files)
        row = {
            'view': view,
            'path': path,
            'version': source['version'],
            'absolute_path': source['path'],
            'status': 'NOT_CHECKED',
            'facts': None,
            'note': '暂不支持此 View 的解析',
        }
        if view in parseable:
            try:
                fp, fact = obtain(view, path, source)
                facts[(view, path)] = (fp, fact)
                row.update(
                    status='PARSED',
                    facts=str(fp),
                    note=('部分解析；' if fact['parse_status'] == 'PARTIAL' else '') + '仅覆盖 ' + ', '.join(fact['covered_sections']),
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                row.update(status='FAILED', note=f'{type(exc).__name__}: {exc}')
        rows.append(row)

    plugin_ctx = {
        'work': work,
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'baseline_revision': parent,
        'target': target,
        'baseline': baseline_map,
        'facts': facts,
        'obtain': obtain,
    }
    out = run_path_plugins(plugin_ctx, plugins=plugins)
    checks = list(out['checks'])
    comparisons = out['comparisons']
    partial_comparisons = out['partial_comparisons']
    changes = out['changes']
    plugins_executed = out['plugins_executed']
    executed_plugin_versions = out['plugin_versions']
    plugin_produced = out.get('plugin_produced')
    if not isinstance(plugin_produced, dict):
        has_any = bool(checks or comparisons or partial_comparisons)
        plugin_produced = {pname: has_any for pname in plugins_executed}

    # Record truthful per-plugin coverage; never allow an explicitly requested (or baseline-suppressed)
    # unexecuted plugin to be silently hidden behind another plugin's PASS.
    explicit_plugins = plugins is not None
    explicit_no_baseline = baseline == '__none__'
    target_views = {v for v, _ in target}
    any_plugin_produced = bool(checks or comparisons or partial_comparisons or any(plugin_produced.values()))
    plugin_coverage = {}
    for pname in plugins_executed:
        if plugin_produced.get(pname, False):
            plugin_coverage[pname] = 'EXECUTED'
            continue
        meta = PATH_CHECK_PLUGIN_META.get(pname, {})
        req_views = set(meta.get('required_views') or ())
        req_baseline = bool(meta.get('requires_baseline', pname in _DIFF_ONLY_PLUGINS))
        must_report_unexecuted = (
            explicit_plugins
            or not any_plugin_produced
            or (explicit_no_baseline and req_baseline and (not req_views or bool(req_views & target_views)))
        )
        if must_report_unexecuted:
            plugin_coverage[pname] = 'NOT_EXECUTED'
            if parent is None and req_baseline:
                reason = '未指定对比基线，该跨版本对比规则未实际执行'
            elif req_views and not (req_views & target_views):
                reason = f'当前版本范围缺少所需视图（{"/".join(sorted(req_views))}），该检查规则未实际执行'
            else:
                reason = '当前版本范围未命中可执行对象或基线成员，该检查规则未实际执行'
            checks.append({
                'check_id': pname,
                'scope_file_keys': [],
                'result': 'INCONCLUSIVE',
                'coverage': 'UNKNOWN',
                'facts_refs': [],
                'detail': reason,
            })
        else:
            plugin_coverage[pname] = 'NOT_APPLICABLE'

    state = (
        'PARTIAL'
        if any(r['status'] != 'PARSED' for r in rows)
        or any(f['parse_status'] != 'COMPLETE' for _, f in facts.values())
        or any(c['result'] == 'INCONCLUSIVE' for c in checks)
        or any(v == 'NOT_EXECUTED' for v in plugin_coverage.values())
        or not (checks or comparisons or partial_comparisons)
        else 'SUCCEEDED'
    )
    parsed_views = {v for (v, _), (_, f) in facts.items() if f.get('parse_status') == 'COMPLETE'}
    partial_views = {v for (v, _), (_, f) in facts.items() if f.get('parse_status') == 'PARTIAL'}
    not_checked_views = {r['view'] for r in rows if r['status'] == 'NOT_CHECKED'}
    dynamic_note = describe_check_note(
        plugins_executed,
        parsed_views=parsed_views,
        partial_views=partial_views,
        not_checked_views=not_checked_views,
        plugin_coverage=plugin_coverage,
    )
    run_at = utc_text()
    nl_snaps = index.get('nl_snapshots') or []
    formal_snapshot_ids = [snapshot['snapshot_id'] for snapshot in nl_snaps]
    report = {
        'schema_version': 'check_result.path.v1',
        'run_id': run,
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'baseline': parent,
        'run_at': run_at,
        'state': state,
        'files': rows,
        'checks': checks,
        'comparisons': comparisons,
        'partial_comparisons': partial_comparisons,
        'changes': changes,
        'summary': {
            'failed_checks': sum(x['result'] == 'FAIL' for x in checks),
            'inconclusive_checks': sum(x['result'] == 'INCONCLUSIVE' for x in checks),
            'failed_files': sum(x['status'] == 'FAILED' for x in rows),
            'files_with_new_source': sum(x['baseline_version'] != x['version'] for x in comparisons),
            'files_with_confirmed_content_change': sum(x['content_status'] == 'CURRENT_CONTENT_DIFF' for x in comparisons),
        },
        'facts_evidence': evidence,
        'tooling': {
            'parser_signatures': dict(sorted(used_parser_sigs.items())),
            'plugins': plugins_executed,
            'plugin_versions': dict(sorted(executed_plugin_versions.items())),
            'plugin_coverage': plugin_coverage,
        },
        'report_context': {
            'captured_at': run_at,
            'deliveries': [d['version'] for d in (index.get('deliveries') or [])],
            'revisions': list(index.get('revisions') or []),
            'nl_observed_cutoff': nl_snaps[-1].get('observed_at') if nl_snaps else None,
            'formal_snapshots': formal_snapshot_ids,
        },
        'note': dynamic_note,
    }
    validate(report, 'check_result_path')
    log = storage_dir(folder, 'log')
    stem = f'check_{revision}_{run}'
    check = log / (stem + '.json')
    excel = log / (stem + '.xlsx')
    check_rel = str(check.relative_to(folder))

    # Shared atomic publication boundary under locked(folder):
    # guarantees clean_cache(--orphan-facts) can NEVER delete pool files belonging to an in-flight CheckResult.
    with locked(folder):
        if not _archive_unchanged(work, vendor, library, folder, index, start_stat, already_locked=True):
            raise ValueError('检查期间归档发生变化')
        for _, (pool_path, pool_data) in sorted(used_pool_blobs.items()):
            _write_pool_atomic(pool_path, pool_data)
        write_atomic(check, report, immutable=True)
        update_pointer(folder, 'latest_check.json', check_rel)
        # Keep latest_check.json and latest_check.xlsx strictly paired: remove stale xlsx pointer until/unless rendered for THIS run.
        latest_xlsx_ptr = folder / 'latest_check.xlsx'
        if latest_xlsx_ptr.is_symlink():
            latest_xlsx_ptr.unlink()
        _append_run(log, {
            'type': 'CHECK',
            'run_id': run,
            'revision': revision,
            'baseline': parent,
            'plugins': plugins_executed,
            'state': state,
            'time': report['run_at'],
            'json': check_rel,
            'excel': str(excel.relative_to(folder)) if render else None,
        })

    if render:
        renderer = single_renderer or render_excel_from_check
        renderer(work, vendor, library, check.name, excel)
        if excel.is_file():
            with locked(folder):
                # Only update latest_check.xlsx if latest_check.json still points to THIS exact check run.
                latest_json_ptr = folder / 'latest_check.json'
                if latest_json_ptr.is_symlink() and os.readlink(latest_json_ptr) == check_rel:
                    update_pointer(folder, 'latest_check.xlsx', str(excel.relative_to(folder)))

    return {'state': state, 'revision': revision, 'run_id': run, 'check': str(check), 'excel': str(excel) if render else None}


def _append_run(log, event):
    path = log / 'runs.jsonl'
    if path.is_symlink():
        raise ValueError('运行日志不能为软链接')
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def run_revision(work, vendor, library, revision, *, baseline=None, plugins=None, render=True, single_renderer=None, progress_cb=None, cancel_event=None):
    return _run(
        work,
        vendor,
        library,
        revision,
        {},
        baseline=baseline,
        plugins=plugins,
        render=render,
        single_renderer=single_renderer,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )


def run_library(
    work,
    vendor,
    library,
    *,
    revisions=None,
    rerun=False,
    plugins=None,
    render_single_excel=True,
    single_renderer=None,
    overall_renderer=None,
    progress_cb=None,
    cancel_event=None,
):
    from .path_query import PathDataQuery, find_latest_check
    folder = library_folder(work, vendor, library)
    index, start_stat = PathDataQuery(work).index(vendor, library, _return_stat=True)
    available = index['revisions']
    if revisions is not None and (not revisions or len(set(revisions)) != len(revisions) or not set(revisions) <= set(available)):
        raise ValueError('版本选择无效')
    selected = [x for x in available if revisions is None or x in revisions]
    if not selected:
        raise ValueError('没有可检查的有效版本')
    expected_plugins = [name for name, _ in resolve_path_plugins(plugins)] if plugins is not None else None
    log = storage_dir(folder, 'log')
    cache = {}
    runs = []
    rows = []
    total_revs = len(selected)
    for r_idx, revision in enumerate(selected, 1):
        check_cancel(cancel_event, f'库级检查 {vendor}/{library} 在 {revision} 处已终止')
        emit_progress(progress_cb, 'CHECK', f'库级检查 {vendor}/{library} · {revision} ({r_idx}/{total_revs})', completed=r_idx - 1, total=total_revs)
        if not _archive_unchanged(work, vendor, library, folder, index, start_stat):
            raise ValueError('整体运行期间归档发生变化')
        if rerun:
            run = _run(
                work,
                vendor,
                library,
                revision,
                cache,
                plugins=plugins,
                render=render_single_excel,
                single_renderer=single_renderer,
                cancel_event=cancel_event,
                _verified=(folder, index, start_stat),
            )
        else:
            hit = find_latest_check(work, vendor, library, revision=revision, plugins=expected_plugins)
            run = (
                {
                    'revision': hit['revision'],
                    'state': hit['state'],
                    'run_id': hit['run_id'],
                    'check': hit['check_path'],
                    'excel': hit['excel_path'],
                }
                if hit
                else None
            )
        pos = available.index(revision)
        default_base = available[pos - 1] if pos > 0 else None
        if not run:
            member_cnt, src_add, src_chg, src_rem = _index_source_deltas(index, revision, default_base)
            runs.append({'revision': revision, 'state': 'NOT_CHECKED', 'run_id': None, 'check': None, 'excel': None})
            rows.append({
                'revision': revision,
                'baseline': default_base,
                'run_id': '',
                'state': 'NOT_CHECKED',
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
        runs.append(run)
        check = json.loads(Path(run['check']).read_text(encoding='utf-8'))
        member_cnt, src_add, src_chg, src_rem = _index_source_deltas(index, revision, check['baseline'])
        rows.append({
            'revision': revision,
            'baseline': check['baseline'],
            'run_id': run['run_id'],
            'run_at': check.get('run_at', ''),
            'state': run['state'],
            'plan': '路径式有效版本检查',
            'summary': check['summary'],
            'checks': check['checks'],
            'comparisons': check.get('comparisons') or [],
            'partial_comparisons': check.get('partial_comparisons') or [],
            'changes': check.get('changes') or [],
            'tooling': check.get('tooling') or {},
            'facts_evidence': check.get('facts_evidence') or {},
            'parsed_files': sum(1 for f in check.get('files', []) if f.get('status') == 'PARSED'),
            'member_count': member_cnt,
            'index_source_added': src_add,
            'index_source_changes': src_chg,
            'index_source_removed': src_rem,
            'note': check['note'] + '；复用历史结果，不代表当前来源已重新验证' if not rerun else check['note'],
            'error': f"解析失败 {check['summary']['failed_files']} 个文件" if check['summary']['failed_files'] else None,
            'comparison_count': len(check['comparisons']),
        })
    data = {'vendor': vendor, 'library': library, 'versions': runs}
    ident = 'run_' + uuid.uuid4().hex
    out = log / f'overall_{ident}.json'
    excel = log / f'overall_{ident}.xlsx'
    write_atomic(out, data, immutable=True)
    ov_renderer = overall_renderer or _default_overall_renderer
    ov_renderer(work, vendor, library, rows, excel)
    state = 'SUCCEEDED' if all(x['state'] == 'SUCCEEDED' for x in runs) else 'PARTIAL'
    with locked(folder):
        update_pointer(folder, 'latest_overall.xlsx', str(excel.relative_to(folder)))
        _append_run(log, {
            'type': 'OVERALL',
            'run_id': ident,
            'revisions': selected,
            'state': state,
            'time': utc_text(),
            'json': str(out.relative_to(folder)),
            'excel': str(excel.relative_to(folder)),
            'rerun': rerun,
        })
    return {'state': state, 'overall': str(out), 'excel': str(excel), 'versions': runs}
