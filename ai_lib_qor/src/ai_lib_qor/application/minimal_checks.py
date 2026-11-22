"""Thin pluggable QoR check orchestrator with separated data persistence and report rendering."""
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import uuid

from ai_lib_qor.checks.path_plugins import run_path_plugins
from ai_lib_qor.facts.parsers import _file_digest, parser_signature, supported_views
from ai_lib_qor.sources.layout import library_folder, log_file, storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .minimal_facts import _stat_key, build_facts


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


def _write_pool_atomic(path, payload):
    """Write an immutable content-addressed gzipped JSON fact object atomically."""
    if path.is_symlink():
        raise ValueError('事实共享池文件不能为软链接')
    if path.is_file():
        return
    blob = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
        compresslevel=6,
    )
    tmp = path.parent / f'.{path.name}.{uuid.uuid4().hex}.tmp'
    try:
        with tmp.open('wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_pool(folder, pool_rel):
    if not isinstance(pool_rel, str) or not pool_rel or pool_rel.startswith('/') or '..' in Path(pool_rel).parts:
        raise ValueError('事实共享池路径无效')
    facts_dir = folder / 'facts'
    if facts_dir.is_symlink():
        raise ValueError('事实共享池目录不能为软链接')
    target = folder / pool_rel
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
        raise ValueError('事实共享池文件不存在或越界')
    return json.loads(gzip.decompress(target.read_bytes()).decode('utf-8'))


def _hydrate_fact(folder, fact_obj, pool_cache):
    """Hydrate a lightweight content-addressed pool pointer into a full file_facts.path.v1 dict."""
    if not isinstance(fact_obj, dict):
        return None
    if fact_obj.get('storage') != 'CONTENT_ADDRESSED_POOL':
        return fact_obj
    pool_rel = fact_obj.get('pool_file')
    if pool_rel not in pool_cache:
        pool_cache[pool_rel] = _read_pool(folder, pool_rel)
    pool_data = pool_cache[pool_rel]
    return {
        'schema_version': fact_obj.get('schema_version', 'file_facts.path.v1'),
        'source': fact_obj['source'],
        'selection': fact_obj['selection'],
        'parsed_at': fact_obj['parsed_at'],
        'view': pool_data['view'],
        'parser': pool_data['parser'],
        'parse_status': pool_data['parse_status'],
        'covered_sections': pool_data['covered_sections'],
        'units': pool_data['units'],
        'objects': pool_data['objects'],
    }


def _load_raw_observations(folder):
    observation = log_file(folder, 'raw_observations.tsv')
    if observation.is_symlink():
        raise ValueError('RAW 观察记录不能为软链接')
    records = {}
    if observation.is_file():
        with observation.open(encoding='utf-8', newline='') as stream:
            for row in csv.reader(stream, delimiter='\t'):
                if len(row) != 5:
                    raise ValueError('RAW 观察记录格式无效')
                records.setdefault((row[0], row[1]), (int(row[2]), int(row[3])))
    return records


def _resolve_check_file(folder, check_filename):
    if not isinstance(check_filename, str) or '/' in check_filename or '\\' in check_filename or check_filename in ('', '.', '..'):
        raise ValueError('检查文件名不安全')
    log_path = folder / 'log' / check_filename
    root_path = folder / check_filename
    if (folder / 'log').is_symlink():
        raise ValueError('日志目录不能为软链接')
    target = log_path if log_path.is_file() else root_path
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
        raise ValueError('检查结果文件不存在')
    return target


def load_check_bundle(work, vendor, library, check_filename):
    """Read-only loader: reconstruct complete report + facts + index bundle solely from saved JSON."""
    folder, index = _fresh(work, vendor, library)
    check_path = _resolve_check_file(folder, check_filename)
    report = json.loads(check_path.read_text(encoding='utf-8'))
    validate(report, 'check_result_path')
    if (report['vendor'], report['library']) != (vendor, library):
        raise ValueError('检查结果与当前库归属不一致')

    facts_map = {}
    pool_cache = {}
    # 1. Embedded facts_evidence (supports both content-addressed pool pointers and legacy full dicts)
    for ref_id, fact_obj in (report.get('facts_evidence') or {}).items():
        if isinstance(fact_obj, dict):
            try:
                hydrated = _hydrate_fact(folder, fact_obj, pool_cache)
            except (OSError, ValueError, TypeError, KeyError):
                hydrated = None
            if hydrated is not None:
                facts_map[ref_id] = hydrated
                facts_map[Path(ref_id).name] = hydrated

    # 2. Standalone facts_*.json files referenced in files[] or facts_refs[] (legacy/external format)
    candidate_refs = [f.get('facts') for f in report.get('files', []) if f.get('facts')]
    for c in report.get('checks', []):
        candidate_refs.extend(c.get('facts_refs') or [])
    for comp in report.get('comparisons', []):
        candidate_refs.extend(comp.get('facts_refs') or [])
    for ref in candidate_refs:
        if not ref or ref in facts_map:
            continue
        name = Path(ref).name
        if name in facts_map:
            facts_map[ref] = facts_map[name]
            continue
        for base in (folder / 'log', folder):
            fp = base / name
            if fp.is_file() and not fp.is_symlink() and fp.resolve().is_relative_to(folder.resolve()):
                try:
                    data = json.loads(fp.read_text(encoding='utf-8'))
                    facts_map[ref] = data
                    facts_map[name] = data
                except (OSError, ValueError, TypeError):
                    pass
                break

    return {
        'folder': folder,
        'check_path': check_path,
        'report': report,
        'index': index,
        'facts': facts_map,
    }


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
    from ai_lib_qor.reporting.excel import render_excel
    try:
        render_excel({**report, '_path_context': {'index': bundle['index'], 'facts': bundle['facts']}}, tmp)
        os.replace(tmp, excel_path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(excel_path)


def _run(work, vendor, library, revision, cache, *, baseline=None, plugins=None, render=True, progress_cb=None, cancel_event=None):
    from .path_query import PathDataQuery
    from ai_lib_qor.workbench.jobs import check_cancel, emit_progress
    check_cancel(cancel_event, f'检查 {vendor}/{library} {revision} 已终止')
    context = PathDataQuery(work).get_check_context(vendor, library, revision, baseline=baseline)
    folder = library_folder(work, vendor, library)
    index = context['index']
    parent = context['baseline']
    target = {(row['view'], row['path']): {'version': row['version'], 'path': row['absolute_path']} for row in context['members']}
    baseline_map = {(row['view'], row['path']): row['baseline'] for row in context['members'] if row['baseline']}

    run = 'run_' + uuid.uuid4().hex
    rows = []
    facts = {}
    evidence = {}
    parseable = set(supported_views())
    raw_obs = _load_raw_observations(folder)
    deliveries_by_ver = {}
    for d in index['deliveries']:
        deliveries_by_ver.setdefault(d['version'], []).append(d)
    pool_mem = {}

    def obtain(view, path, source):
        key = (view, path, source['version'])
        if key in cache:
            p, data, pointer, expected, digest = cache[key]
            actual = Path(data['source']['absolute_path'])
            if _stat_key(actual) != expected or _file_digest(actual) != digest or _stat_key(actual) != expected:
                raise ValueError('本次运行中的来源文件发生变化，不能复用事实')
            evidence[str(p)] = pointer
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
            try:
                cand = _read_pool(folder, pool_rel)
                if (
                    isinstance(cand, dict)
                    and cand.get('source_sha256') == digest
                    and cand.get('parser_sig') == sig
                    and cand.get('view') == view
                    and isinstance(cand.get('objects'), dict)
                ):
                    pool_data = cand
                    pool_mem[pool_rel] = pool_data
            except (OSError, ValueError, TypeError, KeyError):
                pool_data = None

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
            result = build_facts(work, vendor, library, view, path, version=source_version, _capture=True, _in_memory=True)
            data = result['_facts']
            actual = Path(data['source']['absolute_path'])
            before, digest = result['_source_stamp']
            if _stat_key(actual) != before or _file_digest(actual) != digest or _stat_key(actual) != before:
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
            _write_pool_atomic(pool_path, pool_data)
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
        cache[key] = (p, data, pointer, before, digest)
        evidence[str(p)] = pointer
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
    checks = out['checks']
    comparisons = out['comparisons']
    partial_comparisons = out['partial_comparisons']
    changes = out['changes']

    _, current = _fresh(work, vendor, library)
    if current != index:
        raise ValueError('检查期间归档发生变化')

    state = (
        'PARTIAL'
        if any(r['status'] != 'PARSED' for r in rows)
        or any(f['parse_status'] != 'COMPLETE' for _, f in facts.values())
        or any(c['result'] == 'INCONCLUSIVE' for c in checks)
        else 'SUCCEEDED'
    )
    report = {
        'schema_version': 'check_result.path.v1',
        'run_id': run,
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'baseline': parent,
        'run_at': utc_text(),
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
        'note': '仅比较 LEF Macro SIZE、Pin 存在及方向并检查 LEF/Liberty 信号 Pin；VERILOG/CDL/SPICE 的接口差异仅部分解析，GDS 等未检查；当前来源不证明历史字节一致。',
    }
    validate(report, 'check_result_path')
    log = storage_dir(folder, 'log')
    stem = f'check_{revision}_{run}'
    check = log / (stem + '.json')
    excel = log / (stem + '.xlsx')
    write_atomic(check, report, immutable=True)

    # Render report strictly from the saved disk artifact (decoupled from execution state)
    if render:
        render_excel_from_check(work, vendor, library, check.name, excel)

    with locked(folder):
        update_pointer(folder, 'latest_check.json', str(check.relative_to(folder)))
        if render and excel.is_file():
            update_pointer(folder, 'latest_check.xlsx', str(excel.relative_to(folder)))
        _append_run(log, {
            'type': 'CHECK',
            'run_id': run,
            'revision': revision,
            'state': state,
            'time': report['run_at'],
            'json': str(check.relative_to(folder)),
            'excel': str(excel.relative_to(folder)) if render else None,
        })
    return {'state': state, 'revision': revision, 'run_id': run, 'check': str(check), 'excel': str(excel) if render else None}


def _append_run(log, event):
    path = log / 'runs.jsonl'
    if path.is_symlink():
        raise ValueError('运行日志不能为软链接')
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def run_revision(work, vendor, library, revision, *, baseline=None, plugins=None, render=True, progress_cb=None, cancel_event=None):
    return _run(work, vendor, library, revision, {}, baseline=baseline, plugins=plugins, render=render, progress_cb=progress_cb, cancel_event=cancel_event)


def run_library(work, vendor, library, *, revisions=None, rerun=False, plugins=None, render_single_excel=True, progress_cb=None, cancel_event=None):
    from ai_lib_qor.workbench.jobs import check_cancel, emit_progress
    folder, index = _fresh(work, vendor, library)
    available = index['revisions']
    if revisions is not None and (not revisions or len(set(revisions)) != len(revisions) or not set(revisions) <= set(available)):
        raise ValueError('版本选择无效')
    selected = [x for x in available if revisions is None or x in revisions]
    if not selected:
        raise ValueError('没有可检查的有效版本')
    log = storage_dir(folder, 'log')
    cache = {}
    runs = []
    rows = []
    existing = {}
    if not rerun:
        for path in [*folder.glob('check_run_*.json'), *log.glob('check_rev_*_run_*.json')]:
            if path.is_symlink():
                continue
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                validate(item, 'check_result_path')
                if (item['vendor'], item['library']) != (vendor, library):
                    continue
                excel = path.with_suffix('.xlsx') if path.parent == log else folder / ('report_' + item['run_id'] + '.xlsx')
                if excel.is_symlink():
                    continue
                entry = {'revision': item['revision'], 'state': item['state'], 'run_id': item['run_id'], 'check': str(path), 'excel': str(excel) if excel.is_file() else None}
                key = (item['run_at'], path.stat().st_mtime_ns, item['run_id'])
                if item['revision'] not in existing or key > existing[item['revision']][0]:
                    existing[item['revision']] = (key, entry)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    total_revs = len(selected)
    for r_idx, revision in enumerate(selected, 1):
        check_cancel(cancel_event, f'库级检查 {vendor}/{library} 在 {revision} 处已终止')
        emit_progress(progress_cb, 'CHECK', f'库级检查 {vendor}/{library} · {revision} ({r_idx}/{total_revs})', completed=r_idx - 1, total=total_revs)
        _, current = _fresh(work, vendor, library)
        if current != index:
            raise ValueError('整体运行期间归档发生变化')
        run = _run(work, vendor, library, revision, cache, plugins=plugins, render=render_single_excel, cancel_event=cancel_event) if rerun else existing.get(revision, (None, None))[1]
        if not run:
            runs.append({'revision': revision, 'state': 'NOT_CHECKED', 'run_id': None, 'check': None, 'excel': None})
            rows.append({'revision': revision, 'run_id': '', 'state': 'NOT_CHECKED', 'plan': '未执行', 'note': '无已保存的单版本检查结果', 'checks': []})
            continue
        runs.append(run)
        check = json.loads(Path(run['check']).read_text(encoding='utf-8'))
        rows.append({
            'revision': revision,
            'baseline': check['baseline'],
            'run_id': run['run_id'],
            'state': run['state'],
            'plan': '路径式有效版本检查',
            'summary': check['summary'],
            'checks': check['checks'],
            'note': check['note'] + '；复用历史结果，不代表当前来源已重新验证' if not rerun else check['note'],
            'error': f"解析失败 {check['summary']['failed_files']} 个文件" if check['summary']['failed_files'] else None,
            'comparison_count': len(check['comparisons']),
        })
    data = {'vendor': vendor, 'library': library, 'versions': runs}
    ident = 'run_' + uuid.uuid4().hex
    out = log / f'overall_{ident}.json'
    excel = log / f'overall_{ident}.xlsx'
    write_atomic(out, data, immutable=True)
    from ai_lib_qor.reporting.overall_excel import render_overall_excel
    render_overall_excel({'vendor': vendor, 'library': library}, rows, excel)
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
