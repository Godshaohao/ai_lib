"""Configured, immutable metadata scan observations and optional source ingestion."""
import json
from collections import defaultdict
from pathlib import Path
from ai_lib_qor.sources.update_scan import scan_library, compare_scans
from ai_lib_qor.versions.store import write_atomic
from ai_lib_qor.sources.source_discovery import load_scan_sources


def sources(work):
    return load_scan_sources(work)


def observations(runs, source):
    result = []
    for path in (Path(runs) / 'scans').glob('scan_*.json'):
        if path.is_symlink():
            continue
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if (row.get('vendor_id'), row.get('source_library_id'), row.get('root')) == (
                    source['vendor_id'], source['source_library_id'], str(Path(source['root']).resolve())):
                result.append(row)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(result, key=lambda r: r['started_at'], reverse=True)


def observation_index(runs):
    """Read each saved scan once; index by the same identity as observations()."""
    result=defaultdict(list)
    for path in (Path(runs)/'scans').glob('scan_*.json'):
        if path.is_symlink(): continue
        try:
            row=json.loads(path.read_text(encoding='utf-8'))
            key=(row.get('vendor_id'),row.get('source_library_id'),row.get('root'))
            if not row.get('started_at'):continue
            result[key].append(row)
        except (OSError,ValueError,KeyError,AttributeError,TypeError):continue
    for rows in result.values(): rows.sort(key=lambda r:r['started_at'],reverse=True)
    return result


def run_scan(runs, source):
    raw = Path(source['root']).resolve()
    if Path(runs).resolve().is_relative_to(raw):
        raise ValueError('扫描输出目录不能位于 RAW 中')
    history = observations(runs, source)
    row = scan_library(raw, source['vendor_id'], source['source_library_id'], metadata_only=True)
    previous = next((x for x in history if x['status'] == 'COMPLETE' and x.get('comparison_method') == 'size_mtime_ns'), None)
    row['previous_scan_id'] = previous['scan_id'] if previous else None
    row['changes'] = compare_scans(previous, row) if previous and row['status'] == 'COMPLETE' else None
    write_atomic(Path(runs) / 'scans' / f"{row['scan_id']}.json", row, immutable=True)
    return row


def run_scan_and_ingest(runs, work, source, *, progress=None):
    if progress:progress('正在读取 RAW 文件元数据')
    row = run_scan(runs, source)
    result = {'scan_id': row['scan_id'], 'created': 0, 'duplicates': 0,
              'modified': 0, 'blocked': 0, 'reasons': []}
    if row['status'] != 'COMPLETE':
        result['blocked'] = 1
        result['reasons'].append('扫描未完整完成，不发布交付')
        from ai_lib_qor.application.latest_pointers import refresh_library
        refresh_library(work,source['vendor_id'],source['source_library_id'])
    else:
        try:
            from ai_lib_qor.sources.classifier_adapter import classify_observation
            from ai_lib_qor.sources.auto_ingest import auto_ingest
            if progress:progress(f"已扫描 {len(row['files'])} 个文件，正在分类")
            classified = classify_observation(row, source)
            # File-level metadata can be large; keep it separate from the small
            # status record loaded by the global page on every request.
            write_atomic(Path(runs) / 'classified' / f"{row['scan_id']}.json", classified, immutable=True)
            result['classified_count'] = len(classified['files'])
            if progress:progress('正在核验版本并登记交付')
            result.update(auto_ingest(work, source, row, classified=classified))
        except (OSError, ValueError, KeyError, ImportError) as exc:
            result['blocked'] += 1
            result['reasons'].append(str(exc))
    write_atomic(Path(runs) / 'ingest' / f"{row['scan_id']}.json", result, immutable=True)
    return row


def ingest_result(runs, scan):
    if not scan:
        return None
    path = Path(runs) / 'ingest' / f"{scan['scan_id']}.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
