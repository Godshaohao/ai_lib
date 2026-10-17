"""Exercise report-only Web jobs against an existing library, without altering it."""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

from lib_guard.atomic import atomic_write_json, atomic_write_text
from lib_guard.effective.manifest import build_effective_manifest
from lib_guard.scan.scanner import ScanRunner
from lib_guard.scan.cache import ScanCache
from lib_guard.scan.report import load_parser_results
from lib_guard.web.app import create_app
from lib_guard.web.read_model import load_web_state
from lib_guard.window.resolver import default_window_path


def stamps(roots):
    records = {}
    for root in roots:
        root = Path(root)
        for path in ([root] if root.is_file() else root.rglob('*')):
            if path.is_file():
                stat = path.stat()
                records[str(path.resolve())] = [stat.st_size, stat.st_mtime_ns]
    return records


def prepare(source, library, root, *, fresh, reuse_previous=False):
    catalog = {'libraries': [deepcopy(library)]}
    selected = catalog['libraries'][0]
    scan_runs = []
    if fresh:
        if reuse_previous:
            cache = ScanCache({'cache_dir': str(root / 'scanner_cache')})
            for version in selected['versions']:
                previous = Path(version['scan']['scan_dir'])
                inventory = json.loads((previous / 'file_inventory.json').read_text())
                for record in inventory['files']:
                    stamp = (Path(version['raw_path']) / record['path']).stat()
                    if stamp.st_size != record['size_bytes'] or abs(stamp.st_mtime - record['mtime']) > 1e-6:
                        raise ValueError('已有扫描不新鲜，不能用于本次缓存复用')
                results = load_parser_results(previous)
                tasks = json.loads((previous / 'parser_manifest.json').read_text())
                for item in tasks['files']:
                    if item['file_type'] == 'lef':
                        continue
                    for task in item['parser_tasks']:
                        if task.get('cache_key') and task.get('result_path') in results:
                            cache.put_parser_result(task['cache_key'], results[task['result_path']])
        for version in selected['versions']:
            output = root / 'scan' / version['version_id']
            started = time.perf_counter()
            runner = ScanRunner(SimpleNamespace(
                root_path=version['raw_path'], out_dir=str(output),
                library_type='ip', library_name=selected['library_name'], version=version['version_id'],
                scan_mode='scan', scan_id='WEB_EXISTING_' + version['version_id'],
                state_dir=str(root / 'scanner_state'), cache_dir=str(root / 'scanner_cache'),
                no_cache=not reuse_previous, skip_cache=not reuse_previous, no_progress=True, parse_jobs=4,
                parse_file_types=['lef', 'liberty', 'verilog'], hash_policy='none',
                tool_version='existing-web-acceptance', schema_version='1.0'))
            runner.run()
            meta = json.loads((output / 'scan_meta.json').read_text())
            if meta['status'] != 'PASS':
                raise RuntimeError(f"隔离扫描未通过：{output}")
            assert runner.stats['hashed_files'] == 0
            version['scan'] = {'status': 'SCANNED', 'scan_dir': str(output),
                               'scan_id': meta['scan_id'], 'snapshot_identity': meta['snapshot_identity']}
            scan_runs.append({'version': version['version_id'], 'seconds': round(time.perf_counter()-started, 3),
                              'stats': runner.stats, 'scan_dir': str(output)})
    catalog_path, html = root / 'catalog/catalog.json', root / 'catalog/html'
    atomic_write_json(catalog_path, catalog)
    manifest_ids = []
    window = default_window_path(html, selected, selected['library_name'])
    for version in selected['versions']:
        identity = 'snapshot_' + version['version_id']
        manifest = build_effective_manifest(catalog, selected['library_name'], version['version_id'], [], effective_id=identity)
        path = window.parent.parent / 'effective' / identity / 'effective_manifest.json'
        atomic_write_json(path, manifest)
        manifest_ids.append((identity, path))
    target_id, target_path = manifest_ids[-1]
    atomic_write_json(window, {'state': 'PENDING', 'source': 'manual',
        'candidate_effective': {'effective_id': target_id, 'manifest': str(target_path),
            'base_full': selected['versions'][-1]['version_id'], 'overlays': [], 'rule': 'manual_selection'}})
    config = root / 'lib_guard.yml'
    atomic_write_text(config, f"workspace: {root}\nraw_root: {source['paths']['raw_root']}\ncatalog: {catalog_path}\ncatalog_html: {html}\n")
    return config, manifest_ids, scan_runs


def run_case(client, app, library, payload):
    started = time.perf_counter()
    response = client.post(f'/api/libraries/{library}/semantic-review', json=payload)
    assert response.status_code == 202, response.get_json()
    job = response.get_json()
    process = app.extensions['lib_guard_jobs'][job['job_id']]
    try:
        process.wait(timeout=180)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    status = client.get('/api/runs/' + job['job_id']).get_json()
    assert status['return_code'] == 0, status
    assert not any(key in status for key in ('checks', 'delta', 'usage_decision'))
    artifacts = {item['id']: item for item in status['artifacts']}
    for item in artifacts.values():
        with client.get(item['url']) as download:
            assert download.status_code == 200
            assert 'attachment;' in download.headers.get('Content-Disposition', '')
    directory = Path(job['request']).parent
    summary = json.loads((directory / 'semantic_review/summary.json').read_text())
    details = json.loads(Path(artifacts['semantic_checks']['path']).read_text())
    assert summary['raw_content_reads'] == summary['content_hash_reads'] == 0
    index = json.loads(Path(artifacts['semantic_index']['path']).read_text())
    return {'job_id': job['job_id'], 'selection': payload, 'seconds': round(time.perf_counter()-started, 3),
        'file_count': summary['file_count'], 'macro_count': summary['macro_count'],
        'checks': summary['counts'], 'delta': summary['delta_counts'],
        'macro_states': dict(Counter(row['status'] for row in index['current'].get('macro_index', {}).get('macros', []))),
        'not_checked_reasons': dict(Counter(row['reason_code'] for row in details['checks'] if row['status'] == 'NOT_CHECKED')),
        'incomplete_by_attribute': dict(Counter(row['attribute'] for row in details['delta'] if row['status'] in {'INCOMPLETE', 'UNKNOWN'})),
        'raw_content_reads': summary['raw_content_reads'], 'content_hash_reads': summary['content_hash_reads'],
        'markdown': artifacts['markdown']['path'], 'results': artifacts['semantic_checks']['path']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-config', required=True)
    parser.add_argument('--library', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--reuse-previous-parsers', action='store_true', help='显式复用源扫描中未改变版本的非 LEF 解析结果')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = load_web_state(config_path=Path(args.source_config).resolve(), cwd=Path.cwd())
    library = next(item for item in source['catalog']['libraries'] if item['library_name'] == args.library)
    if len(library['versions']) != 2 or any(row.get('package_type') != 'FULL_PACKAGE' for row in library['versions']):
        raise ValueError('本次真实版本验收明确选择已有两个完整包；不猜测增量包或确认当前有效版。')
    protected_roots = [Path(args.source_config).resolve(), source['catalog_path'], source['catalog_path'].parent / 'catalog_runtime.json', source['catalog_html']]
    protected_roots += [Path(v['raw_path']) for v in library['versions']]
    protected_roots += [Path(v['scan']['scan_dir']) for v in library['versions']]
    before = stamps(protected_roots)
    catalog_sha = hashlib.sha256(source['catalog_path'].read_bytes()).hexdigest()
    runs, configurations, scans = [], {}, []
    for name, fresh in [('reused_evidence', False), ('current_evidence', True)]:
        config, manifests, scan_runs = prepare(source, library, out / name, fresh=fresh, reuse_previous=args.reuse_previous_parsers)
        configurations[name] = str(config)
        scans.extend(scan_runs)
        app = create_app(config_path=config, cwd=Path.cwd())
        client = app.test_client()
        options = client.get(f'/api/libraries/{args.library}/semantic-review')
        assert options.status_code == 200
        ids = [item[0] for item in manifests]
        assert {row['id'] for row in options.get_json()['targets']} == set(ids)
        plans = [('lef_basic', ids[0], None)]
        if fresh:
            plans += [('default', ids[0], None), ('ip_basic', ids[0], None),
                      ('lef_basic', '', None), ('lef_basic', ids[0], ['LEF_INTERFACE_DELTA'])]
        for profile, base, checks in plans:
            payload = {'target': ids[1], 'base': base, 'profile': profile}
            if checks is not None:
                payload['checks'] = checks
            row = run_case(client, app, args.library, payload)
            row['evidence'] = name
            runs.append(row)
    mutations = [path for path, value in before.items() if not Path(path).is_file() or [Path(path).stat().st_size, Path(path).stat().st_mtime_ns] != value]
    assert not mutations, mutations
    assert hashlib.sha256(source['catalog_path'].read_bytes()).hexdigest() == catalog_sha
    report = {'source_config': str(Path(args.source_config).resolve()), 'library': args.library,
        'versions': [row['version_id'] for row in library['versions']], 'configs': configurations,
        'explicit_isolated_scans': scans, 'runs': runs, 'protected_file_count': len(before),
        'source_metadata_changes': mutations, 'source_catalog_content_unchanged': True,
        'limitations': ['ASAP7 实际已有测试交付，不是专有 UCIE 数据。',
                        '复用旧证据与主动隔离取证分开；Web 检查任务本身不补扫。',
                        'FULL_PACKAGE 为现有目录记录，本验收不推断包类型、不确认当前有效指针。']}
    atomic_write_json(out / 'validation.json', report)
    text = ['# 现有 ASAP7 库 Web 联动验收', '', f"来源：{args.source_config}",
            f"版本：{' → '.join(report['versions'])}", '',
            '| 证据 | 方案 | 基准 | 文件 / 对象 | 检查 | 属性变化 | 报告 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for row in runs:
        cells = [row['evidence'], row['selection']['profile'], row['selection']['base'] or '无',
                 f"{row['file_count']} / {row['macro_count']}", row['checks'], row['delta'], f"[Markdown]({row['markdown']})"]
        text.append('| ' + ' | '.join(str(cell).replace('|', '\\|') for cell in cells) + ' |')
    text += ['', f"保护 {len(before)} 个文件的大小/mtime 未变；源 Catalog 内容校验相同；原扫描、HTML、有效指针未覆盖。", '',
             '本报告区分任务执行成功与规则检查完整/通过；详细原因见 validation.json 与每个 Markdown。',
             *('- ' + item for item in report['limitations'])]
    atomic_write_text(out / 'validation.md', '\n'.join(text) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
