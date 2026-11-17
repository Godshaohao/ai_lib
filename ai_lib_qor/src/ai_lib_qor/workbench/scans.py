"""Configured, immutable scan observations for the workbench."""
import json
from pathlib import Path
from ai_lib_qor.sources.update_scan import scan_library, compare_scans
from ai_lib_qor.versions.store import write_atomic


def sources(work):
    if not work: return []
    path=Path(work)/'scan_sources.json'
    if not path.is_file() or path.is_symlink(): return []
    data=json.loads(path.read_text(encoding='utf-8'))['sources']
    if not isinstance(data,list): raise ValueError('来源配置格式错误')
    pairs=[(x['vendor_id'],x['source_library_id']) for x in data]
    if len(pairs)!=len(set(pairs)): raise ValueError('扫描来源重复')
    return data


def observations(runs, source):
    result=[]
    for path in (Path(runs)/'scans').glob('scan_*.json'):
        if path.is_symlink(): continue
        try:
            row=json.loads(path.read_text(encoding='utf-8'))
            if (row.get('vendor_id'),row.get('source_library_id'),row.get('root')) == (source['vendor_id'],source['source_library_id'],str(Path(source['root']).resolve())): result.append(row)
        except (OSError,ValueError,KeyError): continue
    return sorted(result,key=lambda x:x['started_at'],reverse=True)


def run_scan(runs, source):
    raw=Path(source['root']).resolve()
    if Path(runs).resolve().is_relative_to(raw): raise ValueError('扫描输出目录不能位于 RAW 中')
    prior=observations(runs,source)
    row=scan_library(raw,source['vendor_id'],source['source_library_id'],metadata_only=True)
    previous=next((x for x in prior if x['status']=='COMPLETE' and x.get('comparison_method')=='size_mtime_ns'),None)
    row['previous_scan_id']=previous['scan_id'] if previous else None
    row['changes']=compare_scans(previous,row) if previous and row['status']=='COMPLETE' else None
    write_atomic(Path(runs)/'scans'/f"{row['scan_id']}.json",row,immutable=True)
    return row


def run_scan_and_ingest(runs, work, source):
    row = run_scan(runs, source)
    result = {'scan_id':row['scan_id'], 'created':0, 'duplicates':0, 'modified':0, 'blocked':0, 'reasons':[]}
    if row['status'] != 'COMPLETE':
        result['blocked'] = 1; result['reasons'].append('扫描未完整完成，不发布交付')
    else:
        try:
            from ai_lib_qor.sources.classifier_adapter import classify_observation
            result['classified'] = classify_observation(row, source)['files']
            if not source.get('version_paths'):
                result['blocked'] = 1; result['reasons'].append('未配置可确认的版本目录，已保留扫描观察')
            else:
                from ai_lib_qor.sources.auto_ingest import auto_ingest
                result.update(auto_ingest(work, source, row))
        except (OSError, ValueError, KeyError, ImportError) as exc:
            result['blocked'] = 1; result['reasons'].append(str(exc))
    write_atomic(Path(runs)/'ingest'/f"{row['scan_id']}.json", result, immutable=True)
    return row


def ingest_result(runs, scan):
    if not scan: return None
    path = Path(runs)/'ingest'/f"{scan['scan_id']}.json"
    if not path.is_file() or path.is_symlink(): return None
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
