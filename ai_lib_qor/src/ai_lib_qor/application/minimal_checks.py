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
from ai_lib_qor.sources.raw_paths import observed_raw_file, read_raw_observations
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.runtime import check_cancel, emit_progress, get_hook
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .facts_pool import (
    hydrate_fact as _hydrate_fact,
    load_check_bundle,
    read_pool as _read_pool,
    resolve_check_file as _resolve_check_file,
    write_pool_atomic as _write_pool_atomic,
)
from .minimal_facts import _stat_key, build_facts
from .path_acceptance import report_cache_is_current

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
    """Backward-compatible wrapper delegating via composition-root hook (no upward reporting import)."""
    impl = get_hook('reporting.render_excel_from_check')
    if impl is None:
        raise RuntimeError('未注册 reporting.render_excel_from_check 渲染器')
    return impl(work, vendor, library, check_filename, excel_path=excel_path)


def render_overall_excel_from_saved(work, vendor, library, overall_filename, excel_path=None):
    """Backward-compatible wrapper delegating via composition-root hook (no upward reporting import)."""
    impl = get_hook('reporting.render_overall_excel_from_saved')
    if impl is None:
        raise RuntimeError('未注册 reporting.render_overall_excel_from_saved 渲染器')
    return impl(work, vendor, library, overall_filename, excel_path=excel_path)


def _next_dated_stem(log_dir: Path, base_prefix: str, date_str: str, *, sep: str = '_') -> tuple[str, str]:
    """Allocate clean `(stem, run_id)` as `<base_prefix><sep><YYYYMMDD>` (appending `_2`, `_3` only on same-day collision)."""
    candidate_id = date_str
    stem = f'{base_prefix}{sep}{candidate_id}'
    if not (log_dir / f'{stem}.json').exists() and not (log_dir / f'{stem}.xlsx').exists():
        return stem, candidate_id
    seq = 2
    while True:
        candidate_id = f'{date_str}_{seq}'
        stem = f'{base_prefix}{sep}{candidate_id}'
        if not (log_dir / f'{stem}.json').exists() and not (log_dir / f'{stem}.xlsx').exists():
            return stem, candidate_id
        seq += 1


def _check_semantic_signature(report: dict) -> dict:
    """Canonical semantic projection of CheckResult (ignoring run_id/run_at/random fact aliases) for dedup reuse."""
    ev = report.get('facts_evidence') or {}

    def _ref_key(ref):
        if not ref:
            return None
        info = ev.get(str(ref))
        if isinstance(info, dict):
            src = info.get('source') or {}
            return (
                info.get('pool_file') or info.get('source_sha256') or str(ref),
                info.get('view'),
                src.get('version'),
                src.get('relative_path'),
            )
        return str(ref)

    def _norm(obj):
        if isinstance(obj, dict):
            return {
                k: ([_ref_key(r) for r in v] if k == 'facts_refs' and isinstance(v, list) else _norm(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_norm(item) for item in obj]
        return obj

    files_sig = [
        (f.get('view'), f.get('path'), f.get('version'), f.get('status'), f.get('note'), _ref_key(f.get('facts')))
        for f in (report.get('files') or [])
    ]
    rc = report.get('report_context') or {}
    rc_sig = {
        'deliveries': rc.get('deliveries'),
        'revisions': rc.get('revisions'),
        'nl_observed_cutoff': rc.get('nl_observed_cutoff'),
        'formal_snapshots': rc.get('formal_snapshots'),
    }
    return {
        'vendor': report.get('vendor'),
        'library': report.get('library'),
        'business_ip': report.get('business_ip'),
        'ip_type': report.get('ip_type'),
        'revision': report.get('revision'),
        'baseline': report.get('baseline'),
        'state': report.get('state'),
        'files': files_sig,
        'checks': _norm(report.get('checks') or []),
        'comparisons': _norm(report.get('comparisons') or []),
        'partial_comparisons': _norm(report.get('partial_comparisons') or []),
        'changes': _norm(report.get('changes') or []),
        'summary': report.get('summary') or {},
        'tooling': report.get('tooling') or {},
        'report_context': rc_sig,
        'note': report.get('note') or '',
    }


def _overall_semantic_signature(data: dict) -> dict:
    versions = []
    for row in data.get('versions') or []:
        chk = row.get('check')
        versions.append((
            row.get('revision'),
            row.get('state'),
            row.get('run_id'),
            Path(chk).name if chk else None,
        ))
    return {
        'vendor': data.get('vendor'),
        'library': data.get('library'),
        'business_ip': data.get('business_ip'),
        'ip_type': data.get('ip_type'),
        'versions': versions,
    }


def _find_latest_overall_json(log_dir: Path, business_ip) -> Path | None:
    if not log_dir.is_dir() or log_dir.is_symlink():
        return None
    if business_ip is not None:
        cands = [p for p in log_dir.glob(f'overall__{business_ip}__*.json') if p.is_file() and not p.is_symlink()]
    else:
        cands = [
            p for p in log_dir.glob('overall_*.json')
            if p.is_file() and not p.is_symlink() and not p.name.startswith('overall__')
        ]
    if not cands:
        return None
    cands.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    return cands[0]


def _default_overall_renderer(work, vendor, library, rows, excel_path, *, business_ip=None, ip_type=None):
    impl = get_hook('reporting.render_overall_excel_rows')
    if impl is None:
        raise RuntimeError('未注册 reporting.render_overall_excel_rows 渲染器')
    return impl(
        work,
        vendor,
        library,
        rows,
        excel_path,
        business_ip=business_ip,
        ip_type=ip_type,
    )


def _archive_unchanged(
    work,
    vendor,
    library,
    folder,
    index,
    start_stat,
    *,
    already_locked=False,
    business_ip=None,
    start_track_stat=None,
):
    """Fast stat-first mid-run archive drift check (covers both physical file_index and multi-track Effective files)."""
    from .minimal_file_index import _archive_stat_summary
    from .path_query import PathDataQuery, track_effective_stat
    if business_ip is not None and start_track_stat is not None:
        try:
            if track_effective_stat(folder, library, business_ip) != start_track_stat:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
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
    business_ip=None,
    plugins=None,
    render=True,
    single_renderer=None,
    progress_cb=None,
    cancel_event=None,
    _verified=None,
):
    from .minimal_effective import _norm_business_ip
    from .path_config import library_ip_config
    from .path_query import PathDataQuery, build_check_context_from_index, build_track_index_view
    ip = _norm_business_ip(business_ip)
    check_cancel(cancel_event, f'检查 {vendor}/{library} {revision} 已终止')
    if _verified is not None:
        if len(_verified) == 6:
            folder, physical_index, start_stat, index, eff_ip_type, start_track_stat = _verified
        else:
            folder, physical_index, start_stat = _verified
            index, eff_ip_type, start_track_stat = physical_index, None, []
    else:
        folder = library_folder(work, vendor, library)
        physical_index, start_stat = PathDataQuery(work).index(vendor, library, _return_stat=True)
        ip_cfg = library_ip_config(work, vendor, library)
        if ip is not None:
            index, eff_ip_type, start_track_stat = build_track_index_view(folder, vendor, library, physical_index, ip)
            if eff_ip_type is None:
                eff_ip_type = ip_cfg['ip_type']
        else:
            if ip_cfg['is_multi_track'] and not physical_index.get('revisions'):
                raise ValueError('该库已启用多业务 IP 分轨，请通过 --ip / business_ip 指定目标业务 IP 轨道')
            index, eff_ip_type, start_track_stat = physical_index, ip_cfg['ip_type'], []
    from .ip_partition import active_tracks_for_library
    from .path_config import excluded_versions
    excl_vers = excluded_versions(work, vendor, library)
    if ip is not None:
        tinfo = active_tracks_for_library(work, vendor, library)
        allowed_vers = set((tinfo.get('tracks') or {}).get(ip) or []) - excl_vers
        # Always include delivery versions already committed into this track's effective revisions.
        for grp in (index.get('views') or {}).values():
            for row in grp.values():
                for eff_row in row.get('effective') or []:
                    if eff_row.get('version'):
                        allowed_vers.add(eff_row['version'])
    else:
        allowed_vers = {d['version'] for d in (index.get('deliveries') or [])} - excl_vers

    context = build_check_context_from_index(
        vendor,
        library,
        index,
        revision,
        baseline=baseline,
        business_ip=ip,
        ip_type=eff_ip_type,
        allowed_versions=allowed_vers,
    )
    parent = context['baseline']
    target = {(row['view'], row['path']): {'version': row['version'], 'path': row['absolute_path']} for row in context['members']}
    baseline_map = {(row['view'], row['path']): row['baseline'] for row in context['members'] if row['baseline']}

    run = 'pending'
    rows = []
    facts = {}
    evidence = {}
    used_parser_sigs = {}
    # Stage every referenced pool blob in memory so publication writes pool + CheckResult under one shared locked(folder) boundary.
    used_pool_blobs = {}
    parseable = set(supported_views())
    raw_obs = read_raw_observations(folder)
    deliveries_by_ver = {}
    for d in index['deliveries']:
        deliveries_by_ver.setdefault(d['version'], []).append(d)
    pool_mem = {}

    def obtain(view, path, source):
        key = (view, path, source['version'])
        if key in cache:
            p, data, pointer, expected, digest, pool_rel, pool_path, pool_data = cache[key]
            recorded = raw_obs.get((source['version'], path))
            actual = observed_raw_file(deliveries_by_ver[source['version']][0]['root'], path, Path(source['path']), recorded)
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
        absolute = Path(source['path'])
        real = observed_raw_file(matches[0]['root'], path, absolute, raw_obs.get((source_version, path)))
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
            recorded = raw_obs.get((source['version'], path))
            actual = observed_raw_file(deliveries_by_ver[source['version']][0]['root'], path, Path(source['path']), recorded)
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

    from .path_config import liberty_filter_evidence, liberty_parse_filter, select_liberty_files, skip_parse_views
    skipped_views_list = skip_parse_views(work, vendor, library)
    skipped_views = set(skipped_views_list)
    skipped_view_counts: dict[str, int] = {}
    lib_policy = liberty_parse_filter(work, vendor, library)
    lib_selection = select_liberty_files(
        [] if 'LIBERTY' in skipped_views else [p for (v, p) in target if v == 'LIBERTY'],
        lib_policy,
    )
    selected_lib_paths = set(lib_selection['selected'])
    lib_skip_note = None
    if lib_selection['applied']:
        kw_desc = f"，关键词: {', '.join(lib_selection['keywords'])}" if lib_selection['keywords'] else ''
        lib_skip_note = (
            f"已按 liberty_parse_filter 跳过（LIBERTY 共 {lib_selection['total_liberty_files']} 个 > 阈值 "
            f"{lib_selection['threshold']}；抽样解析 {lib_selection['selected_count']} 个{kw_desc}）"
        )

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
        if view in skipped_views:
            row['note'] = f'已按 skip_parse_views 配置跳过解析（当前暂不处理 {view}）'
            skipped_view_counts[view] = skipped_view_counts.get(view, 0) + 1
        elif view == 'LIBERTY' and lib_selection['applied'] and path not in selected_lib_paths:
            row['note'] = lib_skip_note
        elif view in parseable:
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

    from .path_config import effective_check_plugins, effective_plugin_params
    resolved_plugins = effective_check_plugins(
        work,
        vendor,
        library,
        ip_type=eff_ip_type,
        explicit_plugins=plugins,
    )
    plugin_params = effective_plugin_params(work, vendor, library, ip_type=eff_ip_type)
    plugin_ctx = {
        'work': work,
        'vendor': vendor,
        'library': library,
        'business_ip': ip,
        'ip_type': eff_ip_type,
        'track_id': f'{vendor}/{library}::{ip}' if ip is not None else None,
        'revision': revision,
        'baseline_revision': parent,
        'target': target,
        'baseline': baseline_map,
        'facts': facts,
        'obtain': obtain,
        'plugin_params': plugin_params,
        'explicit_plugins': plugins is not None,
    }
    out = run_path_plugins(plugin_ctx, plugins=resolved_plugins)
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
        needs_facts = bool(meta.get('needs_facts', True))
        must_report_unexecuted = (
            explicit_plugins
            or not any_plugin_produced
            or (explicit_no_baseline and req_baseline and (not req_views or bool(req_views & target_views)))
        )
        if must_report_unexecuted:
            plugin_coverage[pname] = 'NOT_EXECUTED'
            if parent is None and req_baseline:
                reason = '未指定对比基线，该跨版本对比规则未实际执行'
            elif needs_facts and req_views and (req_views <= skipped_views):
                reason = f'所需视图（{"/".join(sorted(req_views))}）已按 skip_parse_views 配置跳过解析，该检查规则未实际执行'
            elif req_views and not (req_views & target_views):
                reason = f'当前版本范围缺少所需视图（{"/".join(sorted(req_views))}），该检查规则未实际执行'
            else:
                reason = '当前版本范围未命中可执行对象、验收配置或基线成员，该检查规则未实际执行'
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
    if lib_selection['applied'] and 'LIBERTY' in parsed_views:
        not_checked_views.discard('LIBERTY')
    dynamic_note = describe_check_note(
        plugins_executed,
        parsed_views=parsed_views,
        partial_views=partial_views,
        not_checked_views=not_checked_views,
        plugin_coverage=plugin_coverage,
    )
    if lib_selection['applied']:
        if lib_selection['fallback_used']:
            lf_note = (
                f"LIBERTY 共 {lib_selection['total_liberty_files']} 个超过阈值 {lib_selection['threshold']}，"
                f"未命中关键词（{'、'.join(lib_selection['keywords'])}），已按回退策略抽样解析前 "
                f"{lib_selection['selected_count']} 个、跳过 {lib_selection['skipped_count']} 个（NOT_CHECKED）"
            )
        elif lib_selection['keywords']:
            lf_note = (
                f"LIBERTY 共 {lib_selection['total_liberty_files']} 个超过阈值 {lib_selection['threshold']}，"
                f"按关键词（{'、'.join(lib_selection['keywords'])}）抽样解析 {lib_selection['selected_count']} 个、"
                f"跳过 {lib_selection['skipped_count']} 个（NOT_CHECKED）"
            )
        else:
            lf_note = (
                f"LIBERTY 共 {lib_selection['total_liberty_files']} 个超过阈值 {lib_selection['threshold']}，"
                f"按上限抽样解析 {lib_selection['selected_count']} 个、跳过 {lib_selection['skipped_count']} 个（NOT_CHECKED）"
            )
        dynamic_note = f'{lf_note}；{dynamic_note}'
    if skipped_view_counts:
        skip_parts = '/'.join(f'{v}({c})' for v, c in sorted(skipped_view_counts.items()))
        skip_total = sum(skipped_view_counts.values())
        dynamic_note = f'已按 skip_parse_views 跳过 {skip_parts} 共 {skip_total} 个文件的解析（NOT_CHECKED）；{dynamic_note}'
    if parent == '__prev_file__':
        dynamic_note = f'按 file_index 同轨文件时间序对照各自上一时间交付版本；{dynamic_note}'
    run_at = utc_text()
    nl_snaps = index.get('nl_snapshots') or []
    formal_snapshot_ids = [snapshot['snapshot_id'] for snapshot in nl_snaps]
    tooling_block = {
        'parser_signatures': dict(sorted(used_parser_sigs.items())),
        'plugins': plugins_executed,
        'plugin_versions': dict(sorted(executed_plugin_versions.items())),
        'plugin_coverage': plugin_coverage,
    }
    if skipped_views_list:
        tooling_block['skipped_views'] = skipped_views_list
    sampling_evidence = liberty_filter_evidence(lib_selection)
    if sampling_evidence is not None:
        tooling_block['liberty_filter'] = sampling_evidence
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
        'tooling': tooling_block,
        'report_context': {
            'captured_at': run_at,
            'deliveries': [d['version'] for d in (index.get('deliveries') or [])],
            'revisions': list(index.get('revisions') or []),
            'nl_observed_cutoff': nl_snaps[-1].get('observed_at') if nl_snaps else None,
            'formal_snapshots': formal_snapshot_ids,
        },
        'note': dynamic_note,
    }
    if ip is not None:
        report['business_ip'] = ip
        report['ip_type'] = eff_ip_type
        report['track_id'] = f'{vendor}/{library}::{ip}'
    log = storage_dir(folder, 'log')
    latest_json_name = f'latest_check__{ip}.json' if ip is not None else 'latest_check.json'
    latest_xlsx_name = f'latest_check__{ip}.xlsx' if ip is not None else 'latest_check.xlsx'
    date_str = run_at[:10].replace('-', '')
    base_prefix = f'check__{ip}__{revision}' if ip is not None else f'check_{library}_{revision}'
    candidate_sig = _check_semantic_signature(report)
    reused = False

    # Shared atomic publication boundary under locked(folder):
    # 1) Content-idempotent reuse: if the newest saved check for this exact scope has identical semantic payload,
    #    reuse it instead of generating duplicate garbage files.
    # 2) Guarantees clean_cache(--orphan-facts) can NEVER delete pool files belonging to an in-flight CheckResult.
    from .path_query import find_latest_check
    with locked(folder):
        if not _archive_unchanged(
            work,
            vendor,
            library,
            folder,
            physical_index,
            start_stat,
            already_locked=True,
            business_ip=ip,
            start_track_stat=start_track_stat,
        ):
            raise ValueError('检查期间归档发生变化')

        existing_hit = find_latest_check(
            work,
            vendor,
            library,
            revision=revision,
            baseline=parent,
            plugins=plugins_executed,
            business_ip=ip,
        )
        matched_existing = None
        if existing_hit and existing_hit.get('check_path'):
            ex_path = Path(existing_hit['check_path'])
            if ex_path.parent.resolve() == log.resolve() and ex_path.is_file() and not ex_path.is_symlink():
                try:
                    ex_report = json.loads(ex_path.read_text(encoding='utf-8'))
                    if _check_semantic_signature(ex_report) == candidate_sig:
                        matched_existing = (ex_path, ex_report)
                except (OSError, ValueError, TypeError):
                    matched_existing = None

        if matched_existing is not None:
            check, ex_report = matched_existing
            run = ex_report['run_id']
            excel = check.with_suffix('.xlsx')
            check_rel = str(check.relative_to(folder))
            for _, (pool_path, pool_data) in sorted(used_pool_blobs.items()):
                _write_pool_atomic(pool_path, pool_data)
            update_pointer(folder, latest_json_name, check_rel)
            if report_cache_is_current(folder, excel, ip):
                update_pointer(folder, latest_xlsx_name, str(excel.relative_to(folder)))
            else:
                latest_xlsx_ptr = folder / latest_xlsx_name
                if latest_xlsx_ptr.is_symlink():
                    latest_xlsx_ptr.unlink()
            reused = True
        else:
            stem, run = _next_dated_stem(log, base_prefix, date_str)
            report['run_id'] = run
            validate(report, 'check_result_path')
            check = log / (stem + '.json')
            excel = log / (stem + '.xlsx')
            check_rel = str(check.relative_to(folder))
            for _, (pool_path, pool_data) in sorted(used_pool_blobs.items()):
                _write_pool_atomic(pool_path, pool_data)
            write_atomic(check, report, immutable=True)
            update_pointer(folder, latest_json_name, check_rel)
            # Keep latest_check.json and latest_check.xlsx strictly paired: remove stale xlsx pointer until/unless rendered for THIS run.
            latest_xlsx_ptr = folder / latest_xlsx_name
            if latest_xlsx_ptr.is_symlink():
                latest_xlsx_ptr.unlink()
            run_event = {
                'type': 'CHECK',
                'run_id': run,
                'revision': revision,
                'baseline': parent,
                'plugins': plugins_executed,
                'state': state,
                'time': report['run_at'],
                'json': check_rel,
                'excel': str(excel.relative_to(folder)) if render else None,
            }
            if ip is not None:
                run_event['business_ip'] = ip
                run_event['ip_type'] = eff_ip_type
                run_event['track_id'] = f'{vendor}/{library}::{ip}'
            _append_run(log, run_event)

    if render and not (reused and report_cache_is_current(folder, excel, ip)):
        renderer = single_renderer or render_excel_from_check
        renderer(work, vendor, library, check.name, excel)
        if excel.is_file():
            with locked(folder):
                # Only update latest_check.xlsx if latest_check.json still points to THIS exact check run.
                latest_json_ptr = folder / latest_json_name
                if latest_json_ptr.is_symlink() and os.readlink(latest_json_ptr) == check_rel:
                    update_pointer(folder, latest_xlsx_name, str(excel.relative_to(folder)))

    ret = {
        'state': state,
        'revision': revision,
        'run_id': run,
        'check': str(check),
        'excel': str(excel) if render else None,
        'reused': reused,
    }
    if ip is not None:
        ret['business_ip'] = ip
        ret['ip_type'] = eff_ip_type
        ret['track_id'] = f'{vendor}/{library}::{ip}'
    return ret


def _append_run(log, event):
    path = log / 'runs.jsonl'
    if path.is_symlink():
        raise ValueError('运行日志不能为软链接')
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def run_revision(work, vendor, library, revision, *, baseline=None, business_ip=None, plugins=None, render=True, single_renderer=None, progress_cb=None, cancel_event=None):
    return _run(
        work,
        vendor,
        library,
        revision,
        {},
        baseline=baseline,
        business_ip=business_ip,
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
    business_ip=None,
    rerun=False,
    plugins=None,
    render_single_excel=True,
    single_renderer=None,
    overall_renderer=None,
    progress_cb=None,
    cancel_event=None,
):
    from .minimal_effective import _norm_business_ip
    from .path_config import library_ip_config
    from .path_query import PathDataQuery, build_track_index_view, find_latest_check
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    physical_index, start_stat = PathDataQuery(work).index(vendor, library, _return_stat=True)
    ip_cfg = library_ip_config(work, vendor, library)
    if ip is not None:
        index, eff_ip_type, start_track_stat = build_track_index_view(folder, vendor, library, physical_index, ip)
        if eff_ip_type is None:
            eff_ip_type = ip_cfg['ip_type']
    else:
        if ip_cfg['is_multi_track'] and not physical_index.get('revisions'):
            raise ValueError('该库已启用多业务 IP 分轨，请通过 --ip / business_ip 指定目标业务 IP 轨道')
        index, eff_ip_type, start_track_stat = physical_index, None, []
    available = index['revisions']
    if revisions is not None and (not revisions or len(set(revisions)) != len(revisions) or not set(revisions) <= set(available)):
        raise ValueError('版本选择无效')
    selected = [x for x in available if revisions is None or x in revisions]
    if not selected:
        raise ValueError('没有可检查的有效版本')
    from .path_config import effective_check_plugins
    resolved_plugins = effective_check_plugins(work, vendor, library, ip_type=eff_ip_type, explicit_plugins=plugins)
    expected_plugins = [name for name, _ in resolve_path_plugins(resolved_plugins)] if resolved_plugins is not None else None
    log = storage_dir(folder, 'log')
    cache = {}
    runs = []
    rows = []
    total_revs = len(selected)
    for r_idx, revision in enumerate(selected, 1):
        check_cancel(cancel_event, f'库级检查 {vendor}/{library} 在 {revision} 处已终止')
        emit_progress(progress_cb, 'CHECK', f'库级检查 {vendor}/{library} · {revision} ({r_idx}/{total_revs})', completed=r_idx - 1, total=total_revs)
        if not _archive_unchanged(
            work,
            vendor,
            library,
            folder,
            physical_index,
            start_stat,
            business_ip=ip,
            start_track_stat=start_track_stat,
        ):
            raise ValueError('整体运行期间归档发生变化')
        if rerun:
            run = _run(
                work,
                vendor,
                library,
                revision,
                cache,
                business_ip=ip,
                plugins=plugins,
                render=render_single_excel,
                single_renderer=single_renderer,
                cancel_event=cancel_event,
                _verified=(folder, physical_index, start_stat, index, eff_ip_type, start_track_stat),
            )
        else:
            hit = find_latest_check(work, vendor, library, revision=revision, plugins=expected_plugins, business_ip=ip)
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
    if ip is not None:
        data['business_ip'] = ip
        data['ip_type'] = eff_ip_type
        data['track_id'] = f'{vendor}/{library}::{ip}'
    state = 'SUCCEEDED' if all(x['state'] == 'SUCCEEDED' for x in runs) else 'PARTIAL'
    latest_ov_name = f'latest_overall__{ip}.xlsx' if ip is not None else 'latest_overall.xlsx'
    ov_sig = _overall_semantic_signature(data)
    ov_reused = False
    with locked(folder):
        prev_ov = _find_latest_overall_json(log, ip)
        if prev_ov is not None:
            try:
                prev_data = json.loads(prev_ov.read_text(encoding='utf-8'))
                if _overall_semantic_signature(prev_data) == ov_sig:
                    out = prev_ov
                    excel = prev_ov.with_suffix('.xlsx')
                    ov_reused = True
            except (OSError, ValueError, TypeError):
                ov_reused = False
        if not ov_reused:
            ov_date = utc_text()[:10].replace('-', '')
            if ip is not None:
                ov_stem, ident = _next_dated_stem(log, f'overall__{ip}', ov_date, sep='__')
            else:
                ov_stem, ident = _next_dated_stem(log, f'overall_{library}', ov_date, sep='_')
            out = log / f'{ov_stem}.json'
            excel = log / f'{ov_stem}.xlsx'
            write_atomic(out, data, immutable=True)
    if not report_cache_is_current(folder, excel, ip, include_latest=True):
        if overall_renderer is None:
            _default_overall_renderer(work, vendor, library, rows, excel, business_ip=ip, ip_type=eff_ip_type)
        else:
            import inspect
            sig = inspect.signature(overall_renderer)
            if 'business_ip' in sig.parameters:
                overall_renderer(work, vendor, library, rows, excel, business_ip=ip, ip_type=eff_ip_type)
            else:
                overall_renderer(work, vendor, library, rows, excel)
    with locked(folder):
        update_pointer(folder, latest_ov_name, str(excel.relative_to(folder)))
        if not ov_reused:
            ov_event = {
                'type': 'OVERALL',
                'run_id': ident,
                'revisions': selected,
                'state': state,
                'time': utc_text(),
                'json': str(out.relative_to(folder)),
                'excel': str(excel.relative_to(folder)),
                'rerun': rerun,
            }
            if ip is not None:
                ov_event['business_ip'] = ip
                ov_event['ip_type'] = eff_ip_type
                ov_event['track_id'] = f'{vendor}/{library}::{ip}'
            _append_run(log, ov_event)
    ret = {'state': state, 'overall': str(out), 'excel': str(excel), 'versions': runs, 'reused': ov_reused}
    if ip is not None:
        ret['business_ip'] = ip
        ret['ip_type'] = eff_ip_type
        ret['track_id'] = f'{vendor}/{library}::{ip}'
    return ret
